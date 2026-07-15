import json

from app.config import settings
from app.core.llm_client import llm_client
from app.core.prompts import CUSTOMER_IMPACT_AGENT_PROMPT
from app.core.schemas import CustomerImpactOutput, IncidentState
from app.tools.impact_tools import estimate_affected_users


async def customer_impact_agent(state: IncidentState) -> dict:
    region = state["region"]
    service = state["service"]
    severity = state.get("severity", "unknown")
    metrics = state.get("metrics_snapshot", {})

    user_data = estimate_affected_users(region, service)

    prompt = CUSTOMER_IMPACT_AGENT_PROMPT.format(
        region=region,
        service=service,
        severity=severity,
        metrics=json.dumps(metrics, indent=2),
        user_data=json.dumps(user_data, indent=2),
    )

    result = await llm_client.call(
        agent_name="customer_impact",
        prompt=prompt,
        response_schema=CustomerImpactOutput,
        model=settings.gemini_lite_model or None,
    )

    return {
        "affected_users_estimate": result["affected_users_estimate"],
        "customer_comms_needed": result["customer_comms_needed"],
        "customer_comms_draft": result.get("customer_comms_draft"),
    }
