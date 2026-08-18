"""Free live company-source adapters with explicit evidence boundaries.

The adapters use public, fixed endpoints and never receive browser cookies,
passwords, captchas, or API keys.  A successful query is not the same thing as
an official risk clearance: every result carries a narrow ``supports`` label.
"""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx


class LiveCompanySources:
    GGZY_HOME = "https://data.ggzy.gov.cn/"
    GGZY_SEARCH = "https://data.ggzy.gov.cn/yjcx/index/search"
    BING_RSS = "https://cn.bing.com/search"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
    )

    def __init__(self, *, cache_ttl_seconds: int = 600) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    @staticmethod
    def _normalized(value: str) -> str:
        return "".join(str(value or "").split()).replace("(", "（").replace(")", "）")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def query_public_transactions(
        self,
        company_name: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict:
        """Query the official National Public Resources Trading Platform."""
        normalized = self._normalized(company_name)
        query_url = f"https://data.ggzy.gov.cn/#/search?keyWord={quote(company_name)}"
        result = {
            "adapter": "national_public_resource_transactions",
            "source_name": "全国公共资源交易平台数据服务",
            "source_url": query_url,
            "queried_at": self._now(),
            "status": "temporarily_unavailable",
            "result_count": 0,
            "records": [],
            "supports": "仅支持平台收录的政府采购和公共资源交易成交记录，不证明企业无风险",
        }
        owns_client = client is None
        request_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            follow_redirects=True,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Referer": self.GGZY_HOME,
            },
        )
        try:
            # The public service expects the same anonymous session used by its homepage.
            await request_client.get(self.GGZY_HOME)
            response = await request_client.get(
                self.GGZY_SEARCH,
                params={"keyword": company_name, "pageNo": 1, "pageSize": 10},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 200:
                result["status"] = "source_error"
                return result
            records = []
            for item in (payload.get("result") or {}).get("records") or []:
                if self._normalized(item.get("entname")) != normalized:
                    continue
                records.append(
                    {
                        "company_name": item.get("entname"),
                        "unified_social_credit_code": item.get("uniscid"),
                        "legal_representative": item.get("name"),
                        "established_at": item.get("estdate") or item.get("bfrq"),
                        "transaction_count": item.get("bidCount"),
                    }
                )
            result["records"] = records
            result["result_count"] = len(records)
            result["status"] = "success_with_results" if records else "success_no_results"
            return result
        except (httpx.HTTPError, ValueError, ET.ParseError):
            return result
        finally:
            if owns_client:
                await request_client.aclose()

    async def search_public_web_mentions(
        self,
        company_name: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict:
        """Search a public RSS endpoint and keep only exact-name mentions.

        Results are leads, not employee sentiment samples and not official facts.
        """
        normalized = self._normalized(company_name)
        query_url = f"https://cn.bing.com/search?q={quote(company_name)}"
        result = {
            "adapter": "bing_public_web_search",
            "source_name": "Microsoft Bing 公开网页检索",
            "source_url": query_url,
            "queried_at": self._now(),
            "status": "temporarily_unavailable",
            "result_count": 0,
            "records": [],
            "supports": "仅证明检索结果页面包含企业全称，不能据此概括员工口碑或风险",
        }
        owns_client = client is None
        request_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            follow_redirects=True,
            headers={"User-Agent": self.USER_AGENT},
        )
        try:
            response = await request_client.get(
                self.BING_RSS,
                params={"q": company_name, "format": "rss"},
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
            records = []
            seen_urls: set[str] = set()
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                description = (item.findtext("description") or "").strip()
                url = (item.findtext("link") or "").strip()
                haystack = self._normalized(f"{title} {description}")
                parsed = urlsplit(url)
                if normalized not in haystack or parsed.scheme not in {"http", "https"}:
                    continue
                if not parsed.hostname or url in seen_urls:
                    continue
                seen_urls.add(url)
                records.append(
                    {
                        "title": title or parsed.hostname,
                        "url": url,
                        "source_host": parsed.hostname.lower(),
                        "excerpt": description[:500],
                    }
                )
                if len(records) >= 5:
                    break
            result["records"] = records
            result["result_count"] = len(records)
            result["status"] = "success_with_results" if records else "success_no_results"
            return result
        except (httpx.HTTPError, ValueError, ET.ParseError):
            return result
        finally:
            if owns_client:
                await request_client.aclose()

    async def lookup(self, company_name: str) -> list[dict]:
        cache_key = self._normalized(company_name)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        transactions, mentions = await asyncio.gather(
            self.query_public_transactions(company_name),
            self.search_public_web_mentions(company_name),
        )
        result = [transactions, mentions]
        self._cache[cache_key] = (time.monotonic(), result)
        return result


live_company_sources = LiveCompanySources()
