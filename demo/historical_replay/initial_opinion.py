"""历史复现第一轮人工舆论初始条件。

本模块只校验事件级初始条件并把情绪配额确定性地分配给评论任务，
不接收公众反应摘要、不调用大模型，也不改变普通实验的评论生成规则。
"""

from copy import deepcopy


EMOTION_NAMES = ("negative", "neutral", "positive")
SUPPORTED_MODE = "historical_calibration"
ALLOWED_FIELDS = {
    "schema_version",
    "event_id",
    "step",
    "mode",
    "comment_count",
    "emotion_targets",
    "observed_distribution",
    "source",
    "evaluation_role",
}


# 2026/10/8，新增功能：校验人工第一轮数据，只允许其作为历史复现初始条件。
def validate_initial_opinion(
    payload,
    expected_event_id=None,
    expected_comment_count=None,
):
    """返回规范化的历史初始条件，非法配置直接拒绝运行。"""
    if not isinstance(payload, dict):
        raise ValueError("initial_opinion.json 必须是JSON对象。")

    event_id = str(payload.get("event_id", "")).strip()
    if not event_id:
        raise ValueError("initial_opinion.json 缺少 event_id。")
    if expected_event_id is not None and event_id != expected_event_id:
        raise ValueError(
            "initial_opinion.json 与事件输入的 event_id 不一致："
            f"{event_id} != {expected_event_id}"
        )

    schema_version = payload.get("schema_version", 1)
    if schema_version != 1:
        raise ValueError("initial_opinion.json 只支持 schema_version=1。")
    if payload.get("step") != 1:
        raise ValueError("人工舆论初始条件只能用于第1轮。")
    if payload.get("mode") != SUPPORTED_MODE:
        raise ValueError(
            f"initial_opinion.json 的 mode 必须为 {SUPPORTED_MODE}。"
        )
    if payload.get("evaluation_role") != "initial_condition":
        raise ValueError(
            "initial_opinion.json 的 evaluation_role 必须为 initial_condition。"
        )

    comment_count = payload.get("comment_count")
    if (
        isinstance(comment_count, bool)
        or not isinstance(comment_count, int)
        or comment_count <= 0
    ):
        raise ValueError("initial_opinion.json 的 comment_count 必须是正整数。")
    if (
        expected_comment_count is not None
        and comment_count != expected_comment_count
    ):
        raise ValueError(
            "人工舆论初始条件的评论数与系统配置不一致："
            f"{comment_count} != {expected_comment_count}"
        )

    raw_targets = payload.get("emotion_targets")
    if not isinstance(raw_targets, dict):
        raise ValueError("initial_opinion.json 缺少 emotion_targets。")
    unknown_emotions = set(raw_targets) - set(EMOTION_NAMES)
    if unknown_emotions:
        raise ValueError(
            "emotion_targets 包含未知情绪："
            + ", ".join(sorted(unknown_emotions))
        )

    targets = {}
    for emotion in EMOTION_NAMES:
        value = raw_targets.get(emotion, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"emotion_targets.{emotion} 必须是非负整数。")
        targets[emotion] = value
    if sum(targets.values()) != comment_count:
        raise ValueError(
            "emotion_targets 总数必须等于 comment_count："
            f"{sum(targets.values())} != {comment_count}"
        )

    # 2026/10/9，修改功能：第一轮只接收人工情绪比例，公众反应摘要不再进入提示词。
    if "public_discourse_context" in payload:
        raise ValueError(
            "initial_opinion.json 不能包含 public_discourse_context；"
            "第一轮只允许使用人工情绪比例。"
        )
    unknown_fields = set(payload) - ALLOWED_FIELDS
    if unknown_fields:
        raise ValueError(
            "initial_opinion.json 包含不允许的字段："
            + "、".join(sorted(unknown_fields))
        )
    observed_distribution = payload.get("observed_distribution", {})
    if not isinstance(observed_distribution, dict):
        raise ValueError("observed_distribution 必须是JSON对象。")
    source = payload.get("source", {})
    if not isinstance(source, dict):
        raise ValueError("initial_opinion.json 的 source 必须是JSON对象。")

    normalized = {
        "schema_version": 1,
        "event_id": event_id,
        "step": 1,
        "mode": SUPPORTED_MODE,
        "comment_count": comment_count,
        "emotion_targets": targets,
        "observed_distribution": deepcopy(observed_distribution),
        "source": deepcopy(source),
        "evaluation_role": "initial_condition",
    }
    return normalized
