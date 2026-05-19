import os
import requests
import logging

logger = logging.getLogger(__name__)

API_BASE = "https://api.ycloud.com/v2/whatsapp/messages"


def send_message(to: str, body: str) -> bool:
    """Send a plain-text WhatsApp message via YCloud."""
    api_key  = os.environ.get("YCLOUD_API_KEY", "")
    from_num = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }
    payload = {
        "from": from_num,
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    try:
        resp = requests.post(API_BASE, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        logger.info("[WhatsApp] Sent to %s", to)
        return True
    except requests.RequestException as e:
        logger.error("[WhatsApp] Failed to send to %s: %s", to, e)
        return False
