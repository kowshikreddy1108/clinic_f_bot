import os
import json
import logging
import time
import hashlib
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from bot.whatsapp import send_message
from bot.state import get_state, set_state, clear_state
from bot.lists import is_whitelisted, is_blacklisted
from bot.qa import get_next_question, save_lead, QUESTIONS
from bot.email_sender import send_lead_email
from bot.telegram import send_telegram, notify_new_lead, set_webhook
from bot.reminders import check_and_send_reminders, parse_confirm_reply, save_appointment

load_dotenv()
app = Flask(__name__)

from dashboard import dashboard
app.register_blueprint(dashboard)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]

# ── Redis setup ───────────────────────────────────────────────────────────────
import requests as _requests

REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_REDIS_HEADERS = {
    "Authorization": f"Bearer {REDIS_TOKEN}",
    "Content-Type": "application/json"
}

# ── Deduplication ─────────────────────────────────────────────────────────────
def _is_duplicate(phone: str, text: str) -> bool:
    try:
        window    = int(time.time() // 30)
        raw       = f"{phone}:{text[:30]}:{window}"
        dedup_key = "dedup:" + hashlib.md5(raw.encode()).hexdigest()
        resp = _requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_REDIS_HEADERS,
            json=[["SET", dedup_key, "1", "NX", "EX", "60"]],
            timeout=5
        )
        result = resp.json()[0].get("result")
        return result is None
    except Exception as e:
        logger.warning("Dedup check failed: %s", e)
        return False

# ── Blacklist notify once ─────────────────────────────────────────────────────
def _blacklist_already_notified(phone: str) -> bool:
    try:
        resp = _requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_REDIS_HEADERS,
            json=[["GET", f"bl_notified:{phone}"]],
            timeout=5
        )
        return resp.json()[0].get("result") == "1"
    except:
        return False

def _mark_blacklist_notified(phone: str):
    try:
        _requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_REDIS_HEADERS,
            json=[["SET", f"bl_notified:{phone}", "1", "EX", str(60 * 60 * 24 * 365)]],
            timeout=5
        )
    except:
        pass

# ── Thank you counter ─────────────────────────────────────────────────────────
def _get_thankyou_count(phone: str) -> int:
    try:
        resp = _requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_REDIS_HEADERS,
            json=[["GET", f"ty_count:{phone}"]],
            timeout=5
        )
        result = resp.json()[0].get("result")
        return int(result) if result else 0
    except:
        return 0

def _increment_thankyou_count(phone: str):
    try:
        _requests.post(
            f"{REDIS_URL}/pipeline",
            headers=_REDIS_HEADERS,
            json=[
                ["INCR", f"ty_count:{phone}"],
                ["EXPIRE", f"ty_count:{phone}", str(60 * 60 * 24 * 365)]
            ],
            timeout=5
        )
    except:
        pass

# ── Health check for cron-job.org ─────────────────────────────────────────────
@app.route("/health")
def health():
    return "ok", 200

# ── Reminder endpoint — ping this every 5 min via cron-job.org ───────────────
@app.route("/remind")
def remind():
    """
    Add this URL to cron-job.org: https://your-app.onrender.com/remind
    Set schedule: every 5 minutes.
    """
    try:
        check_and_send_reminders()
        return jsonify({"status": "reminders checked"}), 200
    except Exception as e:
        logger.error("[Remind] Error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500

# ── Telegram webhook — receives owner replies ─────────────────────────────────
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """
    Telegram sends owner messages here.
    Owner reply format: confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "no data"}), 200

    try:
        message = data.get("message", {})
        text    = message.get("text", "").strip()

        if not text:
            return jsonify({"status": "no text"}), 200

        logger.info("[Telegram] Owner sent: %s", text)

        # Try to parse as appointment confirmation
        result = parse_confirm_reply(text)
        if result:
            phone, confirmed_time, confirmed_datetime = result

            # Fetch lead name from Redis leads list
            from bot.qa import get_all_leads
            leads = get_all_leads()
            name  = "Customer"
            for lead in leads:
                if lead.get("phone") == phone:
                    name = lead.get("name", "Customer")
                    break

            # Save appointment for reminder system
            save_appointment(phone, name, confirmed_time, confirmed_datetime)

            # Confirm to lead on WhatsApp
            send_message(
                phone,
                f"Hello {name}! 🏡\n\n"
                f"Your property visit with VizagLands is confirmed.\n\n"
                f"📅 Date & Time: {confirmed_time}\n\n"
                f"We look forward to meeting you. You will receive reminders before your visit."
            )

            # Confirm back to owner on Telegram
            send_telegram(
                f"✅ *Appointment Confirmed*\n\n"
                f"👤 Name: {name}\n"
                f"📞 Phone: {phone}\n"
                f"🕐 Time: {confirmed_time}\n\n"
                f"Lead has been notified on WhatsApp."
            )

            logger.info("[Telegram] Appointment saved for %s at %s", phone, confirmed_time)

        else:
            # Owner sent something we don't understand
            send_telegram(
                "❓ Format not recognised.\n\n"
                "To confirm appointment use:\n"
                "`confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM`\n\n"
                "Use exact format: DD-MM-YYYY HH:MM AM/PM"
            )

    except Exception as e:
        logger.error("[Telegram webhook] Error: %s", e)

    return jsonify({"status": "ok"}), 200

# ── Register Telegram webhook (run once after deploy) ─────────────────────────
@app.route("/set_telegram_webhook")
def set_tg_webhook():
    """
    Visit this URL once after deploying to Render:
    https://your-app.onrender.com/set_telegram_webhook
    """
    app_url = request.host_url.rstrip("/")
    success = set_webhook(app_url)
    if success:
        return f"Telegram webhook set to {app_url}/telegram", 200
    return "Failed to set Telegram webhook. Check BOT_TOKEN in env.", 500

# ── Webhook verify ────────────────────────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

# ── Webhook receive ───────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    logger.info("Incoming payload: %s", json.dumps(data, indent=2))
    try:
        events = data if isinstance(data, list) else [data]
        for event in events:
            if event.get("type") == "whatsapp.inbound_message.received":
                msg   = event.get("whatsappInboundMessage", {})
                phone = msg.get("from")
                text  = msg.get("text", {}).get("body", "").strip()
                if phone and text:
                    if _is_duplicate(phone, text):
                        logger.info("Duplicate message from %s ignored", phone)
                        continue
                    handle_message(phone, text)
    except Exception as e:
        logger.warning("Payload parse error: %s", e)
    return jsonify({"status": "ok"}), 200


def handle_message(phone: str, text: str):
    text_lower = text.lower()

    # Whitelist — completely silent
    if is_whitelisted(phone):
        logger.info("Whitelisted number %s — no reply sent", phone)
        return

    # Blacklist — one message only
    if is_blacklisted(phone):
        if not _blacklist_already_notified(phone):
            send_message(phone, "Hi! Thanks for reaching out. Our team will get back to you shortly.")
            _mark_blacklist_notified(phone)
        else:
            logger.info("Blacklisted %s already notified — skipping", phone)
        return

    state = get_state(phone)

    # Already completed flow
    if state and state.get("step") == "done":
        count = _get_thankyou_count(phone)
        if count < 3:
            send_message(phone, "Thank you! We've already noted your requirements. Our team will reach out to you very soon.")
            _increment_thankyou_count(phone)
        else:
            logger.info("Thank you limit reached for %s — silent", phone)
        return

    # New customer
    if state is None:
        set_state(phone, {"step": "waiting_keyword"})
        send_message(
            phone,
            "🏡 *Welcome to VizagLands!*\n\n"
            "Your trusted partner in finding the perfect property in Vizag.\n\n"
            "We're here to make your property journey smooth and stress-free. 🌟\n\n"
            "Reply PROPERTY to connect with our team."
        )
        return

    if state.get("step") == "waiting_keyword":
        if "property" in text_lower:
            set_state(phone, {"step": 0, "answers": {}})
            send_message(phone, get_next_question(0))
        else:
            send_message(phone, "Please reply *PROPERTY* to get started.")
        return

    step    = state.get("step", 0)
    answers = state.get("answers", {})

    if isinstance(step, int) and step < len(QUESTIONS):
        key       = QUESTIONS[step]["key"]
        answers[key] = text
        next_step = step + 1

        if next_step < len(QUESTIONS):
            set_state(phone, {"step": next_step, "answers": answers})
            send_message(phone, get_next_question(next_step))
        else:
            answers["phone"] = phone
            set_state(phone, {"step": "done"})
            lead = save_lead(answers)

            # Thank the lead
            send_message(
                phone,
                "Thank you! We've noted your requirements and our team will reach out to you very soon."
            )
            _increment_thankyou_count(phone)

            # ── Telegram notification to owner ────────────────────────────
            notify_new_lead(lead)

            # ── Email notification ────────────────────────────────────────
            email_sent = send_lead_email(lead)
            if email_sent:
                logger.info("Lead email sent successfully for %s", phone)
            else:
                logger.error("CRITICAL: Lead email FAILED for %s — lead: %s", phone, lead)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
