"""Reviewer dashboard: server-rendered HTML pages.

Uses Jinja templates. Reads data through app.nudges module functions
that the API endpoints also use — keeps HTTP and HTML views consistent.
"""
from pathlib import Path

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import Form, HTTPException
from app import nudges
from app.email_student import EmailSendError
from app.config import settings
from zoneinfo import ZoneInfo
LOCAL_TZ = ZoneInfo("Africa/Kigali")
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from app.agent import personalize
from app import nudges as nudges_module
from app.nudge_routing import route_for_flag, FlagCode
from pydantic import BaseModel, Field
from langsmith import Client as LangSmithClient


REVIEWER_ID = "nthabiseng@test"
router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

JINJA_TEMPLATE_DIR = TEMPLATE_DIR / "jinja"
_jinja_env = Environment(
    loader=FileSystemLoader(str(JINJA_TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)


# Fake contexts per flag code — one per intent, so we can demo every path.
# When real learners flow in, this table goes away and the worker looks
# up each learner's actual context from the DB.
_FAKE_CONTEXTS: dict[str, dict] = {
    "R1": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"days_inactive": 17},
    },
    "Y1": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"days_inactive": 9},
    },
    "R2": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"avg_days_late": 12, "submission_count": 2},
    },
    "Y2": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"avg_days_late": 7, "submission_count": 5},
    },
    "Y3": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"avg_days_late": 6, "submission_count": 8},
    },
    "R3": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {
            "gate_name": "Module 4 project deadline",
            "days_to_gate": 5,
            "avg_days_late": 8,
        },
    },
    "Y1b": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"days_since_login": 2, "submission_count": 0},
    },
    "Y4": {
        "learner_name": "Nthabiseng",
        "course_name": "AI for Africa OCP",
        "specific": {"current_score": 62},
    },
}

_SUBJECTS: dict[str, str] = {
    "reengagement":      "Checking in from the {course} team",
    "late_submission":   "A note about your recent submissions in {course}",
    "gate_ahead":        "Getting ready for what's coming up in {course}",
    "activity_no_work":  "Anything blocking your submissions in {course}?",
    "score_dropping":    "How can we help — your recent {course} scores",
}


@router.post("/generate-draft", response_class=HTMLResponse)
def generate_draft(request: Request, flag_code: str = "Y2"):
    """Run the template → agent → draft pipeline for the given flag.

    Uses hardcoded fake context per flag until real learners flow through
    from the detection engine. Flag defaults to Y2 (mid-severity, most
    common case) so a bare click still does something useful.
    """
    try:
        route = route_for_flag(flag_code)
    except KeyError as e:
        return HTMLResponse(
            f'<div class="text-sm text-red-700 bg-red-50 border border-red-200 '
            f'rounded p-3">{e}</div>',
            status_code=400,
        )

    context = dict(_FAKE_CONTEXTS[flag_code])
    context["severity"] = route.severity

    template = _jinja_env.get_template(f"{route.template_name}.j2")
    rendered = template.render(**context)
    personalized_text, run_id = personalize(
        rendered,
        context,
        flag_code=flag_code,
        template_name=route.template_name,
        nudge_type=route.nudge_type,
        user_id=999,
        severity=route.severity,
)    
    html_body = _text_to_html(personalized_text)

    subject = _SUBJECTS[route.nudge_type].format(course=context["course_name"])

    draft_id = nudges_module.create_draft(
        to_email="nthema@andrew.cmu.edu",
        subject=subject,
        html_body=html_body,
        user_id=999,
        nudge_type=route.nudge_type,
        template_id=route.template_name,
        flag_code=flag_code,
        rendered_template=rendered,
        langsmith_run_id=run_id,
    )

    return HTMLResponse(
        f'<div class="text-sm text-green-700 bg-green-50 border border-green-200 '
        f'rounded p-3">Generated <span class="font-mono">{flag_code}</span> draft '
        f'<span class="font-mono">{draft_id[:8]}…</span>. Reload to see it.</div>',
        status_code=200,
    )

def _text_to_html(text: str) -> str:
    """Wrap paragraph-separated text in <p> tags.

    The agent returns plain prose with blank lines between paragraphs.
    Emails need HTML, so we split on blank lines and wrap each block.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paragraphs)

@router.get("/trace/{run_id}", response_class=HTMLResponse)
def view_trace(request: Request, run_id: str):
    """Fetch prompt + output from LangSmith for a given run.

    Returns an HTML fragment the modal drops in. Fails gracefully if the
    run is missing, expired, or LangSmith is unreachable — auditor sees
    a message instead of a blank modal.
    """
    try:
        client = LangSmithClient()
        run = client.read_run(run_id)
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-sm text-red-700">'
            f'Trace unavailable: {e.__class__.__name__}. Run may have '
            f'expired or LangSmith is unreachable.</div>',
            status_code=200,
        )

    return templates.TemplateResponse(
        request,
        "dashboard/_trace_content.html",
        {
            "run_id": run_id,
            "inputs": run.inputs or {},
            "outputs": run.outputs or {},
        },
    )


@router.get("/", response_class=RedirectResponse)
def dashboard_root():
    """Land users on the review tab by default."""
    return RedirectResponse(url="/dashboard/review", status_code=302)


@router.get("/review", response_class=HTMLResponse)
def review_tab(request: Request):
    """Review tab: table of drafts awaiting reviewer approval."""
    drafts = _load_pending_drafts()
    return templates.TemplateResponse(
        request,
        "dashboard/review.html",
        {"active_tab": "review", "drafts": drafts, "local_tz": LOCAL_TZ},
    )
STATUS_OPTIONS = [
    ("pending_review", "Pending review"),
    ("approved", "Approved"),
    ("rejected", "Rejected"),
    ("sent", "Sent"),
    ("failed", "Failed"),
]

STATUS_COLORS = {
    "pending_review": ("amber-100", "amber-800"),
    "approved":       ("blue-100",  "blue-800"),
    "sent":           ("green-100", "green-800"),
    "rejected":       ("slate-200", "slate-700"),
    "failed":         ("red-100",   "red-800"),
}


@router.get("/audit", response_class=HTMLResponse)
def audit_tab(request: Request, status: str | None = None):
    """Audit tab: full history of every lifecycle transition."""
    # Guard: reject unknown status filters instead of silently ignoring
    valid_statuses = {v for v, _ in STATUS_OPTIONS}
    if status is not None and status != "" and status not in valid_statuses:
        status = None

    rows = _load_audit_rows(status=status or None, limit=200)
    return templates.TemplateResponse(
        request,
        "dashboard/audit.html",
        {
            "active_tab": "audit",
            "rows": rows,
            "status_filter": status or None,
            "status_options": STATUS_OPTIONS,
            "status_colors": STATUS_COLORS,
            "local_tz": LOCAL_TZ,
        },
    )


def _load_audit_rows(status: str | None, limit: int) -> list[dict]:
    """Newest-first history for the audit tab."""
    where = ""
    params: tuple = ()
    if status:
        where = "WHERE delivery_status = %s"
        params = (status,)

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT nudge_id, draft_id, user_id, nudge_type, template_id,
                    delivery_status, reviewer_id, review_notes,
                    provider_message_id, delivered_at, created_at,
                    langsmith_run_id, flag_code
                FROM nudge_events
                {where}
                ORDER BY nudge_id DESC
                LIMIT %s
                """,
                params + (limit,),
            )
            rows = cur.fetchall()

    return [
       {
        "nudge_id": r[0],
        "draft_id": str(r[1]),
        "user_id": r[2],
        "nudge_type": r[3],
        "template_id": r[4],
        "delivery_status": r[5],
        "reviewer_id": r[6],
        "review_notes": r[7],
        "provider_message_id": r[8],
        "delivered_at": r[9],
        "created_at": r[10],
        "langsmith_run_id": r[11],
        "flag_code": r[12],
    }
        for r in rows
    ]

@router.post("/nudges/{draft_id}/approve", response_class=HTMLResponse)
def approve_from_dashboard(request: Request, draft_id: str):
    """HTMX endpoint: approve, send, remove the card from the page."""
    try:
        nudges.send_approved_draft(draft_id, reviewer_id=REVIEWER_ID)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    except ValueError as e:
        return _error_card(request, draft_id, str(e))
    except EmailSendError as e:
        return _error_card(
            request, draft_id,
            f"Approved but send failed: {e}. Row was logged; the email did not go out.",
        )
    # Success: return an empty response. HTMX removes the row.
    return HTMLResponse("", status_code=200)


class RejectPayload(BaseModel):
    notes: str = Field(..., min_length=10, max_length=1000)


@router.post("/nudges/{draft_id}/reject", response_class=HTMLResponse)
def reject_from_dashboard(
    request: Request, draft_id: str, payload: RejectPayload
):
    """HTMX endpoint: reject with a required reason, remove the card."""
    try:
        nudges.reject_draft(
            draft_id, reviewer_id=REVIEWER_ID, notes=payload.notes.strip()
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    except ValueError as e:
        return _error_card(request, draft_id, str(e))
    return HTMLResponse("", status_code=200)


def _error_card(request: Request, draft_id: str, message: str) -> HTMLResponse:
    """Render a small error card that replaces the draft row."""
    return templates.TemplateResponse(
        request,
        "dashboard/_error_row.html",
        {"draft_id": draft_id, "message": message},
        status_code=200,  # HTMX only swaps on 2xx by default
    )


def _load_pending_drafts() -> list[dict]:
    """Same query as the /nudges/pending API endpoint."""
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
        {
            "draft_id": str(r[0]),
            "user_id": r[1],
            "nudge_type": r[2],
            "template_id": r[3],
            "to_email": r[4],
            "subject": r[5],
            "html_body": r[6],
            "created_at": r[8],
        }
        for r in rows if r[7] == "pending_review"
    ]