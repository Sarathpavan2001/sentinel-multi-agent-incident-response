import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def estimate_affected_users(region: str, service: str) -> dict:
    with open(DATA_DIR / "mock_user_counts.json") as f:
        data = json.load(f)
    region_data = data.get(region, {})
    user_data = region_data.get(service)
    if not user_data:
        return {"error": f"No user data found for {region}/{service}"}
    return user_data
