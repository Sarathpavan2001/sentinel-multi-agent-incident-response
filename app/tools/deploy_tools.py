import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def check_deploy_logs(region: str, service: str, time_window: str = "24h") -> dict:
    with open(DATA_DIR / "mock_deploy_logs.json") as f:
        data = json.load(f)
    region_data = data.get(region, {})
    deploys = region_data.get(service, [])
    if not deploys:
        return {"deploys": [], "note": f"No deployments found for {region}/{service}"}
    return {"deploys": deploys, "time_window": time_window}
