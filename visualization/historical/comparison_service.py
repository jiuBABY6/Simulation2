"""历史复现专用：计算模拟趋势与人工群体趋势的探索性对照。"""

from __future__ import annotations

from typing import Any


COMMENT_DISTRIBUTION_FIELDS = {
    "agent_expression": "agent_expression_distribution",
    "current_round": "current_comment_distribution",
    "cumulative": "cumulative_comment_distribution",
    "active_opinion": "active_comment_distribution",
}
COMMENT_BASIS_LABELS = {
    "agent_expression": "Agent实际表达",
    "current_round": "当前轮增量",
    "cumulative": "模拟评论池累计",
    "active_opinion": "活跃舆情",
}
SENTIMENTS = ("positive", "neutral", "negative")


def _direction(previous: float, current: float, tolerance: float = 0.02) -> int:
    delta = current - previous
    if abs(delta) <= tolerance:
        return 0
    return 1 if delta > 0 else -1


def _normalize_period(period: str | None) -> str:
    """统一“以后”和波浪号等写法，只识别表示法差异。"""

    return (period or "").replace("以后", "~").replace("～", "~").replace(" ", "")


def _comment_sentiment_rate(
    round_item: dict[str, Any],
    basis: str,
    sentiment: str,
) -> float | None:
    field = COMMENT_DISTRIBUTION_FIELDS.get(basis)
    if field is None:
        raise ValueError(f"不支持的评论比较口径：{basis}")
    distribution = round_item.get(field, {}).get("distribution", {})
    return distribution.get(sentiment, {}).get("rate")


# 2026/09/02 历史趋势可视化，新增功能：比较双方共同具备的群体负面率。
# 2026/10/9，修改功能：在保留负面方向主指标的同时增加三分类探索性差异。
def compare_negative_trends(
    simulation: dict[str, Any],
    real_trend: dict[str, Any],
    basis: str = "current_round",
) -> dict[str, Any]:
    """按相同阶段比较三类情绪，负面率继续作为方向和峰值主指标。"""

    if basis not in COMMENT_DISTRIBUTION_FIELDS:
        raise ValueError(f"不支持的评论比较口径：{basis}")

    simulation_event_id = str(simulation.get("event_id") or "").strip()
    real_event_id = str(real_trend.get("event_id") or "").strip()
    if not simulation_event_id or not real_event_id:
        raise ValueError("模拟结果和真实趋势都必须包含 event_id")
    if simulation_event_id != real_event_id:
        raise ValueError(
            "模拟结果与真实趋势的 event_id 不一致："
            f"{simulation_event_id} != {real_event_id}"
        )

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
        simulated_comment_rate = _comment_sentiment_rate(
            simulated,
            basis,
            "negative",
        )
        if simulated_comment_rate is None:
            continue
        sentiment_comparison = {}
        for sentiment in SENTIMENTS:
            simulation_rate = _comment_sentiment_rate(
                simulated,
                basis,
                sentiment,
            )
            reference_rate = real_item.get("sentiment", {}).get(
                sentiment, {}
            ).get("estimate")
            sentiment_comparison[sentiment] = {
                "simulation_rate": simulation_rate,
                "real_reference_rate": reference_rate,
                "absolute_error": (
                    round(abs(simulation_rate - reference_rate), 4)
                    if simulation_rate is not None
                    and reference_rate is not None
                    else None
                ),
            }
        pairs.append(
            {
                "step": step,
                "simulation_period": simulated.get("period"),
                "real_reference_period": real_item.get("period"),
                "period_aligned": _normalize_period(
                    simulated.get("period")
                ) == _normalize_period(real_item.get("period")),
                "phase": real_item.get("phase"),
                "sampling_method": real_item.get("sampling_method"),
                "simulation_comment_rate": simulated_comment_rate,
                "simulation_agent_rate": simulated.get("negative_rate"),
                "real_reference_rate": real_rate,
                "sentiment_comparison": sentiment_comparison,
                # 2026/10/8，新增功能：人工初始化轮次继续展示，但不冒充模型自由预测点。
                "is_calibration_point": bool(
                    simulated.get("is_calibration_point", False)
                ),
                "absolute_error": round(
                    abs(simulated_comment_rate - real_rate), 4
                ),
            }
        )

    pairs.sort(key=lambda item: item["step"])
    for item in pairs:
        item["included_in_point_error"] = not item["is_calibration_point"]
    if not pairs:
        return {
            "event_id": simulation_event_id,
            "pairs": [],
            "comparison_basis": basis,
            "metrics": {},
            "metric_scope": {
                "observation_count": 0,
                "transition_count": 0,
                "status": "insufficient_data",
            },
            "alignment": {
                "method": "未找到可共同对齐的事件阶段",
                "different_period_steps": [],
            },
            "interpretation": "没有共同观测点，无法进行探索性趋势对照。",
        }

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
        pairs[index]["simulation_direction"] = simulation_direction
        pairs[index]["real_reference_direction"] = real_direction
        pairs[index]["direction_match"] = simulation_direction == real_direction
        direction_matches += int(simulation_direction == real_direction)
        direction_count += 1
    pairs[0]["direction_match"] = None
    # 2026/10/8，修改功能：MAE和峰值排除人工校准点；第1到第2轮的预测方向仍可评价。
    evaluation_pairs = [
        item for item in pairs if item["included_in_point_error"]
    ]
    metrics = {
        "mean_absolute_error": (
            round(
                sum(item["absolute_error"] for item in evaluation_pairs)
                / len(evaluation_pairs),
                4,
            )
            if evaluation_pairs
            else None
        ),
        "final_absolute_error": (
            pairs[-1]["absolute_error"]
            if pairs[-1]["included_in_point_error"]
            else None
        ),
        "direction_agreement_rate": (
            round(direction_matches / direction_count, 4)
            if direction_count
            else None
        ),
    }
    per_sentiment_mae = {}
    for sentiment in SENTIMENTS:
        errors = [
            item["sentiment_comparison"][sentiment]["absolute_error"]
            for item in evaluation_pairs
            if item["sentiment_comparison"][sentiment]["absolute_error"]
            is not None
        ]
        per_sentiment_mae[sentiment] = (
            round(sum(errors) / len(errors), 4) if errors else None
        )
    metrics["per_sentiment_mae"] = per_sentiment_mae
    valid_sentiment_maes = [
        value for value in per_sentiment_mae.values() if value is not None
    ]
    metrics["macro_mean_absolute_error"] = (
        round(sum(valid_sentiment_maes) / len(valid_sentiment_maes), 4)
        if valid_sentiment_maes
        else None
    )
    metric_scope: dict[str, Any] = {
        "observation_count": len(evaluation_pairs),
        "aligned_observation_count": len(pairs),
        "calibration_point_count": len(pairs) - len(evaluation_pairs),
        "transition_count": direction_count,
        "mae_interpretation": "探索性差异，不代表模型准确率",
    }

    if len(evaluation_pairs) >= 3:
        simulation_peak_rate = max(
            item["simulation_comment_rate"] for item in evaluation_pairs
        )
        real_peak_rate = max(
            item["real_reference_rate"] for item in evaluation_pairs
        )
        simulation_peak_steps = [
            item["step"]
            for item in evaluation_pairs
            if item["simulation_comment_rate"] == simulation_peak_rate
        ]
        real_peak_steps = [
            item["step"]
            for item in evaluation_pairs
            if item["real_reference_rate"] == real_peak_rate
        ]
        metrics.update(
            {
                "simulation_peak_steps": simulation_peak_steps,
                "real_reference_peak_steps": real_peak_steps,
                "peak_step_difference": min(
                    abs(simulation_step - real_step)
                    for simulation_step in simulation_peak_steps
                    for real_step in real_peak_steps
                ),
            }
        )
        metric_scope["status"] = "multi_stage_exploratory"
        interpretation = (
            f"{COMMENT_BASIS_LABELS[basis]}负面率与人工群体趋势的探索性对照，"
            "不代表模型准确率或个体预测能力。"
        )
    elif len(evaluation_pairs) == 2:
        metric_scope.update(
            {
                "status": "limited_two_stage",
                "suppressed_metrics": ["peak_step_difference", "trend_fit"],
            }
        )
        interpretation = (
            "仅有两个共同观测点：可展示负面率变化并比较一次上升、下降或持平方向；"
            "MAE 和最终差异仅为探索性差异，不代表模型准确率；"
            "不计算峰值轮次差或趋势拟合优度。"
        )
    elif len(evaluation_pairs) == 1 and direction_count:
        metric_scope.update(
            {
                "status": "calibrated_single_forecast",
                "suppressed_metrics": ["peak_step_difference", "trend_fit"],
            }
        )
        interpretation = (
            "除人工初始条件外只有一个预测观测点：可比较从初始条件到该点的变化方向；"
            "单点绝对差仅为探索性差异，不代表模型准确率；不计算峰值轮次差。"
        )
    else:
        metric_scope.update(
            {
                "status": "insufficient_overlap",
                "suppressed_metrics": [
                    "direction_agreement_rate",
                    "peak_step_difference",
                    "trend_fit",
                ],
            }
        )
        interpretation = (
            "仅有一个共同观测点，只能描述该点的探索性差异；"
            "无法判断变化方向，也不计算峰值轮次差或趋势拟合优度。"
        )

    if metric_scope["calibration_point_count"]:
        interpretation += (
            " 人工初始化轮次只作为历史初始条件展示，不计入MAE和峰值指标；"
            "从该初始条件到下一轮的变化方向仍属于仿真结果。"
        )

    return {
        "event_id": simulation_event_id,
        "pairs": pairs,
        "comparison_basis": basis,
        "metrics": metrics,
        "metric_scope": metric_scope,
        "alignment": {
            "method": f"按 {len(pairs)} 个共同事件阶段的顺序对齐",
            "different_period_steps": [
                item["step"] for item in pairs if not item["period_aligned"]
            ],
            "note": "存在日期边界差异时不进行日级插值，分别保留模拟与人工材料的原始时间段。",
        },
        "interpretation": interpretation,
    }
