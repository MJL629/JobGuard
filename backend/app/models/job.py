"""
岗位模型
"""

from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, Text, JSON, DateTime, ForeignKey
from .base import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_name = Column(String(200), nullable=False, comment="公司名称")
    company_id = Column(BigInteger, ForeignKey("companies.id", ondelete="SET NULL"), comment="关联企业ID")
    job_title = Column(String(200), nullable=False, comment="岗位名称")
    job_category = Column(String(50), nullable=False, comment="岗位大类")
    sub_category = Column(String(100), comment="岗位细分")
    salary_min = Column(Integer, comment="最低月薪")
    salary_max = Column(Integer, comment="最高月薪")
    location = Column(String(100), comment="工作地点")
    jd_text = Column(Text, comment="岗位描述原文")
    requirements = Column(JSON, comment="技术要求")
    benefits = Column(JSON, comment="福利待遇")
    source_url = Column(String(1000), comment="来源链接")
    source_type = Column(String(50), comment="来源平台")
    posted_at = Column(DateTime, comment="发布日期")
    is_active = Column(Integer, default=1, comment="是否有效")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
