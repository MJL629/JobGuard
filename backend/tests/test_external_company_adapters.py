import json

import httpx
import pytest

from app.services.external_company_adapters import ExternalCompanyAdapters


@pytest.mark.asyncio
async def test_qichacha_adapter_returns_not_configured_without_keys(monkeypatch):
    monkeypatch.setattr("app.config.settings.qichacha_app_key", "")
    monkeypatch.setattr("app.config.settings.qichacha_secret_key", "")

    result = await ExternalCompanyAdapters().query_qichacha_company("广州示例科技有限公司")

    assert result["status"] == "not_configured"
    assert result["records"] == []


@pytest.mark.asyncio
async def test_qichacha_adapter_calls_real_shape_with_auth_headers(monkeypatch):
    monkeypatch.setattr("app.config.settings.qichacha_app_key", "appkey123")
    monkeypatch.setattr("app.config.settings.qichacha_secret_key", "secret456")
    monkeypatch.setattr("app.config.settings.qichacha_base_url", "https://api.qichacha.test")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["token"] = request.headers.get("Token")
        captured["timespan"] = request.headers.get("Timespan")
        payload = {"Status": "200", "Result": [{"Name": "广州示例科技有限公司"}]}
        return httpx.Response(200, content=json.dumps(payload).encode("utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ExternalCompanyAdapters().query_qichacha_company(
            "广州示例科技有限公司", client=client
        )

    assert result["status"] == "success_with_results"
    assert result["records"][0]["Name"] == "广州示例科技有限公司"
    assert "searchKey=" in captured["url"]
    assert captured["token"]
    assert captured["timespan"]


@pytest.mark.asyncio
async def test_aliyun_adapter_returns_not_configured_without_appcode(monkeypatch):
    monkeypatch.setattr("app.config.settings.aliyun_company_appcode", "")
    monkeypatch.setattr("app.config.settings.aliyun_company_query_url", "")

    result = await ExternalCompanyAdapters().query_aliyun_company_api("广州示例科技有限公司")

    assert result["status"] == "not_configured"
    assert result["records"] == []
