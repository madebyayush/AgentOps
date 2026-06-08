"""
AgentOps — Tool Base Class and Registry
========================================
All agent tools inherit BaseTool and are registered in ToolRegistry.

Usage::

    registry = get_registry()
    tool = registry.get("web_search")
    result = await tool.execute(query="what is LangGraph")
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

log = logging.getLogger("agentops.tools")

# Module-level ProceduralMemory singleton (initialised lazily)
_procedural_memory: Optional[Any] = None


def _get_procedural_memory() -> Optional[Any]:
    """Return the module-level ProceduralMemory, creating it on first call."""
    global _procedural_memory
    if _procedural_memory is not None:
        return _procedural_memory
    try:
        from agent.memory.procedural import ProceduralMemory

        _procedural_memory = ProceduralMemory()  # uses POSTGRES_URL env var
    except Exception:
        pass  # silently skip if not configured
    return _procedural_memory


class BaseTool(ABC):
    """
    Abstract base class for all AgentOps tools.

    Subclasses must define:
      - name        : str — unique tool identifier
      - description : str — what this tool does (used by LLM for tool selection)
      - schema      : dict — JSON Schema of the tool's input parameters

    And implement:
      - _execute(**kwargs) -> dict — the actual tool logic
    """

    name: str = "base_tool"
    description: str = "A base tool."
    schema: dict[str, Any] = {}

    @abstractmethod
    async def _execute(self, **kwargs: Any) -> dict[str, Any]:
        """Override to implement tool logic. Return a dict with at least {'output': str}."""
        ...

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Wraps _execute with timing, logging, error handling, and ProceduralMemory tracking."""
        start = time.perf_counter()
        log.info("Tool executing: %s args=%s", self.name, list(kwargs.keys()))
        try:
            result = await self._execute(**kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            result["duration_ms"] = duration_ms
            result["success"] = True
            log.info("Tool completed: %s duration=%.1fms", self.name, duration_ms)
            # Record success (fire-and-forget, non-blocking)
            pm = _get_procedural_memory()
            if pm is not None:
                asyncio.create_task(pm.record_call(self.name, success=True, latency_ms=duration_ms))
            return result
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            log.error("Tool failed: %s error=%s", self.name, exc)
            # Record failure (fire-and-forget, non-blocking)
            pm = _get_procedural_memory()
            if pm is not None:
                asyncio.create_task(
                    pm.record_call(self.name, success=False, latency_ms=duration_ms)
                )
            return {
                "output": f"Tool '{self.name}' failed: {exc}",
                "error": str(exc),
                "success": False,
                "duration_ms": duration_ms,
            }

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def to_registry_schema(self) -> dict[str, Any]:
        """Return the dict used for ProceduralMemory DB upsert."""
        return {
            "tool_name": self.name,
            "description": self.description,
            "schema_json": self.schema,
        }

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r}>"


class ToolRegistry:
    """Singleton registry mapping tool names to BaseTool instances."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._tools[tool.name] = tool
        log.debug("Registered tool: %s", tool.name)

    @classmethod
    def get(cls, name: str) -> Optional[BaseTool]:
        return cls._tools.get(name)

    @classmethod
    def all(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def names(cls) -> list[str]:
        return list(cls._tools.keys())


_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _registry
