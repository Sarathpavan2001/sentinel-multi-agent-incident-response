import asyncio
import hashlib
import json
import logging
import re
import time

from google.api_core.exceptions import ResourceExhausted
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings
from app.core.prompts import CAPACITY_AGENT_PROMPT
from app.core.schemas import Hypothesis, IncidentState
from app.observability import (
    agent_invocations_total,
    agent_iterations,
    agent_latency_seconds,
    agent_tool_calls_total,
    llm_calls_total,
    llm_errors_total,
    llm_latency_seconds,
    llm_rate_limit_backoffs_total,
    llm_tokens_total,
)
from app.tools.infra_tools import check_load_capacity as _check_load_capacity
from app.rag.vector_store import retrieve_sop as _retrieve_sop
from app.tracing import AgentTrace, TraceEvent, get_or_create_trace

logger = logging.getLogger("sentinel")


@tool
def check_load_capacity(region: str, service: str) -> str:
    """Retrieve infrastructure status and capacity data for a region and service.
    Returns instance health, auto-scaling state, load balancer metrics, CDN cache
    hit rates, and database connection pool usage.
    Args:
        region: the infrastructure region (e.g. 'ap-south-1')
        service: the service name (e.g. 'video-streaming')
    """
    result = _check_load_capacity(region, service)
    return json.dumps(result, indent=2)


@tool
def retrieve_sop(query: str) -> str:
    """Search the runbook knowledge base for standard operating procedures.
    Use a query shaped by what you've found so far — e.g. if you see scaling
    exhaustion, search for capacity overload procedures; if capacity looks
    healthy, search for other failure patterns instead.
    Args:
        query: natural language search query for the runbook knowledge base
    """
    return _retrieve_sop(query)


TOOLS = [check_load_capacity, retrieve_sop]


async def capacity_agent(state: IncidentState) -> dict:
    region = state["region"]
    service = state["service"]
    severity = state.get("severity", "unknown")
    metrics = state.get("metrics_snapshot", {})
    round_num = state.get("reconciliation_round", 0)

    reconciliation_context = ""
    notes = state.get("reconciliation_notes", [])
    if notes:
        parts = [
            "IMPORTANT — The Incident Commander has asked you to address "
            "the following in this reconciliation round:\n"
            + "\n".join(f"- {n}" for n in notes)
        ]
        rc_hyp = state.get("root_cause_hypothesis")
        if rc_hyp:
            rc_dict = rc_hyp.model_dump() if hasattr(rc_hyp, "model_dump") else rc_hyp
            parts.append(
                "\nThe Root Cause Agent's current hypothesis "
                "(you MUST engage with their reasoning and evidence, not ignore it):\n"
                f"  Root cause type: {rc_dict.get('root_cause_type')}\n"
                f"  Confidence: {rc_dict.get('confidence')}\n"
                f"  Evidence: {json.dumps(rc_dict.get('evidence', []))}\n"
                f"  Reasoning: {rc_dict.get('reasoning')}"
            )
        reconciliation_context = "\n".join(parts)

    system_prompt = CAPACITY_AGENT_PROMPT.format(
        region=region,
        service=service,
        severity=severity,
        metrics=json.dumps(metrics, indent=2),
        reconciliation_context=reconciliation_context,
    )

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0,
    )
    llm_with_tools = llm.bind_tools(TOOLS)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Investigate the incident in region={region}, service={service}. "
                     f"Use your tools to gather evidence, then produce your hypothesis."),
    ]

    start = time.time()
    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()[:12]
    phase = "reconciliation" if round_num > 0 else "initial"
    agent_invocations_total.labels(agent="capacity", phase=phase).inc()
    logger.info(json.dumps({
        "event": "agent_loop_start", "agent": "capacity",
        "prompt_hash": prompt_hash, "round": round_num,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }))

    incident_id = state.get("incident_id", "")
    trace = get_or_create_trace(incident_id)
    agent_trace = AgentTrace(agent="capacity", phase=phase, round_num=round_num)

    if reconciliation_context:
        agent_trace.events.append(TraceEvent(
            agent="capacity",
            event_type="reconciliation_input",
            data={"context": reconciliation_context[:500]},
        ))

    tool_map = {t.name: t for t in TOOLS}
    max_iterations = 6
    iterations = 0
    active_model = settings.gemini_model

    while iterations < max_iterations:
        iterations += 1
        for rate_attempt in range(3):
            try:
                call_start = time.time()
                response = await llm_with_tools.ainvoke(messages)
                call_dur = time.time() - call_start
                llm_latency_seconds.labels(
                    agent="capacity", model=active_model
                ).observe(call_dur)
                llm_calls_total.labels(
                    agent="capacity", model=active_model, outcome="success"
                ).inc()

                usage = getattr(response, "usage_metadata", None) or {}
                prompt_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
                completion_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0
                if prompt_tokens:
                    llm_tokens_total.labels(
                        agent="capacity", model=active_model, direction="prompt"
                    ).inc(prompt_tokens)
                if completion_tokens:
                    llm_tokens_total.labels(
                        agent="capacity", model=active_model, direction="completion"
                    ).inc(completion_tokens)

                agent_trace.events.append(TraceEvent(
                    agent="capacity",
                    event_type="llm_call",
                    data={
                        "iteration": iterations,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "has_tool_calls": bool(response.tool_calls),
                    },
                    duration_ms=int(call_dur * 1000),
                ))

                logger.info(json.dumps({
                    "event": "llm_call_end", "agent": "capacity",
                    "model": active_model, "iteration": iterations,
                    "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                }))
                break
            except ResourceExhausted:
                llm_rate_limit_backoffs_total.labels(agent="capacity").inc()
                if rate_attempt < 2:
                    delay = 10 * (2 ** rate_attempt)
                    print(f"  [capacity] Rate limited, waiting {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    llm_errors_total.labels(
                        agent="capacity", error_type="rate_limit_exhausted"
                    ).inc()
                    raise
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_fn = tool_map[tc["name"]]
            tc_start = time.time()
            tool_result = await tool_fn.ainvoke(tc["args"])
            tc_dur = time.time() - tc_start
            agent_tool_calls_total.labels(agent="capacity", tool=tc["name"]).inc()

            result_str = str(tool_result)
            agent_trace.events.append(TraceEvent(
                agent="capacity",
                event_type="tool_call",
                data={
                    "tool": tc["name"],
                    "args": tc["args"],
                    "result_preview": result_str[:800],
                },
                duration_ms=int(tc_dur * 1000),
            ))
            agent_trace.tools_used.append(tc["name"])

            logger.info(json.dumps({
                "event": "tool_call", "agent": "capacity",
                "tool": tc["name"], "args_keys": list(tc["args"].keys()),
            }))
            messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

    total_latency = time.time() - start
    agent_latency_seconds.labels(agent="capacity").observe(total_latency)
    agent_iterations.labels(agent="capacity").observe(iterations)
    logger.info(json.dumps({
        "event": "agent_loop_end", "agent": "capacity",
        "latency_ms": int(total_latency * 1000), "iterations": iterations,
    }))

    raw_text = response.content
    if isinstance(raw_text, list):
        text_parts = []
        for c in raw_text:
            if isinstance(c, dict) and "text" in c:
                text_parts.append(c["text"])
            elif isinstance(c, str):
                text_parts.append(c)
            else:
                text_parts.append(str(c))
        raw_text = "\n".join(text_parts)

    hypothesis_dict = _extract_hypothesis_json(raw_text)

    hypothesis = Hypothesis(
        agent="capacity",
        root_cause_type=hypothesis_dict.get("root_cause_type", "unknown"),
        confidence=hypothesis_dict.get("confidence", 0.5),
        evidence=hypothesis_dict.get("evidence", ["Agent produced unstructured output"]),
        reasoning=hypothesis_dict.get("reasoning", raw_text[:500]),
    )

    hyp_dict = hypothesis.model_dump()
    agent_trace.hypothesis = hyp_dict
    agent_trace.end_time = time.time()
    agent_trace.events.append(TraceEvent(
        agent="capacity",
        event_type="hypothesis",
        data=hyp_dict,
    ))
    trace.add_agent_trace(agent_trace)

    history_entry = {
        "agent": "capacity",
        "round": round_num,
        **hyp_dict,
    }

    return {
        "capacity_hypothesis": hypothesis,
        "hypothesis_history": [history_entry],
    }


def _extract_hypothesis_json(text: str) -> dict:
    """Best-effort extraction of a JSON hypothesis from the agent's final message."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    fence_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "root_cause_type" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    start_idx = text.find('"root_cause_type"')
    if start_idx == -1:
        return {}

    brace_start = text.rfind('{', 0, start_idx)
    if brace_start == -1:
        return {}

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace_start:i + 1])
                except json.JSONDecodeError:
                    break

    return {}
