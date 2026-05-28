"""
CRUD — Workflow endpoints
Tests: create, duplicate, list pagination, get, execute (real+dry-run), delete.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_workflow

SAMPLE_GRAPH = {"nodes": [{"id": "n1", "agent": "researcher"}], "edges": []}


class TestWorkflowCreate:
    async def test_create_workflow_success(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/workflows",
            json={"name": "research-pipeline", "graph_json": SAMPLE_GRAPH},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "research-pipeline"
        assert data["version"] == 1
        assert data["graph_json"] == SAMPLE_GRAPH

    async def test_create_workflow_with_description(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/workflows",
            json={
                "name": "described-pipeline",
                "description": "My workflow",
                "graph_json": SAMPLE_GRAPH,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["description"] == "My workflow"

    async def test_create_workflow_duplicate_name(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await seed_workflow(db_session, name="dup-flow")
        resp = await client.post("/api/v1/workflows", json={"name": "dup-flow", "graph_json": {}})
        assert resp.status_code == 409

    async def test_create_workflow_missing_graph(self, client: AsyncClient):
        resp = await client.post("/api/v1/workflows", json={"name": "no-graph-flow"})
        assert resp.status_code == 422


class TestWorkflowList:
    async def test_list_workflows_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_list_workflows_pagination(self, client: AsyncClient, db_session: AsyncSession):
        for i in range(4):
            await seed_workflow(db_session, name=f"flow-page-{i}")
        resp = await client.get("/api/v1/workflows?page_size=2")
        assert resp.status_code == 200
        assert resp.json()["page_size"] == 2


class TestWorkflowGet:
    async def test_get_workflow_success(self, client: AsyncClient, db_session: AsyncSession):
        wf = await seed_workflow(db_session, name="get-flow")
        resp = await client.get(f"/api/v1/workflows/{wf['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-flow"

    async def test_get_workflow_not_found(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/workflows/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestWorkflowExecute:
    async def test_execute_workflow(self, client: AsyncClient, db_session: AsyncSession):
        wf = await seed_workflow(db_session, name="exec-flow")
        resp = await client.post(f"/api/v1/workflows/{wf['id']}/execute", json={"inputs": {}})
        assert resp.status_code == 202
        assert resp.json()["status"] == "dispatched"

    async def test_execute_workflow_dry_run(self, client: AsyncClient, db_session: AsyncSession):
        wf = await seed_workflow(db_session, name="dry-flow")
        resp = await client.post(
            f"/api/v1/workflows/{wf['id']}/execute",
            json={"inputs": {}, "dry_run": True},
        )
        assert resp.status_code == 202
        assert "dry_run" in resp.json()["status"]

    async def test_execute_nonexistent_workflow(self, client: AsyncClient):
        resp = await client.post(f"/api/v1/workflows/{uuid.uuid4()}/execute", json={"inputs": {}})
        assert resp.status_code == 404


class TestWorkflowDelete:
    async def test_delete_workflow(self, client: AsyncClient, db_session: AsyncSession):
        wf = await seed_workflow(db_session, name="delete-flow")
        resp = await client.delete(f"/api/v1/workflows/{wf['id']}")
        assert resp.status_code == 204

    async def test_delete_nonexistent_workflow(self, client: AsyncClient):
        resp = await client.delete(f"/api/v1/workflows/{uuid.uuid4()}")
        assert resp.status_code == 404
