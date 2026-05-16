import os
import json
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

REDIS_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

# Appointment key format in Redis: appt:{phone}
# Value: JSON with keys — name, confirmed_time, reminder_1_sent, reminder_2_sent, noshow_sent


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
        logger.error("[Redis] Pipeline error: %s", e)
        return []


def now_ist() -> datetime:
    return datetime.now(IST)


# ── Appointment storage ───────────────────────────────────────────────────────

def save_appointment(phone: str, name: str, confirmed_time: str, confirmed_datetime: datetime):
    """Store appointment details in Redis after owner confirms."""
    data = {
        "phone": phone,
        "name": name,
        "confirmed_time": confirmed_time,
        # Store as ISO string with timezone
        "confirmed_datetime": confirmed_datetime.isoformat(),
        "reminder_1_sent": False,
        "reminder_2_sent": False,
        "noshow_sent": False
    }
    # TTL 7 days — auto-cleanup old appointments
    ttl = 60 * 60 * 24 * 7
    _redis([["SET", f"appt:{phone}", json.dumps(data), "EX", ttl]])
    logger.info("[Appointments] Saved appointment for %s at %s", phone, confirmed_time)


def get_all_appointments() -> list:
    """Fetch all appointment keys from Redis."""
    try:
        resp = requests.get(
            f"{REDIS_URL}/keys/appt:*",
            headers=_headers(),
            timeout=5
        )
        keys = resp.json().get("result", [])
        if not keys:
            return []

        # Fetch all values in one pipeline call
        commands = [["GET", key] for key in keys]
        results  = _redis(commands)

        appointments = []
        for r in results:
            val = r.get("result")
            if val:
                try:
                    appointments.append(json.loads(val))
                except Exception:
                    pass
        return appointments
    except Exception as e:
        logger.error("[Appointments] Fetch error: %s", e)
        return []


def update_appointment(phone: str, **kwargs):
    """Update specific fields of an appointment."""
    results = _redis([["GET", f"appt:{phone}"]])
    val = results[0].get("result") if results else None
    if not val:
        return
    data = json.loads(val)
    data.update(kwargs)
    ttl = 60 * 60 * 24 * 7
    _redis([["SET", f"appt:{phone}", json.dumps(data), "EX", ttl]])


# ── Parse owner reply from Telegram ──────────────────────────────────────────

def parse_confirm_reply(text: str):
    """
    Parse owner Telegram reply in format:
    confirm:+91XXXXXXXXXX,29-05-2026 03:00 PM

    Returns (phone, confirmed_time_str, confirmed_datetime) or None on failure.
    """
    text = text.strip()
    if not text.lower().startswith("confirm:"):
        return None
    try:
        rest   = text[len("confirm:"):].strip()
        phone, time_str = rest.split(",", 1)
        phone    = phone.strip()
        time_str = time_str.strip()

        confirmed_datetime = datetime.strptime(time_str, "%d-%m-%Y %I:%M %p")
        # Make timezone-aware (IST)
        confirmed_datetime = confirmed_datetime.replace(tzinfo=IST)

        return phone, time_str, confirmed_datetime
    except Exception as e:
        logger.error("[Reminders] Failed to parse confirm reply: %s — %s", text, e)
        return None


# ── Send WhatsApp reminder ────────────────────────────────────────────────────

def _send_whatsapp(phone: str, message: str):
    """Send WhatsApp message via YCloud."""
    try:
        api_key  = os.environ["YCLOUD_API_KEY"]
        from_num = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
        resp = requests.post(
            "https://api.ycloud.com/v2/whatsapp/messages",
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key
            },
            json={
                "from": from_num,
                "to": phone,
                "type": "text",
                "text": {"body": message}
            },
            timeout=10
        )
        if resp.status_code in (200, 201):
            logger.info("[WhatsApp] Reminder sent to %s", phone)
        else:
            logger.error("[WhatsApp] Failed to send to %s: %s", phone, resp.text)
    except Exception as e:
        logger.error("[WhatsApp] Exception sending to %s: %s", phone, e)


def _send_telegram_owner(message: str):
    """Notify owner on Telegram about no-show."""
    from bot.telegram import send_telegram
    send_telegram(message)


# ── Main reminder check ───────────────────────────────────────────────────────

def check_and_send_reminders():
    """
    Called every 5 minutes by cron-job.org via GET /remind.
    Checks all appointments and sends reminders when due.
    """
    appointments = get_all_appointments()
    now          = now_ist()

    if not appointments:
        logger.info("[Reminders] No appointments to check.")
        return

    for appt in appointments:
        phone    = appt.get("phone")
        name     = appt.get("name", "there")
        appt_str = appt.get("confirmed_time", "")
        dt_str   = appt.get("confirmed_datetime")

        if not dt_str or not phone:
            continue

        try:
            appt_dt = datetime.fromisoformat(dt_str)
            if appt_dt.tzinfo is None:
                appt_dt = appt_dt.replace(tzinfo=IST)
        except Exception:
            continue

        time_until = appt_dt - now

        # ── Reminder 1 — 24 hours before ─────────────────────────────────
        if (
            not appt.get("reminder_1_sent")
            and timedelta(hours=23, minutes=55) <= time_until <= timedelta(hours=24, minutes=5)
        ):
            _send_whatsapp(
                phone,
                f"Hello {name}! 🏡\n\n"
                f"This is a reminder from VizagLands.\n\n"
                f"Your property visit is scheduled for tomorrow at *{appt_str}*.\n\n"
                f"Please be on time. If you need to reschedule, reply here."
            )
            update_appointment(phone, reminder_1_sent=True)
            logger.info("[Reminder 1 - 24hr] Sent to %s", phone)

        # ── Reminder 2 — 1 hour before ───────────────────────────────────
        elif (
            not appt.get("reminder_2_sent")
            and timedelta(minutes=55) <= time_until <= timedelta(minutes=65)
        ):
            _send_whatsapp(
                phone,
                f"Hello {name}! 🏡\n\n"
                f"Your property visit with VizagLands is in *1 hour* at {appt_str}.\n\n"
                f"We look forward to seeing you. Please arrive a few minutes early."
            )
            update_appointment(phone, reminder_2_sent=True)
            logger.info("[Reminder 2 - 1hr] Sent to %s", phone)

        # ── No-show — 30 minutes after appointment ────────────────────────
        elif (
            appt.get("reminder_1_sent")
            and appt.get("reminder_2_sent")
            and not appt.get("noshow_sent")
            and now > appt_dt + timedelta(minutes=30)
        ):
            # Notify owner
            _send_telegram_owner(
                f"⚠️ *NO-SHOW ALERT*\n\n"
                f"👤 Name: {name}\n"
                f"📞 Phone: {phone}\n"
                f"🕐 Appointment was: {appt_str}\n\n"
                f"They did not show up. Follow up or reschedule."
            )

            # Recovery message to lead
            _send_whatsapp(
                phone,
                f"Hello {name}, we noticed you missed your property visit today.\n\n"
                f"We'd love to help you find the right property. "
                f"Reply here to reschedule at a convenient time. 🏡"
            )
            update_appointment(phone, noshow_sent=True)
            logger.info("[No-Show] Flagged and recovery sent to %s", phone)
