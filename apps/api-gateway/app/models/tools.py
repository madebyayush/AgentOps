"""Pydantic v2 schemas for Tool resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ToolResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    tool_schema: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ToolInvokeRequest(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: uuid.UUID | None = Field(
        default=None,
        description="Associate this invocation with an in-progress run for audit tracing.",
    )


class ToolInvokeResponse(BaseModel):
    tool_name: str
    success: bool
    result: Any
    error: str | None = None
    duration_ms: float | None = None
