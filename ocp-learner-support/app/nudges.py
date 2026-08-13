"""Nudge lifecycle: draft → review → send, append-only.

Every state transition writes a new row to nudge_events. Latest row per
draft_id is the current state. No UPDATEs, no DELETEs — full history
preserved for the audit tab and fairness monitoring.
"""
import logging
import uuid
from typing import Literal

import psycopg

from app.config import settings
from app.email_student import EmailSendError, send_email

logger = logging.getLogger(__name__)

NudgeType = Literal[
    "reengagement", "late_submission", "gate_ahead",
    "activity_no_work", "score_dropping",
]

def create_draft(
    to_email: str,
    subject: str,
    html_body: str,
    user_id: int,
    nudge_type: NudgeType,
    template_id: str,
    flag_code: str | None = None,
    rendered_template: str | None = None,
    langsmith_run_id: str | None = None,
    computation_id: int | None = None,
    variant_id: str | None = None,
) -> str:
    """Register an agent-generated draft awaiting reviewer approval."""
    draft_id = str(uuid.uuid4())
    _insert_row(
        draft_id=draft_id,
        user_id=user_id,
        nudge_type=nudge_type,
        template_id=template_id,
        variant_id=variant_id,
        computation_id=computation_id,
        delivery_status="pending_review",
        subject=subject,
        html_body=html_body,
        to_email=to_email,
        flag_code=flag_code,
        rendered_template=rendered_template,
        langsmith_run_id=langsmith_run_id,
    )
    logger.info(
        "Draft %s created for user %s (%s, flag=%s, ls_run=%s)",
        draft_id, user_id, nudge_type, flag_code or "—", langsmith_run_id or "—",
    )
    return draft_id


def reject_draft(draft_id: str, reviewer_id: str, notes: str | None = None) -> None:
    """Reviewer rejected the draft. No email is sent."""
    draft = _load_latest_draft_state(draft_id)
    if draft["delivery_status"] != "pending_review":
        raise ValueError(
            f"Draft {draft_id} is in state {draft['delivery_status']!r}, "
            "can only reject a pending_review draft"
        )
    _insert_row(
        draft_id=draft_id,
        user_id=draft["user_id"],
        nudge_type=draft["nudge_type"],
        template_id=draft["template_id"],
        variant_id=draft["variant_id"],
        computation_id=draft["computation_id"],
        delivery_status="rejected",
        subject=draft["subject"],
        html_body=draft["html_body"],
        to_email=draft["to_email"],
        reviewer_id=reviewer_id,
        review_notes=notes,
        rendered_template=draft["rendered_template"],
        langsmith_run_id=draft["langsmith_run_id"],
    )
    logger.info("Draft %s rejected by %s", draft_id, reviewer_id)


def send_approved_draft(draft_id: str, reviewer_id: str) -> None:
    """Reviewer approved. Log approval, send the email, log outcome.

    Three rows written on the success path: approved, then sent. On failure:
    approved, then failed. Raises EmailSendError after logging failure.
    """
    draft = _load_latest_draft_state(draft_id)
    if draft["delivery_status"] != "pending_review":
        raise ValueError(
            f"Draft {draft_id} is in state {draft['delivery_status']!r}, "
            "can only approve a pending_review draft"
        )

    _insert_row(
        draft_id=draft_id,
        user_id=draft["user_id"],
        nudge_type=draft["nudge_type"],
        template_id=draft["template_id"],
        variant_id=draft["variant_id"],
        computation_id=draft["computation_id"],
        delivery_status="approved",
        subject=draft["subject"],
        html_body=draft["html_body"],
        to_email=draft["to_email"],
        reviewer_id=reviewer_id,
        rendered_template=draft["rendered_template"],
        langsmith_run_id=draft["langsmith_run_id"],
    )
    logger.info("Draft %s approved by %s", draft_id, reviewer_id)

    try:
        result = send_email(
            to=draft["to_email"],
            subject=draft["subject"],
            html=draft["html_body"],
        )
        _insert_row(
            draft_id=draft_id,
            user_id=draft["user_id"],
            nudge_type=draft["nudge_type"],
            template_id=draft["template_id"],
            variant_id=draft["variant_id"],
            computation_id=draft["computation_id"],
            delivery_status="sent",
            subject=draft["subject"],
            html_body=draft["html_body"],
            to_email=draft["to_email"],
            reviewer_id=reviewer_id,
            provider_message_id=result.message_id,
            delivered=True,
        )
        logger.info(
            "Draft %s sent to user %s (resend_id=%s)",
            draft_id, draft["user_id"], result.message_id,
        )
    except EmailSendError as e:
        _insert_row(
            draft_id=draft_id,
            user_id=draft["user_id"],
            nudge_type=draft["nudge_type"],
            template_id=draft["template_id"],
            variant_id=draft["variant_id"],
            computation_id=draft["computation_id"],
            delivery_status="failed",
            subject=draft["subject"],
            html_body=draft["html_body"],
            to_email=draft["to_email"],
            reviewer_id=reviewer_id,
            review_notes=str(e),
        )
        logger.warning("Draft %s send failed: %s", draft_id, e)
        raise


def _load_latest_draft_state(draft_id: str) -> dict:
    """Return the latest row for draft_id as a dict.

    Raises LookupError if the draft doesn't exist.
    """
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
            """
                SELECT user_id, nudge_type, template_id, variant_id,
                    computation_id, delivery_status, subject, html_body,
                    to_email, flag_code, rendered_template, langsmith_run_id
                FROM nudge_events
                WHERE draft_id = %s
                ORDER BY created_at DESC, nudge_id DESC
                LIMIT 1
                """,
                (draft_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"Draft {draft_id} not found")
            cols = [
                "user_id", "nudge_type", "template_id", "variant_id",
                "computation_id", "delivery_status", "subject", "html_body",
                "to_email", "flag_code", "rendered_template", "langsmith_run_id",
            ]
            return dict(zip(cols, row))


def _insert_row(
    *,
    draft_id: str,
    user_id: int,
    nudge_type: str,
    template_id: str,
    variant_id: str | None,
    computation_id: int | None,
    delivery_status: str,
    subject: str | None,
    html_body: str | None,
    to_email: str | None,
    flag_code: str | None = None,
    rendered_template: str | None = None,
    langsmith_run_id: str | None = None,
    reviewer_id: str | None = None,
    review_notes: str | None = None,
    provider_message_id: str | None = None,
    delivered: bool = False,
) -> int:
    """Insert one lifecycle row. Returns the new nudge_id."""
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO nudge_events (
                    draft_id, user_id, computation_id, nudge_type, flag_code,
                    template_id, variant_id, channel, delivery_status,
                    subject, html_body, to_email, rendered_template,
                    langsmith_run_id, reviewer_id, review_notes,
                    provider_message_id, delivered_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 'email', %s,
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s THEN NOW() ELSE NULL END
                )
                RETURNING nudge_id
                """,
                (
                    draft_id, user_id, computation_id, nudge_type, flag_code,
                    template_id, variant_id, delivery_status,
                    subject, html_body, to_email, rendered_template,
                    langsmith_run_id, reviewer_id, review_notes,
                    provider_message_id, delivered,
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("INSERT ... RETURNING returned no row")
            return row[0]