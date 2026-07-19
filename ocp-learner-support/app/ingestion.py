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


def sync_enrollments(client: CanvasClient, conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    count = 0
    for e in client.get_paginated(
        f"/api/v1/courses/{COURSE_ID}/enrollments",
        params={"type[]": "StudentEnrollment"}
    ):
        user_id = (e.get("user") or {}).get("id")
        grades = e.get("grades") or {}
        cur.execute(
            """
            INSERT INTO enrollments
                (enrollment_id, course_id, user_id, type, role, enrollment_state,
                 last_activity_at, total_activity_time, current_score, final_score,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(enrollment_id) DO UPDATE SET
                type=excluded.type,
                role=excluded.role,
                enrollment_state=excluded.enrollment_state,
                last_activity_at=excluded.last_activity_at,
                total_activity_time=excluded.total_activity_time,
                current_score=excluded.current_score,
                final_score=excluded.final_score,
                updated_at=excluded.updated_at
            """,
            (e.get("id"), COURSE_ID, user_id, e.get("type"),
             e.get("role"), e.get("enrollment_state"),
             e.get("last_activity_at"), e.get("total_activity_time"),
             grades.get("current_score"), grades.get("final_score"),
             e.get("created_at"), e.get("updated_at"))
        )
        count += 1
    conn.commit()
    log.info("Synced %s enrollments", count)
    return count


def sync_student_summaries(client: CanvasClient, conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    count = 0
    for s in client.get_paginated(
        f"/api/v1/courses/{COURSE_ID}/analytics/student_summaries"
    ):
        if s.get("id") == TEST_STUDENT_ID:
            continue
        td = s.get("tardiness_breakdown") or {}
        cur.execute(
            """
            INSERT INTO student_summaries
                (user_id, page_views, max_page_views, participations,
                 max_participations, tardiness_on_time, tardiness_late,
                 tardiness_missing, tardiness_floating, tardiness_total, pulled_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                page_views=excluded.page_views,
                participations=excluded.participations,
                tardiness_on_time=excluded.tardiness_on_time,
                tardiness_late=excluded.tardiness_late,
                tardiness_missing=excluded.tardiness_missing,
                tardiness_floating=excluded.tardiness_floating,
                tardiness_total=excluded.tardiness_total,
                pulled_at=excluded.pulled_at
            """,
            (s["id"], s.get("page_views"), s.get("max_page_views"),
             s.get("participations"), s.get("max_participations"),
             td.get("on_time"), td.get("late"), td.get("missing"),
             td.get("floating"), td.get("total"), utcnow())
        )
        count += 1
    conn.commit()
    log.info("Synced %s student summaries", count)
    return count


def deduplicate_gate_calendar(conn: psycopg.Connection):
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM gate_calendar
        WHERE gate_id NOT IN (
            SELECT MIN(gate_id) FROM gate_calendar GROUP BY gate_name
        )
    """)
    conn.commit()
    log.info("Gate calendar deduplicated")


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
