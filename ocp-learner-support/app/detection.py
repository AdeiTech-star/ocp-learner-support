"""Core detection logic.

The main entry point is `evaluate_flag` — a pure function that takes signals,
thresholds, and gate context, and returns a FlagResult. Purity matters here:
it's what makes the decisions auditable and testable without a database.

The DB-touching orchestrator (`compute_flag`) lives in db.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .models import FlagLevel, FlagResult, GateContext, SignalSnapshot
from .thresholds import ThresholdConfig


# ---------------------------------------------------------------------------
# Integrity hash
# ---------------------------------------------------------------------------

def integrity_hash(
    *,
    user_id: int,
    computed_at: datetime,
    flag_level: str,
    threshold_version_label: str,
    feature_snapshot: dict,
    reason_codes: list[str],
) -> str:
    """SHA-256 over a canonical serialization of the decision inputs+outputs.

    Purpose: tamper-evidence on the audit log. Given a stored row, anyone
    can recompute this hash from the row's own fields and check it matches.
    Keys sorted; separators tight; timestamps as ISO 8601 with tz — so the
    same inputs always hash identically.
    """
    payload = {
        "user_id": user_id,
        "computed_at": computed_at.astimezone(timezone.utc).isoformat(),
        "flag_level": flag_level,
        "threshold_version_label": threshold_version_label,
        "feature_snapshot": feature_snapshot,
        "reason_codes": sorted(reason_codes),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Freshness check
# ---------------------------------------------------------------------------

def _is_stale(
    signals: SignalSnapshot,
    thresholds: ThresholdConfig,
    now: datetime,
) -> bool:
    """True if the summary is older than the freshness window.

    A missing summary_pulled_at is treated as stale — we can't verify
    freshness, so we don't assume it. Better to return 'unknown' than to
    return green from stale data.
    """
    if signals.summary_pulled_at is None:
        return True
    age = now - signals.summary_pulled_at
    return age.total_seconds() > thresholds.freshness_hours * 3600


# ---------------------------------------------------------------------------
# Per-signal severity scoring
# ---------------------------------------------------------------------------

def _score_login(signals: SignalSnapshot, cfg: ThresholdConfig, now: datetime) -> tuple[int, list[str]]:
    """Days since last activity → 0/1/2 points."""
    if signals.last_activity_at is None:
        # Learner has never been active. Not stale data — genuinely no activity.
        return 2, ["login_never"]
    days = (now - signals.last_activity_at).days
    if days >= cfg.login_days_red:
        return 2, [f"login_stale_red:{days}d"]
    if days >= cfg.login_days_yellow:
        return 1, [f"login_stale_yellow:{days}d"]
    return 0, []


def _score_timeliness(signals: SignalSnapshot, cfg: ThresholdConfig) -> tuple[int, list[str]]:
    """On-time rate → 0/1/2 points. Skips scoring if no submissions yet."""
    if not signals.tardiness_total or signals.tardiness_on_time is None:
        return 0, ["timeliness_no_data"]
    rate = signals.tardiness_on_time / signals.tardiness_total
    if rate < cfg.on_time_rate_red:
        return 2, [f"timeliness_red:{rate:.2f}"]
    if rate < cfg.on_time_rate_yellow:
        return 1, [f"timeliness_yellow:{rate:.2f}"]
    return 0, []


def _score_grade(signals: SignalSnapshot, cfg: ThresholdConfig) -> tuple[int, list[str]]:
    """Current score → 0/1/2 points. Skips scoring if no graded work yet."""
    if signals.current_score is None:
        return 0, ["grade_no_data"]
    if signals.current_score < cfg.score_red:
        return 2, [f"grade_red:{signals.current_score:.1f}"]
    if signals.current_score < cfg.score_yellow:
        return 1, [f"grade_yellow:{signals.current_score:.1f}"]
    return 0, []


def _score_engagement(signals: SignalSnapshot, cfg: ThresholdConfig) -> tuple[int, list[str]]:
    """page_views / max_page_views → 0/1/2 points."""
    if not signals.max_page_views or signals.page_views is None:
        return 0, ["engagement_no_data"]
    ratio = signals.page_views / signals.max_page_views
    if ratio < cfg.engagement_red:
        return 2, [f"engagement_red:{ratio:.2f}"]
    if ratio < cfg.engagement_yellow:
        return 1, [f"engagement_yellow:{ratio:.2f}"]
    return 0, []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _points_to_level(points: int, cfg: ThresholdConfig) -> FlagLevel:
    if points >= cfg.red_min_points:
        return "red"
    if points >= cfg.yellow_min_points:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evaluate_flag(
    *,
    signals: SignalSnapshot,
    thresholds: ThresholdConfig,
    gate_context: GateContext,
    now: datetime | None = None,
) -> FlagResult:
    """Compute a flag from signals. Pure — no I/O, no clock reads unless `now` is None.

    Deterministic given identical inputs (including `now`). This is what makes
    the integrity hash meaningful: anyone with the stored feature_snapshot and
    threshold config can replay the decision.
    """
    now = now or datetime.now(timezone.utc)

    # Freshness gate → unknown
    if _is_stale(signals, thresholds, now):
        reason_codes = ["stale_signal:summary_pulled_at"]
        feature_snapshot = signals.model_dump(mode="json")
        return FlagResult(
            user_id=signals.user_id,
            computed_at=now,
            flag_level="unknown",
            reason_codes=reason_codes,
            threshold_version_label=thresholds.version_label,
            feature_snapshot=feature_snapshot,
            gate_context=gate_context,
            integrity_hash=integrity_hash(
                user_id=signals.user_id,
                computed_at=now,
                flag_level="unknown",
                threshold_version_label=thresholds.version_label,
                feature_snapshot=feature_snapshot,
                reason_codes=reason_codes,
            ),
        )

    # Sum severity points across all four signals
    total_points = 0
    reason_codes: list[str] = []
    for scorer in (_score_login, _score_timeliness, _score_grade, _score_engagement):
        if scorer is _score_login:
            pts, codes = scorer(signals, thresholds, now)  # type: ignore[arg-type]
        else:
            pts, codes = scorer(signals, thresholds)  # type: ignore[arg-type]
        total_points += pts
        reason_codes.extend(codes)

    level = _points_to_level(total_points, thresholds)
    reason_codes.append(f"total_points:{total_points}")

    feature_snapshot = signals.model_dump(mode="json")
    return FlagResult(
        user_id=signals.user_id,
        computed_at=now,
        flag_level=level,
        reason_codes=reason_codes,
        threshold_version_label=thresholds.version_label,
        feature_snapshot=feature_snapshot,
        gate_context=gate_context,
        integrity_hash=integrity_hash(
            user_id=signals.user_id,
            computed_at=now,
            flag_level=level,
            threshold_version_label=thresholds.version_label,
            feature_snapshot=feature_snapshot,
            reason_codes=reason_codes,
        ),
    )