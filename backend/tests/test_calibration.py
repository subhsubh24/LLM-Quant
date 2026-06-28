"""
Tests for ROADMAP B2 — Calibration Evaluation Gate.

Covers:
- brier_score hand-computed values and error handling
- evaluate_calibration: strategy beats baseline (passes=True)
- evaluate_calibration: insufficient samples (passes=False even if brier improves)
- evaluate_calibration: strategy does NOT beat baseline (passes=False)
- reliability_curve binning, empty bins (nan), and ECE for perfect calibration
- brier_score ValueError on empty / mismatched / out-of-range inputs
"""

import math
import random

import pytest

from backend.app.prediction_markets.calibration import (
    CalibrationResult,
    ReliabilityCurve,
    ResolvedPrediction,
    brier_score,
    evaluate_calibration,
    expected_calibration_error,
    reliability_curve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sample(
    predicted_prob: float,
    market_price: float,
    outcome: int,
    market_id: str = "m",
) -> ResolvedPrediction:
    return ResolvedPrediction(
        market_id=market_id,
        predicted_prob=predicted_prob,
        market_price=market_price,
        outcome=outcome,
    )


# 4-sample base pattern used by several tests:
#   preds=[0.7,0.3,0.9,0.2], outcomes=[1,0,1,0]
#   baseline=[0.5,0.6,0.8,0.4]
# Strategy Brier = mean((0.7-1)^2 + (0.3-0)^2 + (0.9-1)^2 + (0.2-0)^2)
#               = mean(0.09 + 0.09 + 0.01 + 0.04) = 0.23/4 = 0.0575
# Baseline Brier = mean((0.5-1)^2 + (0.6-0)^2 + (0.8-1)^2 + (0.4-0)^2)
#               = mean(0.25 + 0.36 + 0.04 + 0.16) = 0.81/4 = 0.2025
_BASE_PREDS = [0.7, 0.3, 0.9, 0.2]
_BASE_BASELINES = [0.5, 0.6, 0.8, 0.4]
_BASE_OUTCOMES = [1, 0, 1, 0]

_BASE_STRATEGY_BRIER = 0.0575
_BASE_BASELINE_BRIER = 0.2025


def _base_samples(n_repeat: int = 1) -> list[ResolvedPrediction]:
    """Return n_repeat copies of the 4-sample base pattern."""
    result = []
    for rep in range(n_repeat):
        for i in range(4):
            result.append(
                _make_sample(
                    predicted_prob=_BASE_PREDS[i],
                    market_price=_BASE_BASELINES[i],
                    outcome=_BASE_OUTCOMES[i],
                    market_id=f"m{rep}_{i}",
                )
            )
    return result


# ---------------------------------------------------------------------------
# brier_score — hand-computed values
# ---------------------------------------------------------------------------

class TestBrierScore:
    def test_hand_computed_value(self):
        """brier_score([0.7,0.3,0.9,0.2], [1,0,1,0]) == 0.0575"""
        result = brier_score(_BASE_PREDS, _BASE_OUTCOMES)
        assert result == pytest.approx(_BASE_STRATEGY_BRIER, rel=1e-9)

    def test_perfect_prediction_is_zero(self):
        result = brier_score([1.0, 0.0, 1.0], [1, 0, 1])
        assert result == pytest.approx(0.0, abs=1e-15)

    def test_worst_prediction_is_one(self):
        # All predictions completely wrong
        result = brier_score([0.0, 1.0], [1, 0])
        assert result == pytest.approx(1.0, rel=1e-9)

    def test_single_element(self):
        result = brier_score([0.6], [1])
        assert result == pytest.approx(0.16, rel=1e-9)

    def test_boundary_predictions_accepted(self):
        # 0.0 and 1.0 are valid
        brier_score([0.0, 1.0], [0, 1])  # should not raise

    # --- Error cases ---

    def test_raises_on_empty_predictions(self):
        with pytest.raises(ValueError, match="empty"):
            brier_score([], [])

    def test_raises_on_length_mismatch(self):
        with pytest.raises(ValueError, match="same length"):
            brier_score([0.5, 0.5], [1])

    def test_raises_on_prediction_above_one(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            brier_score([1.1, 0.5], [1, 0])

    def test_raises_on_prediction_below_zero(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            brier_score([-0.01, 0.5], [0, 0])

    def test_raises_on_outcome_not_binary(self):
        with pytest.raises(ValueError, match=r"\{0, 1\}"):
            brier_score([0.5, 0.5], [0, 2])

    def test_raises_on_outcome_negative(self):
        with pytest.raises(ValueError, match=r"\{0, 1\}"):
            brier_score([0.5], [-1])


# ---------------------------------------------------------------------------
# evaluate_calibration — strategy beats baseline with >=30 samples
# ---------------------------------------------------------------------------

class TestEvaluateCalibrationPasses:
    def test_passes_true_with_sufficient_samples(self):
        """Replicate the 4-sample base pattern 8× → n=32 >= 30; strategy wins."""
        samples = _base_samples(n_repeat=8)  # 32 samples
        result = evaluate_calibration(samples, min_samples=30)

        assert result.n == 32
        assert result.passes is True
        assert result.improvement > 0.0
        assert result.strategy_brier < result.baseline_brier

    def test_brier_scores_match_hand_computed_pattern(self):
        """With a pure repeat of the base pattern, Brier scores equal the base values."""
        samples = _base_samples(n_repeat=8)
        result = evaluate_calibration(samples, min_samples=30)

        assert result.strategy_brier == pytest.approx(_BASE_STRATEGY_BRIER, rel=1e-9)
        assert result.baseline_brier == pytest.approx(_BASE_BASELINE_BRIER, rel=1e-9)

    def test_improvement_equals_baseline_minus_strategy(self):
        samples = _base_samples(n_repeat=8)
        result = evaluate_calibration(samples, min_samples=30)

        assert result.improvement == pytest.approx(
            result.baseline_brier - result.strategy_brier, rel=1e-12
        )

    def test_result_type(self):
        samples = _base_samples(n_repeat=8)
        result = evaluate_calibration(samples, min_samples=30)
        assert isinstance(result, CalibrationResult)

    def test_reliability_curve_returned(self):
        samples = _base_samples(n_repeat=8)
        result = evaluate_calibration(samples, min_samples=30)
        assert isinstance(result.reliability, ReliabilityCurve)

    def test_ece_is_non_negative(self):
        samples = _base_samples(n_repeat=8)
        result = evaluate_calibration(samples, min_samples=30)
        assert result.expected_calibration_error >= 0.0


# ---------------------------------------------------------------------------
# evaluate_calibration — insufficient samples
# ---------------------------------------------------------------------------

class TestEvaluateCalibrationInsufficientSamples:
    def test_passes_false_when_n_below_min(self):
        """Even if strategy_brier < baseline_brier, passes must be False when n<30."""
        # Only 4 samples — strategy clearly wins on score but n < 30
        samples = _base_samples(n_repeat=1)  # n=4
        result = evaluate_calibration(samples, min_samples=30)

        assert result.n == 4
        assert result.strategy_brier < result.baseline_brier  # strategy IS better
        assert result.passes is False  # but insufficient data → False

    def test_passes_false_with_n_equals_min_minus_one(self):
        """n = min_samples - 1 must still fail."""
        # 29 samples: 7 full repeats (28) + 1 extra
        samples = _base_samples(n_repeat=7) + [_base_samples(1)[0]]
        assert len(samples) == 29
        result = evaluate_calibration(samples, min_samples=30)
        assert result.passes is False

    def test_passes_true_at_exactly_min_samples(self):
        """n == min_samples is sufficient if strategy also wins."""
        # Build exactly 30 samples where strategy clearly beats baseline
        exact = []
        for i in range(30):
            exact.append(
                _make_sample(
                    predicted_prob=0.9,
                    market_price=0.5,
                    outcome=1,
                    market_id=f"m{i}",
                )
            )
        result = evaluate_calibration(exact, min_samples=30)
        assert result.n == 30
        assert result.passes is True

    def test_no_exception_on_empty_input(self):
        """evaluate_calibration must not raise on empty input; returns passes=False."""
        result = evaluate_calibration([], min_samples=30)
        assert result.passes is False
        assert result.n == 0


# ---------------------------------------------------------------------------
# evaluate_calibration — strategy does NOT beat baseline
# ---------------------------------------------------------------------------

class TestEvaluateCalibrationFails:
    def test_passes_false_when_strategy_worse(self):
        """If strategy_brier > baseline_brier, passes must be False."""
        # Swap roles: use market_price as predicted (baseline = perfect) and
        # degraded predictions as strategy
        samples = []
        for i in range(32):
            # baseline is perfect (0.0 for outcome 0), strategy guesses 0.5
            samples.append(
                _make_sample(
                    predicted_prob=0.5,   # strategy: random guess
                    market_price=0.0,     # baseline: near-certain
                    outcome=0,
                    market_id=f"m{i}",
                )
            )
        result = evaluate_calibration(samples, min_samples=30)

        assert result.n == 32
        assert result.strategy_brier > result.baseline_brier
        assert result.improvement < 0.0
        assert result.passes is False

    def test_passes_false_when_scores_equal(self):
        """Strategy must be STRICTLY lower than baseline; equal scores fail."""
        # Both strategy and baseline predict the same probability
        samples = []
        for i in range(32):
            samples.append(
                _make_sample(
                    predicted_prob=0.5,
                    market_price=0.5,
                    outcome=i % 2,
                    market_id=f"m{i}",
                )
            )
        result = evaluate_calibration(samples, min_samples=30)
        assert result.strategy_brier == pytest.approx(result.baseline_brier, rel=1e-12)
        assert result.passes is False


class TestSignificanceGate:
    """The pass criterion must require a STATISTICALLY SIGNIFICANT improvement (paired
    bootstrap CI excludes 0), not a raw Brier point comparison — otherwise pure noise
    passes ~21% of the time at N=30 (an adversarial-audit finding)."""

    def _noise_samples(self, n: int, seed: int) -> list[ResolvedPrediction]:
        """A ZERO-EDGE strategy: predictions are noise jittered around the base rate,
        the baseline is the honest base rate, outcomes are a fair coin. The strategy has
        no real skill, so it must NOT pass."""
        rng = random.Random(seed)
        samples = []
        for i in range(n):
            outcome = 1 if rng.random() < 0.5 else 0
            pred = min(max(0.5 + rng.uniform(-0.25, 0.25), 0.0), 1.0)
            samples.append(_make_sample(pred, market_price=0.5, outcome=outcome,
                                        market_id=f"n{i}"))
        return samples

    def test_pure_noise_rarely_passes(self):
        """Across many independent noise draws at N=30, the significance gate must keep
        the false-positive rate LOW (well under the ~21% a raw comparison produced)."""
        passes = 0
        trials = 60
        for t in range(trials):
            res = evaluate_calibration(self._noise_samples(30, seed=1000 + t),
                                       min_samples=30)
            if res.passes:
                passes += 1
        # A 95% CI gate should false-positive on the order of a few percent, not 21%.
        assert passes / trials < 0.12, f"noise passed {passes}/{trials} — gate too weak"

    def test_strong_real_edge_still_passes(self):
        """A genuine, consistent edge must still pass — the gate is not so strict it
        rejects real skill."""
        res = evaluate_calibration(_base_samples(n_repeat=12), min_samples=30)
        assert res.n == 48
        assert res.passes is True
        assert res.improvement_ci_low > 0.0

    def test_bootstrap_is_deterministic(self):
        """Same samples + same seed → identical CI and pass flag (reproducible gate)."""
        samples = _base_samples(n_repeat=10)
        a = evaluate_calibration(samples, min_samples=30, seed=777)
        b = evaluate_calibration(samples, min_samples=30, seed=777)
        assert a.improvement_ci_low == b.improvement_ci_low
        assert a.improvement_ci_high == b.improvement_ci_high
        assert a.passes == b.passes

    def test_ci_brackets_improvement(self):
        """The point improvement must lie within its own CI."""
        res = evaluate_calibration(_base_samples(n_repeat=10), min_samples=30)
        assert res.improvement_ci_low <= res.improvement <= res.improvement_ci_high


# ---------------------------------------------------------------------------
# reliability_curve — binning, empty bins, ECE
# ---------------------------------------------------------------------------

class TestReliabilityCurve:
    def test_bin_count_matches_n_bins(self):
        preds = [0.05, 0.15, 0.55, 0.95]
        outs = [0, 0, 1, 1]
        curve = reliability_curve(preds, outs, n_bins=10)
        assert len(curve.bin_mid) == 10
        assert len(curve.predicted_mean) == 10
        assert len(curve.empirical_freq) == 10
        assert len(curve.counts) == 10
        assert len(curve.bin_edges) == 11

    def test_known_inputs_land_in_expected_bins(self):
        # 0.05 → bin 0 ([0.0, 0.1))
        # 0.95 → bin 9 ([0.9, 1.0])  (right-edge included)
        preds = [0.05, 0.95]
        outs = [0, 1]
        curve = reliability_curve(preds, outs, n_bins=10)

        assert curve.counts[0] == 1
        assert curve.predicted_mean[0] == pytest.approx(0.05)
        assert curve.empirical_freq[0] == pytest.approx(0.0)

        assert curve.counts[9] == 1
        assert curve.predicted_mean[9] == pytest.approx(0.95)
        assert curve.empirical_freq[9] == pytest.approx(1.0)

    def test_right_edge_1_included_in_last_bin(self):
        """A prediction of exactly 1.0 must land in the last bin, not overflow."""
        curve = reliability_curve([1.0], [1], n_bins=10)
        assert curve.counts[9] == 1
        assert sum(curve.counts) == 1

    def test_empty_bins_are_nan_with_count_zero(self):
        # Two predictions that both land in bin 0
        preds = [0.05, 0.08]
        outs = [0, 1]
        curve = reliability_curve(preds, outs, n_bins=10)

        # All bins except bin 0 should be empty
        for i in range(1, 10):
            assert curve.counts[i] == 0
            assert math.isnan(curve.predicted_mean[i])
            assert math.isnan(curve.empirical_freq[i])

    def test_total_count_matches_input_length(self):
        preds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        outs = [0] * 10
        curve = reliability_curve(preds, outs, n_bins=10)
        assert sum(curve.counts) == 10

    def test_ece_zero_for_perfectly_calibrated(self):
        """
        Perfectly calibrated: each bin's empirical_freq matches its midpoint exactly.
        Build synthetic data so that within each bin the observed frequency equals
        the prediction.

        Bin midpoint for bin i (10 bins) ≈ (i + 0.5) / 10.
        We use predictions at exactly the midpoints and set outcomes such that
        empirical_freq == predicted_mean for every bin.

        Strategy: for each of the 10 bins, create 100 samples with prediction = midpoint
        and fraction 'midpoint' of them with outcome=1.  This gives perfect calibration.
        """
        n_bins = 10
        preds: list[float] = []
        outs: list[int] = []
        samples_per_bin = 100

        for b in range(n_bins):
            mid = (b + 0.5) / n_bins
            n_yes = round(mid * samples_per_bin)
            n_no = samples_per_bin - n_yes
            preds.extend([mid] * samples_per_bin)
            outs.extend([1] * n_yes + [0] * n_no)

        curve = reliability_curve(preds, outs, n_bins=n_bins)
        ece = expected_calibration_error(curve)
        # Allow a tiny rounding tolerance from integer rounding of n_yes
        assert ece == pytest.approx(0.0, abs=0.01)

    def test_ece_positive_for_miscalibrated(self):
        """Overconfident strategy: always predicts 0.9 but only 50% resolve YES."""
        preds = [0.9] * 100
        outs = [1] * 50 + [0] * 50
        curve = reliability_curve(preds, outs, n_bins=10)
        ece = expected_calibration_error(curve)
        assert ece > 0.0

    def test_reliability_curve_empty_input(self):
        curve = reliability_curve([], [], n_bins=10)
        assert sum(curve.counts) == 0
        for pm in curve.predicted_mean:
            assert math.isnan(pm)
        for ef in curve.empirical_freq:
            assert math.isnan(ef)

    def test_ece_empty_curve_is_zero(self):
        curve = reliability_curve([], [], n_bins=10)
        assert expected_calibration_error(curve) == 0.0
