"""Export SFT v3 gold review candidates to CSV for human annotation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "finetune" / "jobguard_sft_v3" / "dataset"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET / "gold_review_candidates.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_DATASET / "gold_review_sheet.csv")
    args = parser.parse_args()

    rows = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows.append({
                "source_job_id": row.get("source_job_id"),
                "company_name": row.get("company_name"),
                "job_title": row.get("job_title"),
                "source_type": row.get("source_type"),
                "review_priority": row.get("review_priority"),
                "correct_job_category": "",
                "correct_sub_category": "",
                "correct_skills": "",
                "correct_risk_flags": "",
                "correct_salary": "",
                "correct_location": "",
                "human_decision": "",
                "review_notes": "",
                "jd_text": row.get("jd_text"),
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
