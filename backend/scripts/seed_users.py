"""
用户画像种子数据灌入脚本
读取 data/seed_users.json，写入 MySQL 和 Chroma 用户知识库
"""
import json
import os
import sys
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import Session
from app.models.base import SessionLocal, engine, Base
from app.models.user import (
    User, UserProfile, UserProject, UserSkill, Education, UserPreference
)
from app.rag.user_kb import user_kb
from app.agents.profile_agent import profile_agent


def load_users() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "seed_users.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def hash_password(username: str) -> str:
    """简单占位密码 hash（实际系统应使用 bcrypt）"""
    import hashlib
    return hashlib.sha256(f"{username}_seed_password".encode()).hexdigest()


def seed_users(db: Session):
    users = load_users()
    print(f"准备灌入 {len(users)} 个用户画像...")

    for u in users:
        # 1. 创建 User
        user = db.query(User).filter(User.username == u["username"]).first()
        if not user:
            user = User(
                username=u["username"],
                email=u.get("email"),
                password_hash=hash_password(u["username"]),
                is_active=1,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(user)
            db.flush()

        # 2. 创建/更新 UserProfile
        profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        if not profile:
            profile = UserProfile(user_id=user.id)
            db.add(profile)

        profile.full_name = u.get("full_name")
        profile.gender = u.get("gender")
        profile.birth_year = u.get("birth_year")
        profile.degree = u.get("degree")
        profile.major = u.get("major")
        profile.school = u.get("school")
        profile.graduation_year = u.get("graduation_year")
        profile.current_city = u.get("current_city")
        profile.expected_salary_min = u.get("expected_salary_min")
        profile.expected_salary_max = u.get("expected_salary_max")
        profile.years_of_experience = u.get("years_of_experience", 0)
        profile.resume_raw_text = u.get("resume_raw_text")
        profile.updated_at = datetime.utcnow()
        db.flush()

        # 3. 清空并重建关联表（避免重复灌入）
        db.query(UserProject).filter(UserProject.user_id == user.id).delete()
        db.query(UserSkill).filter(UserSkill.user_id == user.id).delete()
        db.query(Education).filter(Education.user_id == user.id).delete()
        db.query(UserPreference).filter(UserPreference.user_id == user.id).delete()

        for p in u.get("projects", []):
            db.add(UserProject(
                user_id=user.id,
                project_name=p.get("project_name"),
                role=p.get("role"),
                description=p.get("description"),
                tech_stack=p.get("tech_stack", []),
                start_date=p.get("start_date"),
                end_date=p.get("end_date"),
                highlights=p.get("highlights"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ))

        for s in u.get("skills", []):
            db.add(UserSkill(
                user_id=user.id,
                skill_name=s.get("skill_name"),
                proficiency=s.get("proficiency"),
                category=s.get("category"),
                created_at=datetime.utcnow(),
            ))

        for e in u.get("education", []):
            db.add(Education(
                user_id=user.id,
                school=e.get("school"),
                major=e.get("major"),
                degree=e.get("degree"),
                start_year=e.get("start_year"),
                end_year=e.get("end_year"),
                gpa=e.get("gpa"),
                honors=e.get("honors"),
                created_at=datetime.utcnow(),
            ))

        pref = u.get("preferences", {})
        db.add(UserPreference(
            user_id=user.id,
            preferred_job_types=pref.get("preferred_job_types", []),
            preferred_sub_categories=pref.get("preferred_sub_categories", []),
            preferred_locations=pref.get("preferred_locations", []),
            preferred_industries=pref.get("preferred_industries", []),
            overtime_tolerance=pref.get("overtime_tolerance"),
            weekend_preference=pref.get("weekend_preference"),
            holiday_preference=pref.get("holiday_preference"),
            labor_intensity=pref.get("labor_intensity"),
            remote_work=pref.get("remote_work"),
            company_scale_pref=pref.get("company_scale_pref"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ))

        db.flush()
        print(f"  ✅ 用户 {u['username']} ({u.get('full_name')}) id={user.id}")

    db.commit()
    print(f"\nMySQL 用户画像灌入完成：共 {len(users)} 人")
    return users


async def seed_user_kb(users: list[dict]):
    """把用户画像写入 Chroma 用户知识库"""
    print("\n开始写入 Chroma 用户知识库...")
    for u in users:
        documents = []
        metadatas = []

        # 简历摘要
        documents.append(u.get("resume_raw_text", ""))
        metadatas.append({"type": "resume_summary", "user_id": u["user_id"]})

        # 每个项目
        for p in u.get("projects", []):
            text = (
                f"项目：{p.get('project_name')}\n"
                f"角色：{p.get('role')}\n"
                f"技术栈：{', '.join(p.get('tech_stack', []))}\n"
                f"描述：{p.get('description', '')}\n"
                f"亮点：{p.get('highlights', '')}"
            )
            documents.append(text)
            metadatas.append({"type": "project", "project_name": p.get("project_name"), "user_id": u["user_id"]})

        # 技能
        for s in u.get("skills", []):
            documents.append(f"技能：{s.get('skill_name')}，熟练度：{s.get('proficiency')}，分类：{s.get('category')}")
            metadatas.append({"type": "skill", "user_id": u["user_id"]})

        # 求职偏好
        pref = u.get("preferences", {})
        pref_text = (
            f"求职偏好：期望岗位 {', '.join(pref.get('preferred_job_types', []))}，"
            f"细分方向 {', '.join(pref.get('preferred_sub_categories', []))}，"
            f"期望城市 {', '.join(pref.get('preferred_locations', []))}，"
            f"期望行业 {', '.join(pref.get('preferred_industries', []))}，"
            f"加班接受度 {pref.get('overtime_tolerance')}，"
            f"周末偏好 {pref.get('weekend_preference')}，"
            f"劳动强度 {pref.get('labor_intensity')}，"
            f"远程工作 {pref.get('remote_work')}，"
            f"公司规模 {pref.get('company_scale_pref')}。"
        )
        documents.append(pref_text)
        metadatas.append({"type": "preference", "user_id": u["user_id"]})

        try:
            await user_kb.add_documents(u["user_id"], documents, metadatas)
        except Exception as e:
            print(f"  ⚠️ 写入用户知识库失败 {u['username']}: {e}")

    print("Chroma 用户知识库写入完成")


async def main():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        users = seed_users(db)
        await seed_user_kb(users)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
