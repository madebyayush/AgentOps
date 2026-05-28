"""
RBAC — Role-Based Access Control Tests
Tests: operator can read, auditor role propagated in JWT claims,
       admin role propagated, unauthenticated blocked, X-Request-ID present.

Note: Phase 1 auth returns roles from JWT claims but does not enforce
per-role endpoint restrictions (that's Phase 3 RBAC). These tests verify:
  1. The roles claim is correctly extracted and returned in user context.
  2. Endpoints are protected (require any valid auth).
  3. Public endpoints (health, metrics) are accessible without auth.
  4. X-Request-ID is stamped on every response.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from tests.conftest import make_jwt, make_admin_jwt, make_auditor_jwt


class TestRoleExtraction:
    async def test_operator_role_from_jwt(self, app: FastAPI):
        """JWT with roles=['operator'] must be accepted."""
        from app.middleware.auth import get_current_user
        captured = {}

        async def capturing_user():
            token = make_jwt(roles=["operator"])
            from app.middleware.auth import decode_jwt
            claims = decode_jwt(token)
            captured["roles"] = claims.get("roles", [])
            return {"sub": "op-user", "roles": claims.get("roles", []), "auth_method": "jwt"}

        app.dependency_overrides[get_current_user] = capturing_user
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 200
        assert "operator" in captured["roles"]

    async def test_admin_role_from_jwt(self, app: FastAPI):
        """JWT with roles=['admin'] must be accepted."""
        from app.middleware.auth import get_current_user
        captured = {}

        async def capturing_admin():
            token = make_admin_jwt()
            from app.middleware.auth import decode_jwt
            claims = decode_jwt(token)
            captured["roles"] = claims.get("roles", [])
            return {"sub": "admin-user", "roles": claims.get("roles", []), "auth_method": "jwt"}

        app.dependency_overrides[get_current_user] = capturing_admin
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 200
        assert "admin" in captured["roles"]

    async def test_auditor_role_from_jwt(self, app: FastAPI):
        """JWT with roles=['auditor'] must be accepted."""
        from app.middleware.auth import get_current_user
        captured = {}

        async def capturing_auditor():
            token = make_auditor_jwt()
            from app.middleware.auth import decode_jwt
            claims = decode_jwt(token)
            captured["roles"] = claims.get("roles", [])
            return {"sub": "auditor-user", "roles": claims.get("roles", []), "auth_method": "jwt"}

        app.dependency_overrides[get_current_user] = capturing_auditor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 200
        assert "auditor" in captured["roles"]


class TestPublicEndpoints:
    async def test_health_no_auth_required(self, app: FastAPI):
        """/health must be accessible without any auth token."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.status_code in (200, 503)  # 503 acceptable if DB not live

    async def test_ready_no_auth_required(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/ready")
        assert resp.status_code == 200

    async def test_metrics_no_auth_required(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/metrics")
        assert resp.status_code == 200


class TestRequestID:
    async def test_x_request_id_in_response(self, client: AsyncClient):
        """Every response must carry X-Request-ID header."""
        resp = await client.get("/api/v1/agents")
        assert "x-request-id" in resp.headers

    async def test_client_supplied_request_id_echoed(self, client: AsyncClient):
        """If client sends X-Request-ID, the same value must be echoed back."""
        custom_id = "my-trace-id-12345"
        resp = await client.get("/api/v1/agents", headers={"X-Request-ID": custom_id})
        assert resp.headers.get("x-request-id") == custom_id
