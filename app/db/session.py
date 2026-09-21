"""SQLAlchemy engine and session management."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

_settings = get_settings()

if _settings.database_url.startswith("sqlite:///./"):
    os.makedirs(os.path.dirname(_settings.database_url.replace("sqlite:///", "")), exist_ok=True)

engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False}
    if _settings.database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
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
