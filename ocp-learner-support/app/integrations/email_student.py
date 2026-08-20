# import logging
# from dataclasses import dataclass

# import resend

# from app.config import settings

# logger = logging.getLogger(__name__)

# resend.api_key = settings.resend_api_key


# @dataclass
# class SendResult:
#     message_id: str
#     to: str
#     subject: str


# class EmailSendError(Exception):
#     """Raised when Resend rejects a send. Worker catches this and marks the job failed."""


# def send_email(to: str, subject: str, html: str) -> SendResult:
#     """Send a single email via Resend.

#     Returns the Resend message ID so the caller can log it to the audit trail.
#     Raises EmailSendError on any Resend failure — worker decides retry vs fail.
#     """
#     if not settings.resend_api_key:
#         raise EmailSendError("RESEND_API_KEY is not set")
#     if not settings.resend_from_email:
#         raise EmailSendError("RESEND_FROM_EMAIL is not set")

#     params: resend.Emails.SendParams = {
#         "from": settings.resend_from_email,
#         "to": [to],
#         "subject": subject,
#         "html": html,
#     }

#     try:
#         response = resend.Emails.send(params)
#     except Exception as e:
#         logger.exception("Resend send failed for %s", to)
#         raise EmailSendError(str(e)) from e

#     message_id = response.get("id")
#     if not message_id:
#         raise EmailSendError(f"Resend returned no message id: {response}")

#     logger.info("Sent email to %s subject=%r resend_id=%s", to, subject, message_id)
#     return SendResult(message_id=message_id, to=to, subject=subject)




####----------------USING PYTHON SMTP -----------------####
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


class EmailSendError(Exception):
    """Raised when SMTP rejects a send or PII lookup fails."""


def send_email(
    user_id: int,
    subject: str,
    html: str,
    to_override: str | None = None,
) -> SendResult:
    """Send an HTML email via Gmail SMTP.

    Normal path: resolve user_id → PII → substitute ___LEARNER_NAME___ →
    send to student's email.

    Escalation path (to_override set): send the message body as-is to the
    override address, no PII lookup, no name substitution. Used for TA
    briefings where the student's name should not appear.
    """
    if not settings.gmail_address:
        raise EmailSendError("GMAIL_ADDRESS is not set")
    if not settings.gmail_app_password:
        raise EmailSendError("GMAIL_APP_PASSWORD is not set")

    if to_override:
        to_address = to_override
        personalized_html = html
    else:
        email, full_name = _resolve_pii(user_id)
        to_address = email
        personalized_html = html.replace("___LEARNER_NAME___", full_name)

    message_id = str(uuid.uuid4())

    msg = EmailMessage()
    msg["From"] = settings.gmail_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{message_id}@ocp-learner-support>"
    msg.set_content("This email requires an HTML-capable client to view.")
    msg.add_alternative(personalized_html, subtype="html")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.gmail_address, settings.gmail_app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        logger.exception("Gmail auth failed for user %s", user_id)
        raise EmailSendError(
            f"Gmail authentication failed. Check GMAIL_APP_PASSWORD. ({e})"
        ) from e
    except smtplib.SMTPException as e:
        logger.exception("Gmail send failed for user %s", user_id)
        raise EmailSendError(str(e)) from e
    except Exception as e:
        logger.exception("Unexpected send error for user %s", user_id)
        raise EmailSendError(str(e)) from e

    logger.info("Sent email subject=%r message_id=%s override=%s",
                subject, message_id, bool(to_override))
    return SendResult(message_id=message_id, to_user_id=user_id, subject=subject)


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