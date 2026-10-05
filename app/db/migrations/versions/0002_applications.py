"""Add the job application tracker and index run history by recency.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_table(
        "applications",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("job_title", sa.String(200), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("ats_score", sa.Integer),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_updated_at", "applications", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_applications_updated_at", table_name="applications")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_runs_created_at", table_name="runs")
