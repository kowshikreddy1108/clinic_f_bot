import os
import json
import requests

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

# 90 days in seconds â€” prevents Upstash free tier from evicting state keys
STATE_TTL = 60 * 60 * 24 * 90

def _headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json"
    }

def get_state(phone: str) -> dict | None:
    try:
        resp = requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["GET", f"state:{phone}"]],
            timeout=5
        )
        result = resp.json()[0].get("result")
        if result:
            return json.loads(result)
        return None
    except:
        return None

def set_state(phone: str, state: dict):
    try:
        requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            # EX = expire in seconds. This prevents Upstash from randomly evicting keys.
            json=[["SET", f"state:{phone}", json.dumps(state), "EX", STATE_TTL]],
            timeout=5
        )
    except:
        pass

def clear_state(phone: str):
    try:
        requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["DEL", f"state:{phone}"]],
            timeout=5
        )
    except:
        pass