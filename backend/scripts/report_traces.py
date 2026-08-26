"""Aggregate JobGuard JSONL traces into a compact performance report."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def stats(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "avg_ms": 0, "p95_ms": 0}
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95)))
    return {
        "count": len(ordered),
        "avg_ms": round(sum(ordered) / len(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def build_report(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    spans: dict[str, list[float]] = defaultdict(list)
    traces = set()
    errors = 0
    prompt_tokens = completion_tokens = 0
    for row in rows:
        if row.get("trace_id"):
            traces.add(row["trace_id"])
        if row.get("status") == "error":
            errors += 1
        if row.get("event") == "span":
            spans[f'{row.get("kind")}:{row.get("name")}'].append(row.get("latency_ms", 0))
        if row.get("event") == "llm_usage":
            prompt_tokens += row.get("prompt_tokens") or 0
            completion_tokens += row.get("completion_tokens") or 0
    return {
        "trace_count": len(traces),
        "event_count": len(rows),
        "error_events": errors,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens, "total": prompt_tokens + completion_tokens},
        "spans": {name: stats(values) for name, values in sorted(spans.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.trace)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
