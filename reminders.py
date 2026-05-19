import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bot.leads import get_all_leads, update_lead
from bot.whatsapp import send_message

logger = logging.getLogger(__name__)
IST    = ZoneInfo("Asia/Kolkata")

OWNER_PHONE = None  # Set dynamically from env in app.py


def now_ist() -> datetime:
    return datetime.now(IST)


def check_and_send_reminders():
    """
    Called every 5 minutes via GET /remind pinged by cron-job.org.
    Handles: 24hr reminder, 2hr reminder, no-show recovery.
    Follow-up is triggered manually from dashboard.
    """
    import os
    owner_phone = os.environ.get("CLINIC_OWNER_PHONE", "")
    leads       = get_all_leads()
    now         = now_ist()

    for lead in leads:
        phone      = lead.get("phone")
        name       = lead.get("name", "there")
        status     = lead.get("status")
        time_str   = lead.get("confirmed_time")

        # Only process confirmed appointments
        if status != "confirmed" or not time_str or not phone:
            continue

        try:
            appt_dt = datetime.strptime(time_str, "%d-%m-%Y %I:%M %p")
            appt_dt = appt_dt.replace(tzinfo=IST)
        except Exception:
            continue

        time_until = appt_dt - now

        # ── Reminder 1 — 24 hours before ─────────────────────────────────
        if (
            not lead.get("reminder_1_sent")
            and timedelta(hours=23, minutes=55) <= time_until <= timedelta(hours=24, minutes=5)
        ):
            send_message(
                phone,
                f"Hello {name}! 👋\n\n"
                f"This is a reminder from the clinic.\n\n"
                f"Your appointment is tomorrow at *{time_str}*.\n\n"
                f"Please arrive on time. Reply here if you need to reschedule."
            )
            update_lead(phone, reminder_1_sent=True)
            logger.info("[Reminder 1 - 24hr] Sent to %s", phone)

        # ── Reminder 2 — 2 hours before ──────────────────────────────────
        elif (
            not lead.get("reminder_2_sent")
            and timedelta(hours=1, minutes=55) <= time_until <= timedelta(hours=2, minutes=5)
        ):
            send_message(
                phone,
                f"Hello {name}! 👋\n\n"
                f"Your clinic appointment is in *2 hours* at {time_str}.\n\n"
                f"We look forward to seeing you. Please arrive a few minutes early."
            )
            update_lead(phone, reminder_2_sent=True)
            logger.info("[Reminder 2 - 2hr] Sent to %s", phone)

        # ── No-show — 30 minutes after appointment ────────────────────────
        elif (
            lead.get("reminder_1_sent")
            and lead.get("reminder_2_sent")
            and not lead.get("noshow_sent")
            and status == "confirmed"
            and now > appt_dt + timedelta(minutes=30)
        ):
            # Update status
            update_lead(phone, status="noshow", noshow_sent=True)

            # Notify owner on WhatsApp
            if owner_phone:
                send_message(
                    owner_phone,
                    f"⚠️ No-Show Alert\n\n"
                    f"Patient: {name}\n"
                    f"Phone: {phone}\n"
                    f"Appointment was: {time_str}\n\n"
                    f"They did not arrive."
                )

            # Recovery message to patient
            send_message(
                phone,
                f"Hello {name}, we noticed you missed your appointment today.\n\n"
                f"We'd love to help you. Would you like to book another appointment? "
                f"Just reply here and we'll get you scheduled. 🏥"
            )
            logger.info("[No-Show] Recovery sent to %s", phone)
