"""
AgentOps API Gateway — Application Factory
============================================
`create_app()` wires together:
  - lifespan context (DB pool + Redis pool init/teardown)
  - Middleware stack (order matters — applied bottom-up in Starlette)
  - All 7 routers
  - OpenAPI metadata

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Production (via gunicorn + uvicorn workers):
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware.pii_redact import PIIRedactLogFilter
from app.middleware.request_id import RequestIDMiddleware
from app.redis_client import close_redis_pool, init_redis_pool
from app.routers import (
    agents,
    hitl,
    incidents,
    memory,
    observability,
    tools,
    workflows,
)

# ── Logging setup ─────────────────────────────────────────────────────────────
settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s (%(request_id)s): %(message)s",
)

# Attach PII redaction filter to the root logger
_pii_filter = PIIRedactLogFilter()
logging.getLogger().addFilter(_pii_filter)

log = logging.getLogger("agentops.main")


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Async context manager that runs on startup and shutdown.
    - Startup : initialise Redis pool, log banner
    - Shutdown: drain Redis pool

    Database connections are managed per-request via `get_db()` dependency,
    so no explicit pool init is needed here beyond engine creation (which
    happens at module import in db/session.py).
    """
    log.info(
        "AgentOps API Gateway starting — env=%s log_level=%s",
        settings.PLATFORM_ENV,
        settings.LOG_LEVEL,
    )

    # Initialise Redis connection pool
    await init_redis_pool()
    log.info("All startup tasks complete. Gateway is ready.")

    yield  # ← application runs here

    # Graceful shutdown
    log.info("Shutting down AgentOps API Gateway...")
    await close_redis_pool()
    log.info("Shutdown complete.")


# ── App factory ───────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """
    Factory function creating and configuring the FastAPI application.
    Separating creation from the module-level `app` object makes testing easier.
    """
    application = FastAPI(
        title="AgentOps Enterprise API Gateway",
        description=(
            "Autonomous AI orchestration platform — manages agents, workflows, "
            "memory, tools, and human-in-the-loop approvals."
        ),
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware (applied in reverse order — last added is outermost) ────────
    # 1. CORS (outermost — handles preflight before any other logic)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 2. Request ID (stamps every request with a UUID trace ID)
    application.add_middleware(RequestIDMiddleware)

    # ── Global exception handler ──────────────────────────────────────────────
    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        log.exception(
            "Unhandled exception on %s %s (request_id=%s)",
            request.method,
            request.url.path,
            request_id,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Please try again later.",
                "request_id": request_id,
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    api_prefix = settings.API_V1_PREFIX

    # Health / metrics at root (no version prefix — Kubernetes probes expect /health)
    application.include_router(observability.router)

    # All other routes under /api/v1
    application.include_router(agents.router, prefix=api_prefix)
    application.include_router(memory.router, prefix=api_prefix)
    application.include_router(tools.router, prefix=api_prefix)
    application.include_router(workflows.router, prefix=api_prefix)
    application.include_router(hitl.router, prefix=api_prefix)
    application.include_router(incidents.router, prefix=api_prefix)

    return application


# ── Module-level app instance (used by uvicorn / gunicorn) ────────────────────
app = create_app()


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower(),
    )
