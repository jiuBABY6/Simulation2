"""历史复现专用：按 event_id 只读管理人工真实趋势。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from visualization.config import ACTIVE_HISTORICAL_EVENT_PATH, REAL_DATA_DIR
from visualization.shared.artifact_io import load_json_object
from visualization.shared.event_resources import (
    normalize_event_resource_id,
    resolve_event_json_path,
)


def normalize_event_id(event_id: str) -> str:
    """兼容旧调用名称，统一使用共享资源编号校验。"""

    return normalize_event_resource_id(event_id)


def real_trend_path(event_id: str) -> Path:
    return resolve_event_json_path(REAL_DATA_DIR, event_id)


def load_real_trend(event_id: str) -> dict[str, Any]:
    normalized = normalize_event_id(event_id)
    path = real_trend_path(normalized)
    if not path.is_file():
        raise FileNotFoundError(f"找不到事件 {normalized} 的真实趋势：{path}")
    payload = load_json_object(path)
    if payload.get("event_id") != normalized:
        raise ValueError(f"真实趋势文件名与 event_id 不一致：{path}")
    return payload
def list_real_trends() -> list[dict[str, Any]]:
    if not REAL_DATA_DIR.is_dir():
        return []
    items = []
    for path in REAL_DATA_DIR.glob("*.json"):
        try:
            payload = load_real_trend(path.stem)
        except (OSError, ValueError):
            continue
        items.append(
            {
                "event_id": payload["event_id"],
                "stage_count": payload.get(
                    "stage_count", len(payload.get("periods", []))
                ),
                "source": payload.get("source", {}),
            }
        )
    return sorted(items, key=lambda item: str(item["event_id"]))


def get_active_event_id() -> str:
    if not ACTIVE_HISTORICAL_EVENT_PATH.is_file():
        raise FileNotFoundError(
            f"缺少当前历史事件配置：{ACTIVE_HISTORICAL_EVENT_PATH}"
        )
    payload = load_json_object(
        ACTIVE_HISTORICAL_EVENT_PATH,
        encoding="utf-8-sig",
    )
    return normalize_event_id(payload.get("event_id", ""))
