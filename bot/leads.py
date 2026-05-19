import os
import json
import requests
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST         = ZoneInfo("Asia/Kolkata")
REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
LEADS_KEY   = "clinic_leads"


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
    except Exception as e:
        logger.error("[Redis] Error: %s", e)
        return []


def get_all_leads() -> list:
    results = _redis([["GET", LEADS_KEY]])
    val = results[0].get("result") if results else None
    return json.loads(val) if val else []


def save_lead(answers: dict) -> dict:
    leads = get_all_leads()
    lead  = {
        "id": len(leads) + 1,
        "timestamp": datetime.now(IST).strftime("%d %b %Y %H:%M"),
        "status": "pending",
        "confirmed_time": None,
        "reminder_1_sent": False,
        "reminder_2_sent": False,
        "followup_sent": False,
        "noshow_sent": False,
        **answers
    }
    leads.append(lead)
    _redis([["SET", LEADS_KEY, json.dumps(leads)]])
    logger.info("[Leads] Saved lead for %s", lead.get("name"))
    return lead


def update_lead(phone: str, **kwargs):
    """Update fields on a lead by phone number."""
    leads = get_all_leads()
    for lead in leads:
        if lead.get("phone") == phone:
            lead.update(kwargs)
            break
    _redis([["SET", LEADS_KEY, json.dumps(leads)]])


def get_lead(phone: str) -> dict | None:
    for lead in get_all_leads():
        if lead.get("phone") == phone:
            return lead
    return None
