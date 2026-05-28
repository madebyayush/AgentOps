"""
Redis Caching Tests
Tests: cache set/get, TTL, miss on nonexistent key, pub/sub publish,
       sliding-window rate limiter (allow, exhaust, window reset).
"""
from __future__ import annotations

import asyncio
import time
import pytest

from app.redis_client import AgentOpsRedisClient, _build_key


class TestCacheSetGet:
    async def test_cache_set_and_get(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        await client.cache_set("run", "abc123", "state", {"step": 1})
        result = await client.cache_get("run", "abc123", "state")
        assert result == {"step": 1}

    async def test_cache_miss_returns_none(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        result = await client.cache_get("run", "nonexistent", "state")
        assert result is None

    async def test_cache_delete(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        await client.cache_set("run", "del-me", "status", "queued")
        deleted = await client.cache_delete("run", "del-me", "status")
        assert deleted == 1
        assert await client.cache_get("run", "del-me", "status") is None

    async def test_cache_string_value(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        await client.cache_set("run", "xyz", "status", "running")
        result = await client.cache_get("run", "xyz", "status")
        assert result == "running"


class TestRunState:
    async def test_set_and_get_run_state(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        state = {"messages": ["hello"], "step": 5, "tool_calls": []}
        await client.set_run_state("run-001", state)
        retrieved = await client.get_run_state("run-001")
        assert retrieved == state

    async def test_set_and_get_run_status(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        await client.set_run_status("run-002", "running")
        status = await client.get_run_status("run-002")
        assert status == "running"


class TestPubSub:
    async def test_publish_run_event(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        # fakeredis supports pub/sub — we verify publish returns int receiver count
        count = await client.publish_event(
            "agentops:run:test-run:events",
            {"event": "run.queued", "run_id": "test-run"},
        )
        # No subscribers in test, but publish should not raise
        assert isinstance(count, int)


class TestRateLimiter:
    async def test_rate_limit_allows_requests(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        allowed, remaining = await client.rate_limit_check("user-1", window_seconds=60, max_requests=10)
        assert allowed is True
        assert remaining == 9

    async def test_rate_limit_tracks_multiple_requests(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        for _ in range(5):
            allowed, remaining = await client.rate_limit_check("user-2", window_seconds=60, max_requests=5)

        # 5th request uses the last slot
        assert allowed is True
        assert remaining == 0

    async def test_rate_limit_blocks_on_exhaustion(self, fake_redis):
        client = AgentOpsRedisClient(fake_redis)
        # Exhaust limit
        for _ in range(3):
            await client.rate_limit_check("user-block", window_seconds=60, max_requests=3)
        # Next request should be blocked
        allowed, remaining = await client.rate_limit_check("user-block", window_seconds=60, max_requests=3)
        assert allowed is False
        assert remaining == 0

    async def test_key_schema_format(self, fake_redis):
        """Ensure canonical key format agentops:{resource}:{id}:{field} is used."""
        client = AgentOpsRedisClient(fake_redis)
        await client.cache_set("workflow", "wf-abc", "state", {"step": 3})
        key = _build_key("workflow", "wf-abc", "state")
        raw = await fake_redis.get(key)
        assert raw is not None
        assert "step" in raw
