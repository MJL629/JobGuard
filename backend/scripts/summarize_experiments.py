"""Collect serving, SFT and DPO experiment reports into one artifact."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("/root/autodl-tmp/jobguard_adapters")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    sft = [read(ROOT / f"sft_r{r}" / "experiment_report.json") for r in (4, 8, 16)]
    report = {
        "agent": read(Path("data/eval/job_parser_agent_performance.json")),
        "serving": {
            "baseline": read(Path("data/eval/vllm_benchmark.json")),
            "kv_cache_u70_l2048": read(Path("data/eval/vllm_param_a_u70_l2048.json")),
            "kv_cache_u90_l6000": read(Path("data/eval/vllm_param_c_u90_l6000.json")),
            "batch_max_num_seqs_8": read(Path("data/eval/vllm_batch_maxseq8.json")),
        },
        "sft": {"experiments": sft, "generation_eval": read(Path("data/post_training/sft_eval_report.json")), "selected": "sft_r16"},
        "dpo": {
            "selected_training": read(Path("data/post_training/dpo_eval_report.json")),
            "preference_comparison": read(Path("data/post_training/preference_model_comparison.json")),
            "generation_eval": read(Path("data/post_training/dpo_generation_report.json")),
            "overfit_training": read(Path("data/post_training/dpo_overfit_train_report.json")),
            "overfit_generation": read(Path("data/post_training/dpo_overfit_generation_report.json")),
        },
        "recommendation": {
            "production_model": "sft_r16",
            "reason": "Highest held-out field accuracy; DPO improves preference margin but regresses extraction accuracy.",
            "remote_adapter_paths": {
                "sft_r4": str(ROOT / "sft_r4"), "sft_r8": str(ROOT / "sft_r8"),
                "sft_r16": str(ROOT / "sft_r16"), "dpo_r16": str(ROOT / "dpo_r16"),
            },
        },
    }
    Path("data/post_training/experiment_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["recommendation"], ensure_ascii=False))


if __name__ == "__main__":
    main()
