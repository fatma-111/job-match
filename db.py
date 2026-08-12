"""SQLAlchemy engine / session management and DB initialisation."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    # Make sure the folder for the sqlite file exists.
    raw_path = settings.database_url.split("sqlite:///")[-1]
    if raw_path and raw_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(raw_path)) or ".", exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

_initialised = False


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    global _initialised
    from app import models_db  # noqa: F401  (registers models on Base)
    from app.models_db import Base

    Base.metadata.create_all(bind=engine)
    _initialised = True
    logger.info("Database initialised at %s", settings.database_url)


def ensure_db() -> None:
    if not _initialised:
        init_db()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    ensure_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for use outside of request handlers (scheduler, CLI, tests)."""
    ensure_db()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
