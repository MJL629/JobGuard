from types import SimpleNamespace

import pytest

from app.config import settings
from app.llm import gateway as gateway_module
from app.monitoring import metrics


class _Completions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def create(self, **kwargs):
        if self.error:
            raise self.error
        return self.response


def _client(response=None, error=None):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions(response=response, error=error))
    )


class _AsyncChunks:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_vllm_is_optional_and_uses_openai_compatible_config(monkeypatch):
    created = []

    def fake_openai(**kwargs):
        created.append(kwargs)
        return object()

    monkeypatch.setattr(gateway_module, "AsyncOpenAI", fake_openai)
    monkeypatch.setattr(settings, "vllm_model", "local-benchmark-model")
    monkeypatch.setattr(settings, "vllm_base_url", "http://127.0.0.1:9000/v1")
    monkeypatch.setattr(settings, "vllm_api_key", "EMPTY")

    gateway = gateway_module.LLMGateway()

    assert gateway._is_mock("vllm_local") is False
    assert gateway._provider_models["vllm_local"] == "local-benchmark-model"
    assert any(
        item["base_url"] == "http://127.0.0.1:9000/v1"
        and item["api_key"] == "EMPTY"
        for item in created
    )


def test_vllm_without_model_does_not_affect_existing_providers(monkeypatch):
    monkeypatch.setattr(settings, "vllm_model", "")
    gateway = gateway_module.LLMGateway()

    assert gateway._is_mock("vllm_local") is True
    assert "zhipu" in gateway._clients
    assert "deepseek" in gateway._clients


@pytest.mark.asyncio
async def test_chat_records_usage_and_privacy_safe_metadata():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
    )
    gateway = gateway_module.LLMGateway()
    gateway._mock_mode["zhipu"] = False
    gateway._clients["zhipu"] = _client(response=response)

    result = await gateway.chat(
        [{"role": "user", "content": "private prompt must not be recorded"}],
        metadata={"agent_name": "test_agent", "private": "secret"},
    )

    assert result == "ok"
    call = metrics.get_recent_llm_calls(1)[0]
    assert call["agent"] == "test_agent"
    assert call["input_tokens"] == 12
    assert call["output_tokens"] == 3
    assert call["success"] is True
    assert "prompt" not in call
    assert "private" not in call


@pytest.mark.asyncio
async def test_chat_error_is_observed_and_reraised():
    gateway = gateway_module.LLMGateway()
    gateway._mock_mode["zhipu"] = False
    gateway._clients["zhipu"] = _client(error=TimeoutError("timeout"))

    with pytest.raises(TimeoutError):
        await gateway.chat([{"role": "user", "content": "not stored"}])

    call = metrics.get_recent_llm_calls(1)[0]
    assert call["success"] is False
    assert call["error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_stream_records_ttft_and_usage_when_provider_exposes_it():
    chunks = _AsyncChunks([
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=" token"))],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=2),
        ),
    ])
    gateway = gateway_module.LLMGateway()
    gateway._mock_mode["zhipu"] = False
    gateway._clients["zhipu"] = _client(response=chunks)

    stream = await gateway.chat(
        [{"role": "user", "content": "not stored"}],
        stream=True,
        metadata={"agent_name": "stream_agent"},
    )
    content = "".join([part async for part in stream])

    assert content == "first token"
    call = metrics.get_recent_llm_calls(1)[0]
    assert call["stream"] is True
    assert call["ttft_ms"] is not None
    assert call["ttft_ms"] >= 0
    assert call["input_tokens"] == 8
    assert call["output_tokens"] == 2
    assert call["success"] is True


@pytest.mark.asyncio
async def test_metrics_failure_never_breaks_mock_chat(monkeypatch):
    def fail_metrics(**kwargs):
        raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(metrics, "record_llm_call", fail_metrics)
    gateway = gateway_module.LLMGateway()
    gateway._mock_mode["zhipu"] = True

    result = await gateway.chat([{"role": "user", "content": "hello"}])

    assert result == gateway_module.MOCK_RESPONSES["chat"]


@pytest.mark.asyncio
async def test_agent_helpers_route_to_configured_vllm(monkeypatch):
    gateway = gateway_module.LLMGateway()
    calls = []

    async def fake_chat(messages, **kwargs):
        calls.append(kwargs)
        return "local response"

    monkeypatch.setattr(settings, "llm_primary_provider", "vllm_local")
    monkeypatch.setattr(settings, "llm_reasoning_provider", "vllm_local")
    monkeypatch.setattr(gateway, "chat", fake_chat)

    assert await gateway.chat_primary([{"role": "user", "content": "primary"}]) == "local response"
    assert await gateway.chat_reasoning([{"role": "user", "content": "reasoning"}]) == "local response"
    assert calls[0]["provider"] == "vllm_local"
    assert calls[1]["provider"] == "vllm_local"
    assert calls[1]["model"] is None
