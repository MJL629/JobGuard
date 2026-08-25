"""Smoke-test the real JobGuard -> LLMGateway -> vLLM path."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm.gateway import LLMGateway


async def main() -> None:
    gateway = LLMGateway()
    if gateway._is_mock("vllm_local"):
        raise RuntimeError(
            "vllm_local is disabled; set VLLM_BASE_URL, VLLM_API_KEY, and VLLM_MODEL"
        )

    print(f"vLLM endpoint: {settings.vllm_base_url}")
    print(f"model: {settings.vllm_model}")
    response = await gateway.chat(
        messages=[
            {
                "role": "user",
                "content": "解释一下vLLM中的PagedAttention",
            }
        ],
        provider="vllm_local",
        temperature=0.3,
        max_tokens=1024,
    )
    print("\nModel response:\n")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
