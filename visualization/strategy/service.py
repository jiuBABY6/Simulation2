"""回应方案对照实验专用的只读展示服务。"""

from __future__ import annotations

from typing import Any

from visualization.shared.artifact_io import load_jsonl_objects
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


def _raw_metrics_by_step(adapter, scenario_id: str) -> dict[int, dict]:
    """读取场景原始指标，为旧批次补齐后来新增的展示字段。

    2026/10/16，新增功能：新批次会把诊断分布写入实验汇总；旧批次
    只在 ``metrics_history.jsonl`` 中保存。兼容读取使历史实验无需重跑，
    同时不修改任何实验文件。
    """

    path = adapter.state_file(scenario_id, "metrics_history.jsonl")
    if not path.is_file():
        return {}
    indexed = {}
    for record in load_jsonl_objects(path):
        if (
            record.get("event_id") != adapter.event_id
            or record.get("is_example")
        ):
            continue
        step = record.get("step")
        if isinstance(step, int) and step >= 1:
            indexed[step] = record
    return indexed


def _distribution(item: dict, raw_metrics: dict, field_name: str) -> dict:
    """优先返回实验汇总字段，缺失时回退到只读原始指标。"""

    value = item.get(field_name)
    if isinstance(value, dict) and value:
        return dict(value)
    fallback = raw_metrics.get(field_name, {})
    return dict(fallback) if isinstance(fallback, dict) else {}


def load_dashboard(experiment_id: str) -> dict[str, Any]:
    """整理回应方案对比页需要的数据，不参与仿真计算。"""

    adapter = get_experiment_adapter(experiment_id)
    if adapter.mode != STRATEGY_MODE:
        raise ValueError("所选批次不是回应方案对照实验")

    strategies = []
    for scenario in adapter.scenarios():
        scenario_id = str(scenario["scenario_id"])
        result = adapter.scenario_result(scenario_id)
        official_responses = _official_responses(result)
        raw_by_step = _raw_metrics_by_step(adapter, scenario_id)
        rounds = []
        for item in adapter.rounds(scenario_id):
            raw_metrics = raw_by_step.get(item.get("step"), {})
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
                    # 2026/10/16，新增功能：展示沉默、原创、转发
                    # 和表达去重率，便于判断行为空间是否真正生效。
                    "agent_action_distribution": dict(
                        item.get("agent_action_distribution", {})
                    ),
                    "agent_expression_distribution": _distribution(
                        item,
                        raw_metrics,
                        "agent_expression_distribution",
                    ),
                    # 2026/10/16，新增功能：补齐与历史复现一致的
                    # Agent内部情绪、实际表达情绪和官方态度逐轮数据。
                    "agent_emotion_distribution": _distribution(
                        item,
                        raw_metrics,
                        "agent_emotion_distribution",
                    ),
                    "official_attitude_distribution": _distribution(
                        item,
                        raw_metrics,
                        "official_attitude_distribution",
                    ),
                    "official_attitude_diagnostics": _distribution(
                        item,
                        raw_metrics,
                        "official_attitude_diagnostics",
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
