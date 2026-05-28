"""
Tools Router
============
Endpoints:
  GET  /tools          — list all enabled tools
  GET  /tools/{id}     — get tool schema by ID
  POST /tools/invoke   — invoke a tool (dispatches to agent-runtime)
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Tool
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import rate_limit
from app.models.tools import ToolInvokeRequest, ToolInvokeResponse, ToolResponse

log = logging.getLogger("agentops.routers.tools")
router = APIRouter(prefix="/tools", tags=["Tools"])


@router.get("", response_model=list[ToolResponse], summary="List all enabled tools")
async def list_tools(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> list[ToolResponse]:
    result = await db.execute(
        select(Tool).where(Tool.is_enabled == True).order_by(Tool.name)  # noqa: E712
    )
    tools = result.scalars().all()
    return [ToolResponse.model_validate(t) for t in tools]


@router.get("/{tool_id}", response_model=ToolResponse, summary="Get tool schema by ID")
async def get_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> ToolResponse:
    tool = await db.get(Tool, tool_id)
    if not tool or not tool.is_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")
    return ToolResponse.model_validate(tool)


@router.post(
    "/invoke",
    response_model=ToolInvokeResponse,
    summary="Invoke a registered tool",
)
async def invoke_tool(
    body: ToolInvokeRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
    _rl: None = Depends(rate_limit),
) -> ToolInvokeResponse:
    """
    Dispatches a tool invocation request.
    Phase 1: validates tool exists and returns a stub response.
    Phase 2: will publish to Kafka / agent-runtime for actual execution.
    """
    result = await db.execute(
        select(Tool).where(Tool.name == body.tool_name, Tool.is_enabled == True)  # noqa: E712
    )
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{body.tool_name}' not found or is disabled.",
        )

    start = time.perf_counter()
    # Phase 1 stub — actual dispatch to agent-runtime added in Phase 2
    log.info(
        "Tool invocation: tool=%s run_id=%s by=%s",
        body.tool_name,
        body.run_id,
        user["sub"],
    )
    duration_ms = (time.perf_counter() - start) * 1000

    return ToolInvokeResponse(
        tool_name=body.tool_name,
        success=True,
        result={"status": "dispatched", "note": "Full execution available in Phase 2."},
        duration_ms=duration_ms,
    )
