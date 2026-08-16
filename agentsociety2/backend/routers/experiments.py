"""
实验数据 API。

提供实验基本信息与产出文件查询。新 replay 写入格式为
``run/replay/_schema.json`` + sharded JSONL；实验统计通过
``agentsociety2.storage.ReplayReader`` 读取，不再访问 ``sqlite.db``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agentsociety2.backend.path_security import (
    resolve_artifact_path,
    resolve_experiment_dir,
    resolve_under_root,
    require_safe_segment,
)
from agentsociety2.logger import get_logger
from agentsociety2.storage.replay_metadata import AGENT_PROFILE_DATASET_CAPABILITY
from agentsociety2.storage.replay_reader import ReplayReader

logger = get_logger()

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentInfo(BaseModel):
    """实验信息。"""

    experiment_id: str
    hypothesis_id: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    agent_count: int
    step_count: int


def _get_experiment_path(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
):
    return resolve_experiment_dir(workspace_path, hypothesis_id, experiment_id)


def _list_agent_state_datasets(datasets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "entity_snapshot"
        and "agent_snapshot" in dataset.get("capabilities", [])
        and dataset.get("entity_key")
        and dataset.get("step_key")
    ]
    items.sort(
        key=lambda item: (
            0 if "geo_point" not in item.get("capabilities", []) else 1,
            item["dataset_id"],
        )
    )
    return items


def _get_agent_profile_dataset(
    datasets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidates = [
        dataset
        for dataset in datasets
        if AGENT_PROFILE_DATASET_CAPABILITY in dataset.get("capabilities", [])
        and dataset.get("entity_key")
    ]
    candidates.sort(key=lambda item: item["dataset_id"])
    return candidates[0] if candidates else None


def _get_timeline_dataset(datasets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    agent_datasets = [
        dataset
        for dataset in _list_agent_state_datasets(datasets)
        if dataset.get("step_key") and dataset.get("time_key")
    ]
    if agent_datasets:
        return agent_datasets[0]

    env_datasets = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "env_snapshot"
        and "env_snapshot" in dataset.get("capabilities", [])
        and dataset.get("step_key")
        and dataset.get("time_key")
    ]
    env_datasets.sort(key=lambda item: item["dataset_id"])
    return env_datasets[0] if env_datasets else None


def _read_replay_summary(replay_dir) -> tuple[int, int]:
    """Return ``(agent_count, step_count)`` from current replay JSONL data."""

    reader = ReplayReader(replay_dir)
    try:
        datasets = reader.load_dataset_catalog()
        agent_count = 0
        profile_dataset = _get_agent_profile_dataset(datasets)
        if profile_dataset is not None and profile_dataset.get("entity_key"):
            agent_count = reader.count_distinct(
                profile_dataset, str(profile_dataset["entity_key"])
            )
        else:
            agent_state = _list_agent_state_datasets(datasets)
            if agent_state and agent_state[0].get("entity_key"):
                agent_count = reader.count_distinct(
                    agent_state[0], str(agent_state[0]["entity_key"])
                )

        step_count = 0
        timeline_dataset = _get_timeline_dataset(datasets)
        if timeline_dataset is not None and timeline_dataset.get("step_key"):
            step_count = reader.count_distinct(
                timeline_dataset, str(timeline_dataset["step_key"])
            )

        return agent_count, step_count
    finally:
        reader.close()


@router.get("/{hypothesis_id}/{experiment_id}/info")
async def get_experiment_info(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> ExperimentInfo:
    """
    获取实验基本信息。

    返回指定实验的状态、开始/结束时间、Agent 数量和已执行 step 数。
    """
    # Validate path parameters at the API boundary
    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    exp_path = _get_experiment_path(workspace_path, hypothesis_id, experiment_id)

    if not exp_path.exists():
        raise HTTPException(status_code=404, detail="Experiment not found")

    run_dir = exp_path / "run"
    pid_file = run_dir / "pid.json"
    replay_dir = run_dir / "replay"

    status = "not_started"
    start_time = None
    end_time = None

    if pid_file.exists():
        try:
            pid_data = json.loads(pid_file.read_text(encoding="utf-8"))
            status = pid_data.get("status", "unknown")
            start_time = pid_data.get("start_time")
            end_time = pid_data.get("end_time")
        except Exception as e:
            logger.warning(f"Failed to read pid.json: {e}")

    agent_count = 0
    step_count = 0
    if replay_dir.is_dir() and (replay_dir / "_schema.json").is_file():
        try:
            agent_count, step_count = await asyncio.to_thread(
                _read_replay_summary, replay_dir
            )
        except Exception as e:
            logger.warning(f"Failed to query replay data: {e}")

    return ExperimentInfo(
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        agent_count=agent_count,
        step_count=step_count,
    )


@router.get("/{hypothesis_id}/{experiment_id}/artifacts")
async def list_artifacts(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> List[Dict[str, str]]:
    """列出实验运行过程中生成的 Markdown 产出文件。"""

    # Validate path parameters at the API boundary
    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    exp_path = _get_experiment_path(workspace_path, hypothesis_id, experiment_id)
    artifacts_dir = resolve_under_root(exp_path, "run", "artifacts")

    if not artifacts_dir.is_dir():
        return []

    artifacts = []
    for file_path in sorted(artifacts_dir.glob("*.md")):
        artifacts.append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "type": "ask" if file_path.name.startswith("ask_") else "intervene",
            }
        )

    return artifacts


@router.get("/{hypothesis_id}/{experiment_id}/artifacts/{artifact_name}")
async def get_artifact(
    hypothesis_id: str,
    experiment_id: str,
    artifact_name: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> Dict[str, str]:
    """获取指定 Markdown 产出文件内容。"""

    artifact_path = resolve_artifact_path(
        workspace_path, hypothesis_id, experiment_id, artifact_name
    )
    return {
        "name": artifact_name,
        "content": artifact_path.read_text(encoding="utf-8"),
    }
