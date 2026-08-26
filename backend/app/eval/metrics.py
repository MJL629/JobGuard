"""Deterministic baseline metrics shared by Base/SFT/DPO evaluations."""

from __future__ import annotations

import json
from typing import Any


def _as_object(value: Any) -> dict | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def evaluate_record(prediction: Any, expected: dict[str, Any]) -> dict[str, float]:
    """Score JSON validity, required fields and exact expected field values."""
    parsed = _as_object(prediction)
    required = expected.get("required_fields", [])
    expected_values = expected.get("values", {})
    if parsed is None:
        return {"json_valid": 0.0, "required_field_rate": 0.0, "value_accuracy": 0.0}

    field_rate = (
        sum(field in parsed and parsed[field] not in (None, "") for field in required)
        / len(required)
        if required else 1.0
    )
    value_accuracy = (
        sum(parsed.get(key) == value for key, value in expected_values.items())
        / len(expected_values)
        if expected_values else 1.0
    )
    return {
        "json_valid": 1.0,
        "required_field_rate": round(field_rate, 4),
        "value_accuracy": round(value_accuracy, 4),
    }
