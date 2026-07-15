import asyncio
import json
import sys
from pathlib import Path


async def run_scenario(scenario_path: str):
    sys.path.insert(0, str(Path(__file__).parent))

    from app.graph import run_incident_graph
    from app.core.schemas import IncidentState

    with open(scenario_path) as f:
        scenario = json.load(f)

    print(f"\nScenario: {scenario['name']}")
    print(f"Description: {scenario['description']}\n")

    import uuid
    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"

    initial_state: IncidentState = {
        "incident_id": incident_id,
        "region": scenario["region"],
        "service": scenario["service"],
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

    print("\n" + "=" * 60)
    print("  FULL STATE DUMP")
    print("=" * 60)

    display = {}
    for k, v in final_state.items():
        if hasattr(v, "model_dump"):
            display[k] = v.model_dump()
        else:
            display[k] = v

    print(json.dumps(display, indent=2, default=str))


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_demo.py <scenario_file>")
        print("  e.g.: python run_demo.py scenarios/scenario_conflict.json")
        print("        python run_demo.py scenarios/scenario_agree.json")
        sys.exit(1)

    scenario_path = sys.argv[1]
    if not Path(scenario_path).exists():
        print(f"Error: scenario file not found: {scenario_path}")
        sys.exit(1)

    asyncio.run(run_scenario(scenario_path))


if __name__ == "__main__":
    main()
