"""Train JobGuard SFT v3 LoRA adapter.

This script is intended for the GPU server.  It keeps training dependencies out
of the normal FastAPI runtime; install ``backend/finetune/jobguard_sft_v3/
training_requirements.txt`` before running it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "finetune" / "jobguard_sft_v3" / "sft_lora_config.json"


def require_training_deps():
    try:
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
        from trl import SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            "缺少训练依赖。请先运行：\n"
            "pip install -r backend/finetune/jobguard_sft_v3/training_requirements.txt"
        ) from exc
    return load_dataset, LoraConfig, AutoModelForCausalLM, AutoTokenizer, TrainingArguments, SFTTrainer


def format_messages(example: dict, tokenizer) -> dict:
    text = tokenizer.apply_chat_template(
        example["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text, "task": example.get("task"), "label_quality": example.get("label_quality")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--smoke", action="store_true", help="Only load 32 train / 16 val samples")
    args = parser.parse_args()

    load_dataset, LoraConfig, AutoModelForCausalLM, AutoTokenizer, TrainingArguments, SFTTrainer = require_training_deps()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    dataset_dir = ROOT.parent / config["dataset_dir"]
    output_dir = ROOT.parent / config["output_dir"]

    data_files = {
        "train": str(dataset_dir / "train.jsonl"),
        "validation": str(dataset_dir / "val.jsonl"),
    }
    dataset = load_dataset("json", data_files=data_files)
    if args.smoke:
        dataset["train"] = dataset["train"].select(range(min(32, len(dataset["train"]))))
        dataset["validation"] = dataset["validation"].select(range(min(16, len(dataset["validation"]))))

    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    dataset = dataset.map(lambda row: format_messages(row, tokenizer), remove_columns=dataset["train"].column_names)

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        trust_remote_code=True,
        torch_dtype="auto",
        device_map="auto",
    )
    model.config.use_cache = False

    lora_config = LoraConfig(
        task_type="CAUSAL_LM",
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["lora_alpha"],
        lora_dropout=config["lora"]["lora_dropout"],
        target_modules=config["lora"]["target_modules"],
    )
    t = config["training"]
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=1 if args.smoke else t["num_train_epochs"],
        per_device_train_batch_size=t["per_device_train_batch_size"],
        per_device_eval_batch_size=t["per_device_eval_batch_size"],
        gradient_accumulation_steps=t["gradient_accumulation_steps"],
        learning_rate=t["learning_rate"],
        warmup_ratio=t["warmup_ratio"],
        weight_decay=t["weight_decay"],
        logging_steps=t["logging_steps"],
        eval_strategy="steps",
        eval_steps=t["eval_steps"],
        save_steps=t["save_steps"],
        bf16=t["bf16"],
        gradient_checkpointing=t["gradient_checkpointing"],
        report_to=[],
        seed=t["seed"],
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        peft_config=lora_config,
        dataset_text_field="text",
        max_seq_length=t["max_seq_length"],
        args=training_args,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    metrics = trainer.evaluate()
    (output_dir / "eval_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(output_dir), "metrics": metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
