from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.background_check import background_check
from app.agents.tool_registry import tool_registry
from app.agents.tools.company_evidence import search_company_info
from app.models.base import Base
from app.models.company import CompanyEvidence
from app.models.job import Job
from app.services.company_evidence_service import (
    CompanyEvidenceError,
    CompanyEvidenceService,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_official_verification_is_computed_from_allowlisted_host(db):
    evidence, created = CompanyEvidenceService().add_evidence(
        db,
        {
            "company_name": "北京示例科技有限公司",
            "evidence_type": "registry",
            "source_kind": "official",
            "source_name": "国家企业信用信息公示系统",
            "source_url": "https://www.gsxt.gov.cn/company/example",
            "title": "企业登记信息",
            "structured_data": {
                "registration_status": "存续",
                "fabricated_score": 99,
            },
        },
    )

    assert created is True
    assert evidence.is_verified is True
    assert evidence.verification_level == "official"
    assert evidence.structured_data == {"registration_status": "存续"}


def test_non_official_host_cannot_be_claimed_as_official(db):
    with pytest.raises(CompanyEvidenceError, match="官方来源白名单"):
        CompanyEvidenceService().add_evidence(
            db,
            {
                "company_name": "北京示例科技有限公司",
                "evidence_type": "registry",
                "source_kind": "official",
                "source_name": "非官方网站",
                "source_url": "https://example.com/company/1",
                "title": "企业登记信息",
            },
        )


def test_same_source_is_idempotently_updated(db):
    service = CompanyEvidenceService()
    payload = {
        "company_name": "北京示例科技有限公司",
        "evidence_type": "social_insurance",
        "source_kind": "official",
        "source_name": "政府年度报告",
        "source_url": "https://www.gsxt.gov.cn/company/example/annual-report",
        "title": "2025 年度报告",
        "structured_data": {"participants": 12, "reporting_year": 2025},
    }
    first, first_created = service.add_evidence(db, payload)
    payload["structured_data"] = {"participants": 13, "reporting_year": 2025}
    second, second_created = service.add_evidence(db, payload)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert db.query(CompanyEvidence).count() == 1
    assert second.structured_data["participants"] == 13


def test_official_job_backfill_links_jobs_without_inventing_company_risk(db):
    job = Job(
        id=99001,
        company_name="北京示例科技有限公司",
        job_title="Python 开发工程师",
        job_category="engineering",
        source_type="beijing_hr_open_data",
        source_url=(
            "https://data.beijing.gov.cn/zyml/ajg/srlsbj/"
            "466e22a6b0314b4298864dcfb1a50803.htm#job-BJ-1"
        ),
        source_external_id="BJ-1",
        source_published_at=datetime(2026, 7, 1),
        expires_at=datetime(2026, 12, 31, 23, 59, 59),
        last_seen_at=datetime(2026, 8, 3),
        is_active=1,
    )
    db.add(job)
    db.flush()

    summary = CompanyEvidenceService().backfill_official_jobs(db)
    evidence_summary = CompanyEvidenceService().get_summary(
        db, "北京示例科技有限公司"
    )

    assert summary["evidence_inserted"] == 1
    assert job.company_id is not None
    assert evidence_summary["dimensions"]["official_jobs"]["verified"] is True
    assert evidence_summary["dimensions"]["business_risk"]["verified"] is False

    assessment = background_check._build_evidence_limited_assessment(
        {
            "overtime_risk": "low",
            "fake_job_suspicion": "low",
            "kpi_brushing_suspicion": "low",
            "overtime_signals": [],
            "fake_job_reasons": [],
            "jd_analysis_summary": "未发现明确高风险话术。",
            "evidence_phrases": [],
            "work_schedule_inferred": "未知",
        },
        job_info={"company_name": "北京示例科技有限公司"},
    )
    merged = background_check._apply_stored_evidence(assessment, evidence_summary)
    assert merged["verification_status"] == "official_job_evidence"
    assert merged["dimensions"]["business_risk"]["verified"] is False
    assert merged["dimensions"]["social_insurance"]["participants"] is None


def test_verified_registry_fact_is_applied_with_citation(db):
    service = CompanyEvidenceService()
    service.add_evidence(
        db,
        {
            "company_name": "北京示例科技有限公司",
            "evidence_type": "registry",
            "source_kind": "official",
            "source_name": "国家企业信用信息公示系统",
            "source_url": "https://www.gsxt.gov.cn/company/example",
            "title": "企业登记信息",
            "structured_data": {"registration_status": "存续"},
        },
    )
    base = background_check._build_evidence_limited_assessment(
        {
            "overtime_risk": "low",
            "fake_job_suspicion": "low",
            "kpi_brushing_suspicion": "low",
            "overtime_signals": [],
            "fake_job_reasons": [],
            "jd_analysis_summary": "未发现明确高风险话术。",
            "evidence_phrases": [],
            "work_schedule_inferred": "未知",
        },
        job_info={"company_name": "北京示例科技有限公司"},
    )
    result = background_check._apply_stored_evidence(
        base, service.get_summary(db, "北京示例科技有限公司")
    )

    assert result["verification_status"] == "official_company_evidence"
    assert result["dimensions"]["business_risk"]["verified"] is True
    assert result["dimensions"]["business_risk"]["registration_status"] == "存续"
    assert result["sources"][0]["url"].startswith("https://www.gsxt.gov.cn/")


@pytest.mark.asyncio
async def test_company_search_is_a_real_registered_agent_tool(db):
    service = CompanyEvidenceService()
    service.add_evidence(
        db,
        {
            "company_name": "北京示例科技有限公司",
            "evidence_type": "registry",
            "source_kind": "official",
            "source_name": "国家企业信用信息公示系统",
            "source_url": "https://www.gsxt.gov.cn/company/example",
            "title": "企业登记信息",
            "structured_data": {"registration_status": "存续"},
        },
    )

    result = await search_company_info(
        "北京示例科技有限公司", query_type="basic", db=db
    )
    registered = tool_registry.get("search_company_info")
    exposed_names = [
        item["function"]["name"] for item in tool_registry.get_openai_tools()
    ]

    assert registered is not None and registered.func is not None
    assert result["status"] == "success"
    assert result["verified_dimensions"] == ["registry"]
    assert "search_company_info" in exposed_names
    assert "web_search" not in exposed_names
