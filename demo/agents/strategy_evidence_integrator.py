"""回应方案实验的方向性证据整合器。

2026/10/18，新增功能：在不改变 ``positive / neutral / negative``
离散状态契约的前提下，将证据强度、语义方向、Persona亲和度、
独立传播根和上一轮惯性整合为可审计效用，解决“所有弱/中等证据
都只能保持”导致的状态冻结。

本模块只依赖调用方传入的证据和Persona画像，不读写文件、不调用LLM、
不读取真实趋势，也不设置任何群体比例目标。历史趋势复现继续使用
``personalized_hysteresis_v3``，不进入本模块。
"""

from __future__ import annotations

from agents.evidence_impact_router import (
    route_emotion_support,
    route_evidence_impact,
)
from agents.strategy_evidence_assimilation import (
    consume_groups as consume_assimilation_groups,
    prepare_assimilated_groups,
)
from agents.strategy_evidence_lifecycle import (
    update_evidence_memory,
)


EMOTIONS = ("positive", "neutral", "negative")
EMOTION_LEVELS = {"negative": -1, "neutral": 0, "positive": 1}
AGGREGATION_WEIGHTS = (1.0, 0.5, 0.25)
EVIDENCE_STRENGTH_LEVELS = {
    "background": 0,
    "weak": 1,
    "moderate": 2,
    "strong": 3,
}

# 2026/10/19，修改功能：同一官方通告不再由最强的一句话代表全部内容。
# 先在可观察语义维度内取最强值，再按维度权重求平均；权重只描述证据
# 结构，不规定任何方案效果或群体比例。
OFFICIAL_DIMENSION_WEIGHTS = {
    "completed_action": 0.38,
    "verified_fact": 0.24,
    "accountability": 0.16,
    "empathy": 0.10,
    "unresolved_process": 0.08,
    "rumor_control": 0.04,
    "other": 0.04,
}

# 效用的三个来源权重总和为1。证据是当轮变化的主要来源，
# Persona先验和上轮惯性保证同一证据不会让所有Agent同步转向。
PRIOR_UTILITY_WEIGHT = 0.16
EVIDENCE_UTILITY_WEIGHT = 0.68
INERTIA_UTILITY_WEIGHT = 0.16
MIN_SWITCH_MARGIN = 0.06
INERTIA_SWITCH_WEIGHT = 0.10
PREVIOUS_COMMITMENT_SWITCH_WEIGHT = 0.06

_COMPLETED_ENFORCEMENT_MARKERS = (
    "刑事拘留",
    "行政拘留",
    "依法拘留",
    "依法处罚",
    "依法处理",
    "已控制",
    "控制并带回",
    "抓获",
    "到案",
    "送伤者就医",
    "送医治疗",
)
_VERIFIED_PROGRESS_MARKERS = (
    "已调取",
    "已固定",
    "已开展调查",
    "已接报",
    "已立案",
    "立即到场",
    "已接受伤情检查",
    "经查明",
    "经调查",
)
_EMPATHY_MARKERS = (
    "高度关注",
    "表示关切",
    "表示慰问",
    "深表歉意",
    "道歉",
    "心理疏导",
    "提供帮助",
)
_ACCOUNTABILITY_MARKERS = (
    "追责",
    "问责",
    "处分",
    "责任认定",
    "整改",
)
_PENDING_MARKERS = (
    "正在",
    "尚未",
    "有待",
    "进一步",
    "将依法",
    "将继续",
    "将根据",
    "将及时",
    "结果将",
)
_RUMOR_CONTROL_MARKERS = (
    "请勿传播",
    "不信谣",
    "不传谣",
    "未得到权威确认",
    "尊重当事人隐私",
)


def _bounded(value, default=0.0):
    """将数值限制在0到1，避免异常Persona或证据字段放大结果。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def is_neighbor_evidence(item):
    """仅把实际沿关系网络曝光的评论识别为邻居证据。"""

    return (
        item.get("evidence_type") == "simulated_comment"
        and (
            isinstance(item.get("network_influence_weight"), (int, float))
            and not isinstance(item.get("network_influence_weight"), bool)
            or bool(item.get("source_agent_ids"))
        )
    )


def _contains_any(content, markers):
    return any(marker in content for marker in markers)


def _official_semantic_dimensions(item):
    """返回官方证据片段覆盖的可审计语义维度。"""

    content = str(item.get("content", ""))
    target = str(item.get("evidence_target", ""))
    dimensions = []
    # 2026/10/20，新增功能：整份通告允许人工声明可观察语义维度；分句
    # 仍按各自正文识别，避免把整份通告的所有维度复制给每一个片段。
    if item.get("evidence_type") == "official_statement":
        explicit = item.get("evidence_dimensions", {})
        if isinstance(explicit, dict):
            dimensions.extend(
                name
                for name, enabled in explicit.items()
                if enabled is True and name in OFFICIAL_DIMENSION_WEIGHTS
            )
    if _contains_any(content, _COMPLETED_ENFORCEMENT_MARKERS):
        dimensions.append("completed_action")
    if _contains_any(content, _ACCOUNTABILITY_MARKERS):
        dimensions.append("accountability")
    if (
        _contains_any(content, _VERIFIED_PROGRESS_MARKERS)
        or target
        in {
            "event_outcome",
            "identity_confirmation",
            "forensic_result",
            "fact_clarification",
        }
    ):
        dimensions.append("verified_fact")
    if _contains_any(content, _EMPATHY_MARKERS):
        dimensions.append("empathy")
    if item.get("unresolved_concern") is True or _contains_any(
        content,
        _PENDING_MARKERS,
    ):
        dimensions.append("unresolved_process")
    if _contains_any(content, _RUMOR_CONTROL_MARKERS):
        dimensions.append("rumor_control")
    return sorted(set(dimensions)) or ["other"]


def _comment_direction(item):
    """评论已有三分类情绪，直接作为弱社会信号的方向。"""

    emotion = item.get("emotion")
    if emotion == "positive":
        # 建设性表达可以同时给予少量中性缓和，但不表示
        # 对负面事件本身的赞同。
        return {"positive": 0.75, "neutral": 0.25, "negative": 0.0}
    if emotion == "neutral":
        return {"positive": 0.0, "neutral": 1.0, "negative": 0.0}
    if emotion == "negative":
        return {"positive": 0.0, "neutral": 0.0, "negative": 1.0}
    return {emotion_name: 0.0 for emotion_name in EMOTIONS}


def _official_direction(item):
    """把官方证据的可观察语义转换为情绪支持方向。

    这些规则只描述证据内容，不直接指定Agent结论。例如“已拘留”
    主要支持从负面缓和到中性，但是否转变仍取决于Persona和旧状态。
    """

    content = str(item.get("content", ""))
    target = str(item.get("evidence_target", ""))
    unresolved = item.get("unresolved_concern") is True
    support = {emotion_name: 0.0 for emotion_name in EMOTIONS}

    if _contains_any(content, _COMPLETED_ENFORCEMENT_MARKERS):
        support.update({"neutral": 0.95, "positive": 0.25})
    elif _contains_any(content, _ACCOUNTABILITY_MARKERS):
        support.update({"neutral": 0.80, "positive": 0.20})
    elif _contains_any(content, _VERIFIED_PROGRESS_MARKERS):
        support.update({"neutral": 0.62, "positive": 0.08})
    elif _contains_any(content, _EMPATHY_MARKERS):
        support.update({"neutral": 0.48, "positive": 0.12})
    elif target in {
        "event_outcome",
        "identity_confirmation",
        "forensic_result",
    }:
        support.update({"neutral": 0.78, "positive": 0.12})
    elif target == "fact_clarification":
        support.update({"neutral": 0.58, "positive": 0.06})
    elif target == "social_action":
        support.update({"neutral": 0.70, "positive": 0.35})
    elif target == "process_accountability":
        support.update({"neutral": 0.52, "positive": 0.08})
    elif target == "investigation_process":
        support.update({"neutral": 0.28})
    else:
        support.update({"neutral": 0.22})

    if unresolved or _contains_any(content, _PENDING_MARKERS):
        # 未完成的调查不自动制造强负面，但会保留少量担忧，
        # 并限制同一证据的缓和幅度。
        support["neutral"] = min(support["neutral"], 0.30)
        support["positive"] = min(support["positive"], 0.05)
        support["negative"] = max(support["negative"], 0.12)
    if _contains_any(content, _RUMOR_CONTROL_MARKERS):
        support["neutral"] = max(support["neutral"], 0.18)
    return support


def _objective_direction(item):
    """为策略试验中可选的客观更新提供保守方向。"""

    support = {emotion_name: 0.0 for emotion_name in EMOTIONS}
    if item.get("positive_eligible") is True:
        support.update({"positive": 0.55, "neutral": 0.72})
    else:
        support["neutral"] = 0.62
    return support


def evidence_direction(item):
    """返回单条证据对事件情绪的目标感知方向支持。"""

    evidence_type = item.get("evidence_type")
    if evidence_type == "simulated_comment":
        base_support = _comment_direction(item)
    elif evidence_type in {"official_statement", "official_statement_unit"}:
        base_support = _official_direction(item)
    elif evidence_type in {"objective_event", "historical_verified_update"}:
        base_support = _objective_direction(item)
    else:
        base_support = {emotion_name: 0.0 for emotion_name in EMOTIONS}
    # 2026/10/20，修改功能：表达情绪不再无条件进入事件情绪。
    # 例如对调查过程的负面提问主要影响官方态度，而公共讨论热度主要
    # 影响参与行为；只有与事件伤害、结果或事实直接相关的内容才获得
    # 较高的事件情绪权重。
    return route_emotion_support(item, base_support)[0]


def _eligible_new_items(appraised_evidence):
    """过滤当轮真正新增的证据，持续背景不重复加权。"""

    return [
        item
        for item in appraised_evidence
        if item.get("is_new_this_step") is True
        and item.get("evidence_strength") != "background"
        and item.get("comment_source") != "current_emergency"
    ]


def _normalized_personal_impact(item):
    """将影响分数换算为相对于该Persona变化门槛的比例。

    此处解除了旧模型中“moderate理论上限低于所有人门槛”的数学
    死区，但不直接降低全局门槛。
    """

    impact = item.get("personal_impact", {})
    score = _bounded(impact.get("emotion_score"))
    threshold = max(_bounded(impact.get("emotion_change_threshold"), 0.5), 0.2)
    return _bounded(score / threshold)


def _weighted_official_group_support(dimension_support):
    """按语义维度组合整份通告，避免单句最大值支配公告效果。"""

    result = {}
    for emotion in EMOTIONS:
        numerator = 0.0
        denominator = 0.0
        for dimension, support in dimension_support.items():
            weight = OFFICIAL_DIMENSION_WEIGHTS.get(dimension, 0.04)
            value = _bounded(support.get(emotion))
            numerator += weight * value
            denominator += weight
        result[emotion] = round(
            numerator / denominator if denominator else 0.0,
            6,
        )
    return result


def _group_directional_evidence(appraised_evidence):
    """按事实/传播根合并证据，并对官方证据执行多维聚合。"""

    grouped = {}
    direction_by_id = {}
    for item in _eligible_new_items(appraised_evidence):
        evidence_id = str(item.get("evidence_id", "")).strip()
        if not evidence_id:
            continue
        group_id = str(item.get("evidence_group_id", evidence_id))
        semantic_support = evidence_direction(item)
        impact_routing = route_evidence_impact(item)
        normalized_impact = _normalized_personal_impact(item)
        directional_support = {
            emotion: round(
                normalized_impact * _bounded(semantic_support.get(emotion)),
                6,
            )
            for emotion in EMOTIONS
        }
        direction_by_id[evidence_id] = {
            "semantic_support": {
                emotion: round(_bounded(semantic_support.get(emotion)), 6)
                for emotion in EMOTIONS
            },
            "normalized_personal_impact": round(normalized_impact, 6),
            "directional_support": directional_support,
            "impact_routing": impact_routing,
        }
        entry = grouped.setdefault(
            group_id,
            {
                "evidence_group_id": group_id,
                "evidence_ids": [],
                "source_kinds": set(),
                "directional_support": {
                    emotion: 0.0 for emotion in EMOTIONS
                },
                "supporting_id_by_emotion": {},
                "positive_eligible": False,
                "semantic_dimension_support": {},
                "evidence_types": set(),
                "max_evidence_strength": "background",
            },
        )
        entry["evidence_ids"].append(evidence_id)
        evidence_type = str(item.get("evidence_type", "")).strip()
        if evidence_type:
            entry["evidence_types"].add(evidence_type)
        strength = str(item.get("evidence_strength", "background"))
        if EVIDENCE_STRENGTH_LEVELS.get(strength, 0) > EVIDENCE_STRENGTH_LEVELS.get(
            entry["max_evidence_strength"],
            0,
        ):
            entry["max_evidence_strength"] = strength
        entry["source_kinds"].add(
            "neighbor"
            if is_neighbor_evidence(item)
            else (
                "public"
                if item.get("evidence_type") == "simulated_comment"
                else "authoritative"
            )
        )
        entry["positive_eligible"] = (
            entry["positive_eligible"]
            or item.get("positive_eligible") is True
        )
        if item.get("evidence_type") in {
            "official_statement",
            "official_statement_unit",
        }:
            for dimension in _official_semantic_dimensions(item):
                dimension_entry = entry[
                    "semantic_dimension_support"
                ].setdefault(
                    dimension,
                    {emotion: 0.0 for emotion in EMOTIONS},
                )
                for emotion, value in directional_support.items():
                    dimension_entry[emotion] = max(
                        dimension_entry[emotion],
                        value,
                    )
        for emotion, value in directional_support.items():
            if value > entry["directional_support"][emotion]:
                entry["directional_support"][emotion] = value
                entry["supporting_id_by_emotion"][emotion] = evidence_id

    normalized_groups = []
    for entry in grouped.values():
        if entry["semantic_dimension_support"]:
            entry["directional_support"] = (
                _weighted_official_group_support(
                    entry["semantic_dimension_support"]
                )
            )
        # 没有可解释方向的文本只保留在可见语境中，不进入状态效用。
        # 这避免“字段齐全但没有情绪/事实含义”的记录被误计为独立证据根。
        if max(entry["directional_support"].values(), default=0.0) <= 0:
            continue
        normalized_groups.append(
            {
                **entry,
                "source_kinds": sorted(entry["source_kinds"]),
                "evidence_types": sorted(entry["evidence_types"]),
                "directional_support": {
                    emotion: round(value, 6)
                    for emotion, value in entry[
                        "directional_support"
                    ].items()
                },
                "base_directional_support": {
                    emotion: round(value, 6)
                    for emotion, value in entry[
                        "directional_support"
                    ].items()
                },
                "semantic_dimensions": sorted(
                    entry["semantic_dimension_support"]
                ),
            }
        )
    return normalized_groups, direction_by_id


def _aggregate_direction(groups, source_kind=None):
    """按独立根使用1、0.5、0.25递减累积，禁止数量无上限放大。"""

    result = {}
    for emotion in EMOTIONS:
        values = []
        for group in groups:
            if source_kind and source_kind not in group["source_kinds"]:
                continue
            value = _bounded(group["directional_support"].get(emotion))
            if value > 0:
                values.append(value)
        values.sort(reverse=True)
        result[emotion] = round(
            min(
                1.0,
                sum(
                    value * AGGREGATION_WEIGHTS[index]
                    for index, value in enumerate(
                        values[: len(AGGREGATION_WEIGHTS)]
                    )
                ),
            ),
            6,
        )
    return result


def _adjacent_options(previous_emotion, base_options):
    if previous_emotion not in EMOTION_LEVELS:
        return [item for item in base_options if item in EMOTION_LEVELS]
    previous_level = EMOTION_LEVELS[previous_emotion]
    return [
        item
        for item in base_options
        if item in EMOTION_LEVELS
        and abs(EMOTION_LEVELS[item] - previous_level) <= 1
    ]


def _emotion_utilities(profile, previous_emotion, directional_support):
    """融合Persona先验、方向性证据与上一轮惯性。"""

    priors = profile.get("emotion_prior", {})
    inertia = _bounded(profile.get("state_inertia"), 0.55)
    utilities = {}
    for emotion in EMOTIONS:
        utility = (
            PRIOR_UTILITY_WEIGHT * _bounded(priors.get(emotion), 1 / 3)
            + EVIDENCE_UTILITY_WEIGHT
            * _bounded(directional_support.get(emotion))
        )
        if emotion == previous_emotion:
            utility += INERTIA_UTILITY_WEIGHT * inertia
        utilities[emotion] = round(utility, 6)
    return utilities


def _supporting_groups(groups, emotion):
    candidates = [
        group
        for group in groups
        if _bounded(group["directional_support"].get(emotion)) > 0
        and (
            emotion != "positive"
            or group.get("positive_eligible") is True
        )
    ]
    candidates.sort(
        key=lambda group: _bounded(
            group["directional_support"].get(emotion)
        ),
        reverse=True,
    )
    return candidates


def resolve_strategy_emotion(
    profile,
    previous_state,
    appraised_evidence,
    base_emotion_options,
    current_step=None,
):
    """返回策略实验的唯一后续情绪及完整审计记录。

    第一轮无上一状态时仍保留全部合法选项，由LLM完成语义初始化。
    后续轮次由本地效用规则确定唯一状态，LLM只解释该结果。
    """

    previous_emotion = (previous_state or {}).get("current_emotion")
    if previous_emotion not in EMOTION_LEVELS:
        return {
            "resolution_version": "strategy_directional_utility_v3",
            "selected_emotion": None,
            "emotion_options": list(base_emotion_options),
            "state_change_basis": "initial_state",
            "transition_reason": "llm_initialization_without_previous_state",
            "emotion_utilities": {},
            "aggregated_directional_support": {
                emotion: 0.0 for emotion in EMOTIONS
            },
            "neighbor_directional_support": {
                emotion: 0.0 for emotion in EMOTIONS
            },
            "public_directional_support": {
                emotion: 0.0 for emotion in EMOTIONS
            },
            "utility_margin": None,
            "required_switch_margin": None,
            "supporting_evidence_ids": [],
            "directional_evidence_group_count": 0,
            "independent_neighbor_root_count": 0,
            "effective_non_peer_evidence_count": 0,
            "held_non_peer_evidence_count": 0,
            "peer_signal_strength": 0.0,
            "peer_change_threshold": None,
            "required_peer_root_count": 2,
            "peer_influence_eligible": False,
            "evidence_direction_by_id": {},
            "directional_evidence_groups": [],
            "evidence_lifecycle": {
                "new_group_count": 0,
                "restored_group_count": 0,
                "consumed_group_count": 0,
            },
            "strategy_evidence_memory": {},
            "strategy_evidence_assimilation": {},
            "evidence_assimilation": {
                "active_group_count": 0,
                "new_group_count": 0,
                "restored_group_count": 0,
                "expired_group_count": 0,
                "consumed_group_count": 0,
                "average_absorbed_fraction": None,
            },
        }

    new_groups, direction_by_id = _group_directional_evidence(
        appraised_evidence
    )
    assimilation = prepare_assimilated_groups(
        previous_state,
        current_step,
        new_groups,
        profile,
    )
    groups = assimilation["groups"]
    aggregate = _aggregate_direction(groups)
    neighbor_support = _aggregate_direction(groups, "neighbor")
    public_support = _aggregate_direction(groups, "public")
    utilities = _emotion_utilities(profile, previous_emotion, aggregate)
    options = _adjacent_options(previous_emotion, base_emotion_options)
    alternatives = [
        emotion for emotion in options if emotion != previous_emotion
    ]
    alternative_candidate = (
        max(
            alternatives,
            key=lambda emotion: utilities.get(emotion, 0.0),
        )
        if alternatives
        else previous_emotion
    )
    # 始终记录“最强相邻挑战状态－上一状态”的有符号效用差。
    # 即使最终保持，也能区分“几乎越界”和“上一状态明显占优”。
    utility_margin = (
        utilities.get(alternative_candidate, 0.0)
        - utilities.get(previous_emotion, 0.0)
    )
    candidate = (
        alternative_candidate if utility_margin > 0 else previous_emotion
    )
    inertia = _bounded(profile.get("state_inertia"), 0.55)
    previous_commitment = _bounded(
        profile.get("emotion_prior", {}).get(previous_emotion),
        1 / 3,
    )
    required_margin = max(
        _bounded(profile.get("emotion_switch_margin"), 0.02),
        # 2026/10/18，修改功能：变化边际同时考虑一般状态惯性和
        # Persona对上一情绪的长期先验承诺。它不会规定任何群体人数，
        # 但能避免一条强通告让不同长期倾向的Agent在同一轮全部转向。
        MIN_SWITCH_MARGIN
        + INERTIA_SWITCH_WEIGHT * inertia
        + PREVIOUS_COMMITMENT_SWITCH_WEIGHT * previous_commitment,
    )
    supporting_groups = _supporting_groups(groups, candidate)
    effective_supporting_groups = supporting_groups[:3]
    supporting_ids = [
        group["supporting_id_by_emotion"].get(candidate)
        for group in effective_supporting_groups
        if group["supporting_id_by_emotion"].get(candidate)
    ]
    authoritative_support = any(
        "authoritative" in group["source_kinds"]
        for group in supporting_groups
    )
    # 只有社会评论时至少需要两个独立根，防止单条弱评论
    # 直接覆盖Persona。官方/客观证据可单独作用，但仍须越过效用边际。
    independent_support_sufficient = (
        authoritative_support or len(supporting_groups) >= 2
    )
    if candidate == previous_emotion:
        selected = previous_emotion
        reason = "held_by_personal_utility"
        supporting_ids = []
    elif not supporting_ids:
        selected = previous_emotion
        reason = "held_without_directional_evidence"
    elif not independent_support_sufficient:
        selected = previous_emotion
        reason = "held_without_independent_roots"
        supporting_ids = []
    elif utility_margin < required_margin:
        selected = previous_emotion
        reason = "held_by_personal_margin"
        supporting_ids = []
    else:
        selected = candidate
        reason = "changed_after_directional_utility"

    consumed_group_ids = (
        [
            group["evidence_group_id"]
            for group in effective_supporting_groups
        ]
        if selected != previous_emotion
        else []
    )
    evidence_memory = update_evidence_memory(
        previous_state,
        current_step,
        new_groups,
        consumed_group_ids,
    )
    assimilation_memory = consume_assimilation_groups(
        assimilation["memory"],
        consumed_group_ids,
        current_step,
    )
    assimilation_diagnostics = {
        **assimilation["diagnostics"],
        "consumed_group_count": len(consumed_group_ids),
        "consumed_group_ids": list(consumed_group_ids),
    }

    neighbor_groups = [
        group for group in groups if "neighbor" in group["source_kinds"]
    ]
    non_peer_groups = [
        group for group in groups if "neighbor" not in group["source_kinds"]
    ]
    effective_non_peer = [
        group
        for group in non_peer_groups
        if max(group["directional_support"].values(), default=0.0) >= 0.08
    ]
    peer_signal = max(neighbor_support.values(), default=0.0)
    peer_threshold = round(required_margin / EVIDENCE_UTILITY_WEIGHT, 6)
    peer_eligible = (
        len(neighbor_groups) >= 2 and peer_signal >= peer_threshold
    )
    selected_sources = {
        source_kind
        for group in supporting_groups
        for source_kind in group["source_kinds"]
    }
    if selected != previous_emotion:
        basis = (
            "changed_by_peer_directional_evidence"
            if "neighbor" in selected_sources
            else "changed_by_non_peer_directional_evidence"
        )
    elif groups:
        basis = "held_by_directional_persona_utility"
    else:
        basis = "held_without_directional_evidence"

    return {
        "resolution_version": "strategy_directional_utility_v3",
        "selected_emotion": selected,
        "emotion_options": [selected],
        "state_change_basis": basis,
        "transition_reason": reason,
        "emotion_utilities": utilities,
        "aggregated_directional_support": aggregate,
        "neighbor_directional_support": neighbor_support,
        "public_directional_support": public_support,
        "utility_margin": round(utility_margin, 6),
        "required_switch_margin": round(required_margin, 6),
        "previous_emotion_commitment": round(previous_commitment, 6),
        "supporting_evidence_ids": supporting_ids,
        "directional_evidence_group_count": len(groups),
        "independent_neighbor_root_count": len(neighbor_groups),
        "new_public_evidence_count": len(
            [group for group in groups if "public" in group["source_kinds"]]
        ),
        "new_non_peer_evidence_count": len(non_peer_groups),
        "effective_non_peer_evidence_count": len(effective_non_peer),
        "held_non_peer_evidence_count": (
            len(non_peer_groups) - len(effective_non_peer)
        ),
        "peer_signal_strength": round(peer_signal, 6),
        "peer_change_threshold": peer_threshold,
        "required_peer_root_count": 2,
        "peer_influence_eligible": peer_eligible,
        "evidence_direction_by_id": direction_by_id,
        "directional_evidence_groups": groups,
        "evidence_lifecycle": {
            "new_group_count": len(new_groups),
            "restored_group_count": assimilation_diagnostics[
                "restored_group_count"
            ],
            "consumed_group_count": len(consumed_group_ids),
            "consumed_group_ids": consumed_group_ids,
        },
        "strategy_evidence_memory": evidence_memory,
        "strategy_evidence_assimilation": assimilation_memory,
        "evidence_assimilation": assimilation_diagnostics,
    }
