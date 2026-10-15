"""历史趋势复现的发言资格评估。

本模块只回答“Agent本轮是否有必要公开表达”，不改变其内部情绪和
官方态度，也不参与五策略实验。LLM仍先表达主观意愿；规则层只在
缺少状态变化或新观点时抑制连续重复发言。强证据只增加个体发言动机，
不再自动绕过沉默约束。
"""

from __future__ import annotations

from difflib import SequenceMatcher

from agents.decision_engine import collect_current_evidence
from agents.evidence_appraisal import appraise_evidence_for_persona


PARTICIPATION_THRESHOLD = 0.38
REPEATED_EXPRESSION_THRESHOLD = 0.72


def _bounded_rate(value, default=0.0):
    """把Persona中的概率字段安全转换到0到1。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _relative_topic_interest(persona, event_context):
    """返回事件主题相对于该Persona最高主题偏好的强度。"""

    preferences = persona.get("topic_preference", {})
    if not isinstance(preferences, dict) or not preferences:
        return 0.5
    event_labels = event_context.get("event_labels", {})
    if not isinstance(event_labels, dict):
        event_labels = {}
    topic = event_labels.get("topic")
    values = [
        _bounded_rate(value)
        for value in preferences.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    maximum = max(values, default=0.0)
    if maximum <= 0:
        return 0.5
    return _bounded_rate(preferences.get(topic), 0.0) / maximum


def _expression_similarity(expression, own_comment_history):
    """比较本轮表达与最近三次个人表达，返回最高字符序列相似度。"""

    if not isinstance(expression, dict):
        return 0.0
    text = str(expression.get("text", "")).strip()
    if not text:
        return 0.0
    previous_texts = [
        str(item.get("text", "")).strip()
        for item in own_comment_history[-3:]
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    return max(
        (
            SequenceMatcher(None, text, previous_text).ratio()
            for previous_text in previous_texts
        ),
        default=0.0,
    )


def _used_evidence_ids(decision, previous_state):
    """汇总实际推动状态或表达的证据编号。

    官方态度未变化时，态度依据只是持续判断背景，不能自动成为本轮
    发言的强触发器；只有态度发生变化时才计入参与动机。
    """

    evidence_ids = set()
    emotion_evidence = decision.get("emotion_evidence_ids", [])
    if isinstance(emotion_evidence, list):
        evidence_ids.update(str(value) for value in emotion_evidence if value)
    if (
        previous_state.get("official_attitude")
        in {"accept", "wait", "question"}
        and decision.get("official_attitude")
        != previous_state.get("official_attitude")
    ):
        attitude_evidence = decision.get("official_attitude_evidence_ids", [])
        if isinstance(attitude_evidence, list):
            evidence_ids.update(
                str(value) for value in attitude_evidence if value
            )
    expression = decision.get("expression")
    if isinstance(expression, dict) and isinstance(
        expression.get("evidence_ids"), list
    ):
        evidence_ids.update(
            str(value) for value in expression["evidence_ids"] if value
        )
    return evidence_ids


def _state_changed(decision, previous_state):
    """判断情绪或适用的官方态度是否相较上一轮发生变化。"""

    previous_emotion = previous_state.get("current_emotion")
    emotion_changed = bool(previous_emotion) and (
        decision.get("current_emotion") != previous_emotion
    )
    previous_attitude = previous_state.get("official_attitude")
    attitude_changed = previous_attitude in {"accept", "wait", "question"} and (
        decision.get("official_attitude") != previous_attitude
    )
    return emotion_changed or attitude_changed


def apply_historical_participation_policy(
    decision,
    persona,
    event_context,
    visible_comments,
    previous_state,
    history_summary,
):
    """按新颖性、状态变化、Persona和连续发言疲劳评估是否发言。

    该函数不设置沉默配额。个人状态变化保留表达机会；强证据只按照
    Persona相关性增加动机，不能单独保证发言。只有LLM原本想发言但
    动机弱且连续表达时，才改为可解释的沉默。
    """

    result = dict(decision)
    decision_profile = result.get("persona_decision_profile")
    evidence = appraise_evidence_for_persona(
        collect_current_evidence(event_context, visible_comments),
        persona,
        event_context,
        previous_state,
        decision_profile,
    )
    used_ids = _used_evidence_ids(result, previous_state)
    new_ids = {
        str(item.get("evidence_id"))
        for item in evidence
        if item.get("evidence_id")
        and item.get("is_new_this_step") is True
        and item.get("comment_source") != "current_emergency"
    }
    strong_ids = {
        str(item.get("evidence_id"))
        for item in evidence
        if item.get("evidence_id")
        and item.get("is_new_this_step") is True
        and item.get("evidence_strength") == "strong"
    }
    relevant_new_ids = sorted(used_ids.intersection(new_ids))
    used_strong_ids = sorted(used_ids.intersection(strong_ids))
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in evidence
        if item.get("evidence_id")
    }
    personal_impact = 0.0
    for evidence_id in used_ids:
        impact = evidence_by_id.get(evidence_id, {}).get(
            "personal_impact",
            {},
        )
        personal_impact = max(
            personal_impact,
            float(impact.get("emotion_score", 0.0) or 0.0),
            float(impact.get("official_attitude_score", 0.0) or 0.0),
        )
    state_changed = _state_changed(result, previous_state)
    consecutive_rounds = int(
        history_summary.get("consecutive_comment_rounds", 0) or 0
    )
    similarity = _expression_similarity(
        result.get("expression"),
        history_summary.get("own_comment_history", []),
    )
    repeated_expression = similarity >= REPEATED_EXPRESSION_THRESHOLD

    action_preference = persona.get("action_preference", {})
    if not isinstance(action_preference, dict):
        action_preference = {}
    topic_interest = _relative_topic_interest(persona, event_context)
    original_preference = _bounded_rate(
        action_preference.get("original_preference"),
        0.5,
    )
    score = (
        0.23
        + 0.15 * topic_interest
        + 0.15 * original_preference
        + (0.15 if relevant_new_ids else 0.0)
        # 2026/10/14，修改功能：状态变化提高表达动机，但不再保证发言。
        # 是否公开表达仍需通过新颖性、重复和连续发言疲劳约束。
        + (0.15 if state_changed else 0.0)
        + 0.12 * personal_impact
        - min(consecutive_rounds, 3) * 0.05
        - (0.25 if repeated_expression else 0.0)
        - (0.12 if not relevant_new_ids else 0.0)
    )
    score = round(max(0.0, min(1.0, score)), 6)

    participation_threshold = PARTICIPATION_THRESHOLD
    if isinstance(decision_profile, dict):
        # 2026/10/13，Persona差异化表达：原创偏好和主题关注度已经
        # 汇总到表达门槛；这里只做小范围映射，避免画像参数取代
        # 新颖性、疲劳等行为约束。
        participation_threshold = round(
            0.26
            + 0.30
            * _bounded_rate(
                decision_profile.get("expression_threshold"),
                0.4,
            ),
            6,
        )

    assessment = {
        "llm_will_comment": result.get("will_comment") is True,
        "participation_score": score,
        "threshold": participation_threshold,
        "has_relevant_new_evidence": bool(relevant_new_ids),
        "relevant_new_evidence_ids": relevant_new_ids,
        "used_strong_evidence_ids": used_strong_ids,
        "max_personal_evidence_impact": round(personal_impact, 6),
        "state_changed": state_changed,
        "consecutive_comment_rounds": consecutive_rounds,
        "expression_similarity": round(similarity, 6),
        "repeated_expression": repeated_expression,
        # 2026/10/14，修改功能：发言资格只由关注度、行动偏好、证据
        # 新颖性和疲劳决定，不再因当前是negative而获得额外分数。
        "emotion_independent_scoring": True,
    }

    if result.get("will_comment") is not True:
        result["silence_reason"] = "agent_chose_silence"
        assessment["eligible_to_comment"] = False
        assessment["policy_overrode_llm"] = False
        result["participation_assessment"] = assessment
        return result

    weak_motivation = (
        consecutive_rounds >= 2
        or repeated_expression
        or not relevant_new_ids
    )
    should_silence = weak_motivation and score < participation_threshold
    if should_silence:
        if repeated_expression:
            silence_reason = "repeated_view_without_state_change"
        elif not relevant_new_ids:
            silence_reason = "no_relevant_new_evidence"
        else:
            silence_reason = "consecutive_comment_fatigue"
        result["will_comment"] = False
        result["comment_faction"] = None
        result["expression"] = None
        result["silence_reason"] = silence_reason
        reasons = dict(result.get("decision_reason", {}))
        reasons["comment"] = (
            "本轮内部状态未变化，且连续表达后的新增公开表达动机不足，"
            "因此保持沉默。"
        )
        result["decision_reason"] = reasons
        assessment["eligible_to_comment"] = False
        assessment["policy_overrode_llm"] = True
    else:
        result["silence_reason"] = None
        assessment["eligible_to_comment"] = True
        assessment["policy_overrode_llm"] = False

    result["participation_assessment"] = assessment
    return result
