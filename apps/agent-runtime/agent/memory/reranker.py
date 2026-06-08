"""
AgentOps — Cross-Encoder Reranker
===================================
Reranks retrieved MemoryChunks by relevance to a query.

Real path  : Cohere rerank-english-v3.0 (activated by COHERE_API_KEY).
Stub path  : Score-aware passthrough — preserves original retrieval order
             (which is already sorted by cosine similarity from SemanticMemory.recall).
             Returns chunks sorted by their existing score, highest first.
             When you swap in the real Cohere client, set COHERE_API_KEY — no other change needed.

Design goal: stub interface is *identical* to real client so the Phase 8 swap is one env var.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from agent.memory.semantic import MemoryChunk

log = logging.getLogger("agentops.memory.reranker")


class CrossEncoderReranker:
    """
    Reranks a list of MemoryChunks against a query string.

    Usage::
        reranker = CrossEncoderReranker()
        chunks = await reranker.rerank(query="Q1 revenue", chunks=retrieved, top_k=3)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("COHERE_API_KEY")
        self._client: Optional[object] = None

        if self._api_key and not self._api_key.startswith("co-stub") and not self._api_key.startswith("sk-stub"):
            try:
                import cohere

                self._client = cohere.AsyncClientV2(api_key=self._api_key)
                log.info("CrossEncoderReranker: using Cohere rerank-english-v3.0")
            except ImportError:
                log.warning("cohere package not installed — falling back to score-passthrough stub")
        else:
            log.info("CrossEncoderReranker: COHERE_API_KEY absent or stub — using score-passthrough stub")

    async def rerank(
        self,
        query: str,
        chunks: list[MemoryChunk],
        top_k: Optional[int] = None,
    ) -> list[MemoryChunk]:
        """
        Rerank *chunks* by relevance to *query*.
        Returns up to *top_k* chunks (all chunks if top_k is None).
        """
        if not chunks:
            return []

        n = top_k if top_k is not None else len(chunks)

        if self._client is not None:
            return await self._rerank_cohere(query, chunks, n)

        return self._rerank_stub(chunks, n)

    # ── Real Cohere client ────────────────────────────────────────────────────

    async def _rerank_cohere(
        self, query: str, chunks: list[MemoryChunk], top_k: int
    ) -> list[MemoryChunk]:
        import cohere

        client: cohere.AsyncClientV2 = self._client  # type: ignore[assignment]
        documents = [c.content for c in chunks]

        response = await client.rerank(
            model="rerank-english-v3.0",
            query=query,
            documents=documents,
            top_n=top_k,
        )

        reranked: list[MemoryChunk] = []
        for result in response.results:
            original = chunks[result.index]
            reranked.append(
                MemoryChunk(
                    chunk_id=original.chunk_id,
                    content=original.content,
                    score=result.relevance_score,
                    metadata=original.metadata,
                )
            )
        log.debug(
            "CrossEncoderReranker: Cohere reranked %d → %d chunks", len(chunks), len(reranked)
        )
        return reranked

    # ── Score-aware stub ──────────────────────────────────────────────────────

    @staticmethod
    def _rerank_stub(chunks: list[MemoryChunk], top_k: int) -> list[MemoryChunk]:
        """
        Score-aware passthrough: preserves cosine-similarity order from SemanticMemory.
        Does NOT randomise or flatten scores — ordering is meaningful for tests.
        """
        sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)
        result = sorted_chunks[:top_k]
        log.debug("CrossEncoderReranker: stub passthrough returned %d chunks", len(result))
        return result
