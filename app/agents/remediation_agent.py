import json

from app.config import settings
from app.core.llm_client import llm_client
from app.core.prompts import REMEDIATION_AGENT_PROMPT
from app.core.schemas import IncidentState, RemediationProposal
from app.tools.infra_tools import execute_remediation_mock


async def remediation_agent(state: IncidentState) -> dict:
    root_cause = state.get("final_root_cause", "unknown")
    severity = state.get("severity", "unknown")
    affected_users = state.get("affected_users_estimate", 0)

    prompt = REMEDIATION_AGENT_PROMPT.format(
        root_cause=root_cause,
        severity=severity,
        affected_users=affected_users,
        service=state["service"],
        region=state["region"],
    )

    result = await llm_client.call(
        agent_name="remediation",
        prompt=prompt,
        response_schema=RemediationProposal,
        model=settings.gemini_lite_model or None,
    )

    proposal = RemediationProposal(**result)

    needs_approval = proposal.requires_approval or severity in ("high", "critical") or not proposal.reversible

    if needs_approval:
        return {
            "remediation_proposal": proposal,
            "status": "pending_approval",
        }

    exec_result = execute_remediation_mock(proposal.action)
    return {
        "remediation_proposal": proposal,
        "status": "resolved",
    }
