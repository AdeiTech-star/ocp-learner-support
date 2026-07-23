-- AIML04 Learner Support System: Full Baseline Schema (PostgreSQL)
-- Owned by: Gentille Uwera
-- Safe to run on a fresh database. All statements use IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS courses (
    course_id       INTEGER PRIMARY KEY,
    name            TEXT,
    course_code     TEXT,
    workflow_state  TEXT,
    start_at        TEXT,
    end_at          TEXT,
    time_zone       TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY,
    email           TEXT,
    sis_user_id     TEXT,
    login_id        TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id           INTEGER PRIMARY KEY,
    course_id               INTEGER NOT NULL REFERENCES courses(course_id),
    user_id                 INTEGER NOT NULL REFERENCES users(user_id),
    type                    TEXT,
    role                    TEXT,
    enrollment_state        TEXT,
    last_activity_at        TEXT,
    total_activity_time     INTEGER,
    current_score           REAL,
    final_score             REAL,
    created_at              TEXT,
    updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    assignment_id       INTEGER PRIMARY KEY,
    course_id           INTEGER NOT NULL REFERENCES courses(course_id),
    name                TEXT,
    description         TEXT,
    due_at              TEXT,
    unlock_at           TEXT,
    lock_at             TEXT,
    points_possible     REAL,
    grading_type        TEXT,
    submission_types    TEXT,
    published           INTEGER,
    due_at_roadmap      TEXT,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id       INTEGER PRIMARY KEY,
    assignment_id       INTEGER NOT NULL REFERENCES assignments(assignment_id),
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    score               REAL,
    grade               TEXT,
    submitted_at        TEXT,
    graded_at           TEXT,
    workflow_state      TEXT,
    late                INTEGER,
    missing             INTEGER,
    excused             INTEGER,
    attempt             INTEGER,
    days_from_deadline  REAL,
    updated_at          TEXT,
    UNIQUE(assignment_id, user_id)
);

CREATE TABLE IF NOT EXISTS quizzes (
    quiz_id             INTEGER PRIMARY KEY,
    course_id           INTEGER NOT NULL REFERENCES courses(course_id),
    title               TEXT,
    quiz_type           TEXT,
    points_possible     REAL,
    due_at              TEXT,
    published           INTEGER,
    question_count      INTEGER,
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS quiz_submissions (
    quiz_submission_id  INTEGER PRIMARY KEY,
    quiz_id             INTEGER NOT NULL REFERENCES quizzes(quiz_id),
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    score               REAL,
    kept_score          REAL,
    attempt             INTEGER,
    workflow_state      TEXT,
    started_at          TEXT,
    finished_at         TEXT,
    updated_at          TEXT,
    UNIQUE(quiz_id, user_id, attempt)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    run_id                      SERIAL PRIMARY KEY,
    course_id                   INTEGER NOT NULL,
    started_at                  TEXT NOT NULL,
    finished_at                 TEXT,
    status                      TEXT,
    error_message               TEXT,
    courses_synced              INTEGER DEFAULT 0,
    users_synced                INTEGER DEFAULT 0,
    enrollments_synced          INTEGER DEFAULT 0,
    assignments_synced          INTEGER DEFAULT 0,
    submissions_synced          INTEGER DEFAULT 0,
    quizzes_synced              INTEGER DEFAULT 0,
    quiz_submissions_synced     INTEGER DEFAULT 0,
    student_summaries_synced    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gate_calendar (
    gate_id         SERIAL PRIMARY KEY,
    gate_name       TEXT NOT NULL UNIQUE,
    week_number     INTEGER,
    gate_date       TEXT,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS student_summaries (
    user_id                 INTEGER PRIMARY KEY REFERENCES users(user_id),
    page_views              INTEGER,
    max_page_views          INTEGER,
    participations          INTEGER,
    max_participations      INTEGER,
    tardiness_on_time       INTEGER,
    tardiness_late          INTEGER,
    tardiness_missing       INTEGER,
    tardiness_floating      INTEGER,
    tardiness_total         INTEGER,
    pulled_at               TEXT
);

CREATE TABLE IF NOT EXISTS course_activity (
    activity_id     SERIAL PRIMARY KEY,
    activity_date   TEXT NOT NULL UNIQUE,
    views           INTEGER,
    participations  INTEGER
);

CREATE TABLE IF NOT EXISTS flag_events (
    flag_id         SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    flagged_at      TEXT NOT NULL,
    flag_type       TEXT NOT NULL,
    reason          TEXT,
    inputs          TEXT,
    resolved        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS email_log (
    email_id            SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(user_id),
    sent_at             TEXT,
    flag_id             INTEGER REFERENCES flag_events(flag_id),
    approved_by         TEXT,
    opened              INTEGER DEFAULT 0,
    clicked             INTEGER DEFAULT 0,
    reopened_canvas     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS student_risk_signals (
    user_id                     INTEGER PRIMARY KEY REFERENCES users(user_id),
    avg_days_from_deadline      REAL,
    timing_trend                TEXT,
    days_since_last_login       INTEGER,
    total_submissions           INTEGER,
    zero_submissions            INTEGER,
    engagement_ratio            REAL,
    gate_approaching            INTEGER,
    gate_name                   TEXT,
    days_until_gate             INTEGER,
    computed_at                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_enrollments_course ON enrollments(course_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_user ON enrollments(user_id);
CREATE INDEX IF NOT EXISTS idx_assignments_course ON assignments(course_id);
CREATE INDEX IF NOT EXISTS idx_submissions_assignment ON submissions(assignment_id);
CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_quizzes_course ON quizzes(course_id);
CREATE INDEX IF NOT EXISTS idx_quiz_submissions_quiz ON quiz_submissions(quiz_id);
CREATE INDEX IF NOT EXISTS idx_quiz_submissions_user ON quiz_submissions(user_id);
CREATE INDEX IF NOT EXISTS idx_flag_events_user ON flag_events(user_id);
CREATE INDEX IF NOT EXISTS idx_email_log_user ON email_log(user_id);
CREATE INDEX IF NOT EXISTS idx_course_activity_date ON course_activity(activity_date);
CREATE INDEX IF NOT EXISTS idx_risk_signals_user ON student_risk_signals(user_id);
