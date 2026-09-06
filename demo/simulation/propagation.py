"""公共黑板与 Agent 评论可见性。

本模块只负责三件事：
1. 将事件、当前官方声明和当前可用评论组成公共黑板；
2. 根据固定关系网络提取邻居上一轮表达；
3. 合并邻居传播与公共评论补充，构建Agent个人可见范围。

本模块不读取或写入文件，不调用大模型，也不执行 Agent 决策。
"""

import hashlib
import random

from simulation.social_network import (
    get_followed_agent_ids,
    get_influence_weight,
    get_propagation_decay_factor,
)
from simulation.propagation_tracking import build_expression_id


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


def sample_visible_comments(
    comments,
    agent_id,
    event_id,
    step,
    visible_count,
    random_seed,
    current_step_count=None,
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
        selected_comments = random_generator.sample(comments, sample_count)
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
    selected_current = random_generator.sample(current_comments, current_count)
    remaining_count = sample_count - len(selected_current)

    history_count = min(remaining_count, len(historical_comments))
    selected_history = random_generator.sample(historical_comments, history_count)
    remaining_count -= len(selected_history)

    selected_current_ids = {id(comment) for comment in selected_current}
    remaining_current = [
        comment
        for comment in current_comments
        if id(comment) not in selected_current_ids
    ]
    selected_extra = random_generator.sample(remaining_current, remaining_count)
    selected_comments = [*selected_current, *selected_history, *selected_extra]
    random_generator.shuffle(selected_comments)
    return [comment.copy() for comment in selected_comments]


# 2026/9/5，社交网络传播，新增功能：从决策历史提取邻居上一轮实际发表的评论。
def extract_previous_agent_expressions(decision_records, event_id, step):
    """返回上一轮各Agent的实际表达，以agent_id为键。"""
    if not isinstance(decision_records, list):
        raise ValueError("decision_records 必须是列表。")
    previous_step = step - 1
    expressions = {}
    if previous_step < 1:
        return expressions

    for record in decision_records:
        if not isinstance(record, dict):
            continue
        if (
            record.get("event_id") != event_id
            or record.get("step") != previous_step
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
                previous_step,
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
        expressions[record["agent_id"]] = expression
    return expressions


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
    """抽取当前Agent所关注邻居的上一轮表达，并标记传播来源。"""
    followed_agent_ids = set(get_followed_agent_ids(social_network, agent_id))
    decay_factor = get_propagation_decay_factor(social_network)
    comments_by_id = {}
    for source_agent_id in sorted(followed_agent_ids):
        source_comment = agent_expressions.get(source_agent_id)
        if not isinstance(source_comment, dict):
            continue
        comment_id = str(source_comment.get("comment_id", "")).strip()
        if not comment_id:
            continue

        influence_weight = get_influence_weight(
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
        effective_weight = calculate_decayed_propagation_weight(
            influence_weight,
            propagation_depth,
            decay_factor,
        )
        source_expression_id = source_comment.get("expression_id") or (
            build_expression_id(
                event_id,
                step - 1,
                source_agent_id,
                comment_id,
            )
        )
        root_expression_ids = source_comment.get(
            "root_expression_ids", []
        )
        if not isinstance(root_expression_ids, list) or not root_expression_ids:
            root_expression_ids = [source_expression_id]
        root_expression_ids = [
            item for item in root_expression_ids if item
        ]
        propagation_source = {
            "source_agent_id": source_agent_id,
            "source_expression_id": source_expression_id,
            "root_expression_ids": root_expression_ids,
            "source_depth": source_depth,
            "propagation_depth": propagation_depth,
            "influence_weight": influence_weight,
            "decay_factor": decay_factor,
            "effective_weight": effective_weight,
        }
        if comment_id not in comments_by_id:
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
            comments_by_id[comment_id] = propagated
        else:
            propagated = comments_by_id[comment_id]
            propagated["source_agent_ids"].append(source_agent_id)
            propagated["source_expression_ids"].append(source_expression_id)
            propagated["root_expression_ids"] = list(
                dict.fromkeys(
                    [
                        *propagated["root_expression_ids"],
                        *root_expression_ids,
                    ]
                )
            )
            propagated["propagation_depth"] = min(
                propagated["propagation_depth"],
                propagation_depth,
            )
            propagated["propagation_sources"].append(propagation_source)
            propagated["propagation_weight"] = round(
                propagated["propagation_weight"] + effective_weight,
                6,
            )

    random_generator = create_random_generator(
        agent_id,
        event_id,
        step,
        random_seed,
    )
    return weighted_sample_comments(
        list(comments_by_id.values()),
        min(sample_count, len(comments_by_id)),
        random_generator,
    )


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
):
    """优先加入邻居表达，再用公共评论补足本轮可见评论。"""
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
    )
    visible_comments = [*neighbor_comments, *public_comments]
    random_generator = create_random_generator(
        agent_id,
        event_id,
        step,
        random_seed + 1,
    )
    random_generator.shuffle(visible_comments)
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
        )
        neighbor_visible_count = 0
        public_visible_count = len(visible_comments)
    else:
        public_comment_count = (
            visible_count
            if public_comment_count is None
            else public_comment_count
        )
        visible_comments, neighbor_visible_count, public_visible_count = (
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
            )
        )

    # 2026/08/25 第六次联调问题修复，新增功能：记录当前轮与历史评论的实际可见数量。
    current_step_visible_count = sum(
        comment.get("introduced_step") == public_blackboard["step"]
        for comment in visible_comments
    )

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
        "neighbor_visible_count": neighbor_visible_count,
        "public_visible_count": public_visible_count,
        "visible_comments": visible_comments,
    }
