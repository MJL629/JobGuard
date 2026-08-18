"""Add source identity and lifecycle timestamps to jobs.

Revision ID: 20260802_01
Revises:
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All columns are nullable so existing rows remain valid and unchanged.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("jobs")}
    additions = {
        "source_external_id": sa.Column("source_external_id", sa.String(length=255), nullable=True),
        "source_published_at": sa.Column("source_published_at", sa.DateTime(), nullable=True),
        "expires_at": sa.Column("expires_at", sa.DateTime(), nullable=True),
        "last_seen_at": sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("jobs", column)

    inspector = sa.inspect(bind)
    unique_names = {
        constraint.get("name") for constraint in inspector.get_unique_constraints("jobs")
    }
    index_names = {index.get("name") for index in inspector.get_indexes("jobs")}
    if "uq_jobs_source_external_id" not in unique_names:
        op.create_unique_constraint(
            "uq_jobs_source_external_id",
            "jobs",
            ["source_type", "source_external_id"],
        )
    if "idx_jobs_expires_at" not in index_names:
        op.create_index("idx_jobs_expires_at", "jobs", ["expires_at"], unique=False)
    if "idx_jobs_last_seen_at" not in index_names:
        op.create_index("idx_jobs_last_seen_at", "jobs", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_jobs_last_seen_at", table_name="jobs")
    op.drop_index("idx_jobs_expires_at", table_name="jobs")
    op.drop_constraint("uq_jobs_source_external_id", "jobs", type_="unique")
    op.drop_column("jobs", "last_seen_at")
    op.drop_column("jobs", "expires_at")
    op.drop_column("jobs", "source_published_at")
    op.drop_column("jobs", "source_external_id")
