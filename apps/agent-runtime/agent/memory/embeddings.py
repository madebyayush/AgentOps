"""
AgentOps — Embedding Model
===========================
Wraps OpenAI text-embedding-3-small (1536-dim).

When OPENAI_API_KEY is absent the stub returns a deterministic unit-vector
derived from the text hash so that cosine-similarity tests remain meaningful
without requiring network access or API quota.

Interface contract:
    model = EmbeddingModel()
    vector = await model.embed("some text")   # list[float], len == EMBEDDING_DIM
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Optional

log = logging.getLogger("agentops.memory.embeddings")

EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension


class EmbeddingModel:
    """
    Async embedding model wrapper.

    Real path  : OpenAI text-embedding-3-small (activated by OPENAI_API_KEY).
    Stub path  : deterministic unit-vector from SHA-256 of input text.
                 Identical texts produce identical vectors; different texts
                 produce different vectors — cosine similarity is meaningful.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client: Optional[object] = None
        if self._api_key:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=self._api_key)
                log.info("EmbeddingModel: using OpenAI text-embedding-3-small")
            except ImportError:
                log.warning("openai package not installed — falling back to stub embeddings")
        else:
            log.info("EmbeddingModel: OPENAI_API_KEY absent — using deterministic stub")

    async def embed(self, text: str) -> list[float]:
        """Return a 1536-dim embedding vector for *text*."""
        if self._client is not None:
            return await self._embed_openai(text)
        return self._embed_stub(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts; returns one vector per input."""
        if self._client is not None:
            return await self._embed_openai_batch(texts)
        return [self._embed_stub(t) for t in texts]

    # ── Real client ───────────────────────────────────────────────────────────

    async def _embed_openai(self, text: str) -> list[float]:
        from openai import AsyncOpenAI

        client: AsyncOpenAI = self._client  # type: ignore[assignment]
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def _embed_openai_batch(self, texts: list[str]) -> list[list[float]]:
        from openai import AsyncOpenAI

        client: AsyncOpenAI = self._client  # type: ignore[assignment]
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        # API guarantees same order as input
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    # ── Stub (offline / no-key) ───────────────────────────────────────────────

    @staticmethod
    def _embed_stub(text: str) -> list[float]:
        """
        Deterministic pseudo-embedding: hash → seed → pseudo-random unit vector.
        Consistent across calls — same text always gives same vector.
        """
        digest = hashlib.sha256(text.encode()).digest()
        # Use hash bytes as seeds for a 1536-dim vector
        values: list[float] = []
        for i in range(EMBEDDING_DIM):
            byte_idx = i % len(digest)
            bit_idx = (i // len(digest)) % 8
            val = ((digest[byte_idx] >> bit_idx) & 1) * 2.0 - 1.0
            values.append(val)
        # Normalise to unit vector
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]
