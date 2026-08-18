"""受限的岗位网页抓取器：只读取公开 HTML，并保留来源证据。"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 4


class JobFetchError(ValueError):
    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class FetchedJobPage:
    requested_url: str
    final_url: str
    title: str
    text: str
    structured_job: dict
    fetched_at: str

    def evidence(self) -> dict:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "page_title": self.title,
            "fetched_at": self.fetched_at,
            "content_type": "public_web_page",
        }


class JobFetchService:
    async def fetch(self, url: str) -> FetchedJobPage:
        requested_url = url.strip()
        current_url = requested_url
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; JobGuard/1.0; public-job-page-reader)",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,text/plain;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        }
        timeout = httpx.Timeout(12.0, connect=6.0)

        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
            body = b""
            content_type = ""
            final_url = ""
            encoding = "utf-8"
            for _ in range(MAX_REDIRECTS + 1):
                await self._validate_public_url(current_url)
                try:
                    async with client.stream("GET", current_url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise JobFetchError("岗位链接重定向异常", code="invalid_redirect")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status_code in {401, 403}:
                            raise JobFetchError(
                                "该岗位页面需要登录或阻止了自动读取。请在浏览器打开后复制完整 JD，或上传岗位截图",
                                code="login_or_anti_bot",
                            )
                        if response.status_code == 404:
                            raise JobFetchError("岗位链接已失效或岗位已下线", code="job_not_found")
                        if response.status_code >= 400:
                            raise JobFetchError(
                                f"岗位网页返回 HTTP {response.status_code}，请粘贴完整岗位描述",
                                code="upstream_http_error",
                            )

                        content_type = response.headers.get("content-type", "").lower()
                        if not any(item in content_type for item in (
                            "text/html", "application/xhtml", "text/plain", "application/json"
                        )):
                            raise JobFetchError(
                                "链接返回的不是可读取网页，请粘贴 JD 或上传截图",
                                code="unsupported_content_type",
                            )
                        content_length = response.headers.get("content-length")
                        if content_length and content_length.isdigit() and int(content_length) > MAX_HTML_BYTES:
                            raise JobFetchError("岗位网页内容过大，无法安全读取", code="page_too_large")

                        chunks = []
                        received = 0
                        async for chunk in response.aiter_bytes():
                            received += len(chunk)
                            if received > MAX_HTML_BYTES:
                                raise JobFetchError("岗位网页内容过大，无法安全读取", code="page_too_large")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        final_url = str(response.url)
                        encoding = response.encoding or "utf-8"
                except httpx.TimeoutException as exc:
                    raise JobFetchError("岗位网页访问超时，请粘贴完整岗位描述", code="fetch_timeout") from exc
                except JobFetchError:
                    raise
                except httpx.HTTPError as exc:
                    raise JobFetchError("岗位网页暂时无法访问，请粘贴完整岗位描述", code="fetch_failed") from exc
                break
            else:
                raise JobFetchError("岗位链接重定向次数过多", code="too_many_redirects")

        if not final_url:
            raise JobFetchError("岗位网页没有返回内容", code="empty_response")
        try:
            decoded_body = body.decode(encoding, errors="replace")
        except LookupError:
            decoded_body = body.decode("utf-8", errors="replace")
        title, text, structured = self._extract_page(decoded_body, content_type)
        if len(text) < 80 and not structured:
            raise JobFetchError(
                "网页没有提供可读取的岗位正文，可能依赖登录或动态加载。请复制 JD 或上传截图",
                code="insufficient_public_content",
            )
        return FetchedJobPage(
            requested_url=requested_url,
            final_url=final_url,
            title=title,
            text=text[:20000],
            structured_job=structured,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    async def _validate_public_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise JobFetchError("只支持完整的 HTTP/HTTPS 岗位链接", code="invalid_url")
        if parsed.username or parsed.password:
            raise JobFetchError("岗位链接不能包含账号信息", code="credentials_in_url")
        if parsed.port and parsed.port not in {80, 443}:
            raise JobFetchError("岗位链接使用了不安全的端口", code="unsafe_port")
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise JobFetchError("岗位链接域名无法解析", code="dns_failed") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
                raise JobFetchError("出于安全原因，不能读取本机或内网地址", code="private_address")

    @classmethod
    def _extract_page(cls, body: str, content_type: str) -> tuple[str, str, dict]:
        if "application/json" in content_type:
            try:
                data = json.loads(body)
                structured = cls._find_job_posting(data) or {}
                return "", json.dumps(data, ensure_ascii=False), structured
            except json.JSONDecodeError:
                return "", body, {}

        soup = BeautifulSoup(body, "html.parser")
        structured: dict = {}
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                candidate = cls._find_job_posting(json.loads(script.get_text(" ", strip=True)))
                if candidate:
                    structured = candidate
                    break
            except (json.JSONDecodeError, TypeError):
                continue
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
            tag.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        text = "\n".join(
            line.strip() for line in root.get_text("\n").splitlines() if line.strip()
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
        return title, text, structured

    @classmethod
    def _find_job_posting(cls, value) -> dict | None:
        if isinstance(value, dict):
            type_value = value.get("@type")
            if type_value == "JobPosting" or (isinstance(type_value, list) and "JobPosting" in type_value):
                return value
            for nested in value.values():
                found = cls._find_job_posting(nested)
                if found:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_job_posting(nested)
                if found:
                    return found
        return None


job_fetch_service = JobFetchService()
