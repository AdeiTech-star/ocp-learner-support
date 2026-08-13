"""Generate drafts from unresolved flag_events.

Runs as a pipeline step after run_flags. For every open flag without an
existing draft in nudge_events, personalizes the appropriate template and
inserts a pending_review row. Idempotent — reruns don't duplicate drafts.

Owned by: Nthabiseng
"""
import logging
from typing import Any

import psycopg
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path

from app.agent import personalize
from app.nudges import create_draft
from app.nudge_routing import route_for_flag

log = logging.getLogger(__name__)

COURSE_NAME = "AIML04: Math Foundations"

TEMPLATE_DIR = Path(__file__).parent / "templates" / "jinja"
_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)


def _parse_flag_code(reason: str) -> str | None:
    """Extract 'R1' from 'R1: no submissions and no login >14d'.

    Returns None if the format doesn't match — caller skips those rows
    with a warning rather than crashing the pipeline.
    """
    if not reason or ":" not in reason:
        return None
    return reason.split(":", 1)[0].strip()


def _build_context(user_id: int, flag_code: str, conn) -> dict[str, Any]:
    """Assemble template context for one (learner, flag) pair.

    Pulls from student_risk_signals, enrollments, student_summaries,
    users, gate_calendar. Fields are populated best-effort — a template
    that references a missing field will render '{{ specific.foo }}' as
    empty rather than error, because StrictUndefined would raise.

    We fill None values with sensible defaults so templates render.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.days_since_last_login,
                r.avg_days_from_deadline,
                r.total_submissions,
                r.gate_name,
                r.days_until_gate,
                r.timing_trend,
                e.final_score,
                e.current_score
            FROM users u
            LEFT JOIN student_risk_signals r ON u.user_id = r.user_id
            LEFT JOIN enrollments e ON u.user_id = e.user_id
            WHERE u.user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if row is None:
        raise LookupError(f"No user row for user_id={user_id}")

    (days_since_login, avg_days_late_raw, total_subs, gate_name,
     days_to_gate, timing_trend, final_score, current_score) = row

    avg_days_late = abs(avg_days_late_raw) if avg_days_late_raw is not None else 0

    specific: dict[str, Any] = {
        "days_inactive": days_since_login or 0,
        "days_since_login": days_since_login or 0,
        "avg_days_late": round(avg_days_late, 1),
        "submission_count": total_subs or 0,
        "current_score": round(current_score, 1) if current_score is not None else 0,
        "gate_name": gate_name or "the upcoming assessment",
        "days_to_gate": days_to_gate or 0,
        "timing_trend": timing_trend or "unknown",
    }

    return {
        "learner_name": f"Student {user_id}",  # her schema stores no names
        "course_name": COURSE_NAME,
        "specific": specific,
    }


def _text_to_html(text: str) -> str:
    """Wrap paragraph-separated LLM output in <p> tags."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paragraphs)


def _flags_without_drafts(conn) -> list[tuple[int, str, str]]:
    """Find unresolved flags that don't yet have a nudge_events row.

    Dedupe key: (user_id, flag_code). Reruns skip flags that already
    have any draft (pending, approved, sent, rejected, failed) — the
    reviewer's decision on a prior draft stands.

    Returns list of (user_id, flag_code, reason).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.user_id, f.reason
            FROM flag_events f
            WHERE f.resolved = 0
              AND NOT EXISTS (
                  SELECT 1 FROM nudge_events n
                  WHERE n.user_id = f.user_id
                    AND n.flag_code = SPLIT_PART(f.reason, ':', 1)
              )
            """
        )
        rows = cur.fetchall()

    candidates: list[tuple[int, str, str]] = []
    for user_id, reason in rows:
        flag_code = _parse_flag_code(reason)
        if flag_code is None:
            log.warning("Skipping user %s: unparseable reason %r", user_id, reason)
            continue
        candidates.append((user_id, flag_code, reason))
    return candidates


def generate_drafts(conn) -> int:
    """Pipeline step: create pending_review drafts for every open flag.

    Returns the number of drafts created. Idempotent.
    """
    log.info("Generating drafts for unresolved flags")

    with conn.cursor() as cur:
        cur.execute("SELECT user_id, email FROM users")
        email_by_user = dict(cur.fetchall())

    candidates = _flags_without_drafts(conn)
    log.info("Found %d flag(s) without drafts", len(candidates))

    created = 0
    for user_id, flag_code, reason in candidates:
        try:
            route = route_for_flag(flag_code)
        except KeyError:
            log.warning("Skipping user %s: no routing for flag %r", user_id, flag_code)
            continue

        to_email = email_by_user.get(user_id)
        if not to_email:
            log.warning("Skipping user %s: no email on file", user_id)
            continue

        try:
            context = _build_context(user_id, flag_code, conn)
        except LookupError as e:
            log.warning("Skipping user %s: %s", user_id, e)
            continue

        context["severity"] = route.severity

        template = _jinja_env.get_template(f"{route.template_name}.j2")
        rendered = template.render(**context)

        personalized_text, run_id = personalize(
            rendered,
            context,
            flag_code=flag_code,
            template_name=route.template_name,
            nudge_type=route.nudge_type,
            user_id=user_id,
            severity=route.severity,
        )
        html_body = _text_to_html(personalized_text)

        subject = _subject_for(route.nudge_type)
        create_draft(
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            user_id=user_id,
            nudge_type=route.nudge_type,
            template_id=route.template_name,
            flag_code=flag_code,
            rendered_template=rendered,
            langsmith_run_id=run_id,
        )
        created += 1

    log.info("Created %d draft(s)", created)
    return created


_SUBJECTS: dict[str, str] = {
    "reengagement":      "Checking in from the AIML04 team",
    "late_submission":   "A note about your recent submissions in AIML04",
    "gate_ahead":        "Getting ready for what's coming up in AIML04",
    "activity_no_work":  "Anything blocking your submissions in AIML04?",
    "score_dropping":    "How can we help — your recent AIML04 scores",
}


def _subject_for(nudge_type: str) -> str:
    return _SUBJECTS.get(nudge_type, f"AIML04 check-in ({nudge_type})")