"""共享网络报告的实验级摘要。"""

from __future__ import annotations

from typing import Any

from visualization.shared.experiment_adapter import get_experiment_adapter
from visualization.shared.experiment_catalog import HISTORICAL_MODE
from visualization.shared.network.repository import load_json


def _overall_quality(qualities: list[dict[str, Any]]) -> dict[str, Any]:
    llm_count = sum(int(item.get("llm_comment_count", 0)) for item in qualities)
    history_count = sum(
        int(item.get("history_fallback_count", 0)) for item in qualities
    )
    emergency_count = sum(
        int(item.get("emergency_fallback_count", 0)) for item in qualities
    )
    total = llm_count + history_count + emergency_count
    fallback_count = history_count + emergency_count
    return {
        "total_comment_count": total,
        "llm_comment_count": llm_count,
        "history_fallback_count": history_count,
        "emergency_fallback_count": emergency_count,
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_count / total, 6) if total else 0.0,
        "quality_status": (
            "normal"
            if qualities
            and all(item.get("quality_status") == "normal" for item in qualities)
            else "degraded"
        ),
    }


def build_report_summary(experiment_id: str) -> dict[str, Any]:
    """构建两种实验共用的社交网络专题摘要。"""

    adapter = get_experiment_adapter(experiment_id)
    adapter.validate_network_files()
    network = load_json(adapter.network_file)
    scenarios = []
    for item in adapter.scenarios():
        scenario_id = str(item["scenario_id"])
        scenarios.append(
            {
                **item,
                "propagation": adapter.propagation_summary(scenario_id),
                "quality": adapter.comment_quality(scenario_id),
                "final_trend": adapter.final_trend(scenario_id),
            }
        )
    total_exposure = sum(
        int(item["propagation"].get("exposure_count", 0))
        for item in scenarios
    )
    total_continued = sum(
        int(item["propagation"].get("continued_propagation_count", 0))
        for item in scenarios
    )
    max_depth = max(
        (
            int(item["propagation"].get("max_propagation_depth", 0))
            for item in scenarios
        ),
        default=0,
    )
    default_scenario = str(scenarios[0]["scenario_id"]) if scenarios else ""
    mode_text = (
        "历史复现"
        if adapter.mode == HISTORICAL_MODE
        else "回应方案对照实验"
    )
    findings = [
        f"{mode_text}使用 {len(network.get('nodes', []))} 个 Agent、"
        f"{len(network.get('edges', []))} 条固定关注边。",
        f"当前汇总 {len(scenarios)} 个场景、{total_exposure} 次邻居曝光，"
        f"最大传播深度为 {max_depth} 层。",
        "传播记录保留来源表达、目标 Agent、传播深度、衰减权重和是否继续表达。",
        "页面直接读取实验快照，不重新调用大模型，也不修改实验结果。",
    ]
    limitations = [
        "关注关系由固定种子生成，尚未按现实关系或互动行为动态校准。",
        "公共评论补充不属于邻居传播事件，传播链只覆盖关系网络内的曝光。",
        "本页面用于分析模拟机制，不代表现实平台的真实传播规模。",
    ]
    if adapter.mode == HISTORICAL_MODE:
        limitations.insert(
            0, "历史复现只有一条路线，阶段差异不能解释为策略因果效果。"
        )
    else:
        limitations.insert(
            0, "五个策略共享初始网络，但进入场景后传播轨迹独立演化。"
        )
    return {
        "experiment_id": adapter.experiment_id,
        "event_id": adapter.event_id,
        "mode": adapter.mode,
        "mode_label": adapter.descriptor["mode_label"],
        "status": adapter.result.get("status"),
        "entry_triggered": adapter.result.get("entry_triggered"),
        "entry_reason": adapter.result.get("entry_reason"),
        "performance": adapter.result.get("performance", {}),
        "max_step": max(
            (int(item.get("step_count", 0)) for item in scenarios),
            default=adapter.step_count,
        ),
        "default_scenario_id": default_scenario,
        "network": {
            "network_version": network.get("network_version"),
            "network_seed": network.get("network_seed"),
            "node_count": len(network.get("nodes", [])),
            "edge_count": len(network.get("edges", [])),
            "neighbors_per_agent": network.get("neighbors_per_agent"),
            "propagation_decay_factor": network.get("propagation_decay_factor"),
            "visibility": network.get("visibility", {}),
        },
        "overall_propagation": {
            "exposure_count": total_exposure,
            "continued_propagation_count": total_continued,
            "continuation_rate": (
                round(total_continued / total_exposure, 6)
                if total_exposure
                else 0.0
            ),
            "max_propagation_depth": max_depth,
        },
        "overall_quality": _overall_quality(
            [item["quality"] for item in scenarios]
        ),
        "scenarios": scenarios,
        "rounds": (
            adapter.round_summaries(default_scenario)
            if adapter.mode == HISTORICAL_MODE and default_scenario
            else []
        ),
        "findings": findings,
        "limitations": limitations,
    }
