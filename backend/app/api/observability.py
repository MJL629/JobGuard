"""Agent trace APIs for the lightweight observability page."""

import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from app.api.auth import get_current_user
from app.models.user import User
from app.observability.tracing import trace_recorder

router = APIRouter()


def _load_rows(limit: int = 500) -> list[dict]:
    path = Path(trace_recorder.path)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines[-limit:]:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


@router.get("/traces")
async def list_traces(
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
):
    rows = _load_rows(limit)
    traces: dict[str, dict] = {}
    span_latency: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        trace_id = row.get("trace_id") or "no-trace"
        trace = traces.setdefault(trace_id, {
            "trace_id": trace_id,
            "request_id": row.get("request_id"),
            "started_at": row.get("timestamp"),
            "ended_at": row.get("timestamp"),
            "status": "ok",
            "events": 0,
            "latency_ms": 0,
        })
        trace["ended_at"] = row.get("timestamp")
        trace["events"] += 1
        if row.get("status") == "error":
            trace["status"] = "error"
        if row.get("event") == "trace_end":
            trace["latency_ms"] = row.get("latency_ms", 0)
        if row.get("event") == "span":
            name = f"{row.get('kind')}:{row.get('name')}"
            span_latency[name].append(row.get("latency_ms", 0))

    spans = []
    for name, values in span_latency.items():
        spans.append({
            "name": name,
            "count": len(values),
            "avg_ms": round(sum(values) / len(values), 1) if values else 0,
            "max_ms": round(max(values), 1) if values else 0,
        })

    recent_events = rows[-80:][::-1]
    return {
        "code": 0,
        "data": {
            "trace_count": len(traces),
            "event_count": len(rows),
            "traces": sorted(traces.values(), key=lambda x: x["ended_at"] or "", reverse=True)[:50],
            "spans": sorted(spans, key=lambda x: x["avg_ms"], reverse=True),
            "events": recent_events,
        },
    }
