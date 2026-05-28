"""
AgentOps API Gateway — Pytest Fixtures
========================================
NOTE: The root-level conftest.py (api-gateway/conftest.py) patches
      sqlalchemy.dialects.postgresql.{UUID,JSONB} to generic types and sets
      required env vars BEFORE this file is imported. Do not reorder.

Strategy:
  - Database  : SQLite in-memory (engine patched into app.db.session globals)
  - Redis     : fakeredis (fully in-process)
  - Auth      : JWT tokens minted from TEST_SECRET
  - Client    : httpx.AsyncClient with ASGITransport against real FastAPI app
  - Overrides : get_db, get_redis, get_current_user all overridden per test
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Constants ──────────────────────────────────────────────────────────────────
TEST_SECRET = "test-secret-key-for-agentops-testing-only-32chars"
TEST_ALGORITHM = "HS256"
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── Async event loop ───────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── SQLite async engine ────────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """
    Create a shared in-memory SQLite engine.
    Patches app.db.session._engine so the production session factory
    uses this engine for all requests during tests.
    """
    # Import AFTER root conftest has patched UUID/JSONB
    from app.db.base import Base
    import app.db.models  # noqa: F401  register all models

    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Inject into the production session module so get_db() uses SQLite
    import app.db.session as sess_mod

    sess_mod._engine = engine
    sess_mod._AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session — rolled back after each test for isolation."""
    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


# ── Fakeredis ─────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="function")
async def fake_redis():
    server = fakeredis.FakeRedis(decode_responses=True)
    yield server
    await server.flushall()
    await server.aclose()


# ── JWT helpers ────────────────────────────────────────────────────────────────
def make_jwt(
    sub: str = "test-user",
    roles: list[str] | None = None,
    secret: str = TEST_SECRET,
    algorithm: str = TEST_ALGORITHM,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    roles = roles or ["operator"]
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=1))
    payload = {"sub": sub, "roles": roles, "exp": expire, **(extra_claims or {})}
    return jwt.encode(payload, secret, algorithm=algorithm)


def make_expired_jwt(sub: str = "test-user") -> str:
    return make_jwt(sub=sub, expires_delta=timedelta(seconds=-10))


def make_admin_jwt() -> str:
    return make_jwt(sub="admin-user", roles=["admin"])


def make_auditor_jwt() -> str:
    return make_jwt(sub="auditor-user", roles=["auditor"])


# ── Settings fixture ──────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def test_settings():
    from app.config import get_settings

    return get_settings()


# ── FastAPI app with overrides ────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="function")
async def app(db_session: AsyncSession, fake_redis, test_settings) -> FastAPI:
    """
    Return the real FastAPI app with all I/O dependencies overridden:
      get_db()           → test db_session (SQLite)
      get_redis()        → fake_redis (fakeredis)
      get_current_user() → operator user
    """
    from app.main import create_app
    from app.db.session import get_db
    from app.redis_client import get_redis
    from app.middleware.auth import get_current_user

    application = create_app()

    async def override_get_db():
        yield db_session

    async def override_get_redis():
        yield fake_redis

    async def override_get_current_user():
        return {"sub": "test-user", "roles": ["operator"], "auth_method": "jwt"}

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_redis] = override_get_redis
    application.dependency_overrides[get_current_user] = override_get_current_user

    return application


@pytest_asyncio.fixture(scope="function")
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated client (operator JWT)."""
    token = make_jwt(sub="test-user", roles=["operator"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def anon_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="function")
async def admin_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    token = make_admin_jwt()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


# ── DB seed helpers ────────────────────────────────────────────────────────────
async def seed_agent(
    session: AsyncSession, name: str = "test-agent", type_: str = "researcher"
) -> dict:
    from app.db.models import Agent

    agent = Agent(name=name, type=type_, config_json={"model": "gpt-4o"})
    session.add(agent)
    await session.flush()
    return {"id": str(agent.id), "name": agent.name, "type": agent.type}


async def seed_run(session: AsyncSession, agent_id: Any) -> dict:
    from app.db.models import Run, RunStatus

    run = Run(agent_id=agent_id, status=RunStatus.queued, input_json={"prompt": "test"})
    session.add(run)
    await session.flush()
    return {"id": str(run.id), "agent_id": str(run.agent_id), "status": run.status.value}


async def seed_tool(session: AsyncSession, name: str = "test-tool", enabled: bool = True) -> dict:
    from app.db.models import Tool

    tool = Tool(
        name=name, description="A test tool", tool_schema={"type": "object"}, is_enabled=enabled
    )
    session.add(tool)
    await session.flush()
    return {"id": str(tool.id), "name": tool.name, "is_enabled": tool.is_enabled}


async def seed_workflow(session: AsyncSession, name: str = "test-workflow") -> dict:
    from app.db.models import Workflow

    wf = Workflow(name=name, graph_json={"nodes": [], "edges": []}, version=1)
    session.add(wf)
    await session.flush()
    return {"id": str(wf.id), "name": wf.name}


async def seed_hitl(session: AsyncSession, run_id: Any) -> dict:
    from app.db.models import HitlRequest, HitlStatus

    req = HitlRequest(
        run_id=run_id,
        action_description="Delete production database",
        context_json={"risk": "high"},
        status=HitlStatus.pending,
    )
    session.add(req)
    await session.flush()
    return {"id": str(req.id), "run_id": str(req.run_id), "status": req.status.value}


async def seed_incident(session: AsyncSession, severity: str = "high") -> dict:
    from app.db.models import Incident, IncidentSeverity, IncidentStatus

    inc = Incident(
        severity=IncidentSeverity(severity),
        description="Test incident",
        status=IncidentStatus.open,
        metadata_json={},
    )
    session.add(inc)
    await session.flush()
    return {"id": str(inc.id), "severity": inc.severity.value, "status": inc.status.value}
