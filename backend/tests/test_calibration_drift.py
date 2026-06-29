"""Tests for ROADMAP E2 calibration-drift / regime detection.

Adversarial focus:
  * Determinism (identical inputs → identical DriftResult + to_dict twice).
  * Significance-gating (pure-noise recent data does NOT flag drift; measured
    false-positive rate over many seeds stays low, <= ~5%).
  * "insufficient data" beats false alarms (tiny window never flags drift).
  * de_rating bounded [0, 1], never > 1.0, and monotone in effect size.
"""

from __future__ import annotations

import random

import pytest

from backend.app.prediction_markets.calibration_drift import (
    CalibrationBaseline,
    DriftResult,
    DriftSeverity,
    build_baseline,
    confidence_de_rating,
    detect_drift,
)


# ---------------------------------------------------------------------------
# Synthetic data helpers (deterministic given a seeded RNG)
# ---------------------------------------------------------------------------

def _make_window(
    rng: random.Random,
    n: int,
    miscalibration: float = 0.0,
) -> tuple[list[float], list[int]]:
    """Generate a window of resolved predictions with controllable calibration.

    Each prediction has a true probability ``q`` drawn uniformly; the predicted
    probability is reported well-calibrated (= q) when miscalibration == 0, and
    is pushed away from the truth (toward the wrong tail) as miscalibration grows
    in [0, 1].  The outcome is sampled from the TRUE q, so larger miscalibration
    ⇒ worse Brier.
    """
    probs: list[float] = []
    outcomes: list[int] = []
    for _ in range(n):
        q = rng.uniform(0.05, 0.95)
        outcome = 1 if rng.random() < q else 0
        # Reported probability pushed toward the opposite of the truth.
        target = 1.0 - q
        p = q + miscalibration * (target - q)
        p = min(1.0, max(0.0, p))
        probs.append(p)
        outcomes.append(outcome)
    return probs, outcomes


def _baseline_window(rng: random.Random, n: int) -> tuple[list[float], list[int]]:
    return _make_window(rng, n, miscalibration=0.0)


# ---------------------------------------------------------------------------
# build_baseline
# ---------------------------------------------------------------------------

def test_build_baseline_basic():
    bl = build_baseline([0.2, 0.8, 0.5], [0, 1, 1])
    assert isinstance(bl, CalibrationBaseline)
    assert bl.n == 3
    assert 0.0 <= bl.brier <= 1.0
    assert bl.outcome_rate == pytest.approx(2 / 3)


def test_build_baseline_frozen():
    bl = build_baseline([0.2, 0.8], [0, 1])
    with pytest.raises(Exception):
        bl.brier = 0.9  # type: ignore[misc]


def test_build_baseline_empty_raises():
    with pytest.raises(ValueError):
        build_baseline([], [])


def test_build_baseline_outcome_rate():
    bl = build_baseline([0.5] * 4, [1, 1, 0, 0])
    assert bl.outcome_rate == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Strong drift: baseline ~0.18 vs recent ~0.30+ with sufficient N → HIGH
# ---------------------------------------------------------------------------

def _good_baseline() -> CalibrationBaseline:
    # A well-calibrated baseline near Brier ~0.18.
    rng = random.Random(1)
    probs, outs = _make_window(rng, 400, miscalibration=0.0)
    return build_baseline(probs, outs)


def test_clear_drift_flags_high():
    baseline = _good_baseline()
    rng = random.Random(99)
    # Heavily miscalibrated recent window → Brier well above baseline.
    r_probs, r_outs = _make_window(rng, 200, miscalibration=0.9)
    res = detect_drift(baseline, r_probs, r_outs, seed=7)
    assert res.insufficient_data is False
    assert res.drift_detected is True
    assert res.severity == DriftSeverity.HIGH
    assert res.recent_brier > baseline.brier
    assert res.de_rating < 1.0


def test_clear_drift_de_rating_well_below_one():
    baseline = _good_baseline()
    rng = random.Random(99)
    r_probs, r_outs = _make_window(rng, 200, miscalibration=0.9)
    res = detect_drift(baseline, r_probs, r_outs, seed=7)
    assert res.de_rating <= 0.6  # materially de-rated under severe drift


def test_baseline_brier_in_expected_range():
    baseline = _good_baseline()
    # Well-calibrated baseline should sit comfortably below 0.25.
    assert 0.10 <= baseline.brier <= 0.25


def test_recent_brier_clearly_higher_under_drift():
    baseline = _good_baseline()
    rng = random.Random(5)
    r_probs, r_outs = _make_window(rng, 200, miscalibration=0.9)
    res = detect_drift(baseline, r_probs, r_outs, seed=11)
    assert res.recent_brier >= 0.30
    assert res.brier_delta > 0.0


def test_drift_ci_excludes_zero_under_strong_drift():
    baseline = _good_baseline()
    rng = random.Random(3)
    r_probs, r_outs = _make_window(rng, 200, miscalibration=0.9)
    res = detect_drift(baseline, r_probs, r_outs, seed=2)
    assert res.ci_low > 0.0
    assert res.p_value < 0.05


# ---------------------------------------------------------------------------
# No drift: same-distribution recent window → no drift, de_rating 1.0
# ---------------------------------------------------------------------------

def test_same_distribution_no_drift():
    baseline = _good_baseline()
    rng = random.Random(2024)
    r_probs, r_outs = _baseline_window(rng, 200)
    res = detect_drift(baseline, r_probs, r_outs, seed=42)
    assert res.insufficient_data is False
    assert res.drift_detected is False
    assert res.severity == DriftSeverity.NONE
    assert res.de_rating == 1.0


def test_same_distribution_no_drift_multiple_seeds():
    baseline = _good_baseline()
    flagged = 0
    for s in range(20):
        rng = random.Random(10_000 + s)
        r_probs, r_outs = _baseline_window(rng, 200)
        res = detect_drift(baseline, r_probs, r_outs, seed=s)
        if res.drift_detected:
            flagged += 1
    # Same distribution: drift should essentially never fire.
    assert flagged <= 1


# ---------------------------------------------------------------------------
# Insufficient data beats false alarms
# ---------------------------------------------------------------------------

def test_tiny_window_insufficient_data():
    baseline = _good_baseline()
    rng = random.Random(7)
    # Even with severe miscalibration, a tiny window must NOT flag drift.
    r_probs, r_outs = _make_window(rng, 5, miscalibration=0.95)
    res = detect_drift(baseline, r_probs, r_outs, min_recent=30, seed=1)
    assert res.insufficient_data is True
    assert res.drift_detected is False
    assert res.severity == DriftSeverity.NONE
    assert res.de_rating == 1.0


def test_just_below_min_recent_insufficient():
    baseline = _good_baseline()
    rng = random.Random(8)
    r_probs, r_outs = _make_window(rng, 29, miscalibration=0.95)
    res = detect_drift(baseline, r_probs, r_outs, min_recent=30, seed=1)
    assert res.insufficient_data is True
    assert res.drift_detected is False


def test_at_min_recent_is_sufficient():
    baseline = _good_baseline()
    rng = random.Random(9)
    r_probs, r_outs = _make_window(rng, 30, miscalibration=0.0)
    res = detect_drift(baseline, r_probs, r_outs, min_recent=30, seed=1)
    assert res.insufficient_data is False


def test_empty_recent_window_insufficient():
    baseline = _good_baseline()
    res = detect_drift(baseline, [], [], min_recent=30, seed=1)
    assert res.insufficient_data is True
    assert res.drift_detected is False
    assert res.recent_n == 0
    # nan-safe: recent_brier / brier_delta are nan but de_rating still 1.0.
    assert res.de_rating == 1.0


def test_tiny_window_never_flags_many_seeds():
    baseline = _good_baseline()
    for s in range(30):
        rng = random.Random(500 + s)
        r_probs, r_outs = _make_window(rng, 8, miscalibration=0.95)
        res = detect_drift(baseline, r_probs, r_outs, min_recent=30, seed=s)
        assert res.drift_detected is False
        assert res.insufficient_data is True


# ---------------------------------------------------------------------------
# False-positive rate over many seeds (<= ~5%)
# ---------------------------------------------------------------------------

def test_false_positive_rate_under_noise():
    """Same-distribution recent windows should flag drift well under ~5%."""
    baseline = _good_baseline()
    n_trials = 200
    flagged = 0
    for s in range(n_trials):
        rng = random.Random(100_000 + s)
        r_probs, r_outs = _baseline_window(rng, 100)
        res = detect_drift(baseline, r_probs, r_outs, seed=s)
        if res.drift_detected:
            flagged += 1
    fpr = flagged / n_trials
    assert fpr <= 0.05, f"false-positive rate too high: {fpr:.3f}"


def test_false_positive_rate_raw_comparison_would_be_high():
    """Document why significance gating matters: a RAW Brier comparison fires far
    more often than the significance-gated detector on the SAME noise."""
    baseline = _good_baseline()
    n_trials = 200
    raw_flags = 0
    gated_flags = 0
    for s in range(n_trials):
        rng = random.Random(200_000 + s)
        r_probs, r_outs = _baseline_window(rng, 60)
        res = detect_drift(baseline, r_probs, r_outs, seed=s)
        if res.recent_brier > baseline.brier:
            raw_flags += 1
        if res.drift_detected:
            gated_flags += 1
    # Raw point comparison fires far too often; the gated detector collapses it.
    assert raw_flags > gated_flags
    assert gated_flags / n_trials <= 0.05


# ---------------------------------------------------------------------------
# de_rating: bounded, never > 1.0, monotone
# ---------------------------------------------------------------------------

def _result_with_effect(effect: float, detected: bool = True) -> DriftResult:
    return DriftResult(
        drift_detected=detected,
        severity=DriftSeverity.HIGH if effect >= 0.4 else DriftSeverity.LOW,
        insufficient_data=False,
        baseline_brier=0.18,
        recent_brier=0.18 * (1 + effect),
        brier_delta=0.18 * effect,
        ci_low=0.01,
        ci_high=0.05,
        p_value=0.01,
        de_rating=1.0,
        recent_n=100,
        effect_size=effect,
        seed=1,
    )


def test_de_rating_bounded_unit_interval():
    for effect in [0.0, 0.1, 0.2, 0.5, 0.8, 1.0, 2.0, 5.0]:
        d = confidence_de_rating(_result_with_effect(effect))
        assert 0.0 <= d <= 1.0


def test_de_rating_never_above_one():
    # Even a negative / zero effect must not exceed 1.0.
    d = confidence_de_rating(_result_with_effect(0.0, detected=True))
    assert d <= 1.0
    d2 = confidence_de_rating(_result_with_effect(-0.5, detected=True))
    assert d2 <= 1.0


def test_de_rating_no_drift_is_one():
    d = confidence_de_rating(_result_with_effect(0.9, detected=False))
    assert d == 1.0


def test_de_rating_insufficient_data_is_one():
    baseline = _good_baseline()
    rng = random.Random(1)
    r_probs, r_outs = _make_window(rng, 5, miscalibration=0.9)
    res = detect_drift(baseline, r_probs, r_outs, min_recent=30, seed=1)
    assert confidence_de_rating(res) == 1.0


def test_de_rating_monotone_in_effect():
    effects = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 2.0]
    ratings = [confidence_de_rating(_result_with_effect(e)) for e in effects]
    for a, b in zip(ratings, ratings[1:]):
        assert b <= a + 1e-12, f"de_rating not monotone: {ratings}"


def test_de_rating_saturates_at_floor():
    # Very large effect saturates to the floor 1 - max_cut.
    d = confidence_de_rating(_result_with_effect(10.0), max_cut=0.75)
    assert d == pytest.approx(0.25)


def test_de_rating_respects_custom_max_cut():
    d = confidence_de_rating(_result_with_effect(10.0), max_cut=0.5)
    assert d == pytest.approx(0.5)


def test_de_rating_invalid_max_cut_raises():
    with pytest.raises(ValueError):
        confidence_de_rating(_result_with_effect(0.5), max_cut=1.5)


def test_de_rating_invalid_ref_raises():
    with pytest.raises(ValueError):
        confidence_de_rating(_result_with_effect(0.5), high_effect_ref=0.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_determinism_identical_results():
    baseline = _good_baseline()
    rng = random.Random(77)
    r_probs, r_outs = _make_window(rng, 150, miscalibration=0.6)
    res1 = detect_drift(baseline, r_probs, r_outs, seed=123)
    res2 = detect_drift(baseline, r_probs, r_outs, seed=123)
    assert res1 == res2


def test_determinism_to_dict_twice():
    baseline = _good_baseline()
    rng = random.Random(78)
    r_probs, r_outs = _make_window(rng, 150, miscalibration=0.6)
    res = detect_drift(baseline, r_probs, r_outs, seed=123)
    assert res.to_dict() == res.to_dict()


def test_determinism_across_calls_to_dict():
    baseline = _good_baseline()
    rng = random.Random(78)
    r_probs, r_outs = _make_window(rng, 150, miscalibration=0.6)
    d1 = detect_drift(baseline, r_probs, r_outs, seed=123).to_dict()
    d2 = detect_drift(baseline, r_probs, r_outs, seed=123).to_dict()
    assert d1 == d2


def test_different_seed_may_differ_but_deterministic_each():
    baseline = _good_baseline()
    rng = random.Random(80)
    r_probs, r_outs = _make_window(rng, 120, miscalibration=0.3)
    a = detect_drift(baseline, r_probs, r_outs, seed=1)
    b = detect_drift(baseline, r_probs, r_outs, seed=1)
    assert a == b  # same seed → identical


# ---------------------------------------------------------------------------
# Two-sample bootstrap path (raw baseline data supplied)
# ---------------------------------------------------------------------------

def test_two_sample_bootstrap_path_no_drift():
    rng = random.Random(11)
    b_probs, b_outs = _make_window(rng, 300, miscalibration=0.0)
    baseline = build_baseline(b_probs, b_outs)
    r_probs, r_outs = _make_window(rng, 150, miscalibration=0.0)
    res = detect_drift(
        baseline, r_probs, r_outs,
        baseline_probs=b_probs, baseline_outcomes=b_outs, seed=3,
    )
    assert res.drift_detected is False


def test_two_sample_bootstrap_path_drift():
    rng = random.Random(12)
    b_probs, b_outs = _make_window(rng, 300, miscalibration=0.0)
    baseline = build_baseline(b_probs, b_outs)
    r_probs, r_outs = _make_window(rng, 150, miscalibration=0.9)
    res = detect_drift(
        baseline, r_probs, r_outs,
        baseline_probs=b_probs, baseline_outcomes=b_outs, seed=3,
    )
    assert res.drift_detected is True
    assert res.severity == DriftSeverity.HIGH


def test_two_sample_bootstrap_deterministic():
    rng = random.Random(13)
    b_probs, b_outs = _make_window(rng, 200, miscalibration=0.0)
    baseline = build_baseline(b_probs, b_outs)
    r_probs, r_outs = _make_window(rng, 100, miscalibration=0.5)
    res1 = detect_drift(
        baseline, r_probs, r_outs,
        baseline_probs=b_probs, baseline_outcomes=b_outs, seed=9,
    )
    res2 = detect_drift(
        baseline, r_probs, r_outs,
        baseline_probs=b_probs, baseline_outcomes=b_outs, seed=9,
    )
    assert res1 == res2


# ---------------------------------------------------------------------------
# Severity / threshold behavior + immutability
# ---------------------------------------------------------------------------

def test_severity_rank_order():
    assert DriftSeverity.rank(DriftSeverity.NONE) == 0
    assert DriftSeverity.rank(DriftSeverity.LOW) == 1
    assert DriftSeverity.rank(DriftSeverity.HIGH) == 2


def test_result_is_frozen():
    res = detect_drift(_good_baseline(), [0.5] * 30, [1, 0] * 15, seed=1)
    with pytest.raises(Exception):
        res.drift_detected = True  # type: ignore[misc]


def test_meta_is_immutable():
    res = detect_drift(_good_baseline(), [0.5] * 30, [1, 0] * 15, seed=1)
    with pytest.raises(Exception):
        res.meta["alpha"] = 0.99  # type: ignore[index]


def test_low_severity_band():
    """An effect between low and high thresholds, if significant, is LOW."""
    baseline = _good_baseline()
    # Moderate miscalibration; search for a window landing in the LOW band.
    found_low = False
    for s in range(40):
        rng = random.Random(3000 + s)
        r_probs, r_outs = _make_window(rng, 300, miscalibration=0.30)
        res = detect_drift(baseline, r_probs, r_outs, seed=s)
        if res.drift_detected and res.severity == DriftSeverity.LOW:
            found_low = True
            assert 0.15 <= res.effect_size < 0.40
            assert res.de_rating < 1.0
            break
    assert found_low, "expected at least one LOW-severity detection"


def test_high_requires_significance_not_just_effect():
    """A large point effect on a SMALL-but-sufficient window may still fail the
    significance gate; whenever drift is NOT detected, severity is NONE."""
    baseline = _good_baseline()
    rng = random.Random(4242)
    r_probs, r_outs = _make_window(rng, 30, miscalibration=0.10)
    res = detect_drift(baseline, r_probs, r_outs, seed=1)
    if not res.drift_detected:
        assert res.severity == DriftSeverity.NONE
        assert res.de_rating == 1.0


def test_to_dict_keys_present():
    res = detect_drift(_good_baseline(), [0.5] * 30, [1, 0] * 15, seed=1)
    d = res.to_dict()
    for key in [
        "drift_detected", "severity", "insufficient_data", "baseline_brier",
        "recent_brier", "brier_delta", "ci_low", "ci_high", "p_value",
        "de_rating", "recent_n", "effect_size", "seed", "meta",
    ]:
        assert key in d


def test_seed_echoed_in_result():
    res = detect_drift(_good_baseline(), [0.5] * 30, [1, 0] * 15, seed=555)
    assert res.seed == 555
