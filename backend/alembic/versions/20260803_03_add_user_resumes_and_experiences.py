"""Add multiple resumes, generalized experiences and generated templates.

Revision ID: 20260803_03
Revises: 20260803_02
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_03"
down_revision = "20260803_02"
branch_labels = None
depends_on = None


def _column_names(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_resumes" not in tables:
        op.create_table(
            "user_resumes",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("stored_path", sa.String(length=500), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("media_type", sa.String(length=120), nullable=False),
            sa.Column("parser", sa.String(length=100), nullable=True),
            sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("extracted_text", sa.Text(), nullable=True),
            sa.Column("extracted_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("structured_data", sa.JSON(), nullable=True),
            sa.Column("parse_status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("parse_error", sa.Text(), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "sha256", name="uq_user_resumes_user_sha256"),
        )
        op.create_index("ix_user_resumes_user_id", "user_resumes", ["user_id"], unique=False)

    inspector = sa.inspect(bind)
    if "user_experiences" not in inspector.get_table_names():
        op.create_table(
            "user_experiences",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("source_resume_id", sa.BigInteger(), nullable=True),
            sa.Column("experience_type", sa.String(length=30), nullable=False, server_default="project"),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("organization", sa.String(length=200), nullable=True),
            sa.Column("role", sa.String(length=100), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("actions", sa.Text(), nullable=True),
            sa.Column("achievements", sa.Text(), nullable=True),
            sa.Column("tech_stack", sa.JSON(), nullable=True),
            sa.Column("start_date", sa.String(length=20), nullable=True),
            sa.Column("end_date", sa.String(length=20), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column("verification_status", sa.String(length=30), nullable=True, server_default="user_confirmed"),
            sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["source_resume_id"], ["user_resumes.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_user_experiences_user_id", "user_experiences", ["user_id"], unique=False)

    inspector = sa.inspect(bind)
    generated_columns = _column_names(inspector, "generated_resumes")
    if "docx_path" not in generated_columns:
        op.add_column("generated_resumes", sa.Column("docx_path", sa.String(length=500), nullable=True))
    if "template_id" not in generated_columns:
        op.add_column(
            "generated_resumes",
            sa.Column("template_id", sa.String(length=50), nullable=True, server_default="template-01"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "generated_resumes" in tables:
        columns = _column_names(inspector, "generated_resumes")
        if "template_id" in columns:
            op.drop_column("generated_resumes", "template_id")
        if "docx_path" in columns:
            op.drop_column("generated_resumes", "docx_path")
    if "user_experiences" in tables:
        op.drop_table("user_experiences")
    if "user_resumes" in tables:
        op.drop_table("user_resumes")
