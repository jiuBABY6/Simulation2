"""共享网络层的数据读取与场景解析。

这里只负责验证和读取实验快照/JSONL，不计算展示指标，避免文件布局知识
泄漏到网络构图与传播链模块。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from visualization.shared.experiment_adapter import ExperimentAdapter


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 文件不是对象：{path}")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"JSONL 第 {line_number} 行不是对象：{path}")
        records.append(record)
    return records


def load_events(
    adapter: ExperimentAdapter, scenario_id: str
) -> list[dict[str, Any]]:
    return load_jsonl(
        adapter.state_file(scenario_id, "propagation_history.jsonl")
    )


def load_decisions(
    adapter: ExperimentAdapter, scenario_id: str
) -> list[dict[str, Any]]:
    return load_jsonl(
        adapter.state_file(scenario_id, "decision_history.jsonl")
    )


def resolve_scenario(
    adapter: ExperimentAdapter, scenario_id: str | None
) -> tuple[str, str]:
    """返回经过实验适配器验证的场景编号和显示名称。"""

    requested = str(scenario_id or "").strip()
    scenarios = adapter.scenarios()
    if not requested and scenarios:
        item = scenarios[0]
        return str(item["scenario_id"]), str(item["scenario_name"])
    for item in scenarios:
        if item["scenario_id"] == requested:
            return requested, str(item["scenario_name"])
    raise ValueError(f"当前实验不存在场景：{requested}")
