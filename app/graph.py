"""
LangGraph StateGraph definition for Sentinel.

Graph topology:
    monitoring ──┬──> root_cause ────────┐
                 ├──> capacity ──────────┼──> incident_commander ──(conditional)──┐
                 └──> customer_impact ───┘         │                              │
                                                   │  if status=="reconciling"    │
                 ┌─────────────────────────────────┘                              │
                 │                                                                │
                 ├──> root_cause_reeval ──┬──> incident_commander   (loop back)   │
                 └──> capacity_reeval ───┘                                        │
                                                                                  │
                 if status in (resolved, escalated) ──────────────────────────────┘
                         │
                         v
                    remediation ──> postmortem ──> END

Fan-in: LangGraph automatically waits for ALL upstream branches to complete
before firing incident_commander. No manual gate needed.

Reconciliation loop: add_conditional_edges routes IC back to re-evaluation
nodes when conflict is detected and rounds remain.
"""

import json
import logging
import time

from langgraph.graph import END, StateGraph

from app.agents.capacity_agent import capacity_agent
from app.agents.customer_impact_agent import customer_impact_agent
from app.agents.incident_commander import incident_commander
from app.agents.monitoring_agent import monitoring_agent
from app.agents.postmortem_agent import postmortem_agent
from app.agents.remediation_agent import remediation_agent
from app.agents.root_cause_agent import root_cause_agent
from app.core.schemas import IncidentState
from app.tracing import AgentTrace, TraceEvent, get_or_create_trace
from app.observability import (
    agent_invocations_total,
    conflicts_detected_total,
    hypothesis_revisions_total,
    incident_duration_seconds,
    incidents_by_final_status,
    incidents_total,
    reconciliation_rounds_total,
)

logger = logging.getLogger("sentinel")


# ---------------------------------------------------------------------------
# Node wrappers — each returns a partial state dict that LangGraph merges
# via the reducers defined on IncidentState.
# ---------------------------------------------------------------------------

async def node_monitoring(state: IncidentState) -> dict:
    print(f"\n[MONITORING] Analyzing metrics for {state['region']}/{state['service']}...")
    agent_invocations_total.labels(agent="monitoring", phase="initial").inc()
    t = get_or_create_trace(state["incident_id"])
    at = AgentTrace(agent="monitoring", phase="initial")
    result = await monitoring_agent(state)
    sev = result.get("severity")
    at.end_time = time.time()
    at.hypothesis = {"severity": sev}
    at.events.append(TraceEvent(agent="monitoring", event_type="classification",
                                data={"severity": sev, "metrics": result.get("metrics_snapshot", {})}))
    t.add_agent_trace(at)
    t.add_flow_event("monitoring", "root_cause", "fan_out")
    t.add_flow_event("monitoring", "capacity", "fan_out")
    t.add_flow_event("monitoring", "customer_impact", "fan_out")
    print(f"  -> Severity classified: {sev}")
    return result


async def node_root_cause(state: IncidentState) -> dict:
    round_num = state.get("reconciliation_round", 0)
    label = f" (reconciliation round {round_num})" if round_num > 0 else ""
    print(f"\n[ROOT CAUSE{label}] Investigating deployment/software issues...")
    result = await root_cause_agent(state)
    hyp = result.get("root_cause_hypothesis")
    if hyp:
        h = hyp.model_dump() if hasattr(hyp, "model_dump") else hyp
        print(f"  -> Hypothesis: {h.get('root_cause_type')} (confidence: {h.get('confidence', 0):.2f})")
    return result


async def node_capacity(state: IncidentState) -> dict:
    round_num = state.get("reconciliation_round", 0)
    label = f" (reconciliation round {round_num})" if round_num > 0 else ""
    print(f"\n[CAPACITY{label}] Investigating load/scaling issues...")
    result = await capacity_agent(state)
    hyp = result.get("capacity_hypothesis")
    if hyp:
        h = hyp.model_dump() if hasattr(hyp, "model_dump") else hyp
        print(f"  -> Hypothesis: {h.get('root_cause_type')} (confidence: {h.get('confidence', 0):.2f})")
    return result


async def node_customer_impact(state: IncidentState) -> dict:
    print(f"\n[CUSTOMER IMPACT] Estimating blast radius...")
    agent_invocations_total.labels(agent="customer_impact", phase="initial").inc()
    t = get_or_create_trace(state["incident_id"])
    at = AgentTrace(agent="customer_impact", phase="initial")
    result = await customer_impact_agent(state)
    at.end_time = time.time()
    at.hypothesis = {
        "affected_users": result.get("affected_users_estimate"),
        "comms_needed": result.get("customer_comms_needed"),
        "comms_draft": result.get("customer_comms_draft"),
    }
    at.events.append(TraceEvent(agent="customer_impact", event_type="assessment", data=at.hypothesis))
    t.add_agent_trace(at)
    print(f"  -> Affected users: {result.get('affected_users_estimate', 'unknown')}")
    print(f"  -> Comms needed: {result.get('customer_comms_needed', False)}")
    return result


async def node_incident_commander(state: IncidentState) -> dict:
    round_num = state.get("reconciliation_round", 0)
    phase = "reconciliation" if round_num > 0 else "initial"
    print(f"\n[INCIDENT COMMANDER] Evaluating hypotheses (round {round_num})...")
    agent_invocations_total.labels(agent="incident_commander", phase=phase).inc()

    t = get_or_create_trace(state["incident_id"])
    at = AgentTrace(agent="incident_commander", phase=phase, round_num=round_num)

    prior_history = state.get("hypothesis_history", [])
    result = await incident_commander(state)
    status = result.get("status", "unknown")
    at.end_time = time.time()

    if status == "reconciling":
        conflicts_detected_total.inc()
        reconciliation_rounds_total.inc()
        notes = result.get("reconciliation_notes", [])
        question = notes[-1] if isinstance(notes, list) and notes else ""
        at.events.append(TraceEvent(agent="incident_commander", event_type="conflict_detected",
                                    data={"question": question, "round": round_num}))
        at.hypothesis = {"decision": "reconcile", "question": question}
        t.add_flow_event("incident_commander", "root_cause", "reconciliation_request", {"question": question})
        t.add_flow_event("incident_commander", "capacity", "reconciliation_request", {"question": question})
        print(f"  !! CONFLICT DETECTED — requesting reconciliation")
        if notes:
            print(f"  IC question: {notes[-1] if isinstance(notes, list) else notes}")
    else:
        for agent_name in ("root_cause", "capacity"):
            entries = [h for h in prior_history if h["agent"] == agent_name]
            if len(entries) >= 2 and entries[-1]["root_cause_type"] != entries[-2]["root_cause_type"]:
                hypothesis_revisions_total.labels(agent=agent_name).inc()
                at.events.append(TraceEvent(agent="incident_commander", event_type="revision_detected",
                                            data={"agent": agent_name,
                                                  "from": entries[-2]["root_cause_type"],
                                                  "to": entries[-1]["root_cause_type"]}))
        at.events.append(TraceEvent(agent="incident_commander", event_type="decision",
                                    data={"status": status, "final_root_cause": result.get("final_root_cause", "")}))
        at.hypothesis = {"decision": status, "final_root_cause": result.get("final_root_cause")}
        t.add_flow_event("incident_commander", "remediation", "proceed",
                         {"status": status, "root_cause": result.get("final_root_cause", "")})
        print(f"  -> Status: {status}")
        if result.get("final_root_cause"):
            print(f"  -> Final root cause: {result['final_root_cause']}")

    t.add_agent_trace(at)
    return result


async def node_remediation(state: IncidentState) -> dict:
    print(f"\n[REMEDIATION] Proposing remediation action...")
    agent_invocations_total.labels(agent="remediation", phase="initial").inc()
    t = get_or_create_trace(state["incident_id"])
    at = AgentTrace(agent="remediation", phase="initial")
    result = await remediation_agent(state)
    at.end_time = time.time()
    proposal = result.get("remediation_proposal")
    if proposal:
        p = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        at.hypothesis = p
        at.events.append(TraceEvent(agent="remediation", event_type="proposal", data=p))
        print(f"  -> Action: {p.get('action')}")
        print(f"  -> Requires approval: {p.get('requires_approval')}")
    t.add_flow_event("remediation", "postmortem", "proceed", {"status": result.get("status")})
    t.add_agent_trace(at)
    print(f"  -> Status: {result.get('status')}")
    return result


async def node_postmortem(state: IncidentState) -> dict:
    print(f"\n[POSTMORTEM] Generating incident report and updating knowledge base...")
    agent_invocations_total.labels(agent="postmortem", phase="initial").inc()
    t = get_or_create_trace(state["incident_id"])
    at = AgentTrace(agent="postmortem", phase="initial")
    result = await postmortem_agent(state)
    at.end_time = time.time()
    at.events.append(TraceEvent(agent="postmortem", event_type="report_generated",
                                data={"report_preview": str(result.get("final_report", ""))[:500]}))
    t.add_agent_trace(at)
    print(f"  -> Postmortem written, knowledge base updated")
    return result


# ---------------------------------------------------------------------------
# Routing functions for conditional edges
# ---------------------------------------------------------------------------

def route_after_ic(state: IncidentState) -> str:
    """
    The core reconciliation routing logic:
    - If status is "reconciling", loop back to re-evaluate (root_cause_reeval)
    - Otherwise, proceed to remediation
    """
    if state.get("status") == "reconciling":
        return "root_cause_reeval"
    return "remediation"


def route_after_remediation(state: IncidentState) -> str:
    if state.get("status") in ("resolved", "pending_approval"):
        return "postmortem"
    return END


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    """
    Builds the full Sentinel incident response graph.

    Uses a dispatcher node for the reconciliation fan-out since
    add_conditional_edges routes to a single node, and we need to
    fan out to root_cause_reeval + capacity_reeval in parallel.
    """
    graph = StateGraph(IncidentState)

    # --- Nodes ---
    graph.add_node("monitoring", node_monitoring)
    graph.add_node("root_cause", node_root_cause)
    graph.add_node("capacity", node_capacity)
    graph.add_node("customer_impact", node_customer_impact)
    graph.add_node("incident_commander", node_incident_commander)
    graph.add_node("root_cause_reeval", node_root_cause)
    graph.add_node("capacity_reeval", node_capacity)
    graph.add_node("remediation", node_remediation)
    graph.add_node("postmortem", node_postmortem)

    # Dispatcher: a no-op passthrough that fans out to both reeval nodes
    async def reconciliation_dispatcher(state: IncidentState) -> dict:
        print(f"\n  >> Dispatching reconciliation round {state.get('reconciliation_round', 0)}...")
        return {}

    graph.add_node("reconciliation_dispatch", reconciliation_dispatcher)

    # --- Entry ---
    graph.set_entry_point("monitoring")

    # --- Fan-out from monitoring (3 parallel branches) ---
    graph.add_edge("monitoring", "root_cause")
    graph.add_edge("monitoring", "capacity")
    graph.add_edge("monitoring", "customer_impact")

    # --- Fan-in to Incident Commander (waits for all 3) ---
    graph.add_edge("root_cause", "incident_commander")
    graph.add_edge("capacity", "incident_commander")
    graph.add_edge("customer_impact", "incident_commander")

    # --- Conditional: reconciliation loop or proceed ---
    graph.add_conditional_edges(
        "incident_commander",
        route_after_ic,
        {
            "root_cause_reeval": "reconciliation_dispatch",
            "remediation": "remediation",
        },
    )

    # --- Reconciliation fan-out: dispatch → both reeval agents in parallel ---
    graph.add_edge("reconciliation_dispatch", "root_cause_reeval")
    graph.add_edge("reconciliation_dispatch", "capacity_reeval")

    # --- Reconciliation fan-in: both reeval → IC (waits for both) ---
    graph.add_edge("root_cause_reeval", "incident_commander")
    graph.add_edge("capacity_reeval", "incident_commander")

    # --- After remediation: postmortem or end ---
    graph.add_conditional_edges(
        "remediation",
        route_after_remediation,
        {
            "postmortem": "postmortem",
            END: END,
        },
    )

    graph.add_edge("postmortem", END)

    return graph


# ---------------------------------------------------------------------------
# Compiled graph instance + runner
# ---------------------------------------------------------------------------

sentinel_graph = build_graph().compile()


async def run_incident_graph(initial_state: IncidentState) -> IncidentState:
    incidents_total.labels(
        region=initial_state["region"], service=initial_state["service"]
    ).inc()
    graph_start = time.time()

    logger.info(json.dumps({
        "event": "graph_start",
        "incident_id": initial_state["incident_id"],
        "region": initial_state["region"],
        "service": initial_state["service"],
    }))

    print(f"\n{'='*60}")
    print(f"  SENTINEL — Incident {initial_state['incident_id']}")
    print(f"  Region: {initial_state['region']} | Service: {initial_state['service']}")
    print(f"{'='*60}")

    final_state = await sentinel_graph.ainvoke(initial_state)

    trace = get_or_create_trace(initial_state["incident_id"])
    trace.end_time = time.time()

    duration = time.time() - graph_start
    incident_duration_seconds.observe(duration)
    final_status = final_state.get("status", "unknown")
    incidents_by_final_status.labels(status=final_status).inc()

    print(f"\n{'='*60}")
    print(f"  INCIDENT {final_state['incident_id']} — FINAL STATUS: "
          f"{final_status.upper()}")
    print(f"{'='*60}\n")

    logger.info(json.dumps({
        "event": "graph_end",
        "incident_id": final_state["incident_id"],
        "status": final_status,
        "reconciliation_rounds": final_state.get("reconciliation_round", 0),
        "conflict_detected": final_state.get("conflict_detected", False),
        "duration_seconds": round(duration, 2),
    }))

    return final_state
