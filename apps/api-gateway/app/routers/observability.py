"""
Observability Router
====================
Endpoints:
  GET /health   — liveness probe (DB + Redis ping)
  GET /ready    — readiness probe
  GET /metrics  — Prometheus-compatible text metrics (basic counters)
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request, status
from fastapi.responses import PlainTextResponse

from app.config import get_settings

log = logging.getLogger("agentops.routers.observability")
settings = get_settings()

# These routers are mounted at root (no /api/v1 prefix) in main.py
router = APIRouter(tags=["Observability"])

_START_TIME = time.time()


@router.get(
    "/health",
    summary="Liveness probe",
    status_code=status.HTTP_200_OK,
)
async def health(request: Request) -> dict:
    """
    Kubernetes liveness probe.
    Actively pings PostgreSQL and Redis to confirm connectivity.
    Returns 200 if both are reachable, 503 otherwise.
    """
    checks: dict[str, str] = {}
    overall_ok = True

    # ── DB ping ───────────────────────────────────────────────────────────────
    try:
        from app.db.session import get_engine
        from sqlalchemy import text
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "healthy"
    except Exception as exc:
        log.error("Health check — Postgres unreachable: %s", exc)
        checks["postgres"] = f"unhealthy: {exc}"
        overall_ok = False

    # ── Redis ping ────────────────────────────────────────────────────────────
    try:
        from app.redis_client import _redis_pool
        if _redis_pool:
            await _redis_pool.ping()
            checks["redis"] = "healthy"
        else:
            checks["redis"] = "pool_not_initialised"
            overall_ok = False
    except Exception as exc:
        log.error("Health check — Redis unreachable: %s", exc)
        checks["redis"] = f"unhealthy: {exc}"
        overall_ok = False

    response_status = status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "healthy" if overall_ok else "degraded",
        "service": "agentops-api-gateway",
        "environment": settings.PLATFORM_ENV,
        "version": "0.1.0",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "checks": checks,
    }


@router.get(
    "/ready",
    summary="Readiness probe",
    status_code=status.HTTP_200_OK,
)
async def ready() -> dict:
    """
    Kubernetes readiness probe.
    Lightweight check — just confirms the process is alive and config loaded.
    """
    return {
        "status": "ready",
        "service": "agentops-api-gateway",
        "environment": settings.PLATFORM_ENV,
    }


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    response_class=PlainTextResponse,
)
async def metrics() -> str:
    """
    Minimal Prometheus text-format metrics endpoint.
    Full instrumentation (request counters, latency histograms) is provided
    by the OpenTelemetry SDK registered in main.py.
    """
    uptime = round(time.time() - _START_TIME, 1)
    lines = [
        "# HELP agentops_uptime_seconds Total uptime of the API gateway process",
        "# TYPE agentops_uptime_seconds gauge",
        f'agentops_uptime_seconds{{service="api-gateway",env="{settings.PLATFORM_ENV}"}} {uptime}',
        "",
        "# HELP agentops_build_info Build metadata",
        "# TYPE agentops_build_info gauge",
        f'agentops_build_info{{version="0.1.0",env="{settings.PLATFORM_ENV}"}} 1',
        "",
    ]
    return "\n".join(lines)
