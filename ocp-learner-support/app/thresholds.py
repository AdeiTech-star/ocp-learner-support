"""Threshold configuration.

Thresholds are versioned and immutable in storage: every flag_computations row
records which version produced it. Changing thresholds means creating a new
version, not mutating the current one — this preserves auditability.

The v1 defaults below are HEURISTIC. They are placeholders until we back-fit
against a past cohort (see decisions doc §3, "What I need from you"). The
severity-point aggregation is deliberately simple and explainable — Muhammad
can read this file and predict the output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ThresholdConfig(BaseModel):
    """One versioned threshold configuration.

    Aggregation model: each signal contributes 0, 1, or 2 severity points.
    Total points determine the level. This is coarse on purpose — with no
    calibration data yet, a continuous risk score would give false precision.
    """

    model_config = ConfigDict(frozen=True)

    version_label: str

    # Login recency (days since last_activity_at)
    login_days_yellow: int = 7      # 1 point
    login_days_red: int = 14        # 2 points

    # On-time submission rate: tardiness_on_time / tardiness_total
    on_time_rate_yellow: float = Field(default=0.75, ge=0.0, le=1.0)
    on_time_rate_red: float = Field(default=0.50, ge=0.0, le=1.0)

    # Current gradebook score (0-100)
    score_yellow: float = 65.0
    score_red: float = 50.0

    # Engagement ratio: page_views / max_page_views
    engagement_yellow: float = Field(default=0.50, ge=0.0, le=1.0)
    engagement_red: float = Field(default=0.25, ge=0.0, le=1.0)

    # Aggregation cut points (total severity points → level)
    yellow_min_points: int = 2
    red_min_points: int = 4

    # Freshness: how old summary_pulled_at can be before we return 'unknown'
    freshness_hours: int = 48

    # Gate-approach window (mirrors decisions doc §1)
    gate_days_window: int = 7
    gate_tasks_window: int = 2


V1_HEURISTIC = ThresholdConfig(version_label="v1-heuristic-2026-08")
"""Default config used until calibration data is available.

Rationale for each cut point (all TENTATIVE, revisit after calibration):
  * login_days: a full week without any activity is unusual for an active
    learner; two weeks strongly suggests disengagement.
  * on_time_rate: 3/4 on-time is the informal norm; below half is a pattern.
  * score: 65 = borderline pass in most rubrics; 50 = at risk of failing.
  * engagement: half of expected pageviews is a soft signal; a quarter is loud.
  * yellow_min_points=2, red_min_points=4: yellow triggers on any two
    moderate signals or one severe; red triggers on two severe or four
    moderate. Change these once we know the base rate we want.
"""