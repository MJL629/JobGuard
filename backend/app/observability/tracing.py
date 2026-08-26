"""Dependency-free JSONL tracing for agents, tools and model calls."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, AsyncIterator, Callable


_trace_id: ContextVar[str | None] = ContextVar("jobguard_trace_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("jobguard_request_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("jobguard_span_id", default=None)


class TraceRecorder:
    """Append-only trace recorder that is safe for concurrent async requests."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("JOBGUARD_TRACE_PATH", "data/traces.jsonl")
        self.path = Path(configured)
        self._lock = asyncio.Lock()

    @property
    def trace_id(self) -> str | None:
        return _trace_id.get()

    @property
    def request_id(self) -> str | None:
        return _request_id.get()

    async def emit(self, event: dict[str, Any]) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            **event,
        }
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    @asynccontextmanager
    async def trace(
        self, request_id: str | None = None, name: str = "request"
    ) -> AsyncIterator[str]:
        trace_id = uuid.uuid4().hex
        trace_token = _trace_id.set(trace_id)
        request_token = _request_id.set(request_id or uuid.uuid4().hex)
        started = time.perf_counter()
        await self.emit({"event": "trace_start", "name": name})
        status = "ok"
        error = None
        try:
            yield trace_id
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            await self.emit({
                "event": "trace_end",
                "name": name,
                "status": status,
                "error": error,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            })
            _request_id.reset(request_token)
            _trace_id.reset(trace_token)

    @asynccontextmanager
    async def span(self, name: str, kind: str, **attributes: Any) -> AsyncIterator[str]:
        span_id = uuid.uuid4().hex
        parent_span_id = _span_id.get()
        token = _span_id.set(span_id)
        started = time.perf_counter()
        status = "ok"
        error = None
        try:
            yield span_id
        except Exception as exc:
            status, error = "error", f"{type(exc).__name__}: {exc}"
            raise
        finally:
            await self.emit({
                "event": "span",
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "kind": kind,
                "status": status,
                "error": error,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                **attributes,
            })
            _span_id.reset(token)


trace_recorder = TraceRecorder()


def _summarize(value: Any, limit: int = 240) -> str:
    """Create a bounded, non-recursive trace preview without storing full prompts."""
    if isinstance(value, dict):
        preview = {key: type(item).__name__ for key, item in list(value.items())[:12]}
        text = json.dumps(preview, ensure_ascii=False)
    elif isinstance(value, (list, tuple)):
        text = f"{type(value).__name__}(length={len(value)})"
    else:
        text = str(value)
    return text[:limit]


def traced_node(name: str) -> Callable:
    """Decorate a LangGraph async node and preserve its signature semantics."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async with trace_recorder.span(name=name, kind="agent_node") as span_id:
                result = await func(*args, **kwargs)
                await trace_recorder.emit({
                    "event": "agent_node_io",
                    "span_id": span_id,
                    "name": name,
                    "input_summary": _summarize(args[0] if args else kwargs),
                    "output_summary": _summarize(result),
                    "output_status": "ok",
                })
                return result
        return wrapper
    return decorator
