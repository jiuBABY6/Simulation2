"""Agent 内部状态判断使用的评论证据边界。

2026/10/18，新增功能：消融实验可让外部 LLM 增量评论继续出现在
个人可见范围和公开表达阶段，但不允许它们直接改变 Agent 内部状态。
本模块只筛选已有内存对象，不读取文件、不调用模型，也不修改评论。
"""

from __future__ import annotations

from simulation.options import (
    DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS,
    excludes_llm_incremental_from_state,
    uses_evidence_based_emotions,
    uses_strategy_participation_gate,
)


AGENT_EXPRESSION_SOURCE_TYPES = {
    "agent_original_expression",
    "neighbor_propagation",
}

# 2026/10/18，修改功能：回应方案实验仍向行为与表达阶段提供4条邻居
# 表达，但内部状态每轮最多吸收2条最近邻居表达。该限制约束认知证据，
# 不改变社交网络、传播记录或个人实际可见评论数量。
STRATEGY_NEIGHBOR_STATE_LIMIT = 4
STRATEGY_NEIGHBOR_MAX_AGE = DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS
# 2026/10/18，修改功能：公共评论同样只承担有限的状态证据作用。
# 行为层仍接收完整可见评论；这里最多保留5条与当前Persona较相关、
# 且传播根不同的公共表达，避免11条公共评论用数量淹没Persona差异。
STRATEGY_PUBLIC_STATE_LIMIT = 5


def _is_agent_expression(comment: dict) -> bool:
    """判断评论是否来自 Agent 自身或邻居传播。"""

    return (
        comment.get("generation_trigger") == "agent_decision"
        or comment.get("source_type") in AGENT_EXPRESSION_SOURCE_TYPES
    )


def _information_origin(comment: dict) -> str:
    """兼容旧记录推断外生/内生来源。"""

    origin = comment.get("information_origin")
    if origin in {"exogenous", "endogenous"}:
        return origin
    return "endogenous" if _is_agent_expression(comment) else "exogenous"


def _is_initial_comment(comment: dict) -> bool:
    """兼容缺失轮次的旧评论；格式异常的轮次不冒充初始评论。"""

    introduced_step = comment.get("introduced_step", 1)
    try:
        return int(introduced_step or 1) <= 1
    except (TypeError, ValueError):
        return False


def _is_neighbor_comment(comment: dict) -> bool:
    """判断评论是否来自关注网络中的Agent表达。"""

    return comment.get("source_type") == "neighbor_propagation"


def _neighbor_root_key(comment: dict) -> str:
    """返回稳定传播根，避免同一观点链重复占用状态证据名额。"""

    root_ids = comment.get("root_expression_ids")
    if isinstance(root_ids, list):
        normalized = sorted(str(item) for item in root_ids if item)
        if normalized:
            return "|".join(normalized)
    return str(comment.get("comment_id", ""))


def _bounded_rate(value, default=0.0):
    """把画像概率字段安全转换为0到1之间的数值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _persona_public_relevance(comment, persona, event_context):
    """计算公共评论与Persona的稳定相关性，不使用评论情绪极性。"""

    persona = persona if isinstance(persona, dict) else {}
    topic_preferences = persona.get("topic_preference", {})
    topic_preferences = (
        topic_preferences if isinstance(topic_preferences, dict) else {}
    )
    topic_values = [
        _bounded_rate(value)
        for value in topic_preferences.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    maximum_topic = max(topic_values, default=0.0)
    topic = comment.get("topic") or event_context.get(
        "event_labels", {}
    ).get("topic")
    topic_relevance = (
        _bounded_rate(topic_preferences.get(topic)) / maximum_topic
        if maximum_topic > 0
        else 0.5
    )

    orientation = str(comment.get("orientation", "")).strip()
    orientation_preferences = persona.get("information_orientation", {})
    orientation_preferences = (
        orientation_preferences
        if isinstance(orientation_preferences, dict)
        else {}
    )
    orientation_relevance = _bounded_rate(
        orientation_preferences.get(f"{orientation}_rate"),
        1 / 3,
    )
    current_step = event_context.get("current_state", {}).get("step")
    freshness = 1.0 if comment.get("introduced_step") == current_step else 0.0
    return (
        0.55 * orientation_relevance
        + 0.35 * topic_relevance
        + 0.10 * freshness
    )


def _neighbor_weight(comment: dict) -> float:
    """读取传播层已经计算的有效权重，仅用于选择代表性邻居表达。"""

    value = comment.get(
        "normalized_propagation_weight",
        comment.get("propagation_weight", 0.0),
    )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, float(value))


def _bounded_strategy_neighbor_comments(comments):
    """选择最近、不同根且权重较高的少量邻居表达。"""

    eligible = []
    excluded_by_age = 0
    for comment in comments:
        age = comment.get("expression_age", 1)
        if isinstance(age, bool) or not isinstance(age, int):
            age = 1
        if age > STRATEGY_NEIGHBOR_MAX_AGE:
            excluded_by_age += 1
            continue
        eligible.append(comment)

    by_root = {}
    for comment in eligible:
        root_key = _neighbor_root_key(comment)
        current = by_root.get(root_key)
        if current is None or _neighbor_weight(comment) > _neighbor_weight(
            current
        ):
            by_root[root_key] = comment

    ranked = sorted(
        by_root.values(),
        key=lambda item: (
            -_neighbor_weight(item),
            str(item.get("comment_id", "")),
        ),
    )
    selected = ranked[:STRATEGY_NEIGHBOR_STATE_LIMIT]
    return selected, {
        "neighbor_excluded_by_age_count": excluded_by_age,
        "neighbor_duplicate_root_count": len(eligible) - len(by_root),
        "neighbor_excluded_by_limit_count": max(
            0,
            len(ranked) - len(selected),
        ),
    }


def _bounded_strategy_public_comments(comments, persona, event_context):
    """按Persona相关性保留少量独立公共表达。"""

    by_root = {}
    for comment in comments:
        root_key = _neighbor_root_key(comment)
        score = _persona_public_relevance(comment, persona, event_context)
        current = by_root.get(root_key)
        if current is None or score > current[0]:
            by_root[root_key] = (score, comment)
    ranked = sorted(
        by_root.values(),
        key=lambda entry: (
            -entry[0],
            str(entry[1].get("comment_id", "")),
        ),
    )
    selected = [
        entry[1] for entry in ranked[:STRATEGY_PUBLIC_STATE_LIMIT]
    ]
    return selected, {
        "public_duplicate_root_count": len(comments) - len(by_root),
        "public_excluded_by_limit_count": max(
            0,
            len(ranked) - len(selected),
        ),
    }


def build_state_evidence_view(visible_comments, event_context, persona=None):
    """构造状态判断专用评论视图及可审计诊断。

    历史复现继续使用原有证据边界。回应方案实验对邻居表达和公共评论
    分别限流：邻居按传播根与权重保留，公共评论按Persona相关性和传播根
    保留。外部评论消融开关在限流前应用，因此现有消融实验语义不变。
    完整个人可见评论不在本函数内修改，仍可供后续发言与表达阶段使用。
    """

    comments = [
        comment
        for comment in (visible_comments or [])
        if isinstance(comment, dict)
    ]
    filtered = comments
    if excludes_llm_incremental_from_state(event_context):
        filtered = [
            comment
            for comment in filtered
            if _is_initial_comment(comment) or _is_agent_expression(comment)
        ]

    strategy_mode = (
        uses_strategy_participation_gate(event_context)
        and not uses_evidence_based_emotions(event_context)
    )
    visible_neighbors = [
        comment for comment in filtered if _is_neighbor_comment(comment)
    ]
    visible_public = [
        comment for comment in filtered if not _is_neighbor_comment(comment)
    ]
    selected_neighbors = visible_neighbors
    selected_public = visible_public
    neighbor_filter_diagnostics = {
        "neighbor_excluded_by_age_count": 0,
        "neighbor_duplicate_root_count": 0,
        "neighbor_excluded_by_limit_count": 0,
    }
    public_filter_diagnostics = {
        "public_duplicate_root_count": 0,
        "public_excluded_by_limit_count": 0,
    }
    if strategy_mode:
        selected_neighbors, neighbor_filter_diagnostics = (
            _bounded_strategy_neighbor_comments(visible_neighbors)
        )
        selected_public, public_filter_diagnostics = (
            _bounded_strategy_public_comments(
                visible_public,
                persona,
                event_context,
            )
        )
        selected_ids = {
            id(comment)
            for comment in [*selected_neighbors, *selected_public]
        }
        filtered = [
            comment
            for comment in filtered
            if id(comment) in selected_ids
        ]

    diagnostics = {
        "visible_comment_count": len(comments),
        "state_evidence_comment_count": len(filtered),
        "state_evidence_excluded_count": len(comments) - len(filtered),
        "neighbor_visible_comment_count": len(visible_neighbors),
        "neighbor_state_evidence_count": len(selected_neighbors),
        "neighbor_state_evidence_limit": (
            STRATEGY_NEIGHBOR_STATE_LIMIT if strategy_mode else None
        ),
        "strategy_neighbor_evidence_bounded": strategy_mode,
        "public_visible_comment_count": len(visible_public),
        "public_state_evidence_count": len(selected_public),
        "public_state_evidence_limit": (
            STRATEGY_PUBLIC_STATE_LIMIT if strategy_mode else None
        ),
        "strategy_public_evidence_bounded": strategy_mode,
        # 2026/10/19，新增功能：显式诊断外部环境与Agent内生表达的
        # 实际入选数量，避免只看评论总数而无法发现外生语境淹没网络。
        "exogenous_state_evidence_count": sum(
            _information_origin(comment) == "exogenous"
            for comment in filtered
        ),
        "endogenous_state_evidence_count": sum(
            _information_origin(comment) == "endogenous"
            for comment in filtered
        ),
        **neighbor_filter_diagnostics,
        **public_filter_diagnostics,
    }
    return {"comments": filtered, "diagnostics": diagnostics}


def select_state_evidence_comments(
    visible_comments,
    event_context,
    persona=None,
):
    """返回允许进入 Agent 内部状态判断的个人可见评论。

    默认模式返回全部评论。消融模式保留第 1 轮初始语境和 Agent 表达，
    只排除第 2 轮以后由外部增量生成器产生的评论。官方通告不在评论
    列表中，仍通过 ``event_context`` 独立进入状态判断。
    """

    return build_state_evidence_view(
        visible_comments,
        event_context,
        persona,
    )["comments"]
