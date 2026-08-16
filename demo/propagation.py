"""基于公共黑板的 Agent 评论传播和互动接口。"""


def build_blackboard(event_input, event_state, agent_decisions):
    """构建本轮公共黑板。

    黑板规则：事件和官方声明对所有 Agent 可见；自己的评论始终可见；
    其他 Agent 的评论是否可见，由概率决定。

    参数：
        event_input：event_example.json 的固定事件信息。
        event_state：本轮 event_state.json 的当前状态。
        agent_decisions：本轮所有 Agent 的决策结果列表。

    返回：
        blackboard：包含事件、官方声明和本轮有效评论的字典。
    """
    raise NotImplementedError("公共黑板构建接口尚未实现")


def sample_visible_comments(agent_id, blackboard, visibility_config):
    """按概率抽取某个 Agent 本轮可以看到的评论。

    参数：
        agent_id：正在查看黑板的 Agent 编号。
        blackboard：build_blackboard() 返回的公共黑板。
        visibility_config：其他评论的可见概率等配置。

    返回：
        visible_comments：该 Agent 本轮可见的评论列表。
    """
    raise NotImplementedError("评论可见性抽取接口尚未实现")


def propagate_comments(event_input, event_state, agent_decisions, visibility_config):
    """执行本轮公共黑板评论传播，不使用社交网络。

    参数：
        event_input：固定事件信息，所有 Agent 都可以看到。
        event_state：当前事件状态和官方声明，所有 Agent 都可以看到。
        agent_decisions：本轮所有 Agent 的决策结果。
        visibility_config：评论可见概率、是否始终显示自己的评论等配置。

    返回：
        propagation_result：包含每个 Agent 的可见评论和互动记录的字典。
    """
    raise NotImplementedError("公共黑板评论传播接口尚未实现")


def create_interaction_record(event_id, step, viewer_agent_id, source_agent_id, action, comment_id):
    """创建一条标准化的公共黑板互动记录。

    参数：
        event_id：事件编号。
        step：发生互动的时间步。
        viewer_agent_id：看到或处理评论的 Agent 编号。
        source_agent_id：评论发布者的 Agent 编号。
        action：互动动作，例如 visible、ignore、comment、repost。
        comment_id：被看到或处理的评论编号。

    返回：
        interaction_record：可追加保存到 interaction_history.jsonl 的字典。
    """
    raise NotImplementedError("互动记录创建接口尚未实现")


def build_next_decision_context(agent_id, event_input, event_state, agent_state, visible_comments):
    """构建下一轮某个 Agent 的决策输入。

    参数：
        agent_id：当前 Agent 编号。
        event_input：固定事件信息。
        event_state：当前事件状态和官方声明。
        agent_state：该 Agent 上一轮的简化状态。
        visible_comments：本轮该 Agent 能看到的评论列表。

    返回：
        decision_context：下一轮可交给 Agent 决策模块的上下文字典。
    """
    raise NotImplementedError("下一轮 Agent 决策上下文接口尚未实现")
