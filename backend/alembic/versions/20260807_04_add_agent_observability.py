"""Add persistent Agent runs, tool traces and evaluations.

Revision ID: 20260807_04
Revises: 20260803_03
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_04"
down_revision = "20260803_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "user_profiles" in tables:
        columns = {column["name"] for column in inspector.get_columns("user_profiles")}
        if "interview_memory" not in columns:
            op.add_column("user_profiles", sa.Column("interview_memory", sa.JSON(), nullable=True))

    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("session_id", sa.BigInteger(), nullable=True),
            sa.Column("workflow", sa.String(50), nullable=False),
            sa.Column("intent", sa.String(50)),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("current_step", sa.String(100)),
            sa.Column("model_provider", sa.String(50)),
            sa.Column("model_name", sa.String(100)),
            sa.Column("input_summary", sa.Text()),
            sa.Column("context_snapshot", sa.JSON()),
            sa.Column("output_summary", sa.Text()),
            sa.Column("prompt_tokens", sa.Integer()),
            sa.Column("completion_tokens", sa.Integer()),
            sa.Column("estimated_cost_usd", sa.Float()),
            sa.Column("cost_status", sa.String(50), server_default="provider_usage_unavailable"),
            sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tool_success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_step", sa.String(100)),
            sa.Column("error_type", sa.String(100)),
            sa.Column("duration_ms", sa.Integer()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
        op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
        op.create_index("ix_agent_runs_workflow", "agent_runs", ["workflow"])
        op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "tool_call_traces" not in tables:
        op.create_table(
            "tool_call_traces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), nullable=False),
            sa.Column("tool_name", sa.String(100), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("arguments_redacted", sa.JSON()),
            sa.Column("result_summary", sa.JSON()),
            sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_ms", sa.Integer()),
            sa.Column("error_type", sa.String(100)),
            sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("confirmed_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_tool_call_traces_run_id", "tool_call_traces", ["run_id"])
        op.create_index("ix_tool_call_traces_tool_name", "tool_call_traces", ["tool_name"])

    inspector = sa.inspect(op.get_bind())
    if "agent_evaluations" not in inspector.get_table_names():
        op.create_table(
            "agent_evaluations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("run_id", sa.String(36), nullable=False),
            sa.Column("evaluator", sa.String(100), nullable=False),
            sa.Column("metric_name", sa.String(100), nullable=False),
            sa.Column("score", sa.Float()),
            sa.Column("passed", sa.Boolean()),
            sa.Column("details", sa.JSON()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_agent_evaluations_run_id", "agent_evaluations", ["run_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "agent_evaluations" in tables:
        op.drop_table("agent_evaluations")
    if "tool_call_traces" in tables:
        op.drop_table("tool_call_traces")
    if "agent_runs" in tables:
        op.drop_table("agent_runs")
    inspector = sa.inspect(op.get_bind())
    if "user_profiles" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("user_profiles")}
        if "interview_memory" in columns:
            op.drop_column("user_profiles", "interview_memory")
