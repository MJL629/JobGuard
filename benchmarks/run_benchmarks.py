from __future__ import annotations

import argparse
import asyncio

from benchmark_job_matcher import run as run_job_matcher
from benchmark_prompts import run as run_prompts
from benchmark_workflow import run as run_workflow
from common import ROOT, environment_payload, write_json


async def main(phase: str) -> None:
    output_dir = ROOT / "benchmarks" / "results" / phase
    environment = environment_payload(phase)
    job_matcher = await run_job_matcher(phase)
    prompt_prefix = run_prompts(phase)
    workflow = await run_workflow(phase)
    summary = {
        "phase": phase,
        "benchmark_mode": "mock",
        "job_matcher": {
            "default_cases": job_matcher["default_cases"],
            "failure_isolation": job_matcher["failure_isolation"],
        },
        "prompt_prefix": {
            item["agent"]: item["common_prefix_tokens"]
            for item in prompt_prefix["agents"]
        },
        "workflow": {
            "mean_e2e_latency_ms": workflow["workflow_e2e_latency_ms"]["mean"],
            "success_count": workflow["success_count"],
            "failure_count": workflow["failure_count"],
        },
    }
    write_json(output_dir / "environment.json", environment)
    write_json(output_dir / "job_matcher.json", job_matcher)
    write_json(output_dir / "prompt_prefix.json", prompt_prefix)
    write_json(output_dir / "workflow.json", workflow)
    write_json(output_dir / "summary.json", summary)
    print(output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    args = parser.parse_args()
    asyncio.run(main(args.phase))
