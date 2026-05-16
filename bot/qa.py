import os
import json
import requests
from datetime import datetime
import pytz

REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

QUESTIONS = [
    {"key": "name", "text": "Great! Let's get started. 😊\n\nWhat is your *full name*?"},
    {"key": "area", "text": "Which *area or locality* are you looking in?\n(e.g.Anandapuram(atchutapuram),Bheemili,Bhogapuram,Duvvada,Tarluvada,Thagarapuvalasa)"},
    {"key": "budget", "text": "What is your *budget*?\n(e.g. 50 lakhs, 1.2 crore, 30k/month rent)"},
    {"key": "intent", "text": "Are you looking to *Buy* or *Rent*?"},
    {"key": "bhk", "text": "How many *BHK* (bedrooms) do you need?\n(e.g. 1BHK, 2BHK, 3BHK, Office space)"},
]

def _headers():
    return {
        "Authorization": f"Bearer {REDIS_TOKEN}",
        "Content-Type": "application/json"
    }

def get_next_question(step: int) -> str:
    return QUESTIONS[step]["text"]

def get_all_leads() -> list:
    try:
        resp = requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["GET", "all_leads"]],
            timeout=5
        )
        result = resp.json()[0].get("result")
        if result:
            return json.loads(result)
        return []
    except:
        return []

def save_lead(answers: dict) -> dict:
    try:
        leads = get_all_leads()
        lead = {
            "id": len(leads) + 1,
            "timestamp": datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d %b %Y %H:%M"),
            **answers,
        }
        leads.append(lead)
        requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_headers(),
            json=[["SET", "all_leads", json.dumps(leads)]],
            timeout=5
        )
        return lead
    except:
        return answers
        
        