"""Run the deterministic JD extraction baseline against a configured provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.job_parser import JOB_EXTRACT_PROMPT, JobParserAgent
from app.eval.metrics import evaluate_record
from app.llm.gateway import llm_gateway
from app.observability.tracing import trace_recorder


async def run(dataset: Path, provider: str) -> dict:
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for row in rows:
        messages = [
            {"role": "system", "content": "你是一个精确的 JSON 输出引擎。只输出 JSON，不输出解释。"},
            {"role": "user", "content": JOB_EXTRACT_PROMPT.format(raw_text=row["input"])},
        ]
        async with trace_recorder.trace(request_id=row["id"], name="eval.jd"):
            prediction = await llm_gateway.chat(
                messages, provider=provider, temperature=0.0, max_tokens=1200
            )
        cleaned = JobParserAgent._clean_json(prediction)
        score = evaluate_record(cleaned, row["expected"])
        results.append({"id": row["id"], "score": score, "prediction": cleaned})

    metric_names = ("json_valid", "required_field_rate", "value_accuracy")
    summary = {
        name: round(sum(item["score"][name] for item in results) / len(results), 4)
        for name in metric_names
    }
    return {"provider": provider, "cases": len(results), "summary": summary, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="vllm")
    parser.add_argument("--dataset", type=Path, default=Path("data/eval/jd_baseline.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/eval/jd_baseline_result.json"))
    args = parser.parse_args()
    report = asyncio.run(run(args.dataset, args.provider))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
