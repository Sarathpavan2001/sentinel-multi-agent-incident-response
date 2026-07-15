import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    agent: str
    event_type: str  # tool_call, tool_result, llm_decision, hypothesis, reconciliation, status_change
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class AgentTrace:
    agent: str
    phase: str  # initial, reconciliation
    round_num: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0
    events: list[TraceEvent] = field(default_factory=list)
    hypothesis: dict = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "phase": self.phase,
            "round": self.round_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": int((self.end_time - self.start_time) * 1000) if self.end_time else 0,
            "events": [
                {
                    "agent": e.agent,
                    "type": e.event_type,
                    "timestamp": e.timestamp,
                    "data": e.data,
                    "duration_ms": e.duration_ms,
                }
                for e in self.events
            ],
            "hypothesis": self.hypothesis,
            "tools_used": self.tools_used,
        }


@dataclass
class IncidentTrace:
    incident_id: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0
    agent_traces: list[AgentTrace] = field(default_factory=list)
    flow_events: list[dict] = field(default_factory=list)

    def add_agent_trace(self, trace: AgentTrace):
        self.agent_traces.append(trace)

    def add_flow_event(self, from_agent: str, to_agent: str, event_type: str, data: dict = None):
        self.flow_events.append({
            "from": from_agent,
            "to": to_agent,
            "type": event_type,
            "timestamp": time.time(),
            "data": data or {},
        })

    def to_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": int((self.end_time - self.start_time) * 1000) if self.end_time else 0,
            "agent_traces": [t.to_dict() for t in self.agent_traces],
            "flow_events": self.flow_events,
        }


# Global trace store keyed by incident_id
trace_store: dict[str, IncidentTrace] = {}


def get_or_create_trace(incident_id: str) -> IncidentTrace:
    if incident_id not in trace_store:
        trace_store[incident_id] = IncidentTrace(incident_id=incident_id)
    return trace_store[incident_id]
