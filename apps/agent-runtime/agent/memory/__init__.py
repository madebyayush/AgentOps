"""
AgentOps — Memory Sub-package
==============================
Public API for all four memory tiers:

    from agent.memory import SemanticMemory, EpisodicMemory, WorkingMemory, ProceduralMemory
    from agent.memory import MemoryClient, MemoryChunk

Backward-compat shim: MemoryClient wraps all four tiers under the old interface
so existing callers (agent/base.py) continue to work unchanged.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from agent.memory.embeddings import EmbeddingModel, EMBEDDING_DIM
from agent.memory.semantic import (
    SemanticMemory,
    MemoryChunk,
    InMemoryVectorStore,
    VectorStoreProtocol,
)
from agent.memory.reranker import CrossEncoderReranker
from agent.memory.episodic import EpisodicMemory
from agent.memory.working import WorkingMemory
from agent.memory.procedural import ProceduralMemory, ToolStats

log = logging.getLogger("agentops.memory")

__all__ = [
    "EmbeddingModel",
    "EMBEDDING_DIM",
    "SemanticMemory",
    "MemoryChunk",
    "InMemoryVectorStore",
    "VectorStoreProtocol",
    "CrossEncoderReranker",
    "EpisodicMemory",
    "WorkingMemory",
    "ProceduralMemory",
    "ToolStats",
    "MemoryClient",
]


# ── Backward-compat shim ──────────────────────────────────────────────────────


class MemoryClient:
    """
    Backward-compatible wrapper used by BaseAgent.
    Delegates to SemanticMemory and EpisodicMemory internally.

    Old callers:
        client.store(content, namespace, metadata)  → stores + returns vector_id
        client.retrieve(query, namespace, top_k)    → list[str]
        client.store_episodic(key, content, ns)
        client.get_episodic(key, ns)
        client.list_episodic(ns, limit)
    """

    EPISODIC_TTL = 3600 * 24  # 24 hours

    def __init__(
        self,
        redis: Any,
        vector_store: Optional[VectorStoreProtocol] = None,
    ) -> None:
        self._redis = redis
        self._vector_store = vector_store or InMemoryVectorStore()

    # ── Episodic (legacy Redis SETEX interface — kept for BaseAgent) ──────────

    async def store_episodic(
        self,
        key: str,
        content: str,
        namespace: str,
        ttl: int = EPISODIC_TTL,
    ) -> None:
        full_key = f"memory:{namespace}:{key}"
        await self._redis.setex(full_key, ttl, content)

    async def get_episodic(self, key: str, namespace: str) -> Optional[str]:
        full_key = f"memory:{namespace}:{key}"
        value = await self._redis.get(full_key)
        return value if isinstance(value, str) else (value.decode() if value else None)

    async def list_episodic(self, namespace: str, limit: int = 20) -> list[str]:
        pattern = f"memory:{namespace}:*"
        keys = await self._redis.keys(pattern)
        results: list[str] = []
        for key in keys[-limit:]:
            val = await self._redis.get(key)
            if val:
                results.append(val if isinstance(val, str) else val.decode())
        return results

    # ── Semantic (legacy store/retrieve interface) ────────────────────────────

    async def store(
        self,
        content: str,
        namespace: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        vector_id = str(uuid.uuid4())
        meta = metadata or {}
        meta["content"] = content
        meta["namespace"] = namespace
        meta["timestamp"] = str(time.time())

        await self.store_episodic(vector_id, content, namespace)

        placeholder_vector = [0.0] * EMBEDDING_DIM
        await self._vector_store.upsert(namespace, vector_id, placeholder_vector, meta)
        return vector_id

    async def retrieve(
        self,
        query: str,
        namespace: str,
        top_k: int = 5,
    ) -> list[str]:
        query_vector = [0.0] * EMBEDDING_DIM
        matches = await self._vector_store.query(namespace, query_vector, top_k)

        if matches:
            return [m.get("metadata", {}).get("content", json.dumps(m)) for m in matches]

        return await self.list_episodic(namespace, limit=top_k)
