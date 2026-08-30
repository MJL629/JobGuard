"""Real external company data adapters.

The adapters in this module call real third-party APIs when credentials are
configured.  They never fabricate fallback data: missing credentials return a
``not_configured`` status and upstream failures return explicit error states.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings


class ExternalCompanyAdapters:
    """Company-data adapters for authenticated external APIs."""

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds or settings.external_api_timeout_seconds

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _mask(value: str) -> str:
        if not value:
            return ""
        return f"{value[:3]}***{value[-3:]}" if len(value) > 8 else "***"

    @staticmethod
    def _qichacha_token(app_key: str, secret_key: str, timespan: str) -> str:
        raw = f"{app_key}{timespan}{secret_key}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    @classmethod
    def qichacha_configured(cls) -> bool:
        return bool(settings.qichacha_app_key and settings.qichacha_secret_key)

    @classmethod
    def aliyun_configured(cls) -> bool:
        return bool(settings.aliyun_company_appcode and settings.aliyun_company_query_url)

    async def query_qichacha_company(
        self,
        company_name: str,
        *,
        endpoint: str = "/ECIV4/Search",
        page_index: int = 1,
        page_size: int = 10,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Call Qichacha OpenAPI with AppKey/SecretKey auth.

        The default endpoint uses enterprise search.  If the account has access
        to a different product path, callers may pass the endpoint configured in
        the Qichacha console, while keeping the same authentication mechanism.
        """
        name = str(company_name or "").strip()
        if len(name) < 2:
            raise ValueError("企业名称不能为空")
        if not self.qichacha_configured():
            return {
                "adapter": "qichacha_openapi",
                "status": "not_configured",
                "company_name": name,
                "queried_at": self._now(),
                "records": [],
                "result_count": 0,
                "message": "未配置 QICHACHA_APP_KEY / QICHACHA_SECRET_KEY",
            }

        safe_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        timespan = str(int(time.time()))
        app_key = settings.qichacha_app_key
        headers = {
            "Token": self._qichacha_token(app_key, settings.qichacha_secret_key, timespan),
            "Timespan": timespan,
            "User-Agent": "JobGuard/1.0 company-risk-adapter",
            "Accept": "application/json",
        }
        url = f"{settings.qichacha_base_url.rstrip('/')}{safe_endpoint}"
        owns_client = client is None
        request_client = client or httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds))
        try:
            response = await request_client.get(
                url,
                headers=headers,
                params={
                    "key": app_key,
                    "searchKey": name,
                    "pageIndex": max(1, int(page_index)),
                    "pageSize": max(1, min(int(page_size), 20)),
                },
            )
            response.raise_for_status()
            payload = response.json()
            records = self._extract_records(payload)
            return {
                "adapter": "qichacha_openapi",
                "status": "success_with_results" if records else "success_no_results",
                "company_name": name,
                "endpoint": safe_endpoint,
                "queried_at": self._now(),
                "source_name": "企查查开放平台",
                "source_url": "https://openapi.qcc.com/",
                "credential": self._mask(app_key),
                "result_count": len(records),
                "records": records[:20],
                "raw_status": payload.get("Status") or payload.get("status"),
                "raw_message": payload.get("Message") or payload.get("message"),
                "supports": "企业工商/主体搜索数据来自企查查开放平台，具体字段以账号开通接口权限为准",
            }
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            return {
                "adapter": "qichacha_openapi",
                "status": "upstream_error",
                "company_name": name,
                "endpoint": safe_endpoint,
                "queried_at": self._now(),
                "records": [],
                "result_count": 0,
                "error": str(exc)[:300],
            }
        finally:
            if owns_client:
                await request_client.aclose()

    async def query_aliyun_company_api(
        self,
        company_name: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Call an Aliyun Marketplace company API using APPCODE auth."""
        name = str(company_name or "").strip()
        if len(name) < 2:
            raise ValueError("企业名称不能为空")
        if not self.aliyun_configured():
            return {
                "adapter": "aliyun_market_company_api",
                "status": "not_configured",
                "company_name": name,
                "queried_at": self._now(),
                "records": [],
                "result_count": 0,
                "message": "未配置 ALIYUN_COMPANY_APPCODE / ALIYUN_COMPANY_QUERY_URL",
            }

        owns_client = client is None
        request_client = client or httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds))
        try:
            response = await request_client.get(
                settings.aliyun_company_query_url,
                headers={
                    "Authorization": f"APPCODE {settings.aliyun_company_appcode}",
                    "User-Agent": "JobGuard/1.0 company-risk-adapter",
                    "Accept": "application/json",
                },
                params={"keyword": name, "companyName": name, "name": name},
            )
            response.raise_for_status()
            payload = response.json()
            records = self._extract_records(payload)
            return {
                "adapter": "aliyun_market_company_api",
                "status": "success_with_results" if records else "success_no_results",
                "company_name": name,
                "queried_at": self._now(),
                "source_name": "阿里云市场企业数据接口",
                "source_url": settings.aliyun_company_query_url,
                "result_count": len(records),
                "records": records[:20],
                "supports": "企业工商/风险字段来自已配置的阿里云市场 API 商品，字段语义以该商品文档为准",
            }
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            return {
                "adapter": "aliyun_market_company_api",
                "status": "upstream_error",
                "company_name": name,
                "queried_at": self._now(),
                "records": [],
                "result_count": 0,
                "error": str(exc)[:300],
            }
        finally:
            if owns_client:
                await request_client.aclose()

    async def lookup_company(self, company_name: str) -> list[dict[str, Any]]:
        qichacha, aliyun = await self._gather_company_sources(company_name)
        return [qichacha, aliyun]

    async def _gather_company_sources(self, company_name: str) -> tuple[dict, dict]:
        import asyncio

        return await asyncio.gather(
            self.query_qichacha_company(company_name),
            self.query_aliyun_company_api(company_name),
        )

    @staticmethod
    def _extract_records(payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("Result", "result", "Data", "data", "records", "items", "list", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = ExternalCompanyAdapters._extract_records(value)
                if nested:
                    return nested
                if value:
                    return [value]
        return []


external_company_adapters = ExternalCompanyAdapters()
