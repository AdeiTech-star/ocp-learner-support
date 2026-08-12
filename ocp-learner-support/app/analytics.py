"""
Analytics module for AIML04 learner support system.
Computes per-student risk signals from the ingested Canvas data.
Writes results to student_risk_signals table.
Owned by: Gentille Uwera
"""
import logging
import psycopg
from datetime import datetime, timezone
from app.config import settings

log = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def compute_risk_signals(conn: psycopg.Connection) -> int:
    cur = conn.cursor()
    today = today_str()

    # Get all real students
    cur.execute("SELECT user_id FROM users")
    student_ids = [row[0] for row in cur.fetchall()]

    # Get course max page views for engagement ratio
    cur.execute("SELECT MAX(max_page_views) FROM student_summaries")
    row = cur.fetchone()
    course_max_views = row[0] if row and row[0] else 1

    # Get upcoming gates (next 14 days)
    cur.execute("""
        SELECT gate_name, gate_date
        FROM gate_calendar
        WHERE gate_date >= %s
        ORDER BY gate_date ASC
    """, (today,))
    upcoming_gates = cur.fetchall()

    count = 0
    for user_id in student_ids:

        # Average days from deadline across all submitted assignments
        cur.execute("""
            SELECT days_from_deadline
            FROM submissions
            WHERE user_id = %s AND days_from_deadline IS NOT NULL
            ORDER BY submitted_at ASC
        """, (user_id,))
        timing_rows = cur.fetchall()
        deadline_values = [r[0] for r in timing_rows]

        avg_days = None
        timing_trend = "no_data"
        total_submissions = len(deadline_values)

        if deadline_values:
            avg_days = round(sum(deadline_values) / len(deadline_values), 2)
            if len(deadline_values) >= 3:
                mid = len(deadline_values) // 2
                first_half = deadline_values[:mid]
                second_half = deadline_values[mid:]
                avg_first = sum(first_half) / len(first_half)
                avg_second = sum(second_half) / len(second_half)
                diff = avg_second - avg_first
                # Improving = second half is HIGHER (more positive, less late) than first half
                # Worsening = second half is LOWER (more negative, more late) than first half
                if diff > 1:
                    timing_trend = "improving"
                elif diff < -1:
                    timing_trend = "worsening"
                else:
                    timing_trend = "stable"
            else:
                timing_trend = "insufficient_data"

        zero_submissions = 1 if total_submissions == 0 else 0

        # Completed students get a distinct trend label, not a risk-implying one
        cur.execute("SELECT final_score FROM enrollments WHERE user_id = %s", (user_id,))
        fs_row = cur.fetchone()
        final_score = fs_row[0] if fs_row and fs_row[0] is not None else 0
        if final_score == 100.0:
            timing_trend = "completed"

        # Days since last login
        cur.execute("""
            SELECT last_activity_at FROM enrollments WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        days_since_login = None
        if row and row[0]:
            last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_since_login = (now - last).days

        # Engagement ratio
        cur.execute("""
            SELECT page_views FROM student_summaries WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        page_views = row[0] if row and row[0] is not None else 0
        engagement_ratio = round(page_views / course_max_views, 3)

        # Gate proximity (next gate within 7 days)
        gate_approaching = 0
        gate_name = None
        days_until_gate = None
        for gname, gdate in upcoming_gates:
            gate_dt = datetime.strptime(gdate, "%Y-%m-%d")
            delta = (gate_dt - datetime.strptime(today, "%Y-%m-%d")).days
            if 0 <= delta <= 7:
                gate_approaching = 1
                gate_name = gname
                days_until_gate = delta
                break

        cur.execute("""
            INSERT INTO student_risk_signals (
                user_id, avg_days_from_deadline, timing_trend,
                days_since_last_login, total_submissions, zero_submissions,
                engagement_ratio, gate_approaching, gate_name,
                days_until_gate, computed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(user_id) DO UPDATE SET
                avg_days_from_deadline=excluded.avg_days_from_deadline,
                timing_trend=excluded.timing_trend,
                days_since_last_login=excluded.days_since_last_login,
                total_submissions=excluded.total_submissions,
                zero_submissions=excluded.zero_submissions,
                engagement_ratio=excluded.engagement_ratio,
                gate_approaching=excluded.gate_approaching,
                gate_name=excluded.gate_name,
                days_until_gate=excluded.days_until_gate,
                computed_at=excluded.computed_at
        """, (
            user_id, avg_days, timing_trend, days_since_login,
            total_submissions, zero_submissions, engagement_ratio,
            gate_approaching, gate_name, days_until_gate, utcnow()
        ))
        count += 1

    conn.commit()
    log.info("Computed risk signals for %s students", count)
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    conn = psycopg.connect(settings.database_url)
    try:
        compute_risk_signals(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT user_id, avg_days_from_deadline, timing_trend,
                   days_since_last_login, total_submissions,
                   zero_submissions, engagement_ratio,
                   gate_approaching, gate_name, days_until_gate
            FROM student_risk_signals
            ORDER BY avg_days_from_deadline ASC NULLS LAST
        """)
        rows = cur.fetchall()
        print(f"\nRisk signals for {len(rows)} students:")
        print(f"{'user_id':<10} {'avg_timing':<12} {'trend':<20} {'days_silent':<13} {'submitted':<11} {'zero_sub':<10} {'engagement':<12} {'gate?':<7} {'gate_name':<25} {'days_til'}")
        print("-" * 140)
        for r in rows:
            print(f"{r[0]:<10} {str(r[1]):<12} {str(r[2]):<20} {str(r[3]):<13} {r[4]:<11} {r[5]:<10} {str(r[6]):<12} {r[7]:<7} {str(r[8]):<25} {str(r[9])}")
    finally:
        conn.close()
