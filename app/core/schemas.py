import operator
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class Hypothesis(BaseModel):
    agent: str
    root_cause_type: Literal["bad_deployment", "load_spike", "infra_failure", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(min_length=1)
    reasoning: str


class SeverityOutput(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    justification: str


class RemediationProposal(BaseModel):
    action: str
    reversible: bool
    requires_approval: bool
    risk_level: Literal["low", "medium", "high"]


class CustomerImpactOutput(BaseModel):
    affected_users_estimate: int
    customer_comms_needed: bool
    customer_comms_draft: Optional[str] = None


class ReconciliationQuestion(BaseModel):
    question: str
    addressed_to: list[str]


class FinalReport(BaseModel):
    final_root_cause: str
    summary: str
    reconciliation_outcome: str
    recommendations: list[str]


class PostmortemOutput(BaseModel):
    title: str
    timeline: list[str]
    root_cause_analysis: str
    what_went_well: list[str]
    what_went_wrong: list[str]
    action_items: list[str]
    new_runbook_entry: str


def _last_value(existing, new):
    """Reducer: last writer wins. Used for scalar fields written by parallel branches."""
    return new if new is not None else existing


class IncidentState(TypedDict, total=False):
    incident_id: str
    region: str
    service: str
    severity: Annotated[Optional[str], _last_value]
    metrics_snapshot: Annotated[Optional[dict], _last_value]
    root_cause_hypothesis: Annotated[Optional[Hypothesis], _last_value]
    capacity_hypothesis: Annotated[Optional[Hypothesis], _last_value]
    hypothesis_history: Annotated[list[dict], operator.add]
    conflict_detected: Annotated[bool, _last_value]
    reconciliation_round: Annotated[int, _last_value]
    reconciliation_notes: Annotated[list[str], operator.add]
    affected_users_estimate: Annotated[Optional[int], _last_value]
    customer_comms_needed: Annotated[bool, _last_value]
    customer_comms_draft: Annotated[Optional[str], _last_value]
    remediation_proposal: Annotated[Optional[RemediationProposal], _last_value]
    final_root_cause: Annotated[Optional[str], _last_value]
    final_report: Annotated[Optional[str], _last_value]
    status: Annotated[
        Literal[
            "monitoring",
            "investigating",
            "reconciling",
            "pending_approval",
            "resolved",
            "escalated",
        ],
        _last_value,
    ]
