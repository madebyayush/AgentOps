"""
AgentOps — Episodic Memory (Short-term, Redis)
===============================================
Stores the last N interactions per agent session using Redis data structures.

Key schema:
    nexus:episodic:{agent_id}:{session_id}  → Redis List  (LPUSH / LTRIM / LRANGE)
    nexus:stream:{agent_id}                 → Redis Stream (XADD / XRANGE)

Interaction format (stored as JSON in list items)::
    {
        "role"        : "user" | "assistant" | "tool",
        "content"     : str,
        "tool_name"   : str | null,
        "timestamp"   : ISO-8601 UTC,
        "run_id"      : str,
    }

Stream event format (stored as flat dict in stream fields)::
    {
        "event_type"  : str,
        "run_id"      : str,
        "payload"     : JSON-encoded str,
        "timestamp"   : ISO-8601 UTC,
    }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("agentops.memory.episodic")

DEFAULT_MAX_INTERACTIONS = 20
DEFAULT_STREAM_MAX_LEN = 1000  # approximate MAXLEN for Redis Streams


class EpisodicMemory:
    """
    Short-term episodic memory: last-N interactions + durable event stream.

    Usage::
        mem = EpisodicMemory(redis=redis_conn, agent_id="research-agent")
        await mem.push(session_id="sess-1", interaction={"role": "user", "content": "..."})
        history = await mem.load(session_id="sess-1", limit=10)
        await mem.log_event(run_id="run-1", event={"event_type": "tool.call", "payload": {}})
    """

    def __init__(
        self,
        redis: Any,
        agent_id: str,
        max_interactions: int = DEFAULT_MAX_INTERACTIONS,
    ) -> None:
        self._redis = redis
        self.agent_id = agent_id
        self.max_interactions = max_interactions

    # ── Interaction list (Redis List) ─────────────────────────────────────────

    def _list_key(self, session_id: str) -> str:
        return f"nexus:episodic:{self.agent_id}:{session_id}"

    async def push(
        self,
        session_id: str,
        interaction: dict[str, Any],
        run_id: str = "",
    ) -> None:
        """
        Prepend an interaction to the session list and trim to max_interactions.
        Interactions are stored newest-first (LPUSH) so LRANGE 0 N-1 gives
        the N most recent items.
        """
        if "timestamp" not in interaction:
            interaction["timestamp"] = datetime.now(timezone.utc).isoformat()
        if run_id and "run_id" not in interaction:
            interaction["run_id"] = run_id

        key = self._list_key(session_id)
        payload = json.dumps(interaction)
        await self._redis.lpush(key, payload)
        await self._redis.ltrim(key, 0, self.max_interactions - 1)
        log.debug("EpisodicMemory.push: key=%s total_capped=%d", key, self.max_interactions)

    async def load(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Return the most recent `limit` interactions for a session.
        Ordered newest-first (matching storage order).
        """
        n = (limit or self.max_interactions) - 1
        key = self._list_key(session_id)
        raw_items = await self._redis.lrange(key, 0, n)
        result: list[dict[str, Any]] = []
        for item in raw_items:
            text = item if isinstance(item, str) else item.decode()
            try:
                result.append(json.loads(text))
            except json.JSONDecodeError:
                log.warning("EpisodicMemory: skipping malformed item: %r", text[:80])
        return result

    async def clear(self, session_id: str) -> None:
        """Delete the full interaction list for a session."""
        await self._redis.delete(self._list_key(session_id))

    # ── Event stream (Redis Stream) ───────────────────────────────────────────

    def _stream_key(self) -> str:
        return f"nexus:stream:{self.agent_id}"

    async def log_event(
        self,
        run_id: str,
        event: dict[str, Any],
    ) -> str:
        """
        Append an event to the agent's Redis Stream.
        Returns the stream entry ID (e.g. '1718000000000-0').
        """
        stream_key = self._stream_key()
        fields: dict[str, str] = {
            "event_type": str(event.get("event_type", "unknown")),
            "run_id": run_id,
            "payload": json.dumps(event.get("payload", {})),
            "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }
        entry_id = await self._redis.xadd(
            stream_key, fields, maxlen=DEFAULT_STREAM_MAX_LEN, approximate=True
        )
        log.debug("EpisodicMemory.log_event: stream=%s id=%s", stream_key, entry_id)
        return entry_id if isinstance(entry_id, str) else entry_id.decode()

    async def get_events(
        self,
        run_id: Optional[str] = None,
        count: int = 50,
        start: str = "-",
        end: str = "+",
    ) -> list[dict[str, Any]]:
        """
        Read events from the agent's Redis Stream.
        If *run_id* is given, filters client-side (Redis Streams don't support
        field-level filter natively).
        """
        stream_key = self._stream_key()
        raw = await self._redis.xrange(stream_key, start, end, count=count)
        events: list[dict[str, Any]] = []
        for entry_id, fields in raw:
            decoded: dict[str, str] = {
                (k if isinstance(k, str) else k.decode()): (v if isinstance(v, str) else v.decode())
                for k, v in fields.items()
            }
            if run_id and decoded.get("run_id") != run_id:
                continue
            try:
                decoded["payload"] = json.loads(decoded.get("payload", "{}"))
            except json.JSONDecodeError:
                pass
            decoded["entry_id"] = entry_id if isinstance(entry_id, str) else entry_id.decode()
            events.append(decoded)
        return events
