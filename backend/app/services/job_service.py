"""
岗位分析服务层

负责：
1. 串联 岗位解析 Agent → 企业背调 Agent
2. 岗位分析结果存入 MySQL
3. 提供岗位库查询和推荐接口
"""

import json
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.company import Company
from app.models.analysis import JobAnalysis
from app.agents.job_parser import job_parser
from app.agents.background_check import background_check
from app.services.profile_service import profile_service

logger = logging.getLogger(__name__)


class JobService:
    """岗位分析服务"""

    # ─── 岗位解析 + 存储 ──────────────────────────────────────────────

    async def parse_job(self, raw_input: str, input_type: str = "text") -> dict:
        """
        解析岗位信息（纯解析，不背调）

        Returns:
            结构化的岗位信息
        """
        return await job_parser.parse(raw_input, input_type)

    # ─── 岗位分析（解析 + 背调） ──────────────────────────────────────

    async def analyze_job(
        self,
        db: Session,
        user_id: int,
        raw_input: str,
        input_type: str = "text",
        web_search_func=None,
    ) -> dict:
        """
        完整分析流程：解析岗位 → 企业背调 → 存储结果

        Args:
            db: 数据库会话
            user_id: 用户 ID
            raw_input: 用户输入的岗位链接/文本
            input_type: 输入类型
            web_search_func: WebSearch 回调

        Returns:
            分析报告 dict
        """
        # 1. 解析岗位
        job_info = await job_parser.parse(raw_input, input_type)
        if "error" in job_info:
            return job_info

        # 2. 获取用户画像（用于个性化评估）
        user_profile = profile_service.get_full_profile(db, user_id)

        # 3. 企业背调
        report = await background_check.investigate(
            job_info=job_info,
            user_profile=user_profile,
            web_search_func=web_search_func,
        )

        # 4. 存储：企业信息
        company = self._upsert_company(db, job_info, report)

        # 5. 存储：岗位信息
        job = self._upsert_job(db, job_info, company.id if company else None)

        # 6. 存储：分析记录
        self._save_analysis(db, user_id, job.id if job else None, job_info, report)

        db.commit()

        return {
            "job_info": job_info,
            "report": report,
            "job_id": job.id if job else None,
            "company_id": company.id if company else None,
        }

    # ─── 岗位库查询 ──────────────────────────────────────────────────

    def list_jobs(
        self,
        db: Session,
        category: Optional[str] = None,
        sub_category: Optional[str] = None,
        location: Optional[str] = None,
        salary_min: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """岗位列表查询"""
        query = db.query(Job).filter(Job.is_active == 1)

        if category:
            query = query.filter(Job.job_category == category)
        if sub_category:
            query = query.filter(Job.sub_category == sub_category)
        if location:
            query = query.filter(Job.location.contains(location))
        if salary_min is not None:
            query = query.filter(Job.salary_max >= salary_min)

        total = query.count()
        jobs = query.order_by(Job.posted_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "items": [self._job_to_dict(j) for j in jobs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_job_detail(self, db: Session, job_id: int) -> Optional[dict]:
        """获取岗位详情"""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return self._job_to_dict(job)

    def get_job_analysis(self, db: Session, job_id: int, user_id: int) -> Optional[dict]:
        """获取岗位分析报告"""
        analysis = (
            db.query(JobAnalysis)
            .filter(JobAnalysis.job_id == job_id, JobAnalysis.user_id == user_id)
            .order_by(JobAnalysis.created_at.desc())
            .first()
        )
        if not analysis:
            return None

        return {
            "id": analysis.id,
            "company_name": analysis.company_name,
            "job_title": analysis.job_title,
            "risk_level": analysis.risk_level,
            "recommendation_index": analysis.recommendation_index,
            "match_score": analysis.match_score,
            "analysis": analysis.analysis_json,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        }

    def get_analysis_history(self, db: Session, user_id: int) -> list[dict]:
        """获取用户的分析历史"""
        analyses = (
            db.query(JobAnalysis)
            .filter(JobAnalysis.user_id == user_id)
            .order_by(JobAnalysis.created_at.desc())
            .limit(50)
            .all()
        )

        return [
            {
                "id": a.id,
                "company_name": a.company_name,
                "job_title": a.job_title,
                "risk_level": a.risk_level,
                "recommendation_index": a.recommendation_index,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ]

    # ─── 私有方法 ─────────────────────────────────────────────────────

    def _upsert_company(self, db: Session, job_info: dict, report: dict) -> Optional[Company]:
        """创建或更新企业信息"""
        company_name = job_info.get("company_name", "")
        if not company_name:
            return None

        company = db.query(Company).filter(Company.name == company_name).first()
        if not company:
            company = Company(name=company_name)
            db.add(company)

        # 更新风险信息
        company.risk_level = report.get("risk_level")
        company.risk_score = report.get("overall_score")
        company.last_checked = datetime.utcnow()
        company.data_source = "agent_analysis"

        # 更新背调信息
        dimensions = report.get("dimensions", {})
        si = dimensions.get("social_insurance", {})
        if si.get("participants"):
            try:
                company.social_insurance_count = int(str(si["participants"]).replace("人", ""))
            except (ValueError, TypeError):
                pass

        ld = dimensions.get("labor_disputes", {})
        if ld.get("total_cases"):
            try:
                company.labor_dispute_count = int(str(ld["total_cases"]).replace("起", ""))
            except (ValueError, TypeError):
                pass

        db.flush()
        return company

    def _upsert_job(self, db: Session, job_info: dict, company_id: Optional[int]) -> Optional[Job]:
        """创建或更新岗位信息"""
        company_name = job_info.get("company_name", "")
        job_title = job_info.get("job_title", "")
        source_url = job_info.get("source_url", "")

        if not company_name or not job_title:
            return None

        # 检查是否已存在（同公司同岗位同链接）
        job = None
        if source_url:
            job = db.query(Job).filter(Job.source_url == source_url).first()

        if not job:
            job = Job()
            db.add(job)

        job.company_name = company_name
        job.company_id = company_id
        job.job_title = job_title
        job.job_category = job_info.get("job_category", "engineering")
        job.sub_category = job_info.get("sub_category")
        job.salary_min = job_info.get("salary_min")
        job.salary_max = job_info.get("salary_max")
        job.location = job_info.get("location")
        job.jd_text = job_info.get("jd_raw_text") or job_info.get("job_description")
        job.requirements = job_info.get("requirements", [])
        job.benefits = job_info.get("benefits", [])
        job.source_url = source_url
        job.source_type = job_info.get("source_type", "user_input")
        job.posted_at = datetime.utcnow()
        job.is_active = 1

        db.flush()
        return job

    def _save_analysis(
        self,
        db: Session,
        user_id: int,
        job_id: Optional[int],
        job_info: dict,
        report: dict,
    ):
        """保存分析记录"""
        analysis = JobAnalysis(
            job_id=job_id,
            user_id=user_id,
            company_name=job_info.get("company_name", ""),
            job_title=job_info.get("job_title", ""),
            risk_level=report.get("risk_level"),
            recommendation_index=report.get("recommendation_index"),
            match_score=report.get("dimensions", {}).get("match_with_user", {}).get("score"),
            analysis_json=report,
            source_type="user_paste",
        )
        db.add(analysis)

    def _job_to_dict(self, job: Job) -> dict:
        """Job ORM → dict"""
        return {
            "id": job.id,
            "company_name": job.company_name,
            "company_id": job.company_id,
            "job_title": job.job_title,
            "job_category": job.job_category,
            "sub_category": job.sub_category,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "location": job.location,
            "requirements": job.requirements,
            "benefits": job.benefits,
            "source_url": job.source_url,
            "source_type": job.source_type,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        }


# 全局单例
job_service = JobService()
