"""
CRUD — HITL endpoints
Tests: list pending, get detail, approve, reject, double-decision guard, missing reason.
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_agent, seed_run, seed_hitl


class TestHitlList:
    async def test_list_pending_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/hitl/pending")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_pending_shows_pending_only(self, client: AsyncClient, db_session: AsyncSession):
        agent = await seed_agent(db_session, name="hitl-list-agent")
        run = await seed_run(db_session, agent_id=uuid.UUID(agent["id"]))
        await seed_hitl(db_session, run_id=uuid.UUID(run["id"]))

        resp = await client.get("/api/v1/hitl/pending")
        assert resp.status_code == 200
        items = resp.json()
        assert all(item["status"] == "pending" for item in items)


class TestHitlGet:
    async def test_get_hitl_detail(self, client: AsyncClient, db_session: AsyncSession):
        agent = await seed_agent(db_session, name="hitl-get-agent")
        run = await seed_run(db_session, agent_id=uuid.UUID(agent["id"]))
        hitl = await seed_hitl(db_session, run_id=uuid.UUID(run["id"]))

        resp = await client.get(f"/api/v1/hitl/{hitl['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == hitl["id"]
        assert data["status"] == "pending"
        assert "action_description" in data

    async def test_get_hitl_not_found(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/hitl/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestHitlApprove:
    async def test_approve_hitl_request(self, client: AsyncClient, db_session: AsyncSession):
        agent = await seed_agent(db_session, name="hitl-approve-agent")
        run = await seed_run(db_session, agent_id=uuid.UUID(agent["id"]))
        hitl = await seed_hitl(db_session, run_id=uuid.UUID(run["id"]))

        resp = await client.post(
            f"/api/v1/hitl/{hitl['id']}/approve",
            json={"approved_by": "senior-engineer"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["approved_by"] == "senior-engineer"
        assert data["decided_at"] is not None

    async def test_double_approve_returns_409(self, client: AsyncClient, db_session: AsyncSession):
        agent = await seed_agent(db_session, name="hitl-double-agent")
        run = await seed_run(db_session, agent_id=uuid.UUID(agent["id"]))
        hitl = await seed_hitl(db_session, run_id=uuid.UUID(run["id"]))

        await client.post(
            f"/api/v1/hitl/{hitl['id']}/approve",
            json={"approved_by": "engineer"},
        )
        resp2 = await client.post(
            f"/api/v1/hitl/{hitl['id']}/approve",
            json={"approved_by": "engineer"},
        )
        assert resp2.status_code == 409


class TestHitlReject:
    async def test_reject_with_reason(self, client: AsyncClient, db_session: AsyncSession):
        agent = await seed_agent(db_session, name="hitl-reject-agent")
        run = await seed_run(db_session, agent_id=uuid.UUID(agent["id"]))
        hitl = await seed_hitl(db_session, run_id=uuid.UUID(run["id"]))

        resp = await client.post(
            f"/api/v1/hitl/{hitl['id']}/reject",
            json={"approved_by": "security-team", "rejection_reason": "Too risky"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == "Too risky"
