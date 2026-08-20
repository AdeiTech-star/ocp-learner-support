"""Escalation: reviewer hands off a draft to a TA instead of sending.

Marks the original draft as 'escalated' (no email to student) and sends
a separate briefing email to the TA. The TA briefing is LLM-generated
from the same context the AI used to write the student draft, so the TA
gets everything without having to piece it together.

Owned by: Nthabiseng
"""
import logging
from typing import Any

import psycopg
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path

from app.integrations.agent import personalize
from app.config import settings
from app.integrations.email_student import EmailSendError
from app.nudges.drafts import _insert_row, _load_latest_draft_state
from app.nudges.generation import _build_context, _text_to_html

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "jinja"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)


def escalate_draft(draft_id: str, reviewer_id: str, notes: str | None = None) -> None:
    """Mark the draft as escalated, no student email. Send a TA briefing
    with flag context. Raises EmailSendError if TA send fails; the draft
    still gets marked escalated regardless (audit trail is preserved).
    """
    draft = _load_latest_draft_state(draft_id)
    if draft["delivery_status"] != "pending_review":
        raise ValueError(
            f"Draft {draft_id} is in state {draft['delivery_status']!r}, "
            "can only escalate a pending_review draft"
        )

    _insert_row(
        draft_id=draft_id,
        user_id=draft["user_id"],
        nudge_type=draft["nudge_type"],
        template_id=draft["template_id"],
        variant_id=draft["variant_id"],
        computation_id=draft["computation_id"],
        delivery_status="escalated",
        subject=draft["subject"],
        html_body=draft["html_body"],
        reviewer_id=reviewer_id,
        review_notes=notes,
        flag_code=draft["flag_code"],
        rendered_template=draft["rendered_template"],
        langsmith_run_id=draft["langsmith_run_id"],
    )
    logger.info("Draft %s escalated by %s", draft_id, reviewer_id)

    _send_ta_briefing(
        draft_id=draft_id,
        user_id=draft["user_id"],
        flag_code=draft["flag_code"],
        reviewer_id=reviewer_id,
        reviewer_notes=notes,
    )


def _send_ta_briefing(
    *,
    draft_id: str,
    user_id: int,
    flag_code: str | None,
    reviewer_id: str,
    reviewer_notes: str | None,
) -> None:
    """Generate and send the TA briefing email."""
    from app.nudges.drafts import _insert_row
    from app.integrations.email_student import send_email

    ta_recipients = [e.strip() for e in settings.ta_email.split(",") if e.strip()]
    if not ta_recipients:
        raise EmailSendError("TA_EMAIL is not set; cannot escalate")

    with psycopg.connect(settings.database_url) as conn:
        context = _build_context(user_id, flag_code or "unknown", conn)
    context["learner_name"] = f"Student {user_id}"  # override for TA briefing

    context["escalation"] = {
        "reviewer_id": reviewer_id,
        "reviewer_notes": reviewer_notes or "(no note provided)",
        "student_user_id": user_id,
        "flag_code": flag_code or "unknown",
    }

    template = _jinja_env.get_template("ta_escalation.j2")
    rendered = template.render(**context)

    personalized_text, run_id = personalize(
        rendered,
        context,
        flag_code=flag_code,
        template_name="ta_escalation",
        nudge_type="escalation_alert",
        user_id=user_id,
        severity="red",
    )
    html_body = _text_to_html(personalized_text)
    subject = f"Escalation: Student {user_id} needs follow-up (flag {flag_code or '—'})"

    import uuid
    ta_draft_id = str(uuid.uuid4())

    _insert_row(
        draft_id=ta_draft_id,
        user_id=user_id,
        nudge_type="escalation_alert",
        template_id="ta_escalation",
        variant_id=None,
        computation_id=None,
        delivery_status="pending_review",
        subject=subject,
        html_body=html_body,
        flag_code=flag_code,
        rendered_template=rendered,
        langsmith_run_id=run_id,
    )
    _insert_row(
        draft_id=ta_draft_id,
        user_id=user_id,
        nudge_type="escalation_alert",
        template_id="ta_escalation",
        variant_id=None,
        computation_id=None,
        delivery_status="approved",
        subject=subject,
        html_body=html_body,
        reviewer_id=reviewer_id,
        flag_code=flag_code,
        rendered_template=rendered,
        langsmith_run_id=run_id,
    )

    try:
        result = send_email(
            user_id=user_id,
            subject=subject,
            html=html_body,
            to_override=", ".join(ta_recipients),
)
        _insert_row(
            draft_id=ta_draft_id,
            user_id=user_id,
            nudge_type="escalation_alert",
            template_id="ta_escalation",
            variant_id=None,
            computation_id=None,
            delivery_status="sent",
            subject=subject,
            html_body=html_body,
            reviewer_id=reviewer_id,
            provider_message_id=result.message_id,
            delivered=True,
            flag_code=flag_code,
            rendered_template=rendered,
            langsmith_run_id=run_id,
        )
        logger.info("TA briefing sent for draft %s", draft_id)
    except EmailSendError as e:
        _insert_row(
            draft_id=ta_draft_id,
            user_id=user_id,
            nudge_type="escalation_alert",
            template_id="ta_escalation",
            variant_id=None,
            computation_id=None,
            delivery_status="failed",
            subject=subject,
            html_body=html_body,
            reviewer_id=reviewer_id,
            review_notes=str(e),
            flag_code=flag_code,
            rendered_template=rendered,
            langsmith_run_id=run_id,
        )
        logger.warning("TA briefing failed: %s", e)
        raise

def _override_ta_recipient_hook():
    """Placeholder for future: currently send_email resolves via student_pii.
    We need to send TO the TA, not the student. Handled below in
    send_ta_email helper, but leaving this hook if we ever want per-TA
    routing (Q2C).
    """
    pass