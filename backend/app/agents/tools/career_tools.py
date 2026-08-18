"""Read-only career tools shared by the in-app Agent and MCP surface.

All returned claims are derived from JobGuard's database or a curated source
catalog.  The tools never accept credentials and never invent missing facts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_

from app.models.base import SessionLocal
from app.models.job import Job


LEARNING_RESOURCES = [
    {
        "topic": "FastAPI",
        "title": "FastAPI 实战课程",
        "url": "https://www.bilibili.com/video/BV1zV2QBtE39/",
        "source": "哔哩哔哩公开课程",
    },
    {
        "topic": "LangGraph",
        "title": "LangGraph Agent 工作流课程",
        "url": "https://www.bilibili.com/video/BV1PaWgz1Eu6/",
        "source": "哔哩哔哩公开课程",
    },
    {
        "topic": "RAG",
        "title": "RAG 检索增强生成实战",
        "url": "https://www.bilibili.com/video/BV1hj5DzyE5d/",
        "source": "哔哩哔哩公开课程",
    },
    {
        "topic": "Docker",
        "title": "Docker 容器化入门与实战",
        "url": "https://www.bilibili.com/video/BV1Zn4y1X7AZ/",
        "source": "哔哩哔哩公开课程",
    },
]


async def inspect_profile_gaps(*, user_id: int) -> dict:
    """Inspect the authenticated user's persisted profile without exposing raw files."""
    from app.agents.profile_agent import profile_agent
    from app.services.profile_service import profile_service

    db = SessionLocal()
    try:
        profile = profile_service.get_full_profile(db, user_id)
        flattened = {
            **(profile.get("basic") or {}),
            **(profile.get("preferences") or {}),
            "projects": profile.get("projects") or [],
            "skills": profile.get("skills") or [],
            "experiences": profile.get("experiences") or [],
            "education": profile.get("education") or [],
        }
        result = profile_agent.check_completeness(flattened)
        return {
            "tool_name": "inspect_profile_gaps",
            "status": "success",
            "completeness": result["completeness"],
            "ready": result["ready"],
            "missing_fields": result["missing"],
            "experience_count": len(flattened["experiences"]) + len(flattened["projects"]),
            "skill_count": len(flattened["skills"]),
            "next_question": profile_agent._fallback_question(result["missing"]),
        }
    finally:
        db.close()


async def search_job_database(
    keywords: str = "", location: str = "", limit: int = 10, source_kind: str = "all"
) -> dict:
    """Search active, non-expired jobs stored in MySQL."""
    db = SessionLocal()
    try:
        safe_limit = max(1, min(int(limit), 20))
        query = db.query(Job).filter(
            Job.is_active == 1,
            or_(Job.expires_at.is_(None), Job.expires_at > datetime.utcnow()),
        )
        if keywords.strip():
            value = f"%{keywords.strip()}%"
            query = query.filter(or_(Job.job_title.like(value), Job.jd_text.like(value)))
        if location.strip():
            query = query.filter(Job.location.contains(location.strip()))
        if source_kind == "official":
            query = query.filter(Job.source_type == "beijing_hr_open_data")
        elif source_kind == "job_board":
            query = query.filter(Job.source_type != "beijing_hr_open_data")
        elif source_kind != "all":
            raise ValueError("source_kind 不受支持")
        jobs = query.order_by(
            Job.source_url.isnot(None).desc(),
            Job.posted_at.desc(),
            Job.id.desc(),
        ).limit(safe_limit).all()
        return {
            "tool_name": "search_job_database",
            "status": "success",
            "count": len(jobs),
            "source_kind": source_kind,
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {
                    "id": item.id,
                    "company_name": item.company_name,
                    "job_title": item.job_title,
                    "location": item.location,
                    "salary_min": item.salary_min,
                    "salary_max": item.salary_max,
                    "source_type": item.source_type,
                    "source_url": item.source_url,
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                }
                for item in jobs
            ],
            "policy": "仅返回数据库中仍有效的岗位；来源缺失时不补造链接",
        }
    finally:
        db.close()


async def analyze_job_requirements(job_id: int) -> dict:
    """Return evidence-backed, non-personalized requirements for a stored job."""
    from app.services.job_service import job_service

    db = SessionLocal()
    try:
        job = job_service.get_job_detail(db, int(job_id))
        if not job:
            return {"tool_name": "analyze_job_requirements", "status": "not_found", "job_id": job_id}
        jd_text = job.get("jd_text") or ""
        skills = sorted(job_service._extract_required_skills(jd_text))
        return {
            "tool_name": "analyze_job_requirements",
            "status": "success",
            "job_id": int(job_id),
            "company_name": job.get("company_name"),
            "job_title": job.get("job_title"),
            "required_skills": skills,
            "requirements": job.get("requirements") or [],
            "source_url": job.get("source_url"),
            "evidence_excerpt": jd_text[:1200],
            "policy": "结果仅来自岗位原文和结构化字段，不代表企业事实核验",
        }
    finally:
        db.close()


async def recommend_jobs_for_profile(*, user_id: int, limit: int = 10) -> dict:
    """Rank real database jobs against the authenticated user's saved profile."""
    from app.services.job_service import job_service

    db = SessionLocal()
    try:
        result = job_service.recommend_jobs(
            db, user_id=user_id, page=1, page_size=max(1, min(int(limit), 20))
        )
        return {
            "tool_name": "recommend_jobs_for_profile",
            "status": "success",
            "count": len(result.get("items") or []),
            "profile_completeness": result.get("profile_completeness"),
            "scoring_version": result.get("scoring_version"),
            "items": result.get("items") or [],
        }
    finally:
        db.close()


async def generate_targeted_resume(
    job_id: int,
    template_id: str = "template-01",
    max_projects: int = 3,
    *,
    user_id: int,
) -> dict:
    """Generate and persist a resume after the caller has confirmed the side effect."""
    from app.services.resume_service import resume_service

    db = SessionLocal()
    try:
        result = await resume_service.generate_resume(
            db,
            user_id=user_id,
            job_id=int(job_id),
            options={
                "template_id": template_id,
                "max_projects": max(1, min(int(max_projects), 6)),
            },
        )
        if "error" in result:
            return {
                "tool_name": "generate_targeted_resume",
                "status": "failed",
                "message": result["error"],
            }
        return {
            "tool_name": "generate_targeted_resume",
            "status": "success",
            "resume_id": result.get("resume_id"),
            "template_id": result.get("template_id"),
            "version": result.get("version"),
            "docx_ready": bool(result.get("docx_path")),
            "pdf_ready": bool(result.get("pdf_path")),
            "fact_check": result.get("fact_check") or {},
        }
    finally:
        db.close()


async def recommend_learning_resources(topic: str = "", limit: int = 4) -> dict:
    """Return a small curated catalog rather than fabricated course links."""
    query = topic.strip().lower()
    matches = [
        item for item in LEARNING_RESOURCES
        if not query or query in item["topic"].lower() or item["topic"].lower() in query
    ]
    if not matches:
        matches = LEARNING_RESOURCES
    items = matches[: max(1, min(int(limit), 10))]
    return {
        "tool_name": "recommend_learning_resources",
        "status": "success",
        "topic": topic or "通用求职技术栈",
        "items": items,
        "catalog_checked_at": "2026-08-07",
        "notice": "公开课程可能改版或下架，学习前请再次核对标题与讲师；JobGuard 不代表平台背书。",
    }


async def build_company_verification_plan(company_name: str) -> dict:
    """Build a manual verification checklist with official entry points."""
    name = company_name.strip()
    if len(name) < 2:
        raise ValueError("请提供企业全称")
    return {
        "tool_name": "build_company_verification_plan",
        "status": "manual_confirmation_required",
        "company_name": name,
        "steps": [
            {
                "dimension": "工商登记与经营异常",
                "source_name": "国家企业信用信息公示系统",
                "url": "https://www.gsxt.gov.cn/",
                "action": f"搜索企业全称“{name}”，核对统一社会信用代码、登记状态、经营异常和行政处罚。",
            },
            {
                "dimension": "公共信用记录",
                "source_name": "信用中国",
                "url": "https://www.creditchina.gov.cn/",
                "action": f"搜索企业全称“{name}”，核对公开的行政管理与失信相关信息。",
            },
            {
                "dimension": "公开裁判文书",
                "source_name": "中国裁判文书网",
                "url": "https://wenshu.court.gov.cn/",
                "action": f"登录后以企业全称“{name}”检索，并人工区分同名主体与案件角色。",
            },
            {
                "dimension": "被执行信息",
                "source_name": "中国执行信息公开网",
                "url": "https://zxgk.court.gov.cn/",
                "action": f"按企业全称“{name}”和统一社会信用代码交叉核验。",
            },
        ],
        "policy": "查询可能涉及登录、验证码或主体消歧，必须由用户人工确认；未查询不等于没有风险。",
    }
