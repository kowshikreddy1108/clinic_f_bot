import os
import requests
import logging

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_telegram(message: str) -> bool:
    """Send a plain-text message to the owner's Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("[Telegram] BOT_TOKEN or CHAT_ID missing in env.")
        return False
    try:
        resp = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        if resp.status_code == 200:
            logger.info("[Telegram] Message sent successfully.")
            return True
        else:
            logger.error("[Telegram] Failed: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("[Telegram] Exception: %s", e)
        return False


def notify_new_lead(lead: dict):
    """
    Called when a lead completes the Q&A.
    Sends full lead details to owner on Telegram.
    Also shows how to confirm an appointment.
    """
    phone   = lead.get("phone", "Unknown")
    name    = lead.get("name", "Unknown")
    area    = lead.get("area", "Unknown")
    budget  = lead.get("budget", "Unknown")
    intent  = lead.get("intent", "Unknown")
    bhk     = lead.get("bhk", "Unknown")
    ts      = lead.get("timestamp", "")

    message = (
        f"🏡 *NEW PROPERTY LEAD*\n\n"
        f"👤 Name: {name}\n"
        f"📞 Phone: {phone}\n"
        f"📍 Area: {area}\n"
        f"💰 Budget: {budget}\n"
        f"🏠 Intent: {intent}\n"
        f"🛏 BHK: {bhk}\n"
        f"🕐 Time: {ts}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"To confirm appointment, reply:\n"
        f"`confirm:{phone},29-05-2026 03:00 PM`\n\n"
        f"Use exact format: DD-MM-YYYY HH:MM AM/PM"
    )
    send_telegram(message)


def set_webhook(app_url: str) -> bool:
    """
    Register this app's /telegram endpoint as the Telegram webhook.
    Call this once after deployment.
    GET your-app.onrender.com/set_telegram_webhook to trigger.
    """
    webhook_url = f"{app_url}/telegram"
    try:
        resp = requests.post(
            f"{BASE_URL}/setWebhook",
            json={"url": webhook_url},
            timeout=10
        )
        result = resp.json()
        logger.info("[Telegram] Webhook set: %s", result)
        return result.get("ok", False)
    except Exception as e:
        logger.error("[Telegram] Webhook set failed: %s", e)
        return False
