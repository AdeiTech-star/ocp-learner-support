import logging
from dataclasses import dataclass

import resend

from app.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.resend_api_key


@dataclass
class SendResult:
    message_id: str
    to: str
    subject: str


class EmailSendError(Exception):
    """Raised when Resend rejects a send. Worker catches this and marks the job failed."""


def send_email(to: str, subject: str, html: str) -> SendResult:
    """Send a single email via Resend.

    Returns the Resend message ID so the caller can log it to the audit trail.
    Raises EmailSendError on any Resend failure — worker decides retry vs fail.
    """
    if not settings.resend_api_key:
        raise EmailSendError("RESEND_API_KEY is not set")
    if not settings.resend_from_email:
        raise EmailSendError("RESEND_FROM_EMAIL is not set")

    params: resend.Emails.SendParams = {
        "from": settings.resend_from_email,
        "to": [to],
        "subject": subject,
        "html": html,
    }

    try:
        response = resend.Emails.send(params)
    except Exception as e:
        logger.exception("Resend send failed for %s", to)
        raise EmailSendError(str(e)) from e

    message_id = response.get("id")
    if not message_id:
        raise EmailSendError(f"Resend returned no message id: {response}")

    logger.info("Sent email to %s subject=%r resend_id=%s", to, subject, message_id)
    return SendResult(message_id=message_id, to=to, subject=subject)