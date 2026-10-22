"""回应方案实验的 Persona 状态转换约束。

2026/10/18，新增功能：把“个人看见了邻居表达”与“邻居表达足以改变
内部状态”分开。同日修改功能：状态转换改由方向性证据效用整合器
最终裁决，避免“弱证据覆盖Persona”和“中等证据永远不可能生效”
两个极端。模块只使用调用方提供的 Persona、上一轮状态和证据，
不读取文件、不调用 LLM，也不设置任何群体比例目标。
"""

from __future__ import annotations

from agents.decision_profile import build_persona_decision_profile
from agents.evidence_appraisal import appraise_evidence_for_persona
from agents.official_attitude import resolve_official_attitude
from agents.strategy_evidence_integrator import (
    is_neighbor_evidence,
    resolve_strategy_emotion,
)
from agents.strategy_attitude_lifecycle import prepare_attitude_evidence
from domain.comment_semantics import normalize_evidence_semantics


EMOTION_LEVELS = {"negative": -1, "neutral": 0, "positive": 1}
OFFICIAL_ATTITUDES = {"accept", "wait", "question"}
OFFICIAL_EVIDENCE_TARGETS = {
    "official_claim",
    "accountability",
    "official_response",
    "investigation_process",
    "process_accountability",
    "fact_clarification",
    "event_outcome",
    "identity_confirmation",
    "forensic_result",
}
FACT_EVIDENCE_TARGETS = {
    "official_claim",
    "fact_clarification",
    "event_outcome",
    "identity_confirmation",
    "forensic_result",
}


def _bounded(value, default=0.0):
    """将数值安全限制在0到1。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _official_attitude_items(appraised_evidence):
    """普通舆情评论不能单靠数量改变对官方事实的接受判断。"""

    return [
        item
        for item in appraised_evidence
        if (
            item.get("evidence_type") != "simulated_comment"
            or item.get("evidence_target") in OFFICIAL_EVIDENCE_TARGETS
        )
    ]


def _initial_attitude_options(
    profile,
    attitude_items,
    base_attitude_options,
):
    """首次看到通告时按Persona开放不同候选，避免所有人同步接受。"""

    allowed = set(base_attitude_options)
    options = ["wait"] if "wait" in allowed else []
    orientation = profile.get("orientation", {})
    fact = _bounded(orientation.get("fact"), 1 / 3)
    questioning = _bounded(orientation.get("questioning"), 1 / 3)
    substantive_official = any(
        item.get("evidence_type")
        in {"official_statement", "official_statement_unit"}
        and item.get("is_new_this_step") is True
        and item.get("evidence_strength") in {"moderate", "strong"}
        for item in attitude_items
    )
    has_concern = any(
        item.get("unresolved_concern") is True
        for item in attitude_items
    )
    has_claim_support = any(
        item.get("evidence_target") in FACT_EVIDENCE_TARGETS
        and item.get("is_new_this_step") is True
        and item.get("evidence_strength") in {"moderate", "strong"}
        for item in attitude_items
    )
    if (
        "accept" in allowed
        and substantive_official
        and has_claim_support
        and fact >= 0.58
        and fact >= questioning + 0.05
    ):
        options.append("accept")
    if (
        "question" in allowed
        and questioning >= 0.58
        and (has_concern or (substantive_official and not has_claim_support))
    ):
        options.append("question")
    return options or list(base_attitude_options)


def _build_compact_evidence_catalog(
    appraised_evidence,
    evidence_direction_by_id=None,
):
    """按证据组压缩提示词目录，消除通告分句数量造成的隐性权重。"""

    grouped = {}
    evidence_direction_by_id = evidence_direction_by_id or {}
    for item in appraised_evidence:
        evidence_id = str(item.get("evidence_id", "")).strip()
        if not evidence_id:
            continue
        group_id = str(item.get("evidence_group_id", evidence_id))
        entry = grouped.setdefault(
            group_id,
            {
                "evidence_group_id": group_id,
                "member_count": 0,
                "evidence_targets": [],
                "representative": None,
                "representative_score": -1.0,
            },
        )
        entry["member_count"] += 1
        target = item.get("evidence_target")
        if target and target not in entry["evidence_targets"]:
            entry["evidence_targets"].append(target)
        impact = item.get("personal_impact", {})
        score = max(
            _bounded(impact.get("emotion_score")),
            _bounded(impact.get("official_attitude_score")),
        )
        if score > entry["representative_score"]:
            entry["representative_score"] = score
            entry["representative"] = item

    catalog = []
    for entry in grouped.values():
        item = entry["representative"]
        catalog.append(
            {
                "evidence_id": item.get("evidence_id"),
                "evidence_group_id": entry["evidence_group_id"],
                "evidence_member_count": entry["member_count"],
                "evidence_type": item.get("evidence_type"),
                "comment_source": item.get("comment_source"),
                "evidence_targets": entry["evidence_targets"],
                "reaction_target": item.get(
                    "reaction_target", item.get("evidence_target")
                ),
                "evidence_role": item.get("evidence_role", "opinion"),
                "information_source_type": item.get(
                    "information_source_type", "public"
                ),
                "information_origin": item.get(
                    "information_origin", "exogenous"
                ),
                "claim_id": item.get("claim_id"),
                "evidence_strength": item.get("evidence_strength"),
                "is_new_this_step": item.get("is_new_this_step"),
                "neighbor_opinion": is_neighbor_evidence(item),
                # 2026/10/18，修改功能：提示词不再向LLM同时展示
                # “同伴信号已生效”与“每条都hold_only”的矛盾信息。
                # 强度分数依然可审计，状态方向以新整合器输出为准。
                "personal_impact": {
                    key: value
                    for key, value in item.get("personal_impact", {}).items()
                    if key
                    not in {
                        "emotion_change_mode",
                        "official_attitude_change_mode",
                    }
                },
                "directional_appraisal": evidence_direction_by_id.get(
                    str(item.get("evidence_id", "")),
                    {},
                ),
            }
        )
    return catalog


def build_strategy_state_prompt_guard(guard):
    """返回可进入LLM提示词的约束，隐藏规则层预判结论。"""

    return {
        "guard_version": guard.get("guard_version"),
        "emotion_transition": {
            key: value
            for key, value in guard.get("emotion_transition", {}).items()
            if key
            not in {
                "evidence_direction_by_id",
                "directional_evidence_groups",
            }
        },
        "decision_rule": guard.get("decision_rule"),
        # 官方态度的合法候选由顶层official_attitude_options给出。
        # 不把规则层的recommended attitude发送给LLM，避免候选虽有
        # 差异但模型仍机械跟随同一个预判值。
        "official_attitude_rule": (
            "根据Persona和本轮声明证据在合法候选中独立判断；"
            "没有反对不等于接受。"
        ),
    }


def build_strategy_state_guard(
    persona,
    policy,
    event_context,
    previous_state,
    current_evidence,
    base_emotion_options,
    base_attitude_options,
):
    """返回策略状态候选、Persona门槛和可审计诊断。"""

    profile = build_persona_decision_profile(
        persona,
        policy,
        event_context,
    )
    # 2026/10/19，修改功能：状态入口统一补齐评论目标、证据角色与来源。
    # 这样无论证据来自标准决策流程、离线测试还是旧版中间结果，情绪与
    # 官方态度两条判定链看到的都是同一份语义，而不依赖上游是否恰好补齐字段。
    normalized_evidence = [
        normalize_evidence_semantics(item)
        for item in current_evidence
        if isinstance(item, dict)
    ]
    appraised_evidence = appraise_evidence_for_persona(
        normalized_evidence,
        persona,
        event_context,
        previous_state,
        profile,
    )
    emotion_guard = resolve_strategy_emotion(
        profile,
        previous_state,
        appraised_evidence,
        base_emotion_options,
        current_step=event_context.get("current_state", {}).get("step"),
    )

    status = event_context.get("current_state", {}).get(
        "official_statement_status",
        "none",
    )
    attitude_lifecycle = prepare_attitude_evidence(
        previous_state,
        event_context.get("current_state", {}).get("step"),
        _official_attitude_items(appraised_evidence),
    )
    attitude_items = attitude_lifecycle["evidence_items"]
    attitude_resolution = resolve_official_attitude(
        attitude_items,
        profile,
        previous_state,
        status,
        base_attitude_options,
    )
    previous_attitude = (previous_state or {}).get("official_attitude")
    if status == "none":
        attitude_options = ["not_applicable"]
    elif previous_attitude not in OFFICIAL_ATTITUDES:
        attitude_options = _initial_attitude_options(
            profile,
            attitude_items,
            base_attitude_options,
        )
    else:
        # 通告持续有效但没有新增证据时，专用态度解析器会返回上一轮；
        # 有新增事实或关切时也只开放其经过Persona门槛后的裁决结果。
        attitude_options = [attitude_resolution["official_attitude"]]

    # 2026/10/18，修改功能：逐条方向只用于构造紧凑证据目录，不再
    # 重复挂到状态守卫和诊断记录中。这样保留可审计性，同时避免每名
    # Agent、每轮把同一份内部映射序列化两次。
    evidence_direction_by_id = emotion_guard.pop(
        "evidence_direction_by_id",
        {},
    )
    # 2026/10/19，新增功能：生命周期记忆属于本地状态，不进入LLM提示词
    # 和逐条证据目录。它随最终决策写入下一轮 previous_state，使决策
    # 核心继续保持无文件依赖。
    evidence_memory = emotion_guard.pop(
        "strategy_evidence_memory",
        {},
    )
    # 2026/10/20，新增功能：权威证据的渐进吸收记忆只在本地状态链中
    # 流转，不进入LLM提示词。公开情绪仍是离散值，记忆仅解释为什么
    # 不同Persona会在相邻数轮内以不同速度处理同一份通告。
    evidence_assimilation = emotion_guard.pop(
        "strategy_evidence_assimilation",
        {},
    )
    evidence_catalog = _build_compact_evidence_catalog(
        appraised_evidence,
        evidence_direction_by_id,
    )
    return {
        "guard_version": "strategy_directional_utility_v3",
        "emotion_options": emotion_guard.pop("emotion_options"),
        "official_attitude_options": attitude_options,
        "previous_emotion": (previous_state or {}).get("current_emotion"),
        "previous_official_attitude": previous_attitude,
        "persona_profile": profile,
        "emotion_transition": emotion_guard,
        "official_attitude_resolution": attitude_resolution,
        "strategy_attitude_memory": attitude_lifecycle["memory"],
        "attitude_lifecycle_diagnostics": attitude_lifecycle[
            "diagnostics"
        ],
        "strategy_evidence_memory": evidence_memory,
        "strategy_evidence_assimilation": evidence_assimilation,
        "state_evidence_catalog": evidence_catalog,
        "decision_rule": (
            "证据先按评价对象路由到事件情绪、官方态度或参与通道；"
            "事件情绪再由Persona先验、上一轮惯性、权威证据有限渐进"
            "吸收和独立传播根递减效用裁决。同一证据组推动一次变化后"
            "停止重复推动；每轮只允许保持或相邻变化。"
        ),
    }


def attach_strategy_state_audit(decision, guard):
    """把最终状态与规则诊断组合，供状态历史和逐轮指标审计。"""

    normalized = dict(decision)
    previous_emotion = guard.get("previous_emotion")
    previous_attitude = guard.get("previous_official_attitude")
    emotion = normalized.get("current_emotion")
    attitude = normalized.get("official_attitude")
    resolution = dict(guard.get("official_attitude_resolution", {}))
    recommended_attitude = resolution.get("official_attitude")
    if resolution:
        resolution["recommended_official_attitude"] = recommended_attitude
        resolution["official_attitude"] = attitude
        if attitude != recommended_attitude:
            resolution["transition_reason"] = (
                "initial_persona_option_selected"
            )
        normalized["official_attitude_resolution"] = resolution
        normalized["process_evaluation"] = resolution.get(
            "process_evaluation"
        )
    normalized["claim_position"] = {
        "accept": "accepted",
        "wait": "unresolved",
        "question": "challenged",
        "not_applicable": "not_applicable",
    }.get(attitude)
    normalized["strategy_state_guard"] = guard
    normalized["strategy_evidence_memory"] = dict(
        guard.get("strategy_evidence_memory", {})
    )
    normalized["strategy_evidence_assimilation"] = dict(
        guard.get("strategy_evidence_assimilation", {})
    )
    normalized["strategy_attitude_memory"] = dict(
        guard.get("strategy_attitude_memory", {})
    )
    # 方向性证据组保留在完整守卫中供追溯；逐轮指标只保存聚合结果，
    # 防止状态历史被重复的证据明细放大。
    transition_diagnostics = {
        key: value
        for key, value in guard.get("emotion_transition", {}).items()
        if key != "directional_evidence_groups"
    }
    normalized["state_transition_diagnostics"] = {
        **transition_diagnostics,
        "attitude_lifecycle": dict(
            guard.get("attitude_lifecycle_diagnostics", {})
        ),
        "previous_emotion": previous_emotion,
        "current_emotion": emotion,
        "emotion_changed": (
            previous_emotion in EMOTION_LEVELS
            and emotion != previous_emotion
        ),
        "previous_official_attitude": previous_attitude,
        "current_official_attitude": attitude,
        "official_attitude_changed": (
            previous_attitude in OFFICIAL_ATTITUDES
            and attitude != previous_attitude
        ),
        "official_transition_reason": resolution.get(
            "transition_reason"
        ),
    }
    return normalized
