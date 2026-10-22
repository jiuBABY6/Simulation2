"""评论语义与传播来源的统一契约。

2026/10/19，新增功能：把“评论谈论的对象”“在证据链中的作用”与
“内容来自哪类主体”从情绪标签中拆开。现有 ``source_type`` 曾同时表示
生成兜底、邻居传播等技术路径，因此本模块使用 ``provenance_type`` 保存
技术来源，并使用 ``information_source_type`` 保存现实语义来源，避免破坏
旧实验数据和传播代码。

本模块只做确定性规范化，不读取文件、不调用大模型，也不推断具体事实
真伪。旧评论缺少字段时使用保守默认值：公众观点不会被升级为事实证据。
"""

from __future__ import annotations

from copy import deepcopy


REACTION_TARGETS = {
    "event_harm",
    "official_claim",
    "investigation_process",
    "accountability",
    "victim_support",
    "public_discourse",
    "social_action",
    # 兼容现有事件与历史复现证据目标。
    "event_outcome",
    "official_response",
    "process_accountability",
    "fact_clarification",
    "identity_confirmation",
    "forensic_result",
}

EVIDENCE_ROLES = {
    "support",
    "contradict",
    "question",
    "opinion",
    "background",
    "clarify",
}

INFORMATION_SOURCE_TYPES = {
    "official",
    "media",
    "expert",
    "witness",
    "public",
    "agent",
    "event",
}

INFORMATION_ORIGINS = {"exogenous", "endogenous"}

# 旧字段值描述的是系统内部生成/传播路径，而不是现实中的信息主体。
LEGACY_PROVENANCE_TO_SOURCE = {
    "official_statement": "official",
    "event": "event",
    "event_input": "event",
    "agent_original_expression": "agent",
    "neighbor_propagation": "agent",
    "repost_fallback": "public",
    "local_emergency_fallback": "public",
    "llm_generated": "public",
    "visible_comment": "public",
}

ENDOGENOUS_PROVENANCE_TYPES = {
    "agent_original_expression",
    "neighbor_propagation",
    "agent_reshare",
}


def _normalized_enum(value, allowed, default):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def infer_reaction_target(comment: dict) -> str:
    """保守推断评论对象；无法确定时只视为公共讨论。"""

    explicit = (
        comment.get("reaction_target")
        or comment.get("emotion_target")
        or comment.get("evidence_target")
    )
    normalized = str(explicit or "").strip()
    if normalized in REACTION_TARGETS:
        return normalized

    angle_id = str(comment.get("angle_id", "")).strip()
    if angle_id in {"official_completeness", "official_credibility"}:
        return "official_claim"
    if angle_id == "official_follow_up":
        return "investigation_process"
    if comment.get("generation_trigger") == "initial_event":
        return "event_harm"
    return "public_discourse"


def infer_evidence_role(comment: dict, information_source_type: str) -> str:
    """推断信息作用；公众支持性表达仍是观点，不自动成为事实证据。"""

    explicit = _normalized_enum(
        comment.get("evidence_role"),
        EVIDENCE_ROLES,
        "",
    )
    if explicit:
        return explicit
    if comment.get("unresolved_concern") is True:
        return "question"

    stance = str(comment.get("stance", "")).strip().lower()
    orientation = str(comment.get("orientation", "")).strip().lower()
    if stance == "questioning" or orientation == "questioning":
        return "question"
    if stance == "criticism":
        return "opinion"
    if information_source_type in {"official", "event"}:
        return "clarify"
    return "opinion"


def infer_information_source_type(comment: dict, default="public") -> str:
    """从新字段或旧技术来源中恢复现实语义来源。"""

    explicit = _normalized_enum(
        comment.get("information_source_type"),
        INFORMATION_SOURCE_TYPES,
        "",
    )
    if explicit:
        return explicit
    provenance = str(
        comment.get("provenance_type")
        or comment.get("source_type")
        or ""
    ).strip()
    return LEGACY_PROVENANCE_TO_SOURCE.get(
        provenance,
        _normalized_enum(default, INFORMATION_SOURCE_TYPES, "public"),
    )


def infer_information_origin(comment: dict, provenance_type: str) -> str:
    """区分外部环境输入与Agent互动产生的内生表达。"""

    explicit = _normalized_enum(
        comment.get("information_origin"),
        INFORMATION_ORIGINS,
        "",
    )
    if explicit:
        return explicit
    source_type = infer_information_source_type(comment)
    if provenance_type in ENDOGENOUS_PROVENANCE_TYPES or source_type == "agent":
        return "endogenous"
    return "exogenous"


def normalize_comment_semantics(
    comment: dict,
    *,
    default_information_source="public",
    default_provenance=None,
) -> dict:
    """返回带完整语义字段的评论副本，兼容旧评论格式。"""

    if not isinstance(comment, dict):
        raise TypeError("comment 必须是字典。")
    normalized = deepcopy(comment)
    legacy_source = str(comment.get("source_type", "")).strip()
    provenance_type = str(
        comment.get("provenance_type")
        or default_provenance
        or legacy_source
        or "unspecified"
    ).strip()
    information_source_type = infer_information_source_type(
        comment,
        default_information_source,
    )
    normalized["provenance_type"] = provenance_type
    normalized["information_source_type"] = information_source_type
    normalized["information_origin"] = infer_information_origin(
        comment,
        provenance_type,
    )
    normalized["reaction_target"] = infer_reaction_target(comment)
    normalized["evidence_role"] = infer_evidence_role(
        comment,
        information_source_type,
    )

    claim_id = comment.get("claim_id")
    if claim_id is None:
        evidence_ids = comment.get("evidence_ids")
        if isinstance(evidence_ids, list) and len(evidence_ids) == 1:
            claim_id = evidence_ids[0]
    normalized["claim_id"] = (
        str(claim_id).strip() if claim_id is not None and str(claim_id).strip() else None
    )

    root_id = comment.get("root_id")
    if not root_id:
        root_ids = comment.get("root_expression_ids")
        if isinstance(root_ids, list) and root_ids:
            root_id = root_ids[0]
    if not root_id:
        root_id = comment.get("comment_id") or comment.get("task_id")
    normalized["root_id"] = str(root_id).strip() if root_id else None
    return normalized


def normalize_evidence_semantics(evidence: dict) -> dict:
    """为状态证据补齐同一套语义字段，不改变已有强度和个体评分。"""

    evidence_type = str(evidence.get("evidence_type", ""))
    if evidence_type.startswith("official"):
        default_source = "official"
    elif evidence_type in {"objective_event", "historical_verified_update"}:
        default_source = "event"
    else:
        default_source = "public"
    normalized = normalize_comment_semantics(
        evidence,
        default_information_source=default_source,
        default_provenance=evidence_type or "evidence",
    )
    if evidence.get("evidence_target"):
        normalized["reaction_target"] = infer_reaction_target(evidence)
    normalized["evidence_target"] = normalized["reaction_target"]
    return normalized
