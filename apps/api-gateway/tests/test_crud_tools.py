"""
CRUD — Tools endpoints
Tests: list enabled tools, disabled tools excluded, get by ID, invoke existing/nonexistent.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_tool


class TestToolsList:
    async def test_list_tools_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/tools")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_only_enabled_tools(self, client: AsyncClient, db_session: AsyncSession):
        await seed_tool(db_session, name="enabled-tool", enabled=True)
        await seed_tool(db_session, name="disabled-tool", enabled=False)

        resp = await client.get("/api/v1/tools")
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "enabled-tool" in names
        assert "disabled-tool" not in names

    async def test_get_tool_by_id(self, client: AsyncClient, db_session: AsyncSession):
        tool = await seed_tool(db_session, name="fetch-me-tool")
        resp = await client.get(f"/api/v1/tools/{tool['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "fetch-me-tool"
        assert "tool_schema" in resp.json()

    async def test_get_disabled_tool_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        tool = await seed_tool(db_session, name="hidden-tool", enabled=False)
        resp = await client.get(f"/api/v1/tools/{tool['id']}")
        assert resp.status_code == 404

    async def test_get_tool_not_found(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/tools/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestToolInvoke:
    async def test_invoke_existing_tool(self, client: AsyncClient, db_session: AsyncSession):
        await seed_tool(db_session, name="invoke-tool")
        resp = await client.post(
            "/api/v1/tools/invoke",
            json={"tool_name": "invoke-tool", "arguments": {"q": "search term"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["tool_name"] == "invoke-tool"

    async def test_invoke_nonexistent_tool(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/tools/invoke",
            json={"tool_name": "ghost-tool", "arguments": {}},
        )
        assert resp.status_code == 404
