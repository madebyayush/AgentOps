"""
HITL Router — Human-in-the-Loop Approvals
==========================================
Endpoints:
  GET  /hitl/pending       — list all pending HITL requests
  GET  /hitl/{id}          — get HITL request detail
  POST /hitl/{id}/approve  — approve the proposed action
  POST /hitl/{id}/reject   — reject the proposed action
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import HitlRequest, HitlStatus
from app.middleware.auth import get_current_user
from app.models.hitl import HitlDecisionRequest, HitlRequestResponse
from app.redis_client import AgentOpsRedisClient, get_redis

log = logging.getLogger("agentops.routers.hitl")
router = APIRouter(prefix="/hitl", tags=["Human-in-the-Loop"])


@router.get(
    "/pending", response_model=list[HitlRequestResponse], summary="List pending HITL requests"
)
async def list_pending(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> list[HitlRequestResponse]:
    result = await db.execute(
        select(HitlRequest)
        .where(HitlRequest.status == HitlStatus.pending)
        .order_by(HitlRequest.created_at.asc())
    )
    requests = result.scalars().all()
    return [HitlRequestResponse.model_validate(r) for r in requests]


@router.get("/{hitl_id}", response_model=HitlRequestResponse, summary="Get HITL request detail")
async def get_hitl_request(
    hitl_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> HitlRequestResponse:
    req = await db.get(HitlRequest, hitl_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL request not found.")
    return HitlRequestResponse.model_validate(req)


async def _decide(
    hitl_id: uuid.UUID,
    decision: str,
    body: HitlDecisionRequest,
    db: AsyncSession,
    redis,
    user: dict,
) -> HitlRequestResponse:
    """Shared logic for approve / reject."""
    req = await db.get(HitlRequest, hitl_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HITL request not found.")
    if req.status != HitlStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"HITL request is already {req.status.value}.",
        )
    if decision == "reject":
        body.validate_rejection(decision)

    req.status = HitlStatus.approved if decision == "approve" else HitlStatus.rejected
    req.approved_by = body.approved_by
    req.rejection_reason = body.rejection_reason
    req.decided_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(req)

    # Notify agent-runtime via Redis pub/sub so the run can resume or abort
    rc = AgentOpsRedisClient(redis)
    await rc.publish_run_event(
        str(req.run_id),
        f"hitl.{decision}d",
        {
            "hitl_id": str(hitl_id),
            "decided_by": body.approved_by,
            "rejection_reason": body.rejection_reason,
        },
    )
    log.info(
        "HITL %s: id=%s run_id=%s by=%s",
        decision,
        hitl_id,
        req.run_id,
        user["sub"],
    )
    return HitlRequestResponse.model_validate(req)


@router.post(
    "/{hitl_id}/approve",
    response_model=HitlRequestResponse,
    summary="Approve a HITL action",
)
async def approve_hitl(
    hitl_id: uuid.UUID,
    body: HitlDecisionRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    user: dict = Depends(get_current_user),
) -> HitlRequestResponse:
    return await _decide(hitl_id, "approve", body, db, redis, user)


@router.post(
    "/{hitl_id}/reject",
    response_model=HitlRequestResponse,
    summary="Reject a HITL action",
)
async def reject_hitl(
    hitl_id: uuid.UUID,
    body: HitlDecisionRequest,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    user: dict = Depends(get_current_user),
) -> HitlRequestResponse:
    return await _decide(hitl_id, "reject", body, db, redis, user)
