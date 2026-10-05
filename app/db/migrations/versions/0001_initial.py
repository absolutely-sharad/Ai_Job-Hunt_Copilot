"""Baseline schema: documents, runs, chunks.

Matches what ``Base.metadata.create_all`` produced before migrations were introduced, so
existing databases are stamped here and upgraded from this point.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("tags", sa.String(500), nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("job_title", sa.String(200), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("ats_score", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("jd_text", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("chunk_metadata", sa.JSON, nullable=False),
        sa.Column("embedding", sa.JSON, nullable=False),
        sa.Column("norm", sa.Float, nullable=False),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("runs")
    op.drop_table("documents")
