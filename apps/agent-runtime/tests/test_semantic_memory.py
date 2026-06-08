"""
Tests for Semantic Memory (Step 3.1)
=====================================
Tests: remember/recall/forget, cosine similarity, RAG pipeline,
       reranker integration, citation tracking.

All tests use InMemoryVectorStore + stub EmbeddingModel — no API keys required.
"""

from __future__ import annotations

import math
import pytest
from unittest.mock import AsyncMock, patch

from agent.memory.embeddings import EmbeddingModel, EMBEDDING_DIM
from agent.memory.semantic import (
    SemanticMemory,
    MemoryChunk,
    InMemoryVectorStore,
)
from agent.memory.reranker import CrossEncoderReranker

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def embed_model():
    """EmbeddingModel with no API key → deterministic stub."""
    return EmbeddingModel(api_key=None)


@pytest.fixture
def in_memory_store():
    return InMemoryVectorStore()


@pytest.fixture
def semantic(in_memory_store, embed_model):
    return SemanticMemory(
        agent_id="test-agent",
        vector_store=in_memory_store,
        embedding_model=embed_model,
    )


@pytest.fixture
def reranker():
    """Reranker with no API key → score-passthrough stub."""
    return CrossEncoderReranker(api_key=None)


# ── Embedding model tests ─────────────────────────────────────────────────────


class TestEmbeddingModel:
    async def test_stub_returns_correct_dim(self, embed_model):
        vec = await embed_model.embed("hello world")
        assert len(vec) == EMBEDDING_DIM

    async def test_stub_is_unit_vector(self, embed_model):
        vec = await embed_model.embed("test sentence")
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-6

    async def test_stub_is_deterministic(self, embed_model):
        vec1 = await embed_model.embed("same text")
        vec2 = await embed_model.embed("same text")
        assert vec1 == vec2

    async def test_different_texts_differ(self, embed_model):
        vec1 = await embed_model.embed("apples and oranges")
        vec2 = await embed_model.embed("quantum computing")
        assert vec1 != vec2

    async def test_embed_batch(self, embed_model):
        texts = ["first text", "second text", "third text"]
        vecs = await embed_model.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == EMBEDDING_DIM for v in vecs)


# ── InMemoryVectorStore cosine similarity tests ───────────────────────────────


class TestInMemoryVectorStore:
    async def test_upsert_and_query(self, in_memory_store):
        # Insert a known vector
        target = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        await in_memory_store.upsert("ns1", "vec-1", target, {"content": "target"})

        # Query with exact same vector → should get score ~1.0
        results = await in_memory_store.query("ns1", target, top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "vec-1"
        assert abs(results[0]["score"] - 1.0) < 1e-6

    async def test_ranking_order(self, in_memory_store):
        """Higher cosine similarity ranks first."""
        target = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        similar = [0.9] + [0.1] + [0.0] * (EMBEDDING_DIM - 2)
        distant = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)

        await in_memory_store.upsert("ns2", "similar", similar, {"content": "similar"})
        await in_memory_store.upsert("ns2", "distant", distant, {"content": "distant"})

        results = await in_memory_store.query("ns2", target, top_k=2)
        assert results[0]["id"] == "similar"
        assert results[1]["id"] == "distant"

    async def test_delete(self, in_memory_store):
        vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        await in_memory_store.upsert("ns3", "del-me", vec, {"content": "bye"})
        await in_memory_store.delete("ns3", ["del-me"])
        results = await in_memory_store.query("ns3", vec, top_k=1)
        assert results == []

    async def test_filter(self, in_memory_store):
        vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        await in_memory_store.upsert("ns4", "a", vec, {"source_type": "observation"})
        await in_memory_store.upsert("ns4", "b", vec, {"source_type": "reflection"})

        results = await in_memory_store.query(
            "ns4", vec, top_k=5, filter={"source_type": "observation"}
        )
        ids = {r["id"] for r in results}
        assert "a" in ids
        assert "b" not in ids

    async def test_namespace_isolation(self, in_memory_store):
        vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        await in_memory_store.upsert("ns-a", "x", vec, {"content": "in ns-a"})
        results = await in_memory_store.query("ns-b", vec, top_k=5)
        assert results == []

    async def test_upsert_replaces_existing(self, in_memory_store):
        vec = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        await in_memory_store.upsert("ns5", "dup", vec, {"content": "original"})
        await in_memory_store.upsert("ns5", "dup", vec, {"content": "updated"})
        results = await in_memory_store.query("ns5", vec, top_k=5)
        # Should only have one entry with the updated metadata
        dup_results = [r for r in results if r["id"] == "dup"]
        assert len(dup_results) == 1
        assert dup_results[0]["metadata"]["content"] == "updated"


# ── SemanticMemory high-level API tests ──────────────────────────────────────


class TestSemanticMemory:
    async def test_remember_returns_chunk_id(self, semantic):
        chunk_id = await semantic.remember("Q1 revenue was $4.2B")
        assert isinstance(chunk_id, str)
        assert len(chunk_id) > 0

    async def test_recall_returns_chunks(self, semantic):
        await semantic.remember("Machine learning models need training data")
        chunks = await semantic.recall("training data for ML", top_k=5)
        assert isinstance(chunks, list)
        assert all(isinstance(c, MemoryChunk) for c in chunks)

    async def test_recall_empty_namespace(self, semantic):
        chunks = await semantic.recall("anything", top_k=5)
        assert chunks == []

    async def test_recall_scores_populated(self, semantic):
        await semantic.remember("Python is a programming language")
        chunks = await semantic.recall("programming", top_k=5)
        if chunks:
            assert all(isinstance(c.score, float) for c in chunks)

    async def test_forget_removes_chunk(self, semantic):
        chunk_id = await semantic.remember("This memory will be deleted")
        # Verify it exists
        chunks_before = await semantic.recall("memory deleted", top_k=5)
        assert any(c.chunk_id == chunk_id for c in chunks_before)
        # Forget it
        await semantic.forget([chunk_id])
        # Should not appear after deletion
        chunks_after = await semantic.recall("memory deleted", top_k=5)
        assert not any(c.chunk_id == chunk_id for c in chunks_after)

    async def test_metadata_stored_in_chunk(self, semantic):
        await semantic.remember(
            "task result",
            metadata={"task_id": "run-123"},
            source_type="tool_output",
            task_id="run-123",
        )
        chunks = await semantic.recall("task result", top_k=5)
        assert chunks
        meta = chunks[0].metadata
        assert meta.get("agent_id") == "test-agent"
        assert meta.get("source_type") == "tool_output"
        assert meta.get("task_id") == "run-123"

    async def test_citations_are_chunk_ids(self, semantic):
        id1 = await semantic.remember("Fact one about revenue")
        id2 = await semantic.remember("Fact two about growth")
        chunks = await semantic.recall("revenue growth", top_k=5)
        returned_ids = {c.chunk_id for c in chunks}
        # At least one of our stored chunks should be returned
        assert id1 in returned_ids or id2 in returned_ids

    async def test_build_rag_context(self, semantic):
        await semantic.remember("Context sentence A")
        chunks = await semantic.recall("Context", top_k=5)
        context = semantic.build_rag_context(chunks)
        assert "RELEVANT CONTEXT" in context
        assert "Context sentence A" in context

    async def test_build_rag_context_empty(self, semantic):
        context = semantic.build_rag_context([])
        assert context == ""


# ── CrossEncoderReranker tests ────────────────────────────────────────────────


class TestCrossEncoderReranker:
    def _make_chunks(self, n: int) -> list[MemoryChunk]:
        """Create n chunks with known decreasing scores."""
        return [
            MemoryChunk(
                chunk_id=f"chunk-{i}",
                content=f"Content {i}",
                score=1.0 - i * 0.1,
                metadata={},
            )
            for i in range(n)
        ]

    async def test_stub_preserves_score_order(self, reranker):
        chunks = self._make_chunks(5)
        # Shuffle them
        shuffled = list(reversed(chunks))
        result = await reranker.rerank("query", shuffled, top_k=5)
        scores = [c.score for c in result]
        assert scores == sorted(scores, reverse=True)

    async def test_stub_respects_top_k(self, reranker):
        chunks = self._make_chunks(10)
        result = await reranker.rerank("query", chunks, top_k=3)
        assert len(result) == 3

    async def test_stub_empty_input(self, reranker):
        result = await reranker.rerank("query", [], top_k=5)
        assert result == []

    async def test_stub_no_top_k_returns_all(self, reranker):
        chunks = self._make_chunks(7)
        result = await reranker.rerank("query", chunks)
        assert len(result) == 7

    async def test_stub_returns_memory_chunks(self, reranker):
        chunks = self._make_chunks(3)
        result = await reranker.rerank("query", chunks, top_k=3)
        assert all(isinstance(c, MemoryChunk) for c in result)


# ── Full RAG pipeline integration test ───────────────────────────────────────


class TestRAGPipeline:
    async def test_full_pipeline(self, semantic, reranker):
        """remember → recall → rerank → build_rag_context → citations."""
        # Store facts
        id1 = await semantic.remember("Paris is the capital of France", source_type="observation")
        id2 = await semantic.remember("Rome is the capital of Italy", source_type="observation")
        await semantic.remember("The sky is blue", source_type="observation")

        # Retrieve and rerank
        chunks = await semantic.recall("European capitals", top_k=5)
        reranked = await reranker.rerank("European capitals", chunks, top_k=3)

        # Build context
        context = semantic.build_rag_context(reranked)
        assert "RELEVANT CONTEXT" in context

        # Citations
        citation_ids = [c.chunk_id for c in reranked]
        assert isinstance(citation_ids, list)
        assert all(isinstance(cid, str) for cid in citation_ids)
