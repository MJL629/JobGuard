import pytest

from app.agents.background_check import background_check, _real_web_search
from app.agents.job_parser import job_parser


@pytest.mark.asyncio
async def test_jd_analysis_uses_only_phrases_from_source_text():
    result = await background_check._analyze_jd({
        "salary_min": 15000,
        "salary_max": 40000,
        "jd_raw_text": "要求抗压能力强，可以接受高强度工作，实行大小周。",
    })

    assert result["overtime_risk"] == "high"
    assert "抗压能力强" in result["evidence_phrases"]
    assert "高强度工作" in result["evidence_phrases"]
    assert result["salary_authenticity"] == "薪资范围过大，需核实"


def test_evidence_limited_assessment_never_invents_company_facts():
    assessment = background_check._build_evidence_limited_assessment({
        "overtime_risk": "medium",
        "fake_job_suspicion": "low",
        "kpi_brushing_suspicion": "low",
        "overtime_signals": ["抗压能力强"],
        "fake_job_reasons": [],
        "jd_analysis_summary": "发现抗压能力强",
        "evidence_phrases": ["抗压能力强"],
    })

    assert assessment["verification_status"] == "jd_only"
    assert assessment["sources"] == []
    assert assessment["dimensions"]["social_insurance"]["participants"] is None
    assert assessment["dimensions"]["labor_disputes"]["total_cases"] is None
    assert assessment["dimensions"]["online_reputation"]["verified"] is False
    assert assessment["dimensions"]["social_insurance"]["status"] == "not_publicly_available"
    assert assessment["dimensions"]["labor_disputes"]["status"] == "access_controlled"
    assert assessment["dimensions"]["business_risk"]["status"] == "access_controlled"


def test_live_query_outcomes_are_distinguished_from_unverified():
    assessment = background_check._build_evidence_limited_assessment({
        "overtime_risk": "low",
        "fake_job_suspicion": "low",
        "kpi_brushing_suspicion": "low",
        "overtime_signals": [],
        "fake_job_reasons": [],
        "jd_analysis_summary": "未发现明确高风险话术",
        "evidence_phrases": [],
    })
    result = background_check._apply_live_queries(assessment, {
        "live_queries": [
            {
                "adapter": "national_public_resource_transactions",
                "status": "success_no_results",
                "result_count": 0,
            },
            {
                "adapter": "bing_public_web_search",
                "status": "success_with_results",
                "result_count": 2,
            },
        ],
        "sources": [],
    })

    assert result["verification_status"] == "live_sources_queried"
    assert result["dimensions"]["public_transactions"]["status"] == "success_no_results"
    assert result["dimensions"]["online_reputation"]["status"] == "live_results"
    assert "不能代表整体员工口碑" in result["dimensions"]["online_reputation"]["assessment"]


@pytest.mark.asyncio
async def test_unconfigured_web_search_is_explicitly_unverified():
    result = await _real_web_search("某公司 社保人数")
    assert result == "[未接入可核验联网数据源]"


@pytest.mark.asyncio
async def test_private_url_is_rejected_by_safe_fetcher():
    result = await job_parser.parse("http://127.0.0.1/jobs/1", "url")
    assert "error" in result
    assert result["error_code"] == "private_address"


def test_fetched_job_page_is_listed_as_source_but_company_facts_remain_unverified():
    assessment = background_check._build_evidence_limited_assessment(
        {
            "overtime_risk": "low",
            "fake_job_suspicion": "low",
            "kpi_brushing_suspicion": "low",
            "overtime_signals": [],
            "fake_job_reasons": [],
            "jd_analysis_summary": "未发现明确高风险话术",
            "evidence_phrases": [],
            "work_schedule_inferred": "未知",
        },
        job_info={
            "company_name": "示例科技",
            "source_evidence": {
                "final_url": "https://jobs.example.com/1",
                "page_title": "示例岗位",
                "fetched_at": "2026-08-02T10:00:00+00:00",
            },
        },
    )

    assert assessment["verification_status"] == "jd_source_fetched"
    assert assessment["sources"][0]["status"] == "fetched"
    assert assessment["dimensions"]["social_insurance"]["verified"] is False
    assert len(assessment["verification_tasks"]) == 4
    assert all(task["status"] == "manual_required" for task in assessment["verification_tasks"])


def test_fallback_report_contains_evidence_boundary_and_official_tasks():
    assessment = background_check._build_evidence_limited_assessment({
        "overtime_risk": "medium",
        "fake_job_suspicion": "low",
        "kpi_brushing_suspicion": "low",
        "overtime_signals": ["抗压能力强"],
        "fake_job_reasons": [],
        "jd_analysis_summary": "发现抗压能力强",
        "evidence_phrases": ["抗压能力强"],
        "work_schedule_inferred": "未知",
    }, job_info={"company_name": "示例科技"})
    report = background_check._generate_fallback_report(assessment)

    assert "证据边界" in report
    assert "不会补造数字" in report
    assert "国家企业信用信息公示系统" in report
    assert len(report) > 500
