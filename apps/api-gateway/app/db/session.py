"""
AgentOps — Async SQLAlchemy Session Factory
Lazily creates the engine on first call to get_engine() or get_db().
This deferred pattern ensures Settings() is NOT called at import time,
allowing tests to set env vars before any app module is loaded.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

log = logging.getLogger("agentops.db.session")

# Lazily-initialised singletons
_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return (or create on first call) the shared AsyncEngine."""
    global _engine
    if _engine is None:
        from app.config import get_settings
        settings = get_settings()
        _engine = create_async_engine(
            settings.async_postgres_url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,
            echo=not settings.is_production,
        )
        log.debug("AsyncEngine created: %s", settings.async_postgres_url[:40])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (or create on first call) the session factory."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _AsyncSessionLocal


# Compatibility alias — used in db/__init__.py
def _get_async_session_local() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()

AsyncSessionLocal = _get_async_session_local  # callable that returns the factory


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """
    Yield a database session per request.
    The session is automatically closed (and rolled back on error)
    when the request context exits.

    Usage in a router:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
