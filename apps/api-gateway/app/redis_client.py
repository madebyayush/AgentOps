"""
AgentOps — Async Redis Client
==============================
Provides:
  - A module-level async Redis connection pool (initialised during app lifespan)
  - `get_redis()` FastAPI dependency
  - Helper methods following the canonical key schema:
        agentops:{resource}:{id}:{field}
  - Sliding-window rate limiter using Redis Sorted Sets
  - Pub/Sub event publisher for real-time UI streaming

Key Schema Reference:
  agentops:run:{run_id}:state          → serialised agent state (JSON)
  agentops:run:{run_id}:status         → run status string
  agentops:memory:{namespace}:{id}     → cached memory entry (JSON)
  agentops:rate_limit:{user_id}:{win}  → sorted set of request timestamps
  agentops:session:{token_hash}        → session metadata (JSON)
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings

log = logging.getLogger("agentops.redis")
settings = get_settings()

# ── Module-level pool (lifecycle managed in main.py lifespan) ─────────────────
_redis_pool: Redis | None = None


async def init_redis_pool() -> None:
    """Create the global Redis connection pool. Called once during app startup."""
    global _redis_pool
    log.info("Initialising Redis connection pool...")
    _redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    # Validate the connection is alive
    try:
        await _redis_pool.ping()
        log.info("Redis connection pool ready.")
    except RedisError as exc:
        log.error("Redis connection failed during startup: %s", exc)
        raise


async def close_redis_pool() -> None:
    """Gracefully close the Redis pool. Called during app shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        log.info("Closing Redis connection pool...")
        await _redis_pool.aclose()
        _redis_pool = None


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Yield the shared Redis client.
    Usage:
        async def my_endpoint(redis: Redis = Depends(get_redis)):
            ...
    """
    if _redis_pool is None:
        raise RuntimeError(
            "Redis pool has not been initialised. "
            "Ensure init_redis_pool() is called in the app lifespan."
        )
    yield _redis_pool


# ── Key-schema helpers ────────────────────────────────────────────────────────


def _build_key(resource: str, *parts: str) -> str:
    """
    Build a canonical Redis key following the schema:
        agentops:{resource}:{part1}:{part2}:...
    """
    segments = ["agentops", resource, *parts]
    return ":".join(str(s) for s in segments)


class AgentOpsRedisClient:
    """
    Thin wrapper around a Redis connection adding AgentOps-specific helpers.
    Instantiate via `AgentOpsRedisClient(redis)` inside a request handler.
    """

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ── Generic cache ─────────────────────────────────────────────────────────

    async def cache_set(
        self,
        resource: str,
        resource_id: str,
        field: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """
        Store a JSON-serialised value under the canonical key.
        ttl defaults to settings.REDIS_DEFAULT_TTL (seconds).
        """
        key = _build_key(resource, resource_id, field)
        payload = json.dumps(value) if not isinstance(value, str) else value
        effective_ttl = ttl if ttl is not None else settings.REDIS_DEFAULT_TTL
        try:
            await self._r.set(key, payload, ex=effective_ttl)
            log.debug("cache_set: key=%s ttl=%ss", key, effective_ttl)
        except RedisError as exc:
            log.error("cache_set failed for key=%s: %s", key, exc)

    async def cache_get(self, resource: str, resource_id: str, field: str) -> Any | None:
        """
        Retrieve and JSON-deserialise a cached value.
        Returns None on cache miss or error.
        """
        key = _build_key(resource, resource_id, field)
        try:
            raw = await self._r.get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw  # already a plain string
        except RedisError as exc:
            log.error("cache_get failed for key=%s: %s", key, exc)
            return None

    async def cache_delete(self, resource: str, resource_id: str, field: str) -> int:
        """Delete a single cache key. Returns number of keys deleted (0 or 1)."""
        key = _build_key(resource, resource_id, field)
        try:
            return await self._r.delete(key)
        except RedisError as exc:
            log.error("cache_delete failed for key=%s: %s", key, exc)
            return 0

    async def cache_delete_namespace(self, resource: str, resource_id: str) -> int:
        """
        Delete ALL keys matching agentops:{resource}:{resource_id}:*
        Uses SCAN to avoid blocking the server.
        """
        pattern = _build_key(resource, resource_id, "*")
        deleted = 0
        try:
            async for key in self._r.scan_iter(match=pattern, count=100):
                await self._r.delete(key)
                deleted += 1
        except RedisError as exc:
            log.error("cache_delete_namespace failed for pattern=%s: %s", pattern, exc)
        return deleted

    # ── Agent run working memory ──────────────────────────────────────────────

    async def set_run_state(self, run_id: str, state: dict[str, Any]) -> None:
        """Store serialised agent state for an in-progress run (TTL = 2 hours)."""
        await self.cache_set("run", run_id, "state", state, ttl=7200)

    async def get_run_state(self, run_id: str) -> dict[str, Any] | None:
        return await self.cache_get("run", run_id, "state")

    async def set_run_status(self, run_id: str, status: str) -> None:
        await self.cache_set("run", run_id, "status", status, ttl=86400)

    async def get_run_status(self, run_id: str) -> str | None:
        return await self.cache_get("run", run_id, "status")

    # ── Pub/Sub ───────────────────────────────────────────────────────────────

    async def publish_event(self, channel: str, payload: dict[str, Any]) -> int:
        """
        Publish a JSON event to a Redis channel.
        The UI WebSocket handler subscribes to these channels.

        Recommended channel names:
          agentops:run:{run_id}:events
          agentops:workflow:{workflow_id}:events
        """
        message = json.dumps(payload)
        try:
            receivers = await self._r.publish(channel, message)
            log.debug("publish_event: channel=%s receivers=%d", channel, receivers)
            return receivers
        except RedisError as exc:
            log.error("publish_event failed on channel=%s: %s", channel, exc)
            return 0

    async def publish_run_event(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Convenience wrapper for publishing run lifecycle events."""
        channel = _build_key("run", run_id, "events")
        await self.publish_event(
            channel,
            {"event": event_type, "run_id": run_id, "data": data},
        )

    # ── Sliding-window Rate Limiter ───────────────────────────────────────────

    async def rate_limit_check(
        self,
        user_id: str,
        window_seconds: int | None = None,
        max_requests: int | None = None,
    ) -> tuple[bool, int]:
        """
        Sliding-window rate limiter using a Redis Sorted Set.

        Algorithm:
          1. ZREMRANGEBYSCORE to drop entries older than window
          2. ZCARD to count remaining entries in window
          3. If count < limit: ZADD current timestamp, return allowed=True
          4. Else: return allowed=False with remaining TTL

        Returns:
          (allowed: bool, requests_remaining: int)
        """
        _window = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
        _limit = max_requests or settings.RATE_LIMIT_MAX_REQUESTS
        key = _build_key("rate_limit", user_id, f"w{_window}")
        now = time.time()
        window_start = now - _window

        try:
            pipe = self._r.pipeline()
            # 1. Remove stale entries
            await pipe.zremrangebyscore(key, "-inf", window_start)
            # 2. Count current entries
            await pipe.zcard(key)
            results = await pipe.execute()
            current_count: int = results[1]

            if current_count < _limit:
                # 3. Record this request
                pipe2 = self._r.pipeline()
                await pipe2.zadd(key, {str(now): now})
                await pipe2.expire(key, _window + 1)
                await pipe2.execute()
                return True, _limit - current_count - 1
            else:
                return False, 0

        except RedisError as exc:
            log.error("rate_limit_check failed for user=%s: %s", user_id, exc)
            # Fail open on Redis errors to avoid blocking all traffic
            return True, _limit

    # ── Session cache ─────────────────────────────────────────────────────────

    async def set_session(self, token_hash: str, data: dict[str, Any], ttl: int = 3600) -> None:
        key = _build_key("session", token_hash)
        await self._r.set(key, json.dumps(data), ex=ttl)

    async def get_session(self, token_hash: str) -> dict[str, Any] | None:
        key = _build_key("session", token_hash)
        raw = await self._r.get(key)
        if raw:
            return json.loads(raw)
        return None

    async def delete_session(self, token_hash: str) -> None:
        key = _build_key("session", token_hash)
        await self._r.delete(key)
