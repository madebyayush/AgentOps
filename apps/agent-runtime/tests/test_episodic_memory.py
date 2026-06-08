"""
Tests for Episodic Memory (Step 3.2)
======================================
Tests: push/load, LTRIM cap, Redis Streams log_event/get_events,
       session isolation, oldest-dropped policy.

Uses fakeredis for all Redis operations — no live Redis required.
"""

from __future__ import annotations

import json
import pytest
import fakeredis.aioredis as fake_aioredis

from agent.memory.episodic import EpisodicMemory, DEFAULT_MAX_INTERACTIONS

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_redis():
    return fake_aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def episodic(fake_redis):
    return EpisodicMemory(redis=fake_redis, agent_id="test-agent", max_interactions=5)


# ── push / load tests ─────────────────────────────────────────────────────────


class TestEpisodicPushLoad:
    async def test_push_and_load_single(self, episodic):
        await episodic.push("sess-1", {"role": "user", "content": "Hello"})
        interactions = await episodic.load("sess-1")
        assert len(interactions) == 1
        assert interactions[0]["content"] == "Hello"

    async def test_push_multiple_newest_first(self, episodic):
        await episodic.push("sess-2", {"role": "user", "content": "First"})
        await episodic.push("sess-2", {"role": "assistant", "content": "Second"})
        await episodic.push("sess-2", {"role": "user", "content": "Third"})
        interactions = await episodic.load("sess-2")
        # LPUSH stores newest first
        assert interactions[0]["content"] == "Third"
        assert interactions[1]["content"] == "Second"
        assert interactions[2]["content"] == "First"

    async def test_load_respects_limit(self, episodic):
        for i in range(5):
            await episodic.push("sess-3", {"role": "user", "content": f"msg-{i}"})
        result = await episodic.load("sess-3", limit=3)
        assert len(result) == 3

    async def test_load_empty_session(self, episodic):
        result = await episodic.load("nonexistent-session")
        assert result == []

    async def test_timestamp_auto_added(self, episodic):
        await episodic.push("sess-4", {"role": "user", "content": "timestamped"})
        result = await episodic.load("sess-4")
        assert "timestamp" in result[0]

    async def test_run_id_injected(self, episodic):
        await episodic.push("sess-5", {"role": "user", "content": "msg"}, run_id="run-42")
        result = await episodic.load("sess-5")
        assert result[0]["run_id"] == "run-42"


# ── LTRIM enforcement tests ───────────────────────────────────────────────────


class TestEpisodicLTRIM:
    async def test_ltrim_enforces_max_interactions(self, episodic):
        """Push 10 items into an episodic with max_interactions=5; only 5 survive."""
        for i in range(10):
            await episodic.push("sess-trim", {"role": "user", "content": f"msg-{i}"})
        result = await episodic.load("sess-trim")
        assert len(result) == 5

    async def test_oldest_dropped_not_newest(self, episodic):
        """After cap, the NEWEST messages are retained, oldest are dropped."""
        for i in range(7):  # max is 5
            await episodic.push("sess-drop", {"role": "user", "content": f"msg-{i}"})
        result = await episodic.load("sess-drop")
        contents = [r["content"] for r in result]
        # Newest 5 (msg-6 through msg-2) should survive; msg-0 and msg-1 dropped
        assert "msg-6" in contents
        assert "msg-0" not in contents

    async def test_clear_removes_all(self, episodic):
        await episodic.push("sess-clear", {"role": "user", "content": "goodbye"})
        await episodic.clear("sess-clear")
        result = await episodic.load("sess-clear")
        assert result == []


# ── Session isolation tests ───────────────────────────────────────────────────


class TestEpisodicSessionIsolation:
    async def test_different_sessions_isolated(self, episodic):
        await episodic.push("sess-A", {"role": "user", "content": "In A"})
        await episodic.push("sess-B", {"role": "user", "content": "In B"})

        result_a = await episodic.load("sess-A")
        result_b = await episodic.load("sess-B")

        assert all(r["content"] == "In A" for r in result_a)
        assert all(r["content"] == "In B" for r in result_b)

    async def test_clear_one_session_not_other(self, episodic):
        await episodic.push("sess-X", {"role": "user", "content": "keep"})
        await episodic.push("sess-Y", {"role": "user", "content": "delete"})
        await episodic.clear("sess-Y")

        assert len(await episodic.load("sess-X")) == 1
        assert len(await episodic.load("sess-Y")) == 0


# ── Redis Streams tests ───────────────────────────────────────────────────────


class TestEpisodicStreams:
    async def test_log_event_returns_entry_id(self, episodic):
        entry_id = await episodic.log_event(
            "run-1",
            {"event_type": "agent.act.complete", "payload": {"tool": "web_search"}},
        )
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    async def test_get_events_round_trip(self, episodic):
        await episodic.log_event(
            "run-2",
            {"event_type": "agent.think.start", "payload": {"step": 1}},
        )
        events = await episodic.get_events(run_id="run-2", count=10)
        assert len(events) >= 1
        assert events[0]["event_type"] == "agent.think.start"

    async def test_get_events_filters_by_run_id(self, episodic):
        await episodic.log_event("run-A", {"event_type": "ev.A", "payload": {}})
        await episodic.log_event("run-B", {"event_type": "ev.B", "payload": {}})

        events_a = await episodic.get_events(run_id="run-A", count=50)
        assert all(e["run_id"] == "run-A" for e in events_a)

    async def test_get_events_payload_parsed(self, episodic):
        await episodic.log_event(
            "run-3",
            {"event_type": "agent.act.complete", "payload": {"key": "value", "num": 42}},
        )
        events = await episodic.get_events(run_id="run-3", count=10)
        assert events
        payload = events[0]["payload"]
        assert isinstance(payload, dict)
        assert payload.get("key") == "value"
        assert payload.get("num") == 42

    async def test_multiple_events_ordered(self, episodic):
        for i in range(3):
            await episodic.log_event("run-4", {"event_type": f"event-{i}", "payload": {}})
        events = await episodic.get_events(run_id="run-4", count=10)
        types = [e["event_type"] for e in events]
        # Events should appear in insertion order (XRANGE returns oldest-first)
        assert types == ["event-0", "event-1", "event-2"]
