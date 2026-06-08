"""
AgentOps — Semantic Memory (Long-term, Pinecone)
=================================================
Manages vector embeddings in Pinecone with per-agent namespaces.

Index   : agentops-memory  (created once, namespaces separate agents)
Namespace: nexus-{agent_name}

Metadata fields stored per vector:
    content_hash  : SHA-256 hex of the content text
    source_type   : "observation" | "reflection" | "tool_output" | "manual"
    agent_id      : agent name that stored this memory
    task_id       : run_id of the originating task
    created_at    : ISO-8601 UTC timestamp
    tags          : comma-separated tag string
    content       : the raw text (stored in metadata for retrieval)

Real client activates when PINECONE_API_KEY is set.
Stub (InMemoryVectorStore with cosine similarity) activates otherwise.
The stub interface is *identical* — swapping is a one-liner in tests.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from agent.memory.embeddings import EmbeddingModel, EMBEDDING_DIM

log = logging.getLogger("agentops.memory.semantic")

INDEX_NAME = "agentops-memory"


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class MemoryChunk:
    """A single retrieved memory chunk with its relevance score."""

    chunk_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Protocol — identical interface for both real and stub ─────────────────────


@runtime_checkable
class VectorStoreProtocol(Protocol):
    async def upsert(
        self,
        namespace: str,
        vector_id: str,
        values: list[float],
        metadata: dict[str, Any],
    ) -> None: ...

    async def query(
        self,
        namespace: str,
        query_vector: list[float],
        top_k: int,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]: ...

    async def delete(self, namespace: str, ids: list[str]) -> None: ...


# ── Cosine-similarity in-memory stub ─────────────────────────────────────────


class InMemoryVectorStore:
    """
    Dev/test stub with *real* cosine-similarity scoring.
    Interface is identical to PineconeVectorStore — swap is a one-liner.
    """

    def __init__(self) -> None:
        # namespace → list of {id, values, metadata}
        self._store: dict[str, list[dict[str, Any]]] = {}

    async def upsert(
        self,
        namespace: str,
        vector_id: str,
        values: list[float],
        metadata: dict[str, Any],
    ) -> None:
        ns = self._store.setdefault(namespace, [])
        # Replace existing entry with same id
        ns[:] = [e for e in ns if e["id"] != vector_id]
        ns.append({"id": vector_id, "values": values, "metadata": metadata})

    async def query(
        self,
        namespace: str,
        query_vector: list[float],
        top_k: int,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        entries = self._store.get(namespace, [])
        if not entries:
            return []

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(x * x for x in b)) or 1.0
            return dot / (na * nb)

        scored = [
            {**e, "score": cosine(query_vector, e["values"])}
            for e in entries
            if _matches_filter(e["metadata"], filter)
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def delete(self, namespace: str, ids: list[str]) -> None:
        if namespace in self._store:
            self._store[namespace] = [e for e in self._store[namespace] if e["id"] not in ids]


def _matches_filter(metadata: dict[str, Any], filter: Optional[dict[str, Any]]) -> bool:
    if not filter:
        return True
    return all(metadata.get(k) == v for k, v in filter.items())


# ── Real Pinecone client ───────────────────────────────────────────────────────


class PineconeVectorStore:
    """
    Production vector store backed by Pinecone serverless.
    Activated when PINECONE_API_KEY is set.
    """

    def __init__(self, api_key: str) -> None:
        try:
            from pinecone import Pinecone

            self._pc = Pinecone(api_key=api_key)
            self._index = self._pc.Index(INDEX_NAME)
            log.info("PineconeVectorStore: connected to index '%s'", INDEX_NAME)
        except ImportError:
            raise ImportError("pinecone package required: pip install pinecone")

    async def upsert(
        self,
        namespace: str,
        vector_id: str,
        values: list[float],
        metadata: dict[str, Any],
    ) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._index.upsert(
                vectors=[{"id": vector_id, "values": values, "metadata": metadata}],
                namespace=namespace,
            ),
        )

    async def query(
        self,
        namespace: str,
        query_vector: list[float],
        top_k: int,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        import asyncio

        kwargs: dict[str, Any] = {
            "vector": query_vector,
            "top_k": top_k,
            "namespace": namespace,
            "include_metadata": True,
        }
        if filter:
            kwargs["filter"] = filter

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: self._index.query(**kwargs))
        return [
            {
                "id": m.id,
                "values": [],
                "metadata": m.metadata or {},
                "score": m.score,
            }
            for m in response.matches
        ]

    async def delete(self, namespace: str, ids: list[str]) -> None:
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._index.delete(ids=ids, namespace=namespace),
        )


# ── SemanticMemory — high-level API ─────────────────────────────────────────


def _get_vector_store() -> VectorStoreProtocol:
    api_key = os.getenv("PINECONE_API_KEY")
    if api_key:
        return PineconeVectorStore(api_key=api_key)
    log.info("SemanticMemory: PINECONE_API_KEY absent — using InMemoryVectorStore stub")
    return InMemoryVectorStore()


class SemanticMemory:
    """
    Long-term semantic memory using vector embeddings.

    Usage::
        mem = SemanticMemory(agent_id="research-agent")
        chunk_id = await mem.remember("Q1 revenue was $4.2B", metadata={...})
        chunks   = await mem.recall("quarterly revenue figures", top_k=5)
        await mem.forget([chunk_id])
    """

    def __init__(
        self,
        agent_id: str,
        vector_store: Optional[VectorStoreProtocol] = None,
        embedding_model: Optional[EmbeddingModel] = None,
    ) -> None:
        self.agent_id = agent_id
        self.namespace = f"nexus-{agent_id}"
        self._store: VectorStoreProtocol = vector_store or _get_vector_store()
        self._embedder = embedding_model or EmbeddingModel()

    async def remember(
        self,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
        source_type: str = "observation",
        task_id: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """Embed *text* and upsert into the vector store. Returns chunk_id."""
        chunk_id = hashlib.sha256(f"{self.agent_id}:{text}:{time.time()}".encode()).hexdigest()[:32]

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        meta: dict[str, Any] = {
            "content_hash": content_hash,
            "source_type": source_type,
            "agent_id": self.agent_id,
            "task_id": task_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tags": ",".join(tags or []),
            "content": text,
        }
        if metadata:
            meta.update(metadata)

        vector = await self._embedder.embed(text)
        await self._store.upsert(self.namespace, chunk_id, vector, meta)
        log.debug("SemanticMemory.remember: id=%s ns=%s", chunk_id, self.namespace)
        return chunk_id

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[MemoryChunk]:
        """
        Similarity-search for *query* and return top-K MemoryChunks.
        Results are ordered by relevance score (descending).
        """
        query_vector = await self._embedder.embed(query)
        raw = await self._store.query(self.namespace, query_vector, top_k, filter)
        chunks = [
            MemoryChunk(
                chunk_id=r["id"],
                content=r.get("metadata", {}).get("content", ""),
                score=r.get("score", 0.0),
                metadata=r.get("metadata", {}),
            )
            for r in raw
        ]
        log.debug("SemanticMemory.recall: query=%r returned %d chunks", query[:40], len(chunks))
        return chunks

    async def forget(self, ids: list[str]) -> None:
        """Delete vectors by ID."""
        await self._store.delete(self.namespace, ids)
        log.debug("SemanticMemory.forget: deleted %d vectors", len(ids))

    def build_rag_context(self, chunks: list[MemoryChunk]) -> str:
        """
        Format retrieved chunks as a RELEVANT CONTEXT block for injection
        into the LLM system prompt.  Also returns citation chunk_ids.
        """
        if not chunks:
            return ""
        lines = ["=== RELEVANT CONTEXT ==="]
        for i, c in enumerate(chunks, 1):
            lines.append(f"[{i}] (score={c.score:.3f}) {c.content}")
        lines.append("=== END CONTEXT ===")
        return "\n".join(lines)
