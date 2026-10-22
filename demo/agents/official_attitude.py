"""单个 Agent 的官方态度裁决。

本模块只处理个体证据，不调用 LLM、不读取文件，也不使用真实情绪比例。
它把“是否接受事实结论”和“如何评价回应过程”拆成两个维度，再通过
Persona 门槛与上一轮状态迟滞生成兼容旧界面的 ``official_attitude``。

2026/10/14，新增功能：让个体规则成为官方态度的最终裁决者，避免已经
计算出的 Persona 差异再次被相同提示词下的 LLM 集体选择覆盖。
"""

from __future__ import annotations

from domain.comment_semantics import normalize_evidence_semantics


ATTITUDE_LEVELS = {"question": -1, "wait": 0, "accept": 1}

_FACT_TARGETS = {
    "official_claim",
    "fact_clarification",
    "event_outcome",
    "identity_confirmation",
    "forensic_result",
}
_PROCESS_TARGETS = {
    "accountability",
    "official_response",
    "investigation_process",
    "process_accountability",
}


def _normalize_attitude_evidence(item):
    """补齐态度证据语义，同时兼容改造前的内部证据对象。

    旧版 ``official_attitude`` 单元测试和历史中间结果会直接保存
    ``evidence_target``，但没有保存来源与证据角色。这里仅对这种“既没有
    evidence_type、也没有语义来源”的内部证据做保守迁移；带有
    ``simulated_comment`` 标识的公众评论仍会被识别为公众观点，不能因此
    获得事实证明力。
    """

    legacy_item = dict(item)
    target = str(legacy_item.get("evidence_target", ""))
    is_bare_legacy = (
        not legacy_item.get("evidence_type")
        and not legacy_item.get("information_source_type")
    )
    if is_bare_legacy and target in _FACT_TARGETS:
        legacy_item["information_source_type"] = "event"
    if not legacy_item.get("evidence_role"):
        if legacy_item.get("unresolved_concern") is True:
            legacy_item["evidence_role"] = "question"
        elif target in _FACT_TARGETS | _PROCESS_TARGETS:
            legacy_item["evidence_role"] = "clarify"
    return normalize_evidence_semantics(legacy_item)


def _bounded(value, default=0.0):
    """把数值安全限制在 0 到 1。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _impact(item):
    """读取单条证据对当前 Persona 的官方态度影响。"""

    return _bounded(
        item.get("personal_impact", {}).get("official_attitude_score")
    )


def _best_by_group(items):
    """同一事实组只保留个人影响最高的一项，防止通告分句重复计权。"""

    grouped = {}
    for item in items:
        evidence_id = str(item.get("evidence_id", "")).strip()
        if not evidence_id:
            continue
        group_id = str(item.get("evidence_group_id", evidence_id))
        score = _impact(item)
        if group_id not in grouped or score > grouped[group_id][0]:
            grouped[group_id] = (score, item)
    return [entry[1] for entry in grouped.values()]


def _capped_channel_impact(items):
    """按递减边际合并不同事实组，避免证据数量把影响迅速推到 100%。"""

    scores = sorted((_impact(item) for item in _best_by_group(items)), reverse=True)
    weights = (1.0, 0.35, 0.15)
    return min(
        0.90,
        sum(score * weights[index] for index, score in enumerate(scores[:3])),
    )


def _evidence_ids(items, limit=3):
    """返回按个人影响排序的去重证据编号。"""

    ordered = sorted(_best_by_group(items), key=_impact, reverse=True)
    return [str(item["evidence_id"]) for item in ordered[:limit]]


def _split_channels(evidence_items):
    """把态度证据拆成事实支持、过程回应和未解决关切三个通道。"""

    channels = {"claim": [], "process": [], "concern": []}
    for item in evidence_items:
        if item.get("evidence_strength") == "background":
            continue
        target = str(item.get("evidence_target", ""))
        role = str(item.get("evidence_role", "opinion"))
        source_type = str(item.get("information_source_type", "public"))
        unresolved = item.get("unresolved_concern") is True
        authoritative = source_type in {
            "official",
            "event",
            "media",
            "expert",
            "witness",
        }
        if (
            target in _FACT_TARGETS
            and role in {"support", "clarify"}
            and authoritative
        ):
            channels["claim"].append(item)
        # 2026/10/14，修改功能：未解决的过程关切不能同时被计作“官方
        # 已覆盖该问题”。否则同一条质疑会一边提高关切、一边虚增回应
        # 完整度，掩盖“接受事实结论但不满处置过程”的真实组合状态。
        if (
            target in _PROCESS_TARGETS
            and role in {"support", "clarify"}
            and not unresolved
        ):
            channels["process"].append(item)
        if unresolved or role in {"question", "contradict"}:
            channels["concern"].append(item)
    return channels


def _process_evaluation(
    process_coverage,
    concern,
    profile,
    previous_evaluation,
    has_new_process_evidence,
):
    """独立评价回应过程，并对上一轮评价应用证据迟滞。"""

    threshold = _bounded(profile.get("process_satisfaction_threshold"), 0.55)
    if process_coverage >= threshold and concern < threshold * 0.55:
        candidate = "satisfied"
    elif concern >= max(0.30, process_coverage + 0.05):
        candidate = "dissatisfied"
    else:
        candidate = "partial"

    valid = {"satisfied", "partial", "dissatisfied"}
    if previous_evaluation not in valid:
        return candidate, "initial_process_evaluation"
    if not has_new_process_evidence:
        return previous_evaluation, "held_without_new_process_evidence"
    if candidate == previous_evaluation:
        return candidate, "process_evaluation_unchanged"

    # 2026/10/14，修改功能：过程评价不会因为本轮没有重复上轮通告而
    # 自动回到partial。新的弱关切也不能立即抹掉已经形成的满意判断；
    # 必须达到个人过程门槛的明确比例，才允许跨状态变化。
    if (
        previous_evaluation == "satisfied"
        and candidate == "partial"
        and concern < max(0.25, threshold * 0.55)
    ):
        return previous_evaluation, "held_by_process_hysteresis"
    if (
        previous_evaluation == "dissatisfied"
        and candidate == "partial"
        and process_coverage < threshold * 0.70
    ):
        return previous_evaluation, "held_by_process_hysteresis"
    return candidate, "changed_after_process_evidence"


def _apply_hysteresis(
    candidate,
    previous,
    accept_signal,
    question_signal,
    process_coverage,
    profile,
    channels,
    acceptance_threshold,
    question_threshold,
):
    """只在个体证据越过门槛时改变上一轮态度。"""

    if previous not in ATTITUDE_LEVELS or candidate == previous:
        return candidate, "initial_or_unchanged"

    has_new_evidence = any(
        item.get("is_new_this_step") is True
        for items in channels.values()
        for item in items
    )
    if not has_new_evidence:
        return previous, "held_without_new_evidence"

    change_threshold = _bounded(
        profile.get("attitude_change_threshold"),
        0.58,
    )
    if candidate == "accept":
        transition_signal = accept_signal
        required_threshold = change_threshold
    elif candidate == "question":
        transition_signal = question_signal
        # 2026/10/14，修改功能：质疑候选已经通过个体关切门槛，不再
        # 被更高的通用态度门槛重复否决。仅增加一个与状态惯性相关的
        # 小迟滞边际，使真实强质疑可达，同时避免弱噪声触发集体质疑。
        required_threshold = min(
            change_threshold,
            question_threshold
            + 0.04 * _bounded(profile.get("state_inertia"), 0.5),
        )
    elif previous == "accept":
        # 已接受结论的 Agent 不会因为“本轮没有重复强证据”自动退回观望；
        # 必须出现新的未解决关切。
        transition_signal = question_signal if channels["concern"] else 0.0
        required_threshold = change_threshold
    else:
        transition_signal = max(accept_signal, process_coverage)
        required_threshold = change_threshold

    if transition_signal < required_threshold:
        return previous, "held_by_personal_threshold"

    distance = abs(ATTITUDE_LEVELS[candidate] - ATTITUDE_LEVELS[previous])
    if distance > 1:
        has_strong_evidence = any(
            item.get("evidence_strength") == "strong"
            for items in channels.values()
            for item in items
        )
        if not has_strong_evidence or transition_signal < min(
            0.90,
            required_threshold + 0.12,
        ):
            return "wait", "moved_one_level_only"
    return candidate, "changed_after_threshold"


def resolve_official_attitude(
    evidence_items,
    profile,
    previous_state,
    statement_status,
    base_options,
):
    """返回单个 Agent 的确定性官方态度及可审计的双维度结果。

    ``clear`` 只记录内容清晰度，不直接增加接受分，也不压低质疑分。
    事实接受由事实证据和个体证据要求决定；过程评价由回应覆盖与未解决
    关切决定。函数不读取群体分布，因此不会人为制造或抑制群体比例。
    """

    if statement_status == "none":
        return {
            "resolution_version": "official_attitude_v3",
            "official_attitude": "not_applicable",
            "claim_position": "not_applicable",
            "process_evaluation": "not_applicable",
            "process_transition_reason": "no_official_statement",
            "claim_confidence": 0.0,
            "process_coverage": 0.0,
            "unresolved_concern": 0.0,
            "accept_signal": 0.0,
            "question_signal": 0.0,
            "utilities": {"accept": 0.0, "wait": 1.0, "question": 0.0},
            "transition_reason": "no_official_statement",
            "supporting_evidence_ids": [],
            "statement_clarity": "none",
        }

    previous_state = previous_state if isinstance(previous_state, dict) else {}
    evidence_items = [
        _normalize_attitude_evidence(item)
        for item in evidence_items
        if isinstance(item, dict)
    ]
    orientation = profile.get("orientation", {})
    fact = _bounded(orientation.get("fact"), 1 / 3)
    questioning = _bounded(orientation.get("questioning"), 1 / 3)
    channels = _split_channels(evidence_items)
    claim_confidence = _capped_channel_impact(channels["claim"])
    process_coverage = _capped_channel_impact(channels["process"])
    concern = _capped_channel_impact(channels["concern"])

    # 2026/10/14，修改功能：Persona只改变证据门槛和解释强度，不能凭空
    # 生成事实。事实取向略提高对已核实材料的利用，质疑取向略提高对
    # 未解决关切的敏感度，但两者都必须有对应证据才能发挥作用。
    accept_signal = _bounded(claim_confidence + 0.08 * fact - 0.04 * questioning)
    question_signal = _bounded(concern + 0.12 * questioning - 0.05 * fact)
    acceptance_threshold = _bounded(
        profile.get("official_acceptance_threshold"),
        0.58,
    )
    question_threshold = _bounded(
        profile.get("official_question_threshold"),
        0.52,
    )

    if channels["claim"] and accept_signal >= acceptance_threshold:
        candidate = "accept"
    elif channels["concern"] and question_signal >= question_threshold:
        candidate = "question"
    else:
        candidate = "wait"

    previous = previous_state.get("official_attitude")
    selected, transition_reason = _apply_hysteresis(
        candidate,
        previous,
        accept_signal,
        question_signal,
        process_coverage,
        profile,
        channels,
        acceptance_threshold,
        question_threshold,
    )
    allowed = [option for option in base_options if option in ATTITUDE_LEVELS]
    if selected not in allowed:
        selected = "wait" if "wait" in allowed else allowed[0]
        transition_reason = "normalized_to_base_options"

    uncertainty = 1.0 - min(1.0, abs(accept_signal - question_signal))
    utilities = {
        "accept": accept_signal,
        "wait": _bounded(0.38 + 0.24 * uncertainty),
        "question": question_signal,
    }
    if previous in utilities:
        utilities[previous] = _bounded(
            utilities[previous] + 0.20 * _bounded(profile.get("state_inertia"), 0.5)
        )

    evidence_for_result = {
        "accept": channels["claim"],
        "question": channels["concern"] + channels["process"],
        "wait": channels["claim"] + channels["process"] + channels["concern"],
    }
    process_evaluation, process_transition_reason = _process_evaluation(
        process_coverage,
        concern,
        profile,
        previous_state.get("process_evaluation"),
        any(
            item.get("is_new_this_step") is True
            for item in channels["process"] + channels["concern"]
        ),
    )
    claim_position = {
        "accept": "accepted",
        "wait": "unresolved",
        "question": "challenged",
    }[selected]
    return {
        "resolution_version": "official_attitude_v3",
        "official_attitude": selected,
        "claim_position": claim_position,
        "process_evaluation": process_evaluation,
        "process_transition_reason": process_transition_reason,
        "claim_confidence": round(claim_confidence, 6),
        "process_coverage": round(process_coverage, 6),
        "unresolved_concern": round(concern, 6),
        "accept_signal": round(accept_signal, 6),
        "question_signal": round(question_signal, 6),
        "acceptance_threshold": round(acceptance_threshold, 6),
        "question_threshold": round(question_threshold, 6),
        "change_threshold": round(
            _bounded(profile.get("attitude_change_threshold"), 0.58),
            6,
        ),
        "utilities": {key: round(value, 6) for key, value in utilities.items()},
        "transition_reason": transition_reason,
        "supporting_evidence_ids": _evidence_ids(
            evidence_for_result[selected]
        ),
        "statement_clarity": str(statement_status),
        "active_evidence_count": sum(len(items) for items in channels.values()),
        "new_evidence_count": sum(
            item.get("is_new_this_step") is True
            for items in channels.values()
            for item in items
        ),
    }
