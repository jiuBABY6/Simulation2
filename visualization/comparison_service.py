"""计算模拟趋势与人工群体趋势之间的探索性对照指标。"""

from __future__ import annotations

from typing import Any


def _direction(previous: float, current: float, tolerance: float = 0.02) -> int:
    delta = current - previous
    if abs(delta) <= tolerance:
        return 0
    return 1 if delta > 0 else -1


def _normalize_period(period: str | None) -> str:
    """统一“以后”和波浪号等写法，只识别表示法差异。"""

    return (period or "").replace("以后", "~").replace("～", "~").replace(" ", "")


def _comment_negative_rate(round_item: dict[str, Any]) -> float | None:
    distribution = round_item.get("current_comment_distribution", {}).get(
        "distribution", {}
    )
    return distribution.get("negative", {}).get("rate")


# 2026/09/02 历史趋势可视化，新增功能：仅比较双方共同具备的群体负面率。
def compare_negative_trends(
    simulation: dict[str, Any], real_trend: dict[str, Any]
) -> dict[str, Any]:
    """按相同阶段比较负面率，不推导真实接受率或真实质疑率。"""

    simulated_by_step = {
        item["step"]: item for item in simulation.get("rounds", [])
    }
    pairs = []
    for real_item in real_trend.get("periods", []):
        step = real_item.get("step")
        simulated = simulated_by_step.get(step)
        real_rate = real_item.get("sentiment", {}).get("negative", {}).get(
            "estimate"
        )
        if not simulated or real_rate is None:
            continue
        simulated_comment_rate = _comment_negative_rate(simulated)
        if simulated_comment_rate is None:
            continue
        pairs.append(
            {
                "step": step,
                "simulation_period": simulated.get("period"),
                "real_reference_period": real_item.get("period"),
                "period_aligned": _normalize_period(
                    simulated.get("period")
                ) == _normalize_period(real_item.get("period")),
                "phase": real_item.get("phase"),
                "simulation_comment_rate": simulated_comment_rate,
                "simulation_agent_rate": simulated.get("negative_rate"),
                "real_reference_rate": real_rate,
                "absolute_error": round(
                    abs(simulated_comment_rate - real_rate), 4
                ),
            }
        )

    if not pairs:
        return {"pairs": [], "metrics": {}}

    direction_matches = 0
    direction_count = 0
    for index in range(1, len(pairs)):
        simulation_direction = _direction(
            pairs[index - 1]["simulation_comment_rate"],
            pairs[index]["simulation_comment_rate"],
        )
        real_direction = _direction(
            pairs[index - 1]["real_reference_rate"],
            pairs[index]["real_reference_rate"],
        )
        pairs[index]["direction_match"] = simulation_direction == real_direction
        direction_matches += int(simulation_direction == real_direction)
        direction_count += 1
    pairs[0]["direction_match"] = None

    simulation_peak_rate = max(item["simulation_comment_rate"] for item in pairs)
    real_peak_rate = max(item["real_reference_rate"] for item in pairs)
    simulation_peak_steps = [
        item["step"]
        for item in pairs
        if item["simulation_comment_rate"] == simulation_peak_rate
    ]
    real_peak_steps = [
        item["step"]
        for item in pairs
        if item["real_reference_rate"] == real_peak_rate
    ]
    peak_step_difference = min(
        abs(simulation_step - real_step)
        for simulation_step in simulation_peak_steps
        for real_step in real_peak_steps
    )
    return {
        "pairs": pairs,
        "comparison_basis": "current_round_comment_negative_rate",
        "metrics": {
            "mean_absolute_error": round(
                sum(item["absolute_error"] for item in pairs) / len(pairs), 4
            ),
            "final_absolute_error": pairs[-1]["absolute_error"],
            "direction_agreement_rate": (
                round(direction_matches / direction_count, 4)
                if direction_count
                else None
            ),
            "simulation_peak_steps": simulation_peak_steps,
            "real_reference_peak_steps": real_peak_steps,
            "peak_step_difference": peak_step_difference,
        },
        "alignment": {
            "method": "按八个事件阶段的顺序对齐",
            "different_period_steps": [
                item["step"] for item in pairs if not item["period_aligned"]
            ],
            "note": "存在日期边界差异时不进行日级插值，分别保留模拟与人工材料的原始时间段。",
        },
        "interpretation": "当前轮评论负面率与人工群体趋势的探索性对照，不代表模型准确率或个体预测能力。",
    }
