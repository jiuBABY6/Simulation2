"""只读加载历史趋势复现实验结果。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import EXPERIMENTS_DIR


COMMENT_EMOTIONS = ("positive", "neutral", "negative")


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
    return _repair_mojibake(json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(_repair_mojibake(json.loads(line)))
    return records


# 2026/09/02 历史趋势可视化，新增功能：只列出已完成的历史复现批次。
def list_experiments() -> list[dict[str, object]]:
    """返回可展示的历史复现实验，保持实验目录完全只读。"""

    experiments = []
    if not EXPERIMENTS_DIR.exists():
        return experiments
    for result_path in EXPERIMENTS_DIR.glob("*/historical_replay_result.json"):
        try:
            result = _read_json(result_path)
        except (OSError, json.JSONDecodeError):
            continue
        if result.get("mode") != "historical_replay":
            continue
        experiments.append(
            {
                "experiment_id": result.get("experiment_id", result_path.parent.name),
                "event_id": result.get("event_id"),
                "status": result.get("status"),
                "step_count": result.get("step_count"),
                "modified_at": result_path.stat().st_mtime,
            }
        )
    return sorted(experiments, key=lambda item: item["modified_at"], reverse=True)


def _find_result_path(experiment_id: str) -> Path:
    candidate = (EXPERIMENTS_DIR / experiment_id / "historical_replay_result.json").resolve()
    experiments_root = EXPERIMENTS_DIR.resolve()
    if candidate.parent.parent != experiments_root:
        raise ValueError("实验编号不合法")
    if not candidate.is_file():
        raise FileNotFoundError(f"找不到历史复现结果：{experiment_id}")
    return candidate


def _distribution_rate(
    metrics: dict[str, Any], distribution_name: str, label: str
) -> float | None:
    distribution = metrics.get(distribution_name, {}).get("distribution", {})
    item = distribution.get(label, {})
    return item.get("rate")


# 2026/09/02 历史趋势可视化，新增功能：按评论自身情绪标签统计评论池分布。
def _calculate_comment_distribution(comments: list[dict[str, Any]]) -> dict[str, Any]:
    """计算有效评论的正面、中性和负面比例，并保留未分类数量。"""

    counts = {
        emotion: sum(1 for item in comments if item.get("emotion") == emotion)
        for emotion in COMMENT_EMOTIONS
    }
    classified_count = sum(counts.values())
    return {
        "comment_count": len(comments),
        "classified_count": classified_count,
        "unclassified_count": len(comments) - classified_count,
        "distribution": {
            emotion: {
                "count": counts[emotion],
                "rate": (
                    round(counts[emotion] / classified_count, 6)
                    if classified_count
                    else None
                ),
            }
            for emotion in COMMENT_EMOTIONS
        },
    }


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
    initial_comments = (
        _read_json(initial_pool_path).get("comments", [])
        if initial_pool_path.is_file()
        else []
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
    updates_by_step = {
        item.get("step"): item for item in result.get("official_updates", [])
    }

    rounds = []
    cumulative_comments = list(initial_comments)
    for round_item in result.get("rounds", []):
        step = round_item.get("step")
        metrics = metrics_by_step.get(step, {})
        policy = round_item.get("policy_metrics", {})
        current_comments = (
            initial_comments if step == 1 else incremental_by_step.get(step, [])
        )
        if step != 1:
            cumulative_comments.extend(current_comments)
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
                "negative_rate": policy.get("negative_rate"),
                "current_comment_distribution": _calculate_comment_distribution(
                    current_comments
                ),
                "cumulative_comment_distribution": _calculate_comment_distribution(
                    cumulative_comments
                ),
                "accept_rate": policy.get("accept_rate"),
                "wait_rate": _distribution_rate(
                    metrics, "official_attitude_distribution", "wait"
                ),
                "question_rate": policy.get("question_rate"),
                "applicable_agent_count": policy.get(
                    "official_attitude_applicable_count", 0
                ),
                "global_trend": policy.get("global_trend"),
                "official_update": updates_by_step.get(step),
                "comment_generation": round_item.get("comment_generation"),
            }
        )

    return {
        "experiment_id": result.get("experiment_id"),
        "event_id": result.get("event_id"),
        "status": result.get("status"),
        "step_count": result.get("step_count"),
        "official_update_count": result.get("official_update_count"),
        "rounds": rounds,
        "official_updates": result.get("official_updates", []),
        "final_metrics": result.get("final_metrics", {}),
        "comment_quality": result.get("comment_quality", {}),
    }
