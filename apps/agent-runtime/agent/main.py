"""
AgentOps — Agent Runtime Engine Entry Point (Phase 2)
=======================================================
Replaces the Phase 1 stub loop with a full LangGraph-powered execution engine.

Startup sequence:
  1. Validate environment variables
  2. Initialise Redis connection
  3. Build and compile the LangGraph workflow graph with checkpointing
  4. Subscribe to Redis pub/sub channel `agentops.run.queued`
  5. On each message: spawn an OrchestratorAgent run via the compiled graph
  6. Update Run status in Redis after completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import Any, Optional

from dotenv import load_dotenv

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentops.runtime")

load_dotenv()

# ── Environment validation ────────────────────────────────────────────────────
if not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("OPENAI_API_KEY"):
    logger.critical("FATAL: Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY is set. Runtime aborted.")
    raise ValueError("At least one LLM API key is required.")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
RUN_QUEUED_CHANNEL = "agentops.run.queued"
RUN_STATUS_PREFIX = "run:status:"


# ── Runtime Engine ─────────────────────────────────────────────────────────────


class AgentRuntimeEngine:
    """
    Phase 2 Agent Runtime Engine.

    Subscribes to Redis pub/sub for `run.queued` events, then:
      1. Deserialises the run payload (run_id, prompt, agent_id)
      2. Builds the initial AgentState
      3. Invokes the compiled LangGraph graph with the task
      4. Publishes the final status back to Redis
    """

    def __init__(self) -> None:
        self.is_running = False
        self._graph: Optional[Any] = None
        self._redis: Optional[Any] = None
        logger.info("AgentOps Phase 2 Runtime Engine initialised.")

    async def _init_redis(self) -> None:
        """Establish async Redis connection."""
        import redis.asyncio as aioredis

        self._redis = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        logger.info("Redis connection established: %s", REDIS_URL)

    async def _init_graph(self) -> None:
        """Build and compile the LangGraph workflow."""
        from agent.graph import build_workflow_graph, get_checkpointer

        checkpointer = get_checkpointer()
        self._graph = build_workflow_graph(checkpointer)
        logger.info("LangGraph workflow compiled and ready.")

    async def _handle_run_event(self, payload: dict[str, Any]) -> None:
        """Process a single run.queued event end-to-end."""
        run_id = payload.get("run_id", "unknown")
        task = payload.get("prompt", "")
        agent_name = payload.get("agent_id", "orchestrator")

        logger.info("Processing run: run_id=%s task_len=%d", run_id, len(task))

        # Mark as running in Redis
        if self._redis:
            await self._redis.set(f"{RUN_STATUS_PREFIX}{run_id}", "running", ex=3600)

        # Build initial AgentState
        from agent.state import AgentState

        initial_state: AgentState = {
            "run_id": run_id,
            "agent_name": agent_name,
            "session_id": run_id,  # default session == run; override for multi-turn
            "task": task,
            "plan": [],
            "current_step": 0,
            "tool_calls": [],
            "observations": [],
            "memory_context": [],
            "memory_citations": [],
            "reflection": "",
            "retry_count": 0,
            "hitl_pending": False,
            "hitl_request_id": None,
            "error": None,
            "final_output": None,
        }

        try:
            if self._graph:
                config = {"configurable": {"thread_id": run_id}}
                final_state = await self._graph.ainvoke(initial_state, config=config)
                output = final_state.get("final_output", "Completed.")
                status = "completed"
            else:
                output = "Graph not initialised."
                status = "failed"
        except Exception as exc:
            logger.exception("Run failed: run_id=%s error=%s", run_id, exc)
            output = str(exc)
            status = "failed"

        # Update Redis status and publish completion event
        if self._redis:
            await self._redis.set(f"{RUN_STATUS_PREFIX}{run_id}", status, ex=3600)
            await self._redis.publish(
                "agentops.run.completed",
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": status,
                        "output": output[:500],
                    }
                ),
            )

        logger.info("Run completed: run_id=%s status=%s", run_id, status)

    async def start(self) -> None:
        """
        Main execution loop:
          1. Init Redis and LangGraph
          2. Subscribe to run.queued channel
          3. Process events as they arrive (concurrent with asyncio.create_task)
        """
        self.is_running = True
        await self._init_redis()
        await self._init_graph()

        logger.info("AgentOps engine started. Listening on channel: %s", RUN_QUEUED_CHANNEL)

        if self._redis is None:
            logger.error("Redis not available — cannot subscribe to events.")
            return

        pubsub = self._redis.pubsub()
        await pubsub.subscribe(RUN_QUEUED_CHANNEL)

        try:
            async for message in pubsub.listen():
                if not self.is_running:
                    break
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    # Spawn a task so events are processed concurrently
                    asyncio.create_task(self._handle_run_event(payload))
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Invalid run event payload: %s", exc)
        except asyncio.CancelledError:
            logger.info("Runtime event loop cancelled.")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown: drain Redis connections."""
        logger.info("Shutting down AgentOps runtime engine...")
        self.is_running = False
        if self._redis:
            await self._redis.aclose()
        logger.info("Runtime shutdown complete.")


# ── Entry point ───────────────────────────────────────────────────────────────


async def main() -> None:
    engine = AgentRuntimeEngine()

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received.")
        engine.is_running = False

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, ValueError):
            pass  # Windows does not support add_signal_handler for all signals

    try:
        await engine.start()
    except (KeyboardInterrupt, SystemExit):
        await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
