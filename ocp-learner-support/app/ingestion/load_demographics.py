"""One-time loader: reads demographics CSV and splits into student_pii
and student_demographics. Matches on Email against users.email.

Run BEFORE dropping users.email. After successful load, verify counts
then run the migration to drop the PII from users and nudge_events.
"""
import csv
import logging
import sys

import psycopg

from app.config import settings

log = logging.getLogger(__name__)

CSV_PATH = "../Demographics/Students_Merged.csv"


def load(csv_path: str = CSV_PATH) -> None:
    conn = psycopg.connect(settings.database_url)
    with conn.cursor() as cur:
        cur.execute("SELECT email, user_id FROM users")
        email_to_uid = {e.strip().lower(): uid for e, uid in cur.fetchall() if e}

    loaded, skipped = 0, 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = (row.get("Email") or "").strip().lower()
            if not email:
                skipped += 1
                continue
            user_id = email_to_uid.get(email)
            if user_id is None:
                log.warning("Skipping %s: no matching user in Canvas", email)
                skipped += 1
                continue

            _upsert_pii(conn, user_id, row)
            _upsert_demographics(conn, user_id, row)
            loaded += 1

    conn.commit()
    conn.close()
    log.info("Loaded %d rows, skipped %d", loaded, skipped)


def _upsert_pii(conn, user_id: int, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO student_pii (
                user_id, full_name, email, person_reference_id, prefix,
                most_recent_role, most_recent_employer
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                email = EXCLUDED.email,
                person_reference_id = EXCLUDED.person_reference_id,
                prefix = EXCLUDED.prefix,
                most_recent_role = EXCLUDED.most_recent_role,
                most_recent_employer = EXCLUDED.most_recent_employer,
                loaded_at = NOW()
            """,
            (
                user_id,
                row.get("Name", "").strip(),
                row.get("Email", "").strip(),
                row.get("Person Reference ID"),
                row.get("Person Prefix"),
                row.get("Most recent role"),
                row.get("Most recent employer"),
            ),
        )


def _upsert_demographics(conn, user_id: int, row: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO student_demographics (
                user_id, cohort, age_group, country_of_origin, employment_status,
                highest_education_level, field_of_study, university,
                primary_language, sex, immigration_status,
                skill_programming, days_per_week, skill_genai,
                has_reliable_internet, genai_applied, genai_application_context,
                hours_per_week, skill_vectors_matrices, skill_ml_tools,
                skill_probability_stats, programming_languages_used,
                has_laptop_access, genai_where_learned, vectors_where_learned,
                ml_where_studied, ml_where_applied, probstats_where_learned
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                cohort = EXCLUDED.cohort,
                age_group = EXCLUDED.age_group,
                country_of_origin = EXCLUDED.country_of_origin,
                employment_status = EXCLUDED.employment_status,
                highest_education_level = EXCLUDED.highest_education_level,
                field_of_study = EXCLUDED.field_of_study,
                university = EXCLUDED.university,
                primary_language = EXCLUDED.primary_language,
                sex = EXCLUDED.sex,
                immigration_status = EXCLUDED.immigration_status,
                skill_programming = EXCLUDED.skill_programming,
                days_per_week = EXCLUDED.days_per_week,
                skill_genai = EXCLUDED.skill_genai,
                has_reliable_internet = EXCLUDED.has_reliable_internet,
                genai_applied = EXCLUDED.genai_applied,
                genai_application_context = EXCLUDED.genai_application_context,
                hours_per_week = EXCLUDED.hours_per_week,
                skill_vectors_matrices = EXCLUDED.skill_vectors_matrices,
                skill_ml_tools = EXCLUDED.skill_ml_tools,
                skill_probability_stats = EXCLUDED.skill_probability_stats,
                programming_languages_used = EXCLUDED.programming_languages_used,
                has_laptop_access = EXCLUDED.has_laptop_access,
                genai_where_learned = EXCLUDED.genai_where_learned,
                vectors_where_learned = EXCLUDED.vectors_where_learned,
                ml_where_studied = EXCLUDED.ml_where_studied,
                ml_where_applied = EXCLUDED.ml_where_applied,
                probstats_where_learned = EXCLUDED.probstats_where_learned,
                loaded_at = NOW()
            """,
            (
                user_id,
                row.get("Intake/Cohort/Term of entry"),
                row.get("Person Age group"),
                row.get("Person Country of origin"),
                row.get("Person Employment status"),
                row.get("Person Highest education level"),
                row.get("Field of Study"),
                row.get("University / Institution"),
                row.get("Person Primary language of education"),
                row.get("Person Sex"),
                row.get("Person Immigration status"),
                row.get("Computer Programming"),
                row.get("Days per week for the course"),
                row.get("GenAI tools and applications"),
                row.get("Have regular and reliable internet"),
                row.get("GenAI – Applied?"),
                row.get("GenAI – Application context"),
                row.get("Hours per week"),
                row.get("Maths: Vectors & Matrices"),
                row.get("ML Tools and Applications"),
                row.get("Probability and Statistics"),
                row.get("Programming languages most used"),
                row.get("Regular & reliable access to laptop/desktop"),
                row.get("GenAI – Where learned (category)"),
                row.get("Vectors & Matrices – Where learned (category)"),
                row.get("ML – Where studied (category)"),
                row.get("ML – Where applied (category)"),
                row.get("Probability & Statistics – Where learned (category)"),
            ),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load(sys.argv[1] if len(sys.argv) > 1 else CSV_PATH)