"""五策略实验专用的只读展示服务。"""

from __future__ import annotations

from typing import Any

from visualization.shared.experiment_adapter import get_experiment_adapter
from visualization.shared.experiment_catalog import STRATEGY_MODE


def _official_responses(result: dict[str, Any]) -> list[dict[str, Any]]:
    """提取前端需要的公告字段，保留投入轮次与可审计原文。"""

    responses = []
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


def load_dashboard(experiment_id: str) -> dict[str, Any]:
    """整理五策略对比页面需要的数据，不参与仿真计算。"""

    adapter = get_experiment_adapter(experiment_id)
    if adapter.mode != STRATEGY_MODE:
        raise ValueError("所选批次不是五策略实验")

    strategies = []
    for scenario in adapter.scenarios():
        scenario_id = str(scenario["scenario_id"])
        result = adapter.scenario_result(scenario_id)
        official_responses = _official_responses(result)
        rounds = []
        for item in adapter.rounds(scenario_id):
            rounds.append(
                {
                    "step": item.get("step"),
                    "policy_metrics": dict(item.get("policy_metrics", {})),
                    "propagation_metrics": dict(
                        item.get("propagation_metrics", {})
                    ),
                    # 2026/10/11，五策略完整指标展示：保留实验结果中
                    # 已有的逐轮评论生成质量，前端只读展示、不重新计算。
                    "comment_generation": dict(
                        item.get("comment_generation", {})
                    ),
                }
            )
        strategies.append(
            {
                **scenario,
                "status": result.get("status"),
                "comparison_eligible": result.get("comparison_eligible"),
                "entry_triggered": result.get("entry_triggered"),
                "entry_reason": result.get("entry_reason"),
                "official_response_count": len(official_responses),
                # 2026/10/11，新增功能：五策略页面展示公告投入轮次、
                # 公告内容和状态；这里只暴露展示所需字段，不改变实验结果。
                "official_responses": official_responses,
                "rounds": rounds,
                "final_metrics": dict(result.get("final_metrics", {})),
                "effect_metrics": dict(result.get("effect_metrics", {})),
                "comment_quality": adapter.comment_quality(scenario_id),
                "propagation_summary": adapter.propagation_summary(scenario_id),
                "final_trend": adapter.final_trend(scenario_id),
                "performance": dict(result.get("performance", {})),
            }
        )

    return {
        "experiment_id": adapter.experiment_id,
        "event_id": adapter.event_id,
        "mode": adapter.mode,
        "mode_label": adapter.descriptor["mode_label"],
        "status": adapter.result.get("status"),
        "entry_strategy": adapter.result.get("entry_strategy"),
        "entry_triggered": adapter.result.get("entry_triggered"),
        "entry_reason": adapter.result.get("entry_reason"),
        "strategy_count": len(strategies),
        "step_count": adapter.step_count,
        "strategies": strategies,
        "comparison": dict(adapter.result.get("comparison", {})),
        "performance": dict(adapter.result.get("performance", {})),
    }
