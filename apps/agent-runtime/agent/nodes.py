"""
AgentOps — LangGraph Node Functions
=====================================
Each node is a pure async function: (AgentState) -> AgentState.
Nodes do NOT mutate state in place — they return a new dict with updated keys
(LangGraph merges the returned dict into the running state).

Node execution order (default path):
  START
  → memory_retrieval_node
  → planner_node
  → tool_executor_node
  → reflection_node  ──conditional──► continue → tool_executor_node (or output_node)
                                     ► retry   → tool_executor_node
                                     ► hitl    → hitl_checkpoint_node
                                     ► abort   → output_node
  → output_node → END
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

# Import AgentState at runtime so get_type_hints() can resolve it
# when LangGraph inspects reflection_router's signature.
from agent.state import AgentState, ToolCallRecord

log = logging.getLogger("agentops.nodes")

MAX_RETRIES = 3

# ── Memory client singletons (initialised lazily per process) ─────────────────

_semantic_memory: "Optional[Any]" = None
_episodic_memory: "Optional[Any]" = None
_working_memory: "Optional[Any]" = None


def _get_memory_clients() -> tuple["Optional[Any]", "Optional[Any]", "Optional[Any]"]:
    """
    Lazily build SemanticMemory, EpisodicMemory, and WorkingMemory singletons.
    Returns (semantic, episodic, working) — any may be None if dependencies
    (env vars / packages) are missing.
    """
    global _semantic_memory, _episodic_memory, _working_memory
    if _semantic_memory is not None or _episodic_memory is not None:
        return _semantic_memory, _episodic_memory, _working_memory

    agent_id = os.getenv("AGENT_ID", "default-agent")

    # Semantic Memory
    try:
        from agent.memory import SemanticMemory

        _semantic_memory = SemanticMemory(agent_id=agent_id)
    except Exception as exc:
        log.warning("SemanticMemory init failed: %s", exc)

    # Episodic + Working Memory — both need Redis
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            import redis.asyncio as aioredis
            from agent.memory import EpisodicMemory, WorkingMemory

            _redis_conn = aioredis.from_url(redis_url, decode_responses=True)
            _episodic_memory = EpisodicMemory(redis=_redis_conn, agent_id=agent_id)
            _working_memory = WorkingMemory(redis=_redis_conn)
        except Exception as exc:
            log.warning("EpisodicMemory/WorkingMemory init failed: %s", exc)
    else:
        log.info("REDIS_URL not set — episodic and working memory disabled")

    return _semantic_memory, _episodic_memory, _working_memory


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _call_llm(prompt: str, system: str = "") -> str:
    """
    Thin LLM wrapper. Tries OpenAI GPT-4o first, falls back to Anthropic Claude.
    Returns the model's text response.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if openai_key:
        try:
            from openai import AsyncOpenAI
            from openai.types.chat import ChatCompletionMessageParam

            openai_client = AsyncOpenAI(api_key=openai_key)
            messages: list[ChatCompletionMessageParam] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            oai_resp = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.2,
                max_tokens=2048,
            )
            return oai_resp.choices[0].message.content or ""
        except Exception as exc:
            log.warning("OpenAI call failed, trying Anthropic: %s", exc)

    if anthropic_key:
        try:
            import anthropic

            anthropic_client = anthropic.AsyncAnthropic(api_key=anthropic_key)
            ant_resp = await anthropic_client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2048,
                system=system or "You are a helpful AI assistant.",
                messages=[{"role": "user", "content": prompt}],
            )
            return ant_resp.content[0].text  # type: ignore[union-attr]
        except Exception as exc:
            log.error("Anthropic call also failed: %s", exc)

    # Stub fallback for environments with no LLM keys
    log.warning("No LLM API keys found — using stub response.")
    return json.dumps(
        {
            "steps": ["Analyse the task", "Execute solution", "Verify output"],
            "rationale": "Stub plan generated (no LLM key available).",
        }
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Node 1: Memory Retrieval ──────────────────────────────────────────────────


async def memory_retrieval_node(state: "AgentState") -> dict[str, Any]:
    """
    Retrieve context relevant to the task from:
      - SemanticMemory (Pinecone vector similarity, reranked)
      - EpisodicMemory (last N session interactions from Redis)
    Populates state.memory_context and state.memory_citations.
    """
    log.info("[node:memory_retrieval] run=%s task_len=%d", state["run_id"], len(state["task"]))

    semantic, episodic, _working = _get_memory_clients()

    memory_context: list[str] = []
    memory_citations: list[str] = []
    session_id = state.get("session_id", state["run_id"])

    # 1. Semantic recall + rerank
    if semantic is not None:
        try:
            from agent.memory import CrossEncoderReranker

            reranker = CrossEncoderReranker()
            chunks = await semantic.recall(state["task"], top_k=10)
            ranked = await reranker.rerank(state["task"], chunks, top_k=5)
            for chunk in ranked:
                memory_context.append(chunk.content)
                memory_citations.append(chunk.chunk_id)
            log.info(
                "[node:memory_retrieval] semantic: recalled=%d reranked=%d",
                len(chunks),
                len(ranked),
            )
        except Exception as exc:
            log.warning("[node:memory_retrieval] semantic recall failed: %s", exc)

    # 2. Episodic history (recent session interactions)
    if episodic is not None:
        try:
            history = await episodic.load(session_id, limit=5)
            for interaction in history:
                role = interaction.get("role", "assistant")
                content = interaction.get("content", "")
                if content:
                    memory_context.append(f"[History/{role}] {content}")
            log.info(
                "[node:memory_retrieval] episodic: loaded %d interactions",
                len(history),
            )
        except Exception as exc:
            log.warning("[node:memory_retrieval] episodic load failed: %s", exc)

    return {
        "memory_context": memory_context,
        "memory_citations": memory_citations,
        "session_id": session_id,
    }


# ── Node 2: Planner ───────────────────────────────────────────────────────────


async def planner_node(state: "AgentState") -> dict[str, Any]:
    """
    Use the LLM to decompose the task into an ordered list of steps.
    """
    log.info("[node:planner] run=%s", state["run_id"])

    if state.get("error"):
        log.info("[node:planner] Error found in state, skipping planning.")
        return {}

    memory_ctx = "\n".join(state.get("memory_context", []))
    system = (
        "You are a planning expert. Decompose the given task into clear, "
        "executable steps. Respond ONLY with a JSON object: "
        '{"steps": ["step1", "step2", ...], "rationale": "brief explanation"}'
    )
    prompt = f"Task: {state['task']}\n\nRelevant context:\n{memory_ctx or 'None'}"

    raw = await _call_llm(prompt, system)
    try:
        parsed = json.loads(raw)
        plan = parsed.get("steps", [raw])
    except json.JSONDecodeError:
        plan = [raw]  # Treat the whole response as a single step

    log.info("[node:planner] run=%s steps=%d", state["run_id"], len(plan))
    return {"plan": plan, "current_step": 0, "retry_count": 0}


# ── Node 3: Tool Executor ─────────────────────────────────────────────────────


async def tool_executor_node(state: "AgentState") -> dict[str, Any]:
    """
    Execute the current step from the plan.
    Tries to determine which tool to use via LLM, then dispatches to ToolRegistry.
    """
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)

    if current_step >= len(plan):
        log.info("[node:tool_executor] All steps complete for run=%s", state["run_id"])
        return {}  # Nothing to do — graph will route to output

    if state.get("error") or state.get("hitl_pending"):
        log.info(
            "[node:tool_executor] Error or HITL pending for run=%s, skipping tool execution.",
            state["run_id"],
        )
        return {}

    step = plan[current_step]
    log.info(
        "[node:tool_executor] run=%s step=%d/%d: %s",
        state["run_id"],
        current_step + 1,
        len(plan),
        step[:60],
    )

    # Determine tool via LLM
    from agent.tools.base_tool import get_registry

    registry = get_registry()
    tool_names = registry.names()

    tool_prompt = (
        f"Step to execute: {step}\n"
        f"Available tools: {', '.join(tool_names) or 'none'}\n\n"
        "Respond ONLY with JSON: "
        '{"tool": "tool_name_or_none", "arguments": {"key": "value"}, "direct_output": "if no tool needed"}'
    )
    raw = await _call_llm(tool_prompt)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {"tool": None, "direct_output": raw}

    tool_name = decision.get("tool")
    arguments = decision.get("arguments", {})
    direct_output = decision.get("direct_output", "")

    start = time.perf_counter()
    timestamp = _now_iso()

    if tool_name and tool_name != "none":
        tool = registry.get(tool_name)
        if tool:
            result = await tool.execute(**arguments)
            observation = result.get("output", str(result))
            tool_record: "ToolCallRecord" = {
                "tool_name": tool_name,
                "arguments": arguments,
                "result": observation,
                "error": result.get("error"),
                "duration_ms": result.get("duration_ms", 0.0),
                "timestamp": timestamp,
            }
        else:
            observation = f"Tool '{tool_name}' not found in registry."
            tool_record = {
                "tool_name": tool_name,
                "arguments": arguments,
                "result": None,
                "error": observation,
                "duration_ms": 0.0,
                "timestamp": timestamp,
            }
    else:
        observation = direct_output or step
        tool_record = {
            "tool_name": "direct",
            "arguments": {},
            "result": observation,
            "error": None,
            "duration_ms": (time.perf_counter() - start) * 1000,
            "timestamp": timestamp,
        }

    updated_calls = list(state.get("tool_calls", [])) + [tool_record]
    updated_obs = list(state.get("observations", [])) + [observation]

    return {
        "tool_calls": updated_calls,
        "observations": updated_obs,
    }


# ── Node 4: Reflection ────────────────────────────────────────────────────────


async def reflection_node(state: "AgentState") -> dict[str, Any]:
    """
    Evaluate the last tool execution across 3 checks:
      1. tool_success  — did the tool return without error?
      2. schema_valid  — is the output a valid string?
      3. logic_sound   — does output make sense for the task? (LLM call)

    Sets recommendation: continue | retry | escalate_hitl | abort
    """
    log.info("[node:reflection] run=%s", state["run_id"])

    if state.get("error") or state.get("hitl_pending"):
        err_msg = state.get("error") or "Human-in-the-loop approval pending."
        log.info(
            "[node:reflection] Error or HITL pending for run=%s, aborting with error.",
            state["run_id"],
        )
        return {
            "reflection": f"ABORT: {err_msg}",
            "error": err_msg,
        }

    tool_calls = state.get("tool_calls", [])
    observations = state.get("observations", [])
    retry_count = state.get("retry_count", 0)

    last_call = tool_calls[-1] if tool_calls else None
    last_obs = observations[-1] if observations else ""

    # Check 1: tool success
    tool_success = (last_call is None) or (last_call.get("error") is None)

    # Check 2: schema validity (output must be a non-empty string)
    schema_valid = isinstance(last_obs, str) and len(last_obs.strip()) > 0

    # Check 3: logic check via LLM
    plan = state.get("plan", [])
    current_step_idx = state.get("current_step", 0)
    current_step_text = (
        plan[current_step_idx] if plan and current_step_idx < len(plan) else "unknown"
    )

    logic_prompt = (
        f"Task: {state['task']}\n"
        f"Current step: {current_step_text}\n"
        f"Tool output: {last_obs[:500]}\n\n"
        "Does this output logically address the current step? "
        'Respond ONLY with JSON: {"sound": true/false, "reason": "brief explanation"}'
    )
    raw = await _call_llm(logic_prompt)
    try:
        logic_result = json.loads(raw)
        logic_sound = logic_result.get("sound", True)
        logic_reason = logic_result.get("reason", "")
    except json.JSONDecodeError:
        logic_sound = True
        logic_reason = "Could not parse LLM reflection response."

    # Determine recommendation
    all_passed = tool_success and schema_valid and logic_sound
    issues = []
    if not tool_success:
        issues.append(f"Tool error: {last_call.get('error') if last_call else 'unknown'}")
    if not schema_valid:
        issues.append("Tool output was empty or invalid.")
    if not logic_sound:
        issues.append(f"Logic check failed: {logic_reason}")

    if all_passed:
        recommendation = "continue"
    elif retry_count < MAX_RETRIES:
        recommendation = "retry"
        retry_count += 1
    else:
        recommendation = "escalate_hitl"

    rationale = f"{recommendation.upper()}: {'; '.join(issues) or 'All checks passed.'}"
    log.info(
        "[node:reflection] run=%s recommendation=%s retry=%d",
        state["run_id"],
        recommendation,
        retry_count,
    )

    return {
        "reflection": rationale,
        "retry_count": retry_count,
    }


def reflection_router(state: "AgentState") -> str:
    """
    Conditional edge function for LangGraph.
    Reads the reflection rationale and routes to the next node.
    """
    reflection = state.get("reflection", "")
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)

    if "ESCALATE_HITL" in reflection:
        return "hitl"
    elif "RETRY" in reflection:
        return "retry"
    elif "ABORT" in reflection:
        return "abort"
    else:
        # Continue: advance to next step or finish
        if current_step + 1 < len(plan):
            return "next_step"
        else:
            return "done"


# ── Node 5: HITL Checkpoint ───────────────────────────────────────────────────


async def hitl_checkpoint_node(state: "AgentState") -> dict[str, Any]:
    """
    Pause execution and emit a HITL approval request to the API Gateway.
    The graph checkpointer will persist state here until the run is resumed.
    """
    log.warning(
        "[node:hitl] run=%s — Human approval required. Reflection: %s",
        state["run_id"],
        state.get("reflection", "")[:100],
    )

    # In a real deployment: POST to /api/v1/hitl with run_id and context
    # For now, emit a log and set the flag
    return {
        "hitl_pending": True,
        "hitl_request_id": None,  # Set by the HTTP call in production
    }


# ── Node 6: Output ────────────────────────────────────────────────────────────


async def output_node(state: "AgentState") -> dict[str, Any]:
    """
    Consolidate all observations into a final structured output.
    Persists full AgentState snapshot in WorkingMemory.
    Logs completion event to the Redis Stream.
    """
    log.info("[node:output] run=%s", state["run_id"])

    observations = state.get("observations", [])
    error = state.get("error")

    if error:
        final = f"Run aborted: {error}"
    else:
        joined = "\n\n".join(f"Step {i+1}: {obs}" for i, obs in enumerate(observations))
        final = f"Task completed successfully.\n\n{joined}"

    result_state: dict[str, Any] = {
        "final_output": final,
        "current_step": len(state.get("plan", [])),
    }

    # Persist state snapshot and log event (best-effort, non-blocking)
    _semantic, episodic, working = _get_memory_clients()

    if working is not None:
        try:
            merged = {**dict(state), **result_state}
            await working.save_state(state["run_id"], merged)
            log.info("[node:output] WorkingMemory snapshot saved for run=%s", state["run_id"])
        except Exception as exc:
            log.warning("[node:output] WorkingMemory save failed: %s", exc)

    if episodic is not None:
        try:
            await episodic.log_event(
                run_id=state["run_id"],
                event={
                    "event_type": "agent.run.completed" if not error else "agent.run.failed",
                    "payload": {
                        "final_output_len": len(final),
                        "total_tool_calls": len(state.get("tool_calls", [])),
                        "citations": state.get("memory_citations", []),
                        "error": error,
                    },
                },
            )
        except Exception as exc:
            log.warning("[node:output] Stream log_event failed: %s", exc)

    return result_state


# ── Helper: advance_step (exposed for graph.py import) ───────────────────────


def _advance_step(state: "AgentState") -> dict[str, Any]:
    """Increment current_step before re-entering tool_executor."""
    return {"current_step": state.get("current_step", 0) + 1}
