"""历史复现证据的稳定标识与正面资格规则。

本模块只根据当前仿真状态构造证据元数据，不读取真实趋势、人工情绪比例
或文件系统。Agent 与评论生成器共用这里的规则，避免同一官方通告在不同
模块中获得不同的时间语义。
"""

from __future__ import annotations

import re


EVIDENCE_STRENGTHS = {
    "background",
    "weak",
    "moderate",
    "strong",
}

OBJECTIVE_EVIDENCE_STRENGTHS = {
    "background",
    "moderate",
    "strong",
}

VERIFIED_UPDATE_KINDS = {
    "status_continuation",
    "procedural_update",
    "confirmed_fact",
    "final_conclusion",
}

VERIFIED_UPDATE_DEFAULT_STRENGTH = {
    "status_continuation": "background",
    "procedural_update": "moderate",
    "confirmed_fact": "strong",
    "final_conclusion": "strong",
}

POSITIVE_OBJECTIVE_EVENT_TYPES = {
    "search_action",
    "investigation_action",
    "forensic_action",
    "social_support",
}

STRONG_OBJECTIVE_EVENT_TYPES = {
    "identity_confirmation",
    "key_forensic_result",
    "final_conclusion",
}

BACKGROUND_OBJECTIVE_EVENT_TYPES = {
    "status_continuation",
    "pending_investigation",
    "continued_discussion",
}


def normalize_evidence_strength(value: object, default: str) -> str:
    """返回合法证据强度，调用方必须显式提供安全默认值。"""

    strength = str(value or "").strip()
    if strength in EVIDENCE_STRENGTHS:
        return strength
    if default not in EVIDENCE_STRENGTHS:
        raise ValueError(f"非法的默认证据强度：{default}")
    return default


def verified_update_strength(item: dict | None) -> str:
    """确定已核实更新的客观强度。

    2026/10/12，修改功能：不再把 ``verified_updates`` 全部视为强证据。
    事件数据可显式声明强度；旧数据缺少元数据时按普通阶段进展处理，
    避免“调查仍在继续”等状态描述触发全体 Agent 重新判断。
    """

    record = item if isinstance(item, dict) else {}
    update_kind = str(record.get("update_kind", "")).strip()
    default = VERIFIED_UPDATE_DEFAULT_STRENGTH.get(
        update_kind,
        "moderate",
    )
    return normalize_evidence_strength(
        record.get("evidence_strength"),
        default,
    )


def objective_event_strength(event_type: object, explicit=None) -> str:
    """按客观事件语义返回强度；未知类型保守按阶段性进展处理。"""

    event_type = str(event_type or "").strip()
    if event_type in STRONG_OBJECTIVE_EVENT_TYPES:
        default = "strong"
    elif event_type in BACKGROUND_OBJECTIVE_EVENT_TYPES:
        default = "background"
    else:
        default = "moderate"
    return normalize_evidence_strength(explicit, default)


def official_statement_strength(
    statement_status: object,
    is_new: bool,
    explicit=None,
) -> str:
    """区分持续声明、阶段性声明与结论性声明。

    新声明只表示本轮首次发布，并不天然等于强证据。``clear`` 仅表示内容
    已形成明确表述，不等于获得独立印证或必然可信；没有显式强度时统一按
    阶段性证据处理。已核实结论仍可由 ``verified_updates`` 单独标为强证据。
    """

    if not is_new:
        return "background"
    # 2026/10/14，修改功能：解除“通告清晰=强证据=应当接受”的隐式耦合。
    default = "moderate"
    return normalize_evidence_strength(explicit, default)


def build_official_statement_evidence(current_state: dict | None) -> dict | None:
    """返回当前官方通告的稳定证据；没有有效通告时返回 ``None``。

    2026/10/9，历史复现低风险加固：证据编号绑定首次发布轮次，而不是
    当前轮次；持续通告只作为背景，不重复获得正面证据资格。
    """

    state = current_state if isinstance(current_state, dict) else {}
    statement = str(state.get("official_statement", "")).strip()
    status = str(state.get("official_statement_status", "none")).strip()
    current_step = state.get("step")
    if not statement or status == "none":
        return None

    timing = state.get("official_statement_timing")
    timing = timing if isinstance(timing, dict) else {}
    introduced_step = timing.get("introduced_step")
    if not isinstance(introduced_step, int) or introduced_step < 1:
        introduced_step = current_step
    is_new = timing.get("is_new")
    if not isinstance(is_new, bool):
        is_new = introduced_step == current_step
    active_round_count = timing.get("active_round_count")
    if not isinstance(active_round_count, int) or active_round_count < 1:
        active_round_count = (
            current_step - introduced_step + 1
            if isinstance(current_step, int)
            and isinstance(introduced_step, int)
            else 1
        )

    return {
        "evidence_id": f"official_statement_step_{introduced_step}",
        "evidence_type": "official_statement",
        "content": statement,
        "statement_status": status,
        "evidence_target": "official_response",
        "introduced_step": introduced_step,
        "active_round_count": active_round_count,
        "is_new": is_new,
        "evidence_strength": official_statement_strength(
            status,
            is_new,
            timing.get("evidence_strength"),
        ),
        "positive_eligible": is_new,
    }


def _official_clause_target(content: str) -> str:
    """按通告片段的可观察语义标注作用对象，不推断未写明的结论。"""

    if any(word in content for word in ("责任", "追责", "处分", "问责", "道歉")):
        return "process_accountability"
    if any(word in content for word in ("搜寻", "救援", "帮助", "救助")):
        return "social_action"
    if any(word in content for word in ("调查", "核查", "立案", "处理", "工作")):
        return "investigation_process"
    if any(word in content for word in ("确认", "认定", "鉴定", "经查", "发现", "身份")):
        return "fact_clarification"
    return "official_response"


def build_official_statement_evidence_units(
    current_state: dict | None,
) -> list[dict]:
    """把新通告拆成少量可引用证据点，供不同 Persona 分别关注。

    2026/10/13，新增功能：通告仍对所有 Agent 完整广播，但不再只能作为
    一个不可区分的整体发挥作用。所有片段共享同一 ``evidence_group_id``，
    所以同一通告不会被重复计为多条独立证据。
    """

    parent = build_official_statement_evidence(current_state)
    if parent is None:
        return []
    content = str(parent.get("content", "")).strip()
    clauses = [
        clause.strip(" ，,。；;！？!?\n\r\t")
        for clause in re.split(r"[。；;！？!?\n]+", content)
        if clause.strip(" ，,。；;！？!?\n\r\t")
    ]
    if len(clauses) == 1 and len(clauses[0]) > 100:
        clauses = [
            clause.strip(" ，,")
            for clause in re.split(r"[，,]+", clauses[0])
            if clause.strip(" ，,")
        ]
    if len(clauses) <= 1:
        return []
    if len(clauses) > 6:
        clauses = clauses[:5] + ["；".join(clauses[5:])]

    group_id = parent["evidence_id"]
    units = []
    for index, clause in enumerate(clauses, start=1):
        units.append(
            {
                **parent,
                "evidence_id": f"{group_id}_part_{index}",
                "evidence_type": "official_statement_unit",
                "evidence_group_id": group_id,
                "content": clause,
                "evidence_target": _official_clause_target(clause),
                "statement_part_index": index,
            }
        )
    return units


def objective_event_is_positive_eligible(event_type: object) -> bool:
    """判断一种客观事件是否可支撑建设性、希望或行动认可。"""

    return str(event_type or "") in POSITIVE_OBJECTIVE_EVENT_TYPES
