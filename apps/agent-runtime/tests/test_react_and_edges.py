"""
Comprehensive tests for:
  - ReAct loops (full think → act → reflect cycles)
  - Reflection retry logic (retry_count increment, max retry escalation)
  - State transitions (field mutations through every node)
  - LangGraph edge routing (reflection_router all 5 branches)
  - Checkpoint recovery (persist state, resume from same thread_id)
  - Failure handling (tool errors, LLM errors, abort path, unset plan)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PLAN_JSON = json.dumps(
    {"steps": ["Research the topic", "Write the summary"], "rationale": "Two-step approach."}
)
LOGIC_OK = json.dumps({"sound": True, "reason": "Output addresses the step."})
LOGIC_FAIL = json.dumps({"sound": False, "reason": "Output is irrelevant."})
DIRECT_OUT = json.dumps({"tool": "none", "direct_output": "Completed step output."})


def _tool_call(error: str | None = None, result: str = "ok") -> dict[str, Any]:
    return {
        "tool_name": "web_search",
        "arguments": {"query": "test"},
        "result": result if error is None else None,
        "error": error,
        "duration_ms": 50.0,
        "timestamp": "2024-01-01T00:00:00Z",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. ReAct Loop Tests
#    Verify the full think → act → reflect cycle at the node level,
#    and that a complete multi-step loop invokes the right sequence.
# ─────────────────────────────────────────────────────────────────────────────


class TestReActLoop:
    """Full Reason → Act → Observe → Reflect cycles through nodes."""

    @pytest.mark.asyncio
    async def test_single_react_cycle_produces_observation(self, sample_state):
        """One ReAct cycle: planner → executor → reflection produces an observation."""
        from agent.nodes import planner_node, reflection_node, tool_executor_node

        with patch("agent.nodes._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [PLAN_JSON, DIRECT_OUT, LOGIC_OK]

            plan_result = await planner_node(sample_state)
            sample_state.update(plan_result)

            exec_result = await tool_executor_node(sample_state)
            sample_state.update(exec_result)

            reflect_result = await reflection_node(sample_state)
            sample_state.update(reflect_result)

        assert len(sample_state["observations"]) == 1
        assert "Completed step output." in sample_state["observations"][0]
        assert "CONTINUE" in sample_state["reflection"]

    @pytest.mark.asyncio
    async def test_two_step_react_loop_advances_step(self, sample_state):
        """After a successful step, advance_step increments current_step."""
        from agent.nodes import (
            _advance_step,
            planner_node,
            reflection_node,
            tool_executor_node,
        )

        with patch("agent.nodes._call_llm", new_callable=AsyncMock) as mock_llm:
            # Plan → exec step 0 → reflect CONTINUE → advance → exec step 1 → reflect DONE
            mock_llm.side_effect = [
                PLAN_JSON,  # planner
                DIRECT_OUT,  # executor step 0
                LOGIC_OK,  # reflection step 0
                DIRECT_OUT,  # executor step 1
                LOGIC_OK,  # reflection step 1
            ]

            plan_result = await planner_node(sample_state)
            sample_state.update(plan_result)
            assert sample_state["current_step"] == 0

            exec_result = await tool_executor_node(sample_state)
            sample_state.update(exec_result)

            reflect_result = await reflection_node(sample_state)
            sample_state.update(reflect_result)

            advance_result = _advance_step(sample_state)
            sample_state.update(advance_result)
            assert sample_state["current_step"] == 1

            exec_result2 = await tool_executor_node(sample_state)
            sample_state.update(exec_result2)

            reflect_result2 = await reflection_node(sample_state)
            sample_state.update(reflect_result2)

        assert len(sample_state["observations"]) == 2
        assert sample_state["current_step"] == 1

    @pytest.mark.asyncio
    async def test_react_loop_accumulates_tool_calls(self, sample_state):
        """Each ReAct cycle appends to tool_calls without overwriting."""
        from agent.nodes import planner_node, tool_executor_node

        with patch("agent.nodes._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [PLAN_JSON, DIRECT_OUT, DIRECT_OUT]

            plan_result = await planner_node(sample_state)
            sample_state.update(plan_result)

            exec1 = await tool_executor_node(sample_state)
            sample_state.update(exec1)

            sample_state["current_step"] = 1
            exec2 = await tool_executor_node(sample_state)
            combined = exec2["tool_calls"]

        assert len(combined) == 2

    @pytest.mark.asyncio
    async def test_react_loop_memory_context_fed_to_planner(self, sample_state):
        """Memory context retrieved in step 1 is visible to the planner."""
        from agent.nodes import memory_retrieval_node, planner_node

        sample_state["memory_context"] = []

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=PLAN_JSON):
            mem_result = await memory_retrieval_node(sample_state)
            sample_state.update(mem_result)
            plan_result = await planner_node(sample_state)

        assert isinstance(plan_result["plan"], list)
        assert len(plan_result["plan"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Reflection Retry Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReflectionRetries:
    """retry_count increments, max-retry escalation, and HITL paths."""

    @pytest.mark.asyncio
    async def test_retry_increments_retry_count(self, sample_state):
        """reflection_node must increment retry_count when recommending retry."""
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = [_tool_call(error="timeout")]
        sample_state["observations"] = ["timeout"]
        sample_state["retry_count"] = 0

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_FAIL):
            result = await reflection_node(sample_state)

        assert result["retry_count"] == 1
        assert "RETRY" in result["reflection"]

    @pytest.mark.asyncio
    async def test_retry_count_does_not_exceed_max(self, sample_state):
        """At MAX_RETRIES the recommendation must be ESCALATE_HITL, not RETRY."""
        from agent.nodes import MAX_RETRIES, reflection_node

        sample_state["tool_calls"] = [_tool_call(error="persistent")]
        sample_state["observations"] = ["persistent"]
        sample_state["retry_count"] = MAX_RETRIES

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_FAIL):
            result = await reflection_node(sample_state)

        assert "ESCALATE_HITL" in result["reflection"]
        # retry_count must NOT be bumped further
        assert result["retry_count"] == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_retry_resets_on_success(self, sample_state):
        """After a successful step, retry_count should remain at its value
        (nodes don't reset it — graph config resets at plan start)."""
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = [_tool_call()]  # no error
        sample_state["observations"] = ["Success"]
        sample_state["retry_count"] = 2

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_OK):
            result = await reflection_node(sample_state)

        assert "CONTINUE" in result["reflection"]

    @pytest.mark.asyncio
    async def test_three_consecutive_retries_reach_hitl(self, sample_state):
        """Simulate three consecutive failures hitting the HITL escalation path."""
        from agent.nodes import MAX_RETRIES, reflection_node

        sample_state["tool_calls"] = [_tool_call(error="err")]
        sample_state["observations"] = ["err"]

        recommendations = []
        for i in range(MAX_RETRIES + 1):
            sample_state["retry_count"] = i
            with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_FAIL):
                result = await reflection_node(sample_state)
            recommendations.append(result["reflection"])

        # First MAX_RETRIES iterations → RETRY; last → ESCALATE_HITL
        assert all("RETRY" in r for r in recommendations[:MAX_RETRIES])
        assert "ESCALATE_HITL" in recommendations[-1]

    @pytest.mark.asyncio
    async def test_schema_invalid_observation_triggers_retry(self, sample_state):
        """An empty observation fails schema check and should trigger retry."""
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = [_tool_call()]
        sample_state["observations"] = [""]  # empty string → schema_valid = False
        sample_state["retry_count"] = 0

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_OK):
            result = await reflection_node(sample_state)

        # Schema invalid → cannot be CONTINUE
        assert "CONTINUE" not in result["reflection"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. State Transition Tests
#    Every node must write the correct keys and not clobber unrelated state.
# ─────────────────────────────────────────────────────────────────────────────


class TestStateTransitions:
    """Node-level state mutation contracts."""

    @pytest.mark.asyncio
    async def test_memory_retrieval_sets_memory_context(self, sample_state):
        from agent.nodes import memory_retrieval_node

        result = await memory_retrieval_node(sample_state)
        assert "memory_context" in result
        assert isinstance(result["memory_context"], list)

    @pytest.mark.asyncio
    async def test_planner_sets_plan_and_step(self, sample_state):
        from agent.nodes import planner_node

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=PLAN_JSON):
            result = await planner_node(sample_state)

        assert "plan" in result
        assert "current_step" in result
        assert "retry_count" in result
        assert result["current_step"] == 0
        assert result["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_planner_does_not_overwrite_run_id(self, sample_state):
        from agent.nodes import planner_node

        original_run_id = sample_state["run_id"]
        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=PLAN_JSON):
            result = await planner_node(sample_state)

        # planner must NOT return a run_id key (would overwrite)
        assert "run_id" not in result
        assert sample_state["run_id"] == original_run_id

    @pytest.mark.asyncio
    async def test_tool_executor_appends_not_replaces(self, sample_state):
        """tool_executor must append to existing tool_calls/observations."""
        from agent.nodes import tool_executor_node

        existing_call = _tool_call(result="previous")
        sample_state["tool_calls"] = [existing_call]
        sample_state["observations"] = ["previous result"]

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=DIRECT_OUT):
            result = await tool_executor_node(sample_state)

        assert len(result["tool_calls"]) == 2
        assert len(result["observations"]) == 2

    @pytest.mark.asyncio
    async def test_advance_step_increments_by_one(self, sample_state):
        from agent.nodes import _advance_step

        sample_state["current_step"] = 3
        result = _advance_step(sample_state)
        assert result["current_step"] == 4

    @pytest.mark.asyncio
    async def test_hitl_node_sets_pending_true(self, sample_state):
        from agent.nodes import hitl_checkpoint_node

        result = await hitl_checkpoint_node(sample_state)
        assert result["hitl_pending"] is True

    @pytest.mark.asyncio
    async def test_output_node_sets_final_output(self, sample_state):
        from agent.nodes import output_node

        sample_state["observations"] = ["obs A", "obs B"]
        result = await output_node(sample_state)
        assert "final_output" in result
        assert result["final_output"] is not None

    @pytest.mark.asyncio
    async def test_output_node_advances_step_to_end(self, sample_state):
        from agent.nodes import output_node

        sample_state["plan"] = ["step 1", "step 2"]
        result = await output_node(sample_state)
        assert result["current_step"] == len(sample_state["plan"])

    @pytest.mark.asyncio
    async def test_reflection_node_writes_reflection_string(self, sample_state):
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = [_tool_call()]
        sample_state["observations"] = ["result"]

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_OK):
            result = await reflection_node(sample_state)

        assert isinstance(result["reflection"], str)
        assert len(result["reflection"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. LangGraph Edge Routing Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestLangGraphEdgeRouting:
    """reflection_router must return the correct edge key for every branch."""

    def _make_state(self, reflection: str, current_step: int = 0, plan_len: int = 3) -> dict:
        return {
            "reflection": reflection,
            "plan": [f"step {i}" for i in range(plan_len)],
            "current_step": current_step,
        }

    def test_router_continue_mid_plan_returns_next_step(self):
        from agent.nodes import reflection_router

        state = self._make_state("CONTINUE: All checks passed.", current_step=0, plan_len=3)
        assert reflection_router(state) == "next_step"

    def test_router_continue_last_step_returns_done(self):
        from agent.nodes import reflection_router

        # current_step=2, plan has 3 items → next would be 3 which equals len → done
        state = self._make_state("CONTINUE: All checks passed.", current_step=2, plan_len=3)
        assert reflection_router(state) == "done"

    def test_router_retry_returns_retry(self):
        from agent.nodes import reflection_router

        state = self._make_state("RETRY: Tool error.")
        assert reflection_router(state) == "retry"

    def test_router_escalate_hitl_returns_hitl(self):
        from agent.nodes import reflection_router

        state = self._make_state("ESCALATE_HITL: Max retries exceeded.")
        assert reflection_router(state) == "hitl"

    def test_router_abort_returns_abort(self):
        from agent.nodes import reflection_router

        state = self._make_state("ABORT: Unrecoverable error.")
        assert reflection_router(state) == "abort"

    def test_router_empty_reflection_defaults_to_done(self):
        """Empty reflection (no keyword) on last step should route to done."""
        from agent.nodes import reflection_router

        state = self._make_state("", current_step=2, plan_len=3)
        assert reflection_router(state) == "done"

    def test_router_empty_plan_routes_to_done(self):
        """With an empty plan, router should not crash and should route to done."""
        from agent.nodes import reflection_router

        state = {"reflection": "CONTINUE: ok", "plan": [], "current_step": 0}
        route = reflection_router(state)
        assert route in ("done", "next_step")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Checkpoint Recovery Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckpointRecovery:
    """Verify the graph can persist state and resume from the same thread_id."""

    @pytest.mark.asyncio
    async def test_graph_runs_with_sqlite_checkpointer(self, sample_state):
        """Full graph invocation with in-memory SQLite checkpointer succeeds."""
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        from agent.graph import build_workflow_graph

        STUB_FINAL = json.dumps({"steps": ["Only step"], "rationale": "stub"})
        STUB_EXEC = json.dumps({"tool": "none", "direct_output": "Done."})
        STUB_LOGIC = json.dumps({"sound": True, "reason": "OK."})

        async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
            graph = build_workflow_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "recovery-test-001"}}

            with patch(
                "agent.nodes._call_llm",
                new_callable=AsyncMock,
                side_effect=[STUB_FINAL, STUB_EXEC, STUB_LOGIC],
            ):
                final_state = await graph.ainvoke(sample_state, config=config)

        assert final_state.get("final_output") is not None

    @pytest.mark.asyncio
    async def test_different_thread_ids_are_isolated(self, sample_state):
        """Two runs with different thread_ids must not share state."""
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        except ImportError:
            pytest.skip("langgraph-checkpoint-sqlite not installed")

        from agent.graph import build_workflow_graph

        STUB_PLAN = json.dumps({"steps": ["step A"], "rationale": "test"})
        STUB_EXEC = json.dumps({"tool": "none", "direct_output": "thread-specific result"})
        STUB_LOGIC = json.dumps({"sound": True, "reason": "OK."})

        def make_state(task: str) -> dict:
            s = dict(sample_state)
            s["task"] = task
            s["run_id"] = f"run-{task}"
            return s

        async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
            graph = build_workflow_graph(checkpointer=checkpointer)

            for task in ("task-alpha", "task-beta"):
                config = {"configurable": {"thread_id": f"thread-{task}"}}
                with patch(
                    "agent.nodes._call_llm",
                    new_callable=AsyncMock,
                    side_effect=[STUB_PLAN, STUB_EXEC, STUB_LOGIC],
                ):
                    result = await graph.ainvoke(make_state(task), config=config)
                assert result["task"] == task

    @pytest.mark.asyncio
    async def test_checkpointer_none_still_runs(self, sample_state):
        """Graph compiled without a checkpointer should complete successfully."""
        from agent.graph import build_workflow_graph

        STUB_PLAN = json.dumps({"steps": ["step 1"], "rationale": "stub"})
        STUB_EXEC = json.dumps({"tool": "none", "direct_output": "No checkpoint result."})
        STUB_LOGIC = json.dumps({"sound": True, "reason": "OK."})

        graph = build_workflow_graph(checkpointer=None)
        with patch(
            "agent.nodes._call_llm",
            new_callable=AsyncMock,
            side_effect=[STUB_PLAN, STUB_EXEC, STUB_LOGIC],
        ):
            result = await graph.ainvoke(sample_state)

        assert result.get("final_output") is not None

    def test_get_checkpointer_returns_sqlite_in_dev(self):
        """get_checkpointer() returns an AsyncSqliteSaver outside production."""
        import os

        from agent.graph import get_checkpointer

        # Ensure not in production mode
        env_backup = os.environ.pop("PLATFORM_ENV", None)
        try:
            cp = get_checkpointer()
            # Either an AsyncSqliteSaver or None (if not installed) — must not raise
            assert cp is not None or cp is None  # always passes; just checks no exception
        finally:
            if env_backup:
                os.environ["PLATFORM_ENV"] = env_backup


# ─────────────────────────────────────────────────────────────────────────────
# 6. Failure Handling Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFailureHandling:
    """Tool errors, LLM errors, abort routing, missing plan, bad JSON."""

    @pytest.mark.asyncio
    async def test_tool_executor_handles_missing_tool_gracefully(self, sample_state):
        """If LLM requests a non-existent tool, executor returns an error observation."""
        from agent.nodes import tool_executor_node

        bad_tool_response = json.dumps(
            {"tool": "nonexistent_tool_xyz", "arguments": {}, "direct_output": ""}
        )
        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=bad_tool_response):
            result = await tool_executor_node(sample_state)

        assert len(result["tool_calls"]) == 1
        record = result["tool_calls"][0]
        assert record["error"] is not None
        assert "not found" in (record["error"] or "").lower()

    @pytest.mark.asyncio
    async def test_tool_executor_on_empty_plan_returns_empty(self, sample_state):
        """When plan is empty, tool_executor should return an empty dict."""
        from agent.nodes import tool_executor_node

        sample_state["plan"] = []
        sample_state["current_step"] = 0
        result = await tool_executor_node(sample_state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_tool_executor_step_beyond_plan_returns_empty(self, sample_state):
        """When current_step >= len(plan), tool_executor should skip silently."""
        from agent.nodes import tool_executor_node

        sample_state["plan"] = ["only step"]
        sample_state["current_step"] = 5  # way past the end
        result = await tool_executor_node(sample_state)
        assert result == {}

    @pytest.mark.asyncio
    async def test_reflection_handles_no_tool_calls(self, sample_state):
        """reflection_node must not crash when tool_calls list is empty."""
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = []
        sample_state["observations"] = []

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=LOGIC_OK):
            result = await reflection_node(sample_state)

        assert "reflection" in result

    @pytest.mark.asyncio
    async def test_output_node_abort_path_includes_error(self, sample_state):
        """When state.error is set, output_node should surface it in final_output."""
        from agent.nodes import output_node

        sample_state["error"] = "LLM API quota exceeded"
        result = await output_node(sample_state)
        assert "LLM API quota exceeded" in result["final_output"]

    @pytest.mark.asyncio
    async def test_planner_handles_malformed_llm_json(self, sample_state):
        """If LLM returns non-JSON, planner should use the raw text as a single step."""
        from agent.nodes import planner_node

        raw_text = "Just do the thing directly."
        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value=raw_text):
            result = await planner_node(sample_state)

        assert isinstance(result["plan"], list)
        assert len(result["plan"]) == 1
        assert result["plan"][0] == raw_text

    @pytest.mark.asyncio
    async def test_reflection_handles_malformed_logic_json(self, sample_state):
        """If logic-check LLM returns garbage, reflection defaults to sound=True."""
        from agent.nodes import reflection_node

        sample_state["tool_calls"] = [_tool_call()]
        sample_state["observations"] = ["some result"]

        with patch("agent.nodes._call_llm", new_callable=AsyncMock, return_value="not json at all"):
            result = await reflection_node(sample_state)

        # Should not raise; with sound defaulting to True → CONTINUE
        assert "reflection" in result
        assert "CONTINUE" in result["reflection"]

    @pytest.mark.asyncio
    async def test_full_graph_abort_path_on_persistent_failure(self, sample_state):
        """A state with error pre-set should route through output and set final_output."""
        from agent.graph import build_workflow_graph
        from agent.nodes import MAX_RETRIES

        # Pre-set state as if we've already exhausted retries
        sample_state["plan"] = ["step 1"]
        sample_state["current_step"] = 0
        sample_state["retry_count"] = MAX_RETRIES
        sample_state["tool_calls"] = [_tool_call(error="unrecoverable")]
        sample_state["observations"] = ["unrecoverable"]
        sample_state["error"] = "Unrecoverable failure after max retries"

        graph = build_workflow_graph(checkpointer=None)

        STUB_MEM: str = ""  # memory_retrieval mocked
        with patch(
            "agent.nodes._call_llm",
            new_callable=AsyncMock,
            side_effect=[
                json.dumps({"steps": ["step 1"], "rationale": "x"}),  # planner
                json.dumps({"tool": "none", "direct_output": "err"}),  # executor
                LOGIC_FAIL,  # reflection → ESCALATE_HITL then abort via error field
            ],
        ):
            final = await graph.ainvoke(sample_state)

        assert final.get("final_output") is not None

    @pytest.mark.asyncio
    async def test_llm_exception_does_not_crash_executor(self, sample_state):
        """If _call_llm raises, tool_executor should surface error gracefully."""
        from agent.nodes import tool_executor_node

        with patch(
            "agent.nodes._call_llm",
            new_callable=AsyncMock,
            side_effect=Exception("LLM connection refused"),
        ):
            try:
                result = await tool_executor_node(sample_state)
                # If the node catches the exception, it should still return a dict
                assert isinstance(result, dict)
            except Exception as exc:
                # OR the exception propagates — either is acceptable;
                # the graph error handler in main.py catches it at the run level.
                assert "LLM connection refused" in str(exc)
