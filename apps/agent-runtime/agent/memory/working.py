"""
AgentOps — Working Memory (Redis State Persistence)
=====================================================
Serialises and restores the full AgentState at run boundaries.

Key: nexus:state:{run_id}
TTL: 24 hours (configurable)

Serialisation: orjson for speed and correctness with nested dicts/lists.
Falls back to stdlib json if orjson is not installed.

REST access: get_run_state(run_id) is called by graph.py to expose
the endpoint GET /agents/{run_id}/state.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("agentops.memory.working")

DEFAULT_TTL = 3600 * 24  # 24 hours


def _dumps(obj: Any) -> bytes:
    try:
        import orjson

        return orjson.dumps(obj)
    except ImportError:
        import json

        return json.dumps(obj).encode()


def _loads(data: bytes | str) -> Any:
    try:
        import orjson

        return orjson.loads(data)
    except ImportError:
        import json

        return json.loads(data)


class WorkingMemory:
    """
    Persists a full AgentState snapshot in Redis so it can be restored
    after a crash, pod restart, or for inspection via the REST API.

    Usage::
        wm = WorkingMemory(redis=redis_conn)
        await wm.save_state(run_id="run-1", state=state)
        state = await wm.load_state(run_id="run-1")
        await wm.delete_state(run_id="run-1")
    """

    def __init__(self, redis: Any, ttl: int = DEFAULT_TTL) -> None:
        self._redis = redis
        self._ttl = ttl

    def _key(self, run_id: str) -> str:
        return f"nexus:state:{run_id}"

    async def save_state(self, run_id: str, state: dict[str, Any]) -> None:
        """Serialise and persist *state* with TTL."""
        key = self._key(run_id)
        payload = _dumps(state)
        await self._redis.setex(key, self._ttl, payload)
        log.debug("WorkingMemory.save_state: run_id=%s bytes=%d", run_id, len(payload))

    async def load_state(self, run_id: str) -> Optional[dict[str, Any]]:
        """
        Return the stored AgentState dict for *run_id*, or None if not found / expired.
        """
        key = self._key(run_id)
        raw = await self._redis.get(key)
        if raw is None:
            log.debug("WorkingMemory.load_state: miss for run_id=%s", run_id)
            return None
        state = _loads(raw)
        log.debug("WorkingMemory.load_state: hit for run_id=%s", run_id)
        return state

    async def delete_state(self, run_id: str) -> None:
        """Remove the state entry for *run_id*."""
        key = self._key(run_id)
        await self._redis.delete(key)
        log.debug("WorkingMemory.delete_state: run_id=%s", run_id)

    async def get_ttl(self, run_id: str) -> int:
        """Return remaining TTL in seconds, or -2 if key does not exist."""
        return await self._redis.ttl(self._key(run_id))
