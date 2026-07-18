"""
Canvas data ingestion pipeline for AIML04.
Pulls students, assignments, submissions, and activity into Postgres.
Owned by: Gentille Uwera
"""
import logging
from datetime import datetime, timezone

import psycopg

from app.canvas import CanvasClient, COURSE_ID, TEST_STUDENT_ID, get_roadmap_deadline

log = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def calc_days_from_deadline(due_at: str | None,
                             submitted_at: str | None) -> float | None:
    if not submitted_at or not due_at:
        return None
    due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    sub = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
    return round((due - sub).total_seconds() / 86400, 2)


def sync_students(client: CanvasClient, conn: psycopg.Connection) -> int:
    """Pull the 10 real students only. No instructors, no test student."""
    cur = conn.cursor()
    count = 0
    for user in client.get_paginated(
        f"/api/v1/courses/{COURSE_ID}/users",
        params={"enrollment_type[]": "student"}
    ):
        if user.get("id") == TEST_STUDENT_ID:
            continue
        email = (user.get("email")
                 or user.get("sis_user_id")
                 or user.get("login_id"))
        cur.execute(
            """
            INSERT INTO users (user_id, email, sis_user_id, login_id, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                email=excluded.email,
                sis_user_id=excluded.sis_user_id,
                login_id=excluded.login_id,
                updated_at=excluded.updated_at
            """,
            (user["id"], email, user.get("sis_user_id"),
             user.get("login_id"), utcnow())
        )
        count += 1
    conn.commit()
    log.info("Synced %s students", count)
    return count


def sync_assignments(client: CanvasClient, conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    count = 0
    for a in client.get_paginated(
        f"/api/v1/courses/{COURSE_ID}/assignments"
    ):
        cur.execute(
            """
            INSERT INTO assignments
                (assignment_id, course_id, name, due_at,
                 points_possible, due_at_roadmap, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(assignment_id) DO UPDATE SET
                name=excluded.name,
                due_at_roadmap=excluded.due_at_roadmap,
                updated_at=excluded.updated_at
            """,
            (a["id"], COURSE_ID, a["name"], a.get("due_at"),
             a.get("points_possible"),
             get_roadmap_deadline(a["id"]), utcnow())
        )
        count += 1
    conn.commit()
    log.info("Synced %s assignments", count)
    return count


def sync_submissions(client: CanvasClient, conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    count = 0
    for s in client.get_paginated(
        f"/api/v1/courses/{COURSE_ID}/students/submissions",
        params={"student_ids[]": "all"}
    ):
        if s.get("user_id") == TEST_STUDENT_ID:
            continue
        if not s.get("assignment_id") or not s.get("user_id"):
            continue
        cur.execute(
            "SELECT due_at_roadmap FROM assignments WHERE assignment_id = %s",
            (s["assignment_id"],)
        )
        row = cur.fetchone()
        due = row[0] if row else None
        dfd = calc_days_from_deadline(due, s.get("submitted_at"))
        cur.execute(
            """
            INSERT INTO submissions
                (submission_id, assignment_id, user_id, score, grade,
                 submitted_at, graded_at, workflow_state,
                 late, missing, days_from_deadline, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(assignment_id, user_id) DO UPDATE SET
                score=excluded.score,
                submitted_at=excluded.submitted_at,
                workflow_state=excluded.workflow_state,
                late=excluded.late,
                missing=excluded.missing,
                days_from_deadline=excluded.days_from_deadline,
                updated_at=excluded.updated_at
            """,
            (s.get("id"), s["assignment_id"], s["user_id"],
             s.get("score"), s.get("grade"), s.get("submitted_at"),
             s.get("graded_at"), s.get("workflow_state"),
             int(bool(s.get("late"))), int(bool(s.get("missing"))),
             dfd, utcnow())
        )
        count += 1
    conn.commit()
    log.info("Synced %s submissions", count)
    return count
