"""Add source-bound company evidence.

Revision ID: 20260803_02
Revises: 20260802_01
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_02"
down_revision = "20260802_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "company_evidence" in inspector.get_table_names():
        return
    op.create_table(
        "company_evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "verification_level",
            sa.String(length=30),
            nullable=False,
            server_default="reported",
        ),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_hash", name="uq_company_evidence_source_hash"),
    )
    op.create_index(
        "idx_company_evidence_company_type",
        "company_evidence",
        ["company_id", "evidence_type"],
        unique=False,
    )
    op.create_index(
        "idx_company_evidence_observed",
        "company_evidence",
        ["observed_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "company_evidence" in sa.inspect(bind).get_table_names():
        op.drop_table("company_evidence")
