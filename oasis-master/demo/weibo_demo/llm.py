from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class LLMCallBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMCallStats:
    used: int
    budget: int
    max_concurrency: int


class LLMCallGate:
    """未来接入 LLM 时统一控制并发、超时和单次运行调用预算。"""

    def __init__(
        self,
        *,
        max_concurrency: int = 3,
        call_budget: int = 40,
        timeout_seconds: float = 15.0,
    ) -> None:
        if max_concurrency <= 0 or call_budget < 0 or timeout_seconds <= 0:
            raise ValueError("LLM 并发、预算和超时参数必须有效。")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._counter_lock = asyncio.Lock()
        self._used = 0
        self._max_concurrency = max_concurrency
        self._call_budget = call_budget
        self._timeout_seconds = timeout_seconds

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._counter_lock:
            if self._used >= self._call_budget:
                raise LLMCallBudgetExceeded(
                    f"本次运行的 LLM 调用预算 {self._call_budget} 已耗尽。"
                )
            self._used += 1

        async with self._semaphore:
            return await asyncio.wait_for(
                operation(),
                timeout=self._timeout_seconds,
            )

    @property
    def stats(self) -> LLMCallStats:
        return LLMCallStats(
            used=self._used,
            budget=self._call_budget,
            max_concurrency=self._max_concurrency,
        )
