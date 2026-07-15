import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def check_load_capacity(region: str, service: str) -> dict:
    with open(DATA_DIR / "mock_infra_status.json") as f:
        data = json.load(f)
    region_data = data.get(region, {})
    infra = region_data.get(service)
    if not infra:
        return {"error": f"No infra status found for {region}/{service}"}
    return infra


def propose_remediation(root_cause: str) -> dict:
    remediation_map = {
        "bad_deployment": {
            "action": "Rollback to previous stable version",
            "reversible": True,
            "risk_level": "medium",
        },
        "load_spike": {
            "action": "Scale out auto-scaling group to max capacity and enable traffic shedding",
            "reversible": True,
            "risk_level": "low",
        },
        "infra_failure": {
            "action": "Failover to standby instances and isolate unhealthy nodes",
            "reversible": True,
            "risk_level": "medium",
        },
    }
    return remediation_map.get(
        root_cause,
        {
            "action": "Escalate to on-call engineering lead for manual investigation",
            "reversible": True,
            "risk_level": "low",
        },
    )


def execute_remediation_mock(action: str) -> dict:
    return {
        "status": "executed",
        "action": action,
        "result": "Remediation action executed successfully (mock)",
        "timestamp": "2024-12-15T14:15:00Z",
    }
