import json
from pathlib import Path

from app.config import settings
from app.core.llm_client import llm_client
from app.core.prompts import POSTMORTEM_AGENT_PROMPT
from app.core.schemas import IncidentState, PostmortemOutput

RUNBOOK_DIR = Path(__file__).parent.parent.parent / "data" / "runbooks"


async def postmortem_agent(state: IncidentState) -> dict:
    prompt = POSTMORTEM_AGENT_PROMPT.format(
        incident_id=state["incident_id"],
        region=state["region"],
        service=state["service"],
        severity=state.get("severity", "unknown"),
        root_cause=state.get("final_root_cause", "unknown"),
        final_report=state.get("final_report", "N/A"),
        remediation=json.dumps(
            state["remediation_proposal"].model_dump()
            if state.get("remediation_proposal")
            and hasattr(state["remediation_proposal"], "model_dump")
            else state.get("remediation_proposal", {}),
            indent=2,
        )
        if state.get("remediation_proposal")
        else "No remediation taken",
        affected_users=state.get("affected_users_estimate", "unknown"),
    )

    result = await llm_client.call(
        agent_name="postmortem",
        prompt=prompt,
        response_schema=PostmortemOutput,
        model=settings.gemini_lite_model or None,
    )

    new_entry = result.get("new_runbook_entry", "")
    if new_entry:
        learned_path = RUNBOOK_DIR / "learned_incidents.md"
        header = ""
        if not learned_path.exists():
            header = "# Learned Incidents — Auto-Generated Runbook Entries\n\n"
        with open(learned_path, "a", encoding="utf-8") as f:
            f.write(
                f"{header}## Incident {state['incident_id']}\n\n{new_entry}\n\n---\n\n"
            )

        try:
            from app.rag.vector_store import vector_store
            vector_store.rebuild_index()
        except Exception:
            pass

    return {"final_report": json.dumps(result, indent=2)}
