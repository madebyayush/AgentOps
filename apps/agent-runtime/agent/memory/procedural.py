"""
AgentOps — Procedural Memory (Tool Registry, PostgreSQL)
=========================================================
Tracks performance statistics for every tool in the system.

PostgreSQL table: tool_registry
┌────────────────┬──────────────────────────────────────────┐
│ Column         │ Type / Notes                             │
├────────────────┼──────────────────────────────────────────┤
│ tool_name      │ TEXT PRIMARY KEY                         │
│ description    │ TEXT                                     │
│ schema_json    │ JSONB                                    │
│ enabled        │ BOOLEAN DEFAULT TRUE                     │
│ total_calls    │ BIGINT DEFAULT 0                         │
│ success_calls  │ BIGINT DEFAULT 0                         │
│ error_calls    │ BIGINT DEFAULT 0                         │
│ total_latency_ms│ DOUBLE PRECISION DEFAULT 0             │
│ created_at     │ TIMESTAMPTZ DEFAULT now()                │
│ updated_at     │ TIMESTAMPTZ DEFAULT now()                │
└────────────────┴──────────────────────────────────────────┘

Auto-disable policy: if error_rate > ERROR_RATE_THRESHOLD (30%),
the tool is marked enabled=FALSE and an alert is logged.

Falls back to an in-memory dict store when POSTGRES_URL is absent
(for local dev / unit tests that don't want a DB connection).
Real PostgreSQL client is activated by POSTGRES_URL env var.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("agentops.memory.procedural")

ERROR_RATE_THRESHOLD = 0.30  # 30%

# DDL — executed once on startup
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tool_registry (
    tool_name        TEXT PRIMARY KEY,
    description      TEXT        NOT NULL DEFAULT '',
    schema_json      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    total_calls      BIGINT      NOT NULL DEFAULT 0,
    success_calls    BIGINT      NOT NULL DEFAULT 0,
    error_calls      BIGINT      NOT NULL DEFAULT 0,
    total_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class ToolStats:
    tool_name: str
    enabled: bool
    total_calls: int
    success_calls: int
    error_calls: int
    total_latency_ms: float
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    error_rate: float = 0.0
    description: str = ""

    def __post_init__(self) -> None:
        if self.total_calls > 0:
            self.avg_latency_ms = self.total_latency_ms / self.total_calls
            self.success_rate = self.success_calls / self.total_calls
            self.error_rate = self.error_calls / self.total_calls


# ── In-memory fallback store ──────────────────────────────────────────────────


@dataclass
class _InMemoryRow:
    tool_name: str
    description: str = ""
    schema_json: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    total_calls: int = 0
    success_calls: int = 0
    error_calls: int = 0
    total_latency_ms: float = 0.0
    created_at: str = ""
    updated_at: str = ""

    def to_stats(self) -> ToolStats:
        return ToolStats(
            tool_name=self.tool_name,
            enabled=self.enabled,
            total_calls=self.total_calls,
            success_calls=self.success_calls,
            error_calls=self.error_calls,
            total_latency_ms=self.total_latency_ms,
            description=self.description,
        )


class _InMemoryProceduralStore:
    """Thread-safe in-memory fallback for tests / local dev without Postgres."""

    def __init__(self) -> None:
        self._tools: dict[str, _InMemoryRow] = {}

    async def initialize(self) -> None:
        pass  # no-op

    async def register_tool(
        self, tool_name: str, description: str, schema_json: dict[str, Any]
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if tool_name not in self._tools:
            self._tools[tool_name] = _InMemoryRow(
                tool_name=tool_name,
                description=description,
                schema_json=schema_json,
                created_at=now,
                updated_at=now,
            )
        else:
            row = self._tools[tool_name]
            row.description = description
            row.schema_json = schema_json
            row.updated_at = now

    async def record_call(self, tool_name: str, success: bool, latency_ms: float) -> None:
        if tool_name not in self._tools:
            log.warning("ProceduralMemory: unknown tool '%s' — skipping record_call", tool_name)
            return
        row = self._tools[tool_name]
        row.total_calls += 1
        row.total_latency_ms += latency_ms
        if success:
            row.success_calls += 1
        else:
            row.error_calls += 1
        row.updated_at = datetime.now(timezone.utc).isoformat()

    async def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        row = self._tools.get(tool_name)
        return row.to_stats() if row else None

    async def list_stats(self) -> list[ToolStats]:
        return [r.to_stats() for r in self._tools.values()]

    async def set_enabled(self, tool_name: str, enabled: bool) -> None:
        if tool_name in self._tools:
            self._tools[tool_name].enabled = enabled
            self._tools[tool_name].updated_at = datetime.now(timezone.utc).isoformat()

    async def close(self) -> None:
        pass


# ── PostgreSQL backend ────────────────────────────────────────────────────────


class _PostgresProceduralStore:
    """asyncpg-backed store. Activated when POSTGRES_URL is set."""

    def __init__(self, postgres_url: str) -> None:
        self._url = postgres_url
        self._pool: Any = None

    async def initialize(self) -> None:
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._url, min_size=1, max_size=5)
            async with self._pool.acquire() as conn:
                await conn.execute(_CREATE_TABLE_SQL)
            log.info("ProceduralMemory: PostgreSQL pool ready")
        except ImportError:
            raise ImportError("asyncpg required for PostgreSQL: pip install asyncpg")

    async def register_tool(
        self, tool_name: str, description: str, schema_json: dict[str, Any]
    ) -> None:
        sql = """
            INSERT INTO tool_registry (tool_name, description, schema_json, updated_at)
            VALUES ($1, $2, $3::jsonb, now())
            ON CONFLICT (tool_name) DO UPDATE
                SET description = EXCLUDED.description,
                    schema_json  = EXCLUDED.schema_json,
                    updated_at   = now()
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, tool_name, description, json.dumps(schema_json))

    async def record_call(self, tool_name: str, success: bool, latency_ms: float) -> None:
        sql = """
            UPDATE tool_registry SET
                total_calls       = total_calls + 1,
                success_calls     = success_calls + $2::bigint,
                error_calls       = error_calls + $3::bigint,
                total_latency_ms  = total_latency_ms + $4,
                updated_at        = now()
            WHERE tool_name = $1
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                tool_name,
                1 if success else 0,
                0 if success else 1,
                latency_ms,
            )

    async def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        sql = """
            SELECT tool_name, enabled, total_calls, success_calls,
                   error_calls, total_latency_ms, description
            FROM tool_registry WHERE tool_name = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, tool_name)
        if not row:
            return None
        return ToolStats(**dict(row))

    async def list_stats(self) -> list[ToolStats]:
        sql = """
            SELECT tool_name, enabled, total_calls, success_calls,
                   error_calls, total_latency_ms, description
            FROM tool_registry ORDER BY tool_name
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [ToolStats(**dict(r)) for r in rows]

    async def set_enabled(self, tool_name: str, enabled: bool) -> None:
        sql = """
            UPDATE tool_registry SET enabled = $2, updated_at = now()
            WHERE tool_name = $1
        """
        async with self._pool.acquire() as conn:
            await conn.execute(sql, tool_name, enabled)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


# ── ProceduralMemory — high-level API ────────────────────────────────────────


def _get_backend(postgres_url: Optional[str]) -> Any:
    url = postgres_url or os.getenv("POSTGRES_URL")
    if url:
        return _PostgresProceduralStore(url)
    log.info("ProceduralMemory: POSTGRES_URL absent — using in-memory fallback")
    return _InMemoryProceduralStore()


class ProceduralMemory:
    """
    Tracks tool call statistics and enforces the auto-disable policy.

    Usage::
        pm = ProceduralMemory()
        await pm.initialize()
        await pm.register_tool(tool)
        await pm.record_call("web_search", success=True, latency_ms=250.0)
        stats  = await pm.get_stats("web_search")
        disabled = await pm.auto_disable_check()
    """

    def __init__(self, postgres_url: Optional[str] = None) -> None:
        self._backend = _get_backend(postgres_url)

    async def initialize(self) -> None:
        """Create the DB table / pool. Call once on startup."""
        await self._backend.initialize()

    async def register_tool(self, tool: Any) -> None:
        """
        Upsert a tool into the registry.
        *tool* must have .name, .description, and .schema attributes.
        """
        schema = getattr(tool, "schema", {})
        await self._backend.register_tool(tool.name, tool.description, schema)
        log.debug("ProceduralMemory.register_tool: %s", tool.name)

    async def record_call(self, tool_name: str, success: bool, latency_ms: float) -> None:
        """Record one tool execution outcome."""
        await self._backend.record_call(tool_name, success, latency_ms)

    async def get_stats(self, tool_name: str) -> Optional[ToolStats]:
        """Return performance statistics for *tool_name*."""
        return await self._backend.get_stats(tool_name)

    async def list_stats(self) -> list[ToolStats]:
        """Return stats for all registered tools."""
        return await self._backend.list_stats()

    async def auto_disable_check(self) -> list[str]:
        """
        Inspect all tools and disable any whose error_rate > ERROR_RATE_THRESHOLD.
        Returns list of tool names that were newly disabled.
        """
        all_stats = await self._backend.list_stats()
        newly_disabled: list[str] = []
        for stats in all_stats:
            if (
                stats.enabled
                and stats.total_calls >= 10  # minimum sample size
                and stats.error_rate > ERROR_RATE_THRESHOLD
            ):
                await self._backend.set_enabled(stats.tool_name, False)
                newly_disabled.append(stats.tool_name)
                log.warning(
                    "ProceduralMemory AUTO-DISABLE: tool=%s error_rate=%.1f%% "
                    "(success=%d error=%d total=%d)",
                    stats.tool_name,
                    stats.error_rate * 100,
                    stats.success_calls,
                    stats.error_calls,
                    stats.total_calls,
                )
        return newly_disabled

    async def close(self) -> None:
        """Close DB pool / connections."""
        await self._backend.close()
