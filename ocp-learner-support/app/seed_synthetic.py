"""Synthetic learners for smoke-testing the detection engine.

Sixteen profiles across the four flag levels, plus edge cases. The intent is
predictability: given the v1 heuristic thresholds, each learner should land
on a specific level, and test_detection.py asserts that.

If you later change v1 thresholds, expected_level values here must be
updated — the tests will fail loudly, which is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.models import GateContext, SignalSnapshot

NOW = datetime(2026, 8, 4, 9, 0, 0, tzinfo=timezone.utc)
FRESH_PULL = NOW - timedelta(hours=6)
STALE_PULL = NOW - timedelta(hours=72)


@dataclass(frozen=True)
class SyntheticLearner:
    """One test case: a snapshot plus the level we expect the engine to emit."""

    name: str
    snapshot: SignalSnapshot
    expected_level: str
    note: str


def _mk(
    user_id: int,
    *,
    days_since_login: int | None,
    on_time: int | None,
    total_subs: int | None,
    score: float | None,
    page_views: int | None,
    max_page_views: int | None = 100,
    stale: bool = False,
) -> SignalSnapshot:
    """Compact constructor. Keeps the learner list below readable."""
    last_activity = None if days_since_login is None else NOW - timedelta(days=days_since_login)
    late = 0 if total_subs and on_time is not None else None
    missing = 0 if total_subs and on_time is not None else None
    return SignalSnapshot(
        user_id=user_id,
        last_activity_at=last_activity,
        current_score=score,
        tardiness_on_time=on_time,
        tardiness_late=late,
        tardiness_missing=missing,
        tardiness_total=total_subs,
        page_views=page_views,
        max_page_views=max_page_views,
        summary_pulled_at=STALE_PULL if stale else FRESH_PULL,
        fetched_at=NOW,
    )


LEARNERS: list[SyntheticLearner] = [
    # -------- Green: on track --------
    SyntheticLearner(
        name="Green — model student",
        snapshot=_mk(1, days_since_login=1, on_time=10, total_subs=10, score=88.0, page_views=95),
        expected_level="green",
        note="All signals well above yellow cutoffs.",
    ),
    SyntheticLearner(
        name="Green — borderline",
        snapshot=_mk(2, days_since_login=6, on_time=8, total_subs=10, score=70.0, page_views=55),
        expected_level="green",
        note="Just under yellow triggers on each signal; total points = 0.",
    ),
    SyntheticLearner(
        name="Green — high engagement, decent score",
        snapshot=_mk(3, days_since_login=2, on_time=9, total_subs=10, score=75.0, page_views=80),
        expected_level="green",
        note="",
    ),
    SyntheticLearner(
        name="Green — perfect on-time record",
        snapshot=_mk(4, days_since_login=3, on_time=12, total_subs=12, score=82.0, page_views=70),
        expected_level="green",
        note="",
    ),

    # -------- Yellow: at risk (need ≥2 severity points, <4) --------
    SyntheticLearner(
        name="Yellow — one late week + slipping score",
        snapshot=_mk(5, days_since_login=8, on_time=7, total_subs=10, score=68.0, page_views=60),
        expected_level="yellow",
        note="login_stale_yellow (1) + timeliness_yellow (1) = 2 points.",
    ),
    SyntheticLearner(
        name="Yellow — engagement drop",
        snapshot=_mk(6, days_since_login=5, on_time=9, total_subs=10, score=62.0, page_views=30),
        expected_level="yellow",
        note="engagement_yellow (1) + grade_yellow (1) = 2 points.",
    ),
    SyntheticLearner(
        name="Yellow — single severe signal",
        snapshot=_mk(7, days_since_login=3, on_time=10, total_subs=10, score=45.0, page_views=70),
        expected_level="yellow",
        note="grade_red (2) alone = 2 points.",
    ),
    SyntheticLearner(
        name="Yellow — persistent low engagement",
        snapshot=_mk(8, days_since_login=6, on_time=8, total_subs=10, score=60.0, page_views=35),
        expected_level="yellow",
        note="engagement_yellow (1) + grade_yellow (1) = 2 points.",
    ),

    # -------- Red: intervene now (≥4 severity points) --------
    SyntheticLearner(
        name="Red — inactive + failing",
        snapshot=_mk(9, days_since_login=20, on_time=4, total_subs=10, score=42.0, page_views=20),
        expected_level="red",
        note="login_red (2) + timeliness_red (2) + grade_red (2) + engagement_red (2) = 8.",
    ),
    SyntheticLearner(
        name="Red — never logged in",
        snapshot=_mk(10, days_since_login=None, on_time=0, total_subs=3, score=30.0, page_views=5),
        expected_level="red",
        note="login_never (2) + timeliness_red (2) + grade_red (2) + engagement_red (2) = 8.",
    ),
    SyntheticLearner(
        name="Red — long absence, decent prior work",
        snapshot=_mk(11, days_since_login=21, on_time=7, total_subs=10, score=60.0, page_views=40),
        expected_level="red",
        note="login_red (2) + timeliness_yellow (1) + grade_yellow (1) + engagement_yellow (1) = 5.",
    ),

    # -------- Unknown: stale/missing critical signal --------
    SyntheticLearner(
        name="Unknown — stale summary",
        snapshot=_mk(12, days_since_login=2, on_time=9, total_subs=10, score=80.0, page_views=70, stale=True),
        expected_level="unknown",
        note="summary_pulled_at is 72h old (> 48h freshness window).",
    ),
    SyntheticLearner(
        name="Unknown — no summary at all",
        snapshot=SignalSnapshot(
            user_id=13,
            last_activity_at=NOW - timedelta(days=2),
            current_score=None,
            tardiness_on_time=None,
            tardiness_late=None,
            tardiness_missing=None,
            tardiness_total=None,
            page_views=None,
            max_page_views=None,
            summary_pulled_at=None,
            fetched_at=NOW,
        ),
        expected_level="unknown",
        note="No summary_pulled_at → treated as stale by design.",
    ),

    # -------- Edge cases --------
    SyntheticLearner(
        name="Green — new learner, no submissions yet",
        snapshot=_mk(14, days_since_login=1, on_time=None, total_subs=0, score=None, page_views=10, max_page_views=20),
        expected_level="green",
        note="No graded work or submissions — engine skips those signals, engagement is fine.",
    ),
    SyntheticLearner(
        name="Green — score 64.9 (1 pt only)",
        snapshot=_mk(15, days_since_login=4, on_time=10, total_subs=10, score=64.9, page_views=70),
        expected_level="green",
        note="Score 64.9 gives 1 pt, no other triggers, total 1 < yellow_min_points 2 → green.",
    ),
    SyntheticLearner(
        name="Green — score exactly at 65 cutoff",
        snapshot=_mk(16, days_since_login=4, on_time=10, total_subs=10, score=65.0, page_views=70),
        expected_level="green",
        note="Score exactly at 65 → not below the < cut → 0 pts.",
    ),
]


NO_GATE = GateContext(
    gate_id=None,
    gate_name=None,
    due_at=None,
    days_to_gate=None,
    tasks_to_gate=None,
    is_approaching=False,
)


APPROACHING_GATE = GateContext(
    gate_id=1,
    gate_name="Module 2 assessment",
    due_at=NOW + timedelta(days=5),
    days_to_gate=5.0,
    tasks_to_gate=None,
    is_approaching=True,
)