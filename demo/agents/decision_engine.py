"""Agent 决策领域逻辑。

本模块只处理 Persona、事件状态和候选评论之间的规则关系，
不负责文件读写，也不负责发送网络请求。
"""

import hashlib
import json
import random


FACTIONS = [
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
]

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
    return {
        "event_id": event_context.get("event_id"),
        "event_content": event_context.get("event_content", ""),
        "event_topic": event_context.get("event_labels", {}).get(
            "topic",
            "其他",
        ),
        "current_state": {
            "step": state.get("step"),
            "official_statement": state.get("official_statement", ""),
            "official_statement_status": state.get(
                "official_statement_status",
                "none",
            ),
            # 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：明确声明是本轮新发布还是历史声明继续有效。
            "official_statement_timing": {
                "introduced_step": statement_timing.get(
                    "introduced_step"
                ),
                "active_round_count": statement_timing.get(
                    "active_round_count",
                    0,
                ),
                "is_new": statement_timing.get("is_new", False),
            },
        },
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


# 第一类决策：基于规则的决策

# get_topic_match()
# decide_emotion()
# decide_official_attitude()
# decide_will_comment()
# decide_comment_faction()
# score_candidate()
# select_best_candidate()


def get_topic_match(persona, event_context):
    """读取 Agent 对当前事件主题的历史关注比例。"""
    topic = event_context.get("event_labels", {}).get("topic", "其他")
    return float(persona.get("topic_preference", {}).get(topic, 0.0))


def decide_emotion(persona, policy, event_context, topic_match):
    """依据事件情绪和 Persona 的历史情绪比例选择当前情绪。"""
    event_emotion = event_context.get("event_labels", {}).get(
        "event_valence", "neutral"
    )
    emotion_options = policy.get("candidate_rules", {}).get("emotion", {}).get(
        event_emotion, ["neutral"]
    )
    emotion_profile = persona.get("emotion_expression", {})
    emotion_scores = {}

    for emotion in emotion_options:
        score = float(emotion_profile.get(f"{emotion}_rate", 0.0))
        if emotion == "neutral" and event_emotion != "neutral":
            score *= 0.4
        if emotion == event_emotion:
            score *= 1 + topic_match
        emotion_scores[emotion] = round(score, 6)

    if not emotion_scores:
        return "neutral", {"neutral": 1.0}
    current_emotion = max(emotion_scores, key=emotion_scores.get)
    return current_emotion, emotion_scores


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


# 2026/08/25 第五次联调问题修复，修改功能：取消不完整声明对 accept 的结构性排除。
def decide_official_attitude(persona, policy, event_context):
    """根据统一候选项和 Persona 信息取向选择官方态度。"""
    orientation = persona.get("information_orientation", {})
    options = get_official_attitude_options(event_context, policy)

    scores = {}
    for attitude in options:
        if attitude == "not_applicable":
            scores[attitude] = 1.0
        elif attitude == "accept":
            scores[attitude] = float(orientation.get("fact_rate", 0.0))
        elif attitude == "question":
            scores[attitude] = float(orientation.get("questioning_rate", 0.0))
        else:
            scores[attitude] = float(persona.get("emotion_expression", {}).get("neutral_rate", 0.0))
    attitude = max(scores, key=scores.get) if scores else "not_applicable"
    return attitude, {key: round(value, 6) for key, value in scores.items()}


def decide_will_comment(persona, event_context, topic_match, current_emotion):
    """根据主题关注度和非中性情绪决定是否发表评论。"""
    neutral_rate = float(persona.get("emotion_expression", {}).get("neutral_rate", 0.0))
    score = (
        topic_match * 0.80
        + (1 - neutral_rate) * 0.20
    )
    will_comment = score >= 0.35 and current_emotion != "neutral"
    return will_comment, round(score, 6)


def get_faction_preference(persona):
    """读取 Persona 中的派系偏好；旧 Persona 没有该字段时使用均匀偏好。"""
    default = {faction: 0.2 for faction in FACTIONS}
    preference = persona.get("comment_faction_preference", {})
    default.update({key: float(value) for key, value in preference.items() if key in FACTIONS})
    return default


def decide_comment_faction(persona, event_context, current_emotion, topic_match):
    """结合派系偏好、信息取向和官方声明状态选择评论派系。"""
    scores = get_faction_preference(persona)
    orientation = persona.get("information_orientation", {})
    state = event_context.get("current_state", {})

    scores["观点输出派"] += float(orientation.get("fact_rate", 0.0)) * 0.20
    scores["表态判断派"] += float(orientation.get("opinion_rate", 0.0)) * 0.15

    if state.get("official_statement_status") in ["incomplete", "conflict"]:
        scores["观点输出派"] += float(orientation.get("questioning_rate", 0.0)) * 0.20
    if current_emotion == "negative" and event_context.get("event_labels", {}).get("event_valence") == "negative":
        scores["情绪激进派"] += 0.25
    if topic_match < 0.15:
        scores["吃瓜派"] += float(persona.get("emotion_expression", {}).get("neutral_rate", 0.0)) * 0.20

    faction = max(scores, key=scores.get)
    return faction, {key: round(value, 6) for key, value in scores.items()}


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
    preferred_candidates = [
        candidate
        for candidate in fresh_candidates
        if candidate.get("stance") in preferred_stances
    ]
    candidate_pool = preferred_candidates or fresh_candidates
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
# attach_selected_comment()


# 2026/08/25 第五次联调问题修复，修改功能：正式决策复用统一官方态度选项并标记声明状态。
# 2026/08/25 第六次联调问题修复，修改功能：向正式决策提供 Persona 和可见评论结构化摘要。
# 2026/08/27 Agent情绪状态转换，修改功能：加入当前轮证据优先和情绪转换依据约束。
# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：约束不同时间和来源证据的用途。
def build_allowed_choices(event_context, policy, candidates, persona):
    """根据事件状态生成认知决策必须遵守的枚举选项和硬约束。"""
    event_valence = event_context.get("event_labels", {}).get("event_valence", "neutral")
    emotion_options = policy.get("candidate_rules", {}).get("emotion", {}).get(
        event_valence, ["neutral"]
    )
    status = event_context.get("current_state", {}).get("official_statement_status", "none")
    attitude_options = get_official_attitude_options(event_context, policy)
    faction_options = list(FACTIONS)
    forbidden_factions = []

    return {
        "emotion_options": emotion_options,
        "official_attitude_options": attitude_options,
        "official_statement_status": status,
        "faction_options": faction_options,
        "visible_comment_ids": [item.get("comment_id") for item in candidates],
        "forbidden_factions": forbidden_factions,
        "hard_rules": [
            "所有枚举字段必须从允许选项中选择",
            "will_comment 为 false 时，comment_faction 必须为 null",
            "will_comment 为 true 时，必须选择有效的评论派系",
            "个人可见评论只用于形成认知，本阶段不选择最终评论",
            "没有官方声明时 official_attitude 必须为 not_applicable",
            "存在官方声明时必须根据声明原文选择 accept、wait 或 question",
            "本轮情绪优先依据当前事件、当前声明和当前轮可见评论",
            "维持或改变上一轮情绪都必须有当前证据，不能只复用历史状态或Persona倾向",
            "官方态度和个人情绪分别判断，accept不强制为neutral，question不强制为negative",
            "只有is_new为true的官方声明才是本轮新增声明，持续声明只能作为仍然有效的背景信息",
            "current_generated_comments表示本轮新舆情，current_repost_comments只表示旧观点再次传播",
            "current_emergency_comments只用于数量保障，不能作为改变情绪的主要证据",
            "不得仅根据 gender 或 location 推断行为",
        ],
        "persona_fields_used": [
            "topic_preference",
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
    }


# 2026/08/25 第五次联调问题修复，修改功能：明确官方态度语义并要求依据本轮证据重新判断。
# 2026/08/25 第六次联调问题修复，修改功能：隔离预设情绪标签并明确现有 Persona 字段的判断用途。
# 2026/08/25 Agent个人评论历史，修改功能：明确使用Agent此前全部评论辅助本轮判断。
# 2026/08/27 Agent情绪状态转换，修改功能：明确证据优先级并区分上一轮状态与本轮判断。
# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：明确新声明、新评论和历史转发的不同证据强度。
def build_decision_prompt(event_context, choices, candidates, previous_state, history_summary):
    """构造只使用个人可见评论的 Agent 认知决策提示词。"""
    agent_event_view = build_agent_event_view(event_context)
    # 2026/08/27 Agent情绪状态转换，修改功能：将旧状态字段改名为上一轮状态，避免被误当作本轮结论。
    previous_state_view = {
        "previous_emotion": previous_state.get("current_emotion"),
        "previous_official_attitude": previous_state.get(
            "official_attitude"
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
{json.dumps(choices, ensure_ascii=False, indent=2)}

【Agent 个人可见评论】
{json.dumps(candidates, ensure_ascii=False, indent=2)}

【判断说明】
1. 证据优先级是：本轮首次发布的官方声明、本轮LLM新生成评论、持续有效的旧声明、本轮历史转发评论、以前轮次评论与个人历史、Persona长期倾向。
2. 系统没有提供预设的本轮情绪结论。current_emotion 必须根据上述证据重新判断；Persona 的 emotion_expression_prior 只是长期弱先验。
3. Persona 的 fact 取向重点检查可验证事实，opinion 取向重点判断立场和处理态度，questioning 取向重点检查遗漏、矛盾和模糊信息；任何取向都不直接等于固定官方态度。
4. 维持上一轮情绪时，理由必须指出当前轮仍存在的证据；改变情绪时，理由必须指出相较此前新增或变化的证据。当前证据混合或不足以维持负面判断时，可以选择 neutral。
5. own_comment_history 是你在本事件中此前发表过的全部评论，只代表个人记忆，不是本轮公共舆情。请比较历史表达与当前新信息；可以维持原判断，也可以说明依据后改变判断，不得机械复制历史结论。
6. accept 表示总体认可当前声明的可信度和回应价值，不代表声明已经包含全部信息；wait 表示当前证据不足；question 表示主要态度是质疑真实性、完整性或处理方式。
7. not_applicable 只用于当前没有官方声明的情况；incomplete 只表示信息尚不完整，不能直接代替你对声明原文的判断。
8. 官方态度与个人情绪是不同判断：accept 后仍可因事件后果保持 negative，question 时也可保持 neutral；不得机械绑定两者。
9. 决策理由必须引用事件原文、当前声明、Persona 摘要、个人评论历史或分层可见评论，不得以“系统标签为负面”直接得出情绪结论。
10. 不要预设任何一种官方内容策略必然更好，必须结合 Persona 和本轮证据作出判断。
11. official_statement_timing.is_new 为 true 时，声明是本轮新增证据；为 false 时只是此前声明继续有效，不得反复当作首次发布。
12. current_repost_comments 包含历史兜底和邻居上一轮表达在本轮的再次传播，可以说明观点仍有热度，但不代表出现了新事实；current_emergency_comments 不得作为改变情绪的主要依据。
13. Agent恢复后，如果本轮LLM新评论出现充分的新负面证据，仍可重新转为 negative；不得因为旧声明仍在就永久保持 neutral。

个人可见评论只用于判断当前舆论环境。本阶段不要选择具体评论编号。
只返回一个 JSON 对象，不输出 Markdown 或概率。
JSON 字段格式：
{json.dumps(output_format, ensure_ascii=False, indent=2)}
""".strip()


# 2026/08/21 新增功能：校验只基于个人可见评论产生的认知决策。
# 2026/08/25 第五次联调问题修复，修改功能：校验官方态度适用性和三项非空决策理由。
def validate_cognition_decision(decision, choices):
    """校验Agent情绪、官方态度、评论意愿和评论派系。"""
    if not isinstance(decision, dict):
        raise ValueError("LLM 决策结果必须是JSON对象。")

    required_fields = [
        "current_emotion",
        "official_attitude",
        "will_comment",
        "comment_faction",
        "decision_reason",
    ]
    for field in required_fields:
        if field not in decision:
            raise ValueError(f"LLM 输出缺少字段：{field}")
    if decision["current_emotion"] not in choices["emotion_options"]:
        raise ValueError("current_emotion 不在允许选项中。")
    if decision["official_attitude"] not in choices["official_attitude_options"]:
        raise ValueError("official_attitude 不在允许选项中。")

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
    if not isinstance(decision["will_comment"], bool):
        raise ValueError("will_comment 必须是布尔值。")
    if not decision["will_comment"]:
        decision["comment_faction"] = None
        return decision
    if decision["comment_faction"] not in choices["faction_options"]:
        raise ValueError("comment_faction 不在允许选项中。")
    return decision


def validate_decision(decision, choices):
    """兼容旧调用名称，实际校验当前的认知决策。"""
    return validate_cognition_decision(decision, choices)


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


def attach_selected_comment(decision, candidates):
    """将 LLM 返回的评论编号补充为完整评论对象。"""
    selected_id = decision.get("selected_comment_id")
    if selected_id is None:
        decision["selected_comment"] = None
        return decision
    selected = next(
        (item for item in candidates if item.get("comment_id") == selected_id),
        None,
    )
    if selected is None:
        raise ValueError("找不到 LLM 选择的评论。")
    decision["selected_comment"] = selected
    return decision
