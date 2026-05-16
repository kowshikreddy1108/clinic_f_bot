import os
import requests
import logging

logger = logging.getLogger(__name__)

API_BASE = "https://api.ycloud.com/v2/whatsapp/messages"

def send_message(to: str, body: str) -> bool:
    """Send a plain-text WhatsApp message via YCloud API."""
    api_key = os.environ["YCLOUD_API_KEY"]

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }
    payload = {
        "from": os.environ["WHATSAPP_PHONE_NUMBER_ID"],
        "to": to,
        "type": "text",
        "text": {
            "body": body
        }
    }
    try:
        resp = requests.post(API_BASE, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("Message sent to %s", to)
        return True
    except requests.RequestException as e:
        logger.error("Failed to send message to %s: %s", to, e)
        return False