import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Response, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel

from app.config import settings
from app.core.schemas import IncidentState
from app.graph import run_incident_graph
from app.observability import render_metrics
from app.tools.infra_tools import execute_remediation_mock
from app.tracing import trace_store

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(
    title="Sentinel — Multi-Agent Incident Response",
    description="Telecom NOC multi-agent system with conflict reconciliation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

incident_store: dict[str, IncidentState] = {}


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    if settings.sentinel_api_key and settings.sentinel_api_key != "dev-key":
        if not api_key or api_key != settings.sentinel_api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


class TriggerRequest(BaseModel):
    region: str = "ap-south-1"
    service: str = "video-streaming"
    scenario: Optional[str] = None


class TriggerResponse(BaseModel):
    incident_id: str
    status: str
    severity: Optional[str] = None
    final_root_cause: Optional[str] = None
    final_report: Optional[str] = None
    affected_users_estimate: Optional[int] = None
    customer_comms_needed: bool = False
    customer_comms_draft: Optional[str] = None
    conflict_detected: bool = False
    reconciliation_round: int = 0
    reconciliation_notes: list[str] = []
    hypothesis_history: list[dict] = []
    remediation_proposal: Optional[dict] = None


@app.get("/")
async def serve_ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/scenarios")
async def list_scenarios():
    scenario_dir = Path(__file__).parent.parent / "scenarios"
    scenarios = []
    for f in sorted(scenario_dir.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
            data["filename"] = f.name
            scenarios.append(data)
    return scenarios


@app.get("/incidents")
async def list_incidents(api_key: str = Security(verify_api_key)):
    results = []
    for iid, state in incident_store.items():
        proposal = state.get("remediation_proposal")
        proposal_dict = None
        if proposal:
            proposal_dict = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        results.append({
            "incident_id": iid,
            "status": state.get("status"),
            "severity": state.get("severity"),
            "region": state.get("region"),
            "service": state.get("service"),
            "final_root_cause": state.get("final_root_cause"),
            "conflict_detected": state.get("conflict_detected"),
            "reconciliation_round": state.get("reconciliation_round"),
            "affected_users_estimate": state.get("affected_users_estimate"),
            "remediation_proposal": proposal_dict,
        })
    return results


@app.get("/incident/{incident_id}/trace")
async def get_incident_trace(incident_id: str):
    if incident_id not in trace_store:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace_store[incident_id].to_dict()


@app.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint. Intentionally unauthenticated so a scrape
    sidecar (or a local `curl`) can reach it — restrict via network policy in prod."""
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/incident/trigger", response_model=TriggerResponse)
async def trigger_incident(
    request: TriggerRequest,
    api_key: str = Security(verify_api_key),
):
    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

    initial_state: IncidentState = {
        "incident_id": incident_id,
        "region": request.region,
        "service": request.service,
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

    final_state = await run_incident_graph(initial_state)
    incident_store[incident_id] = final_state

    proposal = final_state.get("remediation_proposal")
    proposal_dict = None
    if proposal:
        proposal_dict = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal

    return TriggerResponse(
        incident_id=incident_id,
        status=final_state.get("status", "unknown"),
        severity=final_state.get("severity"),
        final_root_cause=final_state.get("final_root_cause"),
        final_report=final_state.get("final_report"),
        affected_users_estimate=final_state.get("affected_users_estimate"),
        customer_comms_needed=final_state.get("customer_comms_needed", False),
        customer_comms_draft=final_state.get("customer_comms_draft"),
        conflict_detected=final_state.get("conflict_detected", False),
        reconciliation_round=final_state.get("reconciliation_round", 0),
        reconciliation_notes=final_state.get("reconciliation_notes", []),
        hypothesis_history=final_state.get("hypothesis_history", []),
        remediation_proposal=proposal_dict,
    )


@app.get("/incident/{incident_id}")
async def get_incident(
    incident_id: str,
    api_key: str = Security(verify_api_key),
):
    if incident_id not in incident_store:
        raise HTTPException(status_code=404, detail="Incident not found")

    state = incident_store[incident_id]
    proposal = state.get("remediation_proposal")
    proposal_dict = None
    if proposal:
        proposal_dict = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal

    return {
        "incident_id": incident_id,
        "status": state.get("status"),
        "severity": state.get("severity"),
        "final_root_cause": state.get("final_root_cause"),
        "final_report": state.get("final_report"),
        "affected_users_estimate": state.get("affected_users_estimate"),
        "customer_comms_needed": state.get("customer_comms_needed"),
        "customer_comms_draft": state.get("customer_comms_draft"),
        "conflict_detected": state.get("conflict_detected"),
        "reconciliation_round": state.get("reconciliation_round"),
        "reconciliation_notes": state.get("reconciliation_notes"),
        "hypothesis_history": state.get("hypothesis_history", []),
        "remediation_proposal": proposal_dict,
    }


@app.post("/incident/{incident_id}/approve")
async def approve_remediation(
    incident_id: str,
    api_key: str = Security(verify_api_key),
):
    if incident_id not in incident_store:
        raise HTTPException(status_code=404, detail="Incident not found")

    state = incident_store[incident_id]
    if state.get("status") != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Incident is not pending approval (current status: {state.get('status')})",
        )

    proposal = state.get("remediation_proposal")
    if not proposal:
        raise HTTPException(status_code=400, detail="No remediation proposal found")

    action = proposal.action if hasattr(proposal, "action") else proposal.get("action", "")
    exec_result = execute_remediation_mock(action)

    state["status"] = "resolved"
    incident_store[incident_id] = state

    return {
        "incident_id": incident_id,
        "status": "resolved",
        "remediation_executed": exec_result,
    }
