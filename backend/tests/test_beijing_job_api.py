import httpx
import pytest

from app.services.beijing_job_api_service import (
    BeijingJobAPIError,
    BeijingJobAPIService,
    BeijingJobPage,
    BeijingJobTransportError,
)


def test_extracts_common_nested_record_shape_and_total():
    payload = {
        "code": 200,
        "data": {
            "rows": [{"企业名称": "示例公司", "岗位名称": "Python工程师"}],
            "totalCount": 20220,
        },
    }
    assert BeijingJobAPIService.extract_records(payload)[0]["企业名称"] == "示例公司"
    assert BeijingJobAPIService.extract_total(payload) == 20220


def test_extracts_official_page_shape():
    payload = {
        "status": 200,
        "page": {
            "content": [{"企业名称": "示例公司", "岗位名称": "前端工程师"}],
            "total": 1,
        },
        "object": None,
    }
    assert BeijingJobAPIService.extract_records(payload)[0]["岗位名称"] == "前端工程师"
    assert BeijingJobAPIService.extract_total(payload) == 1


def test_computer_filter_requires_title_signal_or_conditional_tech_evidence():
    service = BeijingJobAPIService()
    records = [
        {"岗位名称": "Python后端工程师", "岗位要求": "熟悉 FastAPI"},
        {"岗位名称": "产品经理", "岗位要求": "负责软件开发和 API 产品设计"},
        {"岗位名称": "销售经理", "岗位要求": "会使用计算机办公软件"},
        {"岗位名称": "保洁员", "岗位要求": "身体健康"},
    ]
    selected, summary = service.filter_computer_jobs(records)
    assert [item["岗位名称"] for item in selected] == ["Python后端工程师", "产品经理"]
    assert summary["computer_records"] == 2
    assert summary["excluded_records"] == 2


def test_generic_titles_require_two_specific_it_evidence_signals():
    service = BeijingJobAPIService()
    records = [
        {"岗位名称": "运维工程师", "岗位要求": "5年以上水厂运营经验"},
        {"岗位名称": "空调运维", "岗位要求": "负责制冷设备维修和加氟"},
        {"岗位名称": "系统工程师", "岗位要求": "物理学、光学或机械专业"},
        {"岗位名称": "产品经理", "岗位要求": "食品产品经验，能够进行数据分析"},
        {"岗位名称": "运维工程师", "岗位要求": "熟悉 Linux 操作系统和 MySQL 数据库"},
        {"岗位名称": "系统工程师", "岗位要求": "熟悉 Python 编程及服务器部署"},
    ]
    selected, summary = service.filter_computer_jobs(records)
    assert [item["岗位名称"] for item in selected] == ["运维工程师", "系统工程师"]
    assert summary["excluded_records"] == 4


@pytest.mark.asyncio
async def test_fetch_page_parses_json_without_exposing_key():
    def handler(request: httpx.Request):
        assert request.url.params["currentPage"] == "1"
        return httpx.Response(200, json={
            "data": [{"企业名称": "示例公司", "岗位名称": "Java工程师"}],
            "total": 1,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await BeijingJobAPIService().fetch_page(
            "localSecretKey123",
            page=1,
            page_size=100,
            client=client,
        )
    assert page.total == 1
    assert page.records[0]["岗位名称"] == "Java工程师"


@pytest.mark.asyncio
async def test_permission_error_does_not_contain_key():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403))
    ) as client:
        with pytest.raises(BeijingJobAPIError) as error:
            await BeijingJobAPIService().fetch_page(
                "localSecretKey123",
                page=1,
                page_size=100,
                client=client,
            )
    assert "localSecretKey123" not in str(error.value)


@pytest.mark.asyncio
async def test_fetch_all_stops_at_reported_total(monkeypatch):
    service = BeijingJobAPIService()

    async def fake_fetch_page(user_key, *, page, page_size, client=None):
        records = [{"岗位名称": f"Python工程师{index}"} for index in range(2)]
        return BeijingJobPage(records=records, total=4, page=page, page_size=page_size)

    monkeypatch.setattr(service, "fetch_page", fake_fetch_page)
    result = await service.fetch_all("localSecretKey123", page_size=2, max_pages=10)
    assert len(result) == 4


@pytest.mark.asyncio
async def test_fetch_all_continues_when_server_caps_page_size(monkeypatch):
    service = BeijingJobAPIService()

    async def fake_fetch_page(user_key, *, page, page_size, client=None):
        return BeijingJobPage(
            records=[{"岗位名称": f"Python工程师{page}"}],
            total=3,
            page=page,
            page_size=page_size,
        )

    monkeypatch.setattr(service, "fetch_page", fake_fetch_page)
    result = await service.fetch_all("localSecretKey123", page_size=500, max_pages=10)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_fetch_all_falls_back_to_edge_without_putting_key_in_start_command(monkeypatch):
    requested_urls = []

    class FakeEdgeTransport:
        def start(self):
            return None

        def get_json(self, url):
            requested_urls.append(url)
            return 200, {
                "status": 200,
                "page": {
                    "content": [{"企业名称": "示例公司", "岗位名称": "Python工程师"}],
                    "total": 1,
                },
            }

        def close(self):
            return None

    service = BeijingJobAPIService(edge_transport_factory=FakeEdgeTransport)

    async def fail_regular_transport(user_key, *, page, page_size, client=None):
        raise BeijingJobTransportError("TLS handshake failed")

    monkeypatch.setattr(service, "fetch_page", fail_regular_transport)
    result = await service.fetch_all("localSecretKey123", page_size=100, max_pages=2)
    assert result[0]["岗位名称"] == "Python工程师"
    assert service.transport_used == "edge"
    assert len(requested_urls) == 1


@pytest.mark.asyncio
async def test_edge_permission_error_does_not_contain_key(monkeypatch):
    class FakeEdgeTransport:
        def start(self):
            return None

        def get_json(self, url):
            return 404, {"status": 404, "msg": "not found", "page": None}

        def close(self):
            return None

    service = BeijingJobAPIService(edge_transport_factory=FakeEdgeTransport)

    async def fail_regular_transport(user_key, *, page, page_size, client=None):
        raise BeijingJobTransportError("TLS handshake failed")

    monkeypatch.setattr(service, "fetch_page", fail_regular_transport)
    with pytest.raises(BeijingJobAPIError) as error:
        await service.fetch_all("localSecretKey123", page_size=100, max_pages=2)
    assert "localSecretKey123" not in str(error.value)
    assert "CSV" in str(error.value)


def test_invalid_key_is_rejected_locally():
    with pytest.raises(BeijingJobAPIError):
        BeijingJobAPIService._validate_key("short")
