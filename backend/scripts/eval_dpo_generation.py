"""Generation regression check for the DPO adapter."""

from __future__ import annotations

import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


MODEL = "/root/autodl-tmp/models/Qwen2.5-7B-Instruct"
ADAPTER = "/root/autodl-tmp/jobguard_adapters/dpo_r16"


def parse_json(text: str):
    try:
        return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    except json.JSONDecodeError:
        return None


def main() -> None:
    rows = [json.loads(line) for line in Path("data/post_training/sft_test.jsonl").read_text(encoding="utf-8").splitlines()][:10]
    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True)
    model = PeftModel.from_pretrained(base, ADAPTER).eval()
    valid = exact = fields = total = 0
    with torch.no_grad():
        for row in rows:
            prompt = tokenizer.apply_chat_template(
                [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["prompt"]}],
                tokenize=False, add_generation_prompt=True,
            )
            inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
            ids = model.generate(**inputs, max_new_tokens=256, do_sample=False)
            prediction = parse_json(tokenizer.decode(ids[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True))
            expected = json.loads(row["response"])
            total += len(expected)
            if isinstance(prediction, dict):
                valid += 1
                matched = sum(prediction.get(key) == value for key, value in expected.items())
                fields += matched
                exact += int(matched == len(expected))
    report = {"cases": 10, "json_valid_rate": valid / 10, "exact_match_rate": exact / 10, "field_accuracy": fields / total}
    Path("data/post_training/dpo_generation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
