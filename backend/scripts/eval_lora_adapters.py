"""Evaluate LoRA adapters on held-out JSON extraction examples."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.eval.jobguard_metrics import aggregate, score_record  # noqa: E402


def parse_json(text: str) -> dict | None:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen2.5-7B-Instruct")
    parser.add_argument("--adapter-root", type=Path, default=Path("/root/autodl-tmp/jobguard_adapters"))
    parser.add_argument("--data", type=Path, default=Path("data/post_training/sft_test.jsonl"))
    parser.add_argument("--ranks", default="4,8,16")
    parser.add_argument("--adapter-paths", default="", help="Optional name=path pairs; overrides --ranks")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("data/post_training/sft_eval_report.json"))
    parser.add_argument("--predictions-dir", type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines()][:args.limit]
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    reports = []
    adapters = ([(name, Path(path)) for item in args.adapter_paths.split(",") for name, path in [item.split("=", 1)]]
                if args.adapter_paths else [(f"r{r}", args.adapter_root / f"sft_r{r}") for r in (int(value) for value in args.ranks.split(","))])
    for name, adapter_path in adapters:
        base = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True)
        model = PeftModel.from_pretrained(base, adapter_path).eval()
        scores = []; predictions = []; started = time.perf_counter()
        with torch.no_grad():
            for row in rows:
                prompt = tokenizer.apply_chat_template(
                    [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["prompt"]}],
                    tokenize=False, add_generation_prompt=True,
                )
                inputs = tokenizer(prompt, return_tensors="pt").to("cuda")
                generated = model.generate(**inputs, max_new_tokens=256, do_sample=False)
                prediction = parse_json(tokenizer.decode(generated[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True))
                expected = json.loads(row["response"])
                scores.append(score_record(prediction, expected))
                predictions.append({"id": row.get("source_id", row.get("id")), "prediction": prediction})
        report = {"adapter": name, **aggregate(scores), "duration_s": round(time.perf_counter()-started, 2)}
        reports.append(report)
        if args.predictions_dir:
            args.predictions_dir.mkdir(parents=True, exist_ok=True)
            (args.predictions_dir/f"{name}.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in predictions),encoding="utf-8")
        del model, base
        torch.cuda.empty_cache()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False))


if __name__ == "__main__":
    main()
