import os
import json
import logging
import time
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from bot.whatsapp import send_message
from bot.email_sender import send_lead_email
from bot.state import get_state, set_state, clear_state
from bot.leads import save_lead, update_lead, get_lead
from bot.lists import is_whitelisted, is_blacklisted
from reminders import check_and_send_reminders

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IST          = ZoneInfo("Asia/Kolkata")
VERIFY_TOKEN = os.environ["VERIFY_TOKEN"]
OWNER_PHONE  = os.environ.get("CLINIC_OWNER_PHONE", "")

# Register dashboard blueprint
from dashboard import dashboard as dashboard_bp
app.register_blueprint(dashboard_bp)

# ── Redis (for dedup) ─────────────────────────────────────────────────────────
import requests as _req

REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_RH = {"Authorization": f"Bearer {REDIS_TOKEN}", "Content-Type": "application/json"}


def _redis(commands):
    try:
        return _req.post(f"{REDIS_URL}/pipeline", headers=_RH,
                         json=commands, timeout=5).json()
    except Exception:
        return []


# ── Deduplication ─────────────────────────────────────────────────────────────
def _is_duplicate(phone: str, text: str) -> bool:
    try:
        window    = int(time.time() // 30)
        raw       = f"{phone}:{text[:30]}:{window}"
        dedup_key = "dedup:" + hashlib.md5(raw.encode()).hexdigest()
        result    = _redis([["SET", dedup_key, "1", "NX", "EX", "60"]])
        return result[0].get("result") is None
    except Exception:
        return False


# ── Blacklist notify once ─────────────────────────────────────────────────────
def _bl_notified(phone: str) -> bool:
    try:
        r = _redis([["GET", f"bl_notified:{phone}"]])
        return r[0].get("result") == "1"
    except Exception:
        return False


def _mark_bl_notified(phone: str):
    _redis([["SET", f"bl_notified:{phone}", "1", "EX",
             str(60 * 60 * 24 * 365)]])


# ── Questions ─────────────────────────────────────────────────────────────────
QUESTIONS = [
    {"key": "name",           "text": "What is your *full name*?"},
    {"key": "problem",        "text": "What is the problem or treatment you need?\n(e.g. tooth pain, cleaning, skin checkup, physiotherapy)"},
    {"key": "preferred_time", "text": "What is your *preferred date and time* for the appointment?\n(e.g. Tomorrow 10 AM, 30 May 3 PM)"},
]


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return "ok", 200


# ── Reminder endpoint — pinged every 5 min by cron-job.org ───────────────────
@app.route("/remind")
def remind():
    try:
        check_and_send_reminders()
        return jsonify({"status": "reminders checked"}), 200
    except Exception as e:
        logger.error("[Remind] %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


# ── Owner WhatsApp reply — confirm appointment ────────────────────────────────
# Owner replies to the WhatsApp notification with:
# confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM
#
# This is handled inside the main webhook below since
# all WhatsApp messages come through the same endpoint.


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
    try:
        events = data if isinstance(data, list) else [data]
        for event in events:
            if event.get("type") == "whatsapp.inbound_message.received":
                msg   = event.get("whatsappInboundMessage", {})
                phone = msg.get("from")
                text  = msg.get("text", {}).get("body", "").strip()
                if phone and text:
                    if _is_duplicate(phone, text):
                        logger.info("Duplicate from %s ignored", phone)
                        continue
                    handle_message(phone, text)
    except Exception as e:
        logger.warning("[Webhook] Parse error: %s", e)
    return jsonify({"status": "ok"}), 200


# ── Message handler ───────────────────────────────────────────────────────────
def handle_message(phone: str, text: str):
    text_lower = text.lower().strip()

    # ── Owner reply — confirm appointment ────────────────────────────────
    if phone == OWNER_PHONE:
        handle_owner_reply(text)
        return

    # ── Whitelist — silent ────────────────────────────────────────────────
    if is_whitelisted(phone):
        logger.info("Whitelisted %s — silent", phone)
        return

    # ── Blacklist — one message only ──────────────────────────────────────
    if is_blacklisted(phone):
        if not _bl_notified(phone):
            send_message(phone,
                "Hi! Thanks for reaching out. "
                "Our team will get back to you shortly.")
            _mark_bl_notified(phone)
        return

    state = get_state(phone)

    # ── Already completed ─────────────────────────────────────────────────
    if state and state.get("step") == "done":
        send_message(phone,
            "Thank you! We've already received your request. "
            "Our clinic will contact you shortly. 🏥")
        return

    # ── New patient — send greeting ───────────────────────────────────────
    if state is None:
        set_state(phone, {"step": "waiting_start"})
        send_message(phone,
            "👋 Hi! Welcome to the clinic.\n\n"
            "Book your appointment in 30 seconds.\n\n"
            "Reply *BOOK* to get started.")
        return

    # ── Waiting for BOOK keyword ──────────────────────────────────────────
    if state.get("step") == "waiting_start":
        if "book" in text_lower:
            set_state(phone, {"step": 0, "answers": {}})
            send_message(phone, QUESTIONS[0]["text"])
        else:
            send_message(phone, "Please reply *BOOK* to get started. 🏥")
        return

    # ── Q&A flow ──────────────────────────────────────────────────────────
    step    = state.get("step", 0)
    answers = state.get("answers", {})

    if isinstance(step, int) and step < len(QUESTIONS):
        key          = QUESTIONS[step]["key"]
        answers[key] = text
        next_step    = step + 1

        if next_step < len(QUESTIONS):
            set_state(phone, {"step": next_step, "answers": answers})
            send_message(phone, QUESTIONS[next_step]["text"])
        else:
            # ── All questions answered ────────────────────────────────────
            answers["phone"] = phone
            set_state(phone, {"step": "done"})

            # Save lead
            lead = save_lead(answers)

            # Thank patient
            send_message(phone,
                f"Thank you {answers.get('name', '')}! ✅\n\n"
                f"Your appointment request has been received.\n"
                f"The clinic will confirm your appointment shortly.")

            # Notify owner on WhatsApp
            if OWNER_PHONE:
                send_message(OWNER_PHONE,
                    f"🏥 *NEW PATIENT ENQUIRY*\n\n"
                    f"👤 Name: {answers.get('name')}\n"
                    f"📞 Phone: {phone}\n"
                    f"🩺 Problem: {answers.get('problem')}\n"
                    f"🕐 Preferred Time: {answers.get('preferred_time')}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"To confirm appointment reply:\n"
                    f"confirm:{phone},29-05-2026 03:00 PM\n\n"
                    f"To cancel reply:\n"
                    f"cancel:{phone}")

            # Send email to owner
            send_lead_email(lead)

            logger.info("[Lead] Saved and owner notified for %s", phone)


# ── Owner reply handler ───────────────────────────────────────────────────────
def handle_owner_reply(text: str):
    text = text.strip()

    # ── Confirm: confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM ───────────────
    if text.lower().startswith("confirm:"):
        try:
            rest              = text[len("confirm:"):].strip()
            phone, time_str   = rest.split(",", 1)
            phone             = phone.strip()
            time_str          = time_str.strip()

            # Validate datetime format
            datetime.strptime(time_str, "%d-%m-%Y %I:%M %p")

            # Update lead
            update_lead(phone,
                        status="confirmed",
                        confirmed_time=time_str,
                        reminder_1_sent=False,
                        reminder_2_sent=False)

            # Confirm to patient
            lead = get_lead(phone)
            name = lead.get("name", "there") if lead else "there"
            send_message(phone,
                f"Hello {name}! ✅\n\n"
                f"Your appointment at the clinic is *confirmed*.\n\n"
                f"📅 Date & Time: {time_str}\n\n"
                f"You will receive reminders before your appointment. "
                f"See you soon! 🏥")

            # Confirm back to owner
            send_message(OWNER_PHONE,
                f"✅ Appointment confirmed for {name} ({phone})\n"
                f"Time: {time_str}\n\n"
                f"Patient has been notified.")

            logger.info("[Owner] Confirmed appointment for %s at %s", phone, time_str)

        except Exception as e:
            send_message(OWNER_PHONE,
                f"❌ Format error: {e}\n\n"
                f"Use exactly:\n"
                f"confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM")

    # ── Cancel: cancel:+91XXXXXXXXXX ─────────────────────────────────────
    elif text.lower().startswith("cancel:"):
        try:
            phone = text[len("cancel:"):].strip()
            update_lead(phone, status="cancelled")

            lead = get_lead(phone)
            name = lead.get("name", "there") if lead else "there"

            send_message(phone,
                f"Hello {name}, your appointment request at the clinic "
                f"has been cancelled.\n\n"
                f"If you'd like to reschedule, please reply *BOOK*. 🏥")

            send_message(OWNER_PHONE,
                f"✅ Cancelled appointment for {name} ({phone}).\n"
                f"Patient has been notified.")

        except Exception as e:
            send_message(OWNER_PHONE,
                f"❌ Cancel error: {e}\n\n"
                f"Use: cancel:+91XXXXXXXXXX")

    else:
        send_message(OWNER_PHONE,
            "❓ Command not recognised.\n\n"
            "To confirm: confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM\n"
            "To cancel: cancel:+91XXXXXXXXXX")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
