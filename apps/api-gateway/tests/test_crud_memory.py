"""
CRUD — Memory endpoints
Tests: namespace listing, create entry, list in namespace, delete, pagination.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import seed_agent


class TestMemoryCreate:
    async def test_create_memory_entry(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/memory",
            json={
                "namespace": "user-prefs",
                "content": "User prefers dark mode",
                "metadata": {"tag": "ui"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["namespace"] == "user-prefs"
        assert data["content"] == "User prefers dark mode"
        assert data["metadata_json"]["tag"] == "ui"
        assert "id" in data

    async def test_create_memory_missing_content(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/memory",
            json={"namespace": "test-ns"},
        )
        assert resp.status_code == 422

    async def test_create_memory_empty_content(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/memory",
            json={"namespace": "test-ns", "content": ""},
        )
        assert resp.status_code == 422


class TestMemoryList:
    async def test_list_namespaces_empty(self, client: AsyncClient):
        resp = await client.get("/api/v1/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "namespaces" in data
        assert "total" in data

    async def test_list_namespace_entries(self, client: AsyncClient):
        # Seed two entries in the same namespace
        await client.post(
            "/api/v1/memory", json={"namespace": "ns-list-test", "content": "Entry 1"}
        )
        await client.post(
            "/api/v1/memory", json={"namespace": "ns-list-test", "content": "Entry 2"}
        )

        resp = await client.get("/api/v1/memory/ns-list-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    async def test_list_empty_namespace(self, client: AsyncClient):
        resp = await client.get("/api/v1/memory/nonexistent-ns")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestMemoryDelete:
    async def test_delete_memory_entry(self, client: AsyncClient):
        # Create then delete
        create_resp = await client.post(
            "/api/v1/memory",
            json={"namespace": "delete-ns", "content": "To be deleted"},
        )
        entry_id = create_resp.json()["id"]

        del_resp = await client.delete(f"/api/v1/memory/delete-ns/{entry_id}")
        assert del_resp.status_code == 204

    async def test_delete_nonexistent_entry(self, client: AsyncClient):
        resp = await client.delete(f"/api/v1/memory/some-ns/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_delete_wrong_namespace(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/memory",
            json={"namespace": "real-ns", "content": "Data"},
        )
        entry_id = create_resp.json()["id"]
        # Try to delete from wrong namespace
        resp = await client.delete(f"/api/v1/memory/wrong-ns/{entry_id}")
        assert resp.status_code == 404
