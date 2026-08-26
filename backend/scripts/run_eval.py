"""Evaluate JSONL predictions against the fixed JobGuard benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.eval.jobguard_metrics import aggregate, score_record  # noqa: E402


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Score predictions keyed by benchmark id")
    parser.add_argument("--benchmark", type=Path, default=BACKEND / "data/eval/jobguard_benchmark/test.jsonl")
    parser.add_argument("--predictions", type=Path, required=True,
                        help='JSONL rows: {"id": ..., "prediction": {...}, "latency_ms": ..., "tokens": ...}')
    parser.add_argument("--output", type=Path, default=BACKEND / "data/eval/jobguard_eval_result.json")
    args = parser.parse_args()
    gold = {row["id"]: row for row in load(args.benchmark)}
    predictions = load(args.predictions)
    matched = [row for row in predictions if row.get("id") in gold]
    report = aggregate(score_record(row.get("prediction"), gold[row["id"]]) for row in matched)
    report.update({"benchmark_samples": len(gold), "coverage": round(len(matched) / len(gold), 4) if gold else 0,
                   "latency_ms_mean": round(sum(float(r.get("latency_ms", 0)) for r in matched) / len(matched), 2) if matched else None,
                   "tokens_total": sum(int(r.get("tokens", 0)) for r in matched)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
