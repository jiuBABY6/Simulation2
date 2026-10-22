"""按 event_id 管理历史复现的事件输入、时间线和真实趋势源文件。"""

from __future__ import annotations

import json
from pathlib import Path

if __package__:
    from .runtime_paths import ACTIVE_EVENT_FILE, EVENTS_DIR
else:  # pragma: no cover - 保留直接脚本启动方式
    from runtime_paths import ACTIVE_EVENT_FILE, EVENTS_DIR


def _normalize_event_id(event_id: str) -> str:
    normalized = str(event_id or "").strip()
    if not normalized or Path(normalized).name != normalized:
        raise ValueError("event_id 不合法")
    return normalized


def _load_json_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取JSON文件 {path}：{error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON文件必须是对象：{path}")
    return payload


def get_active_event_id() -> str:
    """读取无参数运行时使用的当前事件编号。"""

    if not ACTIVE_EVENT_FILE.is_file():
        raise FileNotFoundError(
            f"缺少当前事件配置：{ACTIVE_EVENT_FILE}；请使用 --event-id 指定事件"
        )
    payload = _load_json_object(ACTIVE_EVENT_FILE)
    return _normalize_event_id(payload.get("event_id", ""))


def resolve_event_files(event_id: str | None = None) -> dict[str, object]:
    """解析一个事件目录，并校验同一事件的历史复现输入。"""

    normalized = _normalize_event_id(event_id or get_active_event_id())
    events_root = EVENTS_DIR.resolve()
    event_dir = (events_root / normalized).resolve()
    if event_dir.parent != events_root or not event_dir.is_dir():
        raise FileNotFoundError(f"找不到历史事件目录：{normalized}")

    event_file = event_dir / "event_input.json"
    timeline_file = event_dir / "official_response_timeline.json"
    manifest_file = event_dir / "event_manifest.json"
    for label, path in (
        ("事件清单", manifest_file),
        ("事件输入", event_file),
        ("官方时间线", timeline_file),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}不存在：{path}")

    manifest = _load_json_object(manifest_file)
    event_payload = _load_json_object(event_file)
    timeline_payload = _load_json_object(timeline_file)
    if manifest.get("event_id") != normalized:
        raise ValueError(f"事件目录名与 event_manifest.json 的 event_id 不一致：{normalized}")
    if event_payload.get("event_id") != normalized:
        raise ValueError(f"事件目录名与 event_input.json 的 event_id 不一致：{normalized}")
    if timeline_payload.get("event_id") != normalized:
        raise ValueError(
            f"事件目录名与 official_response_timeline.json 的 event_id 不一致：{normalized}"
        )

    # 2026/10/10，修改功能：第一轮人工初始条件和逐轮公众语境均为
    # 历史入口的必需输入；不存在额外的旧回放配置或运行时模式开关。
    initial_opinion_file = event_dir / "initial_opinion.json"
    public_context_file = event_dir / "public_context_timeline.json"
    for label, path in (
        ("第一轮人工初始条件", initial_opinion_file),
        ("逐轮公众语境", public_context_file),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}不存在：{path}")
        payload = _load_json_object(path)
        if payload.get("event_id") != normalized:
            raise ValueError(f"事件目录名与 {path.name} 的 event_id 不一致：{normalized}")

    source_file = event_dir / "real_trend_source.xlsx"
    return {
        "event_id": normalized,
        "event_dir": event_dir,
        "event_file": event_file,
        "timeline_file": timeline_file,
        "initial_opinion_file": initial_opinion_file,
        "public_context_file": public_context_file,
        "real_trend_source": source_file if source_file.is_file() else None,
    }


def list_events() -> list[dict[str, object]]:
    """列出结构完整的历史事件源数据目录。"""

    if not EVENTS_DIR.is_dir():
        return []
    items = []
    for event_dir in EVENTS_DIR.iterdir():
        if not event_dir.is_dir():
            continue
        try:
            resolved = resolve_event_files(event_dir.name)
        except (OSError, ValueError):
            continue
        manifest_file = event_dir / "event_manifest.json"
        manifest = (
            _load_json_object(manifest_file) if manifest_file.is_file() else {}
        )
        items.append(
            {
                "event_id": resolved["event_id"],
                "title": manifest.get("title", resolved["event_id"]),
                "event_dir": str(resolved["event_dir"]),
                "has_initial_opinion": True,
                "has_public_context": True,
                "has_real_trend_source": resolved["real_trend_source"] is not None,
            }
        )
    return sorted(items, key=lambda item: str(item["event_id"]))
