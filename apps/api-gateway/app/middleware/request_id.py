"""
Request ID Middleware
---------------------
Attaches a unique UUID to every request and propagates it:
  - In `request.state.request_id` for downstream handlers and logs
  - In the `X-Request-ID` response header so clients can correlate logs
  - Falls back to a client-supplied `X-Request-ID` header if present
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Honour a client-supplied ID (e.g. from a load balancer) or generate a new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
