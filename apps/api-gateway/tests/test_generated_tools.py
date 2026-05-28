"""
Generated Pytest Suite for Tools Router
=============================================
This suite covers standard routing integration, security blocks,
invalid payloads, and operational CRUD patterns.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_tool


@pytest.mark.asyncio
class TestToolsRouter:

    async def test_list_tools_success(self, client: AsyncClient, db_session: AsyncSession):
        """
        Success track for GET
        """
        await seed_tool(db_session, name="test-tool-list", enabled=True)
        url = "/api/v1/tools"
        resp = await client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert any(t["name"] == "test-tool-list" for t in data)

    async def test_list_tools_unauthorized(self, anon_client: AsyncClient, app: FastAPI):
        """
        Unauthenticated block ensuring API token compliance
        """
        # Remove the dependency override to test real auth
        from app.middleware.auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        url = "/api/v1/tools"
        resp = await anon_client.get(url)
        assert resp.status_code == 401

    async def test_get_tool_success(self, client: AsyncClient, db_session: AsyncSession):
        """
        Success track for GET /{tool_id}
        """
        tool = await seed_tool(db_session, name="get-tool-test", enabled=True)
        url = f"/api/v1/tools/{tool['id']}"
        resp = await client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["name"] == "get-tool-test"

    async def test_get_tool_unauthorized(self, anon_client: AsyncClient, app: FastAPI, db_session: AsyncSession):
        """
        Unauthenticated block ensuring API token compliance
        """
        # Remove the dependency override to test real auth
        from app.middleware.auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        tool = await seed_tool(db_session, name="get-tool-unauth", enabled=True)
        url = f"/api/v1/tools/{tool['id']}"
        resp = await anon_client.get(url)
        assert resp.status_code == 401

    async def test_invoke_tool_success(self, client: AsyncClient, db_session: AsyncSession):
        """
        Success track for POST /invoke
        """
        await seed_tool(db_session, name="invoke-tool-test", enabled=True)
        url = "/api/v1/tools/invoke"
        payload = {"tool_name": "invoke-tool-test", "arguments": {"param": "value"}}
        resp = await client.post(url, json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["success"] is True
        assert data["tool_name"] == "invoke-tool-test"

    async def test_invoke_tool_unauthorized(self, anon_client: AsyncClient, app: FastAPI, db_session: AsyncSession):
        """
        Unauthenticated block ensuring API token compliance
        """
        # Remove the dependency override to test real auth
        from app.middleware.auth import get_current_user
        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        await seed_tool(db_session, name="invoke-tool-unauth", enabled=True)
        url = "/api/v1/tools/invoke"
        payload = {"tool_name": "invoke-tool-unauth", "arguments": {}}
        resp = await anon_client.post(url, json=payload)
        assert resp.status_code == 401

    async def test_invoke_tool_invalid_payload(self, client: AsyncClient):
        """
        Malformed body triggers standard 422 Unprocessable entity response
        """
        url = "/api/v1/tools/invoke"
        invalid_payload = {"invalid_key_trigger": True}
        resp = await client.post(url, json=invalid_payload)
        assert resp.status_code == 422
