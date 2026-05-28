"""
Workflows Router
================
Endpoints:
  POST   /workflows              — create a new workflow
  GET    /workflows              — list workflows (paginated)
  GET    /workflows/{id}         — get workflow by ID
  POST   /workflows/{id}/execute — execute a workflow
  DELETE /workflows/{id}         — delete a workflow
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Workflow
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import rate_limit
from app.models.common import PaginatedResponse
from app.models.workflows import WorkflowCreate, WorkflowExecuteRequest, WorkflowResponse

log = logging.getLogger("agentops.routers.workflows")
router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workflow",
)
async def create_workflow(
    body: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> WorkflowResponse:
    existing = await db.execute(select(Workflow).where(Workflow.name == body.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A workflow named '{body.name}' already exists.",
        )
    wf = Workflow(name=body.name, description=body.description, graph_json=body.graph_json)
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    log.info("Workflow created: id=%s name=%s by=%s", wf.id, wf.name, user["sub"])
    return WorkflowResponse.model_validate(wf)


@router.get(
    "",
    response_model=PaginatedResponse[WorkflowResponse],
    summary="List workflows",
)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> PaginatedResponse[WorkflowResponse]:
    offset = (page - 1) * page_size
    total = (await db.execute(select(func.count()).select_from(Workflow))).scalar_one()
    rows = (
        (
            await db.execute(
                select(Workflow)
                .order_by(Workflow.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return PaginatedResponse(
        items=[WorkflowResponse.model_validate(w) for w in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse, summary="Get workflow by ID")
async def get_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> WorkflowResponse:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    return WorkflowResponse.model_validate(wf)


@router.post(
    "/{workflow_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute a workflow",
)
async def execute_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowExecuteRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
    _rl: None = Depends(rate_limit),
) -> dict:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    log.info(
        "Workflow execute: id=%s name=%s dry_run=%s by=%s",
        workflow_id,
        wf.name,
        body.dry_run,
        user["sub"],
    )
    # Phase 1: return execution plan stub. Phase 2 dispatches to agent-runtime.
    return {
        "workflow_id": str(workflow_id),
        "status": "dry_run_validated" if body.dry_run else "dispatched",
        "message": (
            "Dry-run completed. No agents were executed."
            if body.dry_run
            else "Workflow dispatched to execution engine."
        ),
    }


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workflow",
)
async def delete_workflow(
    workflow_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> None:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found.")
    await db.delete(wf)
    log.info("Workflow deleted: id=%s name=%s by=%s", workflow_id, wf.name, user["sub"])
