"""记录评论沿固定社交网络传播的事件与表达谱系。

本模块只负责传播领域数据：为Agent表达补充谱系、构建邻居曝光事件并
保存传播历史；不负责评论抽样、LLM决策或舆情指标计算。
"""

import hashlib

from infrastructure.json_storage import append_jsonl_many, read_jsonl


def build_expression_id(event_id, step, agent_id, comment_id):
    """为一次Agent实际表达生成稳定且可追踪的编号。"""
    source = f"{event_id}:{step}:{agent_id}:{comment_id}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"expression_{digest}"


def _normalize_string_list(values):
    """将字符串列表去空、去重并保持原顺序。"""
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if str(value).strip()
        )
    )


# 2026/9/5，社交网络传播第二阶段A，新增功能：为Agent实际表达补充传播层级和父表达信息。
def attach_expression_lineage(result):
    """返回补充表达编号、传播深度和父表达编号的决策结果。"""
    if not isinstance(result, dict) or result.get("status") != "success":
        return result

    decision = dict(result.get("decision", {}))
    selected_comment = decision.get("selected_comment")
    if decision.get("will_comment") is not True or not isinstance(
        selected_comment, dict
    ):
        decision.update(
            {
                "expression_id": None,
                "propagation_depth": None,
                "parent_expression_ids": [],
                "root_expression_ids": [],
            }
        )
        return {**result, "decision": decision}

    comment = selected_comment.copy()
    expression_id = build_expression_id(
        result.get("event_id"),
        result.get("step"),
        result.get("agent_id"),
        comment.get("comment_id"),
    )
    if comment.get("source_type") == "neighbor_propagation":
        depth = comment.get("propagation_depth", 1)
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            depth = 1
        parent_ids = _normalize_string_list(
            comment.get("source_expression_ids", [])
        )
        root_ids = _normalize_string_list(comment.get("root_expression_ids", []))
        if not root_ids:
            root_ids = parent_ids.copy()
    else:
        depth = 0
        parent_ids = []
        root_ids = [expression_id]

    # 防止上一轮完整曝光明细随评论多轮嵌套增长，只保留当前表达所需谱系。
    comment.pop("propagation_sources", None)
    comment["expression_id"] = expression_id
    comment["propagation_depth"] = depth
    comment["parent_expression_ids"] = parent_ids
    comment["root_expression_ids"] = root_ids
    decision.update(
        {
            "selected_comment": comment,
            "expression_id": expression_id,
            "propagation_depth": depth,
            "parent_expression_ids": parent_ids,
            "root_expression_ids": root_ids,
        }
    )
    return {**result, "decision": decision}


def _build_event_id(event_id, step, source_expression_id, target_agent_id):
    """为一次邻居曝光生成稳定编号。"""
    source = f"{event_id}:{step}:{source_expression_id}:{target_agent_id}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return f"propagation_{digest}"


# 2026/9/5，社交网络传播第二阶段A，新增功能：将个人视图转换为可持久化的邻居曝光事件。
def build_propagation_events(agent_views, decision_results):
    """构建本轮邻居曝光事件，并标记目标Agent是否继续表达该评论。"""
    if not isinstance(agent_views, dict):
        raise ValueError("agent_views 必须是以agent_id为键的字典。")
    decisions_by_agent = {
        result.get("agent_id"): result
        for result in decision_results
        if isinstance(result, dict) and result.get("status") == "success"
    }
    events = []
    seen_event_ids = set()

    for target_agent_id in sorted(agent_views):
        view = agent_views[target_agent_id]
        result = decisions_by_agent.get(target_agent_id, {})
        decision = result.get("decision", {})
        selected_comment_id = decision.get("selected_comment_id")
        resulting_expression_id = decision.get("expression_id")

        for comment in view.get("visible_comments", []):
            if comment.get("source_type") != "neighbor_propagation":
                continue
            comment_id = comment.get("comment_id")
            for source in comment.get("propagation_sources", []):
                source_expression_id = source.get("source_expression_id")
                if not source_expression_id:
                    continue
                propagation_event_id = _build_event_id(
                    view.get("event_id"),
                    view.get("step"),
                    source_expression_id,
                    target_agent_id,
                )
                if propagation_event_id in seen_event_ids:
                    continue
                seen_event_ids.add(propagation_event_id)
                was_selected = selected_comment_id == comment_id
                events.append(
                    {
                        "propagation_event_id": propagation_event_id,
                        "event_id": view.get("event_id"),
                        "step": view.get("step"),
                        "event_type": "neighbor_exposure",
                        "comment_id": comment_id,
                        "source_expression_id": source_expression_id,
                        "root_expression_ids": source.get(
                            "root_expression_ids", []
                        ),
                        "source_agent_id": source.get("source_agent_id"),
                        "target_agent_id": target_agent_id,
                        "propagation_depth": source.get("propagation_depth"),
                        "influence_weight": source.get("influence_weight"),
                        "decay_factor": source.get("decay_factor"),
                        "effective_weight": source.get("effective_weight"),
                        "was_selected": was_selected,
                        "resulting_expression_id": (
                            resulting_expression_id if was_selected else None
                        ),
                    }
                )
    return events


# 2026/9/5，社交网络传播第二阶段A，新增功能：按事件和轮次防重保存传播事件。
def save_step_propagation_events(output_file, events, event_id, step):
    """追加保存一轮传播事件；完全相同的重试结果直接复用。"""
    existing_events = [
        record
        for record in read_jsonl(output_file)
        if record.get("event_id") == event_id and record.get("step") == step
    ]
    if existing_events:
        existing_by_id = {
            record.get("propagation_event_id"): record
            for record in existing_events
        }
        incoming_by_id = {
            record.get("propagation_event_id"): record for record in events
        }
        if existing_by_id == incoming_by_id:
            return len(existing_events)
        raise ValueError(f"事件 {event_id} 的第 {step} 轮传播事件已经存在且内容不同。")

    duplicate_event_ids = len(
        {
            record.get("propagation_event_id")
            for record in events
            if record.get("propagation_event_id")
        }
    ) != len(events)
    invalid_scope = any(
        record.get("event_id") != event_id or record.get("step") != step
        for record in events
    )
    if duplicate_event_ids:
        raise ValueError("本轮传播事件存在重复编号。")
    if invalid_scope:
        raise ValueError("传播事件的event_id或step与当前轮次不一致。")
    append_jsonl_many(output_file, events)
    return len(events)
