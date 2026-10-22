"""Persona 决策画像与离散迟滞约束。

本模块不调用 LLM、不读写文件，也不读取真实趋势。它把 Persona 转换为
稳定的个体门槛，并根据当轮新证据决定 Agent 应保持状态、只允许相邻变化，
还是可以完整重判。

2026/10/14，修改功能：保留历史复现的离散情绪迟滞，同时把情绪转移和
官方态度的最终裁决放在本地个体规则中。LLM负责解释与表达，不再覆盖已经
由Persona、当前证据和上一轮状态形成的个体裁决。历史复现使用本模块的
完整本地裁决；2026/10/18起，回应方案只复用稳定Persona画像，不复用
历史复现的完整证据规则，由独立的策略状态模块约束邻居影响与状态候选。
"""

from __future__ import annotations

from agents.official_attitude import resolve_official_attitude


EMOTION_LEVELS = {"negative": -1, "neutral": 0, "positive": 1}


def _bounded(value, default=0.0):
    """把数值安全限制在 0 到 1。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _relative_to_population(value, quantiles):
    """用 P25/P75 将 Persona 比例换算为稳定的群体相对位置。"""

    value = _bounded(value)
    if not isinstance(quantiles, dict):
        return value
    p25 = _bounded(quantiles.get("p25"), 0.25)
    p75 = _bounded(quantiles.get("p75"), 0.75)
    if p75 <= p25:
        return value
    if value <= p25:
        return 0.25 * value / p25 if p25 > 0 else 0.0
    if value <= p75:
        return 0.25 + 0.50 * (value - p25) / (p75 - p25)
    upper_span = 1.0 - p75
    if upper_span <= 0:
        return 1.0
    return 0.75 + 0.25 * (value - p75) / upper_span


def _topic_interest(persona, event_context):
    """返回当前事件主题相对该 Agent 最高主题偏好的关注强度。"""

    preferences = persona.get("topic_preference", {})
    if not isinstance(preferences, dict) or not preferences:
        return 0.5
    labels = event_context.get("event_labels", {})
    labels = labels if isinstance(labels, dict) else {}
    values = [_bounded(value) for value in preferences.values()]
    maximum = max(values, default=0.0)
    if maximum <= 0:
        return 0.5
    return _bounded(preferences.get(labels.get("topic"))) / maximum


def build_persona_decision_profile(persona, policy, event_context):
    """构造目标基准使用的稳定 Persona 决策画像。"""

    orientation = persona.get("information_orientation", {})
    orientation = orientation if isinstance(orientation, dict) else {}
    emotion = persona.get("emotion_expression", {})
    emotion = emotion if isinstance(emotion, dict) else {}
    faction = persona.get("comment_faction_preference", {})
    faction = faction if isinstance(faction, dict) else {}
    action = persona.get("action_preference", {})
    action = action if isinstance(action, dict) else {}
    orientation_quantiles = policy.get("orientation_quantiles", {})
    emotion_quantiles = policy.get("emotion_quantiles", {})

    relative_orientation = {}
    for name in ("fact", "opinion", "questioning"):
        field = f"{name}_rate"
        relative_orientation[name] = _relative_to_population(
            orientation.get(field, 1 / 3),
            orientation_quantiles.get(field, {}),
        )
    emotion_prior = {}
    for name in ("positive", "neutral", "negative"):
        field = f"{name}_rate"
        emotion_prior[name] = _relative_to_population(
            emotion.get(field, 1 / 3),
            emotion_quantiles.get(field, {}),
        )

    topic_interest = _topic_interest(persona, event_context)
    dominant_emotion_strength = max(emotion_prior.values(), default=0.5)
    state_inertia = _bounded(
        0.34
        + 0.24 * dominant_emotion_strength
        + 0.14 * relative_orientation["fact"]
        + 0.10 * (1.0 - topic_interest)
    )
    emotion_change_threshold = _bounded(
        0.28 + 0.28 * state_inertia + 0.12 * (1.0 - topic_interest)
    )
    attitude_change_threshold = _bounded(
        0.43
        + 0.20 * state_inertia
        + 0.12 * relative_orientation["questioning"]
        - 0.08 * relative_orientation["fact"]
    )
    official_acceptance_threshold = _bounded(
        0.50
        + 0.24 * relative_orientation["questioning"]
        + 0.08 * relative_orientation["opinion"]
        - 0.16 * relative_orientation["fact"]
    )
    # 2026/10/14，新增功能：事实结论接受、未解决关切和回应过程分别使用
    # 个体门槛；这些门槛都来自现有 Persona，不推断不存在的人口学性格。
    official_question_threshold = _bounded(
        0.24
        + 0.10 * relative_orientation["fact"]
        - 0.12 * relative_orientation["questioning"]
    )
    process_satisfaction_threshold = _bounded(
        0.42
        + 0.24 * relative_orientation["questioning"]
        + 0.08 * relative_orientation["opinion"]
        - 0.10 * relative_orientation["fact"]
    )
    public_conformity = _bounded(
        0.12
        + 0.34 * relative_orientation["opinion"]
        + 0.18 * _bounded(faction.get("吃瓜派"), 0.2)
        + 0.12 * (1.0 - relative_orientation["fact"])
    )
    expression_threshold = _bounded(
        0.55
        - 0.18 * _bounded(action.get("original_preference"), 0.5)
        - 0.12 * topic_interest
    )
    emotion_switch_margin = _bounded(0.01 + 0.02 * state_inertia)

    return {
        "profile_version": "persona_decision_v3",
        "topic_interest": round(topic_interest, 6),
        "orientation": {
            key: round(value, 6) for key, value in relative_orientation.items()
        },
        "emotion_prior": {
            key: round(value, 6) for key, value in emotion_prior.items()
        },
        "state_inertia": round(state_inertia, 6),
        "emotion_change_threshold": round(emotion_change_threshold, 6),
        "attitude_change_threshold": round(attitude_change_threshold, 6),
        "official_acceptance_threshold": round(
            official_acceptance_threshold, 6
        ),
        "official_question_threshold": round(
            official_question_threshold, 6
        ),
        "process_satisfaction_threshold": round(
            process_satisfaction_threshold, 6
        ),
        "public_conformity": round(public_conformity, 6),
        "expression_threshold": round(expression_threshold, 6),
        "emotion_switch_margin": round(emotion_switch_margin, 6),
    }


def _distinct_new_evidence(evidence_items):
    """同一事实、同一情绪方向只保留个人影响更强的一项。

    2026/10/16，修改功能：一份通告可能同时包含“事实复述”和“新增
    处置行动”。总影响仍按 evidence_group_id 去重，但效用计算保留
    不同方向，避免整份通告的第一条片段覆盖真正可推动缓和的行动证据。
    """

    by_group = {}
    for item in evidence_items:
        if not _is_eligible_new_evidence(item):
            continue
        group_id = str(item.get("evidence_group_id", item.get("evidence_id")))
        group_key = (group_id, item.get("emotion"))
        impact = item.get("personal_impact", {})
        score = float(impact.get("emotion_score", 0.0) or 0.0)
        previous = by_group.get(group_key)
        if previous is None or score > previous[0]:
            by_group[group_key] = (score, item)
    return [entry[1] for entry in by_group.values()]


def _is_eligible_new_evidence(item):
    """统一判断本轮证据是否可以推动状态变化。"""

    return (
        item.get("is_new_this_step") is True
        and item.get("evidence_strength") != "background"
        and item.get("comment_source") != "current_emergency"
    )


def _combined_impact(items, score_field):
    """按事实组和递减边际合并影响，避免证据数量造成接近 100% 饱和。"""

    by_group = {}
    for item in items:
        evidence_id = str(item.get("evidence_id", ""))
        group_id = str(item.get("evidence_group_id", evidence_id))
        score = _bounded(item.get("personal_impact", {}).get(score_field))
        by_group[group_id] = max(score, by_group.get(group_id, 0.0))
    scores = sorted(by_group.values(), reverse=True)
    weights = (1.0, 0.35, 0.15)
    return min(
        0.90,
        sum(score * weights[index] for index, score in enumerate(scores[:3])),
    )


def _emotion_utilities(profile, previous_emotion, items):
    """融合长期情绪倾向、可见证据构成与上一轮状态。"""

    utilities = {
        emotion: 0.35 * profile["emotion_prior"].get(emotion, 0.0)
        for emotion in EMOTION_LEVELS
    }
    total_weight = sum(
        _bounded(item.get("personal_impact", {}).get("emotion_score"))
        for item in items
    )
    if total_weight > 0:
        for item in items:
            emotion = item.get("emotion")
            if emotion not in utilities:
                continue
            score = _bounded(
                item.get("personal_impact", {}).get("emotion_score")
            )
            utilities[emotion] += 0.28 * score / total_weight
            if emotion == "positive" and previous_emotion == "negative":
                # 2026/10/16，修改功能：离散状态不允许 negative 直接
                # 跳到 positive，因此建设性行动先为相邻 neutral 提供
                # 缓和效用。它不是强制转向，仍须越过个人门槛并具备
                # neutral方向证据，避免“积极行动反而无法缓和”的断层。
                utilities["neutral"] += 0.18 * score / total_weight
    if previous_emotion in utilities:
        # 2026/10/14，修改功能：上一轮状态仍提供迟滞，但不再以过高固定
        # 奖励压过已经越过个人门槛的新证据。真正的保持条件由下面的
        # 个体切换边际单独控制，避免“候选已开放但永远不变化”。
        utilities[previous_emotion] += 0.12 * profile["state_inertia"]
    return {key: round(value, 6) for key, value in utilities.items()}


def _emotion_supporting_evidence_ids(items, emotion, limit=3):
    """返回支持目标情绪的最强新增证据，供状态变化校验和审计。"""

    candidates = [
        item
        for item in items
        if item.get("emotion") == emotion
        and (
            emotion != "positive"
            or item.get("positive_eligible") is True
        )
    ]
    candidates.sort(
        key=lambda item: _bounded(
            item.get("personal_impact", {}).get("emotion_score")
        ),
        reverse=True,
    )
    return [
        str(item.get("evidence_id"))
        for item in candidates[:limit]
        if item.get("evidence_id")
    ]


def _resolve_emotion_state(options, previous, utilities, items, profile):
    """在候选已开放时按个体效用边际确定最终情绪。

    第一轮缺少上一状态，仍交由LLM完成语义初始化。后续轮次只有在证据
    已越过个人变化门槛、替代状态效用超过上一状态且具有对应新证据时
    才转移，因此既不会永久保持，也不会按群体比例强制切换。
    """

    if previous not in EMOTION_LEVELS:
        return {
            "resolution_version": "emotion_transition_v1",
            "selected_emotion": None,
            "transition_reason": "llm_initialization_without_previous_state",
            "utility_margin": None,
            "required_margin": profile["emotion_switch_margin"],
            "supporting_evidence_ids": [],
        }

    if len(options) <= 1:
        selected = options[0] if options else previous
        return {
            "resolution_version": "emotion_transition_v1",
            "selected_emotion": selected,
            "transition_reason": "held_by_evidence_gate",
            "utility_margin": 0.0,
            "required_margin": profile["emotion_switch_margin"],
            "supporting_evidence_ids": [],
        }

    candidate = max(options, key=lambda emotion: utilities[emotion])
    margin = utilities[candidate] - utilities[previous]
    supporting_ids = _emotion_supporting_evidence_ids(items, candidate)
    required_margin = profile["emotion_switch_margin"]
    if candidate == previous:
        selected = previous
        reason = "held_by_personal_utility"
        supporting_ids = []
    elif not supporting_ids:
        selected = previous
        reason = "held_without_directional_evidence"
    elif margin < required_margin:
        selected = previous
        reason = "held_by_personal_margin"
        supporting_ids = []
    else:
        selected = candidate
        reason = "changed_after_personal_margin"

    return {
        "resolution_version": "emotion_transition_v1",
        "selected_emotion": selected,
        "transition_reason": reason,
        "utility_margin": round(margin, 6),
        "required_margin": required_margin,
        "supporting_evidence_ids": supporting_ids,
    }


def _adjacent_options(previous, levels, base_options):
    """返回包含上一状态且最多相差一个等级的合法候选。"""

    previous_level = levels[previous]
    return [
        option
        for option in base_options
        if option in levels and abs(levels[option] - previous_level) <= 1
    ]


def _constrain_options(
    previous,
    base_options,
    levels,
    utilities,
    transition_impact,
    threshold,
    full_reassessment,
    has_new_evidence,
):
    """按 v1 迟滞规则开放保持、一个相邻候选或全部候选。"""

    if previous not in levels or previous not in base_options:
        return list(base_options)
    if not has_new_evidence or transition_impact < threshold:
        return [previous]
    if full_reassessment:
        return list(base_options)
    adjacent = _adjacent_options(previous, levels, base_options)
    alternatives = [item for item in adjacent if item != previous]
    if not alternatives:
        return [previous]
    best_alternative = max(alternatives, key=lambda key: utilities[key])
    permitted = {previous, best_alternative}
    return [option for option in base_options if option in permitted]


def build_personalized_decision_guard(
    evidence_items,
    profile,
    previous_state,
    base_emotion_options,
    base_attitude_options,
    statement_status,
):
    """生成与目标实验一致的离散个体迟滞候选约束。"""

    previous_state = previous_state if isinstance(previous_state, dict) else {}
    distinct_items = _distinct_new_evidence(evidence_items)
    emotion_impact = _combined_impact(distinct_items, "emotion_score")
    # v1只让与官方回应、调查过程或事实澄清相关的材料推动官方态度。
    # 普通情绪评论仍影响事件情绪，但不能靠数量把官方态度推过门槛。
    # 2026/10/14，修改功能：情绪仍按事实组整体去重；官方态度需要同时
    # 保留同一通告中的“事实结论”和“过程回应”通道，再由专用模块在
    # 各通道内部去重，才能表达“接受结论但不满过程”。
    attitude_items = [
        item
        for item in evidence_items
        if _is_eligible_new_evidence(item)
        and (
            item.get("evidence_type")
            not in {"simulated_comment", "historical_positive_evidence"}
            or item.get("evidence_target")
            in {
                "official_response",
                "investigation_process",
                "process_accountability",
                "fact_clarification",
            }
        )
    ]
    attitude_impact = _combined_impact(
        attitude_items, "official_attitude_score"
    )
    previous_emotion = previous_state.get("current_emotion")
    emotion_utilities = _emotion_utilities(
        profile, previous_emotion, distinct_items
    )
    emotion_full = any(
        item.get("personal_impact", {}).get("emotion_change_mode")
        == "full_reassessment"
        for item in distinct_items
    )

    emotion_options = _constrain_options(
        previous_emotion,
        base_emotion_options,
        EMOTION_LEVELS,
        emotion_utilities,
        emotion_impact,
        profile["emotion_change_threshold"],
        emotion_full,
        bool(distinct_items),
    )
    emotion_resolution = _resolve_emotion_state(
        emotion_options,
        previous_emotion,
        emotion_utilities,
        distinct_items,
        profile,
    )
    resolved_emotion = emotion_resolution["selected_emotion"]
    if resolved_emotion is not None:
        # 2026/10/14，修改功能：后续轮次的最终情绪由个体规则裁决；
        # LLM只解释这个结果，防止模型在候选开放后仍机械复制上一状态。
        emotion_options = [resolved_emotion]
    if statement_status == "none":
        attitude_options = ["not_applicable"]
        attitude_resolution = resolve_official_attitude(
            attitude_items,
            profile,
            previous_state,
            statement_status,
            base_attitude_options,
        )
    else:
        # 2026/10/14，修改功能：规则层直接给出单个 Agent 的官方态度。
        # LLM只解释这个个体裁决，不再在多个相同候选之间制造群体同步。
        attitude_resolution = resolve_official_attitude(
            attitude_items,
            profile,
            previous_state,
            statement_status,
            base_attitude_options,
        )
        attitude_options = [attitude_resolution["official_attitude"]]

    return {
        "guard_version": "personalized_hysteresis_v3",
        "emotion_options": emotion_options,
        "official_attitude_options": attitude_options,
        "emotion_utilities": emotion_utilities,
        "emotion_resolution": emotion_resolution,
        "official_attitude_utilities": attitude_resolution["utilities"],
        "official_attitude_resolution": attitude_resolution,
        "emotion_transition_impact": round(emotion_impact, 6),
        "official_attitude_transition_impact": round(attitude_impact, 6),
        "emotion_change_threshold": profile["emotion_change_threshold"],
        "official_attitude_change_threshold": profile[
            "attitude_change_threshold"
        ],
        "state_inertia": profile["state_inertia"],
        "distinct_new_evidence_count": len(distinct_items),
        "decision_rule": (
            "情绪与官方态度均由Persona、当前证据和上一轮状态进行个体"
            "裁决；LLM只负责解释、发言意愿和原创表达。"
        ),
    }
