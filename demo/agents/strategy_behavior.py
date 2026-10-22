"""回应方案对照实验的 Agent 公开行为门控。

本模块只决定“本轮是否表达”以及规范化动作，不改写 Agent
已经形成的情绪和官方态度。随机门控由事件、Agent 和轮次唯一
确定，不包含策略编号，因而三个回应方案与基线使用同一组个体
行动随机数，避免把采样差异误解为方案效果。
"""

from __future__ import annotations

import hashlib
import math

from simulation.options import allows_reshare_action


OFFICIAL_ATTITUDES = {"accept", "wait", "question"}

def _stable_unit_interval(event_id, agent_id, step, purpose):
    """返回可重复的 [0, 1) 伪随机数，不依赖全局随机状态。"""

    identity = f"{event_id}|{agent_id}|{step}|{purpose}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def _clamp(value, lower=0.05, upper=0.90):
    return max(lower, min(upper, value))


def _topic_interest(persona, event_context):
    topic = event_context.get("event_labels", {}).get("topic", "其他")
    return _clamp(
        float(persona.get("topic_preference", {}).get(topic, 0.0)),
        0.0,
        1.0,
    )


def _activity_level(persona):
    total_posts = persona.get("data_info", {}).get("total_posts", 0)
    if isinstance(total_posts, bool) or not isinstance(
        total_posts,
        (int, float),
    ):
        total_posts = 0
    # 对数压缩防止历史微博极多的少数用户几乎永远发言。
    return _clamp(
        math.log1p(max(0, total_posts)) / math.log1p(5000),
        0.0,
        1.0,
    )


def _has_state_change(decision, previous_state):
    """只识别真实状态转移，不把官方态度开始适用视为心理变化。"""

    previous_emotion = previous_state.get("current_emotion")
    previous_attitude = previous_state.get("official_attitude")
    current_attitude = decision.get("official_attitude")
    return bool(
        (
            previous_emotion
            and decision.get("current_emotion") != previous_emotion
        )
        or (
            previous_attitude in OFFICIAL_ATTITUDES
            and current_attitude in OFFICIAL_ATTITUDES
            and current_attitude != previous_attitude
        )
    )


def _official_response_motivation(decision, event_context):
    """首次通告按个体最终态度提供有限表达动机。"""

    timing = event_context.get("current_state", {}).get(
        "official_statement_timing",
        {},
    )
    if not isinstance(timing, dict) or timing.get("is_new") is not True:
        return 0.0
    return {
        "accept": 0.06,
        "question": 0.08,
        "wait": 0.02,
    }.get(decision.get("official_attitude"), 0.0)


def _has_current_information(visible_comments, current_step, seen_comment_ids):
    seen_ids = set(seen_comment_ids or [])
    return any(
        isinstance(comment, dict)
        and comment.get("introduced_step") == current_step
        and comment.get("comment_id") not in seen_ids
        for comment in visible_comments
    )


def _directional_evidence_motivation(decision):
    """把状态层的方向性证据张力转换为有限的公开表达动机。

    2026/10/18，新增功能：发言门控不再只知道“本轮有没有新评论”，
    而是读取状态层已经审计过的证据相关度和效用差。该分数只影响
    是否表达，不修改内部情绪，也不按正负极性区别对待Agent。
    """

    diagnostics = decision.get("state_transition_diagnostics", {})
    support = diagnostics.get("aggregated_directional_support", {})
    if not isinstance(support, dict):
        support = {}
    strongest_support = max(
        (
            float(value)
            for value in support.values()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
        ),
        default=0.0,
    )
    margin = diagnostics.get("utility_margin")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)):
        margin = 0.0
    group_count = diagnostics.get("directional_evidence_group_count", 0)
    if isinstance(group_count, bool) or not isinstance(
        group_count,
        (int, float),
    ):
        group_count = 0
    # 证据越切身、相邻状态对当前状态的正向挑战越强，越可能促使
    # Agent表达；两项合计最多0.12，避免重新造成“有通告就全体发言”。
    evidence_relevance = 0.08 * _clamp(
        strongest_support,
        0.0,
        1.0,
    )
    utility_tension = (
        0.04
        * _clamp(max(0.0, float(margin)) / 0.25, 0.0, 1.0)
        if group_count > 0
        else 0.0
    )
    return evidence_relevance, utility_tension


def _choose_comment_faction(persona):
    """按Persona稳定选择公开表达派系，不让状态LLM兼任行为判断。"""

    preferences = persona.get("comment_faction_preference", {})
    if not isinstance(preferences, dict) or not preferences:
        return "观点输出派"
    return max(
        preferences,
        key=lambda name: (float(preferences.get(name, 0.0)), str(name)),
    )


def _choose_reshare_comment(visible_comments, event_id, agent_id, step):
    """从个人可见范围稳定选择一条转发对象。"""

    eligible = [
        item
        for item in visible_comments
        if isinstance(item, dict) and item.get("comment_id")
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda item: _stable_unit_interval(
            event_id,
            agent_id,
            step,
            f"strategy-reshare:{item.get('comment_id')}",
        ),
    )


def _choose_action(persona, event_context, visible_comments):
    """依据Persona动作偏好在原创和转发之间独立选择。"""

    event_id = str(event_context.get("event_id", ""))
    step = event_context.get("current_state", {}).get("step", 0)
    agent_id = str(persona.get("agent_id", ""))
    preference = persona.get("action_preference", {})
    original = max(float(preference.get("original_preference", 0.5)), 0.0)
    repost = max(float(preference.get("repost_preference", 0.5)), 0.0)
    total = original + repost
    reshare_probability = repost / total if total else 0.5
    reshare_comment = _choose_reshare_comment(
        visible_comments,
        event_id,
        agent_id,
        step,
    )
    if (
        allows_reshare_action(event_context)
        and reshare_comment is not None
        and _stable_unit_interval(
            event_id,
            agent_id,
            step,
            "strategy-action",
        ) < reshare_probability
    ):
        return "reshare", reshare_comment
    return "original", None


# 2026/10/16，新增功能：用 Persona、上一轮状态、当轮新信息和
# 连续发言疲劳共同决定是否公开表达。该评分不使用情绪极性，
# 避免“负面 Agent 天然更爱发言”造成观测偏差。
def apply_strategy_participation_policy(
    decision,
    persona,
    event_context,
    visible_comments,
    previous_state,
    history_summary,
):
    """独立决定策略实验的发言意愿和动作，不读取LLM发言意愿。"""

    normalized = dict(decision)

    current_step = event_context.get("current_state", {}).get("step", 0)
    event_id = str(event_context.get("event_id", ""))
    agent_id = str(persona.get("agent_id", ""))
    consecutive_rounds = int(
        history_summary.get("consecutive_comment_rounds", 0) or 0
    )
    state_changed = _has_state_change(normalized, previous_state)
    has_current_information = _has_current_information(
        visible_comments,
        current_step,
        history_summary.get("seen_comment_ids", []),
    )
    evidence_relevance, utility_tension = (
        _directional_evidence_motivation(normalized)
    )

    score_components = {
        "base": 0.18,
        "topic_interest": 0.24 * _topic_interest(persona, event_context),
        "historical_activity": 0.14 * _activity_level(persona),
        "state_change": 0.20 if state_changed else 0.0,
        # 2026/10/18，修改功能：把“只要看到新评论就加分”拆为较小的
        # 新鲜度项，以及来自状态证据整合器的相关度和效用张力项。
        # 这样不同回应方案可以产生不同参与者，但不会按方案编号加权。
        "current_information": 0.08 if has_current_information else 0.0,
        "directional_evidence_relevance": evidence_relevance,
        "state_utility_tension": utility_tension,
        # 2026/10/18，修改功能：首次通告不再让所有Agent因
        # not_applicable→wait统一获得状态变化加分；接受、质疑和观望
        # 只产生小幅且不同的公开表达动机。
        "official_response_motivation": _official_response_motivation(
            normalized,
            event_context,
        ),
        "continuous_speaking_fatigue": -0.08 * min(consecutive_rounds, 3),
    }
    participation_score = _clamp(sum(score_components.values()))
    sample = _stable_unit_interval(
        event_id,
        agent_id,
        current_step,
        "strategy-participation",
    )
    # 2026/10/17，修改功能：发言门控只使用Persona、状态变化、
    # 新信息与疲劳，不再把LLM输出的will_comment当成必要条件。
    will_comment = sample < participation_score
    action_type = "silent"
    reshare_comment = None
    if will_comment:
        action_type, reshare_comment = _choose_action(
            persona,
            event_context,
            visible_comments,
        )

    normalized["will_comment"] = will_comment
    normalized["action_type"] = action_type
    normalized["comment_faction"] = (
        _choose_comment_faction(persona) if will_comment else None
    )
    normalized["expression"] = None
    normalized["reshare_comment_id"] = (
        reshare_comment.get("comment_id")
        if isinstance(reshare_comment, dict)
        else None
    )
    normalized["participation_assessment"] = {
        "mode": "persona_state_gate",
        "score": round(participation_score, 6),
        "sample": round(sample, 6),
        "decision_source": "deterministic_persona_gate",
        "state_changed": state_changed,
        "has_current_information": has_current_information,
        "consecutive_comment_rounds": consecutive_rounds,
        "components": {
            key: round(value, 6) for key, value in score_components.items()
        },
    }
    if not will_comment:
        normalized["silence_reason"] = (
            "Persona、当轮信息与连续发言疲劳综合门控"
        )
        decision_reason = dict(normalized.get("decision_reason", {}))
        decision_reason["comment"] = normalized["silence_reason"]
        normalized["decision_reason"] = decision_reason
    else:
        decision_reason = dict(normalized.get("decision_reason", {}))
        decision_reason["comment"] = (
            "独立行为门控判定本轮参与表达；动作由Persona偏好确定。"
        )
        normalized["decision_reason"] = decision_reason
    return normalized
