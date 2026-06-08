"""
AgentOps — LangGraph StateGraph Builder
========================================
Builds and compiles the main agent workflow graph.

Graph structure:
  memory_retrieval → planner → tool_executor → reflection
  reflection (conditional) →
    next_step : advance_step → tool_executor (increment current_step)
    retry     : tool_executor (same step, retry_count already bumped in reflection)
    hitl      : hitl_checkpoint → tool_executor
    done      : output
    abort     : output

Checkpointing:
  Dev  : AsyncSqliteSaver (in-memory SQLite or file)
  Prod : AsyncPostgresSaver (via POSTGRES_URL)
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("agentops.graph")


def build_workflow_graph(checkpointer: Any = None) -> Any:
    """
    Build and compile the LangGraph StateGraph.

    Args:
        checkpointer: A LangGraph checkpointer instance (AsyncSqliteSaver or
                      AsyncPostgresSaver). If None, no checkpointing is used.

    Returns:
        A compiled LangGraph graph ready for .ainvoke() / .astream().
    """
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError:
        raise ImportError(
            "langgraph is required for Phase 2. " "Install it with: pip install langgraph"
        )

    from agent.state import AgentState
    from agent.nodes import (
        memory_retrieval_node,
        planner_node,
        tool_executor_node,
        reflection_node,
        reflection_router,
        hitl_checkpoint_node,
        output_node,
        _advance_step,
    )

    graph = StateGraph(AgentState)

    # ── Add nodes ─────────────────────────────────────────────────────────────
    graph.add_node("memory_retrieval", memory_retrieval_node)
    graph.add_node("planner", planner_node)
    graph.add_node("tool_executor", tool_executor_node)
    graph.add_node("reflection", reflection_node)
    graph.add_node("advance_step", _advance_step)
    graph.add_node("hitl_checkpoint", hitl_checkpoint_node)
    graph.add_node("output", output_node)

    # ── Deterministic edges ───────────────────────────────────────────────────
    graph.add_edge(START, "memory_retrieval")
    graph.add_edge("memory_retrieval", "planner")
    graph.add_edge("planner", "tool_executor")
    graph.add_edge("tool_executor", "reflection")
    graph.add_edge("advance_step", "tool_executor")
    graph.add_edge("hitl_checkpoint", "tool_executor")  # resume after approval
    graph.add_edge("output", END)

    # ── Conditional edges from reflection ─────────────────────────────────────
    graph.add_conditional_edges(
        "reflection",
        reflection_router,
        {
            "next_step": "advance_step",  # proceed to next plan step
            "retry": "tool_executor",  # retry same step
            "hitl": "hitl_checkpoint",  # escalate to human
            "done": "output",  # all steps complete
            "abort": "output",  # unrecoverable failure
        },
    )

    # ── Compile ───────────────────────────────────────────────────────────────
    compile_kwargs: dict[str, Any] = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    compiled = graph.compile(**compile_kwargs)
    log.info(
        "LangGraph workflow compiled successfully (checkpointer=%s).",
        type(checkpointer).__name__ if checkpointer else "None",
    )
    return compiled


def get_checkpointer() -> Any:
    """
    Return the appropriate checkpointer based on the environment.
      Dev  (PLATFORM_ENV != production): AsyncSqliteSaver
      Prod (PLATFORM_ENV == production): AsyncPostgresSaver
    """
    env = os.getenv("PLATFORM_ENV", "development")
    postgres_url = os.getenv("POSTGRES_URL", "")

    if env == "production" and postgres_url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            log.info("Using AsyncPostgresSaver checkpointer (production).")
            return AsyncPostgresSaver.from_conn_string(postgres_url)
        except ImportError:
            log.warning("AsyncPostgresSaver not available, falling back to AsyncSqliteSaver.")

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        log.info("Using AsyncSqliteSaver checkpointer (dev).")
        return AsyncSqliteSaver.from_conn_string(":memory:")
    except ImportError:
        log.warning("AsyncSqliteSaver not available — running without checkpointing.")
        return None


def get_run_state(run_id: str, redis: Any = None) -> Any:
    """
    Retrieve the persisted AgentState for a run from WorkingMemory.
    Used by REST endpoint: GET /agents/{run_id}/state

    Args:
        run_id  : The run ID to look up.
        redis   : An async Redis connection. If None, reads REDIS_URL env var.

    Returns:
        A coroutine that resolves to dict[str, Any] | None.
    """
    import asyncio

    async def _load() -> Any:
        try:
            from agent.memory.working import WorkingMemory

            _redis = redis
            if _redis is None:
                redis_url = os.getenv("REDIS_URL", "")
                if not redis_url:
                    return None
                import redis as _redis_mod
                import redis.asyncio as aioredis

                _redis = aioredis.from_url(redis_url, decode_responses=True)
            wm = WorkingMemory(redis=_redis)
            return await wm.load_state(run_id)
        except Exception as exc:
            log.warning("get_run_state failed for run_id=%s: %s", run_id, exc)
            return None

    return _load()
