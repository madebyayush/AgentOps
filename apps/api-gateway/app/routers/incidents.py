"""
Incidents Router
================
Endpoints:
  POST  /incidents        — create a new incident
  GET   /incidents        — list incidents (paginated, filterable by status/severity)
  GET   /incidents/{id}   — get incident detail
  PATCH /incidents/{id}   — update incident (status, root_cause, resolution)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Incident, IncidentSeverity, IncidentStatus
from app.middleware.auth import get_current_user
from app.models.common import PaginatedResponse
from app.models.incidents import IncidentCreate, IncidentResponse, IncidentUpdateRequest

log = logging.getLogger("agentops.routers.incidents")
router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new incident",
)
async def create_incident(
    body: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> IncidentResponse:
    incident = Incident(
        severity=body.severity,
        description=body.description,
        affected_run_id=body.affected_run_id,
        metadata_json=body.metadata,
    )
    db.add(incident)
    await db.flush()
    await db.refresh(incident)
    log.warning(
        "Incident created: id=%s severity=%s by=%s",
        incident.id,
        incident.severity.value,
        user["sub"],
    )
    return IncidentResponse.model_validate(incident)


@router.get(
    "",
    response_model=PaginatedResponse[IncidentResponse],
    summary="List incidents",
)
async def list_incidents(
    severity: IncidentSeverity | None = Query(None),
    inc_status: IncidentStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> PaginatedResponse[IncidentResponse]:
    filters = []
    if severity:
        filters.append(Incident.severity == severity)
    if inc_status:
        filters.append(Incident.status == inc_status)

    offset = (page - 1) * page_size
    count_q = select(func.count()).select_from(Incident)
    data_q = select(Incident).order_by(Incident.created_at.desc()).offset(offset).limit(page_size)
    if filters:
        count_q = count_q.where(*filters)
        data_q = data_q.where(*filters)

    total = (await db.execute(count_q)).scalar_one()
    rows = (await db.execute(data_q)).scalars().all()
    return PaginatedResponse(
        items=[IncidentResponse.model_validate(i) for i in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.get("/{incident_id}", response_model=IncidentResponse, summary="Get incident by ID")
async def get_incident(
    incident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> IncidentResponse:
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")
    return IncidentResponse.model_validate(inc)


@router.patch("/{incident_id}", response_model=IncidentResponse, summary="Update incident")
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> IncidentResponse:
    inc = await db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    if body.status is not None:
        inc.status = body.status
        if body.status == IncidentStatus.resolved and inc.resolved_at is None:
            inc.resolved_at = datetime.now(timezone.utc)
    if body.root_cause is not None:
        inc.root_cause = body.root_cause
    if body.resolution is not None:
        inc.resolution = body.resolution
    if body.metadata is not None:
        inc.metadata_json = {**inc.metadata_json, **body.metadata}

    await db.flush()
    await db.refresh(inc)
    log.info("Incident updated: id=%s status=%s by=%s", incident_id, inc.status.value, user["sub"])
    return IncidentResponse.model_validate(inc)
