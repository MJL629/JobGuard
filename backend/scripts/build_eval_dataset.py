"""Build the reproducible 500-row JobGuard benchmark (local gold + public silver)."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "eval" / "jobguard_benchmark"
HF_DATASET = "ryang2/linkedin-job-scrape"
SKILLS = ("Python", "Java", "JavaScript", "TypeScript", "SQL", "AWS", "Azure", "GCP", "Docker",
          "Kubernetes", "PyTorch", "TensorFlow", "Spark", "Hadoop", "Kafka", "React", "Vue",
          "Angular", "Node.js", "Go", "C++", "C#", "R", "Tableau", "Looker", "Snowflake",
          "Databricks", "Git", "Linux", "NLP", "Machine Learning", "Deep Learning", "LLM")


def _fetch_public(offset: int, length: int = 100) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"dataset": HF_DATASET, "config": "default", "split": "train",
                                    "offset": offset, "length": length})
    with urllib.request.urlopen(f"https://datasets-server.huggingface.co/rows?{params}", timeout=60) as response:
        return [item["row"] for item in json.load(response)["rows"]]


def _skills(text: str) -> list[str]:
    return [skill for skill in SKILLS if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", text, re.I)]


def _experience(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2}\+?\s*(?:-|to)?\s*\d{0,2}\s*years?)\b", text, re.I)
    return match.group(1) if match else None


def _education(text: str) -> str | None:
    for pattern, label in ((r"(?:bachelor'?s?|BS/BA)", "Bachelor"),
                           (r"(?:master'?s?|MS/MA)", "Master"), (r"Ph\.?D", "PhD")):
        if re.search(pattern, text, re.I):
            return label
    return None


def _local_rows() -> list[dict[str, Any]]:
    result = []
    for path in sorted((ROOT / "data").glob("seed_jobs*.json")):
        for index, row in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            salary = None
            if row.get("salary_min") is not None or row.get("salary_max") is not None:
                salary = f'{row.get("salary_min", "")}-{row.get("salary_max", "")} {row.get("salary_unit", "")}'.strip()
            result.append({"id": f"local-{path.stem}-{index:03d}", "jd_text": row.get("jd_text", ""),
                           "expected_company": row.get("company_name"), "position": row.get("job_title"),
                           "skills": row.get("requirements", []), "experience": row.get("experience_required"),
                           "education": row.get("degree_requirement"), "location": row.get("location"),
                           "salary": salary, "label_quality": "gold", "source": path.name})
    return result


def build(total: int = 500, seed: int = 20260825) -> list[dict[str, Any]]:
    rows, seen = [], set()
    for item in _local_rows():
        key = hashlib.sha256(item["jd_text"].encode()).hexdigest()
        if item["jd_text"] and key not in seen:
            rows.append(item); seen.add(key)
    offset = 0
    while len(rows) < total:
        for raw in _fetch_public(offset):
            text = str(raw.get("job_description") or "").strip()
            key = hashlib.sha256(text.encode()).hexdigest()
            if len(text) < 120 or key in seen:
                continue
            seen.add(key)
            rows.append({"id": f'hf-{raw.get("job_id") or key[:16]}', "jd_text": text,
                         "expected_company": raw.get("company_name"), "position": raw.get("job_title"),
                         "skills": _skills(text), "experience": _experience(text),
                         "education": _education(text), "location": raw.get("location"),
                         "salary": raw.get("salary_raw"), "label_quality": "silver",
                         "source": HF_DATASET})
            if len(rows) >= total:
                break
        offset += 100
        if offset > 5000 and len(rows) < total:
            raise RuntimeError("Public source did not yield enough unique rows")
    random.Random(seed).shuffle(rows)
    return rows[:total]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--total", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()
    if not 500 <= args.total <= 1000:
        parser.error("--total must be between 500 and 1000")
    rows = build(args.total, args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    counts = (int(args.total * .7), int(args.total * .15))
    splits = {"train": rows[:counts[0]], "val": rows[counts[0]:sum(counts)], "test": rows[sum(counts):]}
    for name, values in {**splits, "benchmark": rows}.items():
        (args.output / f"{name}.jsonl").write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values), encoding="utf-8")
    manifest = {"version": "1.0.0", "seed": args.seed, "total": len(rows),
                "splits": {k: len(v) for k, v in splits.items()},
                "label_quality": {q: sum(r["label_quality"] == q for r in rows) for q in ("gold", "silver")},
                "public_source": HF_DATASET}
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
