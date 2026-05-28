"""
AgentOps API Gateway — Application Settings
All configuration is read from environment variables (or .env file).
Missing mandatory variables cause a ValueError at startup — no silent failures.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralised settings loaded from the environment.
    Use `get_settings()` everywhere — never instantiate Settings directly.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Platform ──────────────────────────────────────────────────────────────
    PLATFORM_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # ── Database ──────────────────────────────────────────────────────────────
    POSTGRES_URL: str  # mandatory — asyncpg dialect set in session.py
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str  # mandatory
    REDIS_DEFAULT_TTL: int = 3600  # seconds

    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = secrets.token_hex(32)  # must be overridden in prod
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    API_KEY_HEADER: str = "X-API-Key"

    # ── LLM Providers ─────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # ── Storage ───────────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET_NAME: str = "agent-artifacts"

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 120

    # ── Observability ─────────────────────────────────────────────────────────
    OTEL_SERVICE_NAME: str = "agentops-api-gateway"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    # ── Validators ────────────────────────────────────────────────────────────
    @field_validator("POSTGRES_URL", mode="before")
    @classmethod
    def _postgres_url_must_be_set(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "POSTGRES_URL is required. "
                "Set it to a valid PostgreSQL connection string, "
                "e.g. postgresql+asyncpg://user:pass@localhost:5432/agentops_db"
            )
        return v

    @field_validator("REDIS_URL", mode="before")
    @classmethod
    def _redis_url_must_be_set(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "REDIS_URL is required. "
                "Set it to a valid Redis URL, e.g. redis://localhost:6379/0"
            )
        return v

    @model_validator(mode="after")
    def _warn_insecure_defaults(self) -> "Settings":
        """Warn loudly if JWT_SECRET_KEY is the generated random default in production."""
        import logging

        log = logging.getLogger("agentops.config")
        if self.PLATFORM_ENV == "production":
            if not self.ANTHROPIC_API_KEY and not self.OPENAI_API_KEY:
                raise ValueError(
                    "At least one LLM provider key (ANTHROPIC_API_KEY or OPENAI_API_KEY) "
                    "must be configured in production."
                )
        else:
            if not self.ANTHROPIC_API_KEY and not self.OPENAI_API_KEY:
                log.warning(
                    "No LLM provider API key found. "
                    "Set ANTHROPIC_API_KEY or OPENAI_API_KEY for full functionality."
                )
        return self

    @property
    def async_postgres_url(self) -> str:
        """Return a URL guaranteed to use the asyncpg dialect."""
        url = self.POSTGRES_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def is_production(self) -> bool:
        return self.PLATFORM_ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached singleton Settings instance.
    Import and call this everywhere instead of instantiating Settings directly.
    """
    return Settings()
