"""
Common / shared Pydantic v2 schemas used across multiple routers.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class PaginatedResponse(BaseModel, Generic[DataT]):
    """Generic paginated list wrapper."""
    items: list[DataT]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    has_next: bool

    model_config = {"from_attributes": True}


class ErrorDetail(BaseModel):
    """Standard error response body."""
    code: str
    message: str
    detail: dict | None = None


class HealthResponse(BaseModel):
    """Liveness / readiness probe response."""
    status: str
    service: str
    environment: str
    version: str
    checks: dict[str, str] = Field(default_factory=dict)
