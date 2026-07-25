"""
简历生成模型
"""

from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, Text, JSON, DateTime, ForeignKey
from .base import Base


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
    version = Column(Integer, default=1, comment="版本号")
    created_at = Column(DateTime, default=datetime.utcnow)
