"""读取并汇总单轮仿真结果。

这里仅负责把状态文件转换成实验层需要的稳定结构，不包含五策略或历史复现
专属的编排规则。
"""

from __future__ import annotations

from pathlib import Path

from evaluation.propagation_metrics import (
    calculate_propagation_metrics,
    load_propagation_events,
)
from infrastructure.json_storage import read_jsonl


def extract_policy_metrics(
    round_metrics: dict,
    negative_rate_basis: str = "agent_internal",
) -> dict:
    """提取稳定的策略指标，并明确负面率的观测对象。"""

    try:
        attitude_summary = round_metrics["official_attitude_distribution"]
        attitude = attitude_summary["distribution"]
        if negative_rate_basis == "agent_internal":
            negative_summary = round_metrics["agent_negative_emotion"]
            negative_rate = negative_summary["negative_rate"]
            negative_count = negative_summary["negative_count"]
            negative_denominator = negative_summary["agent_count"]
            expression_summary = round_metrics.get(
                "agent_expression_distribution", {}
            )
        elif negative_rate_basis == "agent_expression":
            expression_summary = round_metrics[
                "agent_expression_distribution"
            ]
            negative_item = expression_summary["distribution"]["negative"]
            negative_rate = negative_item["rate"]
            negative_count = negative_item["count"]
            negative_denominator = expression_summary[
                "classified_expression_count"
            ]
        else:
            raise ValueError(
                "negative_rate_basis 只能是 agent_internal 或 "
                "agent_expression。"
            )
        return {
            "negative_rate": negative_rate,
            "negative_count": negative_count,
            "negative_denominator": negative_denominator,
            "negative_rate_basis": negative_rate_basis,
            "expression_count": expression_summary.get("expression_count"),
            "silent_agent_count": expression_summary.get(
                "silent_agent_count"
            ),
            "question_rate": attitude["question"]["rate"],
            "accept_rate": attitude["accept"]["rate"],
            "official_attitude_applicable_count": attitude_summary.get(
                "applicable_agent_count",
                attitude_summary.get("agent_count", 0),
            ),
            "global_trend": round_metrics["global_trend"][
                "trend_direction"
            ],
        }
    except (KeyError, TypeError) as error:
        raise ValueError("指标结果缺少实验策略所需字段。") from error


def load_step_metrics(metrics_file: str | Path, event_id: str, step: int) -> dict:
    """读取指定事件和时间步的最后一条正式指标。"""

    matches = [
        record
        for record in read_jsonl(metrics_file)
        if record.get("event_id") == event_id
        and record.get("step") == step
        and not record.get("is_example")
    ]
    if not matches:
        raise ValueError(f"找不到事件 {event_id} 第 {step} 轮的指标。")
    return matches[-1]


def load_step_comment_quality(
    incremental_file: str | Path,
    event_id: str,
    step: int,
) -> dict:
    """读取指定轮次的评论生成质量摘要。"""

    matches = [
        record
        for record in read_jsonl(incremental_file)
        if record.get("event_id") == event_id and record.get("step") == step
    ]
    if not matches:
        raise ValueError(f"找不到事件 {event_id} 第 {step} 轮的增量评论。")
    record = matches[-1]
    fallback_count = record.get("fallback_count", 0)
    history_fallback_count = record.get(
        "history_fallback_count", fallback_count
    )
    return {
        "step": step,
        "generation_mode": record.get(
            "generation_mode", "llm_incremental"
        ),
        "quality_status": record.get("quality_status", "normal"),
        "comment_count": record.get("comment_count", 0),
        "llm_comment_count": record.get(
            "llm_comment_count",
            record.get("comment_count", 0) - fallback_count,
        ),
        "history_fallback_count": history_fallback_count,
        "emergency_fallback_count": record.get(
            "emergency_fallback_count", 0
        ),
        "fallback_count": fallback_count,
        "generation_attempts": record.get("generation_attempts", 0),
        "initial_request_count": record.get("initial_request_count", 0),
        "refill_request_count": record.get("refill_request_count", 0),
        "rescue_request_count": record.get("rescue_request_count", 0),
        "generation_wave_count": record.get("generation_wave_count", 0),
        "quality_target_count": record.get("quality_target_count", 0),
        "model_returned_comment_count": record.get(
            "model_returned_comment_count", 0
        ),
        "rejection_counts": record.get("rejection_counts", {}),
        "validation_errors": record.get("validation_errors", []),
        "emotion_coverage": record.get(
            "emotion_coverage", {"status": "not_required"}
        ),
    }


def summarize_comment_quality(quality_records: list[dict]) -> dict:
    """汇总一个场景全部轮次的评论生成质量。"""

    statuses = {record["quality_status"] for record in quality_records}
    if "emergency" in statuses:
        quality_status = "emergency"
    elif "degraded" in statuses:
        quality_status = "degraded"
    else:
        quality_status = "normal"
    coverage_statuses = {
        record.get("emotion_coverage", {}).get("status", "not_required")
        for record in quality_records
    }
    if "incomplete" in coverage_statuses:
        emotion_coverage_status = "incomplete"
    elif "complete" in coverage_statuses:
        emotion_coverage_status = "complete"
    else:
        emotion_coverage_status = "not_required"
    return {
        "quality_status": quality_status,
        "generation_modes": sorted(
            {
                record.get("generation_mode", "llm_incremental")
                for record in quality_records
            }
        ),
        "llm_comment_count": sum(
            record["llm_comment_count"] for record in quality_records
        ),
        "history_fallback_count": sum(
            record["history_fallback_count"] for record in quality_records
        ),
        "emergency_fallback_count": sum(
            record["emergency_fallback_count"] for record in quality_records
        ),
        "fallback_count": sum(
            record["fallback_count"] for record in quality_records
        ),
        "generation_attempts": sum(
            record.get("generation_attempts", 0)
            for record in quality_records
        ),
        "initial_request_count": sum(
            record.get("initial_request_count", 0)
            for record in quality_records
        ),
        "refill_request_count": sum(
            record.get("refill_request_count", 0)
            for record in quality_records
        ),
        "rescue_request_count": sum(
            record.get("rescue_request_count", 0)
            for record in quality_records
        ),
        "warning_steps": [
            record["step"]
            for record in quality_records
            if record["quality_status"] != "normal"
        ],
        "emotion_coverage_status": emotion_coverage_status,
        "emotion_coverage_warning_steps": [
            record["step"]
            for record in quality_records
            if record.get("emotion_coverage", {}).get("status")
            == "incomplete"
        ],
    }


def load_round_result(
    state_dir: str | Path,
    event_id: str,
    step: int,
    negative_rate_basis: str = "agent_internal",
) -> tuple[dict, dict | None]:
    """读取一轮指标，并在增量轮次附加评论质量。"""

    state_path = Path(state_dir)
    round_metrics = load_step_metrics(
        state_path / "metrics_history.jsonl", event_id, step
    )
    round_result = {
        "step": step,
        "policy_metrics": extract_policy_metrics(
            round_metrics, negative_rate_basis=negative_rate_basis
        ),
        "propagation_metrics": round_metrics.get("propagation_metrics", {}),
        # 2026/10/16，新增功能：应用层原样传递行为与实际
        # 表达指标，可视化层只展示，不从决策历史重复计算。
        "agent_action_distribution": round_metrics.get(
            "agent_action_distribution",
            {},
        ),
        "agent_expression_distribution": round_metrics.get(
            "agent_expression_distribution",
            {},
        ),
        # 2026/10/16，新增功能：策略可视化直接展示三组逐轮诊断数据。
        # 应用层只传递指标计算结果，不在前端按决策记录二次推导。
        "agent_emotion_distribution": round_metrics.get(
            "agent_emotion_distribution",
            {},
        ),
        "official_attitude_distribution": round_metrics.get(
            "official_attitude_distribution",
            {},
        ),
        "official_attitude_diagnostics": round_metrics.get(
            "official_attitude_diagnostics",
            {},
        ),
        # 邻居曝光诊断用于核对社交网络是否实际向Agent提供了邻居表达。
        "neighbor_exposure_diagnostics": round_metrics.get(
            "neighbor_exposure_diagnostics",
            {},
        ),
        "strategy_state_diagnostics": round_metrics.get(
            "strategy_state_diagnostics",
            {},
        ),
    }
    comment_quality = None
    if step > 1:
        comment_quality = load_step_comment_quality(
            state_path / "incremental_comment_history.jsonl",
            event_id,
            step,
        )
        round_result["comment_generation"] = comment_quality
    return round_result, comment_quality


def calculate_scenario_propagation_summary(
    state_dir: str | Path, event_id: str
) -> dict:
    """按实际参与 Agent 数汇总场景传播指标。"""

    state_path = Path(state_dir)
    decision_records = read_jsonl(state_path / "decision_history.jsonl")
    agent_ids = {
        record.get("agent_id")
        for record in decision_records
        if record.get("event_id") == event_id and record.get("agent_id")
    }
    events = load_propagation_events(
        state_path / "propagation_history.jsonl", event_id
    )
    return calculate_propagation_metrics(events, len(agent_ids))
