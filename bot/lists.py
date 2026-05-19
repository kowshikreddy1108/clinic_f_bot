import os
import json
import requests

REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_DEFAULT    = {"whitelist": [], "blacklist": []}


def _headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json"
    }


def _load() -> dict:
    try:
        resp = requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["GET", "clinic_lists"]],
            timeout=5
        )
        result = resp.json()[0].get("result")
        return json.loads(result) if result else _DEFAULT.copy()
    except Exception:
        return _DEFAULT.copy()


def _save(data: dict):
    try:
        requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["SET", "clinic_lists", json.dumps(data)]],
            timeout=5
        )
    except Exception:
        pass


def _clean(phone: str) -> str:
    return phone.strip().replace("+", "").replace(" ", "")


def is_whitelisted(phone: str) -> bool:
    cleaned = _clean(phone)
    for e in _load()["whitelist"]:
        p = e["phone"] if isinstance(e, dict) else e
        if _clean(p) == cleaned:
            return True
    return False


def is_blacklisted(phone: str) -> bool:
    cleaned = _clean(phone)
    for e in _load()["blacklist"]:
        p = e["phone"] if isinstance(e, dict) else e
        if _clean(p) == cleaned:
            return True
    return False


def get_whitelist() -> list:
    return _load()["whitelist"]


def get_blacklist() -> list:
    return _load()["blacklist"]


def add_to_whitelist(phone: str, note: str = ""):
    data    = _load()
    cleaned = _clean(phone)
    existing = [_clean(e["phone"] if isinstance(e, dict) else e)
                for e in data["whitelist"]]
    if cleaned not in existing:
        data["whitelist"].append({"phone": phone, "note": note})
        _save(data)


def remove_from_whitelist(phone: str):
    data    = _load()
    cleaned = _clean(phone)
    data["whitelist"] = [
        e for e in data["whitelist"]
        if _clean(e["phone"] if isinstance(e, dict) else e) != cleaned
    ]
    _save(data)


def add_to_blacklist(phone: str, note: str = ""):
    data    = _load()
    cleaned = _clean(phone)
    existing = [_clean(e["phone"] if isinstance(e, dict) else e)
                for e in data["blacklist"]]
    if cleaned not in existing:
        data["blacklist"].append({"phone": phone, "note": note})
        _save(data)


def remove_from_blacklist(phone: str):
    data    = _load()
    cleaned = _clean(phone)
    data["blacklist"] = [
        e for e in data["blacklist"]
        if _clean(e["phone"] if isinstance(e, dict) else e) != cleaned
    ]
    _save(data)
