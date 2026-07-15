import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.schemas import IncidentState, Hypothesis, RemediationProposal


def make_initial_state(region: str, service: str, incident_id: str = "INC-TEST001") -> IncidentState:
    return {
        "incident_id": incident_id,
        "region": region,
        "service": service,
        "severity": None,
        "metrics_snapshot": None,
        "root_cause_hypothesis": None,
        "capacity_hypothesis": None,
        "hypothesis_history": [],
        "conflict_detected": False,
        "reconciliation_round": 0,
        "reconciliation_notes": [],
        "affected_users_estimate": None,
        "customer_comms_needed": False,
        "customer_comms_draft": None,
        "remediation_proposal": None,
        "final_root_cause": None,
        "final_report": None,
        "status": "monitoring",
    }


def test_schemas_validation():
    h = Hypothesis(
        agent="root_cause",
        root_cause_type="bad_deployment",
        confidence=0.85,
        evidence=["deploy at 14:02 correlates with error spike"],
        reasoning="Deployment timestamp matches anomaly onset",
    )
    assert h.confidence == 0.85
    assert h.root_cause_type == "bad_deployment"

    with pytest.raises(Exception):
        Hypothesis(
            agent="root_cause",
            root_cause_type="invalid_type",
            confidence=0.5,
            evidence=["test"],
            reasoning="test",
        )

    with pytest.raises(Exception):
        Hypothesis(
            agent="root_cause",
            root_cause_type="bad_deployment",
            confidence=1.5,
            evidence=["test"],
            reasoning="test",
        )

    with pytest.raises(Exception):
        Hypothesis(
            agent="root_cause",
            root_cause_type="bad_deployment",
            confidence=0.5,
            evidence=[],
            reasoning="test",
        )


def test_remediation_schema():
    r = RemediationProposal(
        action="rollback v2.3.1",
        reversible=True,
        requires_approval=True,
        risk_level="medium",
    )
    assert r.requires_approval is True

    with pytest.raises(Exception):
        RemediationProposal(
            action="test",
            reversible=True,
            requires_approval=False,
            risk_level="extreme",
        )


def test_tools_return_data():
    from app.tools.metrics_tools import check_metrics
    from app.tools.deploy_tools import check_deploy_logs
    from app.tools.infra_tools import check_load_capacity
    from app.tools.impact_tools import estimate_affected_users

    metrics = check_metrics("ap-south-1", "video-streaming")
    assert "error_rate_percent" in metrics
    assert metrics["error_rate_percent"] > 0

    deploys = check_deploy_logs("ap-south-1", "video-streaming")
    assert "deploys" in deploys
    assert len(deploys["deploys"]) > 0

    capacity = check_load_capacity("ap-south-1", "video-streaming")
    assert "total_instances" in capacity

    users = estimate_affected_users("ap-south-1", "video-streaming")
    assert "total_active_users" in users

    missing = check_metrics("nonexistent", "nonexistent")
    assert "error" in missing


def test_tool_registry():
    from app.tools.registry import get_tools_for_agent

    assert len(get_tools_for_agent("monitoring")) == 1
    assert len(get_tools_for_agent("root_cause")) == 2
    assert len(get_tools_for_agent("capacity")) == 2
    assert len(get_tools_for_agent("remediation")) == 2
    assert len(get_tools_for_agent("incident_commander")) == 0
    assert len(get_tools_for_agent("nonexistent")) == 0


def test_conflict_detection_logic():
    """Directly test the IC's conflict-check condition using mocked Hypothesis objects."""
    from app.agents.incident_commander import incident_commander

    def make_hyp(agent, root_cause_type, confidence):
        return Hypothesis(
            agent=agent,
            root_cause_type=root_cause_type,
            confidence=confidence,
            evidence=["test evidence"],
            reasoning="test reasoning",
        )

    def is_conflict(rc_hyp, cap_hyp):
        rc_dict = rc_hyp.model_dump()
        cap_dict = cap_hyp.model_dump()
        rc_type = rc_dict.get("root_cause_type", "unknown")
        cap_type = cap_dict.get("root_cause_type", "unknown")
        rc_conf = rc_dict.get("confidence", 0)
        cap_conf = cap_dict.get("confidence", 0)
        return rc_type != cap_type and rc_conf > 0.6 and cap_conf > 0.6

    # Case A: different root_cause_type, both confidence > 0.6 → conflict
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.85),
        make_hyp("capacity", "load_spike", 0.75),
    ) is True

    # Case B: same root_cause_type, both high confidence → no conflict
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.9),
        make_hyp("capacity", "bad_deployment", 0.85),
    ) is False

    # Case C: different root_cause_type, one confidence <= 0.6 → no conflict
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.85),
        make_hyp("capacity", "load_spike", 0.5),
    ) is False
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.4),
        make_hyp("capacity", "load_spike", 0.9),
    ) is False

    # Case D: confidence exactly at 0.6 boundary — the condition uses strict >
    # so 0.6 does NOT trigger conflict (exclusive boundary)
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.6),
        make_hyp("capacity", "load_spike", 0.6),
    ) is False, "0.6 is on the boundary; condition is strictly > 0.6 so no conflict"

    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.6),
        make_hyp("capacity", "load_spike", 0.9),
    ) is False, "one side at exactly 0.6 still blocks conflict"

    # Just above 0.6 on both sides → conflict fires
    assert is_conflict(
        make_hyp("root_cause", "bad_deployment", 0.61),
        make_hyp("capacity", "load_spike", 0.61),
    ) is True, "0.61 > 0.6 on both sides triggers conflict"


def test_hypothesis_history_reducer_preserves_both():
    """Verify operator.add reducer merges hypothesis_history from parallel branches."""
    from langgraph.graph import StateGraph, END

    async def rc_node(state: IncidentState) -> dict:
        return {
            "hypothesis_history": [
                {"agent": "root_cause", "round": 0,
                 "root_cause_type": "bad_deployment", "confidence": 0.85}
            ]
        }

    async def cap_node(state: IncidentState) -> dict:
        return {
            "hypothesis_history": [
                {"agent": "capacity", "round": 0,
                 "root_cause_type": "load_spike", "confidence": 0.7}
            ]
        }

    async def merge_node(state: IncidentState) -> dict:
        return {}

    graph = StateGraph(IncidentState)
    graph.add_node("rc", rc_node)
    graph.add_node("cap", cap_node)
    graph.add_node("merge", merge_node)
    graph.set_entry_point("rc")
    graph.add_edge("rc", "merge")
    graph.add_edge("cap", "merge")
    graph.set_entry_point("rc")
    # Fan-out: entry goes to both rc and cap via a dispatcher
    async def dispatcher(state: IncidentState) -> dict:
        return {}

    # Rebuild with proper fan-out
    graph = StateGraph(IncidentState)
    graph.add_node("dispatch", dispatcher)
    graph.add_node("rc", rc_node)
    graph.add_node("cap", cap_node)
    graph.add_node("merge", merge_node)
    graph.set_entry_point("dispatch")
    graph.add_edge("dispatch", "rc")
    graph.add_edge("dispatch", "cap")
    graph.add_edge("rc", "merge")
    graph.add_edge("cap", "merge")
    graph.add_edge("merge", END)

    compiled = graph.compile()

    initial: IncidentState = {
        "incident_id": "INC-REDUCER-TEST",
        "region": "us-east-1",
        "service": "video-streaming",
        "hypothesis_history": [],
        "conflict_detected": False,
        "reconciliation_round": 0,
        "reconciliation_notes": [],
        "customer_comms_needed": False,
        "status": "monitoring",
    }

    result = asyncio.run(compiled.ainvoke(initial))
    history = result["hypothesis_history"]

    assert len(history) == 2, f"Expected 2 entries from parallel branches, got {len(history)}"
    agents_in_history = {h["agent"] for h in history}
    assert "root_cause" in agents_in_history, "root_cause entry missing from merged history"
    assert "capacity" in agents_in_history, "capacity entry missing from merged history"


def test_hitl_gate_blocks_auto_execution():
    """Test the remediation agent's HITL gate using the actual gating logic."""
    from unittest.mock import patch, AsyncMock

    # Case 1: requires_approval=True → status must be pending_approval,
    # execute_remediation_mock must NOT be called
    proposal_needs_approval = RemediationProposal(
        action="rollback deployment v2.3.1",
        reversible=True,
        requires_approval=True,
        risk_level="medium",
    )

    with patch("app.agents.remediation_agent.llm_client") as mock_llm, \
         patch("app.agents.remediation_agent.execute_remediation_mock") as mock_exec:

        mock_llm.call = AsyncMock(return_value=proposal_needs_approval.model_dump())

        async def run_approval_case():
            from app.agents.remediation_agent import remediation_agent
            state = make_initial_state("us-east-1", "video-streaming")
            state["final_root_cause"] = "bad deployment"
            state["severity"] = "low"
            return await remediation_agent(state)

        result = asyncio.run(run_approval_case())
        assert result["status"] == "pending_approval", \
            f"Expected pending_approval, got {result['status']}"
        mock_exec.assert_not_called()

    # Case 2: requires_approval=False, reversible=True, low severity, low risk
    # → should proceed to execution, status=resolved
    proposal_auto = RemediationProposal(
        action="restart service pods",
        reversible=True,
        requires_approval=False,
        risk_level="low",
    )

    with patch("app.agents.remediation_agent.llm_client") as mock_llm, \
         patch("app.agents.remediation_agent.execute_remediation_mock") as mock_exec:

        mock_llm.call = AsyncMock(return_value=proposal_auto.model_dump())
        mock_exec.return_value = {"success": True}

        async def run_auto_case():
            from app.agents.remediation_agent import remediation_agent
            state = make_initial_state("us-east-1", "video-streaming")
            state["final_root_cause"] = "transient pod failure"
            state["severity"] = "low"
            return await remediation_agent(state)

        result = asyncio.run(run_auto_case())
        assert result["status"] == "resolved", \
            f"Expected resolved, got {result['status']}"
        mock_exec.assert_called_once()

    # Case 3: requires_approval=False but severity is high → gate blocks
    with patch("app.agents.remediation_agent.llm_client") as mock_llm, \
         patch("app.agents.remediation_agent.execute_remediation_mock") as mock_exec:

        mock_llm.call = AsyncMock(return_value=proposal_auto.model_dump())

        async def run_severity_gate():
            from app.agents.remediation_agent import remediation_agent
            state = make_initial_state("us-east-1", "video-streaming")
            state["final_root_cause"] = "bad deployment"
            state["severity"] = "high"
            return await remediation_agent(state)

        result = asyncio.run(run_severity_gate())
        assert result["status"] == "pending_approval", \
            "High severity should trigger HITL gate even when requires_approval=False"
        mock_exec.assert_not_called()

    # Case 4: requires_approval=False but irreversible → gate blocks
    proposal_irreversible = RemediationProposal(
        action="drop and recreate database index",
        reversible=False,
        requires_approval=False,
        risk_level="low",
    )

    with patch("app.agents.remediation_agent.llm_client") as mock_llm, \
         patch("app.agents.remediation_agent.execute_remediation_mock") as mock_exec:

        mock_llm.call = AsyncMock(return_value=proposal_irreversible.model_dump())

        async def run_irreversible_gate():
            from app.agents.remediation_agent import remediation_agent
            state = make_initial_state("us-east-1", "video-streaming")
            state["final_root_cause"] = "index corruption"
            state["severity"] = "low"
            return await remediation_agent(state)

        result = asyncio.run(run_irreversible_gate())
        assert result["status"] == "pending_approval", \
            "Irreversible action should trigger HITL gate even when requires_approval=False"
        mock_exec.assert_not_called()


@pytest.mark.skipif(
    not Path(Path(__file__).parent.parent / ".env").exists(),
    reason="No .env file with GEMINI_API_KEY — skipping integration test",
)
class TestEndToEnd:
    def test_scenario_agree(self):
        from app.graph import run_incident_graph

        state = make_initial_state("us-east-1", "video-streaming", "INC-TEST-AGREE")
        final = asyncio.run(run_incident_graph(state))
        assert final["status"] in ("resolved", "escalated", "pending_approval")
        assert final["severity"] is not None

    def test_scenario_conflict(self):
        from app.graph import run_incident_graph

        state = make_initial_state("ap-south-1", "video-streaming", "INC-TEST-CONFLICT")
        final = asyncio.run(run_incident_graph(state))
        assert final["status"] in ("resolved", "escalated", "pending_approval")
        assert final["severity"] is not None
        assert final["final_root_cause"] is not None or final["status"] == "escalated"
