"""
LLM 统一调用网关

封装多模型 API，提供统一的 chat 和 embed 接口。
骨架阶段：未配置 API Key 时返回 mock 响应，保证系统可启动可调试。
"""

import base64
import logging
import time
import uuid
from typing import Any, Optional, AsyncGenerator

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
    "vllm_local": {
        "base_url_setting": "vllm_base_url",
        "api_key_setting": "vllm_api_key",
        "model_setting": "vllm_model",
        "default_model": "",
        "role": "local_openai_compatible",
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
        self._provider_models: dict[str, str] = {}

        for name, config in PROVIDERS.items():
            api_key_setting = config.get("api_key_setting") or config["api_key_env"].lower()
            api_key = getattr(settings, api_key_setting, "")
            base_url = getattr(
                settings,
                config.get("base_url_setting", ""),
                config.get("base_url", ""),
            )
            configured_model = getattr(
                settings,
                config.get("model_setting", ""),
                config.get("default_model", ""),
            )
            self._provider_models[name] = configured_model or config.get("default_model", "")

            is_vllm_ready = name != "vllm_local" or bool(base_url and configured_model)
            is_key_ready = bool(api_key) and not api_key.startswith("your_")
            if not is_vllm_ready or not is_key_ready:
                self._clients[name] = None
                self._mock_mode[name] = True
                if name == "vllm_local":
                    logger.info("[LLMGateway] Optional provider 'vllm_local' is disabled")
                else:
                    logger.warning(
                        "[LLMGateway] Provider '%s' 未配置 API Key，将使用 Mock 模式",
                        name,
                    )
            else:
                self._clients[name] = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                )
                self._mock_mode[name] = False
                logger.info("[LLMGateway] Provider '%s' 已就绪", name)

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
        metadata: Optional[dict[str, Any]] = None,
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
            model = self._provider_models.get(provider) or PROVIDERS[provider]["default_model"]
        if not model:
            raise ValueError(f"Provider '{provider}' 未配置模型")

        request_id = uuid.uuid4().hex
        agent_name = self._agent_name(metadata)

        if self._is_mock(provider):
            if stream:
                async def mock_stream():
                    started = time.perf_counter()
                    first_token_at = time.perf_counter()
                    try:
                        yield MOCK_RESPONSES["chat"]
                    finally:
                        self._record_call_safely(
                            request_id=request_id,
                            agent=agent_name,
                            provider=provider,
                            model=model,
                            stream=True,
                            started=started,
                            ttft_ms=(first_token_at - started) * 1000,
                            success=True,
                        )
                return mock_stream()
            started = time.perf_counter()
            self._record_call_safely(
                request_id=request_id,
                agent=agent_name,
                provider=provider,
                model=model,
                stream=False,
                started=started,
                success=True,
            )
            return MOCK_RESPONSES["chat"]

        client = self._clients[provider]
        started = time.perf_counter()
        try:
            if stream:
                return self._stream_chat(
                    client=client,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_id=request_id,
                    agent_name=agent_name,
                    provider=provider,
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                self._record_call_safely(
                    request_id=request_id,
                    agent=agent_name,
                    provider=provider,
                    model=model,
                    stream=False,
                    started=started,
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                    success=True,
                )
                return content
        except Exception as e:
            self._record_call_safely(
                request_id=request_id,
                agent=agent_name,
                provider=provider,
                model=model,
                stream=stream,
                started=started,
                success=False,
                error_type=type(e).__name__,
            )
            logger.error(
                "[LLMGateway] chat 调用失败 (provider=%s, request_id=%s, error_type=%s)",
                provider,
                request_id,
                type(e).__name__,
            )
            raise

    async def _stream_chat(
        self,
        client,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        request_id: str,
        agent_name: Optional[str],
        provider: str,
    ) -> AsyncGenerator[str, None]:
        """流式聊天"""
        started = time.perf_counter()
        ttft_ms: Optional[float] = None
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        error_type: Optional[str] = None
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    input_tokens = getattr(usage, "prompt_tokens", input_tokens)
                    output_tokens = getattr(usage, "completion_tokens", output_tokens)
                choices = getattr(chunk, "choices", None) or []
                content = getattr(choices[0].delta, "content", None) if choices else None
                if content:
                    if ttft_ms is None:
                        ttft_ms = (time.perf_counter() - started) * 1000
                    yield content
        except Exception as exc:
            error_type = type(exc).__name__
            logger.error(
                "[LLMGateway] stream 调用失败 (provider=%s, request_id=%s, error_type=%s)",
                provider,
                request_id,
                error_type,
            )
            raise
        finally:
            self._record_call_safely(
                request_id=request_id,
                agent=agent_name,
                provider=provider,
                model=model,
                stream=True,
                started=started,
                ttft_ms=ttft_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=error_type is None,
                error_type=error_type,
            )

    @staticmethod
    def _agent_name(metadata: Optional[dict[str, Any]]) -> Optional[str]:
        """读取非敏感调用标签；metadata 本身不会被保存。"""
        if not metadata:
            return None
        value = metadata.get("agent_name") or metadata.get("caller")
        return str(value)[:100] if value is not None else None

    @staticmethod
    def _record_call_safely(
        *,
        request_id: str,
        agent: Optional[str],
        provider: str,
        model: str,
        stream: bool,
        started: float,
        ttft_ms: Optional[float] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        success: bool,
        error_type: Optional[str] = None,
    ) -> None:
        """Best-effort metrics: observability must never break model calls."""
        try:
            from app.monitoring import metrics

            metrics.record_llm_call(
                request_id=request_id,
                agent=agent,
                provider=provider,
                model=model,
                stream=stream,
                e2e_latency_ms=(time.perf_counter() - started) * 1000,
                ttft_ms=ttft_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                success=success,
                error_type=error_type,
            )
        except Exception:
            logger.debug("[LLMGateway] metrics recording failed", exc_info=True)

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
        metadata: Optional[dict[str, Any]] = None,
    ) -> str | AsyncGenerator[str, None]:
        """使用主力模型（智谱 GLM-4-Flash）"""
        return await self.chat(
            messages, provider="zhipu", stream=stream, metadata=metadata
        )

    async def vision(
        self,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
        model: str = "glm-4v-flash",
    ) -> str:
        """Analyze an image with Zhipu's multimodal chat endpoint.

        The standard provider credential already configured for text chat is
        reused in memory; image bytes and credentials are never persisted by
        this gateway.
        """
        if self._is_mock("zhipu"):
            raise RuntimeError("视觉模型尚未配置")
        client = self._clients["zhipu"]
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = await client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    },
                ],
            }],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""

    async def chat_reasoning(
        self,
        messages: list[dict],
        stream: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str | AsyncGenerator[str, None]:
        """使用推理模型（DeepSeek V3）"""
        return await self.chat(
            messages, provider="deepseek", model="deepseek-v4-flash",
            temperature=0.3, stream=stream, metadata=metadata,
        )

    async def chat_with_long_context(
        self,
        messages: list[dict],
        stream: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str | AsyncGenerator[str, None]:
        """使用长文本模型（智谱 GLM-4-Flash 128K）"""
        return await self.chat(
            messages, provider="zhipu", model="glm-4-flash",
            stream=stream, metadata=metadata,
        )


# 全局单例
llm_gateway = LLMGateway()
