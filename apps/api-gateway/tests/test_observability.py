"""
Observability Endpoint Tests
Tests: /health response shape, /ready shape, /metrics Prometheus format,
       uptime_seconds is positive number.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from fastapi import FastAPI
from httpx import ASGITransport


class TestHealthEndpoint:
    async def test_health_returns_200_or_503(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.status_code in (200, 503)

    async def test_health_response_shape(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
        data = resp.json()
        assert "status" in data
        assert "service" in data
        assert "environment" in data
        assert "checks" in data
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    async def test_health_service_name(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/health")
        assert resp.json()["service"] == "agentops-api-gateway"


class TestReadyEndpoint:
    async def test_ready_returns_200(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/ready")
        assert resp.status_code == 200

    async def test_ready_response_shape(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/ready")
        data = resp.json()
        assert data["status"] == "ready"
        assert "service" in data
        assert "environment" in data


class TestMetricsEndpoint:
    async def test_metrics_returns_200(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/metrics")
        assert resp.status_code == 200

    async def test_metrics_is_prometheus_format(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/metrics")
        body = resp.text
        assert "# HELP" in body
        assert "# TYPE" in body
        assert "agentops_uptime_seconds" in body
        assert "agentops_build_info" in body

    async def test_metrics_content_type(self, app: FastAPI):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/metrics")
        # Prometheus expects text/plain
        assert "text/plain" in resp.headers.get("content-type", "")
