-- Incremental schema updates for enrollment analytics and student summaries (PostgreSQL)
-- Safe to re-run: uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS throughout.

ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS last_activity_at TEXT;
ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS total_activity_time INTEGER;
ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS current_score REAL;
ALTER TABLE enrollments ADD COLUMN IF NOT EXISTS final_score REAL;

CREATE TABLE IF NOT EXISTS student_summaries (
    user_id              INTEGER PRIMARY KEY REFERENCES users(user_id),
    page_views           INTEGER,
    max_page_views       INTEGER,
    participations       INTEGER,
    max_participations   INTEGER,
    tardiness_on_time    INTEGER,
    tardiness_late       INTEGER,
    tardiness_missing    INTEGER,
    tardiness_floating   INTEGER,
    tardiness_total      INTEGER,
    pulled_at            TEXT
);
