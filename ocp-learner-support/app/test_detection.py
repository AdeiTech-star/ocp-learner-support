"""Unit tests for the pure detection logic.

These do not touch the database. They exercise `evaluate_flag` against the
synthetic dataset in seed_synthetic.py. The DB layer (db.py) needs a real
Postgres to test properly and is covered by a separate integration suite.
"""

from __future__ import annotations

import pytest

from src.detection import evaluate_flag, integrity_hash
from src.thresholds import V1_HEURISTIC
from tests.seed_synthetic import APPROACHING_GATE, LEARNERS, NO_GATE, NOW


# ---------------------------------------------------------------------------
# One test per synthetic learner: level matches expectation.
# Parametrizing keeps failures granular — you see exactly which learner broke.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("learner", LEARNERS, ids=[l.name for l in LEARNERS])
def test_learner_flag_level_matches_expectation(learner):
    result = evaluate_flag(
        signals=learner.snapshot,
        thresholds=V1_HEURISTIC,
        gate_context=NO_GATE,
        now=NOW,
    )
    assert result.flag_level == learner.expected_level, (
        f"{learner.name}: expected {learner.expected_level}, "
        f"got {result.flag_level}. reason_codes={result.reason_codes}. "
        f"note={learner.note!r}"
    )


# ---------------------------------------------------------------------------
# Determinism: same inputs → same output and same hash. This is what makes
# the audit log verifiable.
# ---------------------------------------------------------------------------

def test_evaluate_flag_is_deterministic():
    learner = LEARNERS[0]
    r1 = evaluate_flag(signals=learner.snapshot, thresholds=V1_HEURISTIC, gate_context=NO_GATE, now=NOW)
    r2 = evaluate_flag(signals=learner.snapshot, thresholds=V1_HEURISTIC, gate_context=NO_GATE, now=NOW)
    assert r1.flag_level == r2.flag_level
    assert r1.reason_codes == r2.reason_codes
    assert r1.integrity_hash == r2.integrity_hash


def test_integrity_hash_changes_when_level_changes():
    """If any auditable field differs, the hash must differ. Otherwise the
    hash gives false assurance."""
    learner = LEARNERS[0]
    result = evaluate_flag(signals=learner.snapshot, thresholds=V1_HEURISTIC, gate_context=NO_GATE, now=NOW)
    tampered = integrity_hash(
        user_id=result.user_id,
        computed_at=result.computed_at,
        flag_level="red",  # changed
        threshold_version_label=result.threshold_version_label,
        feature_snapshot=result.feature_snapshot,
        reason_codes=result.reason_codes,
    )
    assert tampered != result.integrity_hash


def test_integrity_hash_ignores_reason_code_order():
    """Reason codes are conceptually a set — order shouldn't affect the hash."""
    learner = LEARNERS[0]
    result = evaluate_flag(signals=learner.snapshot, thresholds=V1_HEURISTIC, gate_context=NO_GATE, now=NOW)
    shuffled = list(reversed(result.reason_codes))
    hash_shuffled = integrity_hash(
        user_id=result.user_id,
        computed_at=result.computed_at,
        flag_level=result.flag_level,
        threshold_version_label=result.threshold_version_label,
        feature_snapshot=result.feature_snapshot,
        reason_codes=shuffled,
    )
    assert hash_shuffled == result.integrity_hash


# ---------------------------------------------------------------------------
# Gate context passes through unchanged. Gate detection lives in db.py's
# fetch_gate_context; evaluate_flag just records what it was handed.
# ---------------------------------------------------------------------------

def test_gate_context_preserved_in_result():
    learner = LEARNERS[0]
    result = evaluate_flag(
        signals=learner.snapshot,
        thresholds=V1_HEURISTIC,
        gate_context=APPROACHING_GATE,
        now=NOW,
    )
    assert result.gate_context.is_approaching is True
    assert result.gate_context.gate_id == 1
    assert result.gate_context.days_to_gate == 5.0


# ---------------------------------------------------------------------------
# Distribution sanity check: with 16 synthetic learners we expect at least one
# in each level. Catches accidents where a threshold change collapses everyone
# into one bucket.
# ---------------------------------------------------------------------------

def test_synthetic_dataset_covers_all_levels():
    levels = {
        evaluate_flag(
            signals=learner.snapshot,
            thresholds=V1_HEURISTIC,
            gate_context=NO_GATE,
            now=NOW,
        ).flag_level
        for learner in LEARNERS
    }
    assert levels == {"green", "yellow", "red", "unknown"}, (
        f"Synthetic dataset should cover all four levels; got {levels}"
    )