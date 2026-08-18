"""
企业模型
"""

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    BigInteger,
    String,
    Integer,
    Text,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    Index,
)
from .base import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
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


class CompanyEvidence(Base):
    """A source-bound company fact. No field is treated as verified without this row."""

    __tablename__ = "company_evidence"
    __table_args__ = (
        Index("idx_company_evidence_company_type", "company_id", "evidence_type"),
        Index("idx_company_evidence_observed", "observed_at"),
    )

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    company_id = Column(
        BigInteger,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_name = Column(String(200), nullable=False, comment="查询时使用的企业名称")
    evidence_type = Column(
        String(50), nullable=False, comment="registry/penalty/job/social_insurance 等"
    )
    source_kind = Column(
        String(30), nullable=False, comment="official/job_board/media/user_provided"
    )
    source_name = Column(String(200), nullable=False)
    source_url = Column(String(1000), nullable=False)
    title = Column(String(300), nullable=False)
    content_excerpt = Column(Text, comment="支持结论的最小必要原文摘录")
    structured_data = Column(JSON, comment="从来源中直接提取的结构化字段")
    source_hash = Column(String(64), nullable=False, unique=True, comment="幂等来源指纹")
    is_verified = Column(Boolean, nullable=False, default=False)
    verification_level = Column(
        String(30), nullable=False, default="reported", comment="official/reported"
    )
    published_at = Column(DateTime)
    observed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
