"""Evaluate JobGuard SFT v3 model outputs.

Input prediction JSONL format:

{"id": "...", "prediction": "{...}"}

The script compares predictions against dataset/test.jsonl by id and reports
JSON success, required-field success, exact field accuracy, skill F1 and risk
flag F1.  Use ``--self-check`` to score labels against themselves as a dataset
sanity check.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "finetune" / "jobguard_sft_v3" / "dataset" / "test.jsonl"
DEFAULT_OUT = ROOT / "finetune" / "jobguard_sft_v3" / "dataset" / "eval_self_check_report.json"

REQUIRED_BY_TASK = {
    "jd_extract": {
        "company_name", "job_title", "job_category", "sub_category", "location",
        "salary_min", "salary_max", "degree_requirement", "required_skills", "risk_flags",
    },
    "job_classify": {"job_category", "sub_category", "confidence", "evidence_keywords"},
    "risk_label": {"risk_level", "risk_flags", "evidence_phrases", "unknown_fields"},
    "skill_normalize": {"normalized_skills", "skill_groups"},
}

FIELDS_BY_TASK = {
    "jd_extract": ["company_name", "job_title", "job_category", "sub_category", "location", "salary_min", "salary_max", "degree_requirement", "experience_requirement"],
    "job_classify": ["job_category", "sub_category"],
    "risk_label": ["risk_level"],
    "skill_normalize": [],
}


def parse_object(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def to_set(value: Any) -> set[str]:
    if isinstance(value, str):
        value = [value]
    if isinstance(value, dict):
        rows = []
        for item in value.values():
            rows.extend(item if isinstance(item, list) else [item])
        value = rows
    return {normalize(item) for item in (value or []) if normalize(item)}


def f1(pred_values: Any, gold_values: Any) -> tuple[float, float, float]:
    pred = to_set(pred_values)
    gold = to_set(gold_values)
    if not pred and not gold:
        return 1.0, 1.0, 1.0
    overlap = len(pred & gold)
    precision = overlap / len(pred) if pred else 0.0
    recall = overlap / len(gold) if gold else 0.0
    score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, score


def score_row(task: str, prediction: Any, expected: dict) -> dict[str, float]:
    parsed = parse_object(prediction)
    if parsed is None:
        return {
            "json_success": 0.0,
            "required_field_success": 0.0,
            "field_accuracy": 0.0,
            "skill_precision": 0.0,
            "skill_recall": 0.0,
            "skill_f1": 0.0,
            "risk_precision": 0.0,
            "risk_recall": 0.0,
            "risk_f1": 0.0,
        }
    required = REQUIRED_BY_TASK[task]
    required_ok = required.issubset(set(parsed))
    fields = FIELDS_BY_TASK.get(task, [])
    comparable = [field for field in fields if expected.get(field) not in (None, "")]
    field_accuracy = (
        sum(normalize(parsed.get(field)) == normalize(expected.get(field)) for field in comparable) / len(comparable)
        if comparable else 1.0
    )
    if task == "skill_normalize":
        sp, sr, sf = f1(parsed.get("normalized_skills"), expected.get("normalized_skills"))
    else:
        sp, sr, sf = f1(parsed.get("required_skills"), expected.get("required_skills"))
    rp, rr, rf = f1(parsed.get("risk_flags"), expected.get("risk_flags"))
    return {
        "json_success": 1.0,
        "required_field_success": 1.0 if required_ok else 0.0,
        "field_accuracy": field_accuracy,
        "skill_precision": sp,
        "skill_recall": sr,
        "skill_f1": sf,
        "risk_precision": rp,
        "risk_recall": rr,
        "risk_f1": rf,
    }


def read_dataset(path: Path) -> dict[str, dict]:
    rows = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            expected = parse_object(row["messages"][-1]["content"])
            rows[row["id"]] = {**row, "expected": expected}
    return rows


def read_predictions(path: Path) -> dict[str, Any]:
    rows = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["id"]] = row.get("prediction")
    return rows


def aggregate(scores: list[dict[str, float]]) -> dict[str, float]:
    if not scores:
        return {"samples": 0}
    keys = scores[0].keys()
    return {
        "samples": len(scores),
        **{key: round(sum(row[key] for row in scores) / len(scores), 6) for key in keys},
    }


def evaluate(dataset_path: Path, predictions_path: Path | None = None, self_check: bool = False) -> dict:
    gold = read_dataset(dataset_path)
    predictions = (
        {row_id: row["expected"] for row_id, row in gold.items()}
        if self_check else read_predictions(predictions_path)
    )
    by_task = defaultdict(list)
    missing_predictions = []
    for row_id, row in gold.items():
        if row_id not in predictions:
            missing_predictions.append(row_id)
            continue
        by_task[row["task"]].append(score_row(row["task"], predictions[row_id], row["expected"]))
    task_reports = {task: aggregate(scores) for task, scores in sorted(by_task.items())}
    all_scores = [score for scores in by_task.values() for score in scores]
    return {
        "dataset": str(dataset_path),
        "prediction_file": str(predictions_path) if predictions_path else None,
        "self_check": self_check,
        "overall": aggregate(all_scores),
        "by_task": task_reports,
        "missing_predictions": len(missing_predictions),
        "missing_prediction_ids_preview": missing_predictions[:20],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not args.self_check and not args.predictions:
        raise SystemExit("请提供 --predictions，或使用 --self-check 做数据自检")
    report = evaluate(args.data, args.predictions, args.self_check)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
