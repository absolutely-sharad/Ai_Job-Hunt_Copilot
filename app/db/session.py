"""SQLAlchemy engine and session management."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import ON_VERCEL, get_settings
from app.db.models import Base

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
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


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
