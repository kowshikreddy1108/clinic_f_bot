import os
import json
import requests

REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
STATE_TTL   = 60 * 60 * 24 * 90  # 90 days


def _headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json"
    }


def _redis(commands: list) -> list:
    try:
        resp = requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=commands,
            timeout=5
        )
        return resp.json()
    except Exception:
        return []


def get_state(phone: str) -> dict | None:
    results = _redis([["GET", f"state:{phone}"]])
    val = results[0].get("result") if results else None
    return json.loads(val) if val else None


def set_state(phone: str, state: dict):
    _redis([["SET", f"state:{phone}", json.dumps(state), "EX", STATE_TTL]])


def clear_state(phone: str):
    _redis([["DEL", f"state:{phone}"]])
