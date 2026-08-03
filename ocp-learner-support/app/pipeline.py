"""
Main pipeline orchestrator for AIML04 Canvas ingestion.
Calls all sync functions in order and logs the run.
Owned by: Gentille Uwera
"""
import logging
import psycopg
from app.canvas import CanvasClient
from app.config import settings
from app.ingestion import (
    sync_students,
    sync_assignments,
    sync_enrollments,
    sync_submissions,
    sync_quizzes,
    sync_student_summaries,
    sync_course_activity,
    deduplicate_gate_calendar,
    load_gate_calendar,
)
from app.analytics import compute_risk_signals

log = logging.getLogger(__name__)


def run_pipeline():
    log.info("Pipeline starting")
    conn = psycopg.connect(settings.database_url)
    client = CanvasClient()
    try:
        load_gate_calendar(conn)
        deduplicate_gate_calendar(conn)
        sync_students(client=client, conn=conn)
        sync_assignments(client=client, conn=conn)
        sync_enrollments(client=client, conn=conn)
        sync_submissions(client=client, conn=conn)
        sync_quizzes(client=client, conn=conn)
        sync_student_summaries(client=client, conn=conn)
        sync_course_activity(client=client, conn=conn)
        compute_risk_signals(conn)
        log.info("Pipeline completed successfully")
    except Exception as e:
        log.exception("Pipeline failed: %s", e)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_pipeline()
