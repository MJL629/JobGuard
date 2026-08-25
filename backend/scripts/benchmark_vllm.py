"""Benchmark an OpenAI-compatible vLLM server with streaming requests."""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings


PROMPT = "解释一下vLLM中的PagedAttention"
DEFAULT_OUTPUT = Path(__file__).with_name("benchmark_result.json")


async def run_request(client: AsyncOpenAI, request_number: int) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_at: float | None = None
    completion_tokens: int | None = None
    generated_text = ""

    stream = await client.chat.completions.create(
        model=settings.vllm_model,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=0.3,
        max_tokens=1024,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            completion_tokens = getattr(usage, "completion_tokens", completion_tokens)
        choices = getattr(chunk, "choices", None) or []
        content = getattr(choices[0].delta, "content", None) if choices else None
        if content:
            if first_token_at is None:
                first_token_at = time.perf_counter()
            generated_text += content

    finished = time.perf_counter()
    total_seconds = finished - started
    ttft_seconds = (first_token_at - started) if first_token_at else None
    generation_seconds = (finished - first_token_at) if first_token_at else None
    tokens_per_second = (
        completion_tokens / generation_seconds
        if completion_tokens is not None and generation_seconds and generation_seconds > 0
        else None
    )
    return {
        "request": request_number,
        "ttft_ms": round(ttft_seconds * 1000, 3) if ttft_seconds is not None else None,
        "total_time_ms": round(total_seconds * 1000, 3),
        "completion_tokens": completion_tokens,
        "tokens_per_second": round(tokens_per_second, 3) if tokens_per_second is not None else None,
        "output_characters": len(generated_text),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def values(name: str) -> list[float]:
        return [float(item[name]) for item in results if item[name] is not None]

    summary: dict[str, Any] = {"successful_requests": len(results)}
    for field in ("ttft_ms", "total_time_ms", "completion_tokens", "tokens_per_second"):
        samples = values(field)
        summary[field] = {
            "mean": round(statistics.fmean(samples), 3),
            "min": round(min(samples), 3),
            "max": round(max(samples), 3),
        } if samples else None
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.requests < 1:
        parser.error("--requests must be at least 1")
    if not settings.vllm_base_url or not settings.vllm_model:
        parser.error("VLLM_BASE_URL and VLLM_MODEL must be configured")

    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key=settings.vllm_api_key or "EMPTY",
    )
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str | int]] = []
    benchmark_started = time.perf_counter()
    for request_number in range(1, args.requests + 1):
        try:
            result = await run_request(client, request_number)
            results.append(result)
            print(
                f"[{request_number}/{args.requests}] "
                f"TTFT={result['ttft_ms']} ms total={result['total_time_ms']} ms "
                f"tokens/s={result['tokens_per_second']}"
            )
        except Exception as exc:
            errors.append({"request": request_number, "error": type(exc).__name__})
            print(f"[{request_number}/{args.requests}] failed: {type(exc).__name__}: {exc}")

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": settings.vllm_base_url,
        "model": settings.vllm_model,
        "prompt": PROMPT,
        "requested_requests": args.requests,
        "wall_time_seconds": round(time.perf_counter() - benchmark_started, 3),
        "summary": summarize(results),
        "results": results,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved benchmark results to: {args.output.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
