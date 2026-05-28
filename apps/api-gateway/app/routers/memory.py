"""
Memory Router
=============
Endpoints:
  GET    /memory               — list distinct namespaces
  POST   /memory               — create a memory entry
  GET    /memory/{namespace}   — list entries in a namespace (paginated)
  DELETE /memory/{namespace}/{id} — delete a specific entry
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import MemoryEntry
from app.middleware.auth import get_current_user
from app.models.memory import MemoryEntryCreate, MemoryEntryResponse, MemoryNamespaceList
from app.models.common import PaginatedResponse

log = logging.getLogger("agentops.routers.memory")
router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("", response_model=MemoryNamespaceList, summary="List all memory namespaces")
async def list_namespaces(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> MemoryNamespaceList:
    result = await db.execute(select(distinct(MemoryEntry.namespace)))
    namespaces = [row[0] for row in result.all()]
    return MemoryNamespaceList(namespaces=namespaces, total=len(namespaces))


@router.post(
    "",
    response_model=MemoryEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a memory entry",
)
async def create_memory_entry(
    body: MemoryEntryCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> MemoryEntryResponse:
    entry = MemoryEntry(
        namespace=body.namespace,
        content=body.content,
        metadata_json=body.metadata,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    log.info(
        "MemoryEntry created: id=%s namespace=%s by=%s", entry.id, entry.namespace, user["sub"]
    )
    return MemoryEntryResponse.model_validate(entry)


@router.get(
    "/{namespace}",
    response_model=PaginatedResponse[MemoryEntryResponse],
    summary="List entries in a namespace",
)
async def list_namespace_entries(
    namespace: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> PaginatedResponse[MemoryEntryResponse]:
    offset = (page - 1) * page_size
    total_result = await db.execute(
        select(func.count()).select_from(MemoryEntry).where(MemoryEntry.namespace == namespace)
    )
    total: int = total_result.scalar_one()
    entries_result = await db.execute(
        select(MemoryEntry)
        .where(MemoryEntry.namespace == namespace)
        .order_by(MemoryEntry.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    entries = entries_result.scalars().all()
    return PaginatedResponse(
        items=[MemoryEntryResponse.model_validate(e) for e in entries],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + page_size) < total,
    )


@router.delete(
    "/{namespace}/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a memory entry",
)
async def delete_memory_entry(
    namespace: str,
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> None:
    entry = await db.get(MemoryEntry, entry_id)
    if not entry or entry.namespace != namespace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory entry not found.")
    await db.delete(entry)
    log.info("MemoryEntry deleted: id=%s namespace=%s by=%s", entry_id, namespace, user["sub"])
