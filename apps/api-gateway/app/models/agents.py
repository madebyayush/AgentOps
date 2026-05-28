"""
Pydantic v2 schemas for Agent and Run resources.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.db.models import RunStatus

# ── Agent ─────────────────────────────────────────────────────────────────────


class AgentCreate(BaseModel):
    """Request body for creating a new Agent."""

    name: str = Field(..., min_length=1, max_length=255, examples=["code-reviewer"])
    type: str = Field(..., min_length=1, max_length=100, examples=["researcher"])
    config_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_no_spaces(cls, v: str) -> str:
        if " " in v.strip():
            raise ValueError("Agent name must not contain spaces. Use hyphens or underscores.")
        return v.strip()


class AgentResponse(BaseModel):
    """Agent resource representation returned by the API."""

    id: uuid.UUID
    name: str
    type: str
    config_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Run ───────────────────────────────────────────────────────────────────────


class AgentRunRequest(BaseModel):
    """Request body to enqueue a new agent run."""

    prompt: str = Field(..., min_length=1, max_length=32_000)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional key-value context injected into the agent's system prompt.",
    )
    max_steps: int = Field(default=25, ge=1, le=200)
    require_hitl: bool = Field(
        default=False,
        description="If true, agent will pause and emit HITL requests before destructive actions.",
    )


class AgentRunResponse(BaseModel):
    """Returned immediately after enqueueing a run."""

    run_id: uuid.UUID
    agent_id: uuid.UUID
    status: RunStatus
    message: str = "Run enqueued successfully."


class RunStatusResponse(BaseModel):
    """Full status of a run — polled by clients or streamed via WebSocket."""

    run_id: uuid.UUID
    agent_id: uuid.UUID
    status: RunStatus
    input_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
