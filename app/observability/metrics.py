"""
Sentinel observability metrics — Prometheus counters/histograms/gauges at three tiers:

  1. Agent level      — per-agent invocation counts, latency, iterations, tool calls
  2. LLM level        — call counts, latency, token consumption, errors, rate limits
  3. Workflow level   — incidents by status, conflict detection, reconciliation rounds

All metrics live in a dedicated CollectorRegistry so tests can be reset independently.
Exposed via `GET /metrics` (see main.py) in standard Prometheus text format.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

metrics_registry = CollectorRegistry()

# ---------------------------------------------------------------------------
# Agent-level metrics
# ---------------------------------------------------------------------------

agent_invocations_total = Counter(
    "sentinel_agent_invocations_total",
    "Total number of times each agent has been invoked",
    ["agent", "phase"],  # phase: initial | reconciliation
    registry=metrics_registry,
)

agent_latency_seconds = Histogram(
    "sentinel_agent_latency_seconds",
    "Wall-clock time for a full agent invocation (including all its tool calls)",
    ["agent"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
    registry=metrics_registry,
)

agent_iterations = Histogram(
    "sentinel_agent_iterations",
    "Number of tool-calling loop iterations before an agent produced its final hypothesis",
    ["agent"],
    buckets=(1, 2, 3, 4, 5, 6, 8, 10),
    registry=metrics_registry,
)

agent_tool_calls_total = Counter(
    "sentinel_agent_tool_calls_total",
    "Individual tool calls made by tool-calling agents",
    ["agent", "tool"],
    registry=metrics_registry,
)

# ---------------------------------------------------------------------------
# LLM-level metrics
# ---------------------------------------------------------------------------

llm_calls_total = Counter(
    "sentinel_llm_calls_total",
    "Total LLM API calls",
    ["agent", "model", "outcome"],  # outcome: success | validation_failure | error
    registry=metrics_registry,
)

llm_latency_seconds = Histogram(
    "sentinel_llm_latency_seconds",
    "LLM call latency (single request/response, excludes retry backoff waits)",
    ["agent", "model"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30),
    registry=metrics_registry,
)

llm_tokens_total = Counter(
    "sentinel_llm_tokens_total",
    "LLM token consumption by direction (prompt vs completion)",
    ["agent", "model", "direction"],  # direction: prompt | completion
    registry=metrics_registry,
)

llm_errors_total = Counter(
    "sentinel_llm_errors_total",
    "LLM errors surfaced to the caller (after all retries exhausted)",
    ["agent", "error_type"],
    registry=metrics_registry,
)

llm_rate_limit_backoffs_total = Counter(
    "sentinel_llm_rate_limit_backoffs_total",
    "429 rate-limit hits that triggered a backoff retry",
    ["agent"],
    registry=metrics_registry,
)

# ---------------------------------------------------------------------------
# Workflow-level metrics
# ---------------------------------------------------------------------------

incidents_total = Counter(
    "sentinel_incidents_total",
    "Incidents that entered the graph (increments on graph_start)",
    ["region", "service"],
    registry=metrics_registry,
)

incidents_by_final_status = Counter(
    "sentinel_incidents_by_final_status_total",
    "Incidents partitioned by their terminal status",
    ["status"],  # resolved | pending_approval | escalated
    registry=metrics_registry,
)

incident_duration_seconds = Histogram(
    "sentinel_incident_duration_seconds",
    "End-to-end wall-clock time for a full incident run (graph_start → graph_end)",
    buckets=(5, 10, 20, 30, 60, 120, 300, 600),
    registry=metrics_registry,
)

conflicts_detected_total = Counter(
    "sentinel_conflicts_detected_total",
    "Times the Incident Commander detected a conflict and triggered reconciliation",
    registry=metrics_registry,
)

reconciliation_rounds_total = Counter(
    "sentinel_reconciliation_rounds_total",
    "Total reconciliation rounds fired across all incidents",
    registry=metrics_registry,
)

hypothesis_revisions_total = Counter(
    "sentinel_hypothesis_revisions_total",
    "Times an agent genuinely changed its root_cause_type between rounds",
    ["agent"],
    registry=metrics_registry,
)


def render_metrics() -> bytes:
    """Serialize the registry to Prometheus text-format bytes."""
    return generate_latest(metrics_registry)
