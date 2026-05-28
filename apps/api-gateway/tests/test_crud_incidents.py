"""
CRUD — Incident endpoints
Tests: create, list with severity/status filters, get, PATCH update, resolved_at auto-set.
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_incident


class TestIncidentCreate:
    async def test_create_incident_success(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/incidents",
            json={"severity": "high", "description": "Database timeout spike"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["severity"] == "high"
        assert data["status"] == "open"
        assert data["resolved_at"] is None

    async def test_create_incident_critical(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/incidents",
            json={"severity": "critical", "description": "Total system outage"},
        )
        assert resp.status_code == 201
        assert resp.json()["severity"] == "critical"

    async def test_create_incident_invalid_severity(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/incidents",
            json={"severity": "catastrophic", "description": "Bad severity"},
        )
        assert resp.status_code == 422

    async def test_create_incident_missing_description(self, client: AsyncClient):
        resp = await client.post("/api/v1/incidents", json={"severity": "low"})
        assert resp.status_code == 422


class TestIncidentList:
    async def test_list_incidents_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/incidents")
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_filter_by_severity(self, client: AsyncClient, db_session: AsyncSession):
        await seed_incident(db_session, severity="critical")
        await seed_incident(db_session, severity="low")

        resp = await client.get("/api/v1/incidents?severity=critical")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(i["severity"] == "critical" for i in items)

    async def test_filter_by_status(self, client: AsyncClient, db_session: AsyncSession):
        await seed_incident(db_session)  # creates as "open"
        resp = await client.get("/api/v1/incidents?status=open")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(i["status"] == "open" for i in items)


class TestIncidentGet:
    async def test_get_incident_success(self, client: AsyncClient, db_session: AsyncSession):
        inc = await seed_incident(db_session, severity="medium")
        resp = await client.get(f"/api/v1/incidents/{inc['id']}")
        assert resp.status_code == 200
        assert resp.json()["severity"] == "medium"

    async def test_get_incident_not_found(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/incidents/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestIncidentPatch:
    async def test_update_status(self, client: AsyncClient, db_session: AsyncSession):
        inc = await seed_incident(db_session)
        resp = await client.patch(
            f"/api/v1/incidents/{inc['id']}",
            json={"status": "investigating"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    async def test_resolve_sets_resolved_at(self, client: AsyncClient, db_session: AsyncSession):
        inc = await seed_incident(db_session)
        resp = await client.patch(
            f"/api/v1/incidents/{inc['id']}",
            json={"status": "resolved", "resolution": "Rolled back bad deployment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None
        assert data["resolution"] == "Rolled back bad deployment"

    async def test_patch_nonexistent_incident(self, client: AsyncClient):
        resp = await client.patch(
            f"/api/v1/incidents/{uuid.uuid4()}",
            json={"status": "closed"},
        )
        assert resp.status_code == 404
