"""历史复现专用：按 event_id 只读管理人工真实趋势。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from visualization.config import ACTIVE_HISTORICAL_EVENT_PATH, REAL_DATA_DIR


def normalize_event_id(event_id: str) -> str:
    normalized = str(event_id or "").strip()
    if not normalized or Path(normalized).name != normalized:
        raise ValueError("event_id 不合法")
    return normalized


def real_trend_path(event_id: str) -> Path:
    normalized = normalize_event_id(event_id)
    root = REAL_DATA_DIR.resolve()
    candidate = (root / f"{normalized}.json").resolve()
    if candidate.parent != root:
        raise ValueError("event_id 不合法")
    return candidate


def load_real_trend(event_id: str) -> dict[str, Any]:
    normalized = normalize_event_id(event_id)
    path = real_trend_path(normalized)
    if not path.is_file():
        raise FileNotFoundError(f"找不到事件 {normalized} 的真实趋势：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"真实趋势JSON不是对象：{path}")
    if payload.get("event_id") != normalized:
        raise ValueError(f"真实趋势文件名与 event_id 不一致：{path}")
    return payload


def has_real_trend(event_id: str | None) -> bool:
    try:
        load_real_trend(str(event_id or ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return True


def list_real_trends() -> list[dict[str, Any]]:
    if not REAL_DATA_DIR.is_dir():
        return []
    items = []
    for path in REAL_DATA_DIR.glob("*.json"):
        try:
            payload = load_real_trend(path.stem)
        except (OSError, ValueError, json.JSONDecodeError):
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
    payload = json.loads(
        ACTIVE_HISTORICAL_EVENT_PATH.read_text(encoding="utf-8-sig")
    )
    if not isinstance(payload, dict):
        raise ValueError("active_event.json 必须是JSON对象")
    return normalize_event_id(payload.get("event_id", ""))
