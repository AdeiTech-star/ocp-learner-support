"""Email dispatch. Tries Gmail SMTP first; falls back to Resend if SMTP
is blocked (e.g. Render Free tier blocks outbound port 587).
"""
import logging
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage

import psycopg

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    message_id: str
    to_user_id: int | None
    subject: str
    provider: str  # "smtp" or "resend"


class EmailSendError(Exception):
    """Raised when both SMTP and Resend fail (or PII lookup fails)."""


def send_email(
    user_id: int,
    subject: str,
    html: str,
    to_override: str | None = None,
) -> SendResult:
    """Send an HTML email. Tries SMTP first, falls back to Resend on network errors."""
    # Resolve recipient + personalize (same for both providers)
    if to_override:
        to_address = to_override
        personalized_html = html
    else:
        email, full_name = _resolve_pii(user_id)
        to_address = email
        personalized_html = html.replace("___LEARNER_NAME___", full_name)

    # Try SMTP first
    try:
        message_id = _send_via_smtp(to_address, subject, personalized_html)
        logger.info("Sent via SMTP subject=%r message_id=%s override=%s",
                    subject, message_id, bool(to_override))
        return SendResult(message_id=message_id, to_user_id=user_id,
                          subject=subject, provider="smtp")
    except (OSError, smtplib.SMTPException) as smtp_err:
        # OSError catches "Network is unreachable" (Render Free blocks SMTP)
        logger.warning("SMTP failed (%s), falling back to Resend", smtp_err)

    # Fallback to Resend
    try:
        message_id = _send_via_resend(to_address, subject, personalized_html)
        logger.info("Sent via Resend subject=%r message_id=%s override=%s",
                    subject, message_id, bool(to_override))
        return SendResult(message_id=message_id, to_user_id=user_id,
                          subject=subject, provider="resend")
    except Exception as resend_err:
        logger.exception("Both SMTP and Resend failed for user %s", user_id)
        raise EmailSendError(
            f"Both providers failed. Last error: {resend_err}"
        ) from resend_err


def _send_via_smtp(to_address: str, subject: str, html: str) -> str:
    """Send via Gmail SMTP. Returns the message_id."""
    if not settings.gmail_address:
        raise EmailSendError("GMAIL_ADDRESS is not set")
    if not settings.gmail_app_password:
        raise EmailSendError("GMAIL_APP_PASSWORD is not set")

    message_id = str(uuid.uuid4())
    msg = EmailMessage()
    msg["From"] = settings.gmail_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{message_id}@ocp-learner-support>"
    msg.set_content("This email requires an HTML-capable client to view.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(settings.gmail_address, settings.gmail_app_password)
        smtp.send_message(msg)

    return message_id


def _send_via_resend(to_address: str, subject: str, html: str) -> str:
    """Send via Resend HTTPS API. Returns the Resend message id."""
    import resend  # imported here so the module doesn't require it unless used

    if not settings.resend_api_key:
        raise EmailSendError("RESEND_API_KEY is not set")
    if not settings.resend_from_email:
        raise EmailSendError("RESEND_FROM_EMAIL is not set")

    resend.api_key = settings.resend_api_key
    params = {
        "from": settings.resend_from_email,
        "to": [to_address],
        "subject": subject,
        "html": html,
    }
    response = resend.Emails.send(params)
    message_id = response.get("id")
    if not message_id:
        raise EmailSendError(f"Resend returned no message id: {response}")
    return message_id


def _resolve_pii(user_id: int) -> tuple[str, str]:
    """Look up (email, full_name) from student_pii."""
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, full_name FROM student_pii WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise EmailSendError(
                    f"No PII on file for user_id={user_id}; cannot send"
                )
            return row[0], row[1]