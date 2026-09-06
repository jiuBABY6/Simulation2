"""根据当前事件状态和上一轮 Agent 评论生成增量评论。

本模块只负责生成并追加保存后续轮次的新评论，不修改初始 comment_pool.json，
也不执行公共黑板构建或 Agent 决策。
"""

import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor

# 2026/08/22 增量评论累积对齐：改为依赖共享评论生成服务，不再依赖初始评论生成器。
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
    build_incremental_angle_tasks,
    format_comment_tasks,
    generate_event_angle_plan,
    validate_event_angle_plan,
)
from comments.repository import load_comment_pool
from simulation.event_context import load_event_context
from simulation.event_state_updater import load_event_state_history
from infrastructure.json_storage import append_jsonl, read_jsonl
from project_config import (
    COMMENT_BATCH_EXTRA_COUNT,
    COMMENT_VISIBILITY_SEED,
    COMMENT_POOL_FILE,
    COMMENT_PROFILE_FILE,
    DECISION_HISTORY_FILE,
    EVENT_FILE,
    EVENT_STATE_FILE,
    INCREMENTAL_COMMENT_COUNT,
    INCREMENTAL_COMMENT_BATCH_WORKERS,
    INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT,
    INCREMENTAL_COMMENT_FILE,
    INCREMENTAL_COMMENT_QUALITY_RESCUE_ATTEMPTS,
    INCREMENTAL_COMMENT_REFILL_ATTEMPTS,
    INCREMENTAL_COMMENT_RESCUE_EXTRA_COUNT,
    ensure_runtime_directories,
)


# 2026/08/24 增量评论兜底机制，新增功能：集中定义历史兜底评论必须保留的业务字段。
FALLBACK_COMMENT_FIELDS = (
    "text",
    "profile_id",
    "profile_label",
    "topic",
    "emotion",
    "faction",
    "orientation",
    "stance",
)

# 2026/08/24 增量评论稳定补齐，新增功能：定义模型和历史评论都不足时使用的中性应急文本。
EMERGENCY_COMMENT_TEMPLATES = (
    "目前公开信息仍然有限，先继续关注后续进展和正式说明。",
    "现阶段还缺少可以核实的完整信息，暂时不宜过早下结论。",
    "已经看到当前讨论，后续公开信息是否充分更值得关注。",
    "不同观点都可以保留，先等待事件出现进一步的明确进展。",
    "公众关心的问题仍需要清楚说明，继续观察后续回应。",
)
EMERGENCY_COMMENT_PREFIXES = (
    "",
    "我觉得，",
    "从目前看，",
    "就现有信息看，",
)

# 2026/08/25 第八次联调问题修复，新增功能：限制提示词中的近期避重文本数量，避免输入随轮次无限增长。
RECENT_AVOID_TEXT_COUNT = 30
# 2026/08/26 第十一次联调问题修复，新增功能：补充较早历史评论的有限避重样本。
OLDER_AVOID_TEXT_COUNT = 20


# 2026/08/24 增量评论兜底机制，修改功能：校验并兼容历史记录中的兜底数量字段。
# 2026/08/24 增量评论稳定补齐，修改功能：允许完整兜底并校验新增的数据质量字段。
def validate_incremental_record(record):
    """检查一条增量评论批次是否包含必要字段。"""
    if not isinstance(record, dict):
        raise ValueError("增量评论历史中的每一行都必须是 JSON 对象。")
    if not record.get("event_id"):
        raise ValueError("增量评论历史记录缺少 event_id。")
    if not isinstance(record.get("step"), int) or record["step"] < 2:
        raise ValueError("增量评论历史记录的 step 必须大于或等于 2。")
    if not isinstance(record.get("comments"), list):
        raise ValueError("增量评论历史记录缺少 comments 数组。")
    if record.get("comment_count") != len(record["comments"]):
        raise ValueError("增量评论记录的 comment_count 与实际数量不一致。")

    history_fallback_comments = [
        comment
        for comment in record["comments"]
        if isinstance(comment, dict)
        and comment.get("source_type") == "repost_fallback"
    ]
    emergency_fallback_comments = [
        comment
        for comment in record["comments"]
        if isinstance(comment, dict)
        and comment.get("source_type") == "local_emergency_fallback"
    ]
    fallback_comments = history_fallback_comments + emergency_fallback_comments
    fallback_count = record.get("fallback_count", 0)
    if (
        isinstance(fallback_count, bool)
        or not isinstance(fallback_count, int)
        or fallback_count < 0
        or fallback_count > record["comment_count"]
    ):
        raise ValueError("增量评论记录的 fallback_count 不合法。")
    if fallback_count != len(fallback_comments):
        raise ValueError("增量评论记录的 fallback_count 与实际兜底数量不一致。")
    if any(
        not comment.get("source_comment_id")
        for comment in history_fallback_comments
    ):
        raise ValueError("兜底评论缺少 source_comment_id。")
    if any(
        not comment.get("fallback_reason")
        for comment in emergency_fallback_comments
    ):
        raise ValueError("本地应急评论缺少 fallback_reason。")

    history_fallback_count = record.get(
        "history_fallback_count",
        len(history_fallback_comments),
    )
    emergency_fallback_count = record.get(
        "emergency_fallback_count",
        len(emergency_fallback_comments),
    )
    llm_comment_count = record.get(
        "llm_comment_count",
        record["comment_count"] - fallback_count,
    )
    count_fields = (
        history_fallback_count,
        emergency_fallback_count,
        llm_comment_count,
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in count_fields
    ):
        raise ValueError("增量评论记录的来源数量字段不合法。")
    if history_fallback_count != len(history_fallback_comments):
        raise ValueError("history_fallback_count 与实际历史兜底数量不一致。")
    if emergency_fallback_count != len(emergency_fallback_comments):
        raise ValueError("emergency_fallback_count 与实际应急兜底数量不一致。")
    if llm_comment_count + fallback_count != record["comment_count"]:
        raise ValueError("模型生成数量和兜底数量之和不等于评论总数。")

    quality_status = record.get("quality_status")
    if quality_status is not None and quality_status not in {
        "normal",
        "degraded",
        "emergency",
    }:
        raise ValueError("增量评论记录的 quality_status 不合法。")
    if quality_status is not None:
        expected_quality_status = "normal"
        if emergency_fallback_count > 0:
            expected_quality_status = "emergency"
        elif history_fallback_count > INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT:
            expected_quality_status = "degraded"
        if quality_status != expected_quality_status:
            raise ValueError("quality_status 与实际兜底数量不一致。")
    rejection_counts = record.get("rejection_counts", {})
    if not isinstance(rejection_counts, dict):
        raise ValueError("增量评论记录的 rejection_counts 必须是 JSON 对象。")
    if any(
        not isinstance(reason, str)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for reason, count in rejection_counts.items()
    ):
        raise ValueError("增量评论记录的过滤统计不合法。")
    # 2026/09/04 增量评论生成架构优化，修改功能：校验首轮请求、统一补齐和请求波次统计。
    for field in (
        "generation_attempts",
        "initial_request_count",
        "refill_request_count",
        "rescue_request_count",
        "generation_wave_count",
        "quality_target_count",
        "model_returned_comment_count",
    ):
        value = record.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"增量评论记录的 {field} 不合法。")
    quality_target_count = record.get("quality_target_count", 0)
    if quality_target_count > record["comment_count"]:
        raise ValueError("quality_target_count 不能超过本轮评论总数。")
    if not isinstance(record.get("validation_errors", []), list):
        raise ValueError("增量评论记录的 validation_errors 必须是数组。")
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：校验增量评论角度任务诊断字段。
    angle_task_count = record.get("angle_task_count", 0)
    completed_angle_task_count = record.get("completed_angle_task_count", 0)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (angle_task_count, completed_angle_task_count)
    ):
        raise ValueError("增量评论记录的角度任务数量不合法。")
    if completed_angle_task_count > angle_task_count:
        raise ValueError("已完成角度任务数量不能超过计划数量。")
    if not isinstance(record.get("angle_counts", {}), dict):
        raise ValueError("增量评论记录的 angle_counts 必须是 JSON 对象。")
    if not isinstance(record.get("profile_faction_combinations", []), list):
        raise ValueError("增量评论记录的人物类型与派系统计必须是数组。")


def load_incremental_history(history_file=INCREMENTAL_COMMENT_FILE):
    """读取并检查已经保存的增量评论批次。"""
    records = read_jsonl(history_file)
    for record in records:
        validate_incremental_record(record)
    return records


def collect_existing_comments(comment_pool, incremental_history, event_id):
    """合并当前事件的初始评论和已生成的增量评论。"""
    if comment_pool.get("event_id") != event_id:
        raise ValueError("初始评论池与当前事件的 event_id 不一致。")

    comments = list(comment_pool["comments"])
    for record in incremental_history:
        if record.get("event_id") == event_id:
            comments.extend(record["comments"])
    return comments


# 2026/08/24 增量评论兜底机制，新增功能：读取当前轮次之前已被 Agent 选择的评论编号。
def load_selected_comment_ids(
    event_id,
    current_step,
    decision_history_file=DECISION_HISTORY_FILE,
):
    """返回当前事件在本轮之前已经被 Agent 选择的评论编号。"""
    selected_comment_ids = set()
    for record in read_jsonl(decision_history_file):
        if record.get("status") != "success" or record.get("is_example"):
            continue
        if record.get("event_id") != event_id:
            continue
        step = record.get("step")
        if not isinstance(step, int) or step >= current_step:
            continue

        decision = record.get("decision", {})
        if (
            not isinstance(decision, dict)
            or decision.get("will_comment") is not True
        ):
            continue
        selected_comment_id = decision.get("selected_comment_id")
        if not selected_comment_id:
            selected_comment = decision.get("selected_comment")
            if isinstance(selected_comment, dict):
                selected_comment_id = selected_comment.get("comment_id")
        if selected_comment_id:
            selected_comment_ids.add(str(selected_comment_id))
    return selected_comment_ids


# 2026/08/25 第六次联调问题修复，修改功能：合并上一轮重复选中的评论并保留选择次数。
def load_previous_round_comments(
    event_id,
    current_step,
    existing_comments,
    decision_history_file=DECISION_HISTORY_FILE,
):
    """从完整决策历史中读取上一轮 Agent 实际发布的评论。"""
    previous_step = current_step - 1
    comment_map = {
        str(comment.get("comment_id")): comment
        for comment in existing_comments
        if isinstance(comment, dict) and comment.get("comment_id")
    }
    comments_by_agent = {}

    for record in read_jsonl(decision_history_file):
        if record.get("status") != "success":
            continue
        if record.get("event_id") != event_id or record.get("step") != previous_step:
            continue

        decision = record.get("decision", {})
        if decision.get("will_comment") is not True:
            continue

        selected = decision.get("selected_comment")
        if not isinstance(selected, dict):
            selected_id = str(decision.get("selected_comment_id", ""))
            selected = comment_map.get(selected_id)
        if not isinstance(selected, dict) or not selected.get("text"):
            continue

        agent_id = record.get("agent_id")
        if not agent_id:
            continue
        comments_by_agent[agent_id] = {
            "comment_id": selected.get("comment_id"),
            "text": selected.get("text", ""),
            "emotion": selected.get("emotion"),
            "faction": selected.get("faction"),
            "stance": selected.get("stance"),
        }

    grouped_comments = {}
    for agent_id in sorted(comments_by_agent):
        comment = comments_by_agent[agent_id]
        comment_id = comment.get("comment_id")
        normalized_text = " ".join(comment.get("text", "").split())
        group_key = (
            f"comment_id:{comment_id}"
            if comment_id
            else f"comment_text:{normalized_text}"
        )
        if group_key not in grouped_comments:
            grouped_comments[group_key] = {
                **comment,
                "selection_count": 0,
            }
        grouped_comments[group_key]["selection_count"] += 1

    return sorted(
        grouped_comments.values(),
        key=lambda item: (
            -item["selection_count"],
            str(item.get("comment_id", "")),
            item.get("text", ""),
        ),
    )


# 2026/08/25 第六次联调问题修复，新增功能：汇总上一轮全部增量评论的情绪、立场和派系分布。
def summarize_previous_incremental_comments(existing_comments, current_step):
    """返回上一轮增量评论分布，不把全部评论原文重复放入提示词。"""
    summary = {
        "comment_count": 0,
        "emotion_counts": {},
        "stance_counts": {},
        "faction_counts": {},
    }
    for comment in existing_comments:
        if (
            not isinstance(comment, dict)
            or comment.get("introduced_step") != current_step - 1
        ):
            continue
        summary["comment_count"] += 1
        for field, count_field in (
            ("emotion", "emotion_counts"),
            ("stance", "stance_counts"),
            ("faction", "faction_counts"),
        ):
            value = comment.get(field)
            if value:
                counts = summary[count_field]
                counts[value] = counts.get(value, 0) + 1
    return summary


def determine_generation_trigger(event_context, state_history):
    """判断本轮增量评论由新官方声明还是持续讨论触发。"""
    current_state = event_context["current_state"]
    current_step = current_state["step"]
    previous_states = [
        state
        for state in state_history
        if state.get("event_id") == event_context["event_id"]
        and state.get("step", 0) < current_step
    ]
    previous_state = max(previous_states, key=lambda item: item["step"], default={})

    current_statement = str(current_state.get("official_statement", "")).strip()
    current_status = current_state.get("official_statement_status", "none")
    previous_statement = str(previous_state.get("official_statement", "")).strip()
    previous_status = previous_state.get("official_statement_status", "none")

    statement_changed = (
        current_statement
        and (current_statement, current_status) != (previous_statement, previous_status)
    )
    return "official_statement" if statement_changed else "ongoing_discussion"


# 2026/08/24 增量评论兜底机制，新增功能：从初始评论和历史增量评论中确定性抽取未使用评论。
# 2026/08/24 增量评论稳定补齐，修改功能：按实际缺口尽量抽取，不再用固定数量上限终止场景。
def select_fallback_comments(
    existing_comments,
    generated_comments,
    selected_comment_ids,
    missing_count,
    event_id,
    current_step,
    random_seed=COMMENT_VISIBILITY_SEED,
):
    """按最近轮次优先的顺序抽取可追踪的历史评论。"""
    if missing_count <= 0:
        return []

    generated_texts = {
        str(comment.get("text", "")).strip()
        for comment in generated_comments
        if isinstance(comment, dict) and comment.get("text")
    }
    used_fallback_source_ids = {
        str(comment.get("source_comment_id"))
        for comment in existing_comments
        if isinstance(comment, dict)
        and comment.get("source_type") == "repost_fallback"
        and comment.get("source_comment_id")
    }
    candidates_by_step = {}

    for comment in existing_comments:
        if not isinstance(comment, dict):
            continue
        comment_id = str(comment.get("comment_id", "")).strip()
        introduced_step = comment.get("introduced_step")
        if not comment_id or not isinstance(introduced_step, int):
            continue
        if introduced_step >= current_step:
            continue
        if (
            comment_id in selected_comment_ids
            or comment_id in used_fallback_source_ids
        ):
            continue
        if comment.get("source_type") == "repost_fallback":
            continue
        if any(
            field not in comment or comment[field] in (None, "")
            for field in FALLBACK_COMMENT_FIELDS
        ):
            continue
        if comment.get("faction") not in FACTIONS:
            continue
        if comment.get("emotion") not in EMOTIONS:
            continue
        if comment.get("orientation") not in ORIENTATIONS:
            continue
        if comment.get("stance") not in STANCES:
            continue
        text = str(comment.get("text", "")).strip()
        if not text or text in generated_texts:
            continue
        candidates_by_step.setdefault(introduced_step, []).append(comment)

    random_generator = random.Random(
        f"{random_seed}:{event_id}:{current_step}"
    )
    selected_comments = []
    for step in sorted(candidates_by_step, reverse=True):
        step_candidates = sorted(
            candidates_by_step[step],
            key=lambda item: str(item["comment_id"]),
        )
        random_generator.shuffle(step_candidates)
        take_count = min(
            missing_count - len(selected_comments),
            len(step_candidates),
        )
        selected_comments.extend(step_candidates[:take_count])
        if len(selected_comments) == missing_count:
            break

    fallback_comments = []
    for source_comment in selected_comments:
        fallback_comment = {
            field: source_comment[field] for field in FALLBACK_COMMENT_FIELDS
        }
        fallback_comment["text"] = str(fallback_comment["text"]).strip()
        fallback_comment["source_type"] = "repost_fallback"
        fallback_comment["source_comment_id"] = source_comment["comment_id"]
        fallback_comments.append(fallback_comment)
    return fallback_comments


# 2026/08/24 增量评论稳定补齐，新增功能：历史候选不足时生成可识别、可追踪的中性本地应急评论。
def build_emergency_fallback_comments(
    event_context,
    profiles,
    existing_comments,
    generated_comments,
    missing_count,
):
    """使用确定性中性模板补足剩余数量，避免依赖模型再次请求。"""
    if missing_count <= 0:
        return []
    if not profiles:
        raise ValueError("本地应急补齐需要至少一个人物类型。")

    used_texts = {
        str(comment.get("text", "")).strip()
        for comment in [*existing_comments, *generated_comments]
        if isinstance(comment, dict) and comment.get("text")
    }
    topic = event_context.get("event_labels", {}).get("topic", "其他")
    factions = ("吃瓜派", "观点输出派", "表态判断派")
    comments = []

    for index in range(missing_count):
        template = EMERGENCY_COMMENT_TEMPLATES[
            index % len(EMERGENCY_COMMENT_TEMPLATES)
        ]
        prefix_index = (
            index // len(EMERGENCY_COMMENT_TEMPLATES)
        ) % len(EMERGENCY_COMMENT_PREFIXES)
        text = f"{EMERGENCY_COMMENT_PREFIXES[prefix_index]}{template}"
        while text in used_texts:
            text = f"再补充一点，{text}"
        used_texts.add(text)

        profile = profiles[index % len(profiles)]
        comments.append(
            {
                "text": text,
                "profile_id": profile["profile_id"],
                "profile_label": profile["profile_label"],
                "topic": topic,
                "emotion": "neutral",
                "faction": factions[index % len(factions)],
                "orientation": "opinion",
                "stance": "neutral",
                "source_type": "local_emergency_fallback",
                "fallback_reason": "insufficient_valid_comments",
            }
        )
    return comments


# 2026/08/24 增量评论稳定补齐，新增功能：统一完成历史评论兜底和本地应急补齐，保证本轮目标数量。
def complete_incremental_comments(
    event_context,
    profiles,
    existing_comments,
    generated_comments,
    selected_comment_ids,
    target_count,
):
    """先使用严格历史候选，再以本地中性评论补足全部剩余缺口。"""
    missing_count = target_count - len(generated_comments)
    if missing_count <= 0:
        return list(generated_comments[:target_count])

    history_fallbacks = select_fallback_comments(
        existing_comments=existing_comments,
        generated_comments=generated_comments,
        selected_comment_ids=selected_comment_ids,
        missing_count=missing_count,
        event_id=event_context["event_id"],
        current_step=event_context["current_state"]["step"],
    )
    completed_comments = [*generated_comments, *history_fallbacks]
    emergency_count = target_count - len(completed_comments)
    if emergency_count > 0:
        completed_comments.extend(
            build_emergency_fallback_comments(
                event_context=event_context,
                profiles=profiles,
                existing_comments=existing_comments,
                generated_comments=completed_comments,
                missing_count=emergency_count,
            )
        )
    return completed_comments


# 2026/08/25 第八次联调问题修复，新增功能：提取近期评论文本供增量生成器主动避重。
def select_recent_avoid_texts(
    existing_comments,
    current_step,
    max_count=RECENT_AVOID_TEXT_COUNT,
):
    """按最近轮次优先返回有限数量的不重复评论文本。"""
    if not isinstance(max_count, int) or max_count < 1:
        raise ValueError("max_count 必须是正整数。")

    ordered_comments = sorted(
        (
            comment
            for comment in existing_comments
            if isinstance(comment, dict)
            and isinstance(comment.get("introduced_step"), int)
            and comment["introduced_step"] < current_step
        ),
        key=lambda item: (
            item.get("introduced_step", 0),
            str(item.get("comment_id", "")),
        ),
        reverse=True,
    )
    texts = []
    seen_texts = set()
    for comment in ordered_comments:
        text = str(comment.get("text", "")).strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        texts.append(text)
        if len(texts) == max_count:
            break
    return texts


# 2026/08/26 第十一次联调问题修复，新增功能：分层选择近期评论和较早历史评论供首次请求避重。
def select_history_avoid_texts(
    existing_comments,
    current_step,
    recent_count=RECENT_AVOID_TEXT_COUNT,
    older_count=OLDER_AVOID_TEXT_COUNT,
):
    """返回近期文本和较早历史的确定性均匀样本。"""
    if (
        not isinstance(recent_count, int)
        or not isinstance(older_count, int)
        or recent_count < 0
        or older_count < 0
        or recent_count + older_count < 1
    ):
        raise ValueError("历史避重文本数量必须是非负整数且总数大于零。")

    ordered_texts = select_recent_avoid_texts(
        existing_comments,
        current_step,
        max(len(existing_comments), 1),
    )
    recent_texts = ordered_texts[:recent_count]
    older_texts = ordered_texts[recent_count:]
    if len(older_texts) <= older_count:
        return [*recent_texts, *older_texts]
    if older_count == 0:
        return recent_texts
    if older_count == 1:
        return [*recent_texts, older_texts[0]]

    sample_indexes = [
        index * (len(older_texts) - 1) // (older_count - 1)
        for index in range(older_count)
    ]
    return [
        *recent_texts,
        *(older_texts[index] for index in sample_indexes),
    ]


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：增量提示词接收本轮活跃角度任务。
# 2026/09/04 评论质量与耗时平衡，修改功能：支持精简补齐上下文和同任务备选表达。
def build_incremental_prompt(
    event_context,
    previous_comments,
    profiles,
    comment_count,
    generation_trigger,
    previous_incremental_summary=None,
    avoid_texts=None,
    comment_tasks=None,
    include_discussion_context=True,
    compact_profiles=False,
    allow_task_alternatives=False,
):
    """构造后续轮次增量评论生成提示词。"""
    if compact_profiles:
        profile_text = "\n".join(
            f"- profile_id={profile['profile_id']}，"
            f"profile_label={profile['profile_label']}"
            for profile in profiles
        )
    else:
        profile_text = "\n".join(
            f"- profile_id={profile['profile_id']}，"
            f"profile_label={profile['profile_label']}：{profile['definition']}"
            for profile in profiles
        )
    current_state = event_context["current_state"]
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：增量评论逐项完成程序分配的活跃角度任务。
    task_text = ""
    task_output_field = ""
    task_rule = ""
    if comment_tasks is not None:
        if allow_task_alternatives:
            task_rule = (
                "每个 task_id 至少返回一条评论；允许为部分 task_id 返回第二个备选表达，"
                "但同一 task_id 的文本必须明显不同。"
            )
        else:
            task_rule = "每个 task_id 必须恰好生成一条评论。"
        task_text = f"""
【本批次角度任务】
{format_comment_tasks(comment_tasks)}

{task_rule}评论必须围绕对应的 angle_name 和 focus，并遵循
expression_instruction 指定的表达方式。人物类型和评论派系由你结合角度、
官方声明和上一轮讨论合理选择。
""".strip()
        task_output_field = '      "task_id": "step_2_001",\n'

    discussion_text = ""
    if include_discussion_context:
        discussion_text = f"""
【上一轮 Agent 实际评论】
{json.dumps(previous_comments, ensure_ascii=False, indent=2)}

这些评论只用于理解讨论方向，不得逐字复用，也不得只修改少量词语后输出。
同一条实际评论只展示一次，selection_count 表示上一轮选择该评论的 Agent 数量。

【上一轮全部增量评论分布】
{json.dumps(previous_incremental_summary or {}, ensure_ascii=False, indent=2)}
""".strip()

    return f"""
你是社会舆情模拟系统的增量评论生成器。请根据当前事件状态和上一轮真实讨论，生成本轮新出现的社会评论。

【事件内容】
{event_context.get('event_content', '')}

【事件主题】
{event_context.get('event_labels', {}).get('topic', '其他')}

【当前时间步】
{current_state.get('step')}

【当前官方声明】
{current_state.get('official_statement', '')}

【官方声明类型】
{current_state.get('official_statement_status', 'none')}

【本轮生成原因】
{generation_trigger}

{discussion_text}

【近期不得重复的评论文本】
{json.dumps(avoid_texts or [], ensure_ascii=False, indent=2)}

【可使用的人物类型】
{profile_text}

{task_text}

【生成要求】
1. 生成 {comment_count} 条新的中文微博评论。
2. 评论应体现对当前官方声明或上一轮讨论的继续反应，不得复制上面的近期文本，也不要只替换少量词语进行复述。
3. 同一批次尽量从价格、配置、信息可信度、处理态度和公众感受等不同角度表达，避免重复同一个论点。
4. 尽量覆盖不同人物类型、五种评论派系、三种情绪和三种信息取向。
5. 不得编造事件中没有提供的姓名、数字、时间和调查结论。
6. 每条评论长度控制在 15 至 100 个汉字。
7. profile_id 必须来自给定人物类型。
8. faction 只能是：{FACTIONS}
9. emotion 只能是：{EMOTIONS}
10. orientation 只能是：{ORIENTATIONS}
11. stance 只能是：{STANCES}
12. 提供角度任务时，task_id 必须来自本批次角度任务，不得自行创建；是否允许同一任务提供备选表达以本批次任务说明为准。

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
      "orientation": "questioning",
      "stance": "questioning"
    }}
  ]
}}
""".strip()


def get_next_comment_number(existing_comments):
    """根据已有 comment_id 计算下一条评论的数字编号。"""
    numbers = []
    for comment in existing_comments:
        match = re.fullmatch(r"comment_(\d+)", str(comment.get("comment_id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


# 2026/08/24 增量评论稳定补齐，新增功能：合并多个子批次的模型返回数量和过滤原因。
def merge_batch_generation_stats(summary, batch_stats):
    """将一个子批次的诊断数据累加到本轮统计。"""
    summary["batch_count"] += 1
    summary["generation_attempts"] += batch_stats.get("attempt_count", 0)
    summary["model_returned_comment_count"] += batch_stats.get(
        "raw_comment_count",
        0,
    )
    for reason, count in batch_stats.get("rejection_counts", {}).items():
        summary["rejection_counts"][reason] = (
            summary["rejection_counts"].get(reason, 0) + count
        )
    summary["validation_errors"].extend(
        batch_stats.get("validation_errors", [])
    )


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：统计本轮模型评论实际完成的角度任务。
def summarize_angle_task_counts(comments):
    """返回每个有效角度的模型评论数量。"""
    counts = {}
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        angle_id = str(comment.get("angle_id", "")).strip()
        if angle_id:
            counts[angle_id] = counts.get(angle_id, 0) + 1
    return dict(sorted(counts.items()))


# 2026/09/04 增量评论生成架构优化，新增功能：单次执行一个增量评论批次，供首轮并行生成复用。
def generate_incremental_comment_batch(
    event_context,
    previous_comments,
    profiles,
    used_texts,
    batch_size,
    generation_trigger,
    previous_incremental_summary,
    avoid_texts,
    comment_tasks,
):
    """执行一次评论生成和校验，不在子批次内部重复补齐。"""
    request_count = (
        batch_size
        if comment_tasks is not None
        else batch_size + COMMENT_BATCH_EXTRA_COUNT
    )
    prompt = build_incremental_prompt(
        event_context,
        previous_comments,
        profiles,
        request_count,
        generation_trigger,
        previous_incremental_summary,
        avoid_texts,
        comment_tasks,
    )
    batch_stats = {}
    rejected_duplicate_texts = []
    comments = generate_valid_comment_batch(
        prompt=prompt,
        event_input=event_context,
        profiles=profiles,
        used_texts=set(used_texts),
        expected_count=batch_size,
        allow_partial=True,
        generation_stats=batch_stats,
        rejected_duplicate_texts=rejected_duplicate_texts,
        comment_tasks=comment_tasks,
        max_attempts=1,
    )
    return {
        "comments": comments,
        "stats": batch_stats,
        "rejected_duplicate_texts": rejected_duplicate_texts,
    }


# 2026/09/04 增量评论生成架构优化，新增功能：合并并行批次并处理跨批次重复文本或任务。
def merge_parallel_comment_batches(
    batch_results,
    used_texts,
    generation_summary,
    rejected_duplicate_texts,
):
    """按批次原顺序合并有效评论，并返回本轮首轮接收结果。"""
    comments = []
    accepted_task_ids = set()
    for batch_result in batch_results:
        merge_batch_generation_stats(
            generation_summary,
            batch_result.get("stats", {}),
        )
        for text in batch_result.get("rejected_duplicate_texts", []):
            if text not in rejected_duplicate_texts:
                rejected_duplicate_texts.append(text)

        for comment in batch_result.get("comments", []):
            text = str(comment.get("text", "")).strip()
            task_id = str(comment.get("task_id", "")).strip()
            if text in used_texts:
                generation_summary["rejection_counts"]["重复文本"] = (
                    generation_summary["rejection_counts"].get("重复文本", 0)
                    + 1
                )
                if text and text not in rejected_duplicate_texts:
                    rejected_duplicate_texts.append(text)
                continue
            if task_id and task_id in accepted_task_ids:
                generation_summary["rejection_counts"]["重复 task_id"] = (
                    generation_summary["rejection_counts"].get(
                        "重复 task_id",
                        0,
                    )
                    + 1
                )
                continue
            comments.append(comment)
            used_texts.add(text)
            if task_id:
                accepted_task_ids.add(task_id)
    return comments


# 2026/09/04 评论质量与耗时平衡，新增功能：集中计算尚未完成的角度任务，供两级补齐复用。
def select_missing_comment_tasks(comment_tasks, comments):
    """返回尚无有效评论的任务；非任务化生成返回 None。"""
    if comment_tasks is None:
        return None
    completed_task_ids = {
        comment.get("task_id")
        for comment in comments
        if comment.get("task_id")
    }
    return [
        task
        for task in comment_tasks
        if task["task_id"] not in completed_task_ids
    ]


# 2026/08/24 第三次联调问题修复，修改功能：增量评论不足时使用合格历史评论补足。
# 2026/08/24 增量评论稳定补齐，修改功能：取消固定兜底上限并向调用方返回本轮生成统计。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：按活跃角度任务生成本轮增量评论。
# 2026/09/04 增量评论生成架构优化，修改功能：首轮批次并行生成，缺失任务统一进行一次定向补齐。
# 2026/09/04 评论质量与耗时平衡，修改功能：增加17条质量门槛和最多一次质量救援请求。
def generate_incremental_comments(
    event_context,
    previous_comments,
    profiles,
    existing_comments,
    comment_count,
    generation_trigger,
    selected_comment_ids=None,
    generation_stats=None,
    previous_incremental_summary=None,
    angle_plan=None,
):
    """调用 DeepSeek 生成并规范化本轮增量评论。"""
    if not isinstance(comment_count, int) or comment_count <= 0:
        raise ValueError("comment_count 必须是正整数。")

    current_step = event_context["current_state"]["step"]
    if current_step < 2:
        raise ValueError("第 1 轮应使用初始评论生成器，增量评论从第 2 轮开始。")

    used_texts = {
        str(comment.get("text", "")).strip()
        for comment in existing_comments
        if isinstance(comment, dict) and comment.get("text")
    }
    generated_comments = []
    summary = {
        "batch_count": 0,
        "generation_attempts": 0,
        "initial_request_count": 0,
        "refill_request_count": 0,
        "rescue_request_count": 0,
        "generation_wave_count": 0,
        "quality_target_count": max(
            comment_count - INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT,
            0,
        ),
        "model_returned_comment_count": 0,
        "rejection_counts": {},
        "validation_errors": [],
    }
    selected_comment_ids = {
        str(comment_id) for comment_id in (selected_comment_ids or ())
    }
    # 2026/08/26 第十一次联调问题修复，修改功能：首次请求同时覆盖近期评论和较早历史样本。
    previous_comment_texts = [
        str(comment.get("text", "")).strip()
        for comment in previous_comments
        if isinstance(comment, dict) and str(comment.get("text", "")).strip()
    ]
    history_avoid_texts = list(
        dict.fromkeys(
            [
                *previous_comment_texts,
                *select_history_avoid_texts(
                    existing_comments,
                    current_step,
                ),
            ]
        )
    )
    # 2026/09/04 增量评论生成架构优化，修改功能：首轮并行批次独立收集反馈，合并后统一用于一次补齐。
    round_rejected_duplicate_texts = []
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：为本轮全部增量评论预先分配活跃角度。
    comment_tasks = (
        build_incremental_angle_tasks(
            angle_plan,
            event_context["current_state"],
            comment_count,
        )
        if angle_plan is not None
        else None
    )
    batch_count = (comment_count + COMMENT_BATCH_SIZE - 1) // COMMENT_BATCH_SIZE

    batch_specs = []
    task_offset = 0
    for batch_index in range(batch_count):
        remaining = comment_count - batch_index * COMMENT_BATCH_SIZE
        batch_size = min(COMMENT_BATCH_SIZE, remaining)
        batch_tasks = (
            comment_tasks[task_offset:task_offset + batch_size]
            if comment_tasks is not None
            else None
        )
        task_offset += batch_size
        batch_specs.append(
            {
                "event_context": event_context,
                "previous_comments": previous_comments,
                "profiles": profiles,
                "used_texts": used_texts,
                "batch_size": batch_size,
                "generation_trigger": generation_trigger,
                "previous_incremental_summary": previous_incremental_summary,
                "avoid_texts": history_avoid_texts,
                "comment_tasks": batch_tasks,
            }
        )

    worker_count = min(
        INCREMENTAL_COMMENT_BATCH_WORKERS,
        len(batch_specs),
    )
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(generate_incremental_comment_batch, **batch_spec)
            for batch_spec in batch_specs
        ]
        batch_results = [future.result() for future in futures]
    summary["initial_request_count"] = len(batch_results)
    summary["generation_wave_count"] = 1
    generated_comments = merge_parallel_comment_batches(
        batch_results,
        used_texts,
        summary,
        round_rejected_duplicate_texts,
    )

    # 2026/09/04 增量评论生成架构优化，新增功能：合并全部缺失角度任务，只追加一轮定向补齐请求。
    missing_count = comment_count - len(generated_comments)
    if missing_count > 0:
        missing_tasks = select_missing_comment_tasks(
            comment_tasks,
            generated_comments,
        )
        refill_request_count = (
            missing_count
            if missing_tasks is not None
            else missing_count + COMMENT_BATCH_EXTRA_COUNT
        )
        refill_avoid_texts = list(
            dict.fromkeys(
                [
                    *history_avoid_texts,
                    *[comment["text"] for comment in generated_comments],
                    *round_rejected_duplicate_texts,
                ]
            )
        )
        refill_prompt = build_incremental_prompt(
            event_context,
            previous_comments,
            profiles,
            refill_request_count,
            generation_trigger,
            previous_incremental_summary,
            refill_avoid_texts,
            missing_tasks,
            include_discussion_context=False,
            compact_profiles=True,
        )
        refill_stats = {}
        refill_comments = generate_valid_comment_batch(
            prompt=refill_prompt,
            event_input=event_context,
            profiles=profiles,
            used_texts=used_texts,
            expected_count=missing_count,
            allow_partial=True,
            generation_stats=refill_stats,
            rejected_duplicate_texts=round_rejected_duplicate_texts,
            comment_tasks=missing_tasks,
            max_attempts=INCREMENTAL_COMMENT_REFILL_ATTEMPTS,
        )
        merge_batch_generation_stats(summary, refill_stats)
        generated_comments.extend(refill_comments)
        summary["refill_request_count"] = refill_stats.get(
            "attempt_count",
            0,
        )
        summary["generation_wave_count"] = 2

    # 2026/09/04 评论质量与耗时平衡，新增功能：只有兜底缺口超过告警上限时才追加一次精简质量救援。
    missing_count = comment_count - len(generated_comments)
    if (
        missing_count > INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT
        and INCREMENTAL_COMMENT_QUALITY_RESCUE_ATTEMPTS > 0
    ):
        missing_tasks = select_missing_comment_tasks(
            comment_tasks,
            generated_comments,
        )
        rescue_avoid_texts = list(
            dict.fromkeys(
                [
                    *history_avoid_texts,
                    *[comment["text"] for comment in generated_comments],
                    *round_rejected_duplicate_texts,
                ]
            )
        )
        rescue_prompt = build_incremental_prompt(
            event_context,
            previous_comments=[],
            profiles=profiles,
            comment_count=(
                missing_count + INCREMENTAL_COMMENT_RESCUE_EXTRA_COUNT
            ),
            generation_trigger=generation_trigger,
            previous_incremental_summary=None,
            avoid_texts=rescue_avoid_texts,
            comment_tasks=missing_tasks,
            include_discussion_context=False,
            compact_profiles=True,
            allow_task_alternatives=True,
        )
        rescue_prompt = f"""
{rescue_prompt}

【质量救援要求】
前两波生成后仍缺少 {missing_count} 条有效评论。请优先更换论点、句式和表达方式，
不得复述已有评论。为容易重复的任务提供备选表达，系统只接收每个任务第一条
通过校验且不重复的评论。
""".strip()
        rescue_stats = {}
        rescue_comments = generate_valid_comment_batch(
            prompt=rescue_prompt,
            event_input=event_context,
            profiles=profiles,
            used_texts=used_texts,
            expected_count=missing_count,
            allow_partial=True,
            generation_stats=rescue_stats,
            rejected_duplicate_texts=round_rejected_duplicate_texts,
            comment_tasks=missing_tasks,
            max_attempts=INCREMENTAL_COMMENT_QUALITY_RESCUE_ATTEMPTS,
        )
        merge_batch_generation_stats(summary, rescue_stats)
        generated_comments.extend(rescue_comments)
        summary["rescue_request_count"] = rescue_stats.get(
            "attempt_count",
            0,
        )
        summary["generation_wave_count"] = 3

    llm_comment_count = len(generated_comments)
    # 2026/08/24 增量评论稳定补齐，修改功能：无论模型缺口大小都统一补足到目标数量。
    generated_comments = complete_incremental_comments(
        event_context=event_context,
        profiles=profiles,
        existing_comments=existing_comments,
        generated_comments=generated_comments,
        selected_comment_ids=selected_comment_ids,
        target_count=comment_count,
    )
    if generation_stats is not None:
        generation_stats.clear()
        generation_stats.update(summary)
        generation_stats["llm_comment_count"] = llm_comment_count
        generation_stats["angle_task_count"] = (
            len(comment_tasks) if comment_tasks is not None else 0
        )
        generation_stats["completed_angle_task_count"] = sum(
            bool(comment.get("task_id")) for comment in generated_comments
        )

    next_number = get_next_comment_number(existing_comments)
    result = []
    for offset, comment in enumerate(generated_comments):
        result.append(
            {
                "comment_id": f"comment_{next_number + offset:03d}",
                **comment,
                "introduced_step": current_step,
                "generation_trigger": generation_trigger,
            }
        )
    return result


def append_incremental_record(record, history_file=INCREMENTAL_COMMENT_FILE):
    """检查重复时间步后，将一批增量评论追加到 JSONL 历史。"""
    validate_incremental_record(record)
    history = load_incremental_history(history_file)
    duplicate = any(
        item.get("event_id") == record.get("event_id")
        and item.get("step") == record.get("step")
        for item in history
    )
    if duplicate:
        raise ValueError(
            f"事件 {record.get('event_id')} 的第 {record.get('step')} 轮增量评论已经存在。"
        )
    append_jsonl(history_file, record)


# 2026/08/24 增量评论稳定补齐，新增功能：根据历史兜底阈值和应急兜底数量标记本轮数据质量。
def determine_comment_quality(history_fallback_count, emergency_fallback_count):
    """返回 normal、degraded 或 emergency 三种评论数据质量状态。"""
    if emergency_fallback_count > 0:
        return "emergency"
    if history_fallback_count > INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT:
        return "degraded"
    return "normal"


# 2026/08/24 增量评论兜底机制，修改功能：加载排除项并保存每轮实际兜底数量。
# 2026/08/24 增量评论稳定补齐，修改功能：保存模型生成、两级兜底、过滤原因和数据质量状态。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：复用初始角度计划并保存角度任务诊断。
def run_incremental_generation(comment_count=INCREMENTAL_COMMENT_COUNT):
    """读取本轮所需数据，生成增量评论并追加保存。"""
    ensure_runtime_directories()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    event_id = event_context["event_id"]
    current_step = event_context["current_state"]["step"]
    if current_step < 2:
        raise ValueError("当前还是第 1 轮，不需要生成增量评论。")

    incremental_history = load_incremental_history(INCREMENTAL_COMMENT_FILE)
    if any(
        record.get("event_id") == event_id and record.get("step") == current_step
        for record in incremental_history
    ):
        raise ValueError(f"事件 {event_id} 的第 {current_step} 轮增量评论已经存在。")

    comment_pool = load_comment_pool(COMMENT_POOL_FILE)
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：优先复用初始评论池中的事件角度计划。
    raw_angle_plan = comment_pool.get("angle_plan")
    angle_plan = (
        validate_event_angle_plan(raw_angle_plan, event_context)
        if raw_angle_plan is not None
        else generate_event_angle_plan(event_context)
    )
    existing_comments = collect_existing_comments(
        comment_pool,
        incremental_history,
        event_id,
    )
    previous_comments = load_previous_round_comments(
        event_id,
        current_step,
        existing_comments,
        DECISION_HISTORY_FILE,
    )
    # 2026/08/25 第六次联调问题修复，新增功能：向生成器提供上一轮完整增量评论的分布摘要。
    previous_incremental_summary = summarize_previous_incremental_comments(
        existing_comments,
        current_step,
    )
    state_history = load_event_state_history(EVENT_STATE_FILE, event_id)
    generation_trigger = determine_generation_trigger(event_context, state_history)
    profiles = load_generation_profiles(COMMENT_PROFILE_FILE)
    # 2026/08/24 增量评论兜底机制，新增功能：兜底抽取前排除已经被 Agent 选择的历史评论。
    selected_comment_ids = load_selected_comment_ids(
        event_id,
        current_step,
        DECISION_HISTORY_FILE,
    )

    generation_stats = {}
    comments = generate_incremental_comments(
        event_context=event_context,
        previous_comments=previous_comments,
        profiles=profiles,
        existing_comments=existing_comments,
        comment_count=comment_count,
        generation_trigger=generation_trigger,
        selected_comment_ids=selected_comment_ids,
        generation_stats=generation_stats,
        previous_incremental_summary=previous_incremental_summary,
        angle_plan=angle_plan,
    )
    history_fallback_count = sum(
        comment.get("source_type") == "repost_fallback"
        for comment in comments
    )
    emergency_fallback_count = sum(
        comment.get("source_type") == "local_emergency_fallback"
        for comment in comments
    )
    fallback_count = history_fallback_count + emergency_fallback_count
    quality_status = determine_comment_quality(
        history_fallback_count,
        emergency_fallback_count,
    )
    record = {
        "event_id": event_id,
        "step": current_step,
        "generation_trigger": generation_trigger,
        "comment_count": len(comments),
        "llm_comment_count": generation_stats.get("llm_comment_count", 0),
        "history_fallback_count": history_fallback_count,
        "emergency_fallback_count": emergency_fallback_count,
        "fallback_count": fallback_count,
        "quality_status": quality_status,
        "generation_attempts": generation_stats.get("generation_attempts", 0),
        # 2026/09/04 增量评论生成架构优化，新增功能：保存业务层首轮、补齐和波次请求数量。
        "initial_request_count": generation_stats.get(
            "initial_request_count",
            0,
        ),
        "refill_request_count": generation_stats.get(
            "refill_request_count",
            0,
        ),
        # 2026/09/04 评论质量与耗时平衡，新增功能：保存自适应质量门槛和救援请求数量。
        "rescue_request_count": generation_stats.get(
            "rescue_request_count",
            0,
        ),
        "generation_wave_count": generation_stats.get(
            "generation_wave_count",
            0,
        ),
        "quality_target_count": generation_stats.get(
            "quality_target_count",
            0,
        ),
        "model_returned_comment_count": generation_stats.get(
            "model_returned_comment_count",
            0,
        ),
        "rejection_counts": generation_stats.get("rejection_counts", {}),
        "validation_errors": generation_stats.get("validation_errors", []),
        "angle_task_count": generation_stats.get("angle_task_count", 0),
        "completed_angle_task_count": generation_stats.get(
            "completed_angle_task_count",
            0,
        ),
        "angle_counts": summarize_angle_task_counts(comments),
        "profile_faction_combinations": summarize_profile_faction_combinations(
            comments
        ),
        "comments": comments,
    }
    append_incremental_record(record, INCREMENTAL_COMMENT_FILE)

    print(
        f"事件 {event_id} 第 {current_step} 轮增量评论生成完成，"
        f"新增 {len(comments)} 条，其中模型生成 "
        f"{record['llm_comment_count']} 条、历史兜底 "
        f"{history_fallback_count} 条、本地应急 "
        f"{emergency_fallback_count} 条；质量状态 {quality_status}。"
    )
    print(f"输出文件：{INCREMENTAL_COMMENT_FILE}")
    return record


def main():
    """提供增量评论生成的命令行入口。"""
    parser = argparse.ArgumentParser(description="生成当前轮次的增量评论")
    parser.add_argument(
        "--count",
        type=int,
        default=INCREMENTAL_COMMENT_COUNT,
        help="本轮生成的增量评论数量",
    )
    args = parser.parse_args()
    run_incremental_generation(args.count)


if __name__ == "__main__":
    main()
