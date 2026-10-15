"""历史趋势复现的逐轮公众语境读取与校验。

该文件中的内容是历史回放的显式条件，不是模型预测结果。它可以包含当时
已经出现的公众议题、未解决疑问和建设性证据，但不得包含每轮情绪比例或
把后续阶段的信息提前写入当前轮。公众语境只约束当轮可见信息，Agent 的
情绪与官方态度仍由 LLM 结合 Persona、评论和当前证据直接判断。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from infrastructure.json_storage import load_json
from simulation.evidence_policy import (
    EVIDENCE_STRENGTHS,
    OBJECTIVE_EVIDENCE_STRENGTHS,
    VERIFIED_UPDATE_KINDS,
    normalize_evidence_strength,
    verified_update_strength,
)


PUBLIC_CONTEXT_STATUSES = {
    "public_question",
    "unverified_claim",
    "ongoing_discussion",
    "social_action",
}


def _find_forbidden_fields(value, forbidden_fields):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden_fields:
                found.add(key)
            found.update(_find_forbidden_fields(child, forbidden_fields))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_fields(child, forbidden_fields))
    return found


def _normalize_source_refs(value, field_name):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name}.source_refs 必须是非空字符串数组。")
    refs = [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]
    if len(refs) != len(value):
        raise ValueError(f"{field_name}.source_refs 必须是非空字符串数组。")
    return refs


def _normalize_evidence_list(items, *, step, kind):
    if not isinstance(items, list):
        raise ValueError(f"公众语境第 {step} 轮的 {kind} 必须是数组。")
    id_field = {
        "verified_updates": "evidence_id",
        "public_discourse": "context_id",
        "positive_evidence": "evidence_id",
    }[kind]
    normalized = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"公众语境第 {step} 轮 {kind} 第 {position} 项必须是对象。"
            )
        evidence_id = str(item.get(id_field, "")).strip()
        content = str(item.get("content", "")).strip()
        if not evidence_id or not content:
            raise ValueError(
                f"公众语境第 {step} 轮 {kind} 第 {position} 项缺少编号或内容。"
            )
        record = {
            id_field: evidence_id,
            "content": content,
            "source_refs": _normalize_source_refs(
                item.get("source_refs"),
                f"公众语境 {evidence_id}",
            ),
        }
        if kind == "verified_updates":
            update_kind = str(
                item.get("update_kind", "procedural_update")
            ).strip()
            if update_kind not in VERIFIED_UPDATE_KINDS:
                raise ValueError(
                    f"公众语境 {evidence_id} 的 update_kind 不合法："
                    f"{update_kind}"
                )
            explicit_strength = item.get("evidence_strength")
            if (
                explicit_strength is not None
                and explicit_strength not in OBJECTIVE_EVIDENCE_STRENGTHS
            ):
                raise ValueError(
                    f"公众语境 {evidence_id} 的 evidence_strength 不合法："
                    f"{explicit_strength}"
                )
            record["update_kind"] = update_kind
            record["evidence_strength"] = verified_update_strength(item)
            record["evidence_target"] = str(
                item.get("evidence_target", "fact_clarification")
            ).strip() or "fact_clarification"
            record["claim_id"] = str(
                item.get("claim_id", evidence_id)
            ).strip() or evidence_id
        if kind == "public_discourse":
            status = str(item.get("status", "")).strip()
            if status not in PUBLIC_CONTEXT_STATUSES:
                raise ValueError(
                    f"公众语境 {evidence_id} 的 status 不合法：{status}"
                )
            record["status"] = status
            record["unresolved_concern"] = bool(
                item.get("unresolved_concern", False)
            )
        if kind == "positive_evidence":
            target = str(item.get("target", "")).strip()
            if not target:
                raise ValueError(f"公众语境 {evidence_id} 缺少 target。")
            record["target"] = target
            explicit_strength = item.get("evidence_strength")
            if (
                explicit_strength is not None
                and explicit_strength not in EVIDENCE_STRENGTHS
            ):
                raise ValueError(
                    f"公众语境 {evidence_id} 的 evidence_strength 不合法："
                    f"{explicit_strength}"
                )
            record["evidence_strength"] = normalize_evidence_strength(
                explicit_strength,
                "moderate",
            )
        normalized.append(record)
    return normalized


# 2026/10/10，修改功能：主线恢复为 LLM 直接判断；逐轮公众语境仅提供
# 当时可见的文字证据，校验器继续拒绝隐藏的数值拟合目标。
def validate_public_context_timeline(
    payload,
    expected_event_id=None,
    expected_total_steps=None,
):
    """校验逐轮公众语境，并返回不共享引用的规范化副本。"""

    if not isinstance(payload, dict):
        raise ValueError("public_context_timeline.json 必须是JSON对象。")
    event_id = str(payload.get("event_id", "")).strip()
    if not event_id:
        raise ValueError("公众语境缺少 event_id。")
    if expected_event_id is not None and event_id != expected_event_id:
        raise ValueError("公众语境与事件编号不一致。")
    if payload.get("schema_version", 1) != 1:
        raise ValueError("公众语境仅支持 schema_version=1。")

    forbidden_fields = {
        "emotion_targets",
        "observed_distribution",
        "negative_rate",
        "neutral_rate",
        "positive_rate",
    }
    leaked = _find_forbidden_fields(payload, forbidden_fields)
    if leaked:
        raise ValueError(
            "公众语境不能包含逐轮数值拟合目标："
            + "、".join(sorted(leaked))
        )

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("公众语境必须包含非空 steps 数组。")
    steps = []
    seen_steps = set()
    seen_ids = set()
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValueError("公众语境的每个阶段必须是JSON对象。")
        step = raw_step.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("公众语境 step 必须是正整数。")
        if step in seen_steps:
            raise ValueError(f"公众语境存在重复 step：{step}")
        period = str(raw_step.get("period", "")).strip()
        phase = str(raw_step.get("phase", "")).strip()
        if not period or not phase:
            raise ValueError(f"公众语境第 {step} 轮缺少 period 或 phase。")
        record = {"step": step, "period": period, "phase": phase}
        for kind in (
            "verified_updates",
            "public_discourse",
            "positive_evidence",
        ):
            record[kind] = _normalize_evidence_list(
                raw_step.get(kind, []), step=step, kind=kind
            )
            id_field = "context_id" if kind == "public_discourse" else "evidence_id"
            for item in record[kind]:
                evidence_id = item[id_field]
                if evidence_id in seen_ids:
                    raise ValueError(f"公众语境编号重复：{evidence_id}")
                seen_ids.add(evidence_id)
        steps.append(record)
        seen_steps.add(step)

    steps.sort(key=lambda item: item["step"])
    if expected_total_steps is not None:
        expected = set(range(1, expected_total_steps + 1))
        if seen_steps != expected:
            raise ValueError(
                "公众语境必须完整覆盖历史时间线："
                f"期望 {sorted(expected)}，实际 {sorted(seen_steps)}"
            )
    return {"schema_version": 1, "event_id": event_id, "steps": steps}


def load_public_context_timeline(
    path,
    expected_event_id=None,
    expected_total_steps=None,
):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"公众语境不存在：{path}")
    return validate_public_context_timeline(
        load_json(path),
        expected_event_id=expected_event_id,
        expected_total_steps=expected_total_steps,
    )


def get_public_context_for_step(timeline, step):
    for item in timeline.get("steps", []):
        if item.get("step") == step:
            return deepcopy(item)
    raise ValueError(f"公众语境缺少第 {step} 轮。")
