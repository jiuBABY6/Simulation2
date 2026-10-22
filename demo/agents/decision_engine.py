"""Agent 决策领域逻辑。

本模块只处理 Persona、事件状态和候选评论之间的规则关系，
不负责文件读写，也不负责发送网络请求。
"""

import hashlib
import json
import random
from difflib import SequenceMatcher

from agents.evidence_appraisal import (
    appraise_evidence_for_persona,
    build_transition_evidence_sets,
    summarize_used_evidence_appraisal,
)
from agents.decision_profile import (
    build_persona_decision_profile,
    build_personalized_decision_guard,
)
from agents.strategy_state_transition import (
    attach_strategy_state_audit,
    build_strategy_state_prompt_guard,
    build_strategy_state_guard,
)
from domain.comment_semantics import normalize_evidence_semantics
from simulation.evidence_policy import (
    build_official_statement_evidence,
    build_official_statement_evidence_units,
    normalize_evidence_strength,
    objective_event_is_positive_eligible,
    objective_event_strength,
    verified_update_strength,
)
from simulation.options import (
    allows_reshare_action,
    uses_agent_generated_expression,
    uses_evidence_based_emotions,
    uses_strategy_participation_gate,
)


FACTIONS = [
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
]
ALL_EMOTIONS = ["positive", "neutral", "negative"]
EXPRESSION_STANCES = ["support", "neutral", "questioning", "criticism"]
MAX_EXPRESSION_LENGTH = 280
EMOTION_LEVELS = {"negative": -1, "neutral": 0, "positive": 1}
EMOTION_TARGETS = {
    "event_outcome",
    "official_response",
    "social_action",
    "public_discourse",
}
PERSONA_FACTOR_OPTIONS = (
    "topic_interest",
    "fact_orientation",
    "opinion_orientation",
    "questioning_orientation",
    "emotion_expression_prior",
    "comment_faction_preference",
)


def _visible_comment_evidence_group_id(comment):
    """优先使用传播根作为证据组，避免同一观点链重复计权。"""

    root_ids = comment.get("root_expression_ids")
    if isinstance(root_ids, list):
        normalized = sorted(str(item) for item in root_ids if item)
        if normalized:
            return "|".join(normalized)
    return str(comment.get("comment_id", ""))


def collect_current_evidence(event_context, candidates=None):
    """汇总公众语境、官方声明和个人可见评论等当前证据。"""

    state = event_context.get("current_state", {})
    objective_context = state.get("objective_event_context", {})
    evidence = []
    public_context = state.get("public_context", {})
    if isinstance(public_context, dict):
        for item in public_context.get("verified_updates", []):
            if isinstance(item, dict) and item.get("evidence_id"):
                evidence.append(
                    {
                        "evidence_id": str(item["evidence_id"]),
                        "evidence_type": "historical_verified_update",
                        "content": str(item.get("content", "")),
                        "update_kind": item.get("update_kind"),
                        "evidence_group_id": item.get(
                            "claim_id",
                            item["evidence_id"],
                        ),
                        "evidence_target": item.get(
                            "evidence_target",
                            "fact_clarification",
                        ),
                        "exposure_scope": "public_context",
                        "is_new_this_step": True,
                        "evidence_strength": verified_update_strength(item),
                        "positive_eligible": False,
                    }
                )
    individual_context = state.get("individual_public_context", {})
    if isinstance(individual_context, dict):
        for item in individual_context.get("public_discourse", []):
            if isinstance(item, dict) and item.get("context_id"):
                evidence.append(
                    {
                        "evidence_id": str(item["context_id"]),
                        "evidence_type": "historical_public_discourse",
                        "evidence_group_id": item["context_id"],
                        "content": str(item.get("content", "")),
                        "status": item.get("status"),
                        "unresolved_concern": bool(
                            item.get("unresolved_concern", False)
                        ),
                        "exposure_scope": "individual_public_context",
                        "is_new_this_step": True,
                        "evidence_strength": "weak",
                        "positive_eligible": (
                            item.get("status") == "social_action"
                        ),
                    }
                )
        for item in individual_context.get("positive_evidence", []):
            if isinstance(item, dict) and item.get("evidence_id"):
                evidence.append(
                    {
                        "evidence_id": str(item["evidence_id"]),
                        "evidence_type": "historical_positive_evidence",
                        "evidence_group_id": item["evidence_id"],
                        "content": str(item.get("content", "")),
                        "target": item.get("target"),
                        "evidence_target": item.get(
                            "target",
                            "social_action",
                        ),
                        "exposure_scope": "individual_public_context",
                        "is_new_this_step": True,
                        "evidence_strength": normalize_evidence_strength(
                            item.get("evidence_strength"),
                            "moderate",
                        ),
                        "positive_eligible": True,
                    }
                )
    if isinstance(objective_context, dict):
        for item in objective_context.get("events", []):
            if not isinstance(item, dict) or not item.get(
                "objective_event_id"
            ):
                continue
            event_type = str(item.get("event_type", ""))
            evidence.append(
                {
                    "evidence_id": str(item["objective_event_id"]),
                    "evidence_type": "objective_event",
                    "evidence_group_id": item.get(
                        "claim_id",
                        item["objective_event_id"],
                    ),
                    "event_type": event_type,
                    "content": str(item.get("content", "")),
                    "evidence_target": item.get(
                        "evidence_target",
                        "fact_clarification",
                    ),
                    "exposure_scope": "objective_event",
                    "is_new_this_step": True,
                    "evidence_strength": objective_event_strength(
                        event_type,
                        item.get("evidence_strength"),
                    ),
                    "positive_eligible": objective_event_is_positive_eligible(
                        event_type
                    ),
                }
            )

    official_evidence = build_official_statement_evidence(state)
    if official_evidence is not None:
        official_evidence = {
            **official_evidence,
            "evidence_group_id": official_evidence["evidence_id"],
            "exposure_scope": "official_broadcast",
            "is_new_this_step": bool(official_evidence.get("is_new")),
        }
        evidence.append(official_evidence)
        for unit in build_official_statement_evidence_units(state):
            evidence.append(
                {
                    **unit,
                    "exposure_scope": "official_broadcast",
                    "is_new_this_step": bool(unit.get("is_new")),
                }
            )

    current_step = state.get("step")
    for item in candidates or []:
        if not isinstance(item, dict) or not item.get("comment_id"):
            continue
        source = classify_visible_comment_source(item, current_step)
        if source == "historical":
            continue
        evidence.append(
            normalize_evidence_semantics({
                "evidence_id": str(item["comment_id"]),
                "evidence_type": "simulated_comment",
                "evidence_group_id": _visible_comment_evidence_group_id(
                    item
                ),
                "comment_source": source,
                "content": str(item.get("text", "")),
                "emotion": item.get("emotion"),
                "stance": item.get("stance"),
                "evidence_target": item.get(
                    "reaction_target",
                    item.get("emotion_target", "public_discourse"),
                ),
                "reaction_target": item.get(
                    "reaction_target",
                    item.get("emotion_target", "public_discourse"),
                ),
                "evidence_role": item.get("evidence_role", "opinion"),
                "claim_id": item.get("claim_id"),
                "information_source_type": item.get(
                    "information_source_type"
                ),
                "information_origin": item.get("information_origin"),
                "provenance_type": item.get(
                    "provenance_type", item.get("source_type")
                ),
                # 2026/10/12，个体曝光约束：候选评论来自该 Agent
                # 的个人可见集合；历史评论不再作为本轮决策证据，只有
                # 本轮生成或经邻居传播而首次看到的评论才可触发状态变化。
                "exposure_scope": "individual_visible_comment",
                "is_new_this_step": source != "historical",
                "evidence_strength": (
                    "background" if source == "historical" else "weak"
                ),
                "positive_eligible": item.get("emotion") == "positive",
                # 2026/10/13，邻居来源权重，新增功能：把传播层已经计算的
                # 有效边权带入个体证据评估；公共评论没有该字段时使用中性
                # 基准，不根据来源身份臆造可信度。
                "network_influence_weight": item.get(
                    "normalized_propagation_weight",
                    item.get("propagation_weight"),
                ),
                "raw_network_influence_weight": item.get(
                    "propagation_weight"
                ),
                "source_agent_ids": item.get("source_agent_ids", []),
                "propagation_depth": item.get("propagation_depth"),
            })
        )
    # 2026/10/19，新增功能：所有证据在进入Persona评估前使用同一套
    # 语义契约。旧事件缺少字段时保守补全，普通公众观点不会被视为
    # 已核实事实；该步骤不调用LLM，也不修改原评论对象。
    return [normalize_evidence_semantics(item) for item in evidence]


def get_emotion_options(event_context, policy):
    """按事件级开关返回情绪选项；默认继续使用现有政策约束。"""

    if uses_evidence_based_emotions(event_context):
        # 历史复现显式使用三分类证据情绪；回应方案
        # 对照已恢复到2026/10/15批次的政策候选状态。
        return list(ALL_EMOTIONS)
    event_valence = event_context.get("event_labels", {}).get(
        "event_valence", "neutral"
    )
    return policy.get("candidate_rules", {}).get("emotion", {}).get(
        event_valence, ["neutral"]
    )

# 辅助函数
def get_level(value, quantiles):
    """根据字段自己的 P25、P75 分位数返回 low、medium 或 high。"""
    if not quantiles:
        return "medium"
    if value < quantiles.get("p25", 0.33):
        return "low"
    if value < quantiles.get("p75", 0.66):
        return "medium"
    return "high"


# 2026/08/25 第六次联调问题修复，新增功能：构造不包含预设情绪标签的 Agent 事件视图。
def build_agent_event_view(event_context):
    """保留事件原文、主题和当前声明，不向 Agent 暴露 event_valence。"""
    state = event_context.get("current_state", {})
    statement_timing = state.get("official_statement_timing", {})
    current_state_view = {
        "step": state.get("step"),
        "official_statement": state.get("official_statement", ""),
        "official_statement_status": state.get(
            "official_statement_status",
            "none",
        ),
        # 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：明确声明是本轮新发布还是历史声明继续有效。
        "official_statement_timing": {
            "introduced_step": statement_timing.get("introduced_step"),
            "active_round_count": statement_timing.get(
                "active_round_count",
                0,
            ),
            "is_new": statement_timing.get("is_new", False),
        },
    }
    # 2026/10/12，历史回放只把已核实事实作为公共广播；争议讨论和
    # 建设性证据由上游按 Agent 抽样后放入 individual_public_context。
    if state.get("public_context") is not None:
        current_state_view["public_context"] = state.get("public_context")
        current_state_view["public_context_timing"] = state.get(
            "public_context_timing"
        )
    if state.get("individual_public_context") is not None:
        current_state_view["individual_public_context"] = state.get(
            "individual_public_context"
        )
    if state.get("objective_event_context") is not None:
        current_state_view["objective_event_context"] = state.get(
            "objective_event_context"
        )
        current_state_view["objective_event_timing"] = state.get(
            "objective_event_timing"
        )
    return {
        "event_id": event_context.get("event_id"),
        "event_content": event_context.get("event_content", ""),
        "event_topic": event_context.get("event_labels", {}).get(
            "topic",
            "其他",
        ),
        "current_state": current_state_view,
    }


# 2026/08/25 第六次联调问题修复，新增功能：将现有 Persona 比例转换为可解释的决策摘要。
# 2026/08/27 Agent情绪状态转换，修改功能：将情绪表达明确为长期倾向，不再提供预设主导情绪。
def build_persona_decision_summary(persona, policy):
    """整理 Agent 的长期倾向，不把 Persona 比例当作本轮情绪结论。"""
    emotion_profile = persona.get("emotion_expression", {})
    emotion_quantiles = policy.get("emotion_quantiles", {})
    emotion_names = ("positive", "neutral", "negative")
    emotion_summary = {}
    for emotion in emotion_names:
        field = f"{emotion}_rate"
        rate = float(emotion_profile.get(field, 0.0))
        emotion_summary[emotion] = {
            "rate": round(rate, 6),
            "level": get_level(rate, emotion_quantiles.get(field, {})),
        }

    orientation_profile = persona.get("information_orientation", {})
    orientation_quantiles = policy.get("orientation_quantiles", {})
    orientation_names = ("fact", "opinion", "questioning")
    orientation_summary = {}
    for orientation in orientation_names:
        field = f"{orientation}_rate"
        rate = float(orientation_profile.get(field, 0.0))
        orientation_summary[orientation] = {
            "rate": round(rate, 6),
            "level": get_level(rate, orientation_quantiles.get(field, {})),
        }

    return {
        "agent_id": persona.get("agent_id"),
        "topic_preference": persona.get("topic_preference", {}),
        # 2026/10/16，新增功能：向自主行为决策提供长期原创/
        # 转发偏好。该字段只影响行为方式，不直接决定情绪结论。
        "action_preference": persona.get("action_preference", {}),
        "emotion_expression_prior": {
            "meaning": "长期表达倾向，仅作弱先验，不代表本轮当前情绪",
            "details": emotion_summary,
        },
        "information_orientation": {
            "dominant": max(
                orientation_names,
                key=lambda name: orientation_summary[name]["rate"],
            ),
            "details": orientation_summary,
        },
        "comment_faction_preference": persona.get(
            "comment_faction_preference",
            {},
        ),
    }


# 2026/08/27 Agent情绪状态转换，新增功能：统一统计一组评论的情绪和立场分布。
def summarize_comment_group(comments):
    """返回一组评论的数量、情绪分布和立场分布。"""
    emotion_counts = {
        emotion: 0 for emotion in ("positive", "neutral", "negative")
    }
    stance_counts = {
        stance: 0
        for stance in ("support", "neutral", "questioning", "criticism")
    }
    for candidate in comments:
        emotion = candidate.get("emotion")
        stance = candidate.get("stance")
        if emotion in emotion_counts:
            emotion_counts[emotion] += 1
        if stance in stance_counts:
            stance_counts[stance] += 1
    return {
        "comment_count": len(comments),
        "emotion_counts": emotion_counts,
        "stance_counts": stance_counts,
    }


# 2026/08/28 第十七次联调修复-修复证据时间语义，新增功能：区分本轮新评论、历史转发和应急评论。
# 2026/9/5，社交网络传播，修改功能：邻居上一轮表达按本轮再次传播处理。
def classify_visible_comment_source(comment, current_step):
    """根据时间步和来源字段返回评论的证据类型。"""
    if (
        current_step is not None
        and comment.get("introduced_step") != current_step
    ):
        return "historical"

    source_type = comment.get("source_type")
    if source_type in {"repost_fallback", "neighbor_propagation"}:
        return "current_repost"
    if source_type == "local_emergency_fallback":
        return "current_emergency"
    return "current_generated"


# 2026/08/25 第六次联调问题修复，新增功能：汇总个人可见评论的情绪和立场分布。
# 2026/08/27 Agent情绪状态转换，修改功能：分开汇总当前轮评论与历史评论。
# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：按时间和来源形成四层评论摘要。
def summarize_visible_comments(candidates, current_step=None):
    """区分本轮模型评论、转发评论、应急评论和历史评论。"""
    comment_groups = {
        "current_generated": [],
        "current_repost": [],
        "current_emergency": [],
        "historical": [],
    }
    for candidate in candidates:
        source = classify_visible_comment_source(candidate, current_step)
        comment_groups[source].append(candidate)

    current_comments = (
        comment_groups["current_generated"]
        + comment_groups["current_repost"]
        + comment_groups["current_emergency"]
    )

    return {
        "visible_comment_count": len(candidates),
        "current_step": current_step,
        "current_step_comments": summarize_comment_group(current_comments),
        "current_generated_comments": summarize_comment_group(
            comment_groups["current_generated"]
        ),
        "current_repost_comments": summarize_comment_group(
            comment_groups["current_repost"]
        ),
        "current_emergency_comments": summarize_comment_group(
            comment_groups["current_emergency"]
        ),
        "historical_comments": summarize_comment_group(
            comment_groups["historical"]
        ),
    }


# 2026/08/25 第五次联调问题修复，新增功能：统一读取不同声明状态下的官方态度候选项。
def get_official_attitude_options(event_context, policy):
    """无声明时返回不适用，有声明时读取统一的三种态度选项。"""
    status = event_context.get("current_state", {}).get(
        "official_statement_status",
        "none",
    )
    if status == "none":
        return ["not_applicable"]

    rules = policy.get("candidate_rules", {}).get("official_statement", {})
    configured_options = rules.get(status, {}).get("default", [])
    valid_attitudes = {"accept", "wait", "question"}
    options = [
        attitude
        for attitude in configured_options
        if attitude in valid_attitudes
    ]
    return list(dict.fromkeys(options)) or ["accept", "wait", "question"]


def score_candidate(candidate, event_context, persona, current_emotion, faction):
    """计算候选评论与 Agent 当前决策状态的匹配分数。"""
    topic = event_context.get("event_labels", {}).get("topic")
    topic_match = 1.0 if candidate.get("topic") == topic else 0.0
    emotion_match = 1.0 if candidate.get("emotion") == current_emotion else 0.0
    faction_match = 1.0 if candidate.get("faction") == faction else 0.0
    orientation = candidate.get("orientation", "opinion")
    orientation_match = float(
        persona.get("information_orientation", {}).get(f"{orientation}_rate", 0.0)
    )
    return round(
        topic_match * 0.30
        + emotion_match * 0.30
        + faction_match * 0.30
        + orientation_match * 0.10,
        6,
    )


# 2026/08/25 第五次联调问题修复，新增功能：定义官方态度与评论立场的语义对应关系。
def get_attitude_stances(official_attitude):
    """返回一种官方态度优先对应的评论立场。"""
    return {
        "accept": ("support", "neutral"),
        "wait": ("neutral",),
        "question": ("questioning", "criticism"),
    }.get(official_attitude, ())


# 2026/08/25 第八次联调问题修复，新增功能：排除Agent已经发表过的评论编号和相同文本。
def filter_unseen_candidates(
    candidates,
    excluded_comment_ids=None,
    excluded_comment_texts=None,
):
    """返回当前Agent尚未发表过的候选评论，不影响其他Agent的选择。"""
    excluded_ids = {
        str(comment_id).strip()
        for comment_id in (excluded_comment_ids or ())
        if str(comment_id).strip()
    }
    excluded_texts = {
        "".join(str(text).split())
        for text in (excluded_comment_texts or ())
        if str(text).strip()
    }
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("comment_id", "")).strip() not in excluded_ids
        and "".join(str(candidate.get("text", "")).split())
        not in excluded_texts
    ]


# 2026/08/25 第六次联调问题修复，新增功能：从高分候选评论中进行按 Agent 区分的可复现选择。
def select_from_top_candidates(
    scored_candidates,
    event_id,
    step,
    agent_id,
    top_k,
    random_seed,
):
    """使用固定种子从评分最高的若干条评论中选择一条。"""
    if not scored_candidates:
        return None
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k 必须是正整数。")

    top_candidates = scored_candidates[: min(top_k, len(scored_candidates))]
    seed_text = f"{random_seed}:{event_id}:{step}:{agent_id}"
    seed_number = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    return random.Random(seed_number).choice(top_candidates)


# 2026/08/25 第五次联调问题修复，修改功能：优先选择与官方态度一致的评论并保留安全回退。
# 2026/08/25 第六次联调问题修复，修改功能：由固定最高分选择改为 Top K 可复现选择。
# 2026/08/25 第八次联调问题修复，修改功能：评分前硬排除当前Agent已经发表过的评论。
def select_best_candidate(
    candidates,
    event_context,
    persona,
    current_emotion,
    faction,
    official_attitude=None,
    top_k=1,
    random_seed=0,
    excluded_comment_ids=None,
    excluded_comment_texts=None,
):
    """从Agent未发表过的评论中完成态度筛选、评分和可复现选择。"""
    if not candidates:
        return None, []

    fresh_candidates = filter_unseen_candidates(
        candidates,
        excluded_comment_ids,
        excluded_comment_texts,
    )
    if not fresh_candidates:
        return None, []

    preferred_stances = get_attitude_stances(official_attitude)
    attitude_candidates = [
        candidate
        for candidate in fresh_candidates
        if candidate.get("stance") in preferred_stances
    ]
    candidate_pool = attitude_candidates or fresh_candidates
    scored = []
    for candidate in candidate_pool:
        scored.append(
            {
                "comment_id": candidate.get("comment_id"),
                "score": score_candidate(
                    candidate, event_context, persona, current_emotion, faction
                ),
                "text": candidate.get("text", ""),
            }
        )
    scored.sort(
        key=lambda item: (-item["score"], str(item.get("comment_id", "")))
    )
    selected_score = select_from_top_candidates(
        scored_candidates=scored,
        event_id=event_context.get("event_id"),
        step=event_context.get("current_state", {}).get("step"),
        agent_id=persona.get("agent_id"),
        top_k=top_k,
        random_seed=random_seed,
    )
    selected_id = selected_score["comment_id"]
    selected = next(
        item for item in candidate_pool if item.get("comment_id") == selected_id
    )
    return selected, scored



# 第二类决策：受约束的 LLM 决策
# build_agent_event_view()
# build_persona_decision_summary()
# summarize_visible_comments()
# build_allowed_choices()
# build_decision_prompt()
# validate_cognition_decision()
# build_final_decision()


# 2026/08/25 第五次联调问题修复，修改功能：正式决策复用统一官方态度选项并标记声明状态。
# 2026/08/25 第六次联调问题修复，修改功能：向正式决策提供 Persona 和可见评论结构化摘要。
# 2026/08/27 Agent情绪状态转换，修改功能：加入当前轮证据优先和情绪转换依据约束。
# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：约束不同时间和来源证据的用途。
# 2026/10/14 基准机制恢复，修改功能：历史路径先生成稳定画像，再按
# Persona门槛、上一轮状态和新增证据约束情绪及官方态度候选。
def build_allowed_choices(
    event_context,
    policy,
    candidates,
    persona,
    previous_state=None,
    state_only=False,
):
    """根据事件状态生成认知决策必须遵守的枚举选项和硬约束。"""
    base_emotion_options = get_emotion_options(event_context, policy)
    evidence_based = uses_evidence_based_emotions(event_context)
    strategy_behavior = uses_strategy_participation_gate(event_context)
    # 2026/10/17，恢复功能：回应方案的内部状态恢复为
    # 2026/10/15批次使用的受约束LLM逐轮判断。自主行为
    # 仍由strategy_behavior单独开启，不再隐式启用本地状态裁决。
    personalized_guard = evidence_based
    generated_expression = uses_agent_generated_expression(event_context)
    current_evidence = collect_current_evidence(event_context, candidates)
    status = event_context.get("current_state", {}).get(
        "official_statement_status",
        "none",
    )
    base_attitude_options = get_official_attitude_options(
        event_context,
        policy,
    )
    decision_profile = None
    decision_guard = None
    if personalized_guard:
        decision_profile = build_persona_decision_profile(
            persona,
            policy,
            event_context,
        )
        current_evidence = appraise_evidence_for_persona(
            current_evidence,
            persona,
            event_context,
            previous_state,
            decision_profile,
        )
        decision_guard = build_personalized_decision_guard(
            current_evidence,
            decision_profile,
            previous_state,
            base_emotion_options,
            base_attitude_options,
            status,
        )
        emotion_options = decision_guard["emotion_options"]
        attitude_options = decision_guard["official_attitude_options"]
    else:
        emotion_options = base_emotion_options
        attitude_options = base_attitude_options
    strategy_state_guard = None
    if strategy_behavior and not evidence_based and state_only:
        # 2026/10/18，新增功能：回应方案实验不再把全部邻居文本近似
        # 等权交给LLM。Persona转换约束只决定内部状态候选，不参与
        # 后续沉默、原创和转发行为，因此两段职责仍保持分离。
        strategy_state_guard = build_strategy_state_guard(
            persona=persona,
            policy=policy,
            event_context=event_context,
            previous_state=previous_state,
            current_evidence=current_evidence,
            # 2026/10/18，修改功能：回应方案中的current_emotion表示
            # Agent综合心理反应，而不是对负面事件行为本身的价值赞同。
            # 因此开放三分类；相邻状态约束仍阻止正负直接跨级跳变。
            base_emotion_options=list(ALL_EMOTIONS),
            base_attitude_options=base_attitude_options,
        )
        emotion_options = strategy_state_guard["emotion_options"]
        attitude_options = strategy_state_guard[
            "official_attitude_options"
        ]
    positive_evidence_ids = [
        item["evidence_id"]
        for item in current_evidence
        if item.get("positive_eligible") is True
    ]
    transition_evidence = build_transition_evidence_sets(current_evidence)
    strong_evidence_ids = [
        item["evidence_id"]
        for item in current_evidence
        if item.get("is_new_this_step") is True
        and item.get("evidence_strength") == "strong"
    ]
    official_attitude_evidence_ids = [
        item["evidence_id"]
        for item in current_evidence
        if (
            item.get("evidence_type")
            in {
                "official_statement",
                "official_statement_unit",
                "historical_verified_update",
                "objective_event",
                "historical_public_discourse",
            }
            or item.get("evidence_target")
            in {
                "official_response",
                "investigation_process",
                "process_accountability",
                "fact_clarification",
            }
        )
    ]
    emotion_target_options = sorted(EMOTION_TARGETS)
    faction_options = list(FACTIONS)
    forbidden_factions = []

    hard_rules = [
        "所有枚举字段必须从允许选项中选择",
        "will_comment 为 false 时，comment_faction 必须为 null",
        "will_comment 为 true 时，必须选择有效的评论派系",
        "个人可见评论用于形成认知；启用自主表达时可选择沉默、原创或转发",
        "没有官方声明时 official_attitude 必须为 not_applicable",
        "存在官方声明时必须根据声明原文选择 accept、wait 或 question",
        "官方态度和个人情绪分别判断，accept不强制为neutral，question不强制为negative",
        "只有is_new为true的官方声明才是本轮新增声明，持续声明只能作为仍然有效的背景信息",
        "current_generated_comments表示本轮新舆情，current_repost_comments只表示旧观点再次传播",
        "current_emergency_comments只用于数量保障，不能作为改变情绪的主要证据",
        "不得仅根据 gender 或 location 推断行为",
        "是否公开发言不得由情绪极性直接决定；positive、neutral、negative使用相同的新颖性、相关性、重复和疲劳标准",
    ]
    if evidence_based:
        evidence_rules = [
            "当轮公众语境、官方声明和模拟评论是本轮可用证据",
            "情绪必须指向具体对象，并至少引用一个本轮可用证据编号",
            "negative事件中的positive只能表示希望、宽慰、互助支持、事实澄清认可或对改进行动的支持",
            "不得把对悲剧后果、伤害或死亡本身的赞同标记为positive",
            "official_statement_status为clear只表示信息状态，不等于所有Agent都必须accept",
            "接受官方结论不等于悲剧后果、搜寻疏漏或持续公共问题已经消失",
        ]
        evidence_rules.append(
            "选择positive时，必须引用positive_evidence_ids中的至少一个编号"
        )
        hard_rules.extend(evidence_rules)

    choices = {
        "emotion_options": emotion_options,
        "official_attitude_options": attitude_options,
        "official_statement_status": status,
        "faction_options": faction_options,
        "visible_comment_ids": [item.get("comment_id") for item in candidates],
        "forbidden_factions": forbidden_factions,
        "hard_rules": hard_rules,
        "persona_fields_used": [
            "topic_preference",
            "action_preference",
            "information_orientation",
            "emotion_expression",
            "comment_faction_preference",
        ],
        "persona_decision_summary": build_persona_decision_summary(
            persona,
            policy,
        ),
        "visible_comment_summary": summarize_visible_comments(
            candidates,
            event_context.get("current_state", {}).get("step"),
        ),
        "previous_state": {
            "current_emotion": (previous_state or {}).get(
                "current_emotion"
            ),
            "official_attitude": (previous_state or {}).get(
                "official_attitude"
            ),
            "claim_position": (previous_state or {}).get("claim_position"),
            "process_evaluation": (previous_state or {}).get(
                "process_evaluation"
            ),
        },
    }
    if (
        generated_expression
        and not evidence_based
        and strategy_behavior
        and not state_only
    ):
        # 2026/10/16，新增功能：策略对照不再把候选评论当作
        # Agent 最终发言。个人可见评论与当前官方信息只是表达
        # 依据；可用证据编号在此集中一次性给出，由校验层统一守边界。
        expression_evidence_ids = list(
            dict.fromkeys(
                [
                    str(item.get("comment_id"))
                    for item in candidates
                    if item.get("comment_id")
                ]
                + [
                    str(item.get("evidence_id"))
                    for item in current_evidence
                    if item.get("evidence_id")
                ]
            )
        )
        choices.update(
            {
                "behavior_action_options": (
                    ["silent", "original", "reshare"]
                    if allows_reshare_action(event_context)
                    else ["silent", "original"]
                ),
                "expression_emotion_options": base_emotion_options,
                "expression_stance_options": list(EXPRESSION_STANCES),
                "_visible_comment_texts": [
                    str(item.get("text", "")).strip()
                    for item in candidates
                    if str(item.get("text", "")).strip()
                ],
                # 2026/10/16，修改功能：保留文本与评论编号的内部映射。
                # 该字段不进入提示词，仅用于记录原创表达与个人可见评论
                # 的相似度；相同措辞不再改变Agent明确选择的动作。
                "_visible_comment_entries": [
                    {
                        "comment_id": item.get("comment_id"),
                        "text": str(item.get("text", "")).strip(),
                        "faction": item.get("faction"),
                    }
                    for item in candidates
                    if item.get("comment_id")
                    and str(item.get("text", "")).strip()
                ],
                "expression_evidence_ids_allowed": expression_evidence_ids,
                "positive_evidence_ids": positive_evidence_ids,
            }
        )
    if state_only and strategy_behavior and not evidence_based:
        # 2026/10/17，修改功能：回应方案的状态判断与公开行为彻底拆分。
        # 状态请求不再向LLM暴露动作偏好、发言字段或表达字段，避免模型
        # 先产生“想发言”的负面文本，再反向影响情绪和官方态度判断。
        choices["decision_phase"] = "strategy_state"
        choices["persona_fields_used"] = [
            field
            for field in choices["persona_fields_used"]
            if field
            not in {
                "action_preference",
                "comment_faction_preference",
            }
        ]
        choices["persona_decision_summary"] = dict(
            choices["persona_decision_summary"]
        )
        choices["persona_decision_summary"].pop("action_preference", None)
        choices["persona_decision_summary"].pop(
            "comment_faction_preference",
            None,
        )
        behavior_rule_markers = (
            "will_comment",
            "评论派系",
            "自主表达",
            "是否公开发言",
        )
        choices["hard_rules"] = [
            rule
            for rule in choices["hard_rules"]
            if not any(marker in rule for marker in behavior_rule_markers)
        ]
        choices.update(
            {
                "strategy_state_guard": build_strategy_state_prompt_guard(
                    strategy_state_guard
                ),
                # 以下完整守卫只供本地校验和结果审计。前导下划线确保
                # build_strategy_state_prompt不会把规则层推荐结论泄露
                # 给LLM，避免合法候选再次同步收敛到同一预判值。
                "_strategy_state_guard_audit": strategy_state_guard,
                "persona_decision_profile": strategy_state_guard[
                    "persona_profile"
                ],
                "state_evidence_catalog": strategy_state_guard[
                    "state_evidence_catalog"
                ],
            }
        )
        choices.pop("positive_evidence_ids", None)
    if evidence_based:
        choices.update(
            {
                "emotion_choice_mode": "evidence_based_all",
                "base_emotion_options": base_emotion_options,
                "base_official_attitude_options": base_attitude_options,
                "emotion_target_options": emotion_target_options,
                "persona_factor_options": list(PERSONA_FACTOR_OPTIONS),
                "persona_decision_profile": decision_profile,
                "decision_guard": decision_guard,
                "emotion_resolution": decision_guard[
                    "emotion_resolution"
                ],
                "official_attitude_resolution": decision_guard[
                    "official_attitude_resolution"
                ],
                "available_emotion_evidence": current_evidence,
                "positive_evidence_ids": positive_evidence_ids,
                "official_attitude_evidence_ids_allowed": (
                    official_attitude_evidence_ids
                ),
                **transition_evidence,
                "strong_evidence_ids": strong_evidence_ids,
                # 内部状态受迟滞候选约束；公开表达可以与内部情绪不同，
                # 因而继续使用历史模式的完整基础情绪空间。
                "expression_emotion_options": base_emotion_options,
                "expression_stance_options": list(EXPRESSION_STANCES),
                "_visible_comment_texts": [
                    str(item.get("text", "")).strip()
                    for item in candidates
                    if str(item.get("text", "")).strip()
                ],
            }
        )
    return choices


# 2026/08/25 第五次联调问题修复，修改功能：明确官方态度语义并要求依据本轮证据重新判断。
# 2026/08/25 第六次联调问题修复，修改功能：隔离预设情绪标签并明确现有 Persona 字段的判断用途。
# 2026/08/25 Agent个人评论历史，修改功能：明确使用Agent此前全部评论辅助本轮判断。
# 2026/08/27 Agent情绪状态转换，修改功能：明确证据优先级并区分上一轮状态与本轮判断。
# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：明确新声明、新评论和历史转发的不同证据强度。
# 2026/10/10 Persona差异化决策，修改功能：以上一轮状态为基线，
# 由Persona决定证据关注方式和改变门槛，再由本轮新增证据触发状态变化。
def build_decision_prompt(event_context, choices, candidates, previous_state, history_summary):
    """构造只使用个人可见评论的 Agent 认知决策提示词。"""
    if choices.get("decision_phase") == "strategy_state":
        return build_strategy_state_prompt(
            event_context,
            choices,
            candidates,
            previous_state,
            history_summary,
        )
    agent_event_view = build_agent_event_view(event_context)
    prompt_choices = {
        key: value for key, value in choices.items() if not key.startswith("_")
    }
    # 2026/08/27 Agent情绪状态转换，修改功能：将旧状态字段改名为上一轮状态，避免被误当作本轮结论。
    previous_state_view = {
        "previous_emotion": previous_state.get("current_emotion"),
        "previous_official_attitude": previous_state.get(
            "official_attitude"
        ),
        "previous_claim_position": previous_state.get("claim_position"),
        "previous_process_evaluation": previous_state.get(
            "process_evaluation"
        ),
        "previous_will_comment": previous_state.get("will_comment", False),
        "previous_action": previous_state.get("last_action", "none"),
        "previous_comment_faction": previous_state.get(
            "last_comment_faction"
        ),
        "previous_comment_id": previous_state.get("last_comment_id"),
    }
    output_format = {
        "current_emotion": "从 emotion_options 中选择",
        "official_attitude": "从 official_attitude_options 中选择",
        "will_comment": "true or false",
        "comment_faction": "五个派系之一，或 null",
        "decision_reason": {
            "emotion": "一句话说明情绪依据",
            "official_attitude": "一句话说明官方态度依据",
            "comment": "一句话说明是否评论及派系依据",
        },
    }
    generated_expression = bool(choices.get("behavior_action_options"))
    if generated_expression:
        # 2026/10/16，新增功能：一次认知请求同时返回最小社交
        # 动作和原创表达，不为生成评论增加第二次 LLM 调用。
        output_format.update(
            {
                "action_type": "从 behavior_action_options 中选择",
                "reshare_comment_id": (
                    "转发时从 visible_comment_ids 中选择，"
                    "否则为null"
                ),
                "expression": {
                    "text": "原创时生成不超过280字的个人表达，否则为null",
                    "emotion": "从 expression_emotion_options 中选择",
                    "stance": "从 expression_stance_options 中选择",
                    "evidence_ids": "仅引用 expression_evidence_ids_allowed",
                },
            }
        )
    if choices.get("emotion_choice_mode") == "evidence_based_all":
        output_format.update(
            {
                "emotion_target": "从 emotion_target_options 中选择",
                "emotion_evidence_ids": "至少一个 available_emotion_evidence 中的编号",
                "persona_factors": (
                    "至少一个 persona_factor_options 中的长期倾向编号"
                ),
                "official_attitude_evidence_ids": (
                    "存在官方声明时至少一个可用证据编号；无声明时为空数组"
                ),
                "expression": {
                    "text": "决定评论时生成不超过280字的原创表达，否则为null",
                    "emotion": "从 expression_emotion_options 中选择；可与内部情绪不同",
                    "stance": "从 expression_stance_options 中选择",
                    "evidence_ids": "表达实际依据的个人可用证据编号",
                },
            }
        )

    has_previous_state = bool(previous_state_view["previous_emotion"])
    if has_previous_state:
        state_baseline_instruction = (
            "上一轮状态是本轮默认基线。只有出现相较上一轮新增、变化或仍然"
            "有效且足以支持改变的具体证据时，才改变情绪或官方态度；"
            "证据不足时保持原状态。"
        )
    else:
        state_baseline_instruction = (
            "这是该Agent的首次判断，没有上一轮状态可继承。应由Persona决定"
            "关注哪些证据，再根据当前事件、声明和个人可见评论形成初始状态。"
        )

    evidence_based_instructions = ""
    if choices.get("emotion_choice_mode") == "evidence_based_all":
        evidence_based_instructions = """
10. evidence_based_all 模式允许三种情绪，但不是要求平均分布。positive 只能表示对搜寻、互助、事实澄清、公开回应或社会改进的希望、宽慰或认可，不能表示对负面事件后果本身的赞同。
11. 必须填写 emotion_target 和 emotion_evidence_ids；证据编号只能来自 available_emotion_evidence。选择positive时，至少引用一个positive_evidence_ids中的编号。
12. 必须填写 official_attitude_evidence_ids。官方态度只能依据当前可用证据独立判断，不能根据 current_emotion 反推；有声明时优先引用 official_attitude_resolution.supporting_evidence_ids，无声明时该数组必须为空。
13. decision_guard 已根据Persona个体门槛和本轮证据完成后续轮次的情绪裁决；emotion_resolution.selected_emotion非空时，emotion_options是唯一合法内部情绪。official_attitude_resolution 已完成事实接受与过程评价的个体裁决，official_attitude_options 是唯一合法官方态度。不得用群体意见、上一轮措辞习惯或自行偏好覆盖这些裁决。
14. will_comment只能根据本轮证据相关性、观点新颖性、个人行动偏好和连续发言疲劳判断；不得因为current_emotion是neutral就倾向沉默，也不得因为是negative就倾向发言。
15. 情绪或官方态度改变时必须引用本轮新增证据；一个普通证据不足以改变状态，需要两个独立普通新增证据，或一个对当前Persona个体充分的证据。
16. persona_factors必须记录本轮实际使用的长期倾向，不能只写笼统性格描述。
17. public_context中的已核实事实是公共广播；individual_public_context是该Agent本轮实际接触的讨论语境。不得引用未来阶段信息、未曝光语境或把公众语境理解为预设情绪结论。
18. will_comment=true时，expression必须是该Agent基于Persona、上一轮状态和个人证据形成的公开表达；现实中不同个体可能形成相同或相近措辞，因此允许与个人可见评论文本一致，但仍须给出本人的证据和表达动机。will_comment=false时expression必须为null。
19. expression.evidence_ids只能引用available_emotion_evidence；不得虚构证据中没有的时间、人物、因果或调查结论。质疑官方不等于负面情绪，接受官方也不等于积极情绪。
20. persona_decision_profile是由长期Persona稳定推导的个体参数。情绪和官方态度分别使用独立变化门槛，均不是群体配额。官方态度由规则层裁决，LLM只负责给出与该裁决一致的解释和原创表达。
20. 同一官方通告的不同片段拥有共同evidence_group_id，只代表一个事实来源。应优先引用当前Persona真正关注的片段，不能把多个片段重复计算成多条独立证据。
""".strip()


    autonomous_behavior_instructions = ""
    if generated_expression and choices.get("emotion_choice_mode") != "evidence_based_all":
        autonomous_behavior_instructions = """
10. action_type必须是个人的公开行为选择：silent表示不发言，original表示发布自己的话，reshare表示转发一条个人可见评论。
11. action_type=silent时will_comment必须为false，expression和reshare_comment_id必须为null；其他动作时will_comment必须为true。
12. action_type=original时必须给出expression；现实中不同个体可能形成相同或相近措辞，因此允许expression与可见评论文本一致。其evidence_ids只能引用expression_evidence_ids_allowed。只有Agent明确选择reshare时才按转发处理，不能仅凭文本相同擅自改写动作。
13. action_type=reshare时必须从visible_comment_ids中选择reshare_comment_id，expression必须为null。是否原创或转发应参考Persona的action_preference和当轮信息是否值得表达。
14. 即使有个人可见评论，也可因缺少新信息、与个人关注无关、观点重复或连续发言而保持沉默。
15. 情绪状态、官方态度和公开动作是三个不同问题；负面不等于必须发言，接受通告也不等于积极。
""".strip()
    return f"""
你是社会舆情模拟系统中的一个 Agent 决策器。
请根据事件、当前状态、Persona、个人可见评论和个人历史，从允许选项中做出本轮决策。

【事件】
{json.dumps(agent_event_view, ensure_ascii=False, indent=2)}

【Agent 上一轮状态】
{json.dumps(previous_state_view, ensure_ascii=False, indent=2)}

【Agent 历史摘要（含个人评论历史）】
{json.dumps(history_summary, ensure_ascii=False, indent=2)}

【允许选项和硬约束】
{json.dumps(prompt_choices, ensure_ascii=False, indent=2)}

【Agent 内部状态证据视图】
{json.dumps(candidates, ensure_ascii=False, indent=2)}

【判断说明】
1. {state_baseline_instruction}
2. Persona主导决策方式而不预设结论：fact取向重点检查可验证事实，opinion取向重点判断责任和处理态度，questioning取向重点检查遗漏、矛盾和模糊信息；emotion_expression_prior影响状态惯性和表达方式，但不直接指定本轮情绪。
3. 先从Persona摘要确定该Agent最重视的证据类型，再检查本轮首次发布的声明、本轮新评论和公众语境是否提供了与该取向相关的新证据。群体多数意见、事件标签或official_statement_status=clear都不能单独成为状态变化的充分理由。
4. 维持状态时，理由必须指出当前仍然有效的证据；改变状态时，理由必须同时说明相较上一轮新增或变化的证据，以及该证据为何会影响当前Persona。不得只复用历史状态、Persona倾向或个人旧评论作为结论；没有强证据时不得在positive和negative之间直接跨级变化。
5. 官方态度与事件情绪分别判断。accept不强制为neutral或positive，question不强制为negative；接受事实结论后，仍可因事件后果、处置过程或未解决问题保持negative。
6. accept表示总体认可当前声明的可信度和回应价值，wait表示当前证据不足，question表示主要质疑真实性、完整性或处理方式。not_applicable只用于没有官方声明；incomplete只表示信息尚不完整。声明持续有效不等于每轮重新发布。
7. own_comment_history和seen_comment_ids只代表该Agent的有界事件记忆：已见编号再次出现不能冒充新信息。只有“Agent个人可见评论”中的评论才是该Agent本轮收到的社交曝光；不可使用其他Agent未曝光给它的评论。个人可见评论中的多数意见只代表局部舆论环境，不能单独覆盖Persona差异和上一轮状态；历史转发只说明旧观点仍有热度，应急评论只用于数量保障。
8. 是否评论及评论派系应结合topic_preference、comment_faction_preference、此前行动、历史表达和本轮信息新颖性判断；没有新的合适表达时可以保持沉默，不得为了参与而机械重复旧评论。
9. decision_reason必须体现本轮具体证据和适用的Persona特征。不得以事件标签、策略名称或“多数人如此”直接得出结论，也不得预设任何官方内容策略必然更好。
{evidence_based_instructions}
{autonomous_behavior_instructions}

个人可见评论用于判断当前舆论环境；只有action_type=reshare时才记录为转发。original允许产生与可见评论相同或相近的措辞，但仍须引用本人的可用证据。
只返回一个 JSON 对象，不输出 Markdown 或概率。
JSON 字段格式：
{json.dumps(output_format, ensure_ascii=False, indent=2)}
""".strip()


# 2026/10/17，新增功能：策略实验使用独立的状态判断提示词。
def build_strategy_state_prompt(
    event_context,
    choices,
    candidates,
    previous_state,
    history_summary,
):
    """只判断内部情绪和官方态度，不询问是否发言或如何表达。"""

    prompt_choices = {
        key: value
        for key, value in choices.items()
        if not key.startswith("_")
    }
    previous_state_view = {
        "previous_emotion": previous_state.get("current_emotion"),
        "previous_official_attitude": previous_state.get(
            "official_attitude"
        ),
    }
    output_format = {
        "current_emotion": "从 emotion_options 中选择",
        "official_attitude": "从 official_attitude_options 中选择",
        "decision_reason": {
            "emotion": "一句话说明情绪依据",
            "official_attitude": "一句话说明官方态度依据",
        },
    }
    return f"""
你是社会舆情模拟系统中的 Agent 状态判断器。
本次只判断内部情绪和对官方信息的态度，不决定是否发言、发言动作、派系或表达文本。

【事件】
{json.dumps(build_agent_event_view(event_context), ensure_ascii=False, indent=2)}

【Agent 上一轮状态】
{json.dumps(previous_state_view, ensure_ascii=False, indent=2)}

【Agent 有界历史摘要】
{json.dumps(history_summary, ensure_ascii=False, indent=2)}

【允许选项和硬约束】
{json.dumps(prompt_choices, ensure_ascii=False, indent=2)}

【Agent 个人可见评论】
{json.dumps(candidates, ensure_ascii=False, indent=2)}

【判断规则】
1. Persona是长期关注和理解倾向，不是预设结论；上一轮状态是默认基线。
2. 只有当前事件、当前有效官方信息和个人实际可见评论可以作为本轮判断依据。
3. 没有足以改变判断的新信息时优先保持原状态；不得以多数意见直接覆盖个体差异。
4. 情绪与官方态度分别判断：接受官方信息不等于积极，质疑官方也不等于负面。
5. positive、neutral、negative的选择只描述Agent内部反应；不得推断该Agent一定会发言。
6. decision_reason只解释状态判断，不能包含发言意愿、动作或预先生成的评论。
7. 邻居表达只是弱社会信号，不是已核实事实；不得按邻居数量进行多数表决。
8. 顶层emotion_options与official_attitude_options已经过规则层约束，必须从中选择。第一轮仍由你完成语义初始化；后续轮次的唯一emotion_options已由Persona先验、上一轮惯性和方向性证据效用裁决，你只负责解释，不得另行改写。
9. 没有反对评论不等于接受官方结论；通告未更新且没有新关切时，应保持上一轮官方态度。
10. positive表示对事实澄清、救助行动、依法处置或社会改进产生希望、宽慰或认可，不表示赞同事件中的伤害行为。评论数量本身不是转向依据，同一传播根的重复内容不得重复加权。

只返回一个JSON对象，不输出Markdown或概率。
JSON字段格式：
{json.dumps(output_format, ensure_ascii=False, indent=2)}
""".strip()


# 2026/08/21 新增功能：校验只基于个人可见评论产生的认知决策。
# 2026/08/25 第五次联调问题修复，修改功能：校验官方态度适用性和三项非空决策理由。
def _normalize_decision_id_list(value, field_name, available_ids):
    """规范化决策引用编号，并拒绝个人不可见或不存在的证据。"""

    if not isinstance(value, list):
        raise ValueError(f"{field_name} 必须是数组。")
    normalized = []
    for raw_id in value:
        evidence_id = str(raw_id).strip()
        if evidence_id and evidence_id not in normalized:
            normalized.append(evidence_id)
    if not set(normalized).issubset(available_ids):
        raise ValueError(f"{field_name} 包含不可用的证据编号。")
    return normalized


def _record_output_normalization(decision, code):
    """记录无语义损失的LLM格式修复，避免容错行为不可审计。"""

    records = decision.get("output_normalizations")
    if not isinstance(records, list):
        records = []
        decision["output_normalizations"] = records
    if code not in records:
        records.append(code)


def _normalize_expression_text(text):
    """规范化表达文本，仅用于记录与个人可见评论的相似度。"""

    return "".join(str(text or "").split())


def _find_visible_expression_match(text, choices):
    """返回最接近的可见评论及相似度；不据此否决公开表达。"""

    normalized_text = _normalize_expression_text(text)
    if not normalized_text:
        return None, 0.0

    best_entry = None
    best_ratio = 0.0
    entries = choices.get("_visible_comment_entries", [])
    if not entries:
        entries = [
            {"comment_id": None, "text": visible_text, "faction": None}
            for visible_text in choices.get("_visible_comment_texts", [])
        ]
    for entry in entries:
        visible_text = _normalize_expression_text(entry.get("text"))
        if not visible_text:
            continue
        if normalized_text == visible_text:
            return entry, 1.0
        # 短句的少量重合很常见，不以模糊相似度阻止正常原创。
        if min(len(normalized_text), len(visible_text)) < 12:
            continue
        ratio = SequenceMatcher(
            None,
            normalized_text,
            visible_text,
            autojunk=False,
        ).ratio()
        if ratio > best_ratio:
            best_entry = entry
            best_ratio = ratio
    return best_entry, best_ratio


def _validate_state_transition(decision, choices):
    """校验历史状态变化使用了合法的本轮新增证据。

    2026/10/14，修改功能：v3 主流程接受情绪与官方态度专用规则模块
    已经完成的个体裁决，并核对裁决结果与支持证据。旧调用方未提供规则裁决时，
    仍回退到“一个个体充分证据，或两个独立普通新增证据”的兼容校验；
    非相邻情绪跳转还必须引用允许完整重判的强证据。
    """

    previous_state = choices.get("previous_state", {})
    previous_emotion = previous_state.get("current_emotion")
    current_emotion = decision.get("current_emotion")
    emotion_evidence = set(decision.get("emotion_evidence_ids", []))
    change_evidence = set(choices.get("state_change_evidence_ids", []))
    evidence_group_by_id = choices.get("evidence_group_by_id", {})

    def distinct_evidence_group_count(evidence_ids):
        """同一事实的通告与摘要只能计为一组独立依据。"""

        return len(
            {
                str(evidence_group_by_id.get(evidence_id, evidence_id))
                for evidence_id in evidence_ids
            }
        )
    if (
        previous_emotion in EMOTION_LEVELS
        and current_emotion != previous_emotion
    ):
        emotion_resolution = choices.get("emotion_resolution", {})
        if isinstance(emotion_resolution, dict) and emotion_resolution.get(
            "selected_emotion"
        ):
            # 2026/10/14，修改功能：情绪变化已由个体效用边际裁决。
            # 深层校验确认结果及其新增证据被记录，不再用旧的“两条普通
            # 证据”规则二次否决已通过Persona门槛的确定性变化。
            supporting_ids = set(
                emotion_resolution.get("supporting_evidence_ids", [])
            )
            if current_emotion != emotion_resolution.get(
                "selected_emotion"
            ):
                raise ValueError("情绪与个体规则裁决不一致。")
            if not supporting_ids.intersection(emotion_evidence):
                raise ValueError("情绪变化必须记录规则裁决使用的新增证据。")
        else:
            matched_change_evidence = emotion_evidence.intersection(
                change_evidence
            )
            if not matched_change_evidence:
                raise ValueError("情绪变化必须引用本轮新增证据。")
            emotion_single_evidence = set(
                choices.get("emotion_single_change_evidence_ids", [])
            )
            matched_single_evidence = emotion_evidence.intersection(
                emotion_single_evidence
            )
            if (
                not matched_single_evidence
                and distinct_evidence_group_count(matched_change_evidence) < 2
            ):
                raise ValueError(
                    "一个普通证据不足以改变情绪；需要两个相互独立的普通新增"
                    "证据，或一个对当前Persona个体充分的证据。"
                )
            if abs(
                EMOTION_LEVELS[current_emotion]
                - EMOTION_LEVELS[previous_emotion]
            ) > 1:
                full_evidence = set(
                    choices.get("emotion_full_reassessment_evidence_ids", [])
                )
                if not emotion_evidence.intersection(full_evidence):
                    raise ValueError("非相邻情绪变化必须引用个体充分的强证据。")

    previous_attitude = previous_state.get("official_attitude")
    current_attitude = decision.get("official_attitude")
    attitude_evidence = set(
        decision.get("official_attitude_evidence_ids", [])
    )
    attitude_single_evidence = set(
        choices.get("official_attitude_single_change_evidence_ids", [])
    )
    if (
        previous_attitude in {"accept", "wait", "question"}
        and current_attitude != previous_attitude
    ):
        matched_change_evidence = attitude_evidence.intersection(
            change_evidence
        )
        attitude_resolution = choices.get("official_attitude_resolution", {})
        if isinstance(attitude_resolution, dict) and attitude_resolution:
            # 2026/10/14，修改功能：官方态度已由个体规则最终裁决，深层
            # 校验只确认裁决使用的本轮证据被记录；不再用旧的候选式规则
            # 二次否决已经通过Persona门槛的确定性结果。
            supporting_ids = set(
                attitude_resolution.get("supporting_evidence_ids", [])
            )
            if current_attitude != attitude_resolution.get(
                "official_attitude"
            ):
                raise ValueError("官方态度与个体规则裁决不一致。")
            if not supporting_ids.intersection(attitude_evidence):
                raise ValueError("官方态度变化必须记录规则裁决使用的新增证据。")
            return
        matched_single_evidence = attitude_evidence.intersection(
            attitude_single_evidence
        )
        if not matched_change_evidence:
            raise ValueError("官方态度变化必须引用本轮新增证据。")
        if (
            not matched_single_evidence
            and distinct_evidence_group_count(matched_change_evidence) < 2
        ):
            raise ValueError(
                "一个普通证据不足以改变官方态度；需要两个相互独立的普通新增"
                "证据，或一个对当前Persona个体充分的证据。"
            )


def _validate_generated_expression(decision, choices, available_ids):
    """校验一次决策调用内生成的 Agent 原创表达。"""

    # 2026/10/13，LLM输出容错：不发言是权威行为选择。模型即使额外
    # 返回了草稿表达，也不会进入评论池，因此直接丢弃，无需为无效文本
    # 重试整个Agent。决定发言时仍保持全部严格校验。
    if decision["will_comment"] is False:
        if "expression" not in decision:
            _record_output_normalization(
                decision,
                "filled_null_expression_for_silence",
            )
        elif decision.get("expression") is not None:
            _record_output_normalization(
                decision,
                "discarded_expression_for_silence",
            )
        decision["expression"] = None
        return
    if "expression" not in decision:
        raise ValueError("will_comment为true时缺少expression字段。")
    expression = decision.get("expression")
    if not isinstance(expression, dict):
        raise ValueError("will_comment为true时expression必须是JSON对象。")

    text = expression.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("expression.text必须是非空文本。")
    text = text.strip()
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"expression.text不能超过{MAX_EXPRESSION_LENGTH}个字符。"
        )
    matched_entry, similarity = _find_visible_expression_match(text, choices)
    if similarity >= 0.92:
        # 2026/10/16，修改功能：现实中的独立表达可能与公共评论使用
        # 相同或相近措辞。文本相似不再否决决策，也不擅自把 original
        # 改写为 reshare；仅保存审计信息，供后续分析重复表达和趋同传播。
        decision["expression_similarity_audit"] = {
            "matched_visible_comment_id": (
                matched_entry.get("comment_id")
                if isinstance(matched_entry, dict)
                else None
            ),
            "similarity": round(float(similarity), 6),
            "match_type": "exact" if similarity >= 1.0 else "near",
            "accepted": True,
        }
    if expression.get("emotion") not in choices.get(
        "expression_emotion_options",
        choices["emotion_options"],
    ):
        raise ValueError("expression.emotion不在允许选项中。")
    if expression.get("stance") not in choices["expression_stance_options"]:
        raise ValueError("expression.stance不在允许选项中。")
    evidence_ids = _normalize_decision_id_list(
        expression.get("evidence_ids"),
        "expression.evidence_ids",
        available_ids,
    )
    if not evidence_ids:
        raise ValueError("expression.evidence_ids必须是非空数组。")
    if (
        expression["emotion"] == "positive"
        and "positive_evidence_ids" in choices
        and not set(evidence_ids).intersection(
            choices.get("positive_evidence_ids", [])
        )
    ):
        raise ValueError("positive表达必须引用正面语义证据。")
    expression["text"] = text
    expression["evidence_ids"] = evidence_ids


# 2026/10/16，新增功能：统一校验策略对照的沉默、原创和转发。
# 动作合法性与情绪/态度校验分离，后续扩展行为时不会改写证据规则。
def _validate_autonomous_behavior(decision, choices):
    """校验自主动作与发言字段之间的一致性。"""

    action_type = decision.get("action_type")
    allowed_actions = choices.get("behavior_action_options", [])
    if action_type not in allowed_actions:
        raise ValueError("action_type不在允许的行为选项中。")

    should_comment = action_type in {"original", "reshare"}
    if decision.get("will_comment") is not should_comment:
        raise ValueError("will_comment必须与action_type保持一致。")

    if action_type == "silent":
        decision["expression"] = None
        decision["reshare_comment_id"] = None
        return

    if action_type == "original":
        if decision.get("reshare_comment_id") is not None:
            raise ValueError("original动作的reshare_comment_id必须为null。")
        _validate_generated_expression(
            decision,
            choices,
            set(choices.get("expression_evidence_ids_allowed", [])),
        )
        return

    if decision.get("expression") is not None:
        raise ValueError("reshare动作的expression必须为null。")
    reshare_comment_id = decision.get("reshare_comment_id")
    if reshare_comment_id not in choices.get("visible_comment_ids", []):
        raise ValueError("reshare_comment_id必须属于个人可见评论。")


def _validate_decision_shape(decision, choices):
    """校验 LLM 决策的基础结构和枚举字段。"""

    if not isinstance(decision, dict):
        raise ValueError("LLM 决策结果必须是JSON对象。")

    required_fields = [
        "current_emotion",
        "official_attitude",
        "will_comment",
        "decision_reason",
    ]
    for field in required_fields:
        if field not in decision:
            raise ValueError(f"LLM 输出缺少字段：{field}")
    if decision["current_emotion"] not in choices["emotion_options"]:
        raise ValueError("current_emotion 不在允许选项中。")
    if decision["official_attitude"] not in choices["official_attitude_options"]:
        raise ValueError("official_attitude 不在允许选项中。")
    if not isinstance(decision["will_comment"], bool):
        raise ValueError("will_comment 必须是布尔值。")
    if "comment_faction" not in decision:
        if decision["will_comment"]:
            raise ValueError("will_comment为true时缺少comment_faction字段。")
        decision["comment_faction"] = None
        _record_output_normalization(
            decision,
            "filled_null_comment_faction_for_silence",
        )


def _validate_decision_conclusion(decision, choices):
    """校验官方信息适用性、文字理由和最终发言派系。"""

    statement_status = choices.get("official_statement_status", "none")
    if statement_status == "none" and decision["official_attitude"] != "not_applicable":
        raise ValueError("没有官方声明时 official_attitude 必须为 not_applicable。")
    if statement_status != "none" and decision["official_attitude"] == "not_applicable":
        raise ValueError("存在官方声明时 official_attitude 不能为 not_applicable。")

    reasons = decision["decision_reason"]
    reason_fields = ("emotion", "official_attitude", "comment")
    if not isinstance(reasons, dict):
        raise ValueError("decision_reason 必须是JSON对象。")
    if any(
        not isinstance(reasons.get(field), str) or not reasons[field].strip()
        for field in reason_fields
    ):
        raise ValueError("decision_reason 必须包含三项非空文字依据。")
    if not decision["will_comment"]:
        decision["comment_faction"] = None
        return decision
    if decision["comment_faction"] not in choices["faction_options"]:
        raise ValueError("comment_faction 不在允许选项中。")
    return decision


def _normalize_persona_and_emotion_evidence(decision, choices):
    """校验 Persona 因素与情绪证据，返回可用和实际引用编号。"""

    persona_factors = decision.get("persona_factors")
    if not isinstance(persona_factors, list) or not persona_factors:
        raise ValueError("persona_factors 必须是非空数组。")
    normalized_persona_factors = []
    for factor in persona_factors:
        normalized_factor = str(factor).strip()
        if (
            normalized_factor
            and normalized_factor not in normalized_persona_factors
        ):
            normalized_persona_factors.append(normalized_factor)
    if not normalized_persona_factors or not set(
        normalized_persona_factors
    ).issubset(set(choices.get("persona_factor_options", []))):
        raise ValueError("persona_factors 包含不允许的Persona依据。")
    decision["persona_factors"] = normalized_persona_factors

    if decision.get("emotion_target") not in choices.get(
        "emotion_target_options", []
    ):
        raise ValueError("emotion_target 不在允许选项中。")
    evidence_ids = decision.get("emotion_evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValueError("emotion_evidence_ids 必须是非空数组。")
    available_ids = {
        item.get("evidence_id")
        for item in choices.get("available_emotion_evidence", [])
    }
    normalized_evidence_ids = _normalize_decision_id_list(
        evidence_ids,
        "emotion_evidence_ids",
        available_ids,
    )
    resolution_evidence_ids = [
        evidence_id
        for evidence_id in choices.get("emotion_resolution", {}).get(
            "supporting_evidence_ids", []
        )
        if evidence_id in available_ids
    ]
    normalized_evidence_ids = list(
        dict.fromkeys(resolution_evidence_ids + normalized_evidence_ids)
    )
    if not normalized_evidence_ids:
        raise ValueError("emotion_evidence_ids 必须是非空数组。")
    if (
        decision["current_emotion"] == "positive"
        and not set(normalized_evidence_ids).intersection(
            choices.get("positive_evidence_ids", [])
        )
    ):
        raise ValueError("进入positive情绪必须引用正面语义证据。")
    decision["emotion_evidence_ids"] = normalized_evidence_ids
    return available_ids, normalized_evidence_ids


def _normalize_official_attitude_evidence(decision, choices, available_ids):
    """校验声明适用性和官方态度证据编号。"""

    raw_evidence_ids = decision.get("official_attitude_evidence_ids")
    statement_status = choices.get("official_statement_status", "none")
    if statement_status == "none" and raw_evidence_ids is None:
        raw_evidence_ids = []
        _record_output_normalization(
            decision,
            "filled_empty_attitude_evidence_without_statement",
        )
    attitude_evidence_ids = _normalize_decision_id_list(
        raw_evidence_ids,
        "official_attitude_evidence_ids",
        available_ids,
    )
    resolution_evidence_ids = [
        evidence_id
        for evidence_id in choices.get(
            "official_attitude_resolution", {}
        ).get("supporting_evidence_ids", [])
        if evidence_id in available_ids
    ]
    attitude_evidence_ids = list(
        dict.fromkeys(resolution_evidence_ids + attitude_evidence_ids)
    )
    if statement_status == "none" and attitude_evidence_ids:
        raise ValueError("没有官方声明时官方态度证据必须为空。")
    if statement_status != "none" and not attitude_evidence_ids:
        raise ValueError("存在官方声明时必须引用官方态度证据。")
    if not set(attitude_evidence_ids).issubset(
        set(choices.get("official_attitude_evidence_ids_allowed", []))
    ):
        raise ValueError(
            "official_attitude_evidence_ids包含不能用于判断官方态度的证据。"
        )
    decision["official_attitude_evidence_ids"] = attitude_evidence_ids
    return attitude_evidence_ids


def _attach_evidence_decision_audit(
    decision,
    choices,
    available_ids,
    emotion_evidence_ids,
    attitude_evidence_ids,
):
    """完成表达、状态变化校验，并附加既有审计字段。"""

    _validate_generated_expression(decision, choices, available_ids)
    _validate_state_transition(decision, choices)
    expression = decision.get("expression")
    expression_evidence_ids = (
        expression.get("evidence_ids", [])
        if isinstance(expression, dict)
        else []
    )
    decision["evidence_appraisal"] = summarize_used_evidence_appraisal(
        choices.get("available_emotion_evidence", []),
        emotion_evidence_ids
        + attitude_evidence_ids
        + expression_evidence_ids,
    )
    decision["persona_decision_profile"] = dict(
        choices.get("persona_decision_profile", {})
    )
    decision["decision_guard"] = dict(choices.get("decision_guard", {}))
    decision["emotion_resolution"] = dict(
        choices.get("emotion_resolution", {})
    )
    attitude_resolution = dict(
        choices.get("official_attitude_resolution", {})
    )
    if attitude_resolution:
        decision["official_attitude_resolution"] = attitude_resolution
        decision["claim_position"] = attitude_resolution.get(
            "claim_position"
        )
        decision["process_evaluation"] = attitude_resolution.get(
            "process_evaluation"
        )


def validate_cognition_decision(decision, choices):
    """校验Agent情绪、官方态度、评论意愿和评论派系。

    2026/10/15，重构功能：基础结构、证据约束和最终结论分段校验；
    校验顺序及错误条件保持不变，避免单个超长函数混合多类职责。
    """

    if choices.get("decision_phase") == "strategy_state":
        return _validate_strategy_state_decision(decision, choices)

    _validate_decision_shape(decision, choices)
    if choices.get("behavior_action_options"):
        _validate_autonomous_behavior(decision, choices)
    if choices.get("emotion_choice_mode") == "evidence_based_all":
        available_ids, emotion_evidence_ids = (
            _normalize_persona_and_emotion_evidence(decision, choices)
        )
        attitude_evidence_ids = _normalize_official_attitude_evidence(
            decision,
            choices,
            available_ids,
        )
        _attach_evidence_decision_audit(
            decision,
            choices,
            available_ids,
            emotion_evidence_ids,
            attitude_evidence_ids,
        )
    return _validate_decision_conclusion(decision, choices)


# 2026/10/17，新增功能：策略状态请求采用不含行为字段的独立校验。
def _validate_strategy_state_decision(decision, choices):
    """校验纯状态输出，并补齐后续行为层需要的中性占位字段。"""

    if not isinstance(decision, dict):
        raise ValueError("LLM状态判断结果必须是JSON对象。")
    for field in ("current_emotion", "official_attitude", "decision_reason"):
        if field not in decision:
            raise ValueError(f"LLM状态输出缺少字段：{field}")
    if decision["current_emotion"] not in choices["emotion_options"]:
        raise ValueError("current_emotion 不在允许选项中。")
    if decision["official_attitude"] not in choices[
        "official_attitude_options"
    ]:
        raise ValueError("official_attitude 不在允许选项中。")

    statement_status = choices.get("official_statement_status", "none")
    attitude = decision["official_attitude"]
    if statement_status == "none" and attitude != "not_applicable":
        raise ValueError("没有官方声明时 official_attitude 必须为 not_applicable。")
    if statement_status != "none" and attitude == "not_applicable":
        raise ValueError("存在官方声明时 official_attitude 不能为 not_applicable。")

    reasons = decision["decision_reason"]
    if not isinstance(reasons, dict) or any(
        not isinstance(reasons.get(field), str) or not reasons[field].strip()
        for field in ("emotion", "official_attitude")
    ):
        raise ValueError("状态decision_reason必须包含情绪和官方态度两项非空依据。")

    # 这些字段由下一阶段的本地行为门控正式填写。这里使用明确的沉默
    # 占位值，保证最终决策对象仍兼容既有存储与指标契约。
    normalized = dict(decision)
    normalized["will_comment"] = False
    normalized["comment_faction"] = None
    normalized["action_type"] = "silent"
    normalized["reshare_comment_id"] = None
    normalized["expression"] = None
    normalized["decision_reason"] = dict(reasons)
    normalized["decision_reason"]["comment"] = "由独立行为门控判断。"
    normalized["decision_pipeline"] = "state_then_behavior_then_expression"
    # 2026/10/18，新增功能：把Persona转换门槛、证据来源和保持原因
    # 附在最终决策中。该审计不二次改写LLM已在合法候选中选择的状态。
    return attach_strategy_state_audit(
        normalized,
        choices.get(
            "_strategy_state_guard_audit",
            choices.get("strategy_state_guard", {}),
        ),
    )

# 2026/08/21 新增功能：将认知决策和全局评论打分结果组合为最终决策。
# 2026/08/25 第六次联调问题修复，修改功能：记录实际被选中评论的评分。
def build_final_decision(
    cognition_decision,
    selected_comment,
    scored_candidates,
    visible_candidate_count,
):
    """组合认知结果，并记录从个人可见范围选择的最终评论。"""
    decision = dict(cognition_decision)
    # 2026/9/5，社交网络传播，修改功能：最终表达来源改为Agent个人可见评论。
    decision["selection_source"] = "personal_visible_comments"
    decision["visible_candidate_count"] = visible_candidate_count
    decision["scored_candidate_count"] = len(scored_candidates)

    if not decision["will_comment"]:
        decision["selected_comment_id"] = None
        decision["selected_comment"] = None
        decision["selected_comment_score"] = None
        return decision

    if selected_comment is None or not scored_candidates:
        raise ValueError("Agent决定评论，但个人可见候选评论为空。")

    decision["selected_comment_id"] = selected_comment["comment_id"]
    decision["selected_comment"] = selected_comment
    selected_score = next(
        (
            item["score"]
            for item in scored_candidates
            if item.get("comment_id") == selected_comment["comment_id"]
        ),
        None,
    )
    if selected_score is None:
        raise ValueError("找不到已选评论对应的评分。")
    decision["selected_comment_score"] = selected_score
    return decision


def build_generated_expression_comment(
    cognition_decision,
    event_context,
    persona,
):
    """把已校验的历史复现原创表达转换为统一评论对象。"""

    expression = cognition_decision.get("expression")
    if not isinstance(expression, dict):
        raise ValueError("缺少已校验的Agent原创表达。")
    event_id = event_context.get("event_id")
    step = event_context.get("current_state", {}).get("step")
    agent_id = persona.get("agent_id")
    identity = (
        f"{event_id}:{step}:{agent_id}:{expression['text']}:"
        f"{','.join(expression['evidence_ids'])}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    orientation = persona.get("information_orientation", {})
    orientation_options = ("fact", "opinion", "questioning")
    dominant_orientation = max(
        orientation_options,
        key=lambda name: float(orientation.get(f"{name}_rate", 0.0)),
    )
    return {
        "comment_id": f"agent_comment_{digest}",
        "text": expression["text"],
        "topic": event_context.get("event_labels", {}).get("topic", "其他"),
        "emotion": expression["emotion"],
        "faction": cognition_decision["comment_faction"],
        "orientation": dominant_orientation,
        "stance": expression["stance"],
        "introduced_step": step,
        "source_type": "agent_original_expression",
        "provenance_type": "agent_original_expression",
        "information_source_type": "agent",
        "information_origin": "endogenous",
        "generation_trigger": "agent_decision",
        "source_agent_id": agent_id,
        "evidence_ids": list(expression["evidence_ids"]),
        "reaction_target": expression.get(
            "reaction_target", "public_discourse"
        ),
        "evidence_role": expression.get("evidence_role", "opinion"),
        "claim_id": expression.get("claim_id"),
        "root_id": expression.get("root_id"),
    }
