"""Database engine and session-factory construction.

The engine is created from :class:`DatabaseSettings`. A process-wide cached
session factory is exposed for the API/worker; tests construct their own
(e.g. against an in-memory SQLite database) via :func:`create_session_factory`.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from distillery.config.settings import DatabaseSettings, get_settings


def create_db_engine(settings: DatabaseSettings) -> Engine:
    """Create a SQLAlchemy engine with pooling configured from settings.

    SQLite (used in tests) does not support the pool sizing options, so they are
    only applied to server databases.
    """
    url = settings.url
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False} if ":memory:" in url else {}
        return create_engine(url, echo=settings.echo, future=True, connect_args=connect_args)
    return create_engine(
        url,
        echo=settings.echo,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to ``engine``."""
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide cached session factory."""
    engine = create_db_engine(get_settings().database)
    return create_session_factory(engine)
