"""只读索引五策略实验与历史复现实验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from visualization.config import EXPERIMENTS_DIR, REAL_DATA_DIR
from visualization.shared.artifact_io import load_json_object
from visualization.shared.event_resources import has_event_json_resource


STRATEGY_MODE = "strategy_comparison"
HISTORICAL_MODE = "historical_replay"
VALID_MODES = {STRATEGY_MODE, HISTORICAL_MODE}


def resolve_experiment_dir(experiment_id: str) -> Path:
    """把实验编号解析为 experiments 下的直接子目录，拒绝路径穿越。"""

    normalized = str(experiment_id or "").strip()
    if not normalized or Path(normalized).name != normalized:
        raise ValueError("实验编号不合法")
    root = EXPERIMENTS_DIR.resolve()
    candidate = (root / normalized).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise FileNotFoundError(f"找不到实验目录：{normalized}")
    return candidate


def _detect_result(experiment_dir: Path) -> tuple[str, Path] | None:
    strategy_result = experiment_dir / "experiment_result.json"
    historical_result = experiment_dir / "historical_replay_result.json"
    if strategy_result.is_file():
        return STRATEGY_MODE, strategy_result
    if historical_result.is_file():
        return HISTORICAL_MODE, historical_result
    return None


def _strategy_step_count(result: dict[str, Any]) -> int:
    return max(
        (
            len(item.get("rounds", []))
            for item in result.get("strategy_results", [])
            if isinstance(item, dict)
        ),
        default=0,
    )


def _capabilities(
    experiment_dir: Path, mode: str, result: dict[str, Any]
) -> dict[str, bool]:
    if mode == HISTORICAL_MODE:
        state_dir = experiment_dir / "historical_replay" / "state"
        network_file = state_dir / "social_network_snapshot.json"
        propagation_file = state_dir / "propagation_history.jsonl"
        decision_file = state_dir / "decision_history.jsonl"
    else:
        network_file = experiment_dir / "social_network_snapshot.json"
        strategy_results = [
            item
            for item in result.get("strategy_results", [])
            if isinstance(item, dict)
        ]
        trace_files = [
            (
                experiment_dir
                / str(item.get("strategy", ""))
                / "state"
                / "propagation_history.jsonl",
                experiment_dir
                / str(item.get("strategy", ""))
                / "state"
                / "decision_history.jsonl",
            )
            for item in strategy_results
            if str(item.get("strategy", "")).strip()
        ]
    real_trend_compatible = (
        mode == HISTORICAL_MODE
        and has_event_json_resource(REAL_DATA_DIR, result.get("event_id"))
    )
    return {
        "network": network_file.is_file(),
        "comment_trace": (
            propagation_file.is_file() and decision_file.is_file()
            if mode == HISTORICAL_MODE
            else bool(trace_files)
            and all(
                propagation.is_file() and decision.is_file()
                for propagation, decision in trace_files
            )
        ),
        "real_trend_comparison": real_trend_compatible,
    }


def describe_experiment(experiment_id: str) -> dict[str, Any]:
    experiment_dir = resolve_experiment_dir(experiment_id)
    detected = _detect_result(experiment_dir)
    if detected is None:
        raise ValueError(f"无法识别实验类型：{experiment_id}")
    mode, result_path = detected
    result = load_json_object(result_path)
    if mode == HISTORICAL_MODE:
        step_count = int(result.get("step_count") or len(result.get("rounds", [])))
        scenario_count = 1
    else:
        step_count = _strategy_step_count(result)
        scenario_count = len(
            [
                item
                for item in result.get("strategy_results", [])
                if isinstance(item, dict)
            ]
        )
    return {
        "experiment_id": str(result.get("experiment_id") or experiment_dir.name),
        "event_id": result.get("event_id"),
        "mode": mode,
        "mode_label": (
            "回应方案对照推演"
            if mode == STRATEGY_MODE
            else "历史数据复现"
        ),
        "status": result.get("status"),
        "step_count": step_count,
        "scenario_count": scenario_count,
        "modified_at": result_path.stat().st_mtime,
        "capabilities": _capabilities(experiment_dir, mode, result),
    }


def list_experiments(
    mode: str | None = None, *, completed_only: bool = True
) -> list[dict[str, Any]]:
    """列出可视化能够识别的实验，默认隐藏失败和未完成批次。"""

    if mode and mode not in VALID_MODES:
        raise ValueError(f"未知实验模式：{mode}")
    if not EXPERIMENTS_DIR.is_dir():
        return []
    experiments = []
    for experiment_dir in EXPERIMENTS_DIR.iterdir():
        if not experiment_dir.is_dir() or _detect_result(experiment_dir) is None:
            continue
        try:
            item = describe_experiment(experiment_dir.name)
        except (OSError, ValueError):
            continue
        if mode and item["mode"] != mode:
            continue
        if completed_only and item.get("status") != "completed":
            continue
        experiments.append(item)
    return sorted(
        experiments, key=lambda item: float(item["modified_at"]), reverse=True
    )
