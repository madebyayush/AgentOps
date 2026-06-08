"""
Tests for Procedural Memory (Step 3.4)
========================================
Tests: register_tool, record_call, get_stats, list_stats,
       auto_disable_check (error_rate > 30%), alert on disable,
       minimum sample size guard.

Uses the in-memory fallback backend (POSTGRES_URL not set).
Postgres tests run in CI via the real DB service.
"""

from __future__ import annotations

import os
import pytest

from agent.memory.procedural import (
    ProceduralMemory,
    ToolStats,
    ERROR_RATE_THRESHOLD,
    _InMemoryProceduralStore,
)

# ── Fake tool fixture ─────────────────────────────────────────────────────────


class FakeTool:
    def __init__(self, name: str, description: str = "A tool"):
        self.name = name
        self.description = description
        self.schema = {"type": "object", "properties": {}}


@pytest.fixture
def pm():
    """ProceduralMemory with in-memory backend (no POSTGRES_URL)."""
    mem = ProceduralMemory(postgres_url=None)
    return mem


@pytest.fixture
async def pm_initialized(pm):
    await pm.initialize()
    return pm


# ── register_tool tests ───────────────────────────────────────────────────────


class TestRegisterTool:
    async def test_register_creates_entry(self, pm_initialized):
        tool = FakeTool("web_search")
        await pm_initialized.register_tool(tool)
        stats = await pm_initialized.get_stats("web_search")
        assert stats is not None
        assert stats.tool_name == "web_search"

    async def test_register_idempotent(self, pm_initialized):
        tool = FakeTool("web_search", "first description")
        await pm_initialized.register_tool(tool)
        tool.description = "updated description"
        await pm_initialized.register_tool(tool)  # upsert
        stats = await pm_initialized.get_stats("web_search")
        assert stats is not None  # should still exist exactly once

    async def test_register_multiple_tools(self, pm_initialized):
        tools = [FakeTool(f"tool_{i}") for i in range(5)]
        for t in tools:
            await pm_initialized.register_tool(t)
        all_stats = await pm_initialized.list_stats()
        names = {s.tool_name for s in all_stats}
        for t in tools:
            assert t.name in names

    async def test_get_stats_unregistered_returns_none(self, pm_initialized):
        stats = await pm_initialized.get_stats("nonexistent_tool")
        assert stats is None


# ── record_call tests ─────────────────────────────────────────────────────────


class TestRecordCall:
    async def test_record_success_increments_counters(self, pm_initialized):
        tool = FakeTool("code_runner")
        await pm_initialized.register_tool(tool)
        await pm_initialized.record_call("code_runner", success=True, latency_ms=100.0)
        stats = await pm_initialized.get_stats("code_runner")
        assert stats.total_calls == 1
        assert stats.success_calls == 1
        assert stats.error_calls == 0

    async def test_record_failure_increments_error_counter(self, pm_initialized):
        tool = FakeTool("sql_runner")
        await pm_initialized.register_tool(tool)
        await pm_initialized.record_call("sql_runner", success=False, latency_ms=50.0)
        stats = await pm_initialized.get_stats("sql_runner")
        assert stats.error_calls == 1
        assert stats.success_calls == 0

    async def test_latency_accumulates(self, pm_initialized):
        tool = FakeTool("file_reader")
        await pm_initialized.register_tool(tool)
        await pm_initialized.record_call("file_reader", success=True, latency_ms=100.0)
        await pm_initialized.record_call("file_reader", success=True, latency_ms=200.0)
        stats = await pm_initialized.get_stats("file_reader")
        assert stats.total_latency_ms == 300.0
        assert abs(stats.avg_latency_ms - 150.0) < 1e-6

    async def test_multiple_calls_accumulate(self, pm_initialized):
        tool = FakeTool("multi_tool")
        await pm_initialized.register_tool(tool)
        for i in range(10):
            await pm_initialized.record_call("multi_tool", success=(i % 2 == 0), latency_ms=10.0)
        stats = await pm_initialized.get_stats("multi_tool")
        assert stats.total_calls == 10
        assert stats.success_calls == 5
        assert stats.error_calls == 5

    async def test_unknown_tool_does_not_raise(self, pm_initialized):
        """record_call on unregistered tool should log warning, not crash."""
        await pm_initialized.record_call("ghost_tool", success=True, latency_ms=10.0)


# ── get_stats / derived metrics tests ────────────────────────────────────────


class TestGetStats:
    async def test_success_rate_calculated(self, pm_initialized):
        tool = FakeTool("rate_tool")
        await pm_initialized.register_tool(tool)
        for _ in range(8):
            await pm_initialized.record_call("rate_tool", success=True, latency_ms=10.0)
        for _ in range(2):
            await pm_initialized.record_call("rate_tool", success=False, latency_ms=10.0)
        stats = await pm_initialized.get_stats("rate_tool")
        assert abs(stats.success_rate - 0.8) < 1e-6
        assert abs(stats.error_rate - 0.2) < 1e-6

    async def test_zero_calls_no_division(self, pm_initialized):
        tool = FakeTool("zero_tool")
        await pm_initialized.register_tool(tool)
        stats = await pm_initialized.get_stats("zero_tool")
        assert stats.total_calls == 0
        assert stats.success_rate == 0.0
        assert stats.error_rate == 0.0
        assert stats.avg_latency_ms == 0.0


# ── auto_disable_check tests ──────────────────────────────────────────────────


class TestAutoDisableCheck:
    async def _register_and_fill(self, pm, name, success_n, error_n, latency=10.0):
        await pm.register_tool(FakeTool(name))
        for _ in range(success_n):
            await pm.record_call(name, success=True, latency_ms=latency)
        for _ in range(error_n):
            await pm.record_call(name, success=False, latency_ms=latency)

    async def test_high_error_rate_disables_tool(self, pm_initialized):
        """Tool with >30% error rate and ≥10 calls should be disabled."""
        # 4 successes, 7 errors = 11 total, 63.6% error rate
        await self._register_and_fill(pm_initialized, "bad_tool", success_n=4, error_n=7)
        disabled = await pm_initialized.auto_disable_check()
        assert "bad_tool" in disabled
        stats = await pm_initialized.get_stats("bad_tool")
        assert stats.enabled is False

    async def test_low_error_rate_not_disabled(self, pm_initialized):
        """Tool with <30% error rate should stay enabled."""
        # 9 successes, 1 error = 10 total, 10% error rate
        await self._register_and_fill(pm_initialized, "good_tool", success_n=9, error_n=1)
        disabled = await pm_initialized.auto_disable_check()
        assert "good_tool" not in disabled
        stats = await pm_initialized.get_stats("good_tool")
        assert stats.enabled is True

    async def test_minimum_sample_size_guard(self, pm_initialized):
        """Tool with <10 calls should NOT be disabled even at 100% error rate."""
        await self._register_and_fill(pm_initialized, "new_tool", success_n=0, error_n=9)
        disabled = await pm_initialized.auto_disable_check()
        assert "new_tool" not in disabled
        stats = await pm_initialized.get_stats("new_tool")
        assert stats.enabled is True

    async def test_exact_threshold_not_disabled(self, pm_initialized):
        """Error rate exactly at threshold (30%) should NOT disable the tool."""
        # 7 successes, 3 errors = 10 total, exactly 30%
        await self._register_and_fill(pm_initialized, "edge_tool", success_n=7, error_n=3)
        disabled = await pm_initialized.auto_disable_check()
        assert "edge_tool" not in disabled

    async def test_already_disabled_not_returned_again(self, pm_initialized):
        """Once disabled, re-running auto_disable_check should not return it again."""
        await self._register_and_fill(pm_initialized, "already_bad", success_n=2, error_n=9)
        first_run = await pm_initialized.auto_disable_check()
        assert "already_bad" in first_run
        second_run = await pm_initialized.auto_disable_check()
        assert "already_bad" not in second_run  # already disabled

    async def test_auto_disable_check_returns_only_newly_disabled(self, pm_initialized):
        """Should return only tools that were NEWLY disabled in this call."""
        await self._register_and_fill(pm_initialized, "will_fail_1", success_n=1, error_n=10)
        await self._register_and_fill(pm_initialized, "will_fail_2", success_n=1, error_n=10)
        await self._register_and_fill(pm_initialized, "will_pass", success_n=10, error_n=0)

        disabled = await pm_initialized.auto_disable_check()
        assert "will_fail_1" in disabled
        assert "will_fail_2" in disabled
        assert "will_pass" not in disabled


# ── PostgreSQL integration marker (runs only in CI with POSTGRES_URL set) ────


@pytest.mark.skipif(
    not os.getenv("POSTGRES_URL"),
    reason="PostgreSQL integration test — requires POSTGRES_URL env var",
)
class TestProceduralMemoryPostgres:
    @pytest.fixture
    async def pg_pm(self):
        pm = ProceduralMemory(postgres_url=os.getenv("POSTGRES_URL"))
        await pm.initialize()
        yield pm
        await pm.close()

    async def test_register_and_get_stats_postgres(self, pg_pm):
        tool = FakeTool("pg_test_tool")
        await pg_pm.register_tool(tool)
        stats = await pg_pm.get_stats("pg_test_tool")
        assert stats is not None
        assert stats.tool_name == "pg_test_tool"

    async def test_record_call_aggregates_correctly_postgres(self, pg_pm):
        tool = FakeTool("pg_agg_tool")
        await pg_pm.register_tool(tool)
        for _ in range(5):
            await pg_pm.record_call("pg_agg_tool", success=True, latency_ms=50.0)
        for _ in range(2):
            await pg_pm.record_call("pg_agg_tool", success=False, latency_ms=100.0)
        stats = await pg_pm.get_stats("pg_agg_tool")
        assert stats.total_calls == 7
        assert stats.success_calls == 5
        assert stats.error_calls == 2
        assert abs(stats.total_latency_ms - 450.0) < 1.0

    async def test_auto_disable_check_postgres(self, pg_pm):
        tool = FakeTool("pg_bad_tool")
        await pg_pm.register_tool(tool)
        for _ in range(3):
            await pg_pm.record_call("pg_bad_tool", success=True, latency_ms=10.0)
        for _ in range(8):
            await pg_pm.record_call("pg_bad_tool", success=False, latency_ms=10.0)

        disabled = await pg_pm.auto_disable_check()
        assert "pg_bad_tool" in disabled
        stats = await pg_pm.get_stats("pg_bad_tool")
        assert stats.enabled is False
