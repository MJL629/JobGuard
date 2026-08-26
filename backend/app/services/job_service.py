"""
岗位分析服务层

负责：
1. 串联 岗位解析 Agent → 企业背调 Agent
2. 岗位分析结果存入 MySQL
3. 提供岗位库查询和推荐接口
"""

import logging
import re
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

    def recommend_jobs(
        self, db: Session, user_id: int, page: int = 1, page_size: int = 20,
        category: str | None = None, sub_category: str | None = None,
        location: str | None = None, salary_min_filter: int | None = None,
    ) -> dict:
        """用可解释的确定性特征召回全部岗位；大模型只用于后续深度分析。"""
        profile = profile_service.get_full_profile(db, user_id)
        basic = profile.get("basic", {})
        preferences = profile.get("preferences", {})
        user_skills = {
            str(item.get("skill_name", "")).strip().lower()
            for item in profile.get("skills", []) if item.get("skill_name")
        }
        preferred_roles = [str(x).lower() for x in (preferences.get("preferred_job_types") or [])]
        preferred_roles += [str(x).lower() for x in (preferences.get("preferred_sub_categories") or [])]
        preferred_locations = [str(x).lower() for x in (preferences.get("preferred_locations") or [])]
        salary_min = basic.get("expected_salary_min")
        salary_max = basic.get("expected_salary_max")
        has_profile = bool(user_skills or preferred_roles or preferred_locations or salary_min or salary_max)

        items = []
        seen_keys = set()
        query = db.query(Job).filter(Job.is_active == 1)
        if category:
            query = query.filter(Job.job_category == category)
        sub_alias = {
            "backend": "后端", "frontend": "前端", "fullstack": "全栈",
            "ai_infra": "人工智能基础设施", "devops": "运维",
            "llm_algo": "大模型", "agent_algo": "智能体",
            "data_analysis": "数据分析", "ai_pm": "产品",
        }
        if sub_category:
            query = query.filter(Job.sub_category.contains(sub_alias.get(sub_category, sub_category)))
        location_alias = {"beijing": "北京", "shanghai": "上海", "hangzhou": "杭州", "shenzhen": "深圳", "guangzhou": "广州"}
        if location:
            query = query.filter(Job.location.contains(location_alias.get(location, location)))
        if salary_min_filter is not None:
            query = query.filter(Job.salary_max >= salary_min_filter)

        for job in query.all():
            dedupe_key = self._dedupe_key(job)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            data = self._job_to_dict(job)
            if not has_profile:
                data.update({"match_score": 0, "match_reasons": ["完善画像后可计算个性化匹配度"]})
                items.append(data)
                continue

            score, reasons, rank_boost = self._score_job(
                job=job,
                user_skills=user_skills,
                preferred_roles=preferred_roles,
                preferred_locations=preferred_locations,
                salary_min=salary_min,
                salary_max=salary_max,
                preferences=preferences,
            )

            data.update({
                "match_score": min(100, round(score)),
                "match_reasons": reasons or ["当前画像与岗位的显式条件命中较少"],
                "_rank_boost": rank_boost,
            })
            items.append(data)

        items.sort(key=lambda x: (x["_rank_boost"], x["match_score"], x["id"]), reverse=True)
        total = len(items)
        start = (page - 1) * page_size
        page_items = items[start:start + page_size]
        for item in page_items:
            item.pop("_rank_boost", None)
        return {"items": page_items, "total": total, "page": page, "page_size": page_size}

    def _score_job(
        self,
        job: Job,
        user_skills: set[str],
        preferred_roles: list[str],
        preferred_locations: list[str],
        salary_min: Optional[int],
        salary_max: Optional[int],
        preferences: dict,
    ) -> tuple[float, list[str], int]:
        """Explainable scoring for recommendation cards.

        The score is intentionally rule-based for product demos: it rewards the
        job itself matching the user's target direction, instead of diluting one
        good JD by every skill the user has ever listed.
        """
        reasons: list[str] = []
        score = 8.0
        text = self._job_text(job)

        target_terms = [
            "agent", "multi-agent", "智能体", "大模型", "llm", "rag", "langgraph",
            "ai infra", "ai基础设施", "推理", "vllm", "模型服务", "后训练",
            "sft", "dpo", "prompt", "提示词", "知识库", "向量数据库",
        ]
        strong_target_hits = [term for term in target_terms if term in text]
        if strong_target_hits:
            score += min(35, 18 + len(strong_target_hits) * 4)
            reasons.append("方向高度相关：" + "、".join(strong_target_hits[:4]))

        role_terms = self._role_terms(preferred_roles)
        if role_terms and any(term in text for term in role_terms):
            score += 18
            reasons.append("岗位方向符合画像偏好")

        requirement_terms = self._requirement_terms(job)
        matched_skills = sorted(
            s for s in user_skills
            if len(s) >= 2 and any(s in req or req in s for req in requirement_terms)
        )
        if matched_skills:
            coverage = len(matched_skills) / max(1, min(len(requirement_terms), 10))
            score += min(25, 10 + coverage * 25)
            reasons.append("技能命中：" + "、".join(matched_skills[:5]))

        location_text = (job.location or "").lower()
        location_alias = {
            "beijing": "北京", "shanghai": "上海", "hangzhou": "杭州",
            "shenzhen": "深圳", "guangzhou": "广州",
        }
        if preferred_locations and any(
            loc in location_text or location_alias.get(loc, "") in location_text
            for loc in preferred_locations
        ):
            score += 10
            reasons.append("工作地点符合偏好")

        if (salary_min or salary_max) and (job.salary_min or job.salary_max):
            wanted_low = salary_min or 0
            wanted_high = salary_max or 10**9
            job_low = job.salary_min or 0
            job_high = job.salary_max or 10**9
            if max(wanted_low, job_low) <= min(wanted_high, job_high):
                score += 8
                reasons.append("薪资范围存在交集")

        overtime_pref = str(preferences.get("overtime_tolerance") or "").lower()
        if overtime_pref and any(word in text for word in ["996", "大小周", "高强度", "抗压"]):
            score -= 8
            reasons.append("岗位描述出现工作强度信号")

        rank_boost = 1 if self._is_domestic_job(job) else 0
        if rank_boost:
            score += 5
            reasons.append("国内岗位，适合答辩展示")

        if strong_target_hits and "agent" in text:
            score += 8

        return max(0, min(98, score)), reasons, rank_boost

    def _job_text(self, job: Job) -> str:
        parts = [job.job_title, job.company_name, job.job_category, job.sub_category, job.location, job.jd_text]
        parts.extend(self._requirement_terms(job))
        return " ".join(str(p or "") for p in parts).lower()

    def _requirement_terms(self, job: Job) -> list[str]:
        terms = []
        for req in job.requirements or []:
            if isinstance(req, dict):
                val = req.get("skill_name") or req.get("name") or req.get("text") or req.get("requirement")
            else:
                val = req
            if val:
                terms.append(str(val).strip().lower())
        return terms

    def _role_terms(self, preferred_roles: list[str]) -> list[str]:
        role_aliases = {
            "backend": ["后端", "java", "go", "服务端"],
            "frontend": ["前端", "react", "vue"],
            "fullstack": ["全栈"],
            "ai_ml": ["人工智能", "算法", "机器学习", "大模型", "llm"],
            "algorithm": ["算法", "机器学习", "大模型", "llm"],
            "ai_infra": ["ai infra", "ai基础设施", "推理", "vllm", "模型服务"],
            "llm_algo": ["大模型", "llm", "后训练", "sft", "dpo"],
            "agent_algo": ["agent", "智能体", "multi-agent", "langgraph"],
            "devops": ["运维", "sre", "devops"],
        }
        return [term for role in preferred_roles for term in role_aliases.get(role, [role, role.replace("_", " ")])]

    def _is_domestic_job(self, job: Job) -> bool:
        domestic_cities = ["北京", "上海", "杭州", "深圳", "广州", "南京", "成都", "武汉", "苏州", "西安"]
        domestic_sources = ["boss", "lagou", "liepin", "51job", "zhilian", "local_seed", "seed", "user_input"]
        source = (job.source_type or "").lower()
        text = " ".join([job.location or "", job.company_name or "", job.job_title or ""])
        return any(city in text for city in domestic_cities) or any(src in source for src in domestic_sources)

    def _dedupe_key(self, job: Job) -> str:
        raw = "|".join([job.company_name or "", job.job_title or "", job.location or ""])
        return re.sub(r"\s+", "", raw).lower()

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

    def get_analysis_by_id(self, db: Session, analysis_id: int, user_id: int) -> Optional[dict]:
        """获取用户自己的单条岗位分析记录"""
        analysis = (
            db.query(JobAnalysis)
            .filter(JobAnalysis.id == analysis_id, JobAnalysis.user_id == user_id)
            .first()
        )
        if not analysis:
            return None
        return {
            "id": analysis.id,
            "job_id": analysis.job_id,
            "company_name": analysis.company_name,
            "job_title": analysis.job_title,
            "risk_level": analysis.risk_level,
            "recommendation_index": analysis.recommendation_index,
            "match_score": analysis.match_score,
            "analysis": analysis.analysis_json,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        }

    def analyze_existing_job_fast(self, db: Session, user_id: int, job_id: int) -> dict:
        """快速生成可回看的岗位分析记录，避免答辩演示时等待长链路 LLM。"""
        job = db.query(Job).filter(Job.id == job_id, Job.is_active == 1).first()
        if not job:
            return {"error": "Job not found"}

        profile = profile_service.get_full_profile(db, user_id)
        basic = profile.get("basic", {})
        preferences = profile.get("preferences", {})
        user_skills = {
            str(item.get("skill_name", "")).strip().lower()
            for item in profile.get("skills", []) if item.get("skill_name")
        }
        preferred_roles = [str(x).lower() for x in (preferences.get("preferred_job_types") or [])]
        preferred_roles += [str(x).lower() for x in (preferences.get("preferred_sub_categories") or [])]
        preferred_locations = [str(x).lower() for x in (preferences.get("preferred_locations") or [])]
        score, reasons, _ = self._score_job(
            job=job,
            user_skills=user_skills,
            preferred_roles=preferred_roles,
            preferred_locations=preferred_locations,
            salary_min=basic.get("expected_salary_min"),
            salary_max=basic.get("expected_salary_max"),
            preferences=preferences,
        )
        match_percent = round(score)
        risk_level = "low" if match_percent >= 75 else "medium" if match_percent >= 45 else "high"
        recommendation_index = 5 if match_percent >= 85 else 4 if match_percent >= 70 else 3 if match_percent >= 50 else 2
        requirements = self._requirement_terms(job)
        intensity_flags = [word for word in ["996", "大小周", "高强度", "抗压"] if word in self._job_text(job)]
        report = {
            "company_name": job.company_name,
            "job_title": job.job_title,
            "match_score": match_percent,
            "risk_level": risk_level,
            "recommendation_index": recommendation_index,
            "recommendation_text": "优先考虑" if recommendation_index >= 4 else "建议进一步确认",
            "dimensions": {
                "jd_analysis": {
                    "overtime_risk": "medium" if intensity_flags else "low",
                    "fake_job_suspicion": "low",
                    "kpi_brushing_suspicion": "low",
                    "salary_authenticity": "薪资范围明确" if job.salary_min or job.salary_max else "未标注薪资",
                    "assessment": "岗位描述与目标方向匹配度较高，适合用于进一步沟通。" if match_percent >= 70 else "岗位与当前画像存在部分匹配，但需要面试中确认职责边界。",
                    "score": 4 if not intensity_flags else 3,
                },
                "match_with_user": {
                    "skill_match": "；".join(reasons[:3]) or "显式技能命中较少",
                    "salary_match": "薪资范围存在交集" if job.salary_min or job.salary_max else "岗位未标注薪资",
                    "location_match": "地点符合偏好" if any("地点" in r for r in reasons) else "地点需要进一步确认",
                    "intensity_match": "出现工作强度信号，建议面试确认" if intensity_flags else "未发现明显高强度信号",
                    "score": max(1, min(5, round(match_percent / 20))),
                },
            },
            "overall_score": round(max(0, 10 - match_percent / 10), 1),
            "summary": f"该岗位与马嘉玲当前画像的匹配度约为 {match_percent}%。主要依据包括：{'；'.join(reasons[:4]) or '岗位方向和画像信息的基础匹配'}。",
            "red_flags": [f"岗位描述出现“{flag}”等工作强度信号" for flag in intensity_flags],
            "positive_points": reasons[:5] or ["岗位信息较完整，可作为进一步分析对象"],
            "advice": "建议优先展示并进一步投递/沟通，面试时重点确认团队方向、导师机制、工作强度和实习转正路径。" if match_percent >= 75 else "建议作为备选岗位，面试前继续核对职责、地点和工作强度。",
            "report": "",
            "job_snapshot": {
                "location": job.location,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "requirements": requirements[:12],
                "source_type": job.source_type,
            },
        }
        analysis = JobAnalysis(
            job_id=job.id,
            user_id=user_id,
            company_name=job.company_name,
            job_title=job.job_title,
            risk_level=risk_level,
            recommendation_index=recommendation_index,
            match_score=match_percent,
            analysis_json=report,
            source_type="job_card_fast",
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        report["analysis_id"] = analysis.id
        return {"job_info": self._job_to_dict(job), "report": report, "analysis_id": analysis.id}

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
                "job_id": a.job_id,
                "company_name": a.company_name,
                "job_title": a.job_title,
                "risk_level": a.risk_level,
                "recommendation_index": a.recommendation_index,
                "match_score": a.match_score,
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
            "jd_text": job.jd_text,
            "source_url": job.source_url,
            "source_type": job.source_type,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        }


# 全局单例
job_service = JobService()
