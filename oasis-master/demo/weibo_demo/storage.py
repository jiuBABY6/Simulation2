from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import DomainEvent


class EventStore(Protocol):
    def append(self, event: DomainEvent) -> None:
        ...

    def clear(self) -> None:
        ...


class InMemoryEventStore:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def append(self, event: DomainEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


class JsonlEventStore:
    """单写入器 JSONL 事件日志；后续可替换为 SQLite/PostgreSQL。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def append(self, event: DomainEvent) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
                + "\n"
            )

    def clear(self) -> None:
        self.path.write_text("", encoding="utf-8")
