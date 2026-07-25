"""
用户画像服务层

负责：
1. 将 Agent 提取的结构化信息写入 MySQL
2. 将用户信息向量化写入 Chroma 知识库
3. 画像完整度计算
"""

import json
import logging
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.user import (
    User, UserProfile, UserProject, UserSkill, Education, UserPreference,
)
from app.rag.user_kb import user_kb
from app.agents.profile_agent import profile_agent

logger = logging.getLogger(__name__)


class ProfileService:
    """用户画像服务"""

    # ─── 简历解析 + 存储 ──────────────────────────────────────────────

    async def process_resume(
        self,
        db: Session,
        user_id: int,
        resume_text: str,
        file_path: Optional[str] = None,
    ) -> dict:
        """
        处理用户上传的简历：
        1. Agent 解析简历提取结构化信息
        2. 存入 MySQL
        3. 向量化存入 Chroma

        Returns:
            {"parsed": {...}, "profile": {...}, "completeness": int}
        """
        # 1. Agent 解析
        parsed = await profile_agent.parse_resume(resume_text)
        if not parsed:
            return {"error": "简历解析失败", "parsed": {}}

        # 2. 存入 MySQL
        profile = self._save_parsed_resume(db, user_id, parsed, resume_text, file_path)

        # 3. 向量化存入 Chroma
        await self._sync_to_vector_store(user_id, parsed)

        # 4. 计算完整度
        completeness_result = profile_agent.check_completeness(self._profile_to_dict(profile, parsed))

        return {
            "parsed": parsed,
            "profile": self._profile_to_dict(profile, parsed),
            "completeness": completeness_result["completeness"],
            "missing_fields": completeness_result["missing"],
        }

    # ─── 画像更新 ─────────────────────────────────────────────────────

    async def update_profile(
        self,
        db: Session,
        user_id: int,
        updates: dict,
    ) -> dict:
        """
        更新用户画像（从对话中提取的信息）

        Args:
            updates: Agent 提取的变更字段
        """
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)

        # 更新基本信息字段
        basic_fields = [
            "full_name", "gender", "birth_year", "degree", "major",
            "school", "graduation_year", "current_city",
        ]
        for field in basic_fields:
            if field in updates and updates[field] is not None:
                setattr(profile, field, updates[field])

        # 更新薪资
        if "expected_salary_min" in updates and updates["expected_salary_min"] is not None:
            profile.expected_salary_min = updates["expected_salary_min"]
        if "expected_salary_max" in updates and updates["expected_salary_max"] is not None:
            profile.expected_salary_max = updates["expected_salary_max"]

        db.flush()

        # 更新偏好表
        pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        if not pref:
            pref = UserPreference(user_id=user_id)
            db.add(pref)

        pref_fields = [
            "preferred_locations", "preferred_job_types", "preferred_sub_categories",
            "preferred_industries", "overtime_tolerance", "weekend_preference",
            "holiday_preference", "labor_intensity", "remote_work", "company_scale_pref",
        ]
        for field in pref_fields:
            if field in updates and updates[field] is not None:
                setattr(pref, field, updates[field])

        # job_direction 映射到 preferred_job_types
        if "job_direction" in updates and updates["job_direction"] is not None:
            direction = updates["job_direction"]
            if isinstance(direction, str):
                pref.preferred_job_types = [direction]
            elif isinstance(direction, list):
                pref.preferred_job_types = direction

        db.flush()

        # 更新完整度
        profile.profile_completeness = profile_agent.check_completeness(
            self._profile_to_dict(profile, {})
        )["completeness"]

        db.commit()

        # 同步到向量库
        await self._sync_to_vector_store(user_id, updates)

        return self._profile_to_dict(profile, {})

    # ─── 画像查询 ─────────────────────────────────────────────────────

    def get_full_profile(self, db: Session, user_id: int) -> dict:
        """获取用户完整画像"""
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        projects = db.query(UserProject).filter(UserProject.user_id == user_id).all()
        skills = db.query(UserSkill).filter(UserSkill.user_id == user_id).all()
        education = db.query(Education).filter(Education.user_id == user_id).all()
        pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()

        result = {
            "user_id": user_id,
            "basic": {},
            "education": [],
            "projects": [],
            "skills": [],
            "preferences": {},
            "completeness": 0,
        }

        if profile:
            result["basic"] = {
                "full_name": profile.full_name,
                "gender": profile.gender,
                "birth_year": profile.birth_year,
                "degree": profile.degree,
                "major": profile.major,
                "school": profile.school,
                "graduation_year": profile.graduation_year,
                "current_city": profile.current_city,
                "expected_salary_min": profile.expected_salary_min,
                "expected_salary_max": profile.expected_salary_max,
                "years_of_experience": profile.years_of_experience,
            }
            result["completeness"] = profile.profile_completeness

        for edu in education:
            result["education"].append({
                "school": edu.school,
                "major": edu.major,
                "degree": edu.degree,
                "start_year": edu.start_year,
                "end_year": edu.end_year,
                "gpa": edu.gpa,
                "honors": edu.honors,
            })

        for proj in projects:
            result["projects"].append({
                "id": proj.id,
                "project_name": proj.project_name,
                "role": proj.role,
                "description": proj.description,
                "tech_stack": proj.tech_stack,
                "start_date": proj.start_date,
                "end_date": proj.end_date,
                "highlights": proj.highlights,
                "project_url": proj.project_url,
                "sort_order": proj.sort_order,
            })

        for skill in skills:
            result["skills"].append({
                "skill_name": skill.skill_name,
                "proficiency": skill.proficiency,
                "category": skill.category,
            })

        if pref:
            result["preferences"] = {
                "preferred_job_types": pref.preferred_job_types,
                "preferred_sub_categories": pref.preferred_sub_categories,
                "preferred_locations": pref.preferred_locations,
                "preferred_industries": pref.preferred_industries,
                "overtime_tolerance": pref.overtime_tolerance,
                "weekend_preference": pref.weekend_preference,
                "holiday_preference": pref.holiday_preference,
                "labor_intensity": pref.labor_intensity,
                "remote_work": pref.remote_work,
                "company_scale_pref": pref.company_scale_pref,
            }

        return result

    # ─── 项目经历管理 ────────────────────────────────────────────────

    def add_project(self, db: Session, user_id: int, project_data: dict) -> dict:
        """添加项目经历"""
        project = UserProject(
            user_id=user_id,
            project_name=project_data.get("project_name", ""),
            role=project_data.get("role"),
            description=project_data.get("description"),
            tech_stack=project_data.get("tech_stack"),
            start_date=project_data.get("start_date"),
            end_date=project_data.get("end_date"),
            highlights=project_data.get("highlights"),
            project_url=project_data.get("project_url"),
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return {"id": project.id, "project_name": project.project_name}

    # ─── 私有方法 ─────────────────────────────────────────────────────

    def _save_parsed_resume(
        self,
        db: Session,
        user_id: int,
        parsed: dict,
        resume_text: str,
        file_path: Optional[str] = None,
    ) -> UserProfile:
        """将解析结果存入 MySQL"""
        # 用户画像
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)

        profile.full_name = parsed.get("full_name") or profile.full_name
        profile.gender = parsed.get("gender") or profile.gender
        profile.birth_year = parsed.get("birth_year") or profile.birth_year
        profile.degree = parsed.get("degree") or profile.degree
        profile.major = parsed.get("major") or profile.major
        profile.school = parsed.get("school") or profile.school
        profile.graduation_year = parsed.get("graduation_year") or profile.graduation_year
        profile.current_city = parsed.get("current_city") or profile.current_city
        profile.years_of_experience = parsed.get("years_of_experience", 0)
        profile.resume_raw_text = resume_text
        if file_path:
            profile.resume_file_path = file_path

        db.flush()

        # 教育经历
        education_list = parsed.get("education_list", [])
        if education_list:
            # 先删除旧数据
            db.query(Education).filter(Education.user_id == user_id).delete()
            for edu in education_list:
                db.add(Education(
                    user_id=user_id,
                    school=edu.get("school", ""),
                    major=edu.get("major", ""),
                    degree=edu.get("degree", ""),
                    start_year=edu.get("start_year"),
                    end_year=edu.get("end_year"),
                    gpa=edu.get("gpa"),
                    honors=edu.get("honors"),
                ))

        # 项目经历（追加，不覆盖已有）
        projects = parsed.get("projects", [])
        for proj in projects:
            db.add(UserProject(
                user_id=user_id,
                project_name=proj.get("project_name", ""),
                role=proj.get("role"),
                description=proj.get("description"),
                tech_stack=proj.get("tech_stack"),
                start_date=proj.get("start_date"),
                end_date=proj.get("end_date"),
                highlights=proj.get("highlights"),
                project_url=proj.get("project_url"),
            ))

        # 技能（追加，不覆盖）
        skills = parsed.get("skills", [])
        existing_skills = {
            s.skill_name for s in db.query(UserSkill).filter(UserSkill.user_id == user_id).all()
        }
        for skill in skills:
            skill_name = skill.get("skill_name", "")
            if skill_name and skill_name not in existing_skills:
                db.add(UserSkill(
                    user_id=user_id,
                    skill_name=skill_name,
                    proficiency=skill.get("proficiency", "了解"),
                    category=skill.get("category", "其他"),
                ))

        db.commit()
        db.refresh(profile)
        return profile

    async def _sync_to_vector_store(self, user_id: int, data: dict):
        """将用户信息向量化存入 Chroma"""
        try:
            documents = []
            metadatas = []

            user_id_str = str(user_id)

            # 基本信息
            basic_parts = []
            for key in ["degree", "major", "school", "current_city"]:
                if data.get(key):
                    basic_parts.append(f"{key}: {data[key]}")
            if basic_parts:
                documents.append("用户基本信息：" + "；".join(basic_parts))
                metadatas.append({"type": "basic", "user_id": user_id_str})

            # 项目经历
            projects = data.get("projects", [])
            for proj in projects:
                proj_text = f"项目名称：{proj.get('project_name', '')}\n"
                proj_text += f"角色：{proj.get('role', '')}\n"
                proj_text += f"描述：{proj.get('description', '')}\n"
                tech = proj.get("tech_stack", [])
                if tech:
                    proj_text += f"技术栈：{', '.join(tech)}\n"
                highlights = proj.get("highlights", "")
                if highlights:
                    proj_text += f"亮点：{highlights}"
                documents.append(proj_text)
                metadatas.append({
                    "type": "project",
                    "user_id": user_id_str,
                    "project_name": proj.get("project_name", ""),
                    "tech_stack": json.dumps(tech, ensure_ascii=False) if tech else "",
                })

            # 技能
            skills = data.get("skills", [])
            if skills:
                skill_text = "技能列表：" + "、".join(
                    f"{s.get('skill_name', '')}({s.get('proficiency', '')})"
                    for s in skills
                )
                documents.append(skill_text)
                metadatas.append({"type": "skills", "user_id": user_id_str})

            # 偏好
            pref_parts = []
            pref_map = {
                "preferred_job_types": "偏好岗位",
                "preferred_locations": "偏好城市",
                "weekend_preference": "周末偏好",
                "overtime_tolerance": "加班接受度",
            }
            for key, label in pref_map.items():
                val = data.get(key)
                if val:
                    pref_parts.append(f"{label}: {val}")
            # 薪资
            if data.get("expected_salary_min") and data.get("expected_salary_max"):
                pref_parts.append(
                    f"期望薪资: {data['expected_salary_min']}-{data['expected_salary_max']}元"
                )

            if pref_parts:
                documents.append("求职偏好：" + "；".join(pref_parts))
                metadatas.append({"type": "preference", "user_id": user_id_str})

            if documents:
                await user_kb.add_documents(user_id_str, documents, metadatas)
                logger.info(f"[ProfileService] 向量库同步成功，user={user_id}，共 {len(documents)} 条")

        except Exception as e:
            logger.error(f"[ProfileService] 向量库同步失败: {e}")

    def _profile_to_dict(self, profile: UserProfile, parsed: dict) -> dict:
        """将 ORM 对象转为 dict，供 Agent 使用"""
        result = {
            "full_name": profile.full_name,
            "degree": profile.degree,
            "major": profile.major,
            "school": profile.school,
            "graduation_year": profile.graduation_year,
            "current_city": profile.current_city,
            "expected_salary_min": profile.expected_salary_min,
            "expected_salary_max": profile.expected_salary_max,
        }
        # 合并 parsed 中的额外信息
        if parsed:
            result.update({k: v for k, v in parsed.items() if v and k not in result})
        return result


# 全局单例
profile_service = ProfileService()
