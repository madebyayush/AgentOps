"""
CRUD — Agent endpoints
Tests: create, list, get, duplicate name, run enqueue, status, 404 paths.
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_agent, seed_run


class TestAgentCreate:
    async def test_create_agent_success(self, client: AsyncClient):
        resp = await client.post("/api/v1/agents", json={"name": "coder-bot", "type": "coder"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "coder-bot"
        assert data["type"] == "coder"
        assert "id" in data
        assert "created_at" in data

    async def test_create_agent_with_config(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/agents",
            json={"name": "researcher-bot", "type": "researcher", "config_json": {"model": "claude-3-5"}},
        )
        assert resp.status_code == 201
        assert resp.json()["config_json"]["model"] == "claude-3-5"

    async def test_create_agent_duplicate_name(self, client: AsyncClient, db_session: AsyncSession):
        await seed_agent(db_session, name="unique-bot")
        resp = await client.post("/api/v1/agents", json={"name": "unique-bot", "type": "generic"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    async def test_create_agent_missing_name(self, client: AsyncClient):
        resp = await client.post("/api/v1/agents", json={"type": "coder"})
        assert resp.status_code == 422  # Pydantic validation error

    async def test_create_agent_name_with_spaces_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v1/agents", json={"name": "bad name here", "type": "coder"})
        assert resp.status_code == 422


class TestAgentList:
    async def test_list_agents_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["page"] == 1

    async def test_list_agents_pagination(self, client: AsyncClient, db_session: AsyncSession):
        for i in range(5):
            await seed_agent(db_session, name=f"paginate-bot-{i}")
        resp = await client.get("/api/v1/agents?page=1&page_size=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page_size"] == 3
        assert data["total"] >= 5


class TestAgentGet:
    async def test_get_agent_success(self, client: AsyncClient, db_session: AsyncSession):
        a = await seed_agent(db_session, name="get-me-bot")
        resp = await client.get(f"/api/v1/agents/{a['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-me-bot"

    async def test_get_agent_not_found(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/agents/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestAgentRun:
    async def test_run_enqueue_success(self, client: AsyncClient, db_session: AsyncSession):
        a = await seed_agent(db_session, name="run-me-bot")
        resp = await client.post(
            f"/api/v1/agents/{a['id']}/run",
            json={"prompt": "Analyze this dataset", "max_steps": 10},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert "run_id" in data

    async def test_run_enqueue_agent_not_found(self, client: AsyncClient):
        resp = await client.post(
            f"/api/v1/agents/{uuid.uuid4()}/run",
            json={"prompt": "do something"},
        )
        assert resp.status_code == 404

    async def test_get_status_no_runs(self, client: AsyncClient, db_session: AsyncSession):
        a = await seed_agent(db_session, name="status-bot")
        resp = await client.get(f"/api/v1/agents/{a['id']}/status")
        assert resp.status_code == 404
