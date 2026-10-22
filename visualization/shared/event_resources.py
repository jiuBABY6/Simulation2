"""按事件编号定位只读可视化资源的共享路径规则。"""

from __future__ import annotations

from pathlib import Path


def normalize_event_resource_id(event_id: str) -> str:
    """校验事件编号可安全用作资源文件名。"""

    normalized = str(event_id or "").strip()
    if not normalized or Path(normalized).name != normalized:
        raise ValueError("event_id 不合法")
    return normalized


def resolve_event_json_path(root: Path, event_id: str) -> Path:
    """返回指定目录下的事件 JSON 路径并拒绝路径穿越。"""

    normalized = normalize_event_resource_id(event_id)
    resolved_root = Path(root).resolve()
    candidate = (resolved_root / f"{normalized}.json").resolve()
    if candidate.parent != resolved_root:
        raise ValueError("event_id 不合法")
    return candidate


def has_event_json_resource(root: Path, event_id: str | None) -> bool:
    """只判断资源是否存在，不让非法编号影响实验目录扫描。"""

    try:
        return resolve_event_json_path(root, str(event_id or "")).is_file()
    except ValueError:
        return False
