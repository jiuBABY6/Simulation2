"""评论生成共享服务。

本模块集中管理评论字段约束、人物类型读取、模型结果校验和批次累积补齐。
初始评论生成器与增量评论生成器只负责各自的业务提示词和结果组织。
"""

import json
import re

from comments.angle_planner import validate_comment_tasks
from infrastructure.json_storage import load_json
from infrastructure.llm_service import call_deepseek_json
from project_config import (
    COMMENT_BATCH_EXTRA_COUNT,
    COMMENT_BATCH_RETRY_COUNT,
    COMMENT_POOL_MAX_TOKENS,
    COMMENT_POOL_TEMPERATURE,
)


FACTIONS = [
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
]
EMOTIONS = ["positive", "neutral", "negative"]
ORIENTATIONS = ["fact", "opinion", "questioning"]
STANCES = ["support", "questioning", "neutral", "criticism"]
COMMENT_BATCH_SIZE = 10

# 2026/09/04 增量评论生成架构优化，新增功能：将可明确识别的中英文枚举写法本地归一，避免为格式差异重新请求LLM。
COMMENT_VALUE_ALIASES = {
    "emotion": {
        "正面": "positive",
        "积极": "positive",
        "中性": "neutral",
        "负面": "negative",
        "消极": "negative",
    },
    "orientation": {
        "事实": "fact",
        "观点": "opinion",
        "质疑": "questioning",
        "疑问": "questioning",
    },
    "stance": {
        "支持": "support",
        "质疑": "questioning",
        "中立": "neutral",
        "批评": "criticism",
        "反对": "criticism",
    },
}

# 2026/08/26 第十次联调问题修复，新增功能：限制重试提示词中的重复文本反馈数量。
RETRY_DUPLICATE_FEEDBACK_LIMIT = 50


# 2026/08/22 增量评论累积对齐：将人物类型读取迁移到共享服务，解除增量模块对初始生成模块的依赖。
def load_generation_profiles(profile_file):
    """读取评论生成所使用的人物类型，并整理成统一格式。"""
    raw_profiles = load_json(profile_file)
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("人物类型文件必须是非空 JSON 数组。")

    profiles = []
    for item in raw_profiles:
        if not isinstance(item, dict):
            continue

        profile_id = item.get("id")
        definition = str(item.get("define", "")).strip()
        if profile_id is None or not definition:
            continue

        label_match = re.search(
            r"画像\s*\d+\s*[：:]\s*(.*?)(?:\s*\([^)]*\))?(?:\n|$)",
            definition,
        )
        profile_label = (
            label_match.group(1).strip()
            if label_match
            else f"人物类型{profile_id}"
        )
        profiles.append(
            {
                "profile_id": int(profile_id),
                "profile_label": profile_label,
                "definition": definition,
            }
        )

    if not profiles:
        raise ValueError("人物类型文件中没有可用的人物类型。")
    return profiles


# 2026/08/24 增量评论第二次修改，新增功能：兼容模型返回的字符串人物类型编号。
def normalize_profile_id(profile_id):
    """将整数或整数字符串转换为人物类型编号，其他值返回 None。"""
    if isinstance(profile_id, bool):
        return None
    if isinstance(profile_id, int):
        return profile_id
    if isinstance(profile_id, str):
        value = profile_id.strip()
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
    return None


# 2026/09/04 增量评论生成架构优化，新增功能：规范化评论枚举字段中的空格、大小写和明确别名。
def normalize_comment_value(value, allowed_values, aliases=None):
    """返回合法枚举值；无法明确映射时返回 None。"""
    normalized = str(value).strip()
    if normalized in allowed_values:
        return normalized
    lowered = normalized.lower()
    if lowered in allowed_values:
        return lowered
    return (aliases or {}).get(normalized) or (aliases or {}).get(lowered)


# 2026/08/22 增量评论累积对齐：统一校验模型评论，供初始评论和增量评论共同使用。
# 2026/08/23 评论派系覆盖对齐，修改功能：定向补充时只接收指定派系的评论。
# 2026/08/24 增量评论第二次修改，修改功能：规范化人物类型编号并统计评论过滤原因。
# 2026/08/26 第十次联调问题修复，修改功能：记录被过滤的具体重复评论供后续重试避开。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：校验任务编号并写入程序分配的角度字段。
# 2026/09/04 评论质量与耗时平衡，修改功能：把程序分配的表达方式写入有效评论，供后续诊断和补齐复用。
def normalize_comments(
    raw_result,
    event_input,
    profiles,
    used_texts,
    allowed_factions=None,
    rejection_counts=None,
    rejected_duplicate_texts=None,
    comment_tasks=None,
):
    """校验模型结果，补充人物和角度字段，并过滤无效或重复评论。"""
    if not isinstance(raw_result, dict) or not isinstance(
        raw_result.get("comments"), list
    ):
        raise ValueError("DeepSeek 返回结果必须包含 comments 数组。")

    accepted_factions = set(FACTIONS)
    if allowed_factions is not None:
        accepted_factions = set(allowed_factions)
        invalid_factions = accepted_factions - set(FACTIONS)
        if not accepted_factions or invalid_factions:
            raise ValueError(f"定向评论派系不合法：{sorted(invalid_factions)}")

    profile_map = {item["profile_id"]: item for item in profiles}
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：任务化生成时只接收程序分配的角度任务。
    normalized_tasks = (
        validate_comment_tasks(comment_tasks)
        if comment_tasks is not None
        else []
    )
    task_map = {task["task_id"]: task for task in normalized_tasks}
    accepted_task_ids = set()
    default_topic = event_input.get("event_labels", {}).get("topic", "其他")
    normalized = []
    if rejection_counts is None:
        rejection_counts = {}

    def reject(reason):
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    for item in raw_result["comments"]:
        if not isinstance(item, dict):
            reject("非对象评论")
            continue

        text = str(item.get("text", "")).strip()
        profile_id = normalize_profile_id(item.get("profile_id"))
        task_id = str(item.get("task_id", "")).strip()
        faction = normalize_comment_value(item.get("faction", ""), FACTIONS)
        emotion = normalize_comment_value(
            item.get("emotion", ""),
            EMOTIONS,
            COMMENT_VALUE_ALIASES["emotion"],
        )
        orientation = normalize_comment_value(
            item.get("orientation", ""),
            ORIENTATIONS,
            COMMENT_VALUE_ALIASES["orientation"],
        )
        stance = normalize_comment_value(
            item.get("stance", ""),
            STANCES,
            COMMENT_VALUE_ALIASES["stance"],
        )
        if task_map and task_id not in task_map:
            reject("无效 task_id")
            continue
        if task_id and task_id in accepted_task_ids:
            reject("重复 task_id")
            continue
        if not text:
            reject("空文本")
            continue
        if text in used_texts:
            reject("重复文本")
            if (
                rejected_duplicate_texts is not None
                and text not in rejected_duplicate_texts
            ):
                rejected_duplicate_texts.append(text)
                del rejected_duplicate_texts[
                    :-RETRY_DUPLICATE_FEEDBACK_LIMIT
                ]
            continue
        if profile_id not in profile_map:
            reject("无效 profile_id")
            continue
        if faction not in accepted_factions:
            reject("无效 faction")
            continue
        if emotion not in EMOTIONS:
            reject("无效 emotion")
            continue
        if orientation not in ORIENTATIONS:
            reject("无效 orientation")
            continue
        if stance not in STANCES:
            reject("无效 stance")
            continue

        profile = profile_map[profile_id]
        comment = {
            "text": text,
            "profile_id": profile_id,
            "profile_label": profile["profile_label"],
            "topic": default_topic,
            "emotion": emotion,
            "faction": faction,
            "orientation": orientation,
            "stance": stance,
        }
        if task_map:
            task = task_map[task_id]
            comment.update(
                {
                    "task_id": task_id,
                    "angle_id": task["angle_id"],
                    "angle_name": task["angle_name"],
                    "angle_focus": task["focus"],
                    "expression_mode": task.get("expression_mode"),
                    "expression_instruction": task.get(
                        "expression_instruction"
                    ),
                }
            )
            accepted_task_ids.add(task_id)
        normalized.append(comment)
        used_texts.add(text)

    return normalized


# 2026/08/22 增量评论累积对齐：新增补齐提示词，只请求缺少的数量并避免重复已有结果。
# 2026/08/24 增量评论第二次修改，修改功能：补齐时额外请求少量评论抵消校验过滤。
# 2026/08/25 第八次联调问题修复，修改功能：补齐时要求更换表达角度，减少再次返回重复文本。
# 2026/08/26 第十次联调问题修复，修改功能：补齐时明确反馈前几次被过滤的重复评论。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：任务化补齐只请求缺失角度任务。
def build_comment_retry_prompt(
    original_prompt,
    remaining_count,
    collected_comments,
    rejected_duplicate_texts=None,
    missing_tasks=None,
):
    """在原提示词后追加补齐要求，请求模型只生成尚缺少的评论。"""
    collected_texts = [comment["text"] for comment in collected_comments]
    duplicate_texts = list(
        rejected_duplicate_texts or []
    )[-RETRY_DUPLICATE_FEEDBACK_LIMIT:]
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：任务化补齐只请求尚未完成的角度任务。
    request_count = (
        remaining_count
        if missing_tasks is not None
        else remaining_count + COMMENT_BATCH_EXTRA_COUNT
    )
    task_requirement = ""
    if missing_tasks is not None:
        task_requirement = f"""
本次只能完成下列尚未完成的角度任务，每个 task_id 恰好返回一条评论：
{json.dumps(missing_tasks, ensure_ascii=False, indent=2)}
不得返回已经完成或任务列表之外的 task_id。
""".strip()
    return f"""
{original_prompt}

【本次补齐要求】
以下数量要求优先于原提示词中的数量要求。
前一次返回的有效评论数量不足，还缺 {remaining_count} 条有效评论。
本次请生成 {request_count} 条评论，系统校验后只接收缺少的数量。
{task_requirement}
不得重复下列已经接收的评论：
{json.dumps(collected_texts, ensure_ascii=False)}
前几次请求中，下列评论已被系统判定为历史重复文本：
{json.dumps(duplicate_texts, ensure_ascii=False)}
不得再次生成上述重复文本，也不得只替换少量词语复述；请更换人物立场、关注点或表达角度。
输出格式仍必须与上面的 JSON 格式完全一致。
""".strip()


# 2026/08/24 增量评论稳定补齐，新增功能：将批次尝试次数和过滤统计返回给增量评论记录。
def update_comment_generation_stats(
    generation_stats,
    expected_count,
    attempt_count,
    raw_comment_count,
    collected_comments,
    rejection_counts,
    validation_errors,
):
    """按需写入一批评论的生成统计，不改变原有评论返回结构。"""
    if generation_stats is None:
        return
    generation_stats.clear()
    generation_stats.update(
        {
            "expected_count": expected_count,
            "attempt_count": attempt_count,
            "raw_comment_count": raw_comment_count,
            "accepted_comment_count": len(collected_comments),
            "rejection_counts": dict(rejection_counts),
            "validation_errors": list(validation_errors),
        }
    )


# 2026/08/22 增量评论累积对齐：重试时保留已获得的有效评论，仅继续补齐剩余数量。
# 2026/08/23 评论派系覆盖对齐，修改功能：批次生成支持传入允许接收的评论派系。
# 2026/08/24 增量评论第二次修改，修改功能：增加补齐次数并在失败信息中输出过滤原因。
# 2026/08/24 增量评论兜底机制，修改功能：仅允许增量评论在重试结束后返回部分有效结果。
# 2026/08/24 增量评论稳定补齐，修改功能：增量批次可收集诊断信息，并在模型请求失败后交由本地补齐。
# 2026/08/26 第十次联调问题修复，修改功能：累积具体重复文本并传入后续补齐请求。
# 2026/08/26 第十一次联调问题修复，修改功能：支持同一轮多个子批次共享重复文本反馈。
# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：按角度任务累计有效评论并定向重试。
# 2026/09/04 增量评论生成架构优化，修改功能：允许调用方限制单批请求次数，初始评论仍沿用原重试配置。
def generate_valid_comment_batch(
    prompt,
    event_input,
    profiles,
    used_texts,
    expected_count,
    allowed_factions=None,
    allow_partial=False,
    generation_stats=None,
    rejected_duplicate_texts=None,
    comment_tasks=None,
    max_attempts=None,
):
    """累积生成一批有效评论，直到达到目标数量或超过重试次数。"""
    if not isinstance(expected_count, int) or expected_count <= 0:
        raise ValueError("expected_count 必须是正整数。")
    attempt_limit = (
        COMMENT_BATCH_RETRY_COUNT
        if max_attempts is None
        else max_attempts
    )
    if (
        isinstance(attempt_limit, bool)
        or not isinstance(attempt_limit, int)
        or attempt_limit <= 0
    ):
        raise ValueError("max_attempts 必须是正整数。")
    # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：批次生成可按程序分配的角度任务累计结果。
    normalized_tasks = (
        validate_comment_tasks(comment_tasks, expected_count)
        if comment_tasks is not None
        else None
    )

    collected_comments = []
    original_used_texts = set(used_texts)
    rejection_counts = {}
    if rejected_duplicate_texts is None:
        rejected_duplicate_texts = []
    elif not isinstance(rejected_duplicate_texts, list):
        raise ValueError("rejected_duplicate_texts 必须是列表。")
    validation_errors = []
    attempt_count = 0
    raw_comment_count = 0

    for attempt in range(1, attempt_limit + 1):
        attempt_count = attempt
        remaining_count = expected_count - len(collected_comments)
        completed_task_ids = {
            comment.get("task_id")
            for comment in collected_comments
            if comment.get("task_id")
        }
        missing_tasks = (
            [
                task
                for task in normalized_tasks
                if task["task_id"] not in completed_task_ids
            ]
            if normalized_tasks is not None
            else None
        )
        request_prompt = prompt
        if attempt > 1:
            request_prompt = build_comment_retry_prompt(
                prompt,
                remaining_count,
                collected_comments,
                rejected_duplicate_texts,
                missing_tasks,
            )

        try:
            raw_result = call_deepseek_json(
                prompt=request_prompt,
                system_prompt="你只能返回合法 JSON 对象，并且必须包含 comments 数组。",
                temperature=COMMENT_POOL_TEMPERATURE,
                max_tokens=COMMENT_POOL_MAX_TOKENS,
                # 2026/09/04 Demo性能基线，新增功能：标记初始和增量评论生成请求类型。
                request_type="comment_generation",
            )
            raw_comments = (
                raw_result.get("comments", [])
                if isinstance(raw_result, dict)
                else []
            )
            if isinstance(raw_comments, list):
                raw_comment_count += len(raw_comments)
            temporary_used_texts = original_used_texts | {
                comment["text"] for comment in collected_comments
            }
            new_comments = normalize_comments(
                raw_result,
                event_input,
                profiles,
                temporary_used_texts,
                allowed_factions,
                rejection_counts,
                rejected_duplicate_texts,
                missing_tasks,
            )
        except ValueError as error:
            new_comments = []
            validation_errors.append(str(error))
        except RuntimeError as error:
            if not allow_partial:
                raise
            validation_errors.append(str(error))
            break

        collected_comments.extend(new_comments[:remaining_count])
        if len(collected_comments) == expected_count:
            used_texts.update(
                comment["text"] for comment in collected_comments
            )
            update_comment_generation_stats(
                generation_stats,
                expected_count,
                attempt_count,
                raw_comment_count,
                collected_comments,
                rejection_counts,
                validation_errors,
            )
            return collected_comments

        shortage = (
            f"需要 {expected_count} 条，已累积 {len(collected_comments)} 条，"
            f"还缺 {expected_count - len(collected_comments)} 条"
        )
        filter_summary = json.dumps(rejection_counts, ensure_ascii=False)
        print(
            f"评论批次尚未补齐，第 {attempt}/{attempt_limit} 次："
            f"{shortage}；过滤统计：{filter_summary}"
        )

    shortage = (
        f"需要 {expected_count} 条，已累积 {len(collected_comments)} 条，"
        f"还缺 {expected_count - len(collected_comments)} 条"
    )
    filter_summary = json.dumps(rejection_counts, ensure_ascii=False)
    update_comment_generation_stats(
        generation_stats,
        expected_count,
        attempt_count,
        raw_comment_count,
        collected_comments,
        rejection_counts,
        validation_errors,
    )
    details = [shortage, f"过滤统计：{filter_summary}"]
    if validation_errors:
        details.append(f"最近一次生成错误：{validation_errors[-1]}")
    if allow_partial:
        used_texts.update(comment["text"] for comment in collected_comments)
        print(f"评论批次返回部分有效结果：{'；'.join(details)}")
        return collected_comments
    raise RuntimeError(f"评论批次重试后仍然失败：{'；'.join(details)}")


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：统计人物类型与评论派系组合供联调诊断。
def summarize_profile_faction_combinations(comments):
    """返回稳定排序的人物类型与评论派系组合数量。"""
    counts = {}
    labels = {}
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        profile_id = normalize_profile_id(comment.get("profile_id"))
        faction = comment.get("faction")
        if profile_id is None or faction not in FACTIONS:
            continue
        key = (profile_id, faction)
        counts[key] = counts.get(key, 0) + 1
        labels[profile_id] = str(comment.get("profile_label", "")).strip()

    return [
        {
            "profile_id": profile_id,
            "profile_label": labels.get(profile_id, ""),
            "faction": faction,
            "count": counts[(profile_id, faction)],
        }
        for profile_id, faction in sorted(
            counts,
            key=lambda item: (item[0], FACTIONS.index(item[1])),
        )
    ]
