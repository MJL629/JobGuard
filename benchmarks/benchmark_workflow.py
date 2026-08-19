from __future__ import annotations

from statistics import mean
from time import perf_counter
from typing import Any

from common import load_scenarios
from app.graph import builder


async def run(phase: str) -> dict[str, Any]:
    scenario = load_scenarios()["workflow"]
    latencies = []
    successes = 0
    traces: list[list[str]] = []
    for index in range(scenario["iterations"]):
        start = perf_counter()
        result = await builder.classify_message(
            scenario["message"],
            user_id="benchmark-user",
            session_id=f"benchmark-{index}",
            session_type=scenario["session_type"],
        )
        latencies.append((perf_counter() - start) * 1000)
        traces.append(result.get("graph_trace", []))
        successes += int(result.get("intent") == scenario["expected_intent"])

    ordered = sorted(latencies)
    p95_index = max(0, int(len(ordered) * 0.95) - 1)
    first_trace = traces[0] if traces else []
    return {
        "phase": phase,
        "benchmark_mode": "mock",
        "scenario": scenario,
        "workflow_e2e_latency_ms": {
            "mean": round(mean(latencies), 3),
            "min": round(min(latencies), 3),
            "p95": round(ordered[p95_index], 3),
            "max": round(max(latencies), 3),
        },
        "llm_call_count": 0,
        "tool_call_count": 0,
        "graph_node_execution_count_per_run": len(first_trace),
        "graph_trace": first_trace,
        "success_count": successes,
        "failure_count": scenario["iterations"] - successes,
        "note": "The fixed scenario is resolved by existing rule-based intent routing; no LLM/tool call is expected.",
    }
