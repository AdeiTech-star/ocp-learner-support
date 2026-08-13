-- OWNERSHIP: Nthabiseng — AI agent draft/review/send lifecycle.
-- Append-only: one row per state transition. Latest row per draft_id
-- represents current state.

CREATE TABLE IF NOT EXISTS nudge_events (
    nudge_id             BIGSERIAL PRIMARY KEY,
    draft_id             UUID NOT NULL,             -- groups rows for one draft
    computation_id       BIGINT,
    rendered_template    TEXT,
    langsmith_run_id     TEXT,
    user_id              INTEGER NOT NULL,
    nudge_type           TEXT NOT NULL
                     CHECK (nudge_type IN (
                         'reengagement', 'late_submission', 'gate_ahead',
                         'activity_no_work', 'score_dropping'
                     )),
    flag_code            TEXT
                     CHECK (flag_code IN ('R1','R2','R3','Y1','Y1b','Y2','Y3','Y4')),
    template_id          TEXT NOT NULL,
    variant_id           TEXT,
    channel              TEXT NOT NULL CHECK (channel IN ('email', 'in_product')),
    delivery_status      TEXT NOT NULL
                         CHECK (delivery_status IN (
                             'pending_review', 'approved', 'rejected',
                             'sent', 'failed'
                         )),
    subject              TEXT,                      -- draft content, needed for review
    html_body            TEXT,                      -- draft content, needed for review
    to_email             TEXT,                      -- where it'll be sent
    reviewer_id          TEXT,                      -- who approved/rejected
    review_notes         TEXT,                      -- optional reason on reject
    delivered_at         TIMESTAMPTZ,
    provider_message_id  TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nudge_events_draft
    ON nudge_events (draft_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_nudge_events_user_time
    ON nudge_events (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_nudge_events_status_time
    ON nudge_events (delivery_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_nudge_events_provider_message_id
    ON nudge_events (provider_message_id)
    WHERE provider_message_id IS NOT NULL;