"""按轮次构建共享社交网络视图。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from visualization.shared.experiment_adapter import get_experiment_adapter
from visualization.shared.network.repository import (
    load_decisions,
    load_events,
    load_json,
    resolve_scenario,
)


def _official_responses(adapter, scenario_id: str) -> list[dict[str, Any]]:
    """返回当前五策略场景的公告节点；历史页面继续使用自身时间线。"""

    if adapter.mode != "strategy_comparison":
        return []
    responses = []
    result = adapter.scenario_result(scenario_id)
    for item in result.get("official_responses", []):
        if not isinstance(item, dict):
            continue
        step = item.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            continue
        responses.append(
            {
                "step": step,
                "strategy_id": str(item.get("strategy_id") or "").strip(),
                "strategy_name": str(item.get("strategy_name") or "").strip(),
                "official_statement": str(
                    item.get("official_statement") or ""
                ).strip(),
                "official_statement_status": str(
                    item.get("official_statement_status") or ""
                ).strip(),
            }
        )
    return sorted(responses, key=lambda item: item["step"])


def build_network_view(
    experiment_id: str, scenario_id: str | None, step: int | None
) -> dict[str, Any]:
    """返回指定轮次的节点状态、本轮传播和截至该轮的累计传播。"""

    adapter = get_experiment_adapter(experiment_id)
    adapter.validate_network_files()
    scenario_id, scenario_name = resolve_scenario(adapter, scenario_id)
    max_step = adapter.scenario_step_count(scenario_id)
    step = max_step if step is None else step
    if (
        isinstance(step, bool)
        or not isinstance(step, int)
        or not 1 <= step <= max_step
    ):
        raise ValueError(f"step 必须是 1 到 {max_step} 之间的整数")

    network = load_json(adapter.network_file)
    all_events = load_events(adapter, scenario_id)
    events = [
        event for event in all_events if int(event.get("step", 0)) <= step
    ]
    # 本轮与累计共用快照，但分别统计，防止前端用累计边误解当前轮传播。
    round_events = [
        event for event in all_events if int(event.get("step", 0)) == step
    ]
    edge_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in network.get("edges", []):
        # 快照边是 source 关注 target，信息流方向则由 target 指向 source。
        source_agent_id = edge["target_agent_id"]
        target_agent_id = edge["source_agent_id"]
        edge_stats[(source_agent_id, target_agent_id)] = {
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "follower_agent_id": target_agent_id,
            "followed_agent_id": source_agent_id,
            "exposure_count": 0,
            "selected_exposure_count": 0,
            "effective_weight_total": 0.0,
            "max_depth": 0,
            "round_exposure_count": 0,
            "round_selected_exposure_count": 0,
            "round_effective_weight_total": 0.0,
            "round_max_depth": 0,
        }
    for event in events:
        key = (event.get("source_agent_id"), event.get("target_agent_id"))
        if key not in edge_stats:
            continue
        stats = edge_stats[key]
        stats["exposure_count"] += 1
        if event.get("was_selected") is True:
            stats["selected_exposure_count"] += 1
        stats["effective_weight_total"] += float(
            event.get("effective_weight", 0.0)
        )
        stats["max_depth"] = max(
            int(stats["max_depth"]), int(event.get("propagation_depth", 0))
        )
    for event in round_events:
        key = (event.get("source_agent_id"), event.get("target_agent_id"))
        if key not in edge_stats:
            continue
        stats = edge_stats[key]
        stats["round_exposure_count"] += 1
        if event.get("was_selected") is True:
            stats["round_selected_exposure_count"] += 1
        stats["round_effective_weight_total"] += float(
            event.get("effective_weight", 0.0)
        )
        stats["round_max_depth"] = max(
            int(stats["round_max_depth"]),
            int(event.get("propagation_depth", 0)),
        )

    node_stats: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {
            "sent_exposure_count": 0,
            "received_exposure_count": 0,
            "continued_count": 0,
        }
    )
    for event in events:
        source = event.get("source_agent_id")
        target = event.get("target_agent_id")
        if source:
            node_stats[str(source)]["sent_exposure_count"] += 1
        if target:
            node_stats[str(target)]["received_exposure_count"] += 1
            if event.get("was_selected") is True:
                node_stats[str(target)]["continued_count"] += 1
    round_node_stats: defaultdict[str, dict[str, int]] = defaultdict(
        lambda: {
            "round_sent_exposure_count": 0,
            "round_received_exposure_count": 0,
            "round_continued_count": 0,
        }
    )
    for event in round_events:
        source = event.get("source_agent_id")
        target = event.get("target_agent_id")
        if source:
            round_node_stats[str(source)]["round_sent_exposure_count"] += 1
        if target:
            round_node_stats[str(target)]["round_received_exposure_count"] += 1
            if event.get("was_selected") is True:
                round_node_stats[str(target)]["round_continued_count"] += 1

    decisions = [
        record
        for record in load_decisions(adapter, scenario_id)
        if record.get("step") == step and record.get("status") == "success"
    ]
    decision_by_agent = {
        str(record.get("agent_id")): record.get("decision", {})
        for record in decisions
        if record.get("agent_id")
        and isinstance(record.get("decision"), dict)
    }
    nodes = []
    for node in network.get("nodes", []):
        agent_id = str(node["agent_id"])
        decision = decision_by_agent.get(agent_id, {})
        nodes.append(
            {
                **node,
                **node_stats[agent_id],
                **round_node_stats[agent_id],
                "current_emotion": decision.get("current_emotion"),
                "official_attitude": decision.get("official_attitude"),
                "will_comment": decision.get("will_comment", False),
                "selected_comment_id": decision.get("selected_comment_id"),
            }
        )
    emotion_counts = {
        emotion: sum(node.get("current_emotion") == emotion for node in nodes)
        for emotion in ("positive", "neutral", "negative")
    }
    decision_count = sum(emotion_counts.values())
    round_descriptor = next(
        (
            item
            for item in adapter.rounds(scenario_id)
            if item.get("step") == step
        ),
        {},
    )
    official_responses = _official_responses(adapter, scenario_id)
    return {
        "experiment_id": adapter.experiment_id,
        "mode": adapter.mode,
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "step": step,
        "max_step": max_step,
        "period": round_descriptor.get("period", ""),
        "phase": round_descriptor.get("phase", ""),
        # 2026/10/11，新增功能：共享网络时间轴在五策略模式下同步
        # 标出公告投入轮次，并允许前端展示公告详情。
        "official_responses": official_responses,
        "nodes": nodes,
        "edges": list(edge_stats.values()),
        "event_count": len(events),
        "round_event_count": len(round_events),
        "active_edge_count": sum(
            1 for item in edge_stats.values() if item["exposure_count"] > 0
        ),
        "round_active_edge_count": sum(
            1
            for item in edge_stats.values()
            if item["round_exposure_count"] > 0
        ),
        "emotion_distribution": {
            emotion: {
                "count": count,
                "rate": round(count / decision_count, 6)
                if decision_count
                else 0.0,
            }
            for emotion, count in emotion_counts.items()
        },
        "commenting_agent_count": sum(
            node.get("will_comment") is True for node in nodes
        ),
    }
