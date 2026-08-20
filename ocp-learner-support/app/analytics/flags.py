"""
Flag detection engine for AIML04 learner support system.
Reads student_risk_signals, applies detection rules, writes to flag_events.
Owned by: Gentille Uwera
"""
import json
import logging
import psycopg
from datetime import datetime, timezone
from app.config import settings

log = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def already_flagged(cur, user_id: int, reason_code: str) -> bool:
    """Return True if this user already has an unresolved flag with this reason code."""
    cur.execute(
        """
        SELECT 1 FROM flag_events
        WHERE user_id = %s AND reason LIKE %s AND resolved = 0
        LIMIT 1
        """,
        (user_id, f"{reason_code}%")
    )
    return cur.fetchone() is not None


def insert_flag(cur, user_id: int, flag_type: str, reason: str, inputs: dict):
    cur.execute(
        """
        INSERT INTO flag_events (user_id, flagged_at, flag_type, reason, inputs, resolved)
        VALUES (%s, %s, %s, %s, %s, 0)
        """,
        (user_id, utcnow(), flag_type, reason, json.dumps(inputs))
    )


def run_flags(conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    flag_count = 0

    cur.execute("""
        SELECT
            r.user_id,
            r.avg_days_from_deadline,
            r.timing_trend,
            r.days_since_last_login,
            r.total_submissions,
            r.zero_submissions,
            r.engagement_ratio,
            r.gate_approaching,
            r.gate_name,
            r.days_until_gate,
            e.final_score
        FROM student_risk_signals r
        LEFT JOIN enrollments e ON r.user_id = e.user_id
    """)
    rows = cur.fetchall()

    for row in rows:
        (user_id, avg_timing, trend, days_silent, total_subs,
         zero_subs, engagement, gate_approaching, gate_name,
         days_until_gate, current_score) = row

        # R1: Zero submissions and silent for more than 14 days
        if zero_subs and days_silent is not None and days_silent > 14:
            if not already_flagged(cur, user_id, "R1"):
                insert_flag(cur, user_id, "red", f"R1: No submissions and silent for {days_silent} days", {
                    "zero_submissions": zero_subs,
                    "days_since_last_login": days_silent,
                    "total_submissions": total_subs
                })
                flag_count += 1
                log.info("RED R1: user %s silent %s days, zero submissions", user_id, days_silent)

        # R2: Severely late and barely started
        if avg_timing is not None and avg_timing < -10 and total_subs < 3:
            if not already_flagged(cur, user_id, "R2"):
                insert_flag(cur, user_id, "red", f"R2: Average {avg_timing:.1f} days late with only {total_subs} submissions", {
                    "avg_days_from_deadline": avg_timing,
                    "total_submissions": total_subs
                })
                flag_count += 1
                log.info("RED R2: user %s avg %.1fd late, only %s submissions", user_id, avg_timing, total_subs)

        # R3: Gate approaching and already behind
        if gate_approaching and avg_timing is not None and avg_timing < -5:
            if not already_flagged(cur, user_id, "R3"):
                insert_flag(cur, user_id, "red", f"R3: {gate_name} gate in {days_until_gate} days, already averaging {avg_timing:.1f}d late", {
                    "gate_name": gate_name,
                    "days_until_gate": days_until_gate,
                    "avg_days_from_deadline": avg_timing
                })
                flag_count += 1
                log.info("RED R3: user %s gate %s in %s days, avg %.1fd", user_id, gate_name, days_until_gate, avg_timing)

        # Y1: No submissions but still active (7-14 days since login)
        if zero_subs and days_silent is not None and 7 < days_silent <= 14:
            if not already_flagged(cur, user_id, "Y1"):
                insert_flag(cur, user_id, "yellow", f"Y1: No submissions but logged in {days_silent} days ago", {
                    "zero_submissions": zero_subs,
                    "days_since_last_login": days_silent,
                    "engagement_ratio": engagement
                })
                flag_count += 1
                log.info("YELLOW Y1: user %s no submissions, last seen %s days ago", user_id, days_silent)

        # Y1b: No submissions but still active within the last 7 days
        if zero_subs and days_silent is not None and days_silent <= 7:
            if not already_flagged(cur, user_id, "Y1b"):
                insert_flag(cur, user_id, "yellow", f"Y1b: No formal submissions but logged in {days_silent} days ago — engaging but not submitting", {
                    "zero_submissions": zero_subs,
                    "days_since_last_login": days_silent,
                    "engagement_ratio": engagement
                })
                flag_count += 1
                log.info("YELLOW Y1b: user %s active but no submissions, last seen %s days ago", user_id, days_silent)

        # Y2: Consistently late but still progressing
        if avg_timing is not None and -10 <= avg_timing < -5 and total_subs >= 3:
            if not already_flagged(cur, user_id, "Y2"):
                insert_flag(cur, user_id, "yellow", f"Y2: Averaging {avg_timing:.1f} days late across {total_subs} submissions", {
                    "avg_days_from_deadline": avg_timing,
                    "total_submissions": total_subs,
                    "timing_trend": trend
                })
                flag_count += 1
                log.info("YELLOW Y2: user %s avg %.1fd late, %s submissions", user_id, avg_timing, total_subs)

        # Y3: Worsening trend and already negative
        if trend == "worsening" and avg_timing is not None and avg_timing < 0:
            if not already_flagged(cur, user_id, "Y3"):
                insert_flag(cur, user_id, "yellow", f"Y3: Submission timing is worsening, currently averaging {avg_timing:.1f}d from deadline", {
                    "timing_trend": trend,
                    "avg_days_from_deadline": avg_timing
                })
                flag_count += 1
                log.info("YELLOW Y3: user %s worsening trend, avg %.1fd", user_id, avg_timing)

        # Y4: Submitting but score unexpectedly low
        if total_subs > 0 and current_score is not None and current_score > 0 and current_score < 70:
            if not already_flagged(cur, user_id, "Y4"):
                insert_flag(cur, user_id, "yellow", f"Y4: Has {total_subs} submissions but final score is {current_score:.1f}%", {
                    "total_submissions": total_subs,
                    "current_score": current_score
                })
                flag_count += 1
                log.info("YELLOW Y4: user %s score %.1f%%", user_id, current_score)

    conn.commit()
    log.info("Flags run complete: %s new flags raised", flag_count)
    return flag_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    conn = psycopg.connect(settings.database_url)
    try:
        count = run_flags(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT flag_id, user_id, flag_type, reason, flagged_at
            FROM flag_events ORDER BY flagged_at DESC
        """)
        rows = cur.fetchall()
        print(f"\nAll flag events ({len(rows)} total):")
        for r in rows:
            print(f"  [{r[2].upper()}] user {r[1]} — {r[3]}")
    finally:
        conn.close()
