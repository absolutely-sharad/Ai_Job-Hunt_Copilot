"""Schema management: migrations, model parity, FK behaviour, and timestamp handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.db.models import ApplicationRecord, Base, DocumentRecord, RunRecord
from app.db.session import init_db, session_scope

# The schema `Base.metadata.create_all` produced before migrations existed. Kept as raw DDL
# on purpose: it must not depend on the current models or on the migrations under test.
LEGACY_DDL = [
    """CREATE TABLE documents (
        id VARCHAR(64) NOT NULL PRIMARY KEY, title VARCHAR(200) NOT NULL,
        kind VARCHAR(32) NOT NULL, tags VARCHAR(500) NOT NULL, chunk_count INTEGER NOT NULL,
        char_count INTEGER NOT NULL, created_at DATETIME NOT NULL)""",
    """CREATE TABLE runs (
        id VARCHAR(64) NOT NULL PRIMARY KEY, job_title VARCHAR(200) NOT NULL,
        company VARCHAR(200) NOT NULL, ats_score INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
        jd_text TEXT NOT NULL, payload JSON NOT NULL, created_at DATETIME NOT NULL)""",
    """CREATE TABLE chunks (
        id VARCHAR(128) NOT NULL PRIMARY KEY, document_id VARCHAR(64) NOT NULL,
        text TEXT NOT NULL, chunk_metadata JSON NOT NULL, embedding JSON NOT NULL,
        norm FLOAT NOT NULL)""",
    "CREATE INDEX ix_chunks_document_id ON chunks (document_id)",
]


@pytest.fixture(scope="module", autouse=True)
def _app_schema():
    """Tests that use the application engine must not depend on another test booting the app."""
    init_db()


@pytest.fixture
def scratch_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/scratch.db")
    yield engine
    engine.dispose()


def _revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _drift(engine) -> list:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def test_fresh_database_migrates_to_head(scratch_engine):
    init_db(scratch_engine)
    assert {"documents", "runs", "chunks", "applications"} <= set(
        inspect(scratch_engine).get_table_names()
    )
    assert _revision(scratch_engine) == "0002"


def test_init_db_is_idempotent(scratch_engine):
    init_db(scratch_engine)
    init_db(scratch_engine)
    assert _revision(scratch_engine) == "0002"


def test_models_and_migrations_do_not_drift(scratch_engine):
    """Fails when someone edits a model without adding a migration."""
    init_db(scratch_engine)
    assert _drift(scratch_engine) == []


def test_legacy_database_is_upgraded_in_place(scratch_engine):
    """A DB made by the old create_all (no alembic_version) keeps its data and gains new tables."""
    with scratch_engine.begin() as connection:
        for statement in LEGACY_DDL:
            connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO documents VALUES "
                "('doc-old', 'Old project', 'project', '', 2, 120, '2026-01-01 09:00:00')"
            )
        )

    init_db(scratch_engine)

    assert _revision(scratch_engine) == "0002"
    assert "applications" in inspect(scratch_engine).get_table_names()
    with scratch_engine.connect() as connection:
        title = connection.execute(text("SELECT title FROM documents")).scalar_one()
    assert title == "Old project"
    assert _drift(scratch_engine) == []


def test_utc_datetime_round_trips_as_aware():
    """SQLite drops tzinfo; the column type must put it back so the API never emits naive times."""
    local = timezone(timedelta(hours=5, minutes=30))
    with session_scope() as session:
        session.add(
            DocumentRecord(
                id="doc-tz",
                title="tz",
                kind="note",
                created_at=datetime(2026, 3, 1, 12, 0, tzinfo=local),
            )
        )
        session.add(
            DocumentRecord(
                id="doc-naive", title="naive", kind="note", created_at=datetime(2026, 3, 1, 12, 0)
            )
        )
    with session_scope() as session:
        aware = session.get(DocumentRecord, "doc-tz")
        naive = session.get(DocumentRecord, "doc-naive")
        assert aware.created_at.tzinfo is not None
        assert aware.created_at == datetime(
            2026, 3, 1, 6, 30, tzinfo=UTC
        )  # converted, not relabelled
        assert naive.created_at == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)  # naive is taken as UTC
        session.delete(aware)
        session.delete(naive)


def test_foreign_keys_are_enforced_and_set_null_on_run_delete():
    with session_scope() as session:
        session.add(RunRecord(id="run-fk", job_title="Eng", company="Acme", ats_score=50))
        session.flush()
        session.add(ApplicationRecord(id="job-fk", run_id="run-fk", job_title="Eng"))

    with session_scope() as session:
        session.delete(session.get(RunRecord, "run-fk"))

    with session_scope() as session:
        application = session.get(ApplicationRecord, "job-fk")
        assert application is not None and application.run_id is None
        session.delete(application)


def test_application_cannot_reference_a_missing_run():
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), session_scope() as session:
        session.add(ApplicationRecord(id="job-bad", run_id="run-does-not-exist", job_title="Eng"))
