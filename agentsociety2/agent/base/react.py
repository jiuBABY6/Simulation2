"""Base ReAct loop data structures and scaffolding.

中文：提供 ReAct 循环的数据结构（``ReactDecision`` / ``ReactToolResult``）。
English: Provides the ReAct loop data structures (``ReactDecision`` / ``ReactToolResult``).

The concrete ReAct loop orchestration (message building, LLM dispatch, tool
execution) lives in the agent subclasses and their support modules
(``person_prompt.py``, ``person_tools.py``).  This module only owns the
shared dataclasses so that the base tool dispatch and the person-specific
react loop can reference a single canonical definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ReactDecision",
    "ReactToolResult",
]


@dataclass(frozen=True)
class ReactDecision:
    """One parsed ReAct tool decision.

    Args:
        thought: Optional model thought text.
        action: Tool/action name.
        args: Parsed tool arguments.
        final: Final text when the action is ``finish``.
    """

    thought: str
    action: str
    args: dict[str, Any]
    final: str


@dataclass(frozen=True)
class ReactToolResult:
    """Result returned by one ReAct tool dispatch.

    Args:
        ok: Whether the tool call succeeded.
        observation: Text shown to the next ReAct turn.
        data: Structured result data for tracing and tests.
    """

    ok: bool
    observation: str
    data: dict[str, Any]
