"""Validate JobGuard SFT v3 dataset before training."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "finetune" / "jobguard_sft_v3" / "dataset"
REQUIRED_BY_TASK = {
    "jd_extract": {
        "company_name", "job_title", "job_category", "sub_category", "location",
        "salary_min", "salary_max", "degree_requirement", "required_skills", "risk_flags",
    },
    "job_classify": {"job_category", "sub_category", "confidence", "evidence_keywords"},
    "risk_label": {"risk_level", "risk_flags", "evidence_phrases", "unknown_fields"},
    "skill_normalize": {"normalized_skills", "skill_groups"},
}


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def validate_split(path: Path) -> dict:
    total = 0
    json_success = 0
    schema_success = 0
    task_counts = Counter()
    label_counts = Counter()
    source_counts = Counter()
    errors = []
    for line_number, row in iter_jsonl(path):
        total += 1
        task = row.get("task")
        task_counts[task] += 1
        label_counts[row.get("label_quality")] += 1
        source_counts[row.get("source_type")] += 1
        messages = row.get("messages") or []
        if len(messages) != 3 or messages[-1].get("role") != "assistant":
            errors.append({"line": line_number, "error": "messages_format"})
            continue
        try:
            output = json.loads(messages[-1].get("content") or "")
            json_success += 1
        except json.JSONDecodeError:
            errors.append({"line": line_number, "task": task, "error": "assistant_json_invalid"})
            continue
        required = REQUIRED_BY_TASK.get(task)
        if not required:
            errors.append({"line": line_number, "task": task, "error": "unknown_task"})
            continue
        missing = sorted(required - set(output))
        if missing:
            errors.append({"line": line_number, "task": task, "error": "missing_fields", "fields": missing})
            continue
        schema_success += 1
    return {
        "file": path.name,
        "examples": total,
        "assistant_json_success": round(json_success / total, 6) if total else 0,
        "required_field_success": round(schema_success / total, 6) if total else 0,
        "task_counts": dict(task_counts),
        "label_quality_counts": dict(label_counts),
        "source_type_top10": dict(source_counts.most_common(10)),
        "error_count": len(errors),
        "errors_preview": errors[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    report = {
        "dataset": str(args.dataset),
        "splits": [
            validate_split(args.dataset / "train.jsonl"),
            validate_split(args.dataset / "val.jsonl"),
            validate_split(args.dataset / "test.jsonl"),
        ],
    }
    report["total_examples"] = sum(item["examples"] for item in report["splits"])
    report["overall_json_success"] = round(
        sum(item["assistant_json_success"] * item["examples"] for item in report["splits"]) / report["total_examples"],
        6,
    )
    report["overall_required_field_success"] = round(
        sum(item["required_field_success"] * item["examples"] for item in report["splits"]) / report["total_examples"],
        6,
    )
    out_path = args.dataset / "validation_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(item["error_count"] for item in report["splits"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
