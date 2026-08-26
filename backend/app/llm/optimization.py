"""Small, dependency-free helpers for LLM routing, caching and context control."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable


@dataclass(frozen=True)
class RouteDecision:
    provider: str
    reason: str
    complexity: str


def choose_provider(
    messages: list[dict[str, Any]],
    *,
    task_type: str = "general",
    local_available: bool = True,
) -> RouteDecision:
    """Route short deterministic tasks locally and reasoning tasks remotely."""
    text = "\n".join(str(message.get("content", "")) for message in messages)
    reasoning_markers = ("综合", "推理", "权衡", "风险评估", "compare", "reason")
    complex_task = task_type in {"reasoning", "risk_assessment"} or any(
        marker in text.lower() for marker in reasoning_markers
    )
    if complex_task:
        return RouteDecision("deepseek", "reasoning_task", "complex")
    if local_available and len(text) <= 12_000:
        return RouteDecision("vllm", "short_deterministic_task", "simple")
    return RouteDecision("zhipu", "local_unavailable_or_long_context", "medium")


def compact_messages(messages: list[dict[str, Any]], max_chars: int = 16_000) -> list[dict[str, Any]]:
    """Keep system messages and the newest conversation turns within a char budget."""
    if max_chars <= 0:
        return []
    total = sum(len(str(message.get("content", ""))) for message in messages)
    if total <= max_chars:
        return [dict(message) for message in messages]

    system = [dict(message) for message in messages if message.get("role") == "system"]
    remaining = max_chars - sum(len(str(message.get("content", ""))) for message in system)
    if remaining <= 0:
        clipped = system[:1]
        if clipped:
            clipped[0]["content"] = str(clipped[0].get("content", ""))[:max_chars]
        return clipped

    recent: list[dict[str, Any]] = []
    for message in reversed(messages):
        if message.get("role") == "system":
            continue
        content = str(message.get("content", ""))
        if len(content) <= remaining:
            recent.append(dict(message))
            remaining -= len(content)
        else:
            clipped = dict(message)
            clipped["content"] = content[-remaining:]
            recent.append(clipped)
            break
    return system + list(reversed(recent))


class TTLResponseCache:
    """Bounded in-memory exact-match cache for deterministic LLM responses."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def get(self, key: str) -> str | None:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return value

    async def set(self, key: str, value: str, ttl_seconds: float) -> None:
        async with self._lock:
            self._items[key] = (time.monotonic() + ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


async def gather_limited(
    factories: Iterable[Callable[[], Awaitable[Any]]], concurrency: int = 4
) -> list[Any]:
    """Execute independent async work concurrently with a safe upper bound."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(factory: Callable[[], Awaitable[Any]]) -> Any:
        async with semaphore:
            return await factory()

    return await asyncio.gather(*(run(factory) for factory in factories))
