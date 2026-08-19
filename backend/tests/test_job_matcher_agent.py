import asyncio

import pytest

from app.agents.job_matcher import JobMatcherAgent
from app.config import settings


def _jobs(count):
    return [
        {"id": index + 1, "job_title": f"job-{index + 1}", "score": 100 - index}
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_match_batch_respects_configured_concurrency(monkeypatch):
    active = 0
    observed_max = 0
    lock = asyncio.Lock()

    async def fake_match(self, profile, job):
        nonlocal active, observed_max
        async with lock:
            active += 1
            observed_max = max(observed_max, active)
        await asyncio.sleep(0.01)
        async with lock:
            active -= 1
        return {"overall_score": job["score"]}

    monkeypatch.setattr(settings, "job_match_llm_concurrency", 2)
    monkeypatch.setattr(JobMatcherAgent, "match_single", fake_match)

    results = await JobMatcherAgent().match_batch({}, _jobs(7), top_k=7)

    assert observed_max == 2
    assert len(results) == 7


@pytest.mark.asyncio
async def test_match_batch_keeps_job_mapping_and_score_order(monkeypatch):
    async def fake_match(self, profile, job):
        await asyncio.sleep(0)
        return {"overall_score": job["score"], "source_job_id": job["id"]}

    monkeypatch.setattr(settings, "job_match_llm_concurrency", 4)
    monkeypatch.setattr(JobMatcherAgent, "match_single", fake_match)

    results = await JobMatcherAgent().match_batch({}, _jobs(5), top_k=5)

    assert [item["job"]["id"] for item in results] == [1, 2, 3, 4, 5]
    assert all(
        item["job"]["id"] == item["match"]["source_job_id"] for item in results
    )


@pytest.mark.asyncio
async def test_single_failure_degrades_without_losing_batch_item(monkeypatch):
    async def fake_match(self, profile, job):
        if job["id"] == 3:
            raise RuntimeError("injected")
        return {"overall_score": job["score"]}

    monkeypatch.setattr(settings, "job_match_llm_concurrency", 4)
    monkeypatch.setattr(JobMatcherAgent, "match_single", fake_match)

    results = await JobMatcherAgent().match_batch({}, _jobs(5), top_k=5)

    assert len(results) == 5
    failed = next(item for item in results if item["job"]["id"] == 3)
    assert failed["match"]["degraded"] is True
    assert failed["match"]["overall_score"] == 0
