"""Pydantic v2 schemas for Incident resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import IncidentSeverity, IncidentStatus


class IncidentCreate(BaseModel):
    severity: IncidentSeverity
    description: str = Field(..., min_length=1)
    affected_run_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentResponse(BaseModel):
    id: uuid.UUID
    severity: IncidentSeverity
    description: str
    status: IncidentStatus
    root_cause: str | None
    resolution: str | None
    affected_run_id: uuid.UUID | None
    metadata_json: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class IncidentUpdateRequest(BaseModel):
    """PATCH body — all fields optional, at least one must be provided."""

    status: IncidentStatus | None = None
    root_cause: str | None = None
    resolution: str | None = None
    metadata: dict[str, Any] | None = None
