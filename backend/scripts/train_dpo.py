"""Reference-aware DPO on top of the best JobGuard SFT LoRA adapter."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode(tokenizer, row: dict, response: str, max_length: int) -> dict[str, torch.Tensor]:
    prefix = tokenizer.apply_chat_template(
        [{"role": "system", "content": row["system"]}, {"role": "user", "content": row["prompt"]}],
        tokenize=False, add_generation_prompt=True,
    )
    prefix_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
    response_ids = tokenizer(response + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    response_ids = response_ids[: max(1, max_length // 2)]
    prompt_budget = max(1, max_length - len(response_ids))
    input_ids = prefix_ids[:prompt_budget] + response_ids
    prefix_length = min(len(prefix_ids), prompt_budget)
    ids = torch.tensor([input_ids], dtype=torch.long)
    labels = ids.clone(); labels[:, :prefix_length] = -100
    return {"input_ids": ids.cuda(), "attention_mask": torch.ones_like(ids).cuda(), "labels": labels.cuda()}


def response_logp(model, batch: dict[str, torch.Tensor]) -> torch.Tensor:
    logits = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"]).logits[:, :-1]
    labels = batch["labels"][:, 1:]
    mask = labels.ne(-100)
    safe_labels = labels.masked_fill(~mask, 0)
    token_logps = logits.log_softmax(-1).gather(-1, safe_labels.unsqueeze(-1)).squeeze(-1)
    return (token_logps * mask).sum(-1) / mask.sum(-1).clamp_min(1)


@torch.no_grad()
def preference_stats(model, tokenizer, rows: list[dict], max_length: int) -> dict:
    model.eval()
    base_wins = policy_wins = 0; margins = []; logps = []
    for row in rows:
        chosen = encode(tokenizer, row, row["chosen"], max_length)
        rejected = encode(tokenizer, row, row["rejected"], max_length)
        with model.disable_adapter():
            base_margin = response_logp(model, chosen) - response_logp(model, rejected)
        policy_chosen = response_logp(model, chosen); policy_rejected = response_logp(model, rejected)
        policy_margin = policy_chosen - policy_rejected
        base_wins += int(base_margin.item() > 0)
        policy_wins += int(policy_margin.item() > 0)
        margins.append(policy_margin.item())
        logps.append((policy_chosen.item(), policy_rejected.item()))
    model.train()
    return {"reference_accuracy": base_wins / len(rows), "preference_accuracy": policy_wins / len(rows),
            "reward_margin": sum(margins) / len(margins), "logps": logps}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen2.5-7B-Instruct")
    parser.add_argument("--sft-adapter", default="/root/autodl-tmp/jobguard_adapters/sft_r16")
    parser.add_argument("--output", type=Path, default=Path("/root/autodl-tmp/jobguard_adapters/dpo_r16"))
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--beta", type=float, default=0.1)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--train-data", type=Path, default=Path("data/post_training/preference_train.jsonl"))
    parser.add_argument("--test-data", type=Path, default=Path("data/post_training/preference_test.jsonl"))
    parser.add_argument("--eval-limit", type=int, default=200)
    args = parser.parse_args()
    random.seed(42)
    torch.manual_seed(42)
    train_rows = load_jsonl(args.train_data)
    test_rows = load_jsonl(args.test_data)[:args.eval_limit]
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map={"": 0}, trust_remote_code=True,
    )
    base.config.use_cache = False
    base.gradient_checkpointing_enable()
    base.enable_input_require_grads()
    model = PeftModel.from_pretrained(base, args.sft_adapter, is_trainable=True)
    before = preference_stats(model, tokenizer, test_rows, args.max_length)
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=args.learning_rate
    )
    losses = []
    started = time.perf_counter()
    model.train()
    for step in range(args.steps):
        row = train_rows[step % len(train_rows)]
        chosen = encode(tokenizer, row, row["chosen"], args.max_length)
        rejected = encode(tokenizer, row, row["rejected"], args.max_length)
        with torch.no_grad(), model.disable_adapter():
            ref_chosen = response_logp(model, chosen)
            ref_rejected = response_logp(model, rejected)
        policy_chosen = response_logp(model, chosen)
        policy_rejected = response_logp(model, rejected)
        advantage = (policy_chosen - policy_rejected) - (ref_chosen - ref_rejected)
        loss = -F.logsigmoid(args.beta * advantage).mean()
        if not torch.isfinite(loss):
            raise RuntimeError(f"non-finite DPO loss at step {step + 1}")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(loss.item())
        print(json.dumps({"step": step + 1, "dpo_loss": round(loss.item(), 6), "advantage": round(advantage.item(), 6)}), flush=True)
    after = preference_stats(model, tokenizer, test_rows, args.max_length)
    pair_improvement_win_rate = sum(
        (ac - ar) > (bc - br) for (bc, br), (ac, ar) in zip(before["logps"], after["logps"])
    ) / len(test_rows)
    kl_to_sft_estimate = sum(
        abs(ac - bc) + abs(ar - br) for (bc, br), (ac, ar) in zip(before["logps"], after["logps"])
    ) / (2 * len(test_rows))
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    report = {
        "steps": args.steps, "beta": args.beta, "learning_rate": args.learning_rate,
        "train_examples": len(train_rows), "test_examples": len(test_rows),
        "sft_preference_accuracy": before["preference_accuracy"],
        "preference_accuracy": after["preference_accuracy"], "reward_margin": after["reward_margin"],
        "win_rate_vs_sft_margin": pair_improvement_win_rate, "kl_to_sft_estimate": kl_to_sft_estimate,
        "final_dpo_loss": round(sum(losses[-5:]) / min(5, len(losses)), 6),
        "duration_s": round(time.perf_counter() - started, 2),
        "max_gpu_memory_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 2),
    }
    (args.output / "experiment_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    Path("data/post_training/dpo_eval_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
