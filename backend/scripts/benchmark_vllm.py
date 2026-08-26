"""Small streaming benchmark for an OpenAI-compatible vLLM endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx


PROMPT = "请用三点说明大模型应用中为什么需要全链路可观测性，每点一句话。"


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)
    return round(ordered[index], 2)


async def one_request(client: httpx.AsyncClient, url: str, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0.2,
        "max_tokens": 64,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    started = time.perf_counter()
    first_token = None
    completion_tokens = 0
    async with client.stream("POST", f"{url}/chat/completions", json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            choices = chunk.get("choices", [])
            if choices and choices[0].get("delta", {}).get("content") and first_token is None:
                first_token = time.perf_counter()
            if chunk.get("usage"):
                completion_tokens = chunk["usage"].get("completion_tokens", 0)
    ended = time.perf_counter()
    return {
        "ttft_ms": (first_token - started) * 1000 if first_token else None,
        "e2e_ms": (ended - started) * 1000,
        "completion_tokens": completion_tokens,
        "tpot_ms": (
            ((ended - first_token) * 1000) / max(1, completion_tokens - 1)
            if first_token and completion_tokens
            else None
        ),
    }


async def run_level(url: str, model: str, concurrency: int) -> dict:
    request_count = max(8, concurrency * 2)
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=120) as client:
        async def limited() -> dict:
            async with semaphore:
                return await one_request(client, url, model)

        started = time.perf_counter()
        results = await asyncio.gather(*(limited() for _ in range(request_count)))
        duration = time.perf_counter() - started

    ttfts = [r["ttft_ms"] for r in results if r["ttft_ms"] is not None]
    e2es = [r["e2e_ms"] for r in results]
    tpots = [r["tpot_ms"] for r in results if r["tpot_ms"] is not None]
    output_tokens = sum(r["completion_tokens"] for r in results)
    return {
        "concurrency": concurrency,
        "requests": request_count,
        "duration_s": round(duration, 3),
        "success_rate": 1.0,
        "request_throughput_rps": round(request_count / duration, 3),
        "output_throughput_tps": round(output_tokens / duration, 3),
        "ttft_ms_p50": percentile(ttfts, 0.50),
        "ttft_ms_p95": percentile(ttfts, 0.95),
        "tpot_ms_p50": percentile(tpots, 0.50),
        "tpot_ms_p95": percentile(tpots, 0.95),
        "e2e_ms_p50": percentile(e2es, 0.50),
        "e2e_ms_p95": percentile(e2es, 0.95),
    }


async def run(args: argparse.Namespace) -> dict:
    levels = [int(value) for value in args.concurrency.split(",")]
    results = []
    for level in levels:
        result = await run_level(args.url.rstrip("/"), args.model, level)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    return {"url": args.url, "model": args.model, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6006/v1")
    parser.add_argument("--model", default="qwen2.5-7b")
    parser.add_argument("--concurrency", default="1,4,8,16")
    parser.add_argument("--output", type=Path, default=Path("data/eval/vllm_benchmark.json"))
    args = parser.parse_args()
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
