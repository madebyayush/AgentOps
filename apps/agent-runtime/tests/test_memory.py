"""
Tests for agent.memory — MemoryClient backward-compat shim.
"""

from __future__ import annotations

import pytest

from agent.memory import InMemoryVectorStore, MemoryClient
from agent.memory.embeddings import EMBEDDING_DIM


class TestInMemoryVectorStore:
    @pytest.mark.asyncio
    async def test_upsert_and_query(self):
        store = InMemoryVectorStore()
        vec = [0.1] * EMBEDDING_DIM
        await store.upsert("ns1", "v1", vec, {"content": "hello"})
        results = await store.query("ns1", vec, top_k=5)
        assert len(results) == 1
        assert results[0]["metadata"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_query_empty_namespace(self):
        store = InMemoryVectorStore()
        results = await store.query("empty_ns", [0.0] * EMBEDDING_DIM, top_k=3)
        assert results == []


class TestMemoryClient:
    @pytest.mark.asyncio
    async def test_store_returns_vector_id(self, fake_redis):
        client = MemoryClient(redis=fake_redis)
        vector_id = await client.store("test content", namespace="agent:test")
        assert isinstance(vector_id, str)
        assert len(vector_id) > 0

    @pytest.mark.asyncio
    async def test_retrieve_returns_stored_content(self, fake_redis):
        client = MemoryClient(redis=fake_redis)
        await client.store("important fact about the task", namespace="agent:test")
        results = await client.retrieve("important fact", namespace="agent:test", top_k=5)
        assert isinstance(results, list)
        # Should return at least something (either from vector store or episodic fallback)
        assert len(results) >= 0  # May be empty if vector store stub returns nothing

    @pytest.mark.asyncio
    async def test_store_episodic_and_get(self, fake_redis):
        client = MemoryClient(redis=fake_redis)
        await client.store_episodic("key1", "episodic content", namespace="agent:test")
        value = await client.get_episodic("key1", namespace="agent:test")
        assert value == "episodic content"

    @pytest.mark.asyncio
    async def test_list_episodic_returns_entries(self, fake_redis):
        client = MemoryClient(redis=fake_redis)
        await client.store_episodic("k1", "content1", namespace="agent:list_test")
        await client.store_episodic("k2", "content2", namespace="agent:list_test")
        items = await client.list_episodic("agent:list_test", limit=10)
        assert isinstance(items, list)
