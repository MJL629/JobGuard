"""
用户相关模型
"""

from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, String, Integer, Text, JSON, DateTime, ForeignKey, Float
)
from sqlalchemy.orm import relationship
from .base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, comment="用户名")
    email = Column(String(100), comment="邮箱")
    phone = Column(String(20), comment="手机号")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    avatar_url = Column(String(500), comment="头像URL")
    is_active = Column(Integer, default=1, comment="是否激活")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    profile = relationship("UserProfile", back_populates="user", uselist=False)
    projects = relationship("UserProject", back_populates="user")
    skills = relationship("UserSkill", back_populates="user")
    education = relationship("Education", back_populates="user")
    preferences = relationship("UserPreference", back_populates="user", uselist=False)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    full_name = Column(String(50), comment="真实姓名")
    gender = Column(String(10), comment="性别")
    birth_year = Column(Integer, comment="出生年份")
    degree = Column(String(20), comment="最高学历")
    major = Column(String(100), comment="专业")
    school = Column(String(100), comment="毕业院校")
    graduation_year = Column(Integer, comment="毕业年份")
    current_city = Column(String(50), comment="当前城市")
    expected_salary_min = Column(Integer, comment="期望最低月薪")
    expected_salary_max = Column(Integer, comment="期望最高月薪")
    years_of_experience = Column(Integer, default=0, comment="工作年限")
    resume_raw_text = Column(Text, comment="原始简历文本")
    resume_file_path = Column(String(500), comment="简历文件路径")
    profile_completeness = Column(Integer, default=0, comment="画像完整度 0-100")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="profile")


class UserProject(Base):
    __tablename__ = "user_projects"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_name = Column(String(200), nullable=False, comment="项目名称")
    role = Column(String(100), comment="担任角色")
    description = Column(Text, comment="项目描述")
    tech_stack = Column(JSON, comment="技术栈")
    start_date = Column(String(20), comment="开始时间")
    end_date = Column(String(20), comment="结束时间")
    highlights = Column(Text, comment="项目亮点/量化成果")
    project_url = Column(String(500), comment="项目链接")
    sort_order = Column(Integer, default=0, comment="排序权重")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="projects")


class UserSkill(Base):
    __tablename__ = "user_skills"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill_name = Column(String(100), nullable=False, comment="技能名称")
    proficiency = Column(String(20), comment="熟练程度")
    category = Column(String(50), comment="技能分类")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="skills")


class Education(Base):
    __tablename__ = "education"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    school = Column(String(100), nullable=False, comment="学校")
    major = Column(String(100), nullable=False, comment="专业")
    degree = Column(String(20), nullable=False, comment="学历")
    start_year = Column(Integer, comment="入学年份")
    end_year = Column(Integer, comment="毕业年份")
    gpa = Column(String(10), comment="GPA")
    honors = Column(Text, comment="荣誉奖项")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="education")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    preferred_job_types = Column(JSON, comment="偏好岗位类型")
    preferred_sub_categories = Column(JSON, comment="偏好细分方向")
    preferred_locations = Column(JSON, comment="偏好工作城市")
    preferred_industries = Column(JSON, comment="偏好行业")
    overtime_tolerance = Column(String(20), comment="加班接受度")
    weekend_preference = Column(String(20), comment="周末偏好")
    holiday_preference = Column(String(20), comment="法定假日偏好")
    labor_intensity = Column(String(20), comment="劳动强度偏好")
    remote_work = Column(String(20), comment="远程工作偏好")
    company_scale_pref = Column(String(20), comment="公司规模偏好")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="preferences")
