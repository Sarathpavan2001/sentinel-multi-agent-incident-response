"""
Scoped tool registry — each agent only gets access to its designated tools.

Root Cause and Capacity agents use LangChain @tool-decorated functions
bound via ChatGoogleGenerativeAI.bind_tools(). The registry here documents
the access mapping and provides get_tools_for_agent() for programmatic
introspection (used by tests and the MCP migration path).

This registry maps 1:1 to MCP capability grants — each agent's tool list
can migrate directly to an MCP server without changing agent logic.
"""

from app.tools.metrics_tools import check_metrics
from app.tools.deploy_tools import check_deploy_logs
from app.tools.infra_tools import (
    check_load_capacity,
    propose_remediation,
    execute_remediation_mock,
)
from app.tools.impact_tools import estimate_affected_users

TOOL_REGISTRY: dict[str, list] = {
    "monitoring": [check_metrics],
    "root_cause": [check_deploy_logs, "retrieve_sop"],
    "capacity": [check_load_capacity, "retrieve_sop"],
    "customer_impact": [estimate_affected_users],
    "remediation": [propose_remediation, execute_remediation_mock],
    "incident_commander": [],
    "postmortem": [],
}


def get_tools_for_agent(agent_name: str) -> list:
    return TOOL_REGISTRY.get(agent_name, [])
