"""北京市公共数据开放平台岗位 API 客户端。"""

from __future__ import annotations

import logging
import re
from asyncio import to_thread
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.services.edge_json_transport import EdgeJSONTransport, EdgeJSONTransportError

logger = logging.getLogger(__name__)

BEIJING_JOB_CONTENT_ID = "466e22a6b0314b4298864dcfb1a50803"
BEIJING_API_ROOT = "https://data.beijing.gov.cn/cms/web/api"


class BeijingJobAPIError(RuntimeError):
    pass


class BeijingJobTransportError(BeijingJobAPIError):
    """The regular HTTP transport failed before a response was received."""


@dataclass
class BeijingJobPage:
    records: list[dict]
    total: int | None
    page: int
    page_size: int


class BeijingJobAPIService:
    """只在内存中使用 userKey，日志和返回值均不包含密钥。"""

    STRONG_COMPUTER_TITLE_KEYWORDS = [
        "前端", "后端", "全栈", "服务端", "客户端开发", "软件开发", "软件工程师",
        "java", "python", "golang", "go开发", "c++", ".net", "php", "javascript",
        "android", "ios", "鸿蒙", "嵌入式", "算法", "大模型", "人工智能", "机器学习",
        "深度学习", "数据开发", "数据工程", "数据分析师", "数据库", "商业智能", "bi工程师",
        "测试开发", "软件测试", "自动化测试", "devops", "sre", "云计算",
        "网络安全", "信息安全", "网络工程师", "it工程师", "ai产品", "数据产品",
        "机器人产品",
    ]
    CONDITIONAL_TITLE_KEYWORDS = [
        "产品经理", "技术支持", "实施工程师", "实施顾问", "售前工程师", "解决方案工程师",
        "运维", "系统工程师",
    ]
    TECH_EVIDENCE_KEYWORDS = [
        "计算机相关", "计算机科学", "计算机网络", "网络工程", "软件工程", "软件开发",
        "软件项目", "互联网", "编程", "数据库", "sql", "java", "python", "linux",
        "windows", "云平台", "云计算", "网络设备", "tcp/ip", "算法", "人工智能",
        "大模型", "ai产品", "ai agent", "ai技术", "信息系统", "信息化软件", "api",
        "服务器", "操作系统", "docker", "kubernetes", "前端", "后端", "c++", "html",
        "javascript", "vue", "react", "erp", "nginx", "tomcat", "redis", "mongodb",
        "虚拟化", "信息安全", "软硬件", "it技术",
    ]

    def __init__(self, edge_transport_factory=EdgeJSONTransport):
        self.edge_transport_factory = edge_transport_factory
        self.transport_used = "httpx"

    async def fetch_page(
        self,
        user_key: str,
        *,
        page: int,
        page_size: int,
        client: httpx.AsyncClient | None = None,
    ) -> BeijingJobPage:
        key = self._validate_key(user_key)
        if page < 1 or page_size < 1 or page_size > 1000:
            raise BeijingJobAPIError("分页参数无效：page>=1，page_size 必须在 1-1000 之间")
        url = f"{BEIJING_API_ROOT}/{key}/{BEIJING_JOB_CONTENT_ID}"
        owns_client = client is None
        client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers={"Accept": "application/json", "User-Agent": "JobGuard/1.0"},
        )
        try:
            try:
                response = await client.get(
                    url,
                    params={"currentPage": page, "pageSize": page_size},
                )
            except httpx.TimeoutException as exc:
                raise BeijingJobAPIError("北京市公共数据接口访问超时") from exc
            except httpx.ConnectError as exc:
                raise BeijingJobTransportError(
                    "标准 HTTPS 连接失败，将尝试 Microsoft Edge 兼容模式"
                ) from exc
            except httpx.HTTPError as exc:
                raise BeijingJobAPIError("北京市公共数据接口连接异常") from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise BeijingJobAPIError("接口没有返回有效 JSON，可能需要重新登录确认权限") from exc
            return self._build_page(payload, response.status_code, page, page_size)
        finally:
            if owns_client:
                await client.aclose()

    async def fetch_all(
        self,
        user_key: str,
        *,
        page_size: int = 500,
        max_pages: int = 100,
    ) -> list[dict]:
        records: list[dict] = []
        self.transport_used = "httpx"
        edge_transport = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=8.0),
                headers={"Accept": "application/json", "User-Agent": "JobGuard/1.0"},
            ) as client:
                for page_number in range(1, max_pages + 1):
                    if edge_transport is None:
                        try:
                            page = await self.fetch_page(
                                user_key,
                                page=page_number,
                                page_size=page_size,
                                client=client,
                            )
                        except BeijingJobTransportError:
                            edge_transport = self.edge_transport_factory()
                            try:
                                await to_thread(edge_transport.start)
                            except EdgeJSONTransportError as exc:
                                raise BeijingJobAPIError(
                                    "标准 HTTPS 握手被站点拒绝，且 Microsoft Edge 兼容模式启动失败："
                                    f"{exc}"
                                ) from exc
                            self.transport_used = "edge"
                            logger.warning(
                                "[BeijingJobs] using temporary Edge compatibility transport"
                            )
                            page = await self._fetch_page_with_edge(
                                edge_transport, user_key, page_number, page_size
                            )
                    else:
                        page = await self._fetch_page_with_edge(
                            edge_transport, user_key, page_number, page_size
                        )
                    records.extend(page.records)
                    if not page.records:
                        break
                    if page.total is not None and len(records) >= page.total:
                        break
                    if page.total is None and len(page.records) < page_size:
                        break
                else:
                    raise BeijingJobAPIError(
                        f"达到安全上限 {max_pages} 页仍未结束，请提高 max_pages 后重试"
                    )
        finally:
            if edge_transport is not None:
                await to_thread(edge_transport.close)
        return records

    async def _fetch_page_with_edge(
        self,
        transport: EdgeJSONTransport,
        user_key: str,
        page: int,
        page_size: int,
    ) -> BeijingJobPage:
        key = self._validate_key(user_key)
        base_url = f"{BEIJING_API_ROOT}/{key}/{BEIJING_JOB_CONTENT_ID}"
        url = f"{base_url}?{urlencode({'currentPage': page, 'pageSize': page_size})}"
        try:
            status_code, payload = await to_thread(transport.get_json, url)
        except EdgeJSONTransportError as exc:
            raise BeijingJobAPIError(f"Microsoft Edge 兼容模式读取接口失败：{exc}") from exc
        return self._build_page(payload, status_code, page, page_size)

    def _build_page(
        self,
        payload,
        status_code: int | None,
        page: int,
        page_size: int,
    ) -> BeijingJobPage:
        payload_status = self._payload_status(payload)
        effective_status = status_code if status_code and status_code >= 400 else payload_status
        if effective_status in {401, 403}:
            raise BeijingJobAPIError("唯一标识码无效、已过期或当前账号无接口权限")
        if effective_status == 404:
            raise BeijingJobAPIError(
                "官方接口返回 404：该数据集页面公开的“接口地址”实际指向说明页，"
                "当前资源可能未正确绑定可调用 API；请改用页面“数据”区域的最新 CSV 文件导入"
            )
        if effective_status is not None and effective_status >= 400:
            raise BeijingJobAPIError(f"北京市公共数据接口返回 HTTP {effective_status}")
        records = self.extract_records(payload)
        total = self.extract_total(payload)
        if not records and self._payload_has_error(payload):
            raise BeijingJobAPIError("接口返回失败状态，请在官方页面确认唯一标识码和调用权限")
        logger.info("[BeijingJobs] fetched page=%s records=%s total=%s", page, len(records), total)
        return BeijingJobPage(records=records, total=total, page=page, page_size=page_size)

    @classmethod
    def is_computer_job(cls, record: dict) -> tuple[bool, str | None]:
        title = cls._first_value(record, ["岗位名称", "招聘岗位", "职位名称", "工种名称", "岗位"])
        description = cls._first_value(
            record,
            ["岗位要求", "岗位描述", "职位描述", "招聘条件", "岗位职责"],
        )
        title_lower = title.lower()
        description_lower = description.lower()
        matched = next(
            (keyword for keyword in cls.STRONG_COMPUTER_TITLE_KEYWORDS if keyword in title_lower),
            None,
        )
        if matched:
            return True, f"岗位名称命中：{matched}"
        conditional = next(
            (keyword for keyword in cls.CONDITIONAL_TITLE_KEYWORDS if keyword in title_lower),
            None,
        )
        evidence = list(dict.fromkeys(
            keyword for keyword in cls.TECH_EVIDENCE_KEYWORDS if keyword in description_lower
        ))
        if conditional and len(evidence) >= 2:
            return True, (
                f"岗位名称命中：{conditional}；岗位要求命中："
                f"{evidence[0]}、{evidence[1]}"
            )
        return False, None

    @classmethod
    def filter_computer_jobs(cls, records: list[dict]) -> tuple[list[dict], dict]:
        selected = []
        reasons: dict[str, int] = {}
        for record in records:
            included, reason = cls.is_computer_job(record)
            if not included:
                continue
            selected.append(record)
            reasons[reason or "其他"] = reasons.get(reason or "其他", 0) + 1
        return selected, {
            "source_records": len(records),
            "computer_records": len(selected),
            "excluded_records": len(records) - len(selected),
            "top_filter_reasons": sorted(reasons.items(), key=lambda item: -item[1])[:20],
        }

    @classmethod
    def extract_records(cls, payload) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("rows", "records", "items", "list", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        for key in ("data", "result", "response", "body", "page", "object"):
            value = payload.get(key)
            records = cls.extract_records(value)
            if records:
                return records
        return []

    @classmethod
    def extract_total(cls, payload) -> int | None:
        if not isinstance(payload, dict):
            return None
        for key in ("total", "totalCount", "recordsTotal", "count", "totalElements"):
            value = payload.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        for key in ("data", "result", "response", "body", "page"):
            found = cls.extract_total(payload.get(key))
            if found is not None:
                return found
        return None

    @staticmethod
    def _payload_has_error(payload) -> bool:
        if not isinstance(payload, dict):
            return False
        code = str(payload.get("code", payload.get("status", ""))).lower()
        success = payload.get("success")
        return success is False or code in {
            "300", "400", "401", "403", "404", "500", "error", "failed"
        }

    @staticmethod
    def _payload_status(payload) -> int | None:
        if not isinstance(payload, dict):
            return None
        raw_status = payload.get("status", payload.get("code"))
        try:
            return int(raw_status)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_key(user_key: str) -> str:
        key = str(user_key or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", key):
            raise BeijingJobAPIError("唯一标识码格式无效")
        return key

    @staticmethod
    def _first_value(record: dict, aliases: list[str]) -> str:
        for alias in aliases:
            value = record.get(alias)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""


beijing_job_api_service = BeijingJobAPIService()
