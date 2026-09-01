"""Generate JobGuard SFT v3 predictions with an OpenAI-compatible API.

Use this for the non-GPU baseline/commercial model comparison, for example:

    python backend/scripts/predict_sft_v3_api.py \
      --provider deepseek \
      --model deepseek-chat \
      --data backend/finetune/jobguard_sft_v3/dataset/test.jsonl \
      --output backend/finetune/jobguard_sft_v3/results/deepseek_predictions.jsonl

Supported providers:
- deepseek: uses DEEPSEEK_API_KEY and https://api.deepseek.com/v1
- zhipu: uses ZHIPU_API_KEY and https://open.bigmodel.cn/api/paas/v4
- siliconflow: uses SILICONFLOW_API_KEY and https://api.siliconflow.cn/v1
- vllm_openai: uses VLLM_API_KEY/VLLM_BASE_URL or EMPTY/http://127.0.0.1:8000/v1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any


PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "default_model": "glm-4-flash",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "default_model": "Qwen/Qwen2.5-7B-Instruct",
    },
    "vllm_openai": {
        "base_url": "http://127.0.0.1:8000/v1",
        "api_key_env": "VLLM_API_KEY",
        "default_model": "",
    },
}


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


def build_messages(sample: dict[str, Any]) -> list[dict[str, str]]:
    messages = sample.get("messages") or []
    prompt_messages = [
        {"role": message["role"], "content": message.get("content") or ""}
        for message in messages
        if message.get("role") in {"system", "user"} and message.get("role") != "assistant"
    ]
    if prompt_messages:
        return prompt_messages

    instruction = sample.get("instruction") or ""
    input_text = sample.get("input") or ""
    return [
        {
            "role": "system",
            "content": "你是 JobGuard 的结构化信息抽取与岗位分析助手。请严格输出合法 JSON，不要输出解释文本。",
        },
        {"role": "user", "content": f"{instruction}\n\n{input_text}"},
    ]


def normalize_prediction(text: str) -> str:
    text = (text or "").strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


async def predict_one(
    client,
    model: str,
    sample: dict[str, Any],
    max_tokens: int,
    temperature: float,
    retries: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    last_error = ""
    for attempt in range(retries + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=build_messages(sample),
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return {
                "id": sample.get("id"),
                "task": sample.get("task"),
                "prediction": normalize_prediction(content),
                "raw_prediction": content.strip(),
                "gold": sample.get("output") or ((sample.get("messages") or [{}])[-1].get("content")),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - depends on external service
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                await asyncio.sleep(min(2 ** attempt, 8))
    return {
        "id": sample.get("id"),
        "task": sample.get("task"),
        "prediction": "",
        "raw_prediction": "",
        "gold": sample.get("output") or ((sample.get("messages") or [{}])[-1].get("content")),
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "prompt_tokens": None,
        "completion_tokens": None,
        "error": last_error,
    }


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Generate JobGuard SFT v3 API baseline predictions.")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    model = args.model or provider["default_model"]
    if not model:
        raise SystemExit("请通过 --model 指定模型名")
    base_url = args.base_url or os.getenv(f"{args.provider.upper()}_BASE_URL") or provider["base_url"]
    api_key = args.api_key or os.getenv(provider["api_key_env"])
    if args.provider == "vllm_openai":
        base_url = args.base_url or os.getenv("VLLM_BASE_URL") or provider["base_url"]
        api_key = args.api_key or os.getenv("VLLM_API_KEY") or "EMPTY"
    if not api_key or api_key.startswith("your_"):
        raise SystemExit(f"缺少 API Key，请设置 {provider['api_key_env']} 或传入 --api-key")

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise SystemExit("缺少 openai 依赖，请先安装：pip install openai") from exc

    samples = load_jsonl(Path(args.data), args.limit)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    with output_path.open("w", encoding="utf-8") as out:
        for index, sample in enumerate(samples, start=1):
            row = await predict_one(
                client=client,
                model=model,
                sample=sample,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                retries=args.retries,
            )
            row["provider"] = args.provider
            row["model"] = model
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            if index == 1 or index % 25 == 0 or index == len(samples):
                print(f"Generated {index}/{len(samples)} API predictions")

    print(f"Wrote {len(samples)} predictions to {output_path}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
