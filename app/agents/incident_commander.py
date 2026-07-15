import json

from app.config import settings
from app.core.llm_client import llm_client
from app.core.prompts import (
    INCIDENT_COMMANDER_RECONCILIATION_PROMPT,
    INCIDENT_COMMANDER_SYNTHESIS_PROMPT,
)
from app.core.schemas import (
    FinalReport,
    IncidentState,
    ReconciliationQuestion,
)


def _build_history_summary(history: list[dict]) -> str:
    """Format hypothesis_history into a readable evolution summary for the IC."""
    if not history:
        return "No prior hypothesis history."
    lines = []
    for entry in history:
        lines.append(
            f"  Round {entry['round']} — {entry['agent']}: "
            f"{entry['root_cause_type']} (confidence {entry['confidence']:.2f})"
            f"\n    Evidence: {json.dumps(entry.get('evidence', []))}"
            f"\n    Reasoning: {entry.get('reasoning', 'N/A')}"
        )
    return "\n".join(lines)


def _detect_revision(history: list[dict], agent: str) -> dict | None:
    """Check if an agent changed position between rounds."""
    agent_entries = [h for h in history if h["agent"] == agent]
    if len(agent_entries) < 2:
        return None
    prev, curr = agent_entries[-2], agent_entries[-1]
    changed_type = prev["root_cause_type"] != curr["root_cause_type"]
    confidence_delta = curr["confidence"] - prev["confidence"]
    return {
        "agent": agent,
        "changed_type": changed_type,
        "previous_type": prev["root_cause_type"],
        "current_type": curr["root_cause_type"],
        "previous_confidence": prev["confidence"],
        "current_confidence": curr["confidence"],
        "confidence_delta": confidence_delta,
    }


async def incident_commander(state: IncidentState) -> dict:
    rc_hyp = state.get("root_cause_hypothesis")
    cap_hyp = state.get("capacity_hypothesis")

    if rc_hyp is None or cap_hyp is None:
        return {}

    rc_dict = rc_hyp.model_dump() if hasattr(rc_hyp, "model_dump") else rc_hyp
    cap_dict = cap_hyp.model_dump() if hasattr(cap_hyp, "model_dump") else cap_hyp

    rc_type = rc_dict.get("root_cause_type", "unknown")
    cap_type = cap_dict.get("root_cause_type", "unknown")
    rc_conf = rc_dict.get("confidence", 0)
    cap_conf = cap_dict.get("confidence", 0)

    conflict = rc_type != cap_type and rc_conf > 0.6 and cap_conf > 0.6
    current_round = state.get("reconciliation_round", 0)
    max_rounds = settings.max_reconciliation_rounds
    history = state.get("hypothesis_history", [])

    if current_round > 0:
        rc_rev = _detect_revision(history, "root_cause")
        cap_rev = _detect_revision(history, "capacity")
        if rc_rev:
            delta = rc_rev["confidence_delta"]
            print(f"  [IC] Root Cause revision: {rc_rev['previous_type']} -> {rc_rev['current_type']} "
                  f"(confidence {rc_rev['previous_confidence']:.2f} -> {rc_rev['current_confidence']:.2f}, "
                  f"delta {delta:+.2f})")
        if cap_rev:
            delta = cap_rev["confidence_delta"]
            print(f"  [IC] Capacity revision: {cap_rev['previous_type']} -> {cap_rev['current_type']} "
                  f"(confidence {cap_rev['previous_confidence']:.2f} -> {cap_rev['current_confidence']:.2f}, "
                  f"delta {delta:+.2f})")

    if conflict and current_round < max_rounds:
        history_summary = _build_history_summary(history)

        prompt = INCIDENT_COMMANDER_RECONCILIATION_PROMPT.format(
            root_cause_hypothesis=json.dumps(rc_dict, indent=2),
            capacity_hypothesis=json.dumps(cap_dict, indent=2),
            round_number=current_round + 1,
        )
        prompt += (
            f"\n\nHypothesis evolution across all rounds so far:\n{history_summary}\n\n"
            f"Use this history to craft a question that addresses what has NOT changed "
            f"between rounds — if an agent is stuck on the same position without engaging "
            f"with new evidence, call that out specifically."
        )

        result = await llm_client.call(
            agent_name="incident_commander",
            prompt=prompt,
            response_schema=ReconciliationQuestion,
        )

        return {
            "conflict_detected": True,
            "reconciliation_round": current_round + 1,
            "reconciliation_notes": [result["question"]],
            "status": "reconciling",
        }

    history_summary = _build_history_summary(history)

    prompt = INCIDENT_COMMANDER_SYNTHESIS_PROMPT.format(
        root_cause_hypothesis=json.dumps(rc_dict, indent=2),
        capacity_hypothesis=json.dumps(cap_dict, indent=2),
        affected_users=state.get("affected_users_estimate", "unknown"),
        comms_needed=state.get("customer_comms_needed", False),
        reconciliation_notes=json.dumps(state.get("reconciliation_notes", [])),
        severity=state.get("severity", "unknown"),
    )
    prompt += f"\n\nFull hypothesis evolution:\n{history_summary}"

    result = await llm_client.call(
        agent_name="incident_commander",
        prompt=prompt,
        response_schema=FinalReport,
    )

    final_status = "resolved"
    if conflict and current_round >= max_rounds:
        final_status = "escalated"

    return {
        "conflict_detected": conflict,
        "final_root_cause": result["final_root_cause"],
        "final_report": result["summary"],
        "status": final_status,
    }
