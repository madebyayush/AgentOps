"""
AgentOps Testing Framework — Boilerplate Mocks
==============================================
This module provides ready-to-use, robust, in-memory mocks for standard
external and internal dependencies (Redis, Database, OpenAI LLM, Kafka)
specifically structured for modern FastAPI / asyncio testing.
"""
from __future__ import annotations

import asyncio
import uuid
import time
from typing import Any, AsyncGenerator, Callable


# ─────────────────────────────────────────────────────────────────────────────
# 1. Mock SQLAlchemy AsyncSession
# ─────────────────────────────────────────────────────────────────────────────

class MockAsyncSession:
    """
    An in-memory mock for SQLAlchemy's AsyncSession.
    Tracks inserts, updates, and supports committing/rolling back.
    """
    def __init__(self):
        self.inserted: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.flushed = False

    def add(self, instance: Any) -> None:
        self.inserted.append(instance)

    async def flush(self) -> None:
        self.flushed = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> MockResult:
        """Stubs session execute returning an empty or custom MockResult."""
        return MockResult([])

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any | None:
        """Returns None or a default stub instance."""
        return None

    async def close(self) -> None:
        pass


class MockResult:
    """Helper for SQLAlchemy execute results."""
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalars(self) -> MockScalars:
        return MockScalars(self._rows)

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class MockScalars:
    """Helper for SQLAlchemy scalar selection."""
    def __init__(self, items: list[Any]):
        self._items = items

    def all(self) -> list[Any]:
        return self._items

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Mock Redis Client
# ─────────────────────────────────────────────────────────────────────────────

class MockRedisClient:
    """
    An in-memory async Redis cache and pub/sub mock.
    Maintains a dictionary for state checking and mock rate limiting.
    """
    def __init__(self):
        self.store: dict[str, str] = {}
        self.events: list[tuple[str, str]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                count += 1
        return count

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def publish(self, channel: str, message: str) -> int:
        self.events.append((channel, message))
        return 1

    async def flushall(self) -> bool:
        self.store.clear()
        self.events.clear()
        return True

    async def hset(self, name: str, key: str, value: str) -> int:
        hash_key = f"__hash__:{name}"
        if hash_key not in self.store:
            self.store[hash_key] = "{}"
        import json
        data = json.loads(self.store[hash_key])
        data[key] = str(value)
        self.store[hash_key] = json.dumps(data)
        return 1

    async def hget(self, name: str, key: str) -> str | None:
        hash_key = f"__hash__:{name}"
        if hash_key not in self.store:
            return None
        import json
        data = json.loads(self.store[hash_key])
        return data.get(key)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Mock OpenAI LLM Client Compliant with AsyncOpenAI API
# ─────────────────────────────────────────────────────────────────────────────

class MockLLMChoiceMessage:
    def __init__(self, content: str, role: str = "assistant"):
        self.content = content
        self.role = role


class MockLLMChoice:
    def __init__(self, content: str, role: str = "assistant", finish_reason: str = "stop"):
        self.message = MockLLMChoiceMessage(content, role)
        self.finish_reason = finish_reason


class MockLLMUsage:
    def __init__(self, prompt_tokens: int = 15, completion_tokens: int = 25):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class MockChatCompletionResponse:
    def __init__(self, content: str, model: str = "gpt-4o"):
        self.id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self.choices = [MockLLMChoice(content)]
        self.model = model
        self.usage = MockLLMUsage()
        self.created = int(time.time())


class MockChatCompletions:
    """Mock for client.chat.completions"""
    def __init__(self, default_response: str = "Cognitive execution completed successfully."):
        self.default_response = default_response
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        **kwargs: Any
    ) -> MockChatCompletionResponse:
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs
        })
        # Try to return customized content depending on system or user prompt if desired
        response_content = self.default_response
        for msg in messages:
            if "hello" in msg.get("content", "").lower():
                response_content = "Hello! I am the AgentOps AI orchestration subsystem. How can I help you today?"
                break
        return MockChatCompletionResponse(response_content, model=model)


class MockLLMClient:
    """
    Mock OpenAI/Anthropic client mirroring the modern AsyncOpenAI instance structure.
    Used for unit testing LLM cognitive calls without API keys.
    """
    def __init__(self, default_response: str = "Cognitive execution completed successfully."):
        self.chat = type("Chat", (object,), {
            "completions": MockChatCompletions(default_response)
        })()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mock Kafka Task Broker
# ─────────────────────────────────────────────────────────────────────────────

class MockKafkaBroker:
    """
    Simulates Kafka message publish/subscribe queueing system.
    Saves and indexes jobs for assertions.
    """
    def __init__(self):
        self.topics: dict[str, list[dict[str, Any]]] = {}

    async def send_and_wait(self, topic: str, value: dict[str, Any], key: str | None = None) -> Any:
        if topic not in self.topics:
            self.topics[topic] = []
        payload = {
            "key": key,
            "value": value,
            "timestamp": time.time(),
            "partition": 0,
            "offset": len(self.topics[topic])
        }
        self.topics[topic].append(payload)
        return payload

    def get_messages(self, topic: str) -> list[dict[str, Any]]:
        return self.topics.get(topic, [])

    def clear(self) -> None:
        self.topics.clear()
