"""Data models for the OCP detection engine.

Kept deliberately narrow: only the shapes that cross module boundaries
(signals in, thresholds in, result out) live here. Internal helpers stay
private to their modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FlagLevel = Literal["green", "yellow", "red", "unknown"]


class SignalSnapshot(BaseModel):
    """Signals for one learner at compute time.

    Mirrors what we pull from enrollments + student_summaries. Nullable
    fields reflect the reality that OCP data is often partial — the engine
    handles missing values explicitly rather than defaulting them to 0.
    """

    model_config = ConfigDict(frozen=True)

    user_id: int
    # Raw signals
    last_activity_at: datetime | None
    current_score: float | None = Field(default=None, ge=0.0, le=100.0)
    tardiness_on_time: int | None = Field(default=None, ge=0)
    tardiness_late: int | None = Field(default=None, ge=0)
    tardiness_missing: int | None = Field(default=None, ge=0)
    tardiness_total: int | None = Field(default=None, ge=0)
    page_views: int | None = Field(default=None, ge=0)
    max_page_views: int | None = Field(default=None, ge=0)
    # Freshness metadata
    summary_pulled_at: datetime | None
    fetched_at: datetime  # when this snapshot itself was assembled


class GateContext(BaseModel):
    """The nearest upcoming gate for a learner, plus distance."""

    model_config = ConfigDict(frozen=True)

    gate_id: int | None
    gate_name: str | None
    due_at: datetime | None
    days_to_gate: float | None
    tasks_to_gate: int | None
    is_approaching: bool  # ≤7 days OR ≤2 tasks; see decisions doc §1


class FlagResult(BaseModel):
    """Output of evaluate_flag. Written verbatim to flag_computations."""

    model_config = ConfigDict(frozen=True)

    user_id: int
    computed_at: datetime
    flag_level: FlagLevel
    reason_codes: list[str]
    threshold_version_label: str
    feature_snapshot: dict  # canonical serialization of SignalSnapshot
    gate_context: GateContext
    integrity_hash: str