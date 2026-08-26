"""End-to-end JobParser Agent evaluation with trace correlation."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LLM_PRIMARY_PROVIDER", "vllm")

from app.agents.job_parser import job_parser
from app.eval.metrics import evaluate_record
from app.observability.tracing import trace_recorder


async def main() -> None:
    dataset = Path("data/eval/jd_baseline.jsonl")
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for row in rows:
        async with trace_recorder.trace(request_id=row["id"], name="eval.job_parser_agent"):
            prediction = await job_parser.parse(row["input"])
        results.append({"id": row["id"], "score": evaluate_record(prediction, row["expected"]), "prediction": prediction})
    names = ("json_valid", "required_field_rate", "value_accuracy")
    report = {
        "cases": len(results),
        "summary": {name: round(sum(r["score"][name] for r in results) / len(results), 4) for name in names},
        "results": results,
    }
    Path("data/eval/job_parser_agent_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
