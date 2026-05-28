"""Pydantic v2 schemas for Memory resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryEntryCreate(BaseModel):
    namespace: str = Field(..., min_length=1, max_length=255, examples=["user-prefs"])
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntryResponse(BaseModel):
    id: uuid.UUID
    namespace: str
    content: str
    embedding_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryNamespaceList(BaseModel):
    namespaces: list[str]
    total: int
