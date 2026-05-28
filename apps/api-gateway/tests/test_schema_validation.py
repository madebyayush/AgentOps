"""
Pydantic Schema Validation Tests
Tests edge cases and rejection rules for all request schemas.
"""
from __future__ import annotations

import uuid
import pytest
from pydantic import ValidationError

from app.models.agents import AgentCreate, AgentRunRequest
from app.models.memory import MemoryEntryCreate
from app.models.tools import ToolInvokeRequest
from app.models.workflows import WorkflowCreate, WorkflowExecuteRequest
from app.models.hitl import HitlDecisionRequest
from app.models.incidents import IncidentCreate, IncidentUpdateRequest
from app.db.models import IncidentSeverity, IncidentStatus


class TestAgentSchema:
    def test_agent_create_valid(self):
        a = AgentCreate(name="my-agent", type="researcher")
        assert a.name == "my-agent"

    def test_agent_name_spaces_rejected(self):
        with pytest.raises(ValidationError) as exc:
            AgentCreate(name="bad name", type="researcher")
        assert "spaces" in str(exc.value).lower()

    def test_agent_name_empty_rejected(self):
        with pytest.raises(ValidationError):
            AgentCreate(name="", type="researcher")

    def test_agent_run_request_prompt_required(self):
        with pytest.raises(ValidationError):
            AgentRunRequest(prompt="")  # min_length=1

    def test_agent_run_request_max_steps_clamped(self):
        with pytest.raises(ValidationError):
            AgentRunRequest(prompt="do it", max_steps=999)  # max=200

    def test_agent_run_request_defaults(self):
        r = AgentRunRequest(prompt="Hello agent")
        assert r.max_steps == 25
        assert r.require_hitl is False
        assert r.context == {}


class TestMemorySchema:
    def test_memory_entry_valid(self):
        m = MemoryEntryCreate(namespace="ns1", content="hello world")
        assert m.namespace == "ns1"

    def test_memory_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            MemoryEntryCreate(namespace="ns1", content="")

    def test_memory_namespace_required(self):
        with pytest.raises(ValidationError):
            MemoryEntryCreate(namespace="", content="data")


class TestToolSchema:
    def test_tool_invoke_valid(self):
        t = ToolInvokeRequest(tool_name="search-web", arguments={"q": "test"})
        assert t.tool_name == "search-web"

    def test_tool_invoke_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ToolInvokeRequest(tool_name="")


class TestWorkflowSchema:
    def test_workflow_create_valid(self):
        wf = WorkflowCreate(name="my-flow", graph_json={"nodes": []})
        assert wf.name == "my-flow"
        assert wf.graph_json == {"nodes": []}

    def test_workflow_execute_dry_run_default(self):
        e = WorkflowExecuteRequest(inputs={})
        assert e.dry_run is False

    def test_workflow_execute_dry_run_true(self):
        e = WorkflowExecuteRequest(inputs={"k": "v"}, dry_run=True)
        assert e.dry_run is True


class TestHitlSchema:
    def test_hitl_decision_valid(self):
        d = HitlDecisionRequest(approved_by="engineer-alice")
        assert d.approved_by == "engineer-alice"
        assert d.rejection_reason is None

    def test_hitl_decision_empty_approved_by_rejected(self):
        with pytest.raises(ValidationError):
            HitlDecisionRequest(approved_by="")

    def test_hitl_validate_rejection_requires_reason(self):
        d = HitlDecisionRequest(approved_by="bob", rejection_reason=None)
        with pytest.raises(ValueError, match="rejection_reason"):
            d.validate_rejection("reject")

    def test_hitl_validate_rejection_with_reason_ok(self):
        d = HitlDecisionRequest(approved_by="bob", rejection_reason="Too risky")
        d.validate_rejection("reject")  # Should not raise


class TestIncidentSchema:
    def test_incident_create_all_severities(self):
        for sev in ("low", "medium", "high", "critical"):
            inc = IncidentCreate(severity=sev, description=f"{sev} incident")
            assert inc.severity.value == sev

    def test_incident_invalid_severity(self):
        with pytest.raises(ValidationError):
            IncidentCreate(severity="extreme", description="bad")

    def test_incident_update_partial(self):
        u = IncidentUpdateRequest(status="resolved")
        assert u.status == IncidentStatus.resolved
        assert u.root_cause is None

    def test_incident_update_all_none_valid(self):
        # All-None patch is technically valid at schema level (business logic validates separately)
        u = IncidentUpdateRequest()
        assert u.status is None
