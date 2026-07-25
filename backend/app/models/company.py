"""
企业模型
"""

from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, Text, DateTime, Float
from .base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="企业名称")
    industry = Column(String(100), comment="所属行业")
    scale = Column(String(50), comment="企业规模")
    address = Column(String(300), comment="企业地址")
    description = Column(Text, comment="企业简介")
    risk_score = Column(Float, default=0, comment="综合风险评分 0-10")
    risk_level = Column(String(20), comment="风险等级")
    social_insurance_count = Column(Integer, comment="社保参保人数")
    labor_dispute_count = Column(Integer, default=0, comment="劳动争议数量")
    reputation_score = Column(Float, comment="网络口碑评分")
    last_checked = Column(DateTime, comment="最后检查时间")
    data_source = Column(String(50), comment="数据来源")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
