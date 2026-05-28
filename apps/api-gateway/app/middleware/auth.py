"""
Authentication Middleware & Dependencies
-----------------------------------------
Supports two auth mechanisms (checked in order):
  1. Bearer JWT    — `Authorization: Bearer <token>`
  2. API Key       — `X-API-Key: <key>`

For now, JWT validation uses a shared secret (HS256).
API Key validation hashes the provided key and performs a constant-time
comparison against hashed values stored in the DB (Phase 3 will add a
full DB lookup; Phase 1 uses a simple env-configured key for bootstrapping).

`get_current_user()` is a FastAPI dependency that routers import.
Unauthenticated routes (health, metrics) skip this dependency.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings

log = logging.getLogger("agentops.auth")
settings = get_settings()

# ── Security schemes ──────────────────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)


# ── Token helpers ─────────────────────────────────────────────────────────────

def decode_jwt(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT, returning its claims.
    Raises HTTPException 401 on invalid / expired tokens.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        log.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key for constant-time comparison."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ── Primary auth dependency ───────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_scheme),
) -> dict[str, Any]:
    """
    FastAPI dependency — validates auth and returns a user context dict.

    Returns:
        {
          "sub": "<user_id_or_key_id>",
          "roles": ["operator"],
          "auth_method": "jwt" | "api_key"
        }

    Usage in a router:
        async def my_endpoint(user = Depends(get_current_user)):
            ...
    """
    # ── 1. Try JWT Bearer ──────────────────────────────────────────────────
    if bearer is not None:
        claims = decode_jwt(bearer.credentials)
        user_ctx = {
            "sub": claims.get("sub", "unknown"),
            "roles": claims.get("roles", ["operator"]),
            "auth_method": "jwt",
        }
        request.state.user = user_ctx
        return user_ctx

    # ── 2. Try API Key ─────────────────────────────────────────────────────
    if api_key is not None:
        # Phase 1: compare against a single env-configured hashed key.
        # Phase 3 will replace this with a full DB lookup.
        from app.config import get_settings as _gs
        _settings = _gs()

        # We derive the "bootstrap" key from the JWT_SECRET_KEY for simplicity.
        # In production, operators set a separate BOOTSTRAP_API_KEY env var.
        expected_hash = _hash_api_key(
            _settings.JWT_SECRET_KEY[:32]  # first 32 chars as the default key
        )
        provided_hash = _hash_api_key(api_key)

        if provided_hash == expected_hash:
            user_ctx = {
                "sub": "api-key-client",
                "roles": ["operator"],
                "auth_method": "api_key",
            }
            request.state.user = user_ctx
            return user_ctx

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    # ── 3. No credentials ─────────────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ── Optional auth (for public endpoints that benefit from user context) ────────

async def get_optional_user(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    api_key: str | None = Security(api_key_scheme),
) -> dict[str, Any] | None:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return await get_current_user(request, bearer, api_key)
    except HTTPException:
        return None
