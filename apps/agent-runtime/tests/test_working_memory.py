"""
Tests for Working Memory (Step 3.3)
=====================================
Tests: save/load round-trip, TTL set, delete, missing key returns None,
       state mutation does not affect stored snapshot.

Uses fakeredis — no live Redis required.
"""

from __future__ import annotations

import pytest
import fakeredis.aioredis as fake_aioredis

from agent.memory.working import WorkingMemory, DEFAULT_TTL

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    return fake_aioredis.FakeRedis(decode_responses=False)  # bytes for orjson compat


@pytest.fixture
def wm(fake_redis):
    return WorkingMemory(redis=fake_redis, ttl=300)


def _sample_state(run_id: str = "run-1") -> dict:
    return {
        "run_id": run_id,
        "agent_name": "research-agent",
        "session_id": "sess-abc",
        "task": "Analyse Q1 revenue",
        "plan": ["Step A", "Step B"],
        "current_step": 1,
        "tool_calls": [
            {
                "tool_name": "web_search",
                "arguments": {"query": "Q1 revenue"},
                "result": "$4.2B",
                "error": None,
                "duration_ms": 250.0,
                "timestamp": "2026-06-01T00:00:00Z",
            }
        ],
        "observations": ["Revenue is $4.2B"],
        "memory_context": ["Prior context"],
        "memory_citations": ["chunk-001"],
        "reflection": "CONTINUE: all checks passed",
        "retry_count": 0,
        "hitl_pending": False,
        "hitl_request_id": None,
        "error": None,
        "final_output": None,
    }


# ── save / load round-trip ────────────────────────────────────────────────────


class TestWorkingMemorySaveLoad:
    async def test_save_then_load(self, wm):
        state = _sample_state("run-save-load")
        await wm.save_state("run-save-load", state)
        loaded = await wm.load_state("run-save-load")
        assert loaded is not None
        assert loaded["run_id"] == "run-save-load"
        assert loaded["task"] == "Analyse Q1 revenue"

    async def test_nested_structures_preserved(self, wm):
        state = _sample_state("run-nested")
        await wm.save_state("run-nested", state)
        loaded = await wm.load_state("run-nested")
        assert loaded["tool_calls"][0]["tool_name"] == "web_search"
        assert loaded["plan"] == ["Step A", "Step B"]
        assert loaded["memory_citations"] == ["chunk-001"]

    async def test_boolean_fields_preserved(self, wm):
        state = _sample_state("run-bool")
        state["hitl_pending"] = True
        await wm.save_state("run-bool", state)
        loaded = await wm.load_state("run-bool")
        assert loaded["hitl_pending"] is True

    async def test_none_fields_preserved(self, wm):
        state = _sample_state("run-none")
        await wm.save_state("run-none", state)
        loaded = await wm.load_state("run-none")
        assert loaded["error"] is None
        assert loaded["final_output"] is None

    async def test_overwrite_updates_snapshot(self, wm):
        state = _sample_state("run-overwrite")
        await wm.save_state("run-overwrite", state)
        state["current_step"] = 2
        await wm.save_state("run-overwrite", state)
        loaded = await wm.load_state("run-overwrite")
        assert loaded["current_step"] == 2


# ── TTL tests ─────────────────────────────────────────────────────────────────


class TestWorkingMemoryTTL:
    async def test_ttl_is_set_on_save(self, wm):
        state = _sample_state("run-ttl")
        await wm.save_state("run-ttl", state)
        ttl = await wm.get_ttl("run-ttl")
        # TTL should be >0 and ≤ configured 300s
        assert 0 < ttl <= 300

    async def test_missing_key_ttl_is_minus_two(self, wm):
        ttl = await wm.get_ttl("run-does-not-exist")
        assert ttl == -2


# ── delete / missing key tests ────────────────────────────────────────────────


class TestWorkingMemoryDelete:
    async def test_delete_removes_key(self, wm):
        state = _sample_state("run-del")
        await wm.save_state("run-del", state)
        await wm.delete_state("run-del")
        loaded = await wm.load_state("run-del")
        assert loaded is None

    async def test_load_missing_key_returns_none(self, wm):
        loaded = await wm.load_state("run-does-not-exist")
        assert loaded is None

    async def test_delete_idempotent(self, wm):
        """Deleting a non-existent key should not raise."""
        await wm.delete_state("run-never-existed")  # should not raise


# ── Isolation between runs ────────────────────────────────────────────────────


class TestWorkingMemoryIsolation:
    async def test_different_run_ids_isolated(self, wm):
        state_a = _sample_state("run-iso-A")
        state_b = _sample_state("run-iso-B")
        state_b["task"] = "Different task"

        await wm.save_state("run-iso-A", state_a)
        await wm.save_state("run-iso-B", state_b)

        loaded_a = await wm.load_state("run-iso-A")
        loaded_b = await wm.load_state("run-iso-B")

        assert loaded_a["task"] == "Analyse Q1 revenue"
        assert loaded_b["task"] == "Different task"
