"""Persistence models for document metadata, pipeline runs, and job applications."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend.

    SQLite drops tzinfo on read, which made the API emit naive timestamps that browsers
    parse as local time. Normalising on the way in and out keeps SQLite and Postgres
    behaving identically.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    tags: Mapped[str] = mapped_column(String(500), default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class RunRecord(Base):
    """A full tailoring run, stored so results are shareable and auditable."""

    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_title: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    ats_score: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    jd_text: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class ChunkRecord(Base):
    """A retrievable chunk with its embedding (used by the SQL vector store)."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    norm: Mapped[float] = mapped_column(Float, default=1.0)


APPLICATION_STATUSES = ("saved", "applied", "interviewing", "offer", "rejected", "withdrawn")


class ApplicationRecord(Base):
    """A job the candidate is pursuing, optionally linked to the run that tailored for it.

    ``run_id`` is nulled (not cascaded) when the run is deleted, and ``ats_score`` is
    snapshotted at creation, so pruning run history never destroys tracker entries.
    """

    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_status", "status"),
        Index("ix_applications_updated_at", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="SET NULL"), default=None
    )
    job_title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(24), default="saved")
    notes: Mapped[str] = mapped_column(Text, default="")
    ats_score: Mapped[int | None] = mapped_column(Integer, default=None)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)
