"""SQLAlchemy engine, session management, and schema migrations."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import ON_VERCEL, get_settings

_settings = get_settings()

if _settings.database_url.startswith("sqlite:///./"):
    os.makedirs(os.path.dirname(_settings.database_url.replace("sqlite:///", "")), exist_ok=True)

_url = _settings.sqlalchemy_url
_is_sqlite = _url.startswith("sqlite")

engine = create_engine(
    _url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    # Serverless instances are short-lived; let the provider's pooler own connections.
    **({"poolclass": NullPool} if ON_VERCEL and not _is_sqlite else {}),
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
        # SQLite ignores FOREIGN KEY / ON DELETE clauses unless this is switched on per connection.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# Revision that matches the schema `create_all` produced before migrations existed.
BASELINE_REVISION = "0001"
# Serialises concurrent cold starts on Postgres so two instances never race to create tables.
_MIGRATION_LOCK_KEY = 727_274_001


def _alembic_config(connection: Connection):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


def init_db(bind: Engine | None = None) -> None:
    """Bring the database schema to the latest revision. Safe to call repeatedly.

    ``bind`` defaults to the application engine; tests pass a throwaway one.

    A database created before migrations existed (tables present, no ``alembic_version``)
    is stamped at the baseline first, so existing deployments upgrade in place instead of
    failing on "table already exists".
    """
    from alembic import command

    with (bind or engine).connect() as connection:
        use_lock = connection.dialect.name == "postgresql"
        if use_lock:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
            connection.commit()
        try:
            config = _alembic_config(connection)
            tables = set(inspect(connection).get_table_names())
            if "documents" in tables and "alembic_version" not in tables:
                command.stamp(config, BASELINE_REVISION)
            command.upgrade(config, "head")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if use_lock:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _MIGRATION_LOCK_KEY}
                )
                connection.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
