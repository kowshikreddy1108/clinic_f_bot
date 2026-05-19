import os
import requests
import logging

logger = logging.getLogger(__name__)


def send_lead_email(lead: dict) -> bool:
    """Send patient lead details to clinic owner via Resend."""
    try:
        api_key   = os.environ["RESEND_API_KEY"]
        recipient = os.environ["LEAD_EMAIL_RECIPIENT"]
        sender    = os.environ.get("LEAD_EMAIL_SENDER", "onboarding@resend.dev")

        subject = f"New Patient Enquiry — {lead.get('name', 'Unknown')}"
        html    = _format_body(lead)

        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [recipient],
                "subject": subject,
                "html": html,
            },
            timeout=15
        )

        if resp.status_code in (200, 201):
            logger.info("[Email] Sent for %s", lead.get("name"))
            return True
        else:
            logger.error("[Email] Failed %s: %s", resp.status_code, resp.text)
            return False

    except Exception as e:
        logger.error("[Email] Error: %s", e)
        return False


def _format_body(lead: dict) -> str:
    rows = "".join(
        f"<tr>"
        f"<td style='padding:8px 12px;color:#666;font-size:14px;"
        f"border-bottom:1px solid #f0f0f0'>{k.capitalize()}</td>"
        f"<td style='padding:8px 12px;font-weight:500;font-size:14px;"
        f"border-bottom:1px solid #f0f0f0'>{v}</td>"
        f"</tr>"
        for k, v in lead.items()
        if k not in ("id", "status", "confirmed_time",
                     "reminder_1_sent", "reminder_2_sent",
                     "followup_sent", "noshow_sent")
    )
    return f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:20px">
      <h2 style="font-size:20px;margin-bottom:4px;color:#111">🏥 New Patient Enquiry</h2>
      <p style="color:#888;font-size:13px;margin-top:0">Captured via WhatsApp bot</p>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e5e5;
                    border-radius:8px;overflow:hidden;margin-top:16px">
        {rows}
      </table>
      <p style="color:#aaa;font-size:11px;margin-top:16px">
        Sent automatically by your Clinic WhatsApp Bot
      </p>
    </div>
    """
