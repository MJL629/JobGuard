"""
LLM 统一调用网关

封装多模型 API，提供统一的 chat 和 embed 接口。
骨架阶段：未配置 API Key 时返回 mock 响应，保证系统可启动可调试。
"""

import os
import logging
from typing import Optional, AsyncGenerator

from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

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
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
        "role": "reasoning",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "default_model": "BAAI/bge-m3",
        "role": "embedding",
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
            if not api_key or api_key.startswith("your_"):
                self._clients[name] = None
                self._mock_mode[name] = True
                logger.warning(
                    f"[LLMGateway] Provider '{name}' 未配置 API Key，将使用 Mock 模式"
                )
            else:
                self._clients[name] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=config["base_url"],
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
        if provider not in PROVIDERS:
            raise ValueError(f"未知的 Provider: {provider}")

        if model is None:
            model = PROVIDERS[provider]["default_model"]

        if self._is_mock(provider):
            if stream:
                async def mock_stream():
                    yield MOCK_RESPONSES["chat"]
                return mock_stream()
            return MOCK_RESPONSES["chat"]

        client = self._clients[provider]
        try:
            if stream:
                return self._stream_chat(client, model, messages, temperature, max_tokens)
            else:
                import time as _time
                _start = _time.time()
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content
                _duration = (_time.time() - _start) * 1000
                # 记录 LLM 调用指标
                try:
                    _tokens = response.usage.total_tokens if response.usage else max(len(content) // 2, 1)
                except Exception:
                    _tokens = max(len(content) // 2, 1)
                try:
                    from app.monitoring import metrics
                    metrics.record_llm_call(
                        provider=provider, model=model,
                        tokens=_tokens, duration_ms=_duration,
                    )
                except Exception:
                    pass
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
    ) -> str | AsyncGenerator[str, None]:
        """使用主力模型（智谱 GLM-4-Flash）"""
        return await self.chat(messages, provider="zhipu", stream=stream)

    async def chat_reasoning(
        self,
        messages: list[dict],
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """使用推理模型（DeepSeek V3）"""
        return await self.chat(
            messages, provider="deepseek", model="deepseek-v4-flash", temperature=0.3, stream=stream
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


# 全局单例
llm_gateway = LLMGateway()
