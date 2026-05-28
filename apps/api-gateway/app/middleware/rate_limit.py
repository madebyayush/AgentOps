"""
Rate Limiting Middleware
-------------------------
Sliding-window rate limiter using Redis sorted sets.

This is implemented as a FastAPI **dependency** (not Starlette middleware)
so it can access the per-request Redis client and user context cleanly.

Usage:
    @router.post("/agents/{id}/run")
    async def run_agent(
        _: None = Depends(rate_limit),
        user: dict = Depends(get_current_user),
        ...
    ):
        ...

The middleware version (below) is a thin Starlette wrapper for routes
that don't inject the Redis dependency directly.
"""
from __future__ import annotations

import logging
import time

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.config import get_settings
from app.redis_client import AgentOpsRedisClient, get_redis

log = logging.getLogger("agentops.rate_limit")
settings = get_settings()


async def rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    """
    FastAPI dependency enforcing per-user sliding-window rate limits.
    Injects nothing into the endpoint — just raises 429 on breach.

    Add to any router or individual endpoint:
        Depends(rate_limit)
    """
    # Determine caller identity (fall back to IP for unauthenticated endpoints)
    user = getattr(request.state, "user", None)
    user_id: str = user["sub"] if user else request.client.host if request.client else "anon"

    client = AgentOpsRedisClient(redis)
    allowed, remaining = await client.rate_limit_check(
        user_id=user_id,
        window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        max_requests=settings.RATE_LIMIT_MAX_REQUESTS,
    )

    # Annotate response headers (useful for client SDKs)
    request.state.rate_limit_remaining = remaining

    if not allowed:
        log.warning("Rate limit exceeded for user=%s path=%s", user_id, request.url.path)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded. Maximum {settings.RATE_LIMIT_MAX_REQUESTS} requests "
                f"per {settings.RATE_LIMIT_WINDOW_SECONDS}s window."
            ),
            headers={
                "Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS),
                "X-RateLimit-Limit": str(settings.RATE_LIMIT_MAX_REQUESTS),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Window": str(settings.RATE_LIMIT_WINDOW_SECONDS),
            },
        )
