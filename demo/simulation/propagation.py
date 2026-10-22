"""公共黑板与 Agent 评论可见性。

本模块只负责三件事：
1. 将事件、当前官方声明和当前可用评论组成公共黑板；
2. 根据固定关系网络提取邻居近期表达；
3. 合并邻居传播与公共评论补充，构建Agent个人可见范围。

本模块不读取或写入文件，不调用大模型，也不执行 Agent 决策。
"""

import hashlib
import random

from simulation.options import (
    DEFAULT_STRATEGY_EXPRESSION_TIME_DECAY,
    DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS,
)

from simulation.social_network import (
    get_followed_agent_ids,
    get_influence_weight,
    get_normalized_influence_weight,
    get_propagation_decay_factor,
)
from simulation.propagation_tracking import build_expression_id


RECENT_EXPRESSION_WINDOW_ROUNDS = DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS
RECENT_EXPRESSION_TIME_DECAY = DEFAULT_STRATEGY_EXPRESSION_TIME_DECAY


def filter_available_comments(comments, current_step):
    """筛选当前时间步已经出现的评论。

    参数：
        comments：全局候选评论列表。
        current_step：当前仿真时间步。

    返回：
        introduced_step 小于或等于当前时间步的评论列表。
    """
    if not isinstance(comments, list):
        raise ValueError("comments 必须是评论列表。")
    if not isinstance(current_step, int) or current_step < 1:
        raise ValueError("current_step 必须是大于或等于 1 的整数。")

    available_comments = []
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError("评论列表中的每一项都必须是字典。")

        introduced_step = comment.get("introduced_step")
        if not isinstance(introduced_step, int) or introduced_step < 1:
            raise ValueError("每条评论必须包含合法的 introduced_step。")

        if introduced_step <= current_step:
            available_comments.append(comment.copy())

    return available_comments


def build_public_blackboard(event_context, comments):
    """构建当前时间步的公共黑板。

    参数：
        event_context：事件固定信息和 current_state 组成的事件上下文。
        comments：全局候选评论列表。

    返回：
        包含事件、官方声明和当前可用评论的公共黑板。
    """
    if not isinstance(event_context, dict):
        raise ValueError("event_context 必须是字典。")

    event_id = event_context.get("event_id")
    current_state = event_context.get("current_state")
    if not event_id:
        raise ValueError("event_context 缺少 event_id。")
    if not isinstance(current_state, dict):
        raise ValueError("event_context 缺少有效的 current_state。")
    if current_state.get("event_id") != event_id:
        raise ValueError("事件信息与当前状态的 event_id 不一致。")

    current_step = current_state.get("step")
    available_comments = filter_available_comments(comments, current_step)

    return {
        "event_id": event_id,
        "step": current_step,
        "event_content": event_context.get("event_content", ""),
        "event_labels": event_context.get("event_labels", {}).copy(),
        "official_statement": current_state.get("official_statement", ""),
        "official_statement_status": current_state.get(
            "official_statement_status", "none"
        ),
        "available_comments": available_comments,
    }


def create_random_generator(agent_id, event_id, step, random_seed):
    """为一个 Agent 的一个时间步创建可复现的随机数生成器。

    Agent 编号只用于区分随机结果，不参与评论偏好或推荐计算。
    """
    seed_text = f"{random_seed}:{event_id}:{step}:{agent_id}"
    seed_number = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    return random.Random(seed_number)


def _preference_value(mapping, key):
    """读取Persona概率字段；缺失或非法值按0处理。"""

    if not isinstance(mapping, dict) or key is None:
        return 0.0
    value = mapping.get(key, 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def comment_persona_relevance_weight(comment, persona):
    """计算公共评论与Persona长期倾向的温和相关度权重。

    权重始终保留1.0的探索基线，因此低偏好评论仍有机会被看见；这里只
    改变历史复现中的抽样概率，不把Persona偏好当作确定性的过滤条件。
    """

    if not isinstance(persona, dict):
        return 1.0
    return 1.0 + sum(
        (
            2.0
            * _preference_value(
                persona.get("topic_preference"),
                comment.get("topic"),
            ),
            1.25
            * _preference_value(
                persona.get("information_orientation"),
                f"{comment.get('orientation')}_rate",
            ),
            0.75
            * _preference_value(
                persona.get("emotion_expression"),
                f"{comment.get('emotion')}_rate",
            ),
            0.75
            * _preference_value(
                persona.get("comment_faction_preference"),
                comment.get("faction"),
            ),
        )
    )


def sample_comments_for_persona(comments, sample_count, random_generator, persona):
    """按Persona相关度执行可复现的不放回加权抽样。"""

    sample_count = min(sample_count, len(comments))
    if sample_count <= 0:
        return []
    if not isinstance(persona, dict):
        return random_generator.sample(comments, sample_count)

    ranked = []
    for index, comment in enumerate(comments):
        weight = comment_persona_relevance_weight(comment, persona)
        # Efraimidis-Spirakis 加权不放回抽样。固定Agent、轮次和随机种子
        # 会得到相同结果，同时避免把相关度最高的评论固定展示给所有人。
        key = random_generator.random() ** (1.0 / max(weight, 0.01))
        ranked.append((key, index, comment))
    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    return [item[2] for item in ranked[:sample_count]]


def sample_visible_comments(
    comments,
    agent_id,
    event_id,
    step,
    visible_count,
    random_seed,
    current_step_count=None,
    persona=None,
):
    """按当前轮和历史评论分层抽取一个 Agent 能看见的评论。

    参数：
        comments：当前时间步可用的评论列表。
        agent_id：当前 Agent 编号，仅用于生成可复现的随机结果。
        event_id：事件编号。
        step：当前仿真时间步。
        visible_count：该 Agent 本轮最多可以看见的评论数量。
        random_seed：全局随机种子。
        current_step_count：优先抽取的当前轮评论数量；不提供时保持普通随机抽样。
        persona：仅历史复现传入，用长期倾向温和调整公共评论抽样概率。

    返回：
        随机抽取且不重复的评论列表。
    """
    if not isinstance(comments, list):
        raise ValueError("comments 必须是评论列表。")
    if not agent_id:
        raise ValueError("agent_id 不能为空。")
    if not event_id:
        raise ValueError("event_id 不能为空。")
    if not isinstance(step, int) or step < 1:
        raise ValueError("step 必须是大于或等于 1 的整数。")
    if not isinstance(visible_count, int) or visible_count < 0:
        raise ValueError("visible_count 必须是非负整数。")
    if current_step_count is not None and (
        not isinstance(current_step_count, int)
        or current_step_count < 0
        or current_step_count > visible_count
    ):
        raise ValueError("current_step_count 必须是 0 到 visible_count 之间的整数。")

    sample_count = min(visible_count, len(comments))
    if sample_count == 0:
        return []

    random_generator = create_random_generator(
        agent_id,
        event_id,
        step,
        random_seed,
    )
    if current_step_count is None:
        selected_comments = sample_comments_for_persona(
            comments,
            sample_count,
            random_generator,
            persona,
        )
        return [comment.copy() for comment in selected_comments]

    # 2026/08/25 第六次联调问题修复，新增功能：优先抽取当前轮 10 条，再抽取历史评论并相互补足缺口。
    current_comments = [
        comment for comment in comments if comment.get("introduced_step") == step
    ]
    historical_comments = [
        comment
        for comment in comments
        if comment.get("introduced_step", step) < step
    ]
    eligible_count = len(current_comments) + len(historical_comments)
    sample_count = min(visible_count, eligible_count)

    current_count = min(current_step_count, len(current_comments), sample_count)
    selected_current = sample_comments_for_persona(
        current_comments,
        current_count,
        random_generator,
        persona,
    )
    remaining_count = sample_count - len(selected_current)

    history_count = min(remaining_count, len(historical_comments))
    selected_history = sample_comments_for_persona(
        historical_comments,
        history_count,
        random_generator,
        persona,
    )
    remaining_count -= len(selected_history)

    selected_current_ids = {id(comment) for comment in selected_current}
    remaining_current = [
        comment
        for comment in current_comments
        if id(comment) not in selected_current_ids
    ]
    selected_extra = sample_comments_for_persona(
        remaining_current,
        remaining_count,
        random_generator,
        persona,
    )
    selected_comments = [*selected_current, *selected_history, *selected_extra]
    random_generator.shuffle(selected_comments)
    return [comment.copy() for comment in selected_comments]


# 2026/10/17，新增功能：策略实验可读取邻居最近多轮的实际表达。
def extract_recent_agent_expressions(
    decision_records,
    event_id,
    step,
    window_rounds=RECENT_EXPRESSION_WINDOW_ROUNDS,
):
    """返回最近若干轮表达，以agent_id映射到按轮龄排序的列表。"""

    if not isinstance(decision_records, list):
        raise ValueError("decision_records 必须是列表。")
    if (
        isinstance(window_rounds, bool)
        or not isinstance(window_rounds, int)
        or window_rounds < 1
    ):
        raise ValueError("window_rounds 必须是正整数。")

    expressions = {}
    lower_step = max(1, step - window_rounds)
    for record in decision_records:
        if not isinstance(record, dict):
            continue
        source_step = record.get("step")
        if (
            record.get("event_id") != event_id
            or not isinstance(source_step, int)
            or not lower_step <= source_step < step
        ):
            continue
        if record.get("status") != "success" or not record.get("agent_id"):
            continue
        decision = record.get("decision", {})
        selected_comment = decision.get("selected_comment")
        if decision.get("will_comment") is not True or not isinstance(
            selected_comment, dict
        ):
            continue
        if not selected_comment.get("comment_id"):
            continue

        expression = selected_comment.copy()
        expression_id = expression.get("expression_id") or decision.get(
            "expression_id"
        )
        if not expression_id:
            expression_id = build_expression_id(
                event_id,
                source_step,
                record["agent_id"],
                expression.get("comment_id"),
            )
        depth = expression.get(
            "propagation_depth",
            decision.get("propagation_depth", 0),
        )
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            depth = 0
        root_ids = expression.get(
            "root_expression_ids",
            decision.get("root_expression_ids", []),
        )
        if not isinstance(root_ids, list) or not root_ids:
            root_ids = [expression_id]
        expression["expression_id"] = expression_id
        expression["propagation_depth"] = depth
        expression["root_expression_ids"] = list(dict.fromkeys(root_ids))
        expression["source_step"] = source_step
        expression["expression_age"] = step - source_step
        expressions.setdefault(record["agent_id"], []).append(expression)

    for agent_expressions in expressions.values():
        agent_expressions.sort(
            key=lambda item: (
                item.get("expression_age", window_rounds + 1),
                str(item.get("expression_id", "")),
            )
        )
    return expressions


# 2026/9/5，社交网络传播，新增功能：从决策历史提取邻居上一轮实际发表的评论。
def extract_previous_agent_expressions(decision_records, event_id, step):
    """兼容旧调用：只返回上一轮每名Agent的一条实际表达。"""

    recent = extract_recent_agent_expressions(
        decision_records,
        event_id,
        step,
        window_rounds=1,
    )
    return {
        agent_id: expressions[0]
        for agent_id, expressions in recent.items()
        if expressions
    }


# 2026/9/5，社交网络传播，新增功能：让高影响力Agent的表达拥有更高可见概率。
def weighted_sample_comments(comments, sample_count, random_generator):
    """依据传播权重进行不放回抽样；权重越大，被看见的概率越高。"""
    if sample_count <= 0 or not comments:
        return []
    if sample_count >= len(comments):
        return [comment.copy() for comment in comments]

    ranked = []
    for comment in comments:
        weight = comment.get("propagation_weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            weight = 1.0
        weight = max(float(weight), 0.001)
        random_value = max(random_generator.random(), 1e-12)
        ranked.append((random_value ** (1.0 / weight), comment))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [comment.copy() for _, comment in ranked[:sample_count]]


# 2026/9/5，社交网络传播第二阶段A，新增功能：传播层级增加时按固定系数降低有效权重。
def calculate_decayed_propagation_weight(
    influence_weight,
    propagation_depth,
    decay_factor,
):
    """计算一条传播路径在当前层级的有效权重。"""
    return round(
        float(influence_weight)
        * (float(decay_factor) ** max(0, propagation_depth - 1)),
        6,
    )


# 2026/9/5，社交网络传播，新增功能：按关注关系和影响力权重抽取邻居上一轮表达。
def sample_neighbor_comments(
    social_network,
    agent_expressions,
    agent_id,
    event_id,
    step,
    sample_count,
    random_seed,
):
    """抽取关注邻居的近期表达，按轮龄、根链和时间衰减去重采样。"""
    followed_agent_ids = set(get_followed_agent_ids(social_network, agent_id))
    decay_factor = get_propagation_decay_factor(social_network)
    temporal_decay_factor = RECENT_EXPRESSION_TIME_DECAY
    recent_window_mode = any(
        isinstance(value, list) for value in agent_expressions.values()
    )
    comments_by_root = {}
    for source_agent_id in sorted(followed_agent_ids):
        source_value = agent_expressions.get(source_agent_id)
        source_comments = (
            source_value
            if isinstance(source_value, list)
            else [source_value]
        )
        for source_comment in source_comments:
            if not isinstance(source_comment, dict):
                continue
            comment_id = str(source_comment.get("comment_id", "")).strip()
            if not comment_id:
                continue

            influence_weight = get_influence_weight(
                social_network,
                source_agent_id,
            )
            normalized_influence_weight = get_normalized_influence_weight(
                social_network,
                source_agent_id,
            )
            source_depth = source_comment.get("propagation_depth", 0)
            if (
                isinstance(source_depth, bool)
                or not isinstance(source_depth, int)
                or source_depth < 0
            ):
                source_depth = 0
            propagation_depth = source_depth + 1
            expression_age = source_comment.get("expression_age", 1)
            if (
                isinstance(expression_age, bool)
                or not isinstance(expression_age, int)
                or expression_age < 1
            ):
                expression_age = 1
            network_weight = calculate_decayed_propagation_weight(
                influence_weight,
                propagation_depth,
                decay_factor,
            )
            time_weight = (
                temporal_decay_factor ** (expression_age - 1)
                if recent_window_mode
                else 1.0
            )
            effective_weight = round(network_weight * time_weight, 6)
            normalized_effective_weight = round(
                normalized_influence_weight
                * (float(decay_factor) ** max(0, propagation_depth - 1))
                * time_weight,
                6,
            )
            source_expression_id = source_comment.get("expression_id") or (
                build_expression_id(
                    event_id,
                    step - expression_age,
                    source_agent_id,
                    comment_id,
                )
            )
            root_expression_ids = source_comment.get(
                "root_expression_ids", []
            )
            if not isinstance(root_expression_ids, list) or not root_expression_ids:
                root_expression_ids = [source_expression_id]
            root_expression_ids = [item for item in root_expression_ids if item]
            # 一条表达可能继承多个根；只要与已候选表达共享任一根，
            # 就属于同一已曝光传播链，不能再次占用邻居曝光名额。
            if recent_window_mode:
                root_set = set(root_expression_ids)
                root_key = next(
                    (
                        key
                        for key, value in comments_by_root.items()
                        if root_set.intersection(
                            value.get("root_expression_ids", [])
                        )
                    ),
                    str(root_expression_ids[0]),
                )
            else:
                # 历史复现仍按上一轮评论编号合并，不因策略实验的
                # 三轮根链去重改变既有条件化回放语义。
                root_key = comment_id
            propagation_source = {
                "source_agent_id": source_agent_id,
                "source_expression_id": source_expression_id,
                "root_expression_ids": root_expression_ids,
                "source_depth": source_depth,
                "propagation_depth": propagation_depth,
                "source_step": source_comment.get("source_step"),
                "expression_age": expression_age,
                "influence_weight": influence_weight,
                "normalized_influence_weight": normalized_influence_weight,
                "decay_factor": decay_factor,
                "temporal_decay_factor": temporal_decay_factor,
                "effective_weight": effective_weight,
                "normalized_effective_weight": normalized_effective_weight,
            }
            existing = comments_by_root.get(root_key)
            if existing is None or expression_age < existing["expression_age"]:
                propagated = source_comment.copy()
                propagated["source_type"] = "neighbor_propagation"
                propagated["original_introduced_step"] = source_comment.get(
                    "introduced_step"
                )
                propagated["introduced_step"] = step
                propagated["source_agent_ids"] = [source_agent_id]
                propagated["source_expression_ids"] = [source_expression_id]
                propagated["root_expression_ids"] = root_expression_ids.copy()
                propagated["propagation_depth"] = propagation_depth
                propagated["propagation_sources"] = [propagation_source]
                propagated["propagation_weight"] = effective_weight
                propagated["normalized_propagation_weight"] = (
                    normalized_effective_weight
                )
                propagated["expression_age"] = expression_age
                comments_by_root[root_key] = propagated
            elif expression_age == existing["expression_age"]:
                existing["source_agent_ids"].append(source_agent_id)
                existing["source_expression_ids"].append(source_expression_id)
                existing["propagation_sources"].append(propagation_source)
                existing["propagation_weight"] = round(
                    existing["propagation_weight"] + effective_weight,
                    6,
                )
                # 多名邻居传播同一根信息时使用概率并集式饱和合并，
                # 保留重复曝光增强，同时确保认知权重不会超过1。
                previous_normalized = float(
                    existing.get("normalized_propagation_weight", 0.0)
                )
                existing["normalized_propagation_weight"] = round(
                    1.0
                    - (1.0 - previous_normalized)
                    * (1.0 - normalized_effective_weight),
                    6,
                )

    random_generator = create_random_generator(
        agent_id,
        event_id,
        step,
        random_seed,
    )
    # 优先补最近一轮邻居表达，仍不足时才依次使用更早轮次；所有
    # 邻居层都用完后，调用方才会用公共评论补齐总可见数量。
    selected = []
    comments = list(comments_by_root.values())
    for expression_age in sorted(
        {item.get("expression_age", 1) for item in comments}
    ):
        remaining = sample_count - len(selected)
        if remaining <= 0:
            break
        age_comments = [
            item
            for item in comments
            if item.get("expression_age", 1) == expression_age
        ]
        selected.extend(
            weighted_sample_comments(
                age_comments,
                min(remaining, len(age_comments)),
                random_generator,
            )
        )
    return selected


# 2026/9/5，社交网络传播，新增功能：合并邻居传播评论与公共评论补充，形成个人可见范围。
def build_network_visible_comments(
    public_comments,
    social_network,
    agent_expressions,
    agent_id,
    event_id,
    step,
    visible_count,
    current_step_count,
    neighbor_comment_count,
    public_comment_count,
    random_seed,
    persona=None,
    include_comment_ids=False,
):
    """优先加入邻居表达，再用公共评论补足本轮可见评论。

    默认保持原有“评论列表＋两个数量”的返回契约；个人视图构建器可
    请求实际编号，用于历史复现的曝光审计。
    """
    neighbor_target = min(neighbor_comment_count, visible_count)
    neighbor_comments = sample_neighbor_comments(
        social_network,
        agent_expressions,
        agent_id,
        event_id,
        step,
        neighbor_target,
        random_seed,
    )
    neighbor_ids = {
        comment.get("comment_id") for comment in neighbor_comments
    }
    remaining_public = [
        comment
        for comment in public_comments
        if comment.get("comment_id") not in neighbor_ids
    ]
    missing_neighbor_count = neighbor_target - len(neighbor_comments)
    public_target = min(
        visible_count - len(neighbor_comments),
        public_comment_count + missing_neighbor_count,
    )
    public_comments = sample_visible_comments(
        remaining_public,
        agent_id,
        event_id,
        step,
        public_target,
        random_seed,
        current_step_count=min(current_step_count, public_target),
        persona=persona,
    )
    visible_comments = [*neighbor_comments, *public_comments]
    random_generator = create_random_generator(
        agent_id,
        event_id,
        step,
        random_seed + 1,
    )
    random_generator.shuffle(visible_comments)
    if include_comment_ids:
        return (
            visible_comments,
            [item.get("comment_id") for item in neighbor_comments],
            [item.get("comment_id") for item in public_comments],
        )
    return visible_comments, len(neighbor_comments), len(public_comments)


# 2026/9/5，社交网络传播，修改功能：个人视图由邻居表达和公共评论共同组成。
def build_agent_blackboard_view(
    public_blackboard,
    agent_id,
    visible_count,
    random_seed,
    current_step_count=None,
    social_network=None,
    agent_expressions=None,
    neighbor_comment_count=0,
    public_comment_count=None,
    persona=None,
):
    """根据公共黑板生成一个 Agent 本轮能够看见的内容。

    参数：
        public_blackboard：build_public_blackboard() 返回的公共黑板。
        agent_id：当前 Agent 编号。
        visible_count：本轮最多展示给该 Agent 的评论数量。
        random_seed：全局随机种子。
        current_step_count：优先展示的当前轮评论数量。
        social_network：本批次固定社交网络；为空时兼容旧的公共抽样方式。
        agent_expressions：上一轮各Agent实际表达。
        neighbor_comment_count：邻居传播评论的目标数量。
        public_comment_count：公共评论的基础补充数量。
        persona：历史复现使用的长期倾向；为空时保持原有均匀抽样。

    返回：
        包含完整事件、官方声明和随机评论子集的 Agent 可见视图。
    """
    if not isinstance(public_blackboard, dict):
        raise ValueError("public_blackboard 必须是字典。")

    required_fields = ["event_id", "step", "available_comments"]
    missing_fields = [
        field for field in required_fields if field not in public_blackboard
    ]
    if missing_fields:
        raise ValueError(
            "public_blackboard 缺少字段：" + ", ".join(missing_fields)
        )

    if social_network is None:
        visible_comments = sample_visible_comments(
            comments=public_blackboard["available_comments"],
            agent_id=agent_id,
            event_id=public_blackboard["event_id"],
            step=public_blackboard["step"],
            visible_count=visible_count,
            random_seed=random_seed,
            current_step_count=current_step_count,
            persona=persona,
        )
        neighbor_comment_ids = []
        public_comment_ids = [
            item.get("comment_id") for item in visible_comments
        ]
        neighbor_target_count = 0
    else:
        public_comment_count = (
            visible_count
            if public_comment_count is None
            else public_comment_count
        )
        visible_comments, neighbor_comment_ids, public_comment_ids = (
            build_network_visible_comments(
                public_comments=public_blackboard["available_comments"],
                social_network=social_network,
                agent_expressions=agent_expressions or {},
                agent_id=agent_id,
                event_id=public_blackboard["event_id"],
                step=public_blackboard["step"],
                visible_count=visible_count,
                current_step_count=current_step_count or 0,
                neighbor_comment_count=neighbor_comment_count,
                public_comment_count=public_comment_count,
                random_seed=random_seed,
                persona=persona,
                include_comment_ids=True,
            )
        )
        neighbor_target_count = min(neighbor_comment_count, visible_count)

    # 2026/08/25 第六次联调问题修复，新增功能：记录当前轮与历史评论的实际可见数量。
    current_step_visible_count = sum(
        comment.get("introduced_step") == public_blackboard["step"]
        for comment in visible_comments
    )

    neighbor_id_set = set(neighbor_comment_ids)
    neighbor_comments = [
        item
        for item in visible_comments
        if item.get("comment_id") in neighbor_id_set
    ]
    neighbor_age_distribution = {}
    neighbor_root_ids = set()
    for comment in neighbor_comments:
        age = str(comment.get("expression_age", 1))
        neighbor_age_distribution[age] = (
            neighbor_age_distribution.get(age, 0) + 1
        )
        neighbor_root_ids.update(comment.get("root_expression_ids", []))

    return {
        "agent_id": agent_id,
        "event_id": public_blackboard["event_id"],
        "step": public_blackboard["step"],
        "event_content": public_blackboard.get("event_content", ""),
        "event_labels": public_blackboard.get("event_labels", {}).copy(),
        "official_statement": public_blackboard.get("official_statement", ""),
        "official_statement_status": public_blackboard.get(
            "official_statement_status", "none"
        ),
        "visible_comment_ids": [
            comment["comment_id"] for comment in visible_comments
        ],
        "current_step_visible_count": current_step_visible_count,
        "historical_visible_count": (
            len(visible_comments) - current_step_visible_count
        ),
        "neighbor_visible_count": len(neighbor_comment_ids),
        "public_visible_count": len(public_comment_ids),
        # 2026/10/17，新增功能：显式记录邻居曝光目标、实际填充率、
        # 轮龄和去重后的根表达数量，便于判断社交网络是否真正生效。
        "neighbor_target_count": neighbor_target_count,
        "effective_neighbor_exposure_rate": (
            round(len(neighbor_comment_ids) / neighbor_target_count, 6)
            if neighbor_target_count
            else None
        ),
        "neighbor_expression_age_distribution": neighbor_age_distribution,
        "unique_neighbor_root_count": len(neighbor_root_ids),
        "visible_neighbor_comment_ids": neighbor_comment_ids,
        "visible_public_comment_ids": public_comment_ids,
        "public_sampling_method": (
            "persona_weighted_seeded" if isinstance(persona, dict) else "uniform_seeded"
        ),
        "visible_comments": visible_comments,
    }
