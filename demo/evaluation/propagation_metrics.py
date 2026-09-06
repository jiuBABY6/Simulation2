"""计算固定社交网络中的评论传播指标。"""

from infrastructure.json_storage import read_jsonl


def load_propagation_events(history_file, event_id, step=None):
    """读取指定事件的传播记录；提供step时只返回该轮记录。"""
    return [
        record
        for record in read_jsonl(history_file)
        if record.get("event_id") == event_id
        and (step is None or record.get("step") == step)
    ]


def _valid_number(value):
    """判断数值字段有效，并排除布尔值。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# 2026/9/5，社交网络传播第二阶段A，新增功能：统计曝光、覆盖、继续传播和传播深度。
def calculate_propagation_metrics(events, agent_count):
    """根据传播事件计算一轮或一个场景的非评价性传播指标。"""
    if not isinstance(events, list):
        raise ValueError("events 必须是传播事件列表。")
    if (
        isinstance(agent_count, bool)
        or not isinstance(agent_count, int)
        or agent_count < 0
    ):
        raise ValueError("agent_count 必须是非负整数。")

    valid_events = [event for event in events if isinstance(event, dict)]
    reached_agents = {
        event.get("target_agent_id")
        for event in valid_events
        if event.get("target_agent_id")
    }
    source_agents = {
        event.get("source_agent_id")
        for event in valid_events
        if event.get("source_agent_id")
    }
    propagated_comments = {
        event.get("comment_id")
        for event in valid_events
        if event.get("comment_id")
    }
    continued_events = [
        event for event in valid_events if event.get("was_selected") is True
    ]
    continued_expression_ids = {
        event.get("resulting_expression_id")
        or (
            event.get("step"),
            event.get("target_agent_id"),
            event.get("comment_id"),
        )
        for event in continued_events
    }
    continued_agents = {
        event.get("target_agent_id")
        for event in continued_events
        if event.get("target_agent_id")
    }
    depths = [
        event["propagation_depth"]
        for event in valid_events
        if isinstance(event.get("propagation_depth"), int)
        and not isinstance(event.get("propagation_depth"), bool)
        and event["propagation_depth"] >= 1
    ]
    effective_weights = [
        float(event["effective_weight"])
        for event in valid_events
        if _valid_number(event.get("effective_weight"))
    ]
    exposure_count = len(valid_events)
    reached_count = len(reached_agents)
    continuation_count = len(continued_expression_ids)
    return {
        "exposure_count": exposure_count,
        "reached_agent_count": reached_count,
        "reach_rate": round(reached_count / agent_count, 6)
        if agent_count
        else 0.0,
        "source_agent_count": len(source_agents),
        "propagated_comment_count": len(propagated_comments),
        "continued_propagation_count": continuation_count,
        "continued_agent_count": len(continued_agents),
        "continuation_rate": round(continuation_count / exposure_count, 6)
        if exposure_count
        else 0.0,
        "max_propagation_depth": max(depths, default=0),
        "average_propagation_depth": round(sum(depths) / len(depths), 6)
        if depths
        else 0.0,
        "total_effective_weight": round(sum(effective_weights), 6),
    }
