"""
简历生成模型
"""

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    BigInteger,
    String,
    Integer,
    Text,
    JSON,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from .base import Base


BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class UserResume(Base):
    """用户上传的原始简历；一名用户可以保存多份。"""

    __tablename__ = "user_resumes"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_user_resumes_user_sha256"),
    )

    id = Column(BIGINT_PK, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    media_type = Column(String(120), nullable=False)
    parser = Column(String(100))
    ocr_used = Column(Boolean, default=False, nullable=False)
    extracted_text = Column(Text)
    extracted_chars = Column(Integer, default=0, nullable=False)
    structured_data = Column(JSON)
    parse_status = Column(String(30), default="pending", nullable=False)
    parse_error = Column(Text)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class GeneratedResume(Base):
    __tablename__ = "generated_resumes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(BigInteger, ForeignKey("jobs.id", ondelete="SET NULL"), comment="关联岗位ID")
    job_title = Column(String(200), comment="目标岗位名称")
    company_name = Column(String(200), comment="目标公司名称")
    resume_markdown = Column(Text, comment="简历 Markdown")
    greeting_text = Column(Text, comment="招呼语")
    selected_projects = Column(JSON, comment="选中的项目ID及排序")
    self_evaluation = Column(Text, comment="自我评价段落")
    pdf_path = Column(String(500), comment="PDF文件路径")
    docx_path = Column(String(500), comment="DOCX文件路径")
    template_id = Column(String(50), default="template-01", comment="所用模板ID")
    version = Column(Integer, default=1, comment="版本号")
    created_at = Column(DateTime, default=datetime.utcnow)
