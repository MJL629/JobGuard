import json

import httpx
import pytest

from app.services.live_company_sources import LiveCompanySources


@pytest.mark.asyncio
async def test_official_public_transaction_adapter_keeps_exact_company_only():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="ok")
        payload = {
            "code": 200,
            "result": {
                "records": [
                    {
                        "entname": "广州示例科技有限公司",
                        "uniscid": "91440000EXAMPLE001",
                        "name": "张三",
                        "bidCount": 3,
                    },
                    {"entname": "广州示例科技有限公司分公司", "bidCount": 99},
                ]
            },
        }
        return httpx.Response(200, content=json.dumps(payload).encode("utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LiveCompanySources().query_public_transactions(
            "广州示例科技有限公司", client=client
        )

    assert result["status"] == "success_with_results"
    assert result["result_count"] == 1
    assert result["records"][0]["transaction_count"] == 3
    assert "不证明企业无风险" in result["supports"]


@pytest.mark.asyncio
async def test_web_search_adapter_filters_unrelated_results():
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item><title>广州示例科技有限公司公开报道</title><link>https://news.example.com/1</link><description>企业全称出现在正文</description></item>
      <item><title>其他公司</title><link>https://news.example.com/2</link><description>无关内容</description></item>
    </channel></rss>"""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss.encode("utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await LiveCompanySources().search_public_web_mentions(
            "广州示例科技有限公司", client=client
        )

    assert result["status"] == "success_with_results"
    assert result["result_count"] == 1
    assert result["records"][0]["url"] == "https://news.example.com/1"
    assert "不能据此概括员工口碑" in result["supports"]
