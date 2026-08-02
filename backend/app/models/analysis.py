"""
岗位分析模型
"""

from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, Text, JSON, DateTime, Float, ForeignKey
from .base import Base


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, ForeignKey("jobs.id", ondelete="SET NULL"), comment="岗位ID")
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_name = Column(String(200), nullable=False, comment="公司名称")
    job_title = Column(String(200), comment="岗位名称")
    risk_level = Column(String(20), comment="风险等级")
    recommendation_index = Column(Integer, comment="推荐指数 1-5")
    match_score = Column(Float, comment="匹配度百分比")
    analysis_json = Column(JSON, comment="完整分析结果")
    source_type = Column(String(50), comment="分析触发方式")
    created_at = Column(DateTime, default=datetime.utcnow)
