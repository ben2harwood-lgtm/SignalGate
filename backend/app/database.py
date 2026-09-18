"""Database engine, session factory and Base for SQLAlchemy models."""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialise local demo schema; hosted schema is Alembic-managed.

    In hosted mode we deliberately do not call create_all(). create_all() can
    create missing tables but cannot safely evolve an existing PostgreSQL
    schema, so a hosted release must run the versioned migration gate first.
    """
    from . import models  # noqa: F401

    if settings.require_license:
        return
    Base.metadata.create_all(bind=engine)
