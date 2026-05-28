"""Pydantic v2 schemas for Workflow resources."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    graph_json: dict[str, Any] = Field(
        ...,
        description=(
            "DAG definition: {nodes: [...], edges: [...], config: {...}}. "
            "Each node references an agent_id and tool list."
        ),
    )


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    graph_json: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowExecuteRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    require_hitl: bool = False
    dry_run: bool = Field(
        default=False,
        description="Validate and plan execution without actually running agents.",
    )
