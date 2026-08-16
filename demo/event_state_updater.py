"""事件状态自动更新接口。"""


def update_event_state(event_input, current_state, agent_decisions, interaction_records, official_response):
    """根据本轮 Agent 决策、互动结果和官方回应，生成下一轮事件状态。

    参数：
        event_input：event_example.json 中的固定事件信息。
        current_state：本轮开始时的 event_state.json。
        agent_decisions：本轮所有 Agent 的决策结果列表。
        interaction_records：本轮评论传播和互动记录列表。
        official_response：本轮新增的官方回应内容；没有回应时传 None。

    返回：
        next_state：下一轮可直接保存为 event_state.json 的字典。
    """
    raise NotImplementedError("事件状态更新接口尚未实现")


def classify_statement_status(official_statement, event_input, interaction_records):
    """判断官方声明属于 none、clear、incomplete 还是 conflict。

    参数：
        official_statement：当前官方声明文本。
        event_input：固定事件信息。
        interaction_records：用于辅助判断冲突的信息记录。

    返回：
        statement_status：官方声明状态字符串。
    """
    raise NotImplementedError("官方声明状态判断接口尚未实现")


def calculate_event_seriousness(event_input, current_state, agent_decisions, interaction_records):
    """根据事件传播规模和 Agent 反应，计算下一轮事件严重程度。

    参数：
        event_input：固定事件信息。
        current_state：本轮事件状态。
        agent_decisions：本轮所有 Agent 决策结果。
        interaction_records：本轮公共黑板可见和互动记录。

    返回：
        seriousness：low、medium 或 high。
    """
    raise NotImplementedError("事件严重程度计算接口尚未实现")
