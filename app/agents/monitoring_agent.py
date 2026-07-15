import json

from app.config import settings
from app.core.llm_client import llm_client
from app.core.prompts import MONITORING_AGENT_PROMPT
from app.core.schemas import IncidentState, SeverityOutput
from app.tools.metrics_tools import check_metrics


async def monitoring_agent(state: IncidentState) -> dict:
    region = state["region"]
    service = state["service"]

    metrics = check_metrics(region, service)

    prompt = MONITORING_AGENT_PROMPT.format(
        metrics=json.dumps(metrics, indent=2),
        region=region,
        service=service,
    )

    result = await llm_client.call(
        agent_name="monitoring",
        prompt=prompt,
        response_schema=SeverityOutput,
        model=settings.gemini_lite_model or None,
    )

    return {
        "severity": result["severity"],
        "metrics_snapshot": metrics,
        "status": "investigating",
    }
