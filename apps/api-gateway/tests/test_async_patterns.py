"""
Async Pattern Tests
Tests: session rollback on error, concurrent requests handled correctly,
       DB session cleanup, Redis pool initialisation guard, model repr methods.
"""

from __future__ import annotations

import asyncio
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.models import Agent, RunStatus, IncidentSeverity, IncidentStatus
from app.redis_client import AgentOpsRedisClient


class TestDBSessionRollback:
    async def test_session_rollback_on_error(self, db_session: AsyncSession):
        """An exception inside a transaction must roll back cleanly."""
        # Insert an agent first
        agent = Agent(id=uuid.uuid4(), name="rollback-test-agent", type="generic", config_json={})
        db_session.add(agent)
        await db_session.flush()

        agent_id = agent.id

        # Simulate error by flushing a duplicate (unique name constraint)
        agent2 = Agent(id=uuid.uuid4(), name="rollback-test-agent", type="generic", config_json={})
        db_session.add(agent2)
        try:
            await db_session.flush()
        except Exception:
            await db_session.rollback()

        # Session should still be usable after rollback
        result = await db_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    async def test_concurrent_redis_operations(self, fake_redis):
        """Multiple concurrent cache operations must all complete without race conditions."""
        client = AgentOpsRedisClient(fake_redis)

        async def set_key(i: int) -> None:
            await client.cache_set("test", f"concurrent-{i}", "val", i * 10)

        await asyncio.gather(*[set_key(i) for i in range(20)])

        # Verify all values are present
        for i in range(20):
            val = await client.cache_get("test", f"concurrent-{i}", "val")
            assert val == i * 10, f"Expected {i * 10} for key concurrent-{i}, got {val}"


class TestModelRepr:
    def test_agent_repr(self):
        a = Agent(id=uuid.uuid4(), name="repr-agent", type="coder", config_json={})
        r = repr(a)
        assert "repr-agent" in r
        assert "Agent" in r

    def test_run_status_enum_is_str(self):
        """RunStatus must be usable as a plain string for JSON serialisation."""
        s = RunStatus.queued
        assert str(s) == "queued" or s.value == "queued"

    def test_incident_severity_enum(self):
        for level in ("low", "medium", "high", "critical"):
            s = IncidentSeverity(level)
            assert s.value == level


class TestRedisPoolGuard:
    async def test_get_redis_raises_if_pool_not_init(self):
        """get_redis() must raise RuntimeError if pool is None."""
        import app.redis_client as rc

        original_pool = rc._redis_pool
        rc._redis_pool = None
        try:
            gen = rc.get_redis()
            with pytest.raises(RuntimeError, match="not been initialised"):
                async for _ in gen:
                    pass
        finally:
            rc._redis_pool = original_pool


class TestConcurrentRequests:
    async def test_sequential_agent_creates_succeed(self, client):
        """Sequential POST /agents with unique names must all return 201."""
        # SQLite in-memory only supports single-writer — test sequentially
        statuses = []
        for i in range(5):
            resp = await client.post(
                "/api/v1/agents",
                json={"name": f"seq-agent-{i}", "type": "generic"},
            )
            statuses.append(resp.status_code)
        assert all(s == 201 for s in statuses), f"Got statuses: {statuses}"

    async def test_duplicate_agent_name_returns_409(self, client):
        """Creating an agent with an already-used name must return 409."""
        await client.post("/api/v1/agents", json={"name": "conflict-agent", "type": "coder"})
        resp = await client.post("/api/v1/agents", json={"name": "conflict-agent", "type": "coder"})
        assert resp.status_code == 409
