import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def check_metrics(region: str, service: str) -> dict:
    with open(DATA_DIR / "mock_metrics.json") as f:
        data = json.load(f)
    region_data = data.get(region, {})
    service_data = region_data.get(service)
    if not service_data:
        return {"error": f"No metrics found for {region}/{service}"}
    return service_data
