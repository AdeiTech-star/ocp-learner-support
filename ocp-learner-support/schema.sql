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



-- NTHABISENG

-- ---------------------------------------------------------------------------
-- Gates: curriculum roadmap checkpoints. Populated by curriculum owners.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gates (
    gate_id     SERIAL PRIMARY KEY,
    course_id   INTEGER,                       -- nullable until course model is finalized
    name        TEXT NOT NULL,
    gate_type   TEXT NOT NULL
                CHECK (gate_type IN ('module_transition', 'assessment',
                                     'project_deadline', 'withdrawal_deadline')),
    due_at      TIMESTAMPTZ NOT NULL,
    ordinal     INTEGER,                       -- position in course sequence
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gates_active_due
    ON gates (is_active, due_at);

-- ---------------------------------------------------------------------------
-- Threshold versions: immutable configurations. compute_flag records which
-- version produced each decision so we can replay history if thresholds change.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flag_threshold_versions (
    version_id     SERIAL PRIMARY KEY,
    version_label  TEXT NOT NULL UNIQUE,       -- e.g. 'v1-heuristic-2026-08'
    config         JSONB NOT NULL,             -- full ThresholdConfig serialized
    notes          TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Enforce exactly one active version at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_flag_threshold_versions_one_active
    ON flag_threshold_versions (is_active) WHERE is_active = TRUE;

-- ---------------------------------------------------------------------------
-- Flag computations: append-only audit log. Every compute_flag call writes
-- exactly one row. Never UPDATE or DELETE rows in this table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flag_computations (
    computation_id       BIGSERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users(user_id),
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    flag_level           TEXT NOT NULL
                         CHECK (flag_level IN ('green', 'yellow', 'red', 'unknown')),
    threshold_version_id INTEGER NOT NULL REFERENCES flag_threshold_versions(version_id),
    feature_snapshot     JSONB NOT NULL,       -- signals as seen at compute time
    reason_codes         TEXT[] NOT NULL DEFAULT '{}',
    nearest_gate_id      INTEGER REFERENCES gates(gate_id),
    days_to_gate         REAL,
    tasks_to_gate        INTEGER,
    is_gate_approaching  BOOLEAN NOT NULL DEFAULT FALSE,
    integrity_hash       TEXT NOT NULL         -- SHA-256 hex; see integrity_hash() in detection.py
);

CREATE INDEX IF NOT EXISTS idx_flag_computations_user_time
    ON flag_computations (user_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_flag_computations_level_time
    ON flag_computations (flag_level, computed_at DESC)
    WHERE flag_level IN ('yellow', 'red');

-- ---------------------------------------------------------------------------
-- Nudge events: scaffolded for M3. Populated when the agent sends a nudge.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nudge_events (
    nudge_id         BIGSERIAL PRIMARY KEY,
    computation_id   BIGINT NOT NULL REFERENCES flag_computations(computation_id),
    user_id          INTEGER NOT NULL REFERENCES users(user_id),
    nudge_type       TEXT NOT NULL
                     CHECK (nudge_type IN ('flag_yellow', 'gate_heads_up',
                                           'gate_reminder', 'gate_final')),
    template_id      TEXT NOT NULL,            -- e.g. 'tmpl_yellow_v1'
    variant_id       TEXT,                     -- for M4 A/B
    channel          TEXT NOT NULL CHECK (channel IN ('email', 'in_product')),
    delivered_at     TIMESTAMPTZ,
    delivery_status  TEXT,                     -- 'queued','sent','failed','bounced'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nudge_events_user_time
    ON nudge_events (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Escalation events: scaffolded for M4. Populated when a red flag or
-- persistent yellow requires a human handler.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS escalation_events (
    escalation_id   BIGSERIAL PRIMARY KEY,
    computation_id  BIGINT NOT NULL REFERENCES flag_computations(computation_id),
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    reason          TEXT NOT NULL,             -- e.g. 'red_flag','persistent_yellow','distress_reply'
    assigned_to     TEXT,                      -- handler identifier (TBD role, see decisions doc)
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'in_progress', 'resolved', 'dismissed')),
    resolution      TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_escalation_events_status
    ON escalation_events (status, created_at)
    WHERE status IN ('queued', 'in_progress');

-- ---------------------------------------------------------------------------
-- Add provider message ID for tracing bounces/complaints back from Resend
-- via webhooks. Partial index because most historical rows won't have one.
-- ---------------------------------------------------------------------------
ALTER TABLE nudge_events
    ADD COLUMN IF NOT EXISTS provider_message_id TEXT;

CREATE INDEX IF NOT EXISTS idx_nudge_events_provider_message_id
    ON nudge_events (provider_message_id)
    WHERE provider_message_id IS NOT NULL;