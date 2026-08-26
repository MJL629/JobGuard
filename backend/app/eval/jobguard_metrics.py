"""Metrics for the fixed JobGuard extraction benchmark."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


FIELDS = ("company", "position", "experience", "education", "location", "salary")


def parse_object(value: Any) -> dict[str, Any] | None:
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
        result = json.loads(text.strip())
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _skill_set(value: Any) -> set[str]:
    if isinstance(value, str):
        value = [value]
    return {_norm(item) for item in (value or []) if _norm(item)}


def score_record(prediction: Any, expected: dict[str, Any]) -> dict[str, float]:
    parsed = parse_object(prediction)
    if parsed is None:
        return {"json_success": 0.0, "field_accuracy": 0.0, "skill_precision": 0.0,
                "skill_recall": 0.0, "skill_f1": 0.0}
    # Accept both benchmark names and the application's native extraction names.
    aliases = {
        "company": ("company", "company_name"), "position": ("position", "job_title"),
        "experience": ("experience", "experience_required"),
        "education": ("education", "education_required"), "location": ("location",),
        "salary": ("salary", "salary_raw"), "skills": ("skills", "requirements"),
    }
    normalized = {key: next((parsed[name] for name in names if name in parsed), None)
                  for key, names in aliases.items()}
    expected_values = {**expected, "company": expected.get("company", expected.get("expected_company"))}
    comparable = [field for field in FIELDS if expected_values.get(field) not in (None, "")]
    field_accuracy = (sum(_norm(normalized[field]) == _norm(expected_values[field]) for field in comparable)
                      / len(comparable) if comparable else 1.0)
    gold, pred = _skill_set(expected.get("skills")), _skill_set(normalized.get("skills"))
    overlap = len(gold & pred)
    precision = overlap / len(pred) if pred else (1.0 if not gold else 0.0)
    recall = overlap / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"json_success": 1.0, "field_accuracy": field_accuracy,
            "skill_precision": precision, "skill_recall": recall, "skill_f1": f1}


def aggregate(scores: Iterable[dict[str, float]]) -> dict[str, float]:
    rows = list(scores)
    if not rows:
        return {"samples": 0}
    keys = rows[0]
    return {"samples": len(rows), **{key: round(sum(row[key] for row in rows) / len(rows), 4)
                                     for key in keys}}
