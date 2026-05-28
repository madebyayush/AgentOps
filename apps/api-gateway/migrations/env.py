"""
Alembic environment configuration — async-aware.

Key design points:
  - Reads DATABASE_URL from app.config (pydantic-settings)
  - Converts URL to the asyncpg dialect automatically
  - Uses asyncio.run() to drive async migrations
  - Imports Base.metadata so autogenerate can diff all 8 models
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# ── Make the app package importable when running alembic from apps/api-gateway/ ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings
from app.db.base import Base
import app.db.models  # noqa: F401 — registers all ORM models with Base.metadata

# ── Alembic Config object ─────────────────────────────────────────────────────
config = context.config

# Set up Python logging from alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for --autogenerate
target_metadata = Base.metadata


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_url() -> str:
    """Return the async-compatible PostgreSQL URL from settings."""
    return get_settings().async_postgres_url


# ── Offline migrations (generate SQL script without a live DB) ────────────────


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — emits SQL to stdout.
    Useful for review and manual DBA application.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (runs against a live DB) ────────────────────────────────


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and drive migrations through it."""
    connectable = create_async_engine(get_url(), future=True)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point called by alembic upgrade/downgrade commands."""
    asyncio.run(run_async_migrations())


# ── Dispatch ──────────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
