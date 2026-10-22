"""场景状态目录的应用层编排。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from simulation.state_manager import (
    initialize_simulation_state,
    initialize_state_from_snapshot,
)


def prepare_scenario_state(
    experiment_dir: str | Path,
    scenario_name: str,
    event_id: str,
    baseline_state_dir: str | Path | None = None,
    initial_state_context: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    """创建一个隔离的场景状态目录。

    保留原有“不覆盖已有场景”的安全语义；调用方只负责提供输入，不需要
    了解状态文件的具体组成。
    """

    scenario_dir = Path(experiment_dir) / scenario_name
    state_dir = scenario_dir / "state"
    if scenario_dir.exists():
        raise FileExistsError(f"实验策略目录已经存在：{scenario_dir}")

    if baseline_state_dir is None:
        initial_event_input: dict[str, Any] = {"event_id": event_id}
        if initial_state_context is not None:
            if not isinstance(initial_state_context, Mapping):
                raise ValueError("initial_state_context 必须是 JSON 对象。")
            initial_event_input.update(dict(initial_state_context))
        initialize_simulation_state(
            state_dir=state_dir,
            event_input=initial_event_input,
        )
    else:
        initialize_state_from_snapshot(
            source_state_dir=baseline_state_dir,
            state_dir=state_dir,
            event_id=event_id,
        )
    return scenario_dir, state_dir

