"""公共黑板与 Agent 评论可见性。

本模块只负责两件事：
1. 将事件、当前官方声明和当前可用评论组成公共黑板；
2. 从公共黑板中为每个 Agent 随机抽取本轮可见评论。

本模块不读取或写入文件，不调用大模型，也不执行 Agent 决策。
"""

import hashlib
import random


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


def build_agent_blackboard_view(
    public_blackboard,
    agent_id,
    visible_count,
    random_seed,
    current_step_count=None,
):
    """根据公共黑板生成一个 Agent 本轮能够看见的内容。

    参数：
        public_blackboard：build_public_blackboard() 返回的公共黑板。
        agent_id：当前 Agent 编号。
        visible_count：本轮最多展示给该 Agent 的评论数量。
        random_seed：全局随机种子。
        current_step_count：优先展示的当前轮评论数量。

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

    visible_comments = sample_visible_comments(
        comments=public_blackboard["available_comments"],
        agent_id=agent_id,
        event_id=public_blackboard["event_id"],
        step=public_blackboard["step"],
        visible_count=visible_count,
        random_seed=random_seed,
        current_step_count=current_step_count,
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
        "visible_comments": visible_comments,
    }
