"""多轮社会演化模拟接口。"""


def run_multi_round_simulation(event_input, initial_state, personas, candidate_comments, simulation_config):
    """运行一个事件的多轮 Agent 决策、传播、状态更新和指标统计。

    参数：
        event_input：event_example.json 的固定事件信息。
        initial_state：event_state.json 的初始状态。
        personas：所有 Agent Persona 列表。
        candidate_comments：本事件当前轮次可用的候选评论。
        simulation_config：最大轮数、并发数、传播配置和输出目录等。

    返回：
        simulation_result：包含每轮决策、状态、互动和指标的模拟结果。
    """
    raise NotImplementedError("多轮模拟接口尚未实现")


def run_one_simulation_step(event_input, event_state, personas, agent_states, candidate_comments, step_config):
    """执行一个时间步的完整流程。

    返回：
        step_result：包含 Agent 决策、互动记录、下一轮事件状态和本轮指标。
    """
    raise NotImplementedError("单轮模拟接口尚未实现")


def should_stop_simulation(step, event_state, round_metrics, stop_config):
    """判断是否满足多轮模拟的停止条件。

    参数：
        step：当前时间步。
        event_state：当前事件状态。
        round_metrics：当前轮次指标。
        stop_config：最大轮数、低活跃轮数等停止条件配置。

    返回：
        should_stop：布尔值；True 表示结束模拟。
    """
    raise NotImplementedError("模拟停止条件接口尚未实现")


def save_step_result(step_result, output_dir):
    """保存一个时间步的决策、互动、状态和指标结果。

    参数：
        step_result：run_one_simulation_step() 返回的结果。
        output_dir：模拟结果输出目录。

    返回：
        None：保存成功后不返回业务数据。
    """
    raise NotImplementedError("时间步结果保存接口尚未实现")
