"""
LLM 统一调用网关

封装多模型 API，提供统一的 chat 和 embed 接口。
骨架阶段：未配置 API Key 时返回 mock 响应，保证系统可启动可调试。
"""

import os
import logging
import time
from typing import Optional, AsyncGenerator

from openai import AsyncOpenAI
from app.config import settings
from app.observability.tracing import trace_recorder
from app.llm.optimization import TTLResponseCache, choose_provider, compact_messages

logger = logging.getLogger(__name__)
response_cache = TTLResponseCache()

# ─── Mock 响应（骨架阶段用）─────────────────────────────────────────────

MOCK_RESPONSES = {
    "chat": "[Mock] LLM 未配置，请设置 API Key 后重启服务。\n当前为骨架响应，用于调试前端和流程。",
    "embed": [0.0] * 1024,  # 1024 维零向量占位
}


# ─── Provider 配置 ─────────────────────────────────────────────────────

PROVIDERS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "default_model": "glm-4-flash",
        "role": "primary",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "role": "reasoning",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "default_model": "BAAI/bge-m3",
        "role": "embedding",
    },
    "vllm": {
        "base_url_setting": "vllm_base_url",
        "api_key_env": "VLLM_API_KEY",
        "default_model_setting": "vllm_model",
        "role": "local",
        "api_key_optional": True,
    },
}


class LLMGateway:
    """
    统一 LLM 调用入口。
    所有 Agent 通过此网关调用 LLM，不直接依赖特定 API。
    """

    def __init__(self):
        self._clients: dict[str, Optional[AsyncOpenAI]] = {}
        self._mock_mode: dict[str, bool] = {}

        for name, config in PROVIDERS.items():
            api_key = getattr(settings, config["api_key_env"].lower(), "")
            if (not api_key or api_key.startswith("your_")) and not config.get("api_key_optional"):
                self._clients[name] = None
                self._mock_mode[name] = True
                logger.warning(
                    f"[LLMGateway] Provider '{name}' 未配置 API Key，将使用 Mock 模式"
                )
            else:
                base_url = (
                    getattr(settings, config["base_url_setting"])
                    if "base_url_setting" in config
                    else config["base_url"]
                )
                self._clients[name] = AsyncOpenAI(
                    api_key=api_key or "local-vllm",
                    base_url=base_url,
                )
                self._mock_mode[name] = False
                logger.info(f"[LLMGateway] Provider '{name}' 已就绪")

    def _is_mock(self, provider: str) -> bool:
        return self._mock_mode.get(provider, True)

    # ─── Chat ────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        provider: str = "zhipu",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        prompt_version: str = "unversioned",
        use_cache: bool = False,
        cache_ttl_seconds: float = 3600,
        context_max_chars: int = 16_000,
    ) -> str | AsyncGenerator[str, None]:
        """
        统一聊天接口。

        Args:
            messages: [{"role": "system/user/assistant", "content": "..."}]
            model: 模型名，默认使用 provider 的 default_model
            provider: 服务商名称
            temperature: 温度参数
            max_tokens: 最大输出 token
            stream: 是否流式输出

        Returns:
            str: 非流式时返回完整响应
            AsyncGenerator[str]: 流式时返回逐 token 生成器
        """
        provider = {"vllm_local": "vllm"}.get(provider, provider)
        if provider not in PROVIDERS:
            raise ValueError(f"未知的 Provider: {provider}")

        if model is None:
            config = PROVIDERS[provider]
            model = (
                getattr(settings, config["default_model_setting"])
                if "default_model_setting" in config
                else config["default_model"]
            )

        messages = compact_messages(messages, max_chars=context_max_chars)
        cache_key = response_cache.key({
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "prompt_version": prompt_version,
        })
        if use_cache and not stream:
            cached = await response_cache.get(cache_key)
            if cached is not None:
                await trace_recorder.emit({
                    "event": "llm_cache",
                    "status": "hit",
                    "provider": provider,
                    "model": model,
                    "prompt_version": prompt_version,
                })
                return cached

        if self._is_mock(provider):
            if stream:
                async def mock_stream():
                    yield MOCK_RESPONSES["chat"]
                return mock_stream()
            return MOCK_RESPONSES["chat"]

        client = self._clients[provider]
        started = time.perf_counter()
        try:
            if stream:
                return self._stream_chat(client, model, messages, temperature, max_tokens)
            else:
                async with trace_recorder.span(
                    name="llm.chat", kind="llm", provider=provider, model=model
                ):
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    usage = response.usage
                    await trace_recorder.emit({
                        "event": "llm_usage",
                        "provider": provider,
                        "model": model,
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                        "total_tokens": getattr(usage, "total_tokens", None),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        "prompt_version": prompt_version,
                        "cache_status": "miss" if use_cache else "disabled",
                    })
                content = response.choices[0].message.content
                if use_cache:
                    await response_cache.set(cache_key, content, cache_ttl_seconds)
                return content
        except Exception as e:
            logger.error(f"[LLMGateway] chat 调用失败 (provider={provider}): {e}")
            raise

    async def _stream_chat(
        self, client, model: str, messages: list[dict], temperature: float, max_tokens: int
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ─── Embedding ───────────────────────────────────────────────────

    async def embed(
        self,
        texts: list[str],
        model: str = "BAAI/bge-m3",
        provider: str = "siliconflow",
    ) -> list[list[float]]:
        """
        统一 Embedding 接口。

        Args:
            texts: 待向量化的文本列表
            model: Embedding 模型名
            provider: 服务商名称

        Returns:
            向量列表，每个向量维度取决于模型
        """
        if self._is_mock(provider):
            return [MOCK_RESPONSES["embed"] for _ in texts]

        client = self._clients[provider]
        try:
            response = await client.embeddings.create(
                model=model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"[LLMGateway] embed 调用失败: {e}")
            raise

    # ─── 便捷方法 ─────────────────────────────────────────────────────

    async def chat_primary(
        self,
        messages: list[dict],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        prompt_version: str = "unversioned",
        use_cache: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """使用主力模型（智谱 GLM-4-Flash）"""
        provider = settings.llm_primary_provider
        # 旧环境中的 vllm_local 并不是已注册的 provider；本机答辩不启动
        # vLLM 时优先使用已配置的云模型，避免连接本地 6006 端口后无回复。
        if provider == "vllm_local":
            provider = "deepseek" if not self._is_mock("deepseek") else "zhipu"
        return await self.chat(
            messages,
            provider=provider,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
            use_cache=use_cache,
        )

    async def chat_routed(
        self,
        messages: list[dict],
        *,
        task_type: str = "general",
        prompt_version: str = "unversioned",
        use_cache: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Choose a model tier from task complexity and record the decision."""
        decision = choose_provider(
            messages,
            task_type=task_type,
            local_available=not self._is_mock("vllm"),
        )
        provider = decision.provider
        if self._is_mock(provider):
            provider = settings.llm_primary_provider
        await trace_recorder.emit({
            "event": "model_route",
            "task_type": task_type,
            "provider": provider,
            "reason": decision.reason,
            "complexity": decision.complexity,
            "prompt_version": prompt_version,
        })
        return await self.chat(
            messages,
            provider=provider,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_version=prompt_version,
            use_cache=use_cache,
        )

    async def chat_reasoning(
        self,
        messages: list[dict],
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """使用推理模型（DeepSeek V4 Flash，默认启用 thinking）"""
        return await self.chat(
            messages, provider="deepseek", model="deepseek-reasoner", temperature=0.3, stream=stream
        )

    async def chat_with_long_context(
        self,
        messages: list[dict],
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """使用长文本模型（智谱 GLM-4-Flash 128K）"""
        return await self.chat(
            messages, provider="zhipu", model="glm-4-flash", stream=stream
        )

    async def chat_local(
        self,
        messages: list[dict],
        stream: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str | AsyncGenerator[str, None]:
        """Use the configured self-hosted vLLM service."""
        return await self.chat(
            messages,
            provider="vllm",
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
        )


# 全局单例
llm_gateway = LLMGateway()
