from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from common import load_scenarios
from app.agents.job_matcher import JobMatcherAgent
from app.config import settings


def _profile() -> dict[str, Any]:
    return {
        "basic": {
            "degree": "本科",
            "major": "计算机科学与技术",
            "expected_salary_min": 10000,
            "expected_salary_max": 18000,
        },
        "preferences": {
            "preferred_locations": ["广州", "深圳"],
            "weekend_preference": "必须双休",
            "overtime_tolerance": "偶尔",
        },
        "skills": [{"skill_name": "Python"}, {"skill_name": "FastAPI"}],
    }


def _jobs(count: int, fail_index: int | None = None) -> list[dict[str, Any]]:
    return [
        {
            "id": index + 1,
            "company_name": f"Benchmark Company {index + 1}",
            "job_title": f"Backend Engineer {index + 1}",
            "location": "广州",
            "salary_min": 10000,
            "salary_max": 18000,
            "requirements": ["Python", "FastAPI"],
            "benchmark_score": 100 - index,
            "benchmark_fail": fail_index == index,
        }
        for index in range(count)
    ]


async def _run_case(
    count: int,
    delay_ms: int,
    configured_concurrency: int | None = None,
    fail_index: int | None = None,
) -> dict[str, Any]:
    agent = JobMatcherAgent()
    jobs = _jobs(count, fail_index=fail_index)
    active = 0
    max_active = 0
    call_count = 0
    failed_calls = 0
    lock = asyncio.Lock()

    original = JobMatcherAgent.match_single
    old_setting = getattr(settings, "job_match_llm_concurrency", None)

    async def fake_match_single(self, user_profile, job):
        nonlocal active, max_active, call_count, failed_calls
        async with lock:
            active += 1
            call_count += 1
            max_active = max(max_active, active)
        try:
            await asyncio.sleep(delay_ms / 1000)
            if job.get("benchmark_fail"):
                failed_calls += 1
                raise RuntimeError("benchmark injected failure")
            return {
                "overall_score": job["benchmark_score"],
                "match_level": "good",
                "match_reasons": [f"job-{job['id']}"],
                "recommendation": "recommend",
            }
        finally:
            async with lock:
                active -= 1

    if configured_concurrency is not None and hasattr(settings, "job_match_llm_concurrency"):
        settings.job_match_llm_concurrency = configured_concurrency
    JobMatcherAgent.match_single = fake_match_single
    try:
        start = perf_counter()
        results = await agent.match_batch(_profile(), jobs, top_k=count)
        elapsed_ms = (perf_counter() - start) * 1000
    finally:
        JobMatcherAgent.match_single = original
        if old_setting is not None and hasattr(settings, "job_match_llm_concurrency"):
            settings.job_match_llm_concurrency = old_setting

    actual_ids = [item["job"]["id"] for item in results]
    expected_success_ids = [job["id"] for job in jobs if not job.get("benchmark_fail")]
    expected_success_ids.sort(
        key=lambda job_id: next(job["benchmark_score"] for job in jobs if job["id"] == job_id),
        reverse=True,
    )
    returned_ids_are_valid = all(job_id in {job["id"] for job in jobs} for job_id in actual_ids)
    return {
        "jobs": count,
        "configured_concurrency": configured_concurrency,
        "observed_max_concurrency": max_active,
        "e2e_latency_ms": round(elapsed_ms, 3),
        "avg_per_job_ms": round(elapsed_ms / count, 3),
        "llm_call_count": call_count,
        "success_count": call_count - failed_calls,
        "failure_count": failed_calls,
        "returned_result_count": len(results),
        "returned_job_ids": actual_ids,
        "returned_ids_are_valid": returned_ids_are_valid,
        "successful_result_order_correct": actual_ids == expected_success_ids,
        "failure_injected": fail_index is not None,
        "benchmark_mode": "mock",
        "mock_llm_delay_ms": delay_ms,
    }


async def run(phase: str) -> dict[str, Any]:
    scenarios = load_scenarios()
    delay_ms = scenarios["mock_llm_delay_ms"]
    baseline = [
        await _run_case(count, delay_ms)
        for count in scenarios["job_counts"]
    ]
    payload: dict[str, Any] = {
        "phase": phase,
        "benchmark_mode": "mock",
        "note": "Mock latency measures scheduling only; it is not real model latency.",
        "default_cases": baseline,
        "failure_isolation": await _run_case(5, delay_ms, fail_index=2),
    }
    if phase == "after":
        payload["concurrency_matrix"] = [
            await _run_case(count, delay_ms, configured_concurrency=concurrency)
            for count in (5, 10)
            for concurrency in scenarios["after_concurrency_matrix"]
        ]
    return payload


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.phase)), ensure_ascii=False, indent=2))
