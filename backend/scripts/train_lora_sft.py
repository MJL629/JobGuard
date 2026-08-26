"""Minimal reproducible LoRA SFT experiment for Qwen JD extraction."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode(tokenizer, row: dict, max_length: int) -> dict[str, torch.Tensor]:
    prefix = tokenizer.apply_chat_template(
        [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["prompt"]}],
        tokenize=False, add_generation_prompt=True,
    )
    prefix_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
    response_ids = tokenizer(row["response"] + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    # Tokenizing the full string with right truncation can remove the entire answer for long JDs,
    # producing an all--100 label tensor and NaN loss. Reserve at least half the window for targets.
    response_ids = response_ids[: max(1, max_length // 2)]
    prompt_budget = max(1, max_length - len(response_ids))
    input_ids = prefix_ids[:prompt_budget] + response_ids
    prefix_length = min(len(prefix_ids), prompt_budget)
    ids = torch.tensor([input_ids], dtype=torch.long)
    labels = ids.clone()
    labels[:, :prefix_length] = -100
    return {"input_ids": ids.cuda(), "attention_mask": torch.ones_like(ids).cuda(), "labels": labels.cuda()}


@torch.no_grad()
def evaluate(model, tokenizer, rows: list[dict], max_length: int, limit: int = 10) -> float:
    model.eval()
    losses = []
    for row in rows[:limit]:
        batch = encode(tokenizer, row, max_length)
        losses.append(model(**batch).loss.item())
    model.train()
    return sum(losses) / len(losses)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen2.5-7B-Instruct")
    parser.add_argument("--r", type=int, required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--train-data", type=Path, default=Path("data/post_training/sft_train.jsonl"))
    parser.add_argument("--val-data", type=Path, default=Path("data/post_training/sft_val.jsonl"))
    parser.add_argument("--eval-limit", type=int, default=75)
    parser.add_argument("--output-root", type=Path, default=Path("/root/autodl-tmp/jobguard_adapters"))
    args = parser.parse_args()
    random.seed(42)
    torch.manual_seed(42)

    train_rows = load_jsonl(args.train_data)
    val_rows = load_jsonl(args.val_data)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    config = LoraConfig(
        r=args.r, lora_alpha=args.r * 2, lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=2e-4)
    order = list(range(len(train_rows)))
    losses = []
    started = time.perf_counter()
    optimizer.zero_grad(set_to_none=True)
    for step in range(args.steps * args.grad_accum):
        if step % len(order) == 0:
            random.shuffle(order)
        row = train_rows[order[step % len(order)]]
        loss = model(**encode(tokenizer, row, args.max_length)).loss / args.grad_accum
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite loss at micro-step {step + 1}")
        loss.backward()
        if (step + 1) % args.grad_accum == 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item() * args.grad_accum)
            print(json.dumps({"r": args.r, "step": len(losses), "loss": round(losses[-1], 5)}), flush=True)

    eval_loss = evaluate(model, tokenizer, val_rows, args.max_length, args.eval_limit)
    output = args.output_root / f"sft_r{args.r}"
    output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output)
    tokenizer.save_pretrained(output)
    report = {
        "r": args.r, "steps": args.steps, "train_examples": len(train_rows),
        "val_examples": len(val_rows), "eval_examples": min(args.eval_limit, len(val_rows)), "trainable_params": trainable,
        "final_train_loss": round(sum(losses[-5:]) / min(5, len(losses)), 6),
        "eval_loss": round(eval_loss, 6),
        "duration_s": round(time.perf_counter() - started, 2),
        "max_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
    }
    (output / "experiment_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
