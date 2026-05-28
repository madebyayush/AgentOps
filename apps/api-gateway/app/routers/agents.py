"""
Agents Router
=============
Endpoints:
  POST   /agents               — register a new agent definition
  GET    /agents               — list all agents (paginated)
  GET    /agents/{id}          — get agent by ID
  POST   /agents/{id}/run      — enqueue a new run for the agent
  GET    /agents/{id}/status   — get the latest run status (Redis-cached)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Agent, Run, RunStatus
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import rate_limit
from app.models.agents import (
    AgentCreate,
    AgentResponse,
    AgentRunRequest,
    AgentRunResponse,
    RunStatusResponse,
)
from app.models.common import PaginatedResponse
from app.redis_client import AgentOpsRedisClient, get_redis

log = logging.getLogger("agentops.routers.agents")
router = APIRouter(prefix="/agents", tags=["Agents"])


# ── POST /agents ──────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent",
)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
    _rl: None = Depends(rate_limit),
) -> AgentResponse:
    """Register a new agent definition in the platform."""
    # Check for name collision
    existing = await db.execute(select(Agent).where(Agent.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An agent named '{body.name}' already exists.",
        )
    agent = Agent(name=body.name, type=body.type, config_json=body.config_json)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    log.info("Agent created: id=%s name=%s by=%s", agent.id, agent.name, user["sub"])
    return AgentResponse.model_validate(agent)


# ── GET /agents ───────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=PaginatedResponse[AgentResponse],
    summary="List all registered agents",
)
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> PaginatedResponse[AgentResponse]:
    offset = (page - 1) * page_size
    total_result = await db.execute(select(func.count()).select_from(Agent))
    total: int = total_result.scalar_one()
    agents_result = await db.execute(
        select(Agent).order_by(Agent.created_at.desc()).offset(offset).limit(page_size)
    )
    agents = agents_result.scalars().all()
    return PaginatedResponse(
        items=[AgentResponse.model_validate(a) for a in agents],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


# ── GET /agents/{id} ──────────────────────────────────────────────────────────

@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get agent by ID",
)
async def get_agent(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> AgentResponse:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse.model_validate(agent)


# ── POST /agents/{id}/run ─────────────────────────────────────────────────────

@router.post(
    "/{agent_id}/run",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a new agent run",
)
async def run_agent(
    agent_id: uuid.UUID,
    body: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    user: dict = Depends(get_current_user),
    _rl: None = Depends(rate_limit),
) -> AgentRunResponse:
    """Enqueue a new run for the given agent. Returns a run_id for polling."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    run = Run(
        agent_id=agent_id,
        status=RunStatus.queued,
        input_json={"prompt": body.prompt, "context": body.context, "max_steps": body.max_steps},
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    # Cache run status in Redis for fast polling
    rc = AgentOpsRedisClient(redis)
    await rc.set_run_status(str(run.id), RunStatus.queued.value)

    # Publish enqueue event for the agent-runtime to consume
    await rc.publish_run_event(
        str(run.id),
        "run.queued",
        {
            "agent_id": str(agent_id),
            "prompt": body.prompt,
            "max_steps": body.max_steps,
            "require_hitl": body.require_hitl,
            "initiated_by": user["sub"],
        },
    )

    log.info("Run enqueued: run_id=%s agent=%s by=%s", run.id, agent.name, user["sub"])
    return AgentRunResponse(
        run_id=run.id,
        agent_id=agent_id,
        status=RunStatus.queued,
    )


# ── GET /agents/{id}/status ───────────────────────────────────────────────────

@router.get(
    "/{agent_id}/status",
    response_model=RunStatusResponse,
    summary="Get the latest run status for an agent",
)
async def get_agent_status(
    agent_id: uuid.UUID,
    run_id: uuid.UUID | None = Query(None, description="Specific run ID to query."),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    user: dict = Depends(get_current_user),
) -> RunStatusResponse:
    """
    Returns the most recent run's status.
    Prefers Redis cache; falls back to DB for completed/historical runs.
    """
    if run_id:
        run = await db.get(Run, run_id)
    else:
        # Fetch the latest run for this agent
        result = await db.execute(
            select(Run)
            .where(Run.agent_id == agent_id)
            .order_by(Run.created_at.desc())
            .limit(1)
        )
        run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No runs found.")

    # Overlay Redis-cached status for in-progress runs (avoids stale DB reads)
    rc = AgentOpsRedisClient(redis)
    cached_status = await rc.get_run_status(str(run.id))
    if cached_status and run.status in (RunStatus.queued, RunStatus.running):
        run.status = RunStatus(cached_status)  # type: ignore[assignment]

    return RunStatusResponse.model_validate(run)
