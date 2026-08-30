"""Executable company evidence lookup tool.

This tool never receives browser credentials.  It reads normalized evidence
that has already been imported into MySQL and returns both facts and citations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.models.base import SessionLocal
from app.services.company_evidence_service import company_evidence_service
from app.services.external_company_adapters import external_company_adapters
from app.services.live_company_sources import live_company_sources

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


QUERY_DIMENSIONS = {
    "basic": {"registry"},
    "social_security": {"social_insurance"},
    "labor_arbitration": {"labor_disputes"},
    "punishment": {"business_risk"},
    "official_jobs": {"official_jobs"},
    "public_transactions": {"public_transactions"},
    "all": {
        "registry",
        "business_risk",
        "social_insurance",
        "labor_disputes",
        "official_jobs",
        "public_transactions",
        "online_reputation",
    },
}


async def search_company_info(
    company_name: str,
    query_type: str = "all",
    *,
    db: "Session | None" = None,
) -> dict:
    """Look up source-bound company facts and return an auditable tool result."""
    if query_type not in QUERY_DIMENSIONS:
        raise ValueError("query_type 不受支持")
    normalized = company_evidence_service.normalize_company_name(company_name)
    if len(normalized) < 2:
        raise ValueError("请提供企业全称")

    live_queries: list[dict] = []
    if query_type in {"all", "public_transactions"}:
        live_queries = await live_company_sources.lookup(company_name)
    external_queries: list[dict] = []
    if query_type in {"all", "basic"}:
        external_queries = await external_company_adapters.lookup_company(company_name)

    owns_session = db is None
    session = db or SessionLocal()
    try:
        for live_result in live_queries:
            if live_result.get("adapter") == "national_public_resource_transactions":
                for record in live_result.get("records") or []:
                    company_evidence_service.add_evidence(
                        session,
                        {
                            "company_name": company_name,
                            "evidence_type": "public_transaction",
                            "source_kind": "official",
                            "source_name": live_result["source_name"],
                            "source_url": live_result["source_url"],
                            "title": f"{company_name}公共资源交易成交记录",
                            "content_excerpt": live_result["supports"],
                            "structured_data": {
                                "transaction_count": record.get("transaction_count"),
                                "unified_social_credit_code": record.get("unified_social_credit_code"),
                                "legal_representative": record.get("legal_representative"),
                                "established_at": record.get("established_at"),
                            },
                        },
                    )
            elif live_result.get("adapter") == "bing_public_web_search":
                for record in live_result.get("records") or []:
                    company_evidence_service.add_evidence(
                        session,
                        {
                            "company_name": company_name,
                            "evidence_type": "reputation",
                            "source_kind": "media",
                            "source_name": record.get("source_host") or live_result["source_name"],
                            "source_url": record["url"],
                            "title": record["title"],
                            "content_excerpt": record.get("excerpt"),
                            "structured_data": {},
                        },
                    )
        for external_result in external_queries:
            if external_result.get("status") != "success_with_results":
                continue
            for record in external_result.get("records") or []:
                structured = {
                    "registration_status": record.get("Status")
                    or record.get("status")
                    or record.get("RegStatus")
                    or record.get("registration_status"),
                    "unified_social_credit_code": record.get("CreditCode")
                    or record.get("creditCode")
                    or record.get("No")
                    or record.get("unified_social_credit_code"),
                    "legal_representative": record.get("OperName")
                    or record.get("legalPerson")
                    or record.get("legal_representative"),
                    "registered_capital": record.get("RegistCapi")
                    or record.get("registeredCapital")
                    or record.get("registered_capital"),
                    "establishment_date": record.get("StartDate")
                    or record.get("estiblishTime")
                    or record.get("establishment_date"),
                    "address": record.get("Address")
                    or record.get("regLocation")
                    or record.get("address"),
                    "business_scope": record.get("Scope")
                    or record.get("businessScope")
                    or record.get("business_scope"),
                }
                company_evidence_service.add_evidence(
                    session,
                    {
                        "company_name": record.get("Name") or record.get("name") or company_name,
                        "evidence_type": "registry",
                        "source_kind": "job_board",
                        "source_name": external_result.get("source_name") or external_result["adapter"],
                        "source_url": external_result.get("source_url") or "https://openapi.qcc.com/",
                        "title": f"{company_name}企业工商信息",
                        "content_excerpt": external_result.get("supports"),
                        "structured_data": structured,
                    },
                )
        if live_queries or external_queries:
            session.flush()
        summary = company_evidence_service.get_summary(session, company_name)
        if owns_session:
            session.commit()
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()

    selected_names = QUERY_DIMENSIONS[query_type]
    selected_dimensions = {
        key: value
        for key, value in (summary.get("dimensions") or {}).items()
        if key in selected_names
    }
    relevant_evidence_ids = {
        evidence_id
        for dimension in selected_dimensions.values()
        for evidence_id in dimension.get("evidence_ids", [])
    }
    sources = [
        source
        for source in summary.get("sources", [])
        if not relevant_evidence_ids or source.get("evidence_id") in relevant_evidence_ids
    ]
    query_sources = [
        {
            "title": item.get("source_name"),
            "url": item.get("source_url"),
            "source_name": item.get("source_name"),
            "status": item.get("status"),
            "supports": item.get("supports"),
            "observed_at": item.get("queried_at"),
        }
        for item in live_queries
        if item.get("source_url")
    ]
    sources = list({
        item.get("url"): item for item in [*sources, *query_sources] if item.get("url")
    }.values())
    verified_dimensions = [
        name for name, value in selected_dimensions.items() if value.get("verified")
    ]
    missing_dimensions = [
        name for name, value in selected_dimensions.items() if not value.get("verified")
    ]
    evidence_count = len(summary.get("evidence") or [])
    return {
        "tool_name": "search_company_info",
        "status": "success" if evidence_count else "no_evidence",
        "company_name": company_name,
        "query_type": query_type,
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "verification_status": summary.get("verification_status", "unverified"),
        "verified_dimensions": verified_dimensions,
        "missing_dimensions": missing_dimensions,
        "dimensions": selected_dimensions,
        "sources": sources,
        "evidence": summary.get("evidence", []),
        "live_queries": live_queries,
        "external_queries": external_queries,
        "adapters": [
            {
                "name": "mysql_company_evidence",
                "status": "used",
                "description": "查询已落库且绑定来源的企业证据",
            },
            {
                "name": "beijing_open_data",
                "status": "available_via_import",
                "description": "官方招聘 CSV 已导入；不证明工商、社保或仲裁风险",
            },
            {
                "name": "qichacha_openapi",
                "status": "configured" if external_company_adapters.qichacha_configured() else "not_configured",
                "description": "真实企查查开放平台接口，配置 QICHACHA_APP_KEY/QICHACHA_SECRET_KEY 后启用",
            },
            {
                "name": "aliyun_market_company_api",
                "status": "configured" if external_company_adapters.aliyun_configured() else "not_configured",
                "description": "真实阿里云市场企业数据接口，配置 AppCode 与接口 URL 后启用",
            },
            {
                "name": "gsxt",
                "status": "manual_handoff",
                "description": "需要合规导入官方查询结果；不保存账号、Cookie 或验证码",
            },
        ],
        "policy": "缺少来源的企业字段返回 unknown，禁止由模型补全",
    }
