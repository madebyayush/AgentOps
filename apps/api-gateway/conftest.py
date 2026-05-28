"""
Root-level conftest: sets required environment variables BEFORE any app
module is imported. Also patches postgresql-specific SQLAlchemy types to
generic equivalents so production ORM models work with SQLite in tests.
"""

import os
import uuid as _uuid_module

# ── 1. Set mandatory env vars ─────────────────────────────────────────────────
os.environ.setdefault("POSTGRES_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-agentops-testing-only-32chars")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("PLATFORM_ENV", "development")

# ── 2. Patch postgresql dialect types to SQLite-compatible equivalents ─────────
import sqlalchemy.dialects.postgresql as pg_dialect
from sqlalchemy import types as sa_types


class _TestUUID(sa_types.TypeDecorator):
    """
    Stores UUIDs as VARCHAR(36) strings in SQLite.
    Handles python uuid.UUID objects transparently.
    """

    impl = sa_types.String(36)
    cache_ok = True

    def __init__(self, as_uuid: bool = True, **kwargs):
        super().__init__()
        self.as_uuid = as_uuid

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid_module.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if self.as_uuid:
            try:
                return _uuid_module.UUID(str(value))
            except (ValueError, AttributeError):
                return value
        return value


class _TestJSONB(sa_types.JSON):
    """Drop-in for postgresql.JSONB using standard JSON in SQLite."""

    pass


# Apply patches before models are imported
pg_dialect.UUID = _TestUUID  # type: ignore[attr-defined]
pg_dialect.JSONB = _TestJSONB  # type: ignore[attr-defined]
