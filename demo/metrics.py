"""舆情整体指标统计接口。"""


def calculate_round_metrics(event_input, event_state, agent_decisions, interaction_records, previous_metrics):
    """计算一个时间步的舆情整体指标。

    参数：
        event_input：固定事件信息。
        event_state：本轮事件状态。
        agent_decisions：本轮所有 Agent 的决策结果。
        interaction_records：本轮传播和互动结果。
        previous_metrics：上一轮指标；没有时可传 None。

    返回：
        round_metrics：本轮指标字典。
    """
    raise NotImplementedError("单轮指标统计接口尚未实现")


def calculate_emotion_distribution(agent_decisions):
    """统计 Agent 的正面、中性和负面情绪比例。

    参数：
        agent_decisions：本轮所有 Agent 的决策结果列表。

    返回：
        emotion_distribution：情绪比例字典。
    """
    raise NotImplementedError("情绪分布统计接口尚未实现")


def calculate_attitude_distribution(agent_decisions):
    """统计 accept、wait 和 question 的比例。

    参数：
        agent_decisions：本轮所有 Agent 的决策结果列表。

    返回：
        attitude_distribution：官方态度比例字典。
    """
    raise NotImplementedError("官方态度统计接口尚未实现")


def calculate_faction_distribution(agent_decisions):
    """统计五类评论派系的比例。

    参数：
        agent_decisions：本轮所有 Agent 的决策结果列表。

    返回：
        faction_distribution：评论派系比例字典。
    """
    raise NotImplementedError("评论派系统计接口尚未实现")


def save_round_metrics(round_metrics, output_file):
    """将本轮指标追加保存到 metrics_history.jsonl。

    参数：
        round_metrics：calculate_round_metrics() 返回的本轮指标。
        output_file：指标历史 JSONL 文件路径。

    返回：
        None：保存成功后不返回业务数据。
    """
    raise NotImplementedError("指标保存接口尚未实现")
