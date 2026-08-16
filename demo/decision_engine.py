"""Agent 决策领域逻辑。

本模块只处理 Persona、事件状态和候选评论之间的规则关系，
不负责文件读写，也不负责发送网络请求。
"""

import json


FACTIONS = [
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
]


def get_level(value, quantiles):
    """根据字段自己的 P25、P75 分位数返回 low、medium 或 high。"""
    if not quantiles:
        return "medium"
    if value < quantiles.get("p25", 0.33):
        return "low"
    if value < quantiles.get("p75", 0.66):
        return "medium"
    return "high"


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


def decide_official_attitude(persona, policy, event_context):
    """根据官方声明状态和信息取向选择 accept、wait 或 question。"""
    state = event_context.get("current_state", {})
    status = state.get("official_statement_status", "none")
    orientation = persona.get("information_orientation", {})
    rules = policy.get("candidate_rules", {}).get("official_statement", {})
    quantiles = policy.get("orientation_quantiles", {})

    fact_level = get_level(
        float(orientation.get("fact_rate", 0.0)),
        quantiles.get("fact_rate", {}),
    )
    questioning_level = get_level(
        float(orientation.get("questioning_rate", 0.0)),
        quantiles.get("questioning_rate", {}),
    )

    status_rules = rules.get(status, rules.get("none", {"default": ["wait"]}))
    if status == "clear" and fact_level == "high":
        options = status_rules.get("fact_high", status_rules.get("default", ["wait"]))
    elif status == "incomplete" and questioning_level in ["medium", "high"]:
        options = status_rules.get(
            "questioning_high_or_medium", status_rules.get("default", ["wait"])
        )
    elif status == "conflict" and questioning_level == "high":
        options = status_rules.get("questioning_high", status_rules.get("default", ["wait"]))
    else:
        options = status_rules.get("default", ["wait"])

    scores = {}
    for attitude in options:
        if attitude == "accept":
            scores[attitude] = float(orientation.get("fact_rate", 0.0))
        elif attitude == "question":
            scores[attitude] = float(orientation.get("questioning_rate", 0.0)) + 0.2
        else:
            scores[attitude] = float(persona.get("emotion_expression", {}).get("neutral_rate", 0.0))
    attitude = max(scores, key=scores.get) if scores else "wait"
    return attitude, {key: round(value, 6) for key, value in scores.items()}


def decide_will_comment(persona, event_context, topic_match, current_emotion):
    """根据主题关注度、事件严重程度和非中性情绪决定是否发表评论。"""
    seriousness_bonus = {"low": 0.05, "medium": 0.10, "high": 0.15}
    state = event_context.get("current_state", {})
    neutral_rate = float(persona.get("emotion_expression", {}).get("neutral_rate", 0.0))
    score = (
        topic_match * 0.70
        + seriousness_bonus.get(state.get("seriousness"), 0.10)
        + (1 - neutral_rate) * 0.15
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
    """结合派系偏好、信息取向和事件状态选择评论派系。"""
    scores = get_faction_preference(persona)
    orientation = persona.get("information_orientation", {})
    state = event_context.get("current_state", {})

    scores["观点输出派"] += float(orientation.get("fact_rate", 0.0)) * 0.20
    scores["表态判断派"] += float(orientation.get("opinion_rate", 0.0)) * 0.15

    if state.get("official_statement_status") in ["incomplete", "conflict"]:
        scores["观点输出派"] += float(orientation.get("questioning_rate", 0.0)) * 0.20
    if current_emotion == "negative" and event_context.get("event_labels", {}).get("event_valence") == "negative":
        scores["情绪激进派"] += 0.25
    if not state.get("group_conflict", False):
        scores.pop("矛盾激化派", None)
    else:
        scores["矛盾激化派"] += 0.20
    if state.get("seriousness") == "low" or topic_match < 0.15:
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


def select_best_candidate(candidates, event_context, persona, current_emotion, faction):
    """从评论池中选择最符合 Agent 决策结果的一条评论。"""
    if not candidates:
        return None, []
    scored = []
    for candidate in candidates:
        scored.append(
            {
                "comment_id": candidate.get("comment_id"),
                "score": score_candidate(
                    candidate, event_context, persona, current_emotion, faction
                ),
                "text": candidate.get("text", ""),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    selected_id = scored[0]["comment_id"]
    selected = next(item for item in candidates if item.get("comment_id") == selected_id)
    return selected, scored


def build_allowed_choices(event_context, policy, candidates, persona):
    """根据事件状态生成 LLM 必须遵守的枚举选项和硬约束。"""
    event_valence = event_context.get("event_labels", {}).get("event_valence", "neutral")
    emotion_options = policy.get("candidate_rules", {}).get("emotion", {}).get(
        event_valence, ["neutral"]
    )
    status = event_context.get("current_state", {}).get("official_statement_status", "none")
    attitude_options = {
        "none": ["wait"],
        "clear": ["accept", "wait"],
        "incomplete": ["wait", "question"],
        "conflict": ["wait", "question"],
    }.get(status, ["wait"])
    faction_options = list(FACTIONS)
    forbidden_factions = []
    if not event_context.get("current_state", {}).get("group_conflict", False):
        faction_options.remove("矛盾激化派")
        forbidden_factions.append("矛盾激化派")

    return {
        "emotion_options": emotion_options,
        "official_attitude_options": attitude_options,
        "faction_options": faction_options,
        "candidate_comment_ids": [item.get("comment_id") for item in candidates],
        "forbidden_factions": forbidden_factions,
        "hard_rules": [
            "所有枚举字段必须从允许选项中选择",
            "will_comment 为 false 时，comment_faction 和 selected_comment_id 必须为 null",
            "will_comment 为 true 时，必须选择有效的派系和评论编号",
            "不得仅根据 gender 或 location 推断行为",
        ],
        "persona_fields_used": [
            "topic_preference",
            "information_orientation",
            "emotion_expression",
            "comment_faction_preference",
        ],
        "persona": persona,
    }


def build_decision_prompt(event_context, choices, candidates, previous_state, history_summary):
    """构造单个 Agent 的受约束 LLM 决策提示词。"""
    output_format = {
        "current_emotion": "positive | neutral | negative",
        "official_attitude": "accept | wait | question",
        "will_comment": "true or false",
        "comment_faction": "五个派系之一，或 null",
        "selected_comment_id": "候选评论编号，或 null",
        "decision_reason": {
            "emotion": "一句话说明情绪依据",
            "official_attitude": "一句话说明官方态度依据",
            "comment": "一句话说明评论依据",
        },
    }
    return f"""
你是社会舆情模拟系统中的一个 Agent 决策器。
请根据事件、当前状态、Persona、最近状态和历史摘要，从允许选项中做出本轮决策。

【事件】
{json.dumps(event_context, ensure_ascii=False, indent=2)}

【Agent 最近状态】
{json.dumps(previous_state, ensure_ascii=False, indent=2)}

【Agent 历史摘要】
{json.dumps(history_summary, ensure_ascii=False, indent=2)}

【允许选项和硬约束】
{json.dumps(choices, ensure_ascii=False, indent=2)}

【候选评论池】
{json.dumps(candidates, ensure_ascii=False, indent=2)}

只返回一个 JSON 对象，不输出 Markdown、概率或候选池之外的新评论。
JSON 字段格式：
{json.dumps(output_format, ensure_ascii=False, indent=2)}
""".strip()


def validate_decision(decision, choices):
    """在本地校验 LLM 决策，防止非法值进入模拟流程。"""
    required_fields = [
        "current_emotion",
        "official_attitude",
        "will_comment",
        "comment_faction",
        "selected_comment_id",
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
    if not decision["will_comment"]:
        decision["comment_faction"] = None
        decision["selected_comment_id"] = None
        return decision
    if decision["comment_faction"] not in choices["faction_options"]:
        raise ValueError("comment_faction 不在允许选项中。")
    if decision["selected_comment_id"] not in choices["candidate_comment_ids"]:
        raise ValueError("selected_comment_id 不在候选评论池中。")
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

