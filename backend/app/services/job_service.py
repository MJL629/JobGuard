"""
岗位分析服务层

负责：
1. 串联 岗位解析 Agent → 企业背调 Agent
2. 岗位分析结果存入 MySQL
3. 提供岗位库查询和推荐接口
"""

import json
import logging
import re
from typing import Optional
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.company import Company
from app.models.analysis import JobAnalysis
from app.agents.job_parser import job_parser
from app.agents.background_check import background_check
from app.services.profile_service import profile_service

logger = logging.getLogger(__name__)

DEFAULT_RECOMMENDATION_WEIGHTS = {
    "rule": 0.55,
    "keyword": 0.25,
    "semantic": 0.20,
}


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
        existing_job_id: int | None = None,
    ) -> dict:
        """
        完整分析流程：解析岗位 → 企业背调 → 存储结果

        Args:
            db: 数据库会话
            user_id: 用户 ID
            raw_input: 用户输入的岗位链接/文本
            input_type: 输入类型

        Returns:
            分析报告 dict
        """
        # 1. 解析岗位
        job_info = await job_parser.parse(raw_input, input_type)
        if "error" in job_info:
            return job_info

        # 2. 获取用户画像（用于个性化评估）
        user_profile = profile_service.get_full_profile(db, user_id)

        # 3. 企业背调（内置真实 WebSearch，无需外部注入）
        report = await background_check.investigate(
            job_info=job_info,
            user_profile=user_profile,
            db=db,
        )

        # 4. 存储：企业信息
        company = self._upsert_company(db, job_info, report)

        # 5. 存储：岗位信息
        job = self._upsert_job(
            db,
            job_info,
            company.id if company else None,
            existing_job_id=existing_job_id,
        )

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
        query = db.query(Job).filter(
            Job.is_active == 1,
            or_(Job.expires_at.is_(None), Job.expires_at > datetime.utcnow()),
        )

        if category:
            query = query.filter(Job.job_category == category)
        if sub_category:
            query = query.filter(Job.sub_category == sub_category)
        if location:
            query = query.filter(Job.location.contains(location))
        if salary_min is not None:
            query = query.filter(Job.salary_max >= salary_min)

        source_jobs = query.order_by(
            Job.source_url.isnot(None).desc(),
            Job.posted_at.desc(),
            Job.id.desc(),
        ).all()
        jobs = self._deduplicate_jobs([
            self._job_to_dict(job) for job in source_jobs
        ])
        total = len(jobs)
        start = (page - 1) * page_size

        return {
            "items": jobs[start:start + page_size],
            "total": total,
            "source_record_total": len(source_jobs),
            "page": page,
            "page_size": page_size,
        }

    def recommend_jobs(
        self,
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """基于已持久化画像做可解释、可复现的岗位排序。"""
        profile = profile_service.get_full_profile(db, user_id)
        candidates = self.list_jobs(db, page=1, page_size=10_000).get("items", [])
        ranked = []
        for job in candidates:
            scoring = self._score_job(profile, job)
            ranked.append({
                **job,
                **scoring,
            })

        ranked.sort(key=lambda item: (
            item["match_score"] is None,
            len(item.get("hard_conflicts", [])),
            -(item["match_score"] if item["match_score"] is not None else -1),
            -item.get("evidence_coverage", 0),
            -int(item.get("id") or 0),
        ))
        start = (page - 1) * page_size
        return {
            "items": ranked[start:start + page_size],
            "total": len(ranked),
            "page": page,
            "page_size": page_size,
            "profile_completeness": profile.get("completeness", 0),
            "scoring_version": "hybrid-recall-v3",
            "scoring_weights": DEFAULT_RECOMMENDATION_WEIGHTS,
            "weight_selection": "offline benchmark: backend/benchmarks/recommendation_weight_eval.py",
        }

    @classmethod
    def _score_job(cls, profile: dict, job: dict, weights: Optional[dict[str, float]] = None) -> dict:
        """规则召回 + 关键词召回 + 语义召回的融合排序。

        设计目标：
        - 规则分 55%：岗位方向、城市、薪资、工作强度等硬条件优先。
        - 关键词分 25%：显式技能/职责命中，保证推荐理由可解释。
        - 语义分 20%：用岗位 taxonomy 和同义词扩展弥补字面不一致。

        这里不让 LLM 直接生成匹配度，避免推荐分数不可复现。后续如果
        Chroma job_kb 已完整构建，可把 semantic 部分替换/增强为真实
        embedding top-k 相似度。
        """
        basic = profile.get("basic", {})
        preferences = profile.get("preferences", {})
        skills = {
            cls._normalize_term(item.get("skill_name", ""))
            for item in profile.get("skills", [])
            if item.get("skill_name")
        }
        projects = profile.get("projects", []) or []
        has_profile_evidence = bool(
            basic.get("expected_salary_min")
            or basic.get("expected_salary_max")
            or preferences.get("preferred_job_types")
            or preferences.get("preferred_locations")
            or skills
            or projects
        )
        profile_text = cls._profile_text(profile)
        job_text = cls._job_search_text(job)

        reasons: list[str] = []
        concerns: list[str] = []
        hard_conflicts: list[str] = []
        unassessed: list[str] = []

        normalized_weights = cls._normalize_recommendation_weights(weights)

        rule_score, rule_reasons, rule_concerns, rule_conflicts, rule_unassessed, rule_detail = cls._rule_recall_score(
            basic=basic,
            preferences=preferences,
            job=job,
        )
        keyword_score, keyword_reasons, keyword_concerns, keyword_detail = cls._keyword_recall_score(
            skills=skills,
            projects=projects,
            job=job,
        )
        semantic_score, semantic_reasons, semantic_concerns, semantic_detail = cls._semantic_recall_score(
            profile_text=profile_text,
            job=job,
            job_text=job_text,
            preferences=preferences,
        )

        reasons.extend(rule_reasons + keyword_reasons + semantic_reasons)
        concerns.extend(rule_concerns + keyword_concerns + semantic_concerns)
        hard_conflicts.extend(rule_conflicts)
        unassessed.extend(rule_unassessed)

        source_bonus = 3 if cls._is_domestic_or_official(job) else 0

        raw_score = (
            rule_score * normalized_weights["rule"]
            + keyword_score * normalized_weights["keyword"]
            + semantic_score * normalized_weights["semantic"]
            + source_bonus
        )
        if hard_conflicts:
            raw_score = min(raw_score, 49)

        evidence_coverage = cls._recommendation_evidence_coverage(rule_detail, keyword_detail, semantic_detail)
        if not has_profile_evidence:
            evidence_coverage = 0
        match_score = None if evidence_coverage < 50 else max(0, min(98, round(raw_score)))
        if match_score is None:
            concerns.insert(0, f"评分证据覆盖率仅{evidence_coverage}%，暂不显示误导性的匹配百分比")
        if unassessed:
            concerns.append(f"规则未参与项：{'、'.join(dict.fromkeys(unassessed))}")

        return {
            "match_score": match_score,
            "match_reasons": reasons[:8],
            "match_concerns": concerns[:8],
            "score_breakdown": {
                "rule_recall": {"score": round(rule_score, 2), "weight": normalized_weights["rule"], "detail": rule_detail},
                "keyword_recall": {"score": round(keyword_score, 2), "weight": normalized_weights["keyword"], "detail": keyword_detail},
                "semantic_recall": {"score": round(semantic_score, 2), "weight": normalized_weights["semantic"], "detail": semantic_detail},
                "source_bonus": source_bonus,
                "final_formula": (
                    f"rule*{normalized_weights['rule']:.2f} + "
                    f"keyword*{normalized_weights['keyword']:.2f} + "
                    f"semantic*{normalized_weights['semantic']:.2f} + source_bonus - hard_conflict_cap"
                ),
            },
            "retrieval_channels": {
                "rule": rule_reasons,
                "keyword": keyword_reasons,
                "semantic": semantic_reasons,
            },
            "evidence_coverage": evidence_coverage,
            "unassessed_fields": list(dict.fromkeys(unassessed)),
            "hard_constraint_status": "conflict" if hard_conflicts else ("clear" if evidence_coverage >= 50 else "unknown"),
            "hard_conflicts": list(dict.fromkeys(hard_conflicts)),
        }

    @staticmethod
    def _normalize_recommendation_weights(weights: Optional[dict[str, float]] = None) -> dict[str, float]:
        """Normalize retrieval weights for offline experiments and safe defaults."""
        raw = dict(DEFAULT_RECOMMENDATION_WEIGHTS)
        if weights:
            for key in ("rule", "keyword", "semantic"):
                if key in weights:
                    raw[key] = max(0.0, float(weights[key]))
        total = sum(raw.values())
        if total <= 0:
            return dict(DEFAULT_RECOMMENDATION_WEIGHTS)
        return {key: round(value / total, 4) for key, value in raw.items()}

    @classmethod
    def _rule_recall_score(
        cls,
        *,
        basic: dict,
        preferences: dict,
        job: dict,
    ) -> tuple[float, list[str], list[str], list[str], list[str], dict]:
        """硬条件规则召回：方向/地点/薪资/工作强度/来源。"""
        reasons: list[str] = []
        concerns: list[str] = []
        hard_conflicts: list[str] = []
        unassessed: list[str] = []
        detail: dict = {}
        assessed = 0
        earned = 0.0

        directions = [str(item).lower() for item in preferences.get("preferred_job_types") or []]
        job_direction_text = " ".join([
            str(job.get("job_title", "")), str(job.get("sub_category", "")),
            str(job.get("job_category", "")),
        ]).lower()
        if directions and job_direction_text.strip():
            assessed += 25
            matched_direction = next(
                (direction for direction in directions if cls._direction_matches(direction, job_direction_text)),
                None,
            )
            direction_score = 25 if matched_direction else 0
            earned += direction_score
            if matched_direction:
                reasons.append(f"规则召回：岗位方向命中 {matched_direction}")
            else:
                message = f"方向冲突：偏好{'/'.join(directions)}，岗位为{job.get('job_title') or '未命名岗位'}"
                concerns.append(message)
                hard_conflicts.append(message)
            detail["direction"] = {"score": direction_score, "max": 25, "assessed": True}
        else:
            missing = "画像岗位方向" if not directions else "岗位方向"
            unassessed.append(missing)
            detail["direction"] = {"score": None, "max": 25, "assessed": False}

        locations = [str(item).lower() for item in preferences.get("preferred_locations") or []]
        job_location = str(job.get("location", "")).lower()
        if locations and job_location:
            assessed += 20
            location_score = 20 if any(location in job_location or job_location in location for location in locations) else 0
            earned += location_score
            if location_score:
                matched_location = next(location for location in locations if location in job_location or job_location in location)
                reasons.append(f"规则召回：地点命中 {matched_location}")
            else:
                message = f"地点冲突：岗位在{job.get('location')}，意向为{'/'.join(locations)}"
                concerns.append(message)
                hard_conflicts.append(message)
            detail["location"] = {"score": location_score, "max": 20, "assessed": True}
        else:
            missing = "画像意向城市" if not locations else "岗位城市"
            unassessed.append(missing)
            detail["location"] = {"score": None, "max": 20, "assessed": False}

        expected_min = basic.get("expected_salary_min")
        salary_min = job.get("salary_min")
        salary_max = job.get("salary_max")
        if expected_min and salary_max:
            assessed += 20
            if salary_max < expected_min:
                salary_score = 0
                message = f"薪资冲突：岗位上限{salary_max // 1000}K，低于期望下限{expected_min // 1000}K"
                concerns.append(message)
                hard_conflicts.append(message)
            elif salary_min and salary_min >= expected_min:
                salary_score = 20
                reasons.append(f"规则召回：薪资 {salary_min // 1000}-{salary_max // 1000}K 达到期望")
            else:
                salary_score = 14
                reasons.append(f"规则召回：薪资上限 {salary_max // 1000}K 达到期望")
            earned += salary_score
            detail["salary"] = {"score": salary_score, "max": 20, "assessed": True}
        else:
            missing = "画像期望薪资" if not expected_min else "岗位薪资"
            unassessed.append(missing)
            detail["salary"] = {"score": None, "max": 20, "assessed": False}

        cls._append_workload_conflicts(preferences, job, concerns, hard_conflicts)
        workload_score = 0 if any("工作强度冲突" in item or "休息制度冲突" in item for item in hard_conflicts) else 15
        assessed += 15
        earned += workload_score
        detail["workload"] = {"score": workload_score, "max": 15, "assessed": True}

        source_score = 10 if cls._is_domestic_or_official(job) else 4
        assessed += 10
        earned += source_score
        detail["source"] = {"score": source_score, "max": 10, "assessed": True}

        normalized = earned / assessed * 100 if assessed else 0
        return normalized, reasons, concerns, hard_conflicts, unassessed, detail

    @classmethod
    def _keyword_recall_score(
        cls,
        *,
        skills: set[str],
        projects: list[dict],
        job: dict,
    ) -> tuple[float, list[str], list[str], dict]:
        """关键词召回：技能词、JD 要求和项目技术栈显式命中。"""
        reasons: list[str] = []
        concerns: list[str] = []
        requirement_text = " ".join([
            *[str(item) for item in job.get("requirements") or []],
            str(job.get("jd_text") or ""),
        ])
        required_skills = cls._extract_required_skills(requirement_text)
        matched_skills = sorted(required_skills & skills)
        project_terms = {
            cls._normalize_term(term)
            for project in projects
            for term in [
                *(project.get("tech_stack") or [] if isinstance(project.get("tech_stack"), list) else []),
                project.get("project_name", ""),
                project.get("description", ""),
            ]
            if term
        }
        matched_project_terms = sorted(required_skills & project_terms)

        if not skills and not project_terms:
            return 0.0, reasons, ["关键词召回：画像暂无可匹配技能或项目"], {
                "assessed": False,
                "required_skills": sorted(required_skills),
                "matched_skills": [],
                "matched_project_terms": [],
            }

        if not required_skills:
            return 35.0, reasons, ["关键词召回：岗位未抽取到明确技能词"], {
                "assessed": False,
                "required_skills": [],
                "matched_skills": [],
                "matched_project_terms": [],
            }

        skill_score = 70 * len(matched_skills) / len(required_skills) if skills else 0
        project_score = 30 * len(matched_project_terms) / len(required_skills) if project_terms else 0
        score = min(100, skill_score + project_score)
        if matched_skills:
            reasons.append(f"关键词召回：技能命中 {len(matched_skills)}/{len(required_skills)}（{'、'.join(matched_skills[:5])}）")
        if matched_project_terms:
            reasons.append(f"关键词召回：项目技术栈命中 {'、'.join(matched_project_terms[:4])}")
        missing_skills = sorted(required_skills - skills)
        if missing_skills:
            concerns.append(f"关键词缺口：岗位提到 {'、'.join(missing_skills[:5])}，画像技能暂未体现")

        return score, reasons, concerns, {
            "assessed": True,
            "required_skills": sorted(required_skills),
            "matched_skills": matched_skills,
            "matched_project_terms": matched_project_terms,
        }

    @classmethod
    def _semantic_recall_score(
        cls,
        *,
        profile_text: str,
        job: dict,
        job_text: str,
        preferences: dict,
    ) -> tuple[float, list[str], list[str], dict]:
        """语义召回：基于岗位 taxonomy/同义词的轻量语义匹配。

        这里是在线稳定版本，不依赖外部 embedding 服务；与 Chroma/BGE-M3
        的真实向量召回可以并存，后续可把相似度写入同一 semantic 通道。
        """
        reasons: list[str] = []
        concerns: list[str] = []
        user_concepts = cls._semantic_concepts(profile_text + " " + " ".join(
            str(item) for item in preferences.get("preferred_job_types") or []
        ))
        job_concepts = cls._semantic_concepts(job_text)
        if not user_concepts or not job_concepts:
            return 30.0, reasons, ["语义召回：画像或岗位语义信息不足"], {
                "assessed": False,
                "user_concepts": sorted(user_concepts),
                "job_concepts": sorted(job_concepts),
                "matched_concepts": [],
            }

        matched = sorted(user_concepts & job_concepts)
        score = min(100, 25 + 75 * len(matched) / max(1, len(user_concepts)))
        if matched:
            reasons.append(f"语义召回：职业方向概念匹配 {'、'.join(matched[:5])}")
        else:
            concerns.append("语义召回：岗位表述与画像核心方向相似度较低")

        # 岗位标题和细分方向对用户关注概念命中时额外强化。
        title_text = " ".join([str(job.get("job_title") or ""), str(job.get("sub_category") or "")]).lower()
        if matched and any(concept in title_text for concept in matched):
            score = min(100, score + 10)

        return score, reasons, concerns, {
            "assessed": True,
            "user_concepts": sorted(user_concepts),
            "job_concepts": sorted(job_concepts),
            "matched_concepts": matched,
        }

    @classmethod
    def _recommendation_evidence_coverage(
        cls,
        rule_detail: dict,
        keyword_detail: dict,
        semantic_detail: dict,
    ) -> int:
        """估算推荐分数证据覆盖率，避免数据太少时展示伪精确分数。"""
        coverage = 0
        for key in ("direction", "location", "salary"):
            item = rule_detail.get(key) or {}
            if item.get("assessed"):
                coverage += int(item.get("max") or 0)
        if keyword_detail.get("assessed"):
            coverage += 35
        # 语义召回只作为增强证据，不能单独把薄画像抬成高覆盖率。
        if semantic_detail.get("assessed") and coverage >= 50:
            coverage += 20
        return round(min(100, coverage))

    @classmethod
    def _profile_text(cls, profile: dict) -> str:
        """把结构化画像压成检索文本，用于轻量语义召回。"""
        basic = profile.get("basic", {}) or {}
        preferences = profile.get("preferences", {}) or {}
        parts: list[str] = [
            str(basic.get("degree") or ""),
            str(basic.get("major") or ""),
            str(basic.get("school") or ""),
            str(basic.get("current_city") or ""),
            str(basic.get("resume_raw_text") or ""),
        ]
        for key in ("preferred_job_types", "preferred_sub_categories", "preferred_industries"):
            parts.extend(str(item) for item in preferences.get(key) or [])
        for skill in profile.get("skills", []) or []:
            parts.append(str(skill.get("skill_name") or ""))
            parts.append(str(skill.get("category") or ""))
        for project in profile.get("projects", []) or []:
            parts.append(str(project.get("project_name") or ""))
            parts.append(str(project.get("description") or ""))
            parts.append(str(project.get("highlights") or ""))
            tech_stack = project.get("tech_stack") or []
            if isinstance(tech_stack, list):
                parts.extend(str(item) for item in tech_stack)
        return " ".join(parts).lower()

    @classmethod
    def _job_search_text(cls, job: dict) -> str:
        """岗位检索文本：标题、类别、JD、要求、福利、来源。"""
        parts = [
            job.get("company_name"),
            job.get("job_title"),
            job.get("job_category"),
            job.get("sub_category"),
            job.get("location"),
            job.get("jd_text"),
            job.get("source_type"),
        ]
        parts.extend(job.get("requirements") or [])
        parts.extend(job.get("benefits") or [])
        return " ".join(str(part or "") for part in parts).lower()

    @classmethod
    def _semantic_concepts(cls, text: str) -> set[str]:
        """把不同表述归一到可解释的岗位语义概念。"""
        lowered = str(text or "").lower()
        taxonomy = {
            "大模型应用": ["大模型应用", "llm application", "llm应用", "ai应用", "生成式ai", "genai"],
            "智能体": ["agent", "智能体", "multi-agent", "多智能体", "tool calling", "function calling", "langgraph"],
            "RAG": ["rag", "检索增强", "知识库", "向量数据库", "embedding", "语义检索", "召回"],
            "后端工程": ["后端", "服务端", "fastapi", "spring boot", "接口", "api", "微服务"],
            "AI Infra": ["ai infra", "ai基础设施", "vllm", "推理服务", "模型服务", "kv cache", "serving"],
            "算法训练": ["算法", "机器学习", "深度学习", "pytorch", "tensorflow", "sft", "dpo", "lora", "后训练"],
            "数据分析": ["数据分析", "sql", "tableau", "powerbi", "可视化", "数据挖掘"],
            "前端工程": ["前端", "vue", "react", "typescript", "javascript", "vite"],
            "Java工程": ["java", "spring", "mybatis", "jvm"],
            "测试运维": ["测试", "qa", "devops", "sre", "kubernetes", "docker"],
        }
        return {
            concept
            for concept, aliases in taxonomy.items()
            if any(alias.lower() in lowered for alias in aliases)
        }

    @classmethod
    def _is_domestic_or_official(cls, job: dict) -> bool:
        """国内/官方来源优先，用于抑制公开英文岗位喧宾夺主。"""
        source_type = str(job.get("source_type") or "").lower()
        source_url = str(job.get("source_url") or "").lower()
        location = str(job.get("location") or "")
        company = str(job.get("company_name") or "")
        domestic_cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "苏州", "西安", "珠海"]
        source_keywords = ["beijing_hr_open_data", "official", "boss", "liepin", "lagou", "51job", "zhilian", "local", "seed"]
        return (
            any(city in location or city in company for city in domestic_cities)
            or any(keyword in source_type for keyword in source_keywords)
            or ".gov.cn" in source_url
        )

    @classmethod
    def _deduplicate_jobs(cls, jobs: list[dict]) -> list[dict]:
        """Collapse repeated source rows while keeping genuinely different cities.

        Source IDs remain available in ``merged_job_ids`` so deduplication never
        destroys provenance.  A missing location is treated as compatible with a
        known location for the same company/title because user-pasted analyses
        frequently omit it.
        """
        grouped_indexes: dict[tuple[str, str], list[int]] = {}
        result: list[dict] = []

        for raw_job in jobs:
            job = dict(raw_job)
            base_key = cls._job_base_key(job)
            location = cls._location_bucket(job.get("location"))
            match_index = None
            for index in grouped_indexes.get(base_key, []):
                existing_location = cls._location_bucket(result[index].get("location"))
                if cls._locations_compatible(existing_location, location):
                    match_index = index
                    break

            if match_index is None:
                job["duplicate_count"] = 1
                job["merged_job_ids"] = [job.get("id")]
                grouped_indexes.setdefault(base_key, []).append(len(result))
                result.append(job)
                continue

            current = result[match_index]
            merged_ids = [
                *current.get("merged_job_ids", [current.get("id")]),
                job.get("id"),
            ]
            winner, other = (
                (job, current)
                if cls._job_quality(job) > cls._job_quality(current)
                else (current, job)
            )
            merged = dict(winner)
            for field in (
                "location", "salary_min", "salary_max", "requirements",
                "benefits", "jd_text", "source_url", "source_external_id",
                "source_published_at", "posted_at", "expires_at", "last_seen_at",
            ):
                if not merged.get(field) and other.get(field):
                    merged[field] = other[field]
            merged["duplicate_count"] = len({item for item in merged_ids if item is not None})
            merged["merged_job_ids"] = list(dict.fromkeys(
                item for item in merged_ids if item is not None
            ))
            result[match_index] = merged

        return result

    @staticmethod
    def _job_base_key(job: dict) -> tuple[str, str]:
        def normalize(value: object) -> str:
            return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())

        company = normalize(job.get("company_name"))
        title = normalize(job.get("job_title"))
        if company and title:
            return company, title
        return "__id__", str(job.get("id"))

    @staticmethod
    def _location_bucket(value: object) -> str:
        text = re.sub(r"\s+", "", str(value or "")).lower()
        if not text:
            return ""
        prefix = re.split(r"[·•,/，\-]", text, maxsplit=1)[0]
        match = re.match(r"(.{2,12}?)(?:市|自治州|地区|盟)", prefix)
        return (match.group(1) if match else prefix).removesuffix("省")

    @staticmethod
    def _locations_compatible(first: str, second: str) -> bool:
        return not first or not second or first == second

    @staticmethod
    def _job_quality(job: dict) -> tuple[int, int, int, int, int, int]:
        source_type = str(job.get("source_type") or "").lower()
        source_url = str(job.get("source_url") or "").lower()
        official = int(
            "official" in source_type
            or "open_data" in source_type
            or ".gov.cn" in source_url
        )
        return (
            official,
            int(bool(job.get("source_url"))),
            int(bool(job.get("source_external_id"))),
            int(bool(job.get("location"))),
            min(len(str(job.get("jd_text") or "")), 2000),
            int(job.get("id") or 0),
        )

    @staticmethod
    def _normalize_term(value: str) -> str:
        aliases = {
            "springboot": "spring boot",
            "js": "javascript",
            "ts": "typescript",
            "postgres": "postgresql",
        }
        normalized = re.sub(r"[^a-z0-9+#.\u4e00-\u9fff]", "", str(value).lower())
        return aliases.get(normalized, normalized)

    @classmethod
    def _extract_required_skills(cls, text: str) -> set[str]:
        catalog = [
            "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "PHP",
            "Vue", "React", "Angular", "FastAPI", "Django", "Flask", "Spring Boot",
            "MySQL", "PostgreSQL", "Redis", "MongoDB", "SQL", "Docker", "Kubernetes",
            "Linux", "Git", "PyTorch", "TensorFlow", "LangChain", "LangGraph", "Figma",
            "Photoshop",
        ]
        lowered = text.lower()
        return {
            cls._normalize_term(skill)
            for skill in catalog
            if re.search(rf"(?<![a-z]){re.escape(skill.lower())}(?![a-z])", lowered)
        }

    @staticmethod
    def _direction_matches(direction: str, job_text: str) -> bool:
        direction = direction.lower()
        job_text = job_text.lower()
        core = re.sub(r"(?:开发)?工程师|开发|岗位|职位", "", direction).strip()
        if direction in job_text or (len(core) >= 2 and core in job_text):
            return True
        alias_groups = {
            "agent": [
                "agent", "智能体", "大模型应用", "ai应用", "rag",
                "tool calling", "langgraph", "langchain",
            ],
            "后端": ["后端", "服务端", "java", "python", "golang", "go开发"],
            "前端": ["前端", "web开发", "javascript", "vue", "react"],
            "算法": ["算法", "机器学习", "深度学习", "ai", "大模型"],
            "测试": ["测试", "qa", "质量保障"],
            "运维": ["运维", "devops", "sre"],
            "产品": ["产品经理", "产品运营"],
            "设计": ["设计", "ui", "ux"],
            "数据": ["数据分析", "数据开发", "数据工程"],
        }
        return any(
            key in direction and any(alias in job_text for alias in aliases)
            for key, aliases in alias_groups.items()
        )

    @staticmethod
    def _append_workload_conflicts(
        preferences: dict,
        job: dict,
        concerns: list[str],
        hard_conflicts: list[str],
    ) -> None:
        evidence = " ".join([
            str(job.get("jd_text") or ""),
            " ".join(str(item) for item in job.get("benefits") or []),
            " ".join(str(item) for item in job.get("requirements") or []),
        ])
        if not evidence:
            return
        conflicts = []
        if preferences.get("weekend_preference") == "必须双休" and re.search(r"单休|大小周", evidence):
            conflicts.append("休息制度冲突：画像要求双休，但岗位原文出现单休/大小周")
        rejects_intensity = preferences.get("labor_intensity") == "排斥高强度"
        rejects_overtime = preferences.get("overtime_tolerance") == "不接受"
        if (rejects_intensity or rejects_overtime) and re.search(r"996|007|长期加班|经常加班|高强度", evidence, re.IGNORECASE):
            conflicts.append("工作强度冲突：岗位原文出现高强度或长期加班信号")
        for conflict in conflicts:
            if conflict not in hard_conflicts:
                hard_conflicts.append(conflict)
                concerns.append(conflict)

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

        # 岗位 JD 风险不等于企业风险，禁止把单次岗位分析写成企业事实。
        company.last_checked = datetime.utcnow()
        company.data_source = report.get("verification_status", "jd_only")

        # 更新背调信息
        dimensions = report.get("dimensions", {})
        si = dimensions.get("social_insurance", {})
        if si.get("verified") and si.get("participants") is not None:
            try:
                company.social_insurance_count = int(str(si["participants"]).replace("人", ""))
            except (ValueError, TypeError):
                pass

        ld = dimensions.get("labor_disputes", {})
        if ld.get("verified") and ld.get("total_cases") is not None:
            try:
                company.labor_dispute_count = int(str(ld["total_cases"]).replace("起", ""))
            except (ValueError, TypeError):
                pass

        db.flush()
        return company

    def _upsert_job(
        self,
        db: Session,
        job_info: dict,
        company_id: Optional[int],
        *,
        existing_job_id: int | None = None,
    ) -> Optional[Job]:
        """创建或更新岗位信息"""
        company_name = job_info.get("company_name", "")
        job_title = job_info.get("job_title", "")
        source_url = job_info.get("source_url") or ""

        if not company_name or not job_title:
            return None

        # 从岗位库进入分析时复用原岗位，只新增分析记录，避免覆盖官方原始数据。
        if existing_job_id is not None:
            existing_job = db.query(Job).filter(Job.id == existing_job_id).first()
            if existing_job is None:
                raise ValueError("指定的岗位不存在")
            return existing_job

        # 复用同一来源或同企业/岗位/城市的记录。分析动作只新增分析报告，
        # 不再反复复制岗位，也不覆盖已经保存的官方来源。
        job = None
        if source_url:
            job = db.query(Job).filter(Job.source_url == source_url).first()

        if not job:
            incoming_location = self._location_bucket(job_info.get("location"))
            candidates = (
                db.query(Job)
                .filter(Job.company_name == company_name, Job.job_title == job_title)
                .order_by(Job.source_url.isnot(None).desc(), Job.id.desc())
                .all()
            )
            job = next(
                (
                    candidate for candidate in candidates
                    if self._locations_compatible(
                        self._location_bucket(candidate.location), incoming_location
                    )
                ),
                None,
            )

        if job:
            return job

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
            "source_external_id": job.source_external_id,
            "source_published_at": job.source_published_at.isoformat() if job.source_published_at else None,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            "expires_at": job.expires_at.isoformat() if job.expires_at else None,
            "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
        }


# 全局单例
job_service = JobService()
