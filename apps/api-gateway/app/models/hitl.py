"""Pydantic v2 schemas for Human-in-the-Loop resources."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import HitlStatus


class HitlRequestResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    action_description: str
    context_json: dict[str, Any]
    status: HitlStatus
    approved_by: str | None
    rejection_reason: str | None
    decided_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class HitlDecisionRequest(BaseModel):
    """Body for approve / reject endpoints."""
    approved_by: str = Field(
        ..., min_length=1, max_length=255,
        description="Username or user ID of the human reviewer.",
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Required when rejecting — explain why the action was refused.",
    )

    def validate_rejection(self, decision: str) -> None:
        """Call this after determining the decision is 'reject'."""
        if decision == "reject" and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejecting a HITL request.")
