"""历史复现中面向单个 Persona 的证据影响评估。

客观证据强度由 ``simulation.evidence_policy`` 负责；本模块仅计算同一证据
对当前 Agent 的个人影响。

2026/10/14，修改功能：证据亲和度改为目标相关的加权组合，并恢复传播
边权的有限作用。避免 ``max`` 规则把不同 Persona 压缩成相近响应，同时
不让邻居意见替代已核实事实。
"""

from __future__ import annotations


_STRENGTH_BASE = {
    "background": 0.05,
    "weak": 0.16,
    "moderate": 0.38,
    "strong": 0.68,
}
_FACT_TARGETS = {
    "fact_clarification",
    "event_outcome",
    "identity_confirmation",
    "forensic_result",
}
_PROCESS_TARGETS = {
    "official_response",
    "investigation_process",
    "process_accountability",
}
_SOCIAL_TARGETS = {
    "public_discourse",
    "search_action",
    "social_action",
    "social_support",
}


def _bounded_rate(value, default=0.0):
    """把 Persona 概率字段转换为 0 到 1 之间的数值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _relative_topic_interest(persona, event_context):
    """返回事件主题相对于该 Persona 最高主题偏好的强度。"""

    preferences = persona.get("topic_preference", {})
    if not isinstance(preferences, dict) or not preferences:
        return 0.5
    labels = event_context.get("event_labels", {})
    labels = labels if isinstance(labels, dict) else {}
    values = [
        _bounded_rate(value)
        for value in preferences.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    maximum = max(values, default=0.0)
    if maximum <= 0:
        return 0.5
    return _bounded_rate(preferences.get(labels.get("topic")), 0.0) / maximum


def _evidence_target(evidence):
    """在缺少显式目标时按证据类型给出保守目标。"""

    target = str(evidence.get("evidence_target", "")).strip()
    if target:
        return target
    evidence_type = evidence.get("evidence_type")
    if evidence_type == "official_statement":
        return "official_response"
    if evidence_type in {"historical_verified_update", "objective_event"}:
        return "fact_clarification"
    return "public_discourse"


def _orientation_affinity_from_values(orientation, target):
    """按证据目标组合信息取向，保留 Persona 之间的结构差异。"""

    fact = _bounded_rate(orientation.get("fact"), 1 / 3)
    opinion = _bounded_rate(orientation.get("opinion"), 1 / 3)
    questioning = _bounded_rate(orientation.get("questioning"), 1 / 3)
    if target in _FACT_TARGETS:
        return 0.65 * fact + 0.10 * opinion + 0.25 * questioning
    if target in _PROCESS_TARGETS:
        return 0.25 * fact + 0.20 * opinion + 0.55 * questioning
    if target in _SOCIAL_TARGETS:
        return 0.15 * fact + 0.55 * opinion + 0.30 * questioning
    return (fact + opinion + questioning) / 3


def _orientation_affinity(persona, target):
    """从原始 Persona 计算信息取向亲和度，供缺少画像时兼容使用。"""

    source = persona.get("information_orientation", {})
    source = source if isinstance(source, dict) else {}
    orientation = {
        "fact": source.get("fact_rate", 1 / 3),
        "opinion": source.get("opinion_rate", 1 / 3),
        "questioning": source.get("questioning_rate", 1 / 3),
    }
    return _orientation_affinity_from_values(orientation, target)


def _previous_emotion_inertia(persona, previous_state):
    """用长期表达倾向估计上一轮情绪的个体惯性。"""

    previous_emotion = (previous_state or {}).get("current_emotion")
    profile = persona.get("emotion_expression", {})
    profile = profile if isinstance(profile, dict) else {}
    if previous_emotion not in {"positive", "neutral", "negative"}:
        return 0.33
    return _bounded_rate(profile.get(f"{previous_emotion}_rate"), 0.33)


def _change_mode(strength, score, adjacent_threshold):
    """将个人影响分数转换为离散状态的转移许可。"""

    if strength in {"background", "weak"}:
        return "hold_only"
    if score < adjacent_threshold:
        return "hold_only"
    if strength == "strong" and score >= 0.78:
        return "full_reassessment"
    return "adjacent_allowed"


def appraise_evidence_for_persona(
    evidence_items,
    persona,
    event_context,
    previous_state=None,
    decision_profile=None,
):
    """为每条证据添加情绪与官方态度的独立个体影响评估。"""

    topic_interest = (
        _bounded_rate(decision_profile.get("topic_interest"), 0.5)
        if isinstance(decision_profile, dict)
        else _relative_topic_interest(persona, event_context)
    )
    emotion_inertia = _previous_emotion_inertia(persona, previous_state)
    appraised = []
    for source in evidence_items:
        item = dict(source)
        strength = str(item.get("evidence_strength", "background"))
        base = _STRENGTH_BASE.get(strength, 0.05)
        target = _evidence_target(item)
        if isinstance(decision_profile, dict):
            orientation = decision_profile.get("orientation", {})
            affinity = _orientation_affinity_from_values(orientation, target)
            emotion_threshold = _bounded_rate(
                decision_profile.get("emotion_change_threshold"), 0.60
            )
            attitude_threshold = _bounded_rate(
                decision_profile.get("attitude_change_threshold"), 0.64
            )
        else:
            affinity = _orientation_affinity(persona, target)
            emotion_threshold = 0.60
            attitude_threshold = 0.64

        # 2026/10/14，修改功能：强度决定证据上限，主题兴趣和取向只调节
        # 实际吸收比例。使用乘法而非固定加数，防止多名 Agent 面对普通
        # 信息时都轻易越过变化门槛。
        attention_weight = affinity
        emotion_score = base * (
            0.58 + 0.22 * topic_interest + 0.20 * affinity
        )
        attitude_score = base * (
            0.60 + 0.20 * topic_interest + 0.20 * affinity
        )
        network_modifier = 1.0
        if (
            isinstance(decision_profile, dict)
            and item.get("evidence_type") == "simulated_comment"
        ):
            conformity = _bounded_rate(
                decision_profile.get("public_conformity"), 0.35
            )
            emotion_score *= 0.55 + 0.45 * conformity
            attitude_score *= 0.45 + 0.35 * conformity
            # 邻居边权只对个人可见评论产生有限调节。公共评论没有边权时
            # 保持 1.0；邻居信息最多改变 15%，不能替代客观事实证据。
            raw_network_weight = item.get("network_influence_weight")
            if isinstance(raw_network_weight, (int, float)) and not isinstance(
                raw_network_weight,
                bool,
            ):
                network_modifier = 0.85 + 0.15 * _bounded_rate(
                    raw_network_weight,
                    0.5,
                )
                emotion_score *= network_modifier
                attitude_score *= network_modifier

        emotion_score = min(1.0, emotion_score)
        attitude_score = min(1.0, attitude_score)
        item["evidence_target"] = target
        item["personal_impact"] = {
            "topic_interest": round(topic_interest, 6),
            "orientation_affinity": round(affinity, 6),
            "emotion_inertia": round(emotion_inertia, 6),
            "attention_weight": round(attention_weight, 6),
            "network_modifier": round(network_modifier, 6),
            "emotion_score": round(emotion_score, 6),
            "official_attitude_score": round(attitude_score, 6),
            "emotion_change_threshold": round(emotion_threshold, 6),
            "official_attitude_change_threshold": round(
                attitude_threshold, 6
            ),
            "emotion_change_mode": _change_mode(
                strength, emotion_score, emotion_threshold
            ),
            "official_attitude_change_mode": _change_mode(
                strength, attitude_score, attitude_threshold
            ),
        }
        appraised.append(item)
    return appraised


def build_transition_evidence_sets(evidence_items):
    """构造状态变化校验所需的证据编号集合。"""

    result = {
        "state_change_evidence_ids": [],
        "evidence_group_by_id": {},
        "emotion_single_change_evidence_ids": [],
        "emotion_full_reassessment_evidence_ids": [],
        "official_attitude_single_change_evidence_ids": [],
        "official_attitude_full_reassessment_evidence_ids": [],
    }
    for item in evidence_items:
        evidence_id = item.get("evidence_id")
        if not evidence_id or item.get("is_new_this_step") is not True:
            continue
        if item.get("comment_source") == "current_emergency":
            continue
        result["evidence_group_by_id"][evidence_id] = str(
            item.get("evidence_group_id", evidence_id)
        )
        if item.get("evidence_strength") != "background":
            result["state_change_evidence_ids"].append(evidence_id)
        impact = item.get("personal_impact", {})
        emotion_mode = impact.get("emotion_change_mode")
        if emotion_mode in {"adjacent_allowed", "full_reassessment"}:
            result["emotion_single_change_evidence_ids"].append(evidence_id)
        if emotion_mode == "full_reassessment":
            result["emotion_full_reassessment_evidence_ids"].append(
                evidence_id
            )
        attitude_mode = impact.get("official_attitude_change_mode")
        if attitude_mode in {"adjacent_allowed", "full_reassessment"}:
            result["official_attitude_single_change_evidence_ids"].append(
                evidence_id
            )
        if attitude_mode == "full_reassessment":
            result[
                "official_attitude_full_reassessment_evidence_ids"
            ].append(evidence_id)
    return result


def summarize_used_evidence_appraisal(evidence_items, used_ids):
    """返回决策实际引用证据的精简个人评估，供实验结果审计。"""

    requested = {str(value) for value in used_ids if value}
    summary = []
    for item in evidence_items:
        evidence_id = str(item.get("evidence_id", ""))
        if evidence_id not in requested:
            continue
        summary.append(
            {
                "evidence_id": evidence_id,
                "evidence_group_id": item.get(
                    "evidence_group_id", evidence_id
                ),
                "evidence_strength": item.get("evidence_strength"),
                "evidence_target": item.get("evidence_target"),
                "personal_impact": dict(item.get("personal_impact", {})),
            }
        )
    return summary
