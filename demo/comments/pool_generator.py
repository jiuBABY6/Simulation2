"""根据事件和预设人物类型生成初始评论池。

本文件只负责一件事：读取事件和 config/comment_profiles.json 中的人物类型，
调用 DeepSeek 生成评论，并保存为 comment_pool.json。

本阶段不处理 Agent 打分、公共黑板、评论传播和多轮事件更新。
"""

import argparse

# 2026/08/22 增量评论累积对齐：初始评论生成器改为复用独立的评论生成服务。
from comments.generation_service import (
    COMMENT_BATCH_SIZE,
    EMOTIONS,
    FACTIONS,
    ORIENTATIONS,
    STANCES,
    generate_valid_comment_batch,
    load_generation_profiles,
    summarize_profile_faction_combinations,
)
from comments.angle_planner import (
    build_initial_angle_tasks,
    format_comment_tasks,
    generate_event_angle_plan,
)
from infrastructure.json_storage import load_json, save_json
from project_config import (
    COMMENT_POOL_FILE,
    COMMENT_POOL_MIN_FACTION_COUNT,
    COMMENT_POOL_SIZE,
    COMMENT_PROFILE_FILE,
    EVENT_FILE,
)


# 2026/08/22 增量评论累积对齐：本文件只保留初始评论提示词和初始评论池组织逻辑。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：初始评论提示词接收程序分配的角度任务。
def build_generation_prompt(
    event_input,
    profiles,
    batch_size,
    comment_tasks=None,
):
    """构造要求大模型按人物类型生成结构化评论的提示词。"""
    event_content = event_input.get("event_content", "")
    event_labels = event_input.get("event_labels", {})
    profile_text = "\n".join(
        f"- profile_id={item['profile_id']}，profile_label={item['profile_label']}：{item['definition']}"
        for item in profiles
    )
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：提示模型逐项完成程序分配的事件角度任务。
    task_text = ""
    task_output_field = ""
    if comment_tasks is not None:
        task_text = f"""
【本批次角度任务】
{format_comment_tasks(comment_tasks)}

每个 task_id 必须恰好生成一条评论。评论必须围绕该任务的 angle_name 和 focus，
并遵循 expression_instruction 指定的表达方式，
人物类型和评论派系由你根据角度语义合理选择。
""".strip()
        task_output_field = '      "task_id": "initial_001",\n'

    return f"""
你是社会舆情模拟系统的评论池生成器。请根据事件内容，模拟不同人物类型可能发布的微博评论。

【事件内容】
{event_content}

【事件标签】
{event_labels}

【可使用的人物类型】
{profile_text}

{task_text}

【生成要求】
1. 本次生成 {batch_size} 条评论，每条评论必须来自上面某一个人物类型。
2. 尽量平均覆盖不同人物类型，也要覆盖五种评论派系、三种情绪和三种信息取向。
3. 评论必须围绕当前事件，不得编造事件中没有提供的具体事实、姓名、数字或时间。
4. 评论使用自然的中文微博表达，长度控制在 15 至 100 个汉字。
5. profile_id 必须从给定人物类型中选择；不要自行创建人物类型。
6. faction 只能是：{FACTIONS}
7. emotion 只能是：{EMOTIONS}
8. orientation 只能是：{ORIENTATIONS}
9. stance 只能是：{STANCES}
10. 提供角度任务时，task_id 必须来自本批次角度任务，不得自行创建或重复。

【输出格式】
只能返回一个 JSON 对象，不要返回 Markdown 或额外解释：
{{
  "comments": [
    {{
{task_output_field}      "text": "评论文本",
      "profile_id": 1,
      "faction": "观点输出派",
      "topic": "事件主题",
      "emotion": "negative",
      "orientation": "fact",
      "stance": "questioning"
    }}
  ]
}}
""".strip()


# 2026/08/23 评论派系覆盖对齐，新增功能：统计初始评论池中五个派系的评论数量。
def count_comments_by_faction(comments):
    """统计评论列表中每个合法派系的数量。"""
    counts = {faction: 0 for faction in FACTIONS}
    for comment in comments:
        faction = comment.get("faction") if isinstance(comment, dict) else None
        if faction in counts:
            counts[faction] += 1
    return counts


# 2026/08/23 评论派系覆盖对齐，新增功能：计算尚未达到最低数量的派系缺口。
def calculate_faction_deficits(comments, minimum_count):
    """返回未达到最低覆盖数量的派系及其缺少数量。"""
    if not isinstance(minimum_count, int) or minimum_count < 1:
        raise ValueError("minimum_count 必须是正整数。")

    counts = count_comments_by_faction(comments)
    return {
        faction: minimum_count - count
        for faction, count in counts.items()
        if count < minimum_count
    }


# 2026/08/23 评论派系覆盖对齐，新增功能：构造只生成一个指定派系的补充提示词。
def build_faction_fill_prompt(
    event_input,
    profiles,
    target_faction,
    comment_count,
    comment_tasks=None,
):
    """在普通生成提示词后追加优先级更高的派系补充要求。"""
    if target_faction not in FACTIONS:
        raise ValueError(f"目标评论派系不合法：{target_faction}")

    base_prompt = build_generation_prompt(
        event_input,
        profiles,
        comment_count,
        comment_tasks,
    )
    return f"""
{base_prompt}

【派系定向补充要求】
以下要求优先于上面的派系覆盖要求。
本次生成的 {comment_count} 条评论，其 faction 必须全部为“{target_faction}”。
不得输出其他评论派系。
""".strip()


# 2026/08/23 评论派系覆盖对齐，新增功能：移出数量过多派系的评论，为缺失派系保留固定池容量。
def remove_surplus_comments(comments, remove_count, minimum_count):
    """从列表尾部确定性移出超过最低数量的派系评论。"""
    if remove_count == 0:
        return list(comments)

    counts = count_comments_by_faction(comments)
    kept_comments = list(comments)
    remaining = remove_count

    for index in range(len(kept_comments) - 1, -1, -1):
        faction = kept_comments[index].get("faction")
        if remaining > 0 and counts.get(faction, 0) > minimum_count:
            counts[faction] -= 1
            kept_comments.pop(index)
            remaining -= 1

    if remaining:
        raise RuntimeError(f"无法为缺失派系释放 {remaining} 个评论位置。")
    return kept_comments


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：派系补齐时保留被替换评论的角度任务。
def split_surplus_comments(comments, remove_count, minimum_count):
    """返回保留评论和被替换评论，供派系补齐复用原角度任务。"""
    kept_comments = remove_surplus_comments(
        comments,
        remove_count,
        minimum_count,
    )
    kept_task_ids = {
        comment.get("task_id")
        for comment in kept_comments
        if comment.get("task_id")
    }
    removed_comments = [
        comment
        for comment in comments
        if comment.get("task_id") not in kept_task_ids
    ]
    return kept_comments, removed_comments


# 2026/08/23 评论派系覆盖对齐，新增功能：定向补齐缺失派系并保持初始评论池总数不变。
def ensure_faction_coverage(
    event_input,
    profiles,
    comments,
    used_texts,
    minimum_count=COMMENT_POOL_MIN_FACTION_COUNT,
):
    """补齐未达最低数量的派系，返回总数量不变的新评论列表。"""
    deficits = calculate_faction_deficits(comments, minimum_count)
    original_count = len(comments)
    required_count = len(FACTIONS) * minimum_count
    if required_count > original_count:
        raise ValueError(
            f"评论池共 {original_count} 条，无法保证五派各至少 {minimum_count} 条。"
        )

    if not deficits:
        return list(comments)

    total_missing_count = sum(deficits.values())
    covered_comments, removed_comments = split_surplus_comments(
        comments,
        total_missing_count,
        minimum_count,
    )
    fill_comments = []
    removed_index = 0
    for faction, missing_count in deficits.items():
        replacement_comments = removed_comments[
            removed_index:removed_index + missing_count
        ]
        removed_index += missing_count
        replacement_tasks = [
            {
                "task_id": comment["task_id"],
                "angle_id": comment["angle_id"],
                "angle_name": comment["angle_name"],
                "focus": comment.get("angle_focus", comment["angle_name"]),
                # 2026/09/04 评论质量与耗时平衡，修改功能：派系补齐时保留原任务的表达方式。
                "expression_mode": comment.get("expression_mode"),
                "expression_instruction": comment.get(
                    "expression_instruction"
                ),
            }
            for comment in replacement_comments
            if all(
                comment.get(field)
                for field in ("task_id", "angle_id", "angle_name")
            )
        ]
        if len(replacement_tasks) != missing_count:
            replacement_tasks = None
        prompt = build_faction_fill_prompt(
            event_input,
            profiles,
            faction,
            missing_count,
            replacement_tasks,
        )
        fill_comments.extend(
            generate_valid_comment_batch(
                prompt=prompt,
                event_input=event_input,
                profiles=profiles,
                used_texts=used_texts,
                expected_count=missing_count,
                allowed_factions=[faction],
                comment_tasks=replacement_tasks,
            )
        )

    covered_comments.extend(fill_comments)

    remaining_deficits = calculate_faction_deficits(
        covered_comments,
        minimum_count,
    )
    if len(covered_comments) != original_count or remaining_deficits:
        raise RuntimeError(f"评论派系覆盖补齐失败：{remaining_deficits}")
    return covered_comments


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：按事件角度任务生成并记录初始评论池。
def generate_comment_pool(
    event_input,
    # 2026/09/05 评论人物类型配置归档，修改功能：默认读取 Demo 配置目录中的评论人物类型。
    profile_file=COMMENT_PROFILE_FILE,
    comment_count=COMMENT_POOL_SIZE,
):
    """根据一个事件和人物类型生成完整的初始评论池。"""
    if not isinstance(event_input, dict):
        raise ValueError("event_input 必须是 JSON 对象。")
    if not event_input.get("event_id"):
        raise ValueError("事件必须包含 event_id。")
    if not event_input.get("event_content"):
        raise ValueError("事件必须包含 event_content。")
    if not isinstance(comment_count, int) or comment_count <= 0:
        raise ValueError("comment_count 必须是正整数。")
    # 2026/08/23 评论派系覆盖对齐，修改功能：生成前拒绝无法满足五派最低数量的评论池规模。
    required_count = len(FACTIONS) * COMMENT_POOL_MIN_FACTION_COUNT
    if comment_count < required_count:
        raise ValueError(
            f"comment_count 至少为 {required_count}，"
            "才能满足五个评论派系的最低覆盖数量。"
        )

    profiles = load_generation_profiles(profile_file)
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：每个事件只生成一次可供全部场景复用的角度计划。
    angle_plan = generate_event_angle_plan(event_input)
    comment_tasks = build_initial_angle_tasks(angle_plan, comment_count)
    used_texts = set()
    comments = []
    batch_count = (comment_count + COMMENT_BATCH_SIZE - 1) // COMMENT_BATCH_SIZE

    task_offset = 0
    for _ in range(batch_count):
        remaining = comment_count - len(comments)
        batch_size = min(COMMENT_BATCH_SIZE, remaining)
        batch_tasks = comment_tasks[task_offset:task_offset + batch_size]
        task_offset += batch_size
        prompt = build_generation_prompt(
            event_input,
            profiles,
            batch_size,
            batch_tasks,
        )
        # 2026/08/22 增量评论累积对齐：通过共享服务保留有效评论，并补齐当前批次。
        batch_comments = generate_valid_comment_batch(
            prompt=prompt,
            event_input=event_input,
            profiles=profiles,
            used_texts=used_texts,
            expected_count=batch_size,
            comment_tasks=batch_tasks,
        )
        comments.extend(batch_comments)

    # 2026/08/23 评论派系覆盖对齐，修改功能：分配评论编号前补齐缺失派系并保持总数不变。
    comments = ensure_faction_coverage(
        event_input=event_input,
        profiles=profiles,
        comments=comments,
        used_texts=used_texts,
    )

    current_step = event_input.get("current_state", {}).get("step", 1)
    if not isinstance(current_step, int):
        current_step = 1

    result_comments = []
    for index, comment in enumerate(comments, start=1):
        result_comments.append(
            {
                "comment_id": f"comment_{index:03d}",
                "task_id": comment["task_id"],
                "angle_id": comment["angle_id"],
                "angle_name": comment["angle_name"],
                "angle_focus": comment["angle_focus"],
                # 2026/09/04 评论质量与耗时平衡，新增功能：初始评论保留表达方式，便于后续评论多样性诊断。
                "expression_mode": comment.get("expression_mode"),
                "expression_instruction": comment.get(
                    "expression_instruction"
                ),
                "text": comment["text"],
                "profile_id": comment["profile_id"],
                "profile_label": comment["profile_label"],
                "topic": comment["topic"],
                "emotion": comment["emotion"],
                "faction": comment["faction"],
                "orientation": comment["orientation"],
                "stance": comment["stance"],
                "introduced_step": current_step,
                "generation_trigger": "initial_event",
            }
        )

    # 2026/08/23 评论派系覆盖对齐，新增功能：在初始评论池结果中保存五派覆盖摘要。
    return {
        "event_id": event_input["event_id"],
        "generation_method": "angle_task_profile_conditioned_generation",
        # 2026/09/05 评论人物类型配置归档，修改功能：在评论池中记录迁移后的配置来源。
        "profile_source": "demo/config/comment_profiles.json",
        "requested_comment_count": comment_count,
        "angle_plan": angle_plan,
        "faction_coverage": {
            "minimum_per_faction": COMMENT_POOL_MIN_FACTION_COUNT,
            "counts": count_comments_by_faction(result_comments),
            "complete": True,
        },
        "profile_faction_combinations": summarize_profile_faction_combinations(
            result_comments
        ),
        "comments": result_comments,
    }


def main():
    """读取命令行参数，生成并保存 comment_pool.json。"""
    parser = argparse.ArgumentParser(description="根据人物类型生成事件评论池")
    parser.add_argument("--event-file", default=str(EVENT_FILE), help="事件 JSON 文件路径")
    parser.add_argument(
        "--profile-file",
        default=str(COMMENT_PROFILE_FILE),
        help="人物类型 JSON 文件路径",
    )
    parser.add_argument("--output-file", default=str(COMMENT_POOL_FILE), help="评论池输出路径")
    parser.add_argument("--count", type=int, default=COMMENT_POOL_SIZE, help="生成评论数量")
    args = parser.parse_args()

    event_input = load_json(args.event_file)
    comment_pool = generate_comment_pool(
        event_input=event_input,
        profile_file=args.profile_file,
        comment_count=args.count,
    )
    save_json(args.output_file, comment_pool)
    print(f"评论生成完成，共 {len(comment_pool['comments'])} 条。")
    print(f"输出文件：{args.output_file}")


if __name__ == "__main__":
    main()
