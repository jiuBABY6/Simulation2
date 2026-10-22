"""只读加载历史趋势复现实验结果。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from visualization.historical.opinion_metrics import (
    calculate_active_comment_distribution,
    calculate_comment_distribution,
)
from visualization.shared.experiment_catalog import resolve_experiment_dir
from visualization.shared.artifact_io import (
    load_json_object,
    load_jsonl_objects,
)


def _repair_mojibake(value: Any) -> Any:
    """修复旧批次中可能出现的 UTF-8/GBK 显示错位，不回写源文件。"""

    if isinstance(value, dict):
        return {key: _repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_repair_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("gb18030").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    suspicious = ("澶", "鎯", "璇", "鍙", "缁", "锛", "銆")
    if sum(marker in value for marker in suspicious) > sum(
        marker in repaired for marker in suspicious
    ):
        return repaired
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return load_json_object(path, transform=_repair_mojibake)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return load_jsonl_objects(path, transform=_repair_mojibake)


def _find_result_path(experiment_id: str) -> Path:
    candidate = (
        resolve_experiment_dir(experiment_id)
        / "historical_replay_result.json"
    )
    if not candidate.is_file():
        raise FileNotFoundError(f"找不到历史复现结果：{experiment_id}")
    return candidate


def _distribution_rate(
    metrics: dict[str, Any], distribution_name: str, label: str
) -> float | None:
    distribution = metrics.get(distribution_name, {}).get("distribution", {})
    item = distribution.get(label, {})
    return item.get("rate")


def _load_agent_expressions_by_step(
    decision_path: Path,
) -> dict[int, list[dict[str, Any]]]:
    """按轮次读取 Agent 最终实际发表的评论。

    生成评论池只是 Agent 可选择的信息环境；只有成功决策中
    ``will_comment=true`` 且具有 ``selected_comment`` 的记录，才属于
    可与真实人类评论比较的公开表达。
    """

    expressions: dict[int, list[dict[str, Any]]] = {}
    for record in _read_jsonl(decision_path):
        if record.get("status") != "success":
            continue
        step = record.get("step")
        decision = record.get("decision", {})
        comment = decision.get("selected_comment")
        if (
            isinstance(step, int)
            and decision.get("will_comment") is True
            and isinstance(comment, dict)
        ):
            expressions.setdefault(step, []).append(comment)
    return expressions


# 2026/09/02 历史趋势可视化，新增功能：按评论自身情绪标签统计评论池分布。
# 2026/09/02 历史趋势可视化，新增功能：合并轮次指标、情绪分布和官方信息节点。
def load_experiment(experiment_id: str) -> dict[str, Any]:
    """读取一个历史复现批次并整理为前端可直接展示的结构。"""

    result_path = _find_result_path(experiment_id)
    result = _read_json(result_path)
    metrics_path = (
        result_path.parent
        / "historical_replay"
        / "state"
        / "metrics_history.jsonl"
    )
    metrics_by_step = {
        item.get("step"): item for item in _read_jsonl(metrics_path)
    }
    initial_pool_path = result_path.parent / "comment_pool.json"
    # 2026/10/8，新增功能：历史页面读取批次快照中的人工初始条件标记，旧批次保持为空。
    initial_pool_payload = (
        _read_json(initial_pool_path) if initial_pool_path.is_file() else {}
    )
    initial_comments = initial_pool_payload.get("comments", [])
    initialization = result.get("initialization") or initial_pool_payload.get(
        "initialization"
    )
    calibrated_step = (
        initialization.get("calibrated_step")
        if isinstance(initialization, dict)
        else None
    )
    incremental_path = (
        result_path.parent
        / "historical_replay"
        / "state"
        / "incremental_comment_history.jsonl"
    )
    incremental_by_step = {
        item.get("step"): item.get("comments", [])
        for item in _read_jsonl(incremental_path)
    }
    decision_path = (
        result_path.parent
        / "historical_replay"
        / "state"
        / "decision_history.jsonl"
    )
    expressions_by_step = _load_agent_expressions_by_step(decision_path)
    updates_by_step = {
        item.get("step"): item for item in result.get("official_updates", [])
    }

    rounds = []
    cumulative_comments = list(initial_comments)
    round_comment_groups: list[list[dict[str, Any]]] = []
    simulation_options = result.get("simulation_options", {})
    active_opinion_window = simulation_options.get(
        "active_opinion_window", 2
    )
    if (
        isinstance(active_opinion_window, bool)
        or not isinstance(active_opinion_window, int)
        or active_opinion_window < 1
    ):
        active_opinion_window = 2
    for round_item in result.get("rounds", []):
        step = round_item.get("step")
        metrics = metrics_by_step.get(step, {})
        policy = round_item.get("policy_metrics", {})
        agent_expressions = expressions_by_step.get(step, [])
        agent_expression_distribution = calculate_comment_distribution(
            agent_expressions
        )
        current_comments = (
            initial_comments if step == 1 else incremental_by_step.get(step, [])
        )
        if step != 1:
            cumulative_comments.extend(current_comments)
        round_comment_groups.append(list(current_comments))
        rounds.append(
            {
                "step": step,
                "period": round_item.get("period", ""),
                "phase": round_item.get("phase", ""),
                "positive_rate": _distribution_rate(
                    metrics, "agent_emotion_distribution", "positive"
                ),
                "neutral_rate": _distribution_rate(
                    metrics, "agent_emotion_distribution", "neutral"
                ),
                # Agent内部状态图继续使用内部三分类，避免把“表达”混入
                # “心里怎么想”；历史主对照改由下方实际表达分布提供。
                "negative_rate": _distribution_rate(
                    metrics, "agent_emotion_distribution", "negative"
                ),
                "expression_negative_rate": policy.get("negative_rate"),
                # 2026/10/12，历史复现主对照口径：只统计 Agent 最终
                # 实际发表的评论；候选评论池分布继续作为环境诊断项。
                "agent_expression_distribution": (
                    agent_expression_distribution
                ),
                "agent_expression_summary": metrics.get(
                    "agent_expression_distribution",
                    {
                        "expression_count": len(agent_expressions),
                        "classified_expression_count": (
                            agent_expression_distribution["classified_count"]
                        ),
                    },
                ),
                "current_comment_distribution": calculate_comment_distribution(
                    current_comments
                ),
                "cumulative_comment_distribution": calculate_comment_distribution(
                    cumulative_comments
                ),
                # 2026/10/9，新增功能：最近若干轮滚动分布近似当前活跃舆论场。
                "active_comment_distribution": calculate_active_comment_distribution(
                    round_comment_groups,
                    active_opinion_window,
                ),
                "accept_rate": policy.get("accept_rate"),
                "wait_rate": _distribution_rate(
                    metrics, "official_attitude_distribution", "wait"
                ),
                "question_rate": policy.get("question_rate"),
                "applicable_agent_count": policy.get(
                    "official_attitude_applicable_count", 0
                ),
                # 2026/10/14，新增功能：直接透传规则层群体趋同诊断；旧实验
                # 没有该字段时保持空对象，页面仍可正常查看。
                "official_attitude_diagnostics": metrics.get(
                    "official_attitude_diagnostics",
                    {},
                ),
                "global_trend": policy.get("global_trend"),
                "official_update": updates_by_step.get(step),
                "comment_generation": round_item.get("comment_generation"),
                "is_calibration_point": (
                    round_item.get("is_calibration_point", False)
                    or step == calibrated_step
                ),
                # 2026/10/10，修改功能：主线历史回放重新把逐轮公众语境
                # 作为当轮提示输入展示，不再把它标记为停用的旧字段。
                "public_context": round_item.get("public_context"),
            }
        )

    return {
        "experiment_id": result.get("experiment_id"),
        "event_id": result.get("event_id"),
        "status": result.get("status"),
        "step_count": result.get("step_count"),
        "official_update_count": result.get("official_update_count"),
        "initialization": initialization,
        "simulation_options": simulation_options,
        "public_context_enabled": result.get("public_context_enabled", False),
        "rounds": rounds,
        "official_updates": result.get("official_updates", []),
        "final_metrics": result.get("final_metrics", {}),
        "comment_quality": result.get("comment_quality", {}),
        "run_manifest": result.get("run_manifest", {}),
    }
