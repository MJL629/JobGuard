"""Compare Base, SFT and DPO preference win rates and margins."""

from __future__ import annotations

import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from train_dpo import encode, response_logp


MODEL = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
ROOT = Path("/root/autodl-tmp/jobguard_adapters")


@torch.no_grad()
def score(model, tokenizer, rows: list[dict]) -> dict:
    model.eval()
    margins = []
    for row in rows:
        chosen = encode(tokenizer, row, row["chosen"], 512)
        rejected = encode(tokenizer, row, row["rejected"], 512)
        margins.append((response_logp(model, chosen) - response_logp(model, rejected)).item())
    return {
        "win_rate": sum(value > 0 for value in margins) / len(margins),
        "strong_win_rate_margin_0_1": sum(value > 0.1 for value in margins) / len(margins),
        "average_margin": round(sum(margins) / len(margins), 6),
        "min_margin": round(min(margins), 6),
    }


def load_base():
    return AutoModelForCausalLM.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
    )


def main() -> None:
    rows = [json.loads(line) for line in Path("data/post_training/preference_test.jsonl").read_text(encoding="utf-8").splitlines()]
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    models = {}
    base = load_base()
    models["base"] = score(base, tokenizer, rows)
    del base
    torch.cuda.empty_cache()
    for name, adapter in (("sft_r16", ROOT / "sft_r16"), ("dpo_r16", ROOT / "dpo_r16")):
        model = PeftModel.from_pretrained(load_base(), adapter)
        models[name] = score(model, tokenizer, rows)
        del model
        torch.cuda.empty_cache()
    Path("data/post_training/preference_model_comparison.json").write_text(
        json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(models, ensure_ascii=False))


if __name__ == "__main__":
    main()
