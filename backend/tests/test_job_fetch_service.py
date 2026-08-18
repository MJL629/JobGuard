import json

import pytest

from app.agents.job_parser import job_parser
from app.services.job_fetch_service import (
    FetchedJobPage,
    JobFetchError,
    JobFetchService,
)


def test_extracts_visible_text_and_jobposting_json_ld():
    html = """
    <html><head><title>后端工程师招聘</title>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "Python 后端工程师",
      "hiringOrganization": {"@type": "Organization", "name": "示例科技"},
      "jobLocation": {"address": {"addressRegion": "广东", "addressLocality": "广州"}},
      "baseSalary": {"value": {"minValue": 15000, "maxValue": 25000}},
      "description": "<p>负责 API 开发</p>",
      "skills": "Python;FastAPI;MySQL"
    }
    </script></head>
    <body><nav>导航内容</nav><main><h1>Python 后端工程师</h1><p>负责 API 开发和数据库设计。</p></main></body></html>
    """
    title, text, posting = JobFetchService._extract_page(html, "text/html")

    assert title == "后端工程师招聘"
    assert "负责 API 开发" in text
    assert "导航内容" not in text
    assert posting["@type"] == "JobPosting"


@pytest.mark.asyncio
async def test_private_address_is_rejected_before_request():
    with pytest.raises(JobFetchError) as error:
        await JobFetchService._validate_public_url("http://127.0.0.1:80/private-job")
    assert error.value.code == "private_address"


@pytest.mark.asyncio
async def test_url_parser_keeps_fetch_evidence(monkeypatch):
    page = FetchedJobPage(
        requested_url="https://jobs.example.com/1",
        final_url="https://jobs.example.com/1?from=share",
        title="Python 后端工程师",
        text="示例科技公开招聘 Python 后端工程师，工作地点广州，负责 API 开发和 MySQL 数据库设计。",
        structured_job={
            "@type": "JobPosting",
            "title": "Python 后端工程师",
            "hiringOrganization": {"name": "示例科技"},
            "jobLocation": {"address": {"addressLocality": "广州"}},
            "skills": "Python;FastAPI;MySQL",
        },
        fetched_at="2026-08-02T10:00:00+00:00",
    )

    async def fake_fetch(url):
        return page

    async def fake_chat(messages, **kwargs):
        if "分类选项" in messages[-1]["content"]:
            return "engineering|后端开发"
        return json.dumps({
            "company_name": "示例科技",
            "job_title": "Python 后端工程师",
            "location": "广州",
            "requirements": ["Python", "FastAPI", "MySQL"],
        }, ensure_ascii=False)

    monkeypatch.setattr("app.agents.job_parser.job_fetch_service.fetch", fake_fetch)
    monkeypatch.setattr("app.agents.job_parser.llm_gateway.chat", fake_chat)

    result = await job_parser.parse("https://jobs.example.com/1", "url")

    assert result["company_name"] == "示例科技"
    assert result["source_url"].endswith("from=share")
    assert result["source_type"] == "public_web"
    assert result["source_evidence"]["fetched_at"] == "2026-08-02T10:00:00+00:00"


def test_labeled_job_fallback_parses_salary_without_hallucination():
    result = job_parser._extract_job_info_fallback(
        "公司：示例科技\n岗位：Python 后端工程师\n薪资：15K-25K\n地点：广州"
    )
    assert result == {
        "company_name": "示例科技",
        "job_title": "Python 后端工程师",
        "location": "广州",
        "salary_min": 15000,
        "salary_max": 25000,
    }
