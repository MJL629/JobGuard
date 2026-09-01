"""Run inference with a JobGuard SFT v3 LoRA adapter.

This script is intentionally separated from evaluation:
- it loads the base model and an optional LoRA adapter;
- it generates JSON predictions for train/val/test samples;
- `eval_sft_v3_outputs.py` can then score the saved predictions.

Example:
    python backend/scripts/predict_sft_v3_outputs.py \
      --base-model /root/autodl-tmp/models/Qwen2.5-7B-Instruct \
      --adapter /root/autodl-tmp/jobguard_sft_v3_outputs/checkpoint-final \
      --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
      --output backend/finetune/jobguard_sft_v3/results/test_predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def build_prompt(sample: dict[str, Any]) -> str:
    instruction = sample.get("instruction") or ""
    input_text = sample.get("input") or ""
    return (
        "<|im_start|>system\n"
        "你是 JobGuard 的结构化信息抽取与岗位分析助手。请严格输出合法 JSON，不要输出解释文本。"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"{instruction}\n\n{input_text}"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def normalize_prediction(text: str) -> str:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate JobGuard SFT v3 predictions.")
    parser.add_argument("--base-model", required=True, help="Base model path or Hugging Face id.")
    parser.add_argument("--adapter", default=None, help="Optional LoRA adapter/checkpoint path.")
    parser.add_argument("--data", required=True, help="Input JSONL dataset path.")
    parser.add_argument("--output", required=True, help="Output JSONL prediction path.")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit for smoke runs.")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    data_path = Path(args.data)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )

    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter)

    model.eval()
    samples = load_jsonl(data_path, args.limit)

    with output_path.open("w", encoding="utf-8") as out:
        for sample in samples:
            prompt = build_prompt(sample)
            inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
            generation_kwargs: dict[str, Any] = {
                "max_new_tokens": args.max_new_tokens,
                "do_sample": args.temperature > 0,
                "temperature": args.temperature if args.temperature > 0 else None,
                "pad_token_id": tokenizer.eos_token_id,
            }
            generation_kwargs = {k: v for k, v in generation_kwargs.items() if v is not None}

            with torch.no_grad():
                generated = model.generate(**inputs, **generation_kwargs)
            new_tokens = generated[0][inputs["input_ids"].shape[-1] :]
            raw_prediction = tokenizer.decode(new_tokens, skip_special_tokens=True)

            out.write(
                json.dumps(
                    {
                        "id": sample.get("id"),
                        "task": sample.get("task"),
                        "prediction": normalize_prediction(raw_prediction),
                        "raw_prediction": raw_prediction.strip(),
                        "gold": sample.get("output"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(f"Wrote {len(samples)} predictions to {output_path}")


if __name__ == "__main__":
    main()
