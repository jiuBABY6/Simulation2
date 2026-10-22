"""可视化层统一的只读 JSON/JSONL 访问。

历史、策略与网络页面只消费实验产物。集中类型校验和错误信息后，各页面
无需重复维护文件解析逻辑，也不会意外修改仿真状态。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


PayloadTransform = Callable[[Any], Any]


def load_json_object(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    transform: PayloadTransform | None = None,
) -> dict[str, Any]:
    """读取 JSON 对象并统一校验顶层类型。"""

    artifact_path = Path(path)
    payload: Any = json.loads(artifact_path.read_text(encoding=encoding))
    if transform is not None:
        payload = transform(payload)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 文件不是对象：{artifact_path}")
    return payload


def load_jsonl_objects(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    transform: PayloadTransform | None = None,
) -> list[dict[str, Any]]:
    """读取 JSONL 对象列表，错误信息包含具体行号。"""

    artifact_path = Path(path)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        artifact_path.read_text(encoding=encoding).splitlines(), start=1
    ):
        if not line.strip():
            continue
        payload: Any = json.loads(line)
        if transform is not None:
            payload = transform(payload)
        if not isinstance(payload, dict):
            raise ValueError(
                f"JSONL 第 {line_number} 行不是对象：{artifact_path}"
            )
        records.append(payload)
    return records
