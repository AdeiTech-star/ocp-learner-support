"""Nudge lifecycle endpoints: review queue + audit log.

Consumed by the reviewer dashboard. Business logic lives in app.nudges;
this module is a thin HTTP adapter around it.
"""
import logging
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import nudges
from app.config import settings
from app.email_student import EmailSendError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nudges", tags=["nudges"])


# ---- Response / request models ----------------------------------------------

class PendingDraft(BaseModel):
    draft_id: str
    user_id: int
    nudge_type: str
    template_id: str
    to_email: str
    subject: str
    html_body: str
    created_at: str


class AuditRow(BaseModel):
    nudge_id: int
    draft_id: str
    user_id: int
    nudge_type: str
    template_id: str
    delivery_status: str
    reviewer_id: str | None
    review_notes: str | None
    provider_message_id: str | None
    delivered_at: str | None
    created_at: str


class ApproveRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1)


class RejectRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1)
    notes: str | None = None


# ---- Endpoints ---------------------------------------------------------------

@router.get("/pending", response_model=list[PendingDraft])
def list_pending():
    """All drafts currently awaiting review.

    A draft is 'pending' if its latest lifecycle row has status
    pending_review. Uses DISTINCT ON to get latest state per draft.
    """
    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (draft_id)
                    draft_id, user_id, nudge_type, template_id,
                    to_email, subject, html_body, delivery_status, created_at
                FROM nudge_events
                ORDER BY draft_id, created_at DESC, nudge_id DESC
                """
            )
            rows = cur.fetchall()

    return [
        PendingDraft(
            draft_id=str(r[0]),
            user_id=r[1],
            nudge_type=r[2],
            template_id=r[3],
            to_email=r[4],
            subject=r[5],
            html_body=r[6],
            created_at=r[8].isoformat(),
        )
        for r in rows if r[7] == "pending_review"
    ]

@router.post("/{draft_id}/approve")
def approve(draft_id: str, req: ApproveRequest):
    """Reviewer approved — dispatch to the send path."""
    try:
        nudges.send_approved_draft(draft_id, reviewer_id=req.reviewer_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    except ValueError as e:
        # Illegal state transition (e.g. already sent, already rejected)
        raise HTTPException(status_code=409, detail=str(e))
    except EmailSendError as e:
        # Approval was logged, but send failed. Not a client bug — return 502
        # so the dashboard can surface it without retrying automatically.
        logger.warning("Send failed after approval for %s: %s", draft_id, e)
        raise HTTPException(status_code=502, detail=f"Approved, send failed: {e}")
    return {"draft_id": draft_id, "status": "sent"}


@router.post("/{draft_id}/reject")
def reject(draft_id: str, req: RejectRequest):
    """Reviewer rejected — log it, no send."""
    try:
        nudges.reject_draft(draft_id, reviewer_id=req.reviewer_id, notes=req.notes)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"draft_id": draft_id, "status": "rejected"}


@router.get("/audit", response_model=list[AuditRow])
def audit(
    status: Literal["pending_review", "approved", "rejected", "sent", "failed"] | None
        = Query(default=None, description="Filter by delivery_status"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Full history, newest first. Optional status filter for the Audit tab."""
    where = ""
    params: tuple = ()
    if status is not None:
        where = "WHERE delivery_status = %s"
        params = (status,)

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT nudge_id, draft_id, user_id, nudge_type, template_id,
                       delivery_status, reviewer_id, review_notes,
                       provider_message_id, delivered_at, created_at
                FROM nudge_events
                {where}
                ORDER BY nudge_id DESC
                LIMIT %s
                """,
                params + (limit,),
            )
            rows = cur.fetchall()

    return [
        AuditRow(
            nudge_id=r[0],
            draft_id=str(r[1]),
            user_id=r[2],
            nudge_type=r[3],
            template_id=r[4],
            delivery_status=r[5],
            reviewer_id=r[6],
            review_notes=r[7],
            provider_message_id=r[8],
            delivered_at=r[9].isoformat() if r[9] else None,
            created_at=r[10].isoformat(),
        )
        for r in rows
    ]