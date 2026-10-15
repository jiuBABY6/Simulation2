"""共享网络层的评论目录与单评论传播链。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from visualization.shared.experiment_adapter import get_experiment_adapter
from visualization.shared.network.repository import (
    load_decisions,
    load_events,
    resolve_scenario,
)


def _comment_texts(decisions: list[dict[str, Any]]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for record in decisions:
        decision = record.get("decision", {})
        if not isinstance(decision, dict):
            continue
        comment = decision.get("selected_comment", {})
        if not isinstance(comment, dict):
            continue
        comment_id = str(comment.get("comment_id", "")).strip()
        text = str(comment.get("text", "")).strip()
        if comment_id and text:
            texts.setdefault(comment_id, text)
    return texts


def build_comment_catalog(
    experiment_id: str, scenario_id: str | None
) -> dict[str, Any]:
    """返回按传播深度和曝光次数排序的评论目录。"""

    adapter = get_experiment_adapter(experiment_id)
    adapter.validate_network_files()
    scenario_id, scenario_name = resolve_scenario(adapter, scenario_id)
    events = load_events(adapter, scenario_id)
    texts = _comment_texts(load_decisions(adapter, scenario_id))
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        comment_id = str(event.get("comment_id", "")).strip()
        if comment_id:
            groups[comment_id].append(event)
    comments = []
    for comment_id, comment_events in groups.items():
        resulting_ids = {
            event.get("resulting_expression_id")
            for event in comment_events
            if event.get("was_selected") is True
            and event.get("resulting_expression_id")
        }
        comments.append(
            {
                "comment_id": comment_id,
                "text": texts.get(comment_id, "未找到评论文本"),
                "exposure_count": len(comment_events),
                "continued_count": len(resulting_ids),
                "max_depth": max(
                    int(event.get("propagation_depth", 0))
                    for event in comment_events
                ),
                "first_step": min(
                    int(event.get("step", 0)) for event in comment_events
                ),
                "last_step": max(
                    int(event.get("step", 0)) for event in comment_events
                ),
            }
        )
    comments.sort(
        key=lambda item: (
            item["max_depth"],
            item["exposure_count"],
            item["continued_count"],
        ),
        reverse=True,
    )
    return {
        "experiment_id": adapter.experiment_id,
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "comments": comments,
    }


def build_comment_cascade(
    experiment_id: str, scenario_id: str | None, comment_id: str
) -> dict[str, Any]:
    """返回一条评论的表达、继续传播和停止曝光节点。"""

    adapter = get_experiment_adapter(experiment_id)
    adapter.validate_network_files()
    scenario_id, scenario_name = resolve_scenario(adapter, scenario_id)
    comment_id = str(comment_id).strip()
    if not comment_id:
        raise ValueError("comment_id 不能为空")
    decisions = load_decisions(adapter, scenario_id)
    events = [
        event
        for event in load_events(adapter, scenario_id)
        if event.get("comment_id") == comment_id
    ]
    expression_nodes: dict[str, dict[str, Any]] = {}
    comment_text = ""
    for record in decisions:
        decision = record.get("decision", {})
        if not isinstance(decision, dict):
            continue
        selected = decision.get("selected_comment", {})
        if not isinstance(selected, dict) or selected.get("comment_id") != comment_id:
            continue
        expression_id = decision.get("expression_id")
        if not expression_id:
            continue
        comment_text = comment_text or str(selected.get("text", ""))
        expression_nodes[str(expression_id)] = {
            "node_id": expression_id,
            "node_type": "expression",
            "agent_id": record.get("agent_id"),
            "step": record.get("step"),
            "depth": decision.get("propagation_depth", 0),
            "parent_expression_ids": decision.get("parent_expression_ids", []),
            "root_expression_ids": decision.get("root_expression_ids", []),
        }
    links = []
    stop_nodes = []
    seen_links: set[tuple[Any, Any, str]] = set()
    for event in events:
        source_id = event.get("source_expression_id")
        if event.get("was_selected") is True and event.get(
            "resulting_expression_id"
        ):
            target_id = event["resulting_expression_id"]
            key = (source_id, target_id, "continued")
            if key not in seen_links:
                seen_links.add(key)
                links.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "link_type": "continued",
                        "step": event.get("step"),
                        "effective_weight": event.get("effective_weight"),
                    }
                )
        else:
            stop_id = f"stop_{event.get('propagation_event_id')}"
            stop_nodes.append(
                {
                    "node_id": stop_id,
                    "node_type": "stopped_exposure",
                    "agent_id": event.get("target_agent_id"),
                    "step": event.get("step"),
                    "depth": event.get("propagation_depth"),
                    "effective_weight": event.get("effective_weight"),
                }
            )
            links.append(
                {
                    "source": source_id,
                    "target": stop_id,
                    "link_type": "stopped",
                    "step": event.get("step"),
                    "effective_weight": event.get("effective_weight"),
                }
            )
    resulting_ids = {
        event.get("resulting_expression_id")
        for event in events
        if event.get("was_selected") is True
        and event.get("resulting_expression_id")
    }
    return {
        "experiment_id": adapter.experiment_id,
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "comment_id": comment_id,
        "comment_text": comment_text or "未找到评论文本",
        "summary": {
            "expression_count": len(expression_nodes),
            "exposure_count": len(events),
            "continued_count": len(resulting_ids),
            "stopped_count": sum(
                event.get("was_selected") is not True for event in events
            ),
            "reached_agent_count": len(
                {
                    event.get("target_agent_id")
                    for event in events
                    if event.get("target_agent_id")
                }
            ),
            "max_depth": max(
                (int(event.get("propagation_depth", 0)) for event in events),
                default=0,
            ),
            "first_step": min(
                (int(event.get("step", 0)) for event in events), default=0
            ),
            "last_step": max(
                (int(event.get("step", 0)) for event in events), default=0
            ),
        },
        "nodes": [*expression_nodes.values(), *stop_nodes],
        "links": links,
    }
