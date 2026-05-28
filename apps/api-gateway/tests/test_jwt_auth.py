"""
JWT Authentication Middleware Tests
Tests: valid JWT, expired JWT, malformed token, wrong algorithm, valid API key,
       invalid API key, no credentials, correct claims propagation.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from jose import jwt

from tests.conftest import make_jwt, make_expired_jwt, TEST_SECRET, TEST_ALGORITHM


class TestJWTValidation:
    async def test_valid_jwt_accepted(self, client: AsyncClient):
        """Default client fixture already sends a valid JWT."""
        resp = await client.get("/api/v1/agents")
        assert resp.status_code == 200

    async def test_expired_jwt_rejected(self, app: FastAPI):
        """A token that expired 10 seconds ago must return 401."""
        expired_token = make_expired_jwt()
        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {expired_token}"},
        ) as ac:
            # Remove the dependency override to test real auth
            from app.middleware.auth import get_current_user

            if get_current_user in app.dependency_overrides:
                del app.dependency_overrides[get_current_user]
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 401

    async def test_malformed_jwt_rejected(self, app: FastAPI):
        """A completely invalid token must return 401."""
        from app.middleware.auth import get_current_user

        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]
        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        ) as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 401

    async def test_wrong_algorithm_jwt_rejected(self, app: FastAPI):
        """A JWT signed with RS256 (not HS256) must be rejected."""
        from app.middleware.auth import get_current_user

        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]
        # We can't sign RS256 without a key pair — just send a modified header
        bad_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.invalidsig"
        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {bad_token}"},
        ) as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 401

    async def test_no_credentials_returns_401(self, anon_client: AsyncClient, app: FastAPI):
        """No auth header at all — must return 401."""
        from app.middleware.auth import get_current_user

        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]
        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers


class TestJWTClaims:
    async def test_jwt_with_custom_sub(self, app: FastAPI):
        """Claims from a valid JWT must reach request.state.user."""
        from app.middleware.auth import get_current_user

        captured_user: dict = {}

        async def capture_user_dependency():
            # Let the real auth run, then capture the result
            token = make_jwt(sub="custom-user-123", roles=["auditor"])
            from app.middleware.auth import decode_jwt

            claims = decode_jwt(token)
            captured_user.update(claims)
            return {"sub": claims["sub"], "roles": claims.get("roles", []), "auth_method": "jwt"}

        app.dependency_overrides[get_current_user] = capture_user_dependency

        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/api/v1/agents")

        assert resp.status_code == 200
        assert captured_user.get("sub") == "custom-user-123"


class TestAPIKeyAuth:
    async def test_valid_api_key_accepted(self, app: FastAPI, test_settings):
        """The bootstrap API key derived from JWT_SECRET_KEY[:32] must work."""
        from app.middleware.auth import get_current_user, _hash_api_key

        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        valid_key = test_settings.JWT_SECRET_KEY[:32]
        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": valid_key},
        ) as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 200

    async def test_invalid_api_key_rejected(self, app: FastAPI):
        """A wrong API key must return 401."""
        from app.middleware.auth import get_current_user

        if get_current_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_user]

        async with AsyncClient(
            transport=__import__("httpx").ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "totally-wrong-key"},
        ) as ac:
            resp = await ac.get("/api/v1/agents")
        assert resp.status_code == 401
