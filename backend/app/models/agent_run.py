"""Persistent Agent observability and evaluation records."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from .base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    session_id = Column(BigInteger, ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True)
    workflow = Column(String(50), nullable=False, index=True)
    intent = Column(String(50))
    status = Column(String(30), nullable=False, default="running", index=True)
    current_step = Column(String(100))
    model_provider = Column(String(50))
    model_name = Column(String(100))
    input_summary = Column(Text)
    context_snapshot = Column(JSON)
    output_summary = Column(Text)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    estimated_cost_usd = Column(Float)
    cost_status = Column(String(50), default="provider_usage_unavailable")
    tool_calls_count = Column(Integer, nullable=False, default=0)
    tool_success_count = Column(Integer, nullable=False, default=0)
    failure_step = Column(String(100))
    error_type = Column(String(100))
    duration_ms = Column(Integer)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime)


class ToolCallTrace(Base):
    __tablename__ = "tool_call_traces"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False, index=True)
    status = Column(String(30), nullable=False)
    arguments_redacted = Column(JSON)
    result_summary = Column(JSON)
    source_count = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer)
    error_type = Column(String(100))
    requires_confirmation = Column(Boolean, nullable=False, default=False)
    confirmed_by_user = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentEvaluation(Base):
    __tablename__ = "agent_evaluations"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    evaluator = Column(String(100), nullable=False)
    metric_name = Column(String(100), nullable=False)
    score = Column(Float)
    passed = Column(Boolean)
    details = Column(JSON)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
