"""
ROADMAP B2 — Calibration Evaluation Gate.

This module evaluates whether a strategy's predicted probabilities are well-calibrated
relative to a naive baseline (the market price at entry).  It is a hard go-live DoD
item: the evaluation MUST pass before deploying live capital (ROADMAP B4).

The eval passes iff:
  - At least `min_samples` resolved predictions are available, AND
  - The strategy's Brier improvement over the baseline is **statistically significant**
    — the lower bound of a paired bootstrap confidence interval on the per-market Brier
    difference is strictly greater than zero.

WHY A SIGNIFICANCE TEST (not a raw Brier comparison)
A bare ``strategy_brier < baseline_brier`` point comparison is NOT honest as a go-live
gate: at small N the sampling noise in a Brier difference is large enough that a
ZERO-EDGE strategy beats an honest baseline a large fraction of the time (an adversarial
audit measured ~21% false positives at N=30), and a p-hacking attack — screen K
strategies, keep the one that "wins" on the eval set — then passes with near-certainty.
So ``passes`` requires the paired bootstrap CI on the improvement to EXCLUDE zero, which
collapses the noise false-positive rate and is the honest, auditable bar.

CALLER RESPONSIBILITIES (this is a pure function — it cannot enforce these)
  * ``predicted_prob`` MUST have been committed BEFORE resolution (no post-hoc fitting).
  * ``market_price`` MUST be the genuine contemporaneous entry-time crowd quote (a
    stale or rigged baseline makes the bar dishonestly easy).
  * To defend against selection/p-hacking, the strategy must be chosen on a DISJOINT
    set and evaluated here on out-of-sample resolutions; with multiple strategies
    screened, apply a multiple-comparison correction (tighten ``alpha``).

SCOPE: this measures whether the model is better CALIBRATED than the crowd — it is NOT
a measure of tradeable PnL edge (a base-rate predictor can be better calibrated than a
mispriced market yet place no profitable bet). Tradeable edge is proven by the
walk-forward backtest + realized paper PnL, not here.

Public API
----------
ResolvedPrediction   – dataclass carrying one resolved market record
brier_score          – mean squared error over a sequence of predictions/outcomes
ReliabilityCurve     – dataclass produced by reliability_curve()
reliability_curve    – bin predictions into n_bins equal-width bins, compute stats
expected_calibration_error – weighted mean |predicted_mean - empirical_freq|
CalibrationResult    – frozen dataclass holding the full evaluation result
evaluate_calibration – orchestrate the full B2 evaluation (with significance test)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedPrediction:
    """A single resolved prediction market record.

    Attributes
    ----------
    market_id:
        Unique identifier of the prediction market.
    predicted_prob:
        Strategy's P[YES] at the time of entry; must be in [0, 1].
    market_price:
        Market's implied P[YES] at entry (used as the naive baseline);
        must be in [0, 1].
    outcome:
        1 if the YES outcome was resolved True, 0 otherwise.
    """
    market_id: str
    predicted_prob: float
    market_price: float
    outcome: int


@dataclass
class ReliabilityCurve:
    """Reliability (calibration) diagram data.

    Attributes
    ----------
    bin_edges:
        Left and right edges of each bin (length = n_bins + 1).
    bin_mid:
        Midpoint of each bin (length = n_bins).
    predicted_mean:
        Mean predicted probability within each bin.  float('nan') for empty bins.
    empirical_freq:
        Fraction of outcome==1 within each bin.  float('nan') for empty bins.
    counts:
        Number of predictions in each bin.
    """
    bin_edges: list[float]
    bin_mid: list[float]
    predicted_mean: list[float]
    empirical_freq: list[float]
    counts: list[int]


@dataclass(frozen=True)
class CalibrationResult:
    """Full calibration evaluation result for ROADMAP B2.

    Attributes
    ----------
    n:
        Number of resolved predictions evaluated.
    strategy_brier:
        Brier score of the strategy's predicted probabilities.
    baseline_brier:
        Brier score of the market-price baseline.
    improvement:
        baseline_brier - strategy_brier.  Positive means strategy is better.  Equal to
        the mean of the per-market Brier differences (the bootstrap statistic).
    improvement_ci_low / improvement_ci_high:
        Lower / upper bound of the (1 - alpha) paired bootstrap CI on `improvement`.
        nan when n == 0.
    passes:
        True iff n >= min_samples AND improvement_ci_low > 0 (the improvement is
        statistically significant, not noise).
    reliability:
        Full reliability curve for the strategy predictions.
    expected_calibration_error:
        ECE of the strategy predictions (lower is better).
    """
    n: int
    strategy_brier: float
    baseline_brier: float
    improvement: float
    improvement_ci_low: float
    improvement_ci_high: float
    passes: bool
    reliability: ReliabilityCurve
    expected_calibration_error: float


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def brier_score(predictions: Sequence[float], outcomes: Sequence[int]) -> float:
    """Compute the Brier score: mean( (p - o)^2 ).

    Parameters
    ----------
    predictions:
        Sequence of predicted probabilities, each in [0, 1].
    outcomes:
        Sequence of binary outcomes (0 or 1), same length as predictions.

    Returns
    -------
    float
        The mean squared error between predictions and outcomes.

    Raises
    ------
    ValueError
        If the sequences are empty, have different lengths, any prediction is
        outside [0, 1], or any outcome is not 0 or 1.
    """
    preds = list(predictions)
    outs = list(outcomes)

    if len(preds) == 0:
        raise ValueError("predictions must not be empty")
    if len(preds) != len(outs):
        raise ValueError(
            f"predictions and outcomes must have the same length "
            f"(got {len(preds)} vs {len(outs)})"
        )

    total = 0.0
    for i, (p, o) in enumerate(zip(preds, outs)):
        if not (0.0 <= p <= 1.0):
            raise ValueError(
                f"predictions[{i}] = {p!r} is outside [0, 1]"
            )
        if o not in (0, 1):
            raise ValueError(
                f"outcomes[{i}] = {o!r} is not in {{0, 1}}"
            )
        total += (p - o) ** 2

    return total / len(preds)


# ---------------------------------------------------------------------------
# Reliability curve
# ---------------------------------------------------------------------------

def reliability_curve(
    predictions: Sequence[float],
    outcomes: Sequence[int],
    n_bins: int = 10,
) -> ReliabilityCurve:
    """Build a reliability (calibration) diagram.

    Bins predictions into `n_bins` equal-width bins over [0, 1].  For each
    bin the mean predicted probability, empirical frequency of outcome==1, and
    count are computed.  Empty bins get float('nan') for the mean and frequency,
    and count 0.  The rightmost bin includes the right edge 1.0.

    Parameters
    ----------
    predictions:
        Sequence of predicted probabilities in [0, 1].
    outcomes:
        Sequence of binary outcomes (0 or 1).
    n_bins:
        Number of equal-width bins.

    Returns
    -------
    ReliabilityCurve
    """
    preds = list(predictions)
    outs = list(outcomes)

    # Build bin edges: [0, 1/n, 2/n, ..., 1]
    edges = [i / n_bins for i in range(n_bins + 1)]
    midpoints = [(edges[i] + edges[i + 1]) / 2.0 for i in range(n_bins)]

    # Accumulate per-bin statistics
    bin_pred_sum = [0.0] * n_bins
    bin_out_sum = [0] * n_bins
    bin_count = [0] * n_bins

    for p, o in zip(preds, outs):
        # Determine bin index; the last bin includes the right edge 1.0
        idx = int(p * n_bins)
        if idx >= n_bins:
            idx = n_bins - 1
        bin_pred_sum[idx] += p
        bin_out_sum[idx] += o
        bin_count[idx] += 1

    predicted_mean: list[float] = []
    empirical_freq: list[float] = []

    for i in range(n_bins):
        c = bin_count[i]
        if c == 0:
            predicted_mean.append(float("nan"))
            empirical_freq.append(float("nan"))
        else:
            predicted_mean.append(bin_pred_sum[i] / c)
            empirical_freq.append(bin_out_sum[i] / c)

    return ReliabilityCurve(
        bin_edges=edges,
        bin_mid=midpoints,
        predicted_mean=predicted_mean,
        empirical_freq=empirical_freq,
        counts=bin_count,
    )


def expected_calibration_error(curve: ReliabilityCurve) -> float:
    """Compute the Expected Calibration Error (ECE) from a ReliabilityCurve.

    ECE = sum over non-empty bins of (count / total) * |predicted_mean - empirical_freq|

    Parameters
    ----------
    curve:
        A ReliabilityCurve produced by reliability_curve().

    Returns
    -------
    float
        The ECE value (lower is better; 0.0 means perfect calibration).
    """
    total = sum(curve.counts)
    if total == 0:
        return 0.0

    ece = 0.0
    for i, c in enumerate(curve.counts):
        if c == 0:
            continue
        ece += (c / total) * abs(curve.predicted_mean[i] - curve.empirical_freq[i])
    return ece


# ---------------------------------------------------------------------------
# Top-level evaluation
# ---------------------------------------------------------------------------

def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list. q in [0, 1]."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _paired_bootstrap_ci(
    diffs: Sequence[float], alpha: float, n_bootstrap: int, seed: int
) -> tuple[float, float]:
    """Deterministic paired bootstrap CI on the mean of per-market Brier differences.

    ``diffs[i] = baseline_se_i - strategy_se_i`` (positive = strategy better on market i).
    Resamples the paired differences with replacement ``n_bootstrap`` times (seeded RNG,
    so the result is fully reproducible) and returns the (alpha/2, 1-alpha/2) percentile
    interval of the resampled means. The pairing matters because both predictors score
    the SAME outcomes — a paired test removes the shared market-difficulty variance.
    """
    n = len(diffs)
    if n == 0:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_bootstrap):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return (_percentile(means, alpha / 2.0), _percentile(means, 1.0 - alpha / 2.0))


def evaluate_calibration(
    samples: Sequence[ResolvedPrediction],
    n_bins: int = 10,
    min_samples: int = 30,
    alpha: float = 0.05,
    n_bootstrap: int = 2000,
    seed: int = 12345,
) -> CalibrationResult:
    """Run the full ROADMAP B2 calibration evaluation with a significance test.

    Computes Brier scores for the strategy predictions and the market-price baseline,
    builds a reliability curve, and runs a paired bootstrap on the per-market Brier
    differences to decide — honestly — whether the improvement is real or noise.

    The evaluation passes iff:
      - n >= min_samples  (insufficient data → passes=False, no exception raised), AND
      - the lower bound of the (1 - alpha) paired bootstrap CI on the improvement is
        strictly > 0 (the strategy beats the baseline by a statistically significant
        margin, not by sampling luck).

    Parameters
    ----------
    samples:
        Sequence of ResolvedPrediction records covering the same resolved markets.
    n_bins:
        Number of equal-width bins for the reliability curve.
    min_samples:
        Minimum number of resolved predictions required to even be eligible to pass.
    alpha:
        Significance level for the bootstrap CI (default 0.05 → 95% CI). Tighten this
        when screening multiple strategies (multiple-comparison correction).
    n_bootstrap:
        Number of bootstrap resamples (deterministic given ``seed``).
    seed:
        RNG seed for the bootstrap — makes ``passes`` and the CI fully reproducible.

    Returns
    -------
    CalibrationResult
        Full evaluation result including Brier scores, improvement, the CI, pass flag,
        reliability curve, and ECE.
    """
    sample_list = list(samples)
    n = len(sample_list)

    strategy_preds = [s.predicted_prob for s in sample_list]
    baseline_preds = [s.market_price for s in sample_list]
    outcomes = [s.outcome for s in sample_list]

    # Handle empty input gracefully
    if n == 0:
        empty_curve = reliability_curve([], [], n_bins=n_bins)
        return CalibrationResult(
            n=0,
            strategy_brier=float("nan"),
            baseline_brier=float("nan"),
            improvement=float("nan"),
            improvement_ci_low=float("nan"),
            improvement_ci_high=float("nan"),
            passes=False,
            reliability=empty_curve,
            expected_calibration_error=0.0,
        )

    strategy_brier = brier_score(strategy_preds, outcomes)
    baseline_brier = brier_score(baseline_preds, outcomes)
    improvement = baseline_brier - strategy_brier

    # Per-market Brier differences (positive = strategy better on that market).
    diffs = [
        (b - o) ** 2 - (s - o) ** 2
        for s, b, o in zip(strategy_preds, baseline_preds, outcomes)
    ]
    ci_low, ci_high = _paired_bootstrap_ci(diffs, alpha, n_bootstrap, seed)

    curve = reliability_curve(strategy_preds, outcomes, n_bins=n_bins)
    ece = expected_calibration_error(curve)

    # Sufficient data AND a statistically-significant improvement (CI excludes 0).
    passes = (n >= min_samples) and (ci_low > 0.0)

    return CalibrationResult(
        n=n,
        strategy_brier=strategy_brier,
        baseline_brier=baseline_brier,
        improvement=improvement,
        improvement_ci_low=ci_low,
        improvement_ci_high=ci_high,
        passes=passes,
        reliability=curve,
        expected_calibration_error=ece,
    )
