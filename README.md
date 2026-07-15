# Sentinel — Multi-Agent Network Operations Command Center

## Problem Statement

DTDL runs telecom infrastructure at massive scale (18M+ concurrent subscribers during peak events like World Cup streaming). When a network anomaly occurs, NOC engineers must rapidly diagnose root cause, assess customer impact, and decide on remediation — often under conflicting signals. Is it a bad deployment? A load spike? Both?

**Sentinel** automates this triage using a multi-agent system where specialist agents independently investigate, can genuinely disagree with each other's hypotheses, and must reconcile through a structured negotiation loop before an incident is closed — mirroring how a real NOC war-room actually works.

## Architecture

```
                         ┌─────────────┐
                         │  Monitoring  │
                         │    Agent     │
                         └──────┬──────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                v               v               v
        ┌──────────────┐ ┌────────────┐ ┌───────────────┐
        │  Root Cause   │ │  Capacity  │ │   Customer    │
        │    Agent      │ │   Agent    │ │ Impact Agent  │
        └──────┬───────┘ └─────┬──────┘ └───────┬───────┘
               │               │                │
               └───────────────┼────────────────┘
                               │
                               v
                    ┌─────────────────────┐
                    │ Incident Commander  │◄────────────────┐
                    │  (Reconciliation)   │                 │
                    └──────────┬──────────┘                 │
                               │                           │
                        ┌──────┴──────┐              ┌─────┴──────┐
                        │  Conflict?  │──── YES ────►│ Dispatcher │
                        └──────┬──────┘              └─────┬──────┘
                               │ NO                        │
                               v                    ┌──────┴──────┐
                    ┌─────────────────┐             │  Root Cause │
                    │  Remediation    │             │  + Capacity │
                    │     Agent       │             │  (Re-eval)  │
                    └────────┬────────┘             └─────────────┘
                             │
                             v
                    ┌─────────────────┐
                    │   Postmortem    │
                    │     Agent      │
                    └────────────────┘
```

### Why This Is Genuinely Multi-Agent

Most "multi-agent" demos are linear pipelines — Agent A passes to Agent B passes to Agent C. Sentinel is architecturally different:

1. **Parallel fan-out with genuine independence**: Root Cause, Capacity, and Customer Impact agents run concurrently via LangGraph's native parallel edge scheduling. Root Cause and Capacity *cannot see each other's output* on the first pass — their disagreement is real, not staged.

2. **Conditional reconciliation loop via `add_conditional_edges`**: When the Incident Commander detects conflict (different `root_cause_type` with both agents above 0.6 confidence), it generates a targeted question and routes *back* through the graph to both investigator agents. This is a true cycle in the graph, not a retry wrapper.

3. **Honest escalation**: If agents cannot reconcile after 2 rounds, the system escalates rather than forcing fake convergence. This is how real NOC war-rooms work — sometimes the answer is "we need a human."

4. **Human-in-the-loop gate**: The Remediation Agent proposes actions but does not auto-execute when severity is high/critical or the action is irreversible. The incident enters `pending_approval` status and requires explicit human approval via the `/incident/{id}/approve` endpoint.

5. **Self-improving knowledge base**: The Postmortem Agent writes new runbook entries and re-indexes the FAISS vector store, so running the same scenario type twice yields richer SOP context the second time.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** (`StateGraph`) | Native support for conditional edges + cycles = real agent negotiation |
| LLM | **Gemini Flash** (`google-generativeai` + `langchain-google-genai`) | Centralized client for structured output; LangChain binding for tool-calling agents |
| Agent framework | **LangChain** tool-calling pattern | Matches DTDL skill requirements |
| RAG store | **FAISS** (local, in-memory) | Zero external dependency, fast retrieval |
| Embeddings | **Gemini Embedding** (`models/gemini-embedding-001`) | Same API key as LLM calls, no separate model download |
| Backend API | **FastAPI** (async) | Native async support, auto-generated OpenAPI docs |
| Validation | **Pydantic v2** | Structured output validation on every LLM decision point |
| Config | **pydantic-settings** + `.env` | Secure secrets management |
| Logging | Structured JSON to file | Observability-ready audit trail |

## Setup & Run

### Prerequisites
- Python 3.10+
- A Google Gemini API key

### Installation

```bash
cd sentinel
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Build the RAG Index

```bash
python -m app.rag.build_index
```

### Run Demo Scenarios

```bash
# Conflict scenario (the centerpiece — agents disagree and reconcile)
python run_demo.py scenarios/scenario_conflict.json

# Agreement scenario (clean convergence, no conflict)
python run_demo.py scenarios/scenario_agree.json
```

### Run the API Server

```bash
uvicorn app.main:app --reload
```

**Endpoints:**
- `GET /` — Agent Trace Viewer UI (single-page app)
- `POST /incident/trigger` — Start a new incident investigation
- `GET /incident/{id}` — Get current incident state
- `GET /incident/{id}/trace` — Get full agent trace data (tool calls, LLM iterations, hypotheses)
- `POST /incident/{id}/approve` — Approve a pending remediation
- `GET /metrics` — Prometheus metrics endpoint
- `GET /health` — Health check

### Run Tests

```bash
pytest tests/ -v
```

## Demo: Conflict Scenario Trace

The conflict scenario (`scenario_conflict.json`) demonstrates Sentinel's core capability. The setup:

- **Region**: ap-south-1 (Mumbai)
- **Service**: video-streaming
- **Context**: ICC Champions Trophy Semi-Final streaming (4.2M concurrent users)
- **Anomaly**: Deploy v2.3.1 landed at 14:02, but traffic was already spiking from 14:00 due to the cricket match
- **Metrics**: 12.4% error rate, latency 10x baseline, 6 unhealthy instances, CDN cache hit rate collapsed from 94% to 62%

**What happens:**

1. **Monitoring Agent** classifies severity as HIGH/CRITICAL based on the metrics
2. **Root Cause Agent** sees the v2.3.1 deployment at 14:02 (large changeset, 47 files, new codec dependency) and hypothesizes `bad_deployment` with high confidence
3. **Capacity Agent** sees traffic at 1.5x baseline during a peak event, 6/24 unhealthy instances, auto-scaling not at max, and hypothesizes `load_spike` with high confidence
4. **Incident Commander** detects the conflict — both agents are above 0.6 confidence with different root causes — and generates a targeted question about the 2-minute overlap between the deploy timestamp and load spike onset
5. Both agents re-evaluate with the IC's question as additional context
6. They either converge (one adjusts their confidence/type) or the IC escalates after max rounds
7. **Remediation Agent** proposes a specific action (e.g., rollback + scale-out) and flags it for human approval given the severity
8. **Postmortem Agent** generates a structured report and adds a new runbook entry to the knowledge base

### Actual Trace Log (Real Run Output)

```
[MONITORING] Analyzing metrics for ap-south-1/video-streaming...
  -> Severity classified: high

[ROOT CAUSE] Investigating deployment/software issues...
  -> Hypothesis: bad_deployment (confidence: 0.95)

[CAPACITY] Investigating load/scaling issues...
  -> Hypothesis: load_spike (confidence: 0.85)

[INCIDENT COMMANDER] Evaluating hypotheses (round 0)...
  !! CONFLICT DETECTED — requesting reconciliation
  IC question: "Did the v2.3.1 deployment cause the CDN cache hit rate
  to collapse and trigger the load, or did an independent surge in traffic
  expose a latent vulnerability in the new deployment?"

  >> Dispatching reconciliation round 1...

[ROOT CAUSE (reconciliation round 1)] Investigating deployment/software issues...
  -> Hypothesis: bad_deployment (confidence: 0.95)

[CAPACITY (reconciliation round 1)] Investigating load/scaling issues...
  -> Hypothesis: bad_deployment (confidence: 0.95)  ← CHANGED from load_spike

[INCIDENT COMMANDER] Evaluating hypotheses (round 1)...
  [IC] Root Cause revision: bad_deployment -> bad_deployment (delta +0.00)
  [IC] Capacity revision: load_spike -> bad_deployment (confidence +0.10)
  -> Status: resolved
  -> Final root cause: v2.3.1 deployment regression in video transcoding
     pipeline and connection pooling logic caused CDN cache hit rate
     collapse from 94% to 62%, triggering origin surge.

[REMEDIATION] Proposing remediation action...
  -> Action: Rollback v2.3.1 to v2.3.0 in ap-south-1
  -> Requires approval: True
  -> Status: pending_approval

[POSTMORTEM] Generating incident report and updating knowledge base...
  -> Built index with 5 chunks from 4 runbooks (new entry added)
  -> Postmortem written, knowledge base updated
```

**Key proof of genuine multi-agent behavior**: The Capacity Agent changed its position from `load_spike` (0.85) to `bad_deployment` (0.95) after seeing the Root Cause Agent's evidence about the CDN cache hit rate collapse being a symptom of the deployment regression, not an external load anomaly. This is real position revision — not a scripted outcome.

## Security & Responsible AI

- **Structured output validation**: Every LLM decision is parsed through a Pydantic schema. If validation fails, the system retries once with the error appended, then fails loudly — never silently proceeds with invalid data.
- **Safety guardrails**: Every agent prompt includes a safety suffix: no fabricated evidence, explicit low-confidence over guessing, flag irreversible/high-severity actions for approval, no PII in outputs.
- **Human-in-the-loop**: Remediation actions with `requires_approval=True` (severity high/critical or irreversible actions) halt execution and require explicit human approval.
- **Secrets management**: All credentials via `.env` (gitignored), loaded through `pydantic-settings`. API key auth middleware on all endpoints.
- **Audit trail**: Structured JSON logging of every LLM call (agent name, prompt hash, model, latency, prompt/completion tokens) to `logs/sentinel.log` — never logs secrets or full prompts.
- **Metrics**: Prometheus metrics at three tiers (workflow / agent / LLM) exposed at `GET /metrics`; a pre-built Grafana dashboard lives in `observability/sentinel-dashboard.json`.

## Observability (Built)

Sentinel ships with production-grade observability at three tiers, served at `GET /metrics` in Prometheus exposition format:

**Workflow-level:** `sentinel_incidents_total`, `sentinel_incidents_by_final_status_total`, `sentinel_incident_duration_seconds`, `sentinel_conflicts_detected_total`, `sentinel_reconciliation_rounds_total`, `sentinel_hypothesis_revisions_total`

**Agent-level:** `sentinel_agent_invocations_total{agent,phase}`, `sentinel_agent_latency_seconds{agent}`, `sentinel_agent_iterations{agent}`, `sentinel_agent_tool_calls_total{agent,tool}`

**LLM-level:** `sentinel_llm_calls_total{agent,model,outcome}`, `sentinel_llm_latency_seconds{agent,model}`, `sentinel_llm_tokens_total{agent,model,direction}`, `sentinel_llm_errors_total{agent,error_type}`, `sentinel_llm_rate_limit_backoffs_total{agent}`

**To spin up Prometheus + Grafana locally:**
```bash
uvicorn app.main:app --reload   # Sentinel on :8000
cd observability && docker compose up -d
# Prometheus → http://localhost:9090
# Grafana    → http://localhost:3000  (dashboard auto-provisioned)
```

### Agent Trace Viewer UI

A built-in single-page trace viewer is served at `GET /` (the root URL). It provides:
- **Scenario selector** — pick a scenario and run it from the browser
- **Summary dashboard** — incident ID, status, severity, affected users, conflict status, reconciliation rounds, duration, agent count
- **Agent flow graph** — 7-node graph with 3D perspective transforms showing the pipeline topology, color-coded by agent role, with reconciliation loop indicator
- **Agent trace cards** — per-agent expandable cards showing every event: tool calls (with args and result previews), LLM iterations (with token counts), hypotheses (with confidence bars and evidence), conflict detection, IC decisions, remediation proposals, and postmortem reports
- **Expand/Collapse All** controls and click-to-navigate from flow graph nodes to trace cards

## Tool Access Control

Tools are registered via a scoped internal registry (`app/tools/registry.py`). Each agent only has access to its designated tools:

| Agent | Tools |
|---|---|
| Monitoring | `check_metrics` |
| Root Cause | `check_deploy_logs`, `retrieve_sop` (RAG) |
| Capacity | `check_load_capacity`, `retrieve_sop` (RAG) |
| Customer Impact | `estimate_affected_users` |
| Remediation | `propose_remediation`, `execute_remediation_mock` |
| Incident Commander | None (logic is graph routing) |
| Postmortem | None (writes to knowledge base directly) |

This registry maps 1:1 to MCP capability grants — each agent's tool list can migrate directly to an MCP server without changing agent logic.

## Productionization Roadmap

### MCP Server Migration
The current tool registry (`registry.py`) enforces least-privilege tool access per agent via a Python dict. In production, this would be replaced with a full MCP (Model Context Protocol) server where each agent's tool access is granted via capability tokens. The 1:1 mapping between the current registry and MCP capability grants is intentional — no agent logic changes required.

### OpenTelemetry Distributed Tracing
Add OpenTelemetry spans per incident ID for cross-service tracing, alerting rules for anomalous latency/error spikes, and per-region SLO dashboards.

### State Persistence
Currently using an in-memory `dict[str, IncidentState]` keyed by `incident_id`. Production deployment would use:
- **Redis** for hot state (active incidents) with TTL-based expiry
- **PostgreSQL** for cold storage (resolved incidents, postmortems) with per-incident row-level locking for concurrent access
- Transaction-safe state transitions to prevent race conditions in multi-user scenarios

### Expanded HITL Controls
- Role-based approval chains (L1 NOC → L2 Engineering → L3 Architecture) based on severity and blast radius
- Slack/PagerDuty integration for approval workflows
- Configurable auto-approval policies for low-severity, reversible actions during off-peak hours

### Additional Agents
- **Change Management Agent**: Cross-references with change management systems before approving rollbacks
- **Communication Agent**: Manages multi-channel customer notifications (SMS, email, in-app) with audience segmentation
- **Compliance Agent**: Ensures incident response meets regulatory requirements (SLA tracking, audit logging)
