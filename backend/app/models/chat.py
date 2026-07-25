"""
对话模型
"""

from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Integer, Text, JSON, DateTime, ForeignKey
from .base import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_type = Column(String(50), nullable=False, comment="会话类型")
    status = Column(String(20), default="active", comment="状态")
    context_json = Column(JSON, comment="会话上下文")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, comment="角色")
    content = Column(Text, nullable=False, comment="消息内容")
    message_type = Column(String(50), default="text", comment="消息类型")
    metadata_json = Column(JSON, comment="附加元数据")
    created_at = Column(DateTime, default=datetime.utcnow)
