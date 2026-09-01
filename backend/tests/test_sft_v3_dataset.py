import json
from pathlib import Path

from backend.scripts.build_sft_v3_dataset import build_dataset
from backend.scripts.validate_sft_v3_dataset import validate_split


def test_sft_v3_builder_creates_balanced_multitask_dataset(tmp_path):
    manifest = build_dataset(tmp_path, max_jobs=20)

    assert manifest["source_jobs"] == 20
    assert manifest["examples"] == 80
    assert manifest["task_counts"] == {
        "jd_extract": 20,
        "job_classify": 20,
        "risk_label": 20,
        "skill_normalize": 20,
    }
    assert (tmp_path / "gold_review_candidates.jsonl").exists()

    train_report = validate_split(tmp_path / "train.jsonl")
    assert train_report["assistant_json_success"] == 1.0
    assert train_report["required_field_success"] == 1.0


def test_sft_v3_dataset_manifest_matches_generated_files():
    dataset_dir = Path("backend/finetune/jobguard_sft_v3/dataset")
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["source_jobs"] == 500
    assert manifest["examples"] == 2000
    assert manifest["split_examples"] == {"train": 1400, "val": 300, "test": 300}
    assert manifest["human_review"]["required"] is True
