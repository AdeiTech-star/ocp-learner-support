"""Async database layer.

Uses psycopg 3 with AsyncConnection. Query style is raw SQL with
parameterized values — matches Gentille's existing conventions.

`compute_flag` is the orchestrator: fetch signals + gate + threshold config,
delegate to evaluate_flag, persist the result.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from .detection import evaluate_flag
from .models import FlagResult, GateContext, SignalSnapshot
from .thresholds import ThresholdConfig


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

async def fetch_signals(conn: psycopg.AsyncConnection, user_id: int, *, now: datetime) -> SignalSnapshot:
    """Assemble a SignalSnapshot for one learner.

    Reads from enrollments and student_summaries. Returns fields nullable
    where the underlying data is missing — evaluate_flag handles nulls
    explicitly and does not silently coerce them to zero.

    Note: enrollments.last_activity_at is TEXT in Gentille's schema, so we
    parse it here. Any parse failure yields None (treated as "never active"
    downstream, which is loud rather than silent).
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT
                e.last_activity_at   AS last_activity_at_text,
                e.current_score      AS current_score,
                s.tardiness_on_time  AS tardiness_on_time,
                s.tardiness_late     AS tardiness_late,
                s.tardiness_missing  AS tardiness_missing,
                s.tardiness_total    AS tardiness_total,
                s.page_views         AS page_views,
                s.max_page_views     AS max_page_views,
                s.pulled_at          AS pulled_at_text
            FROM enrollments e
            LEFT JOIN student_summaries s ON s.user_id = e.user_id
            WHERE e.user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )
        row = await cur.fetchone()

    if row is None:
        # No enrollment record — the learner isn't in this course. Return an
        # all-null snapshot rather than raising; the caller decides what to
        # do (usually: skip, don't flag).
        return SignalSnapshot(
            user_id=user_id,
            last_activity_at=None,
            current_score=None,
            tardiness_on_time=None,
            tardiness_late=None,
            tardiness_missing=None,
            tardiness_total=None,
            page_views=None,
            max_page_views=None,
            summary_pulled_at=None,
            fetched_at=now,
        )

    return SignalSnapshot(
        user_id=user_id,
        last_activity_at=_parse_iso_or_none(row["last_activity_at_text"]),
        current_score=row["current_score"],
        tardiness_on_time=row["tardiness_on_time"],
        tardiness_late=row["tardiness_late"],
        tardiness_missing=row["tardiness_missing"],
        tardiness_total=row["tardiness_total"],
        page_views=row["page_views"],
        max_page_views=row["max_page_views"],
        summary_pulled_at=_parse_iso_or_none(row["pulled_at_text"]),
        fetched_at=now,
    )


async def fetch_gate_context(
    conn: psycopg.AsyncConnection,
    user_id: int,
    *,
    now: datetime,
    cfg: ThresholdConfig,
) -> GateContext:
    """Find the nearest upcoming active gate and the learner's distance to it.

    'Distance in tasks' is a placeholder: OCP doesn't yet expose a
    per-learner remaining-tasks-until-gate signal. Until it does, we compute
    days_to_gate only and set tasks_to_gate to None. The 'approaching'
    predicate falls back to the day window.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT gate_id, name, due_at
            FROM gates
            WHERE is_active = TRUE
              AND due_at >= %s
            ORDER BY due_at ASC
            LIMIT 1
            """,
            (now,),
        )
        row = await cur.fetchone()

    if row is None:
        return GateContext(
            gate_id=None,
            gate_name=None,
            due_at=None,
            days_to_gate=None,
            tasks_to_gate=None,
            is_approaching=False,
        )

    days = (row["due_at"] - now).total_seconds() / 86400.0
    is_approaching = days <= cfg.gate_days_window
    # tasks_to_gate is TODO — see docstring. When ready, compute here and
    # apply cfg.gate_tasks_window in the OR.
    return GateContext(
        gate_id=row["gate_id"],
        gate_name=row["name"],
        due_at=row["due_at"],
        days_to_gate=days,
        tasks_to_gate=None,
        is_approaching=is_approaching,
    )


async def fetch_active_thresholds(conn: psycopg.AsyncConnection) -> tuple[int, ThresholdConfig]:
    """Return (version_id, ThresholdConfig) for the currently active version.

    Raises if none is active — running compute_flag with no threshold config
    is a bug we want to surface, not paper over.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT version_id, config
            FROM flag_threshold_versions
            WHERE is_active = TRUE
            LIMIT 1
            """
        )
        row = await cur.fetchone()

    if row is None:
        raise RuntimeError(
            "No active row in flag_threshold_versions. "
            "Seed one before running compute_flag."
        )

    cfg = ThresholdConfig.model_validate(row["config"])
    return row["version_id"], cfg


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

async def persist_flag(
    conn: psycopg.AsyncConnection,
    result: FlagResult,
    *,
    threshold_version_id: int,
) -> int:
    """Insert one row into flag_computations. Returns the new computation_id."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO flag_computations (
                user_id, computed_at, flag_level, threshold_version_id,
                feature_snapshot, reason_codes,
                nearest_gate_id, days_to_gate, tasks_to_gate, is_gate_approaching,
                integrity_hash
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            RETURNING computation_id
            """,
            (
                result.user_id,
                result.computed_at,
                result.flag_level,
                threshold_version_id,
                psycopg.types.json.Jsonb(result.feature_snapshot),
                result.reason_codes,
                result.gate_context.gate_id,
                result.gate_context.days_to_gate,
                result.gate_context.tasks_to_gate,
                result.gate_context.is_approaching,
                result.integrity_hash,
            ),
        )
        row = await cur.fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def compute_flag(
    conn: psycopg.AsyncConnection,
    user_id: int,
    *,
    now: datetime | None = None,
) -> tuple[FlagResult, int]:
    """End-to-end: fetch signals + gate + thresholds, evaluate, persist.

    Returns (result, computation_id). Caller owns the connection and the
    transaction — this function does not commit. That lets a batch runner
    process many learners in one transaction if it wants to.
    """
    now = now or datetime.now(timezone.utc)
    version_id, cfg = await fetch_active_thresholds(conn)
    signals = await fetch_signals(conn, user_id, now=now)
    gate_context = await fetch_gate_context(conn, user_id, now=now, cfg=cfg)
    result = evaluate_flag(
        signals=signals,
        thresholds=cfg,
        gate_context=gate_context,
        now=now,
    )
    computation_id = await persist_flag(conn, result, threshold_version_id=version_id)
    return result, computation_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso_or_none(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string; return None on any failure.

    Failing loudly here would break every compute_flag call over a single
    malformed row, which is worse than returning None (which cleanly maps
    to 'unknown' or 'login_never' downstream).
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt