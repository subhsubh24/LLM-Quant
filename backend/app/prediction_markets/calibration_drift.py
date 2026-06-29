"""
ROADMAP E2 — Calibration Drift / Regime Detection (pure, offline engine)
=======================================================================

This module is the deterministic DECISION ENGINE for ROADMAP E2 (drift / regime
detection feeding strategy retirement).  Given an established calibration
*baseline* and a *recent* window of resolved predictions, it decides — honestly —
whether the strategy's calibration has **significantly degraded**, and emits a
conservative Kelly-size de-rating multiplier the sizing layer can apply.

WHAT THIS MODULE DOES *NOT* DO
------------------------------
* It does NOT auto-retire a strategy.  Retirement is a human / strategy-registry
  decision (ROADMAP E4); this module only DECIDES a signal that wiring will read.
* It is NOT wired into the orchestrator by this change.  It is the tested,
  deterministic engine the future wiring will call.
* It does NOT touch the database, the network, ``datetime.now()``, or any global
  RNG state.  Everything is a pure function of its inputs (a bootstrap, when used,
  is driven by a FIXED caller-or-module seed).

WHY A SIGNIFICANCE TEST (not a raw Brier comparison)
----------------------------------------------------
A bare ``recent_brier > baseline_brier`` point comparison is NOT an honest drift
signal: at small N the sampling noise in a Brier difference is large enough that
calibration drawn from the SAME distribution as the baseline "degrades" a large
fraction of the time (the prior B2 audit measured ~21% false positives at N≈30 on
a raw comparison).  So ``drift_detected`` here requires the degradation to be
**statistically significant** — the lower bound of a deterministic, seeded
two-sample bootstrap CI on ``recent_brier - baseline_brier`` must exclude zero —
AND the effect to be materially large.  Significance gates noise; effect size
gates triviality.

"INSUFFICIENT DATA" BEATS A FALSE ALARM (ROADMAP E7 discipline)
---------------------------------------------------------------
If the recent window is below ``min_recent`` resolved predictions we refuse to
react: ``drift_detected=False``, ``severity=NONE``, ``de_rating=1.0`` and an
explicit ``insufficient_data=True``.  We never flag drift on a noisy handful of
trades.  This is the significance-weighted-learning rule (E7): prefer "we don't
know yet" over over-reacting to a single noisy week.

Public API
----------
DriftSeverity        – enum-like string constants NONE / LOW / HIGH
CalibrationBaseline  – frozen baseline calibration (Brier + N + outcome rate)
build_baseline       – construct a CalibrationBaseline from resolved predictions
DriftResult          – frozen full drift decision (drift flag, severity, CIs, …)
detect_drift         – the E2 detector (deterministic, significance-gated)
confidence_de_rating – Kelly-size multiplier in [0, 1] (monotone, never > 1.0)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from .calibration import brier_score

__all__ = [
    "DriftSeverity",
    "CalibrationBaseline",
    "build_baseline",
    "DriftResult",
    "detect_drift",
    "confidence_de_rating",
]


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class DriftSeverity:
    """String severity constants (kept as plain str for trivial JSON/round-trip).

    Ordered worst-last in ``ORDER`` so callers can compare severity rank.
    """

    NONE = "none"
    LOW = "low"
    HIGH = "high"

    ORDER = ("none", "low", "high")

    @classmethod
    def rank(cls, severity: str) -> int:
        """Integer rank of a severity (NONE=0, LOW=1, HIGH=2)."""
        return cls.ORDER.index(severity)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalibrationBaseline:
    """An established baseline calibration computed from resolved predictions.

    This is the reference the recent window is judged against.  It is a frozen,
    immutable snapshot — typically the strategy's calibration over a long,
    in-control history.

    Attributes
    ----------
    brier:
        Baseline Brier score (mean squared error of predicted_prob vs outcome).
        Lower is better-calibrated.
    n:
        Number of resolved predictions the baseline was computed from.
    outcome_rate:
        Empirical base rate (fraction of outcome==1) in the baseline set.
        Carried for diagnostics / regime comparison; not used in the test.
    """

    brier: float
    n: int
    outcome_rate: float


def build_baseline(
    predicted_probs: Sequence[float],
    outcomes: Sequence[int],
) -> CalibrationBaseline:
    """Construct a :class:`CalibrationBaseline` from resolved predictions.

    Parameters
    ----------
    predicted_probs:
        Sequence of predicted probabilities, each in [0, 1].
    outcomes:
        Sequence of binary outcomes (0 or 1), same length as predicted_probs.

    Returns
    -------
    CalibrationBaseline

    Raises
    ------
    ValueError
        Propagated from :func:`brier_score` for empty / mismatched / out-of-range
        inputs.
    """
    preds = list(predicted_probs)
    outs = list(outcomes)
    brier = brier_score(preds, outs)  # validates ranges / lengths / non-empty
    outcome_rate = sum(outs) / len(outs)
    return CalibrationBaseline(brier=brier, n=len(preds), outcome_rate=outcome_rate)


# ---------------------------------------------------------------------------
# Drift result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriftResult:
    """Full, immutable drift decision for a recent window vs a baseline.

    Attributes
    ----------
    drift_detected:
        True iff calibration degradation is BOTH statistically significant
        (the bootstrap CI lower bound on ``recent_brier - baseline_brier``
        excludes zero) AND materially large (effect ≥ ``low_threshold``).
        Always False when ``insufficient_data`` is True.
    severity:
        One of DriftSeverity.NONE / LOW / HIGH (see thresholds in
        :func:`detect_drift`).
    insufficient_data:
        True iff the recent window had fewer than ``min_recent`` predictions.
        In that case drift is never flagged (E7 discipline).
    baseline_brier / recent_brier:
        The two Brier scores compared.  ``recent_brier`` is nan when the recent
        window is empty.
    brier_delta:
        ``recent_brier - baseline_brier`` (positive = degradation).  nan when
        recent window is empty.
    ci_low / ci_high:
        Bootstrap CI bounds on ``brier_delta`` at level (1 - alpha).  nan when
        insufficient data (the bootstrap is not run).
    p_value:
        Deterministic bootstrap p-value for the one-sided hypothesis
        "recent is no worse than baseline" (fraction of bootstrap deltas <= 0).
        Small p_value → significant degradation.  nan when insufficient data.
    de_rating:
        Kelly-size multiplier in [0, 1] (1.0 = full size, lower under drift).
        Computed by :func:`confidence_de_rating`; stored here for convenience.
    recent_n:
        Number of resolved predictions in the recent window.
    effect_size:
        Relative degradation ``brier_delta / baseline_brier`` (the dimensionless
        magnitude the severity thresholds compare against).  0.0 when delta <= 0;
        nan when recent window is empty.
    seed:
        The bootstrap seed used (echoed for reproducibility / auditing).
    meta:
        Immutable map of the thresholds / config used, for auditability.
    """

    drift_detected: bool
    severity: str
    insufficient_data: bool
    baseline_brier: float
    recent_brier: float
    brier_delta: float
    ci_low: float
    ci_high: float
    p_value: float
    de_rating: float
    recent_n: int
    effect_size: float
    seed: int
    meta: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    def to_dict(self) -> dict:
        """Deterministic, JSON-friendly dict of the result.

        Identical inputs → byte-identical dict on every call (the contained map
        is materialised into a plain ``dict`` in a fixed key order).
        """
        return {
            "drift_detected": self.drift_detected,
            "severity": self.severity,
            "insufficient_data": self.insufficient_data,
            "baseline_brier": self.baseline_brier,
            "recent_brier": self.recent_brier,
            "brier_delta": self.brier_delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "p_value": self.p_value,
            "de_rating": self.de_rating,
            "recent_n": self.recent_n,
            "effect_size": self.effect_size,
            "seed": self.seed,
            "meta": {k: self.meta[k] for k in sorted(self.meta)},
        }


# ---------------------------------------------------------------------------
# Deterministic bootstrap helpers
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


def _bootstrap_delta(
    base_sq_err: Sequence[float],
    recent_sq_err: Sequence[float],
    baseline_brier: float,
    alpha: float,
    n_bootstrap: int,
    seed: int,
) -> tuple[float, float, float]:
    """Deterministic two-sample bootstrap on ``recent_brier - baseline_brier``.

    Because the baseline and recent windows score DIFFERENT markets, this is an
    *independent* (not paired) two-sample bootstrap: each iteration resamples the
    recent per-prediction squared errors with replacement and (if the baseline's
    raw per-prediction squared errors are available) the baseline ones too,
    forming a bootstrap delta of the two means.  The seeded RNG makes the whole
    procedure bit-for-bit reproducible.

    Returns ``(ci_low, ci_high, p_value)`` where p_value is the one-sided
    bootstrap mass at delta <= 0 (i.e. "recent is no worse than baseline").
    """
    rng = random.Random(seed)
    n_recent = len(recent_sq_err)
    n_base = len(base_sq_err)

    deltas: list[float] = []
    for _ in range(n_bootstrap):
        # Resample recent window.
        r_total = 0.0
        for _ in range(n_recent):
            r_total += recent_sq_err[rng.randrange(n_recent)]
        r_mean = r_total / n_recent

        if n_base > 0:
            b_total = 0.0
            for _ in range(n_base):
                b_total += base_sq_err[rng.randrange(n_base)]
            b_mean = b_total / n_base
        else:
            # No raw baseline errors retained: treat baseline as a fixed point
            # estimate (still honest — the recent resampling carries the noise).
            b_mean = baseline_brier

        deltas.append(r_mean - b_mean)

    deltas.sort()
    ci_low = _percentile(deltas, alpha / 2.0)
    ci_high = _percentile(deltas, 1.0 - alpha / 2.0)
    # One-sided p-value: fraction of bootstrap deltas <= 0.
    n_le_zero = sum(1 for d in deltas if d <= 0.0)
    p_value = n_le_zero / len(deltas)
    return ci_low, ci_high, p_value


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

def detect_drift(
    baseline: CalibrationBaseline,
    recent_probs: Sequence[float],
    recent_outcomes: Sequence[int],
    *,
    baseline_probs: Sequence[float] | None = None,
    baseline_outcomes: Sequence[int] | None = None,
    min_recent: int = 30,
    alpha: float = 0.05,
    low_threshold: float = 0.15,
    high_threshold: float = 0.40,
    n_bootstrap: int = 2000,
    seed: int = 12345,
    max_de_rating_cut: float = 0.75,
) -> DriftResult:
    """ROADMAP E2 calibration-drift detector (deterministic, significance-gated).

    Decides whether the *recent* window's calibration has SIGNIFICANTLY and
    MATERIALLY degraded versus ``baseline``.

    Decision rule
    -------------
    1. INSUFFICIENT DATA (E7): if ``len(recent_probs) < min_recent`` →
       ``insufficient_data=True``, ``drift_detected=False``,
       ``severity=NONE``, ``de_rating=1.0``.  We never flag drift on a tiny
       window — preferring "we don't know yet" over a false alarm.
    2. Otherwise compute ``recent_brier`` and
       ``brier_delta = recent_brier - baseline.brier`` and the relative
       ``effect_size = max(0, brier_delta) / baseline.brier``.
    3. Run a deterministic, seeded bootstrap CI on ``brier_delta``.  The
       degradation is **significant** iff the CI lower bound is strictly > 0
       (the recent window is worse than baseline by more than sampling noise).
    4. ``drift_detected`` iff degradation is BOTH significant AND
       ``effect_size >= low_threshold``.
    5. Severity:
         * NONE  — not detected.
         * HIGH  — detected AND ``effect_size >= high_threshold``.
         * LOW   — detected otherwise.

    Both significance AND effect size are required so a microscopically-but-
    significantly-worse window (large recent N, trivial real change) does not
    trip retirement, and a large-but-noisy point spike (small N) does not either.

    Parameters
    ----------
    baseline:
        Established :class:`CalibrationBaseline`.
    recent_probs, recent_outcomes:
        The recent resolved-prediction window to test.
    baseline_probs, baseline_outcomes:
        OPTIONAL raw baseline per-prediction data.  When supplied, the bootstrap
        resamples the baseline too (a genuine two-sample test).  When omitted the
        baseline is treated as a fixed point estimate (still honest; the recent
        resampling carries the sampling noise).
    min_recent:
        Minimum recent window size to even consider drift (E7 floor).
    alpha:
        Two-sided significance level for the bootstrap CI (default 0.05 → 95% CI).
    low_threshold, high_threshold:
        Relative-degradation effect-size cutoffs for LOW / HIGH severity.
    n_bootstrap:
        Bootstrap resamples (deterministic given ``seed``).
    seed:
        Fixed RNG seed — makes the entire result reproducible.
    max_de_rating_cut:
        Maximum fraction the de-rating may cut sizing by (so de_rating floors at
        ``1 - max_de_rating_cut``).  See :func:`confidence_de_rating`.

    Returns
    -------
    DriftResult
        Fully populated, frozen, deterministic.
    """
    meta = MappingProxyType({
        "min_recent": float(min_recent),
        "alpha": float(alpha),
        "low_threshold": float(low_threshold),
        "high_threshold": float(high_threshold),
        "n_bootstrap": float(n_bootstrap),
        "max_de_rating_cut": float(max_de_rating_cut),
    })

    recent_p = list(recent_probs)
    recent_o = list(recent_outcomes)
    recent_n = len(recent_p)

    # --- Path 1: insufficient data (E7) — never flag drift. ----------------
    if recent_n < min_recent:
        recent_brier_insuff = brier_score(recent_p, recent_o) if recent_n > 0 else float("nan")
        return DriftResult(
            drift_detected=False,
            severity=DriftSeverity.NONE,
            insufficient_data=True,
            baseline_brier=baseline.brier,
            recent_brier=recent_brier_insuff,
            brier_delta=float("nan") if recent_n == 0 else (recent_brier_insuff - baseline.brier),
            ci_low=float("nan"),
            ci_high=float("nan"),
            p_value=float("nan"),
            de_rating=1.0,
            recent_n=recent_n,
            effect_size=float("nan"),
            seed=seed,
            meta=meta,
        )

    # --- Path 2: sufficient data — measure + significance-test. ------------
    recent_brier = brier_score(recent_p, recent_o)  # validates inputs
    brier_delta = recent_brier - baseline.brier
    # Relative degradation; only positive deltas count as degradation.
    if baseline.brier > 0.0:
        effect_size = max(0.0, brier_delta) / baseline.brier
    else:
        # Degenerate perfect baseline: any positive delta is infinite-relative;
        # treat any positive delta as a full-strength effect.
        effect_size = 0.0 if brier_delta <= 0.0 else 1.0

    recent_sq_err = [(p - o) ** 2 for p, o in zip(recent_p, recent_o)]
    if baseline_probs is not None and baseline_outcomes is not None:
        bp = list(baseline_probs)
        bo = list(baseline_outcomes)
        base_sq_err = [(p - o) ** 2 for p, o in zip(bp, bo)]
    else:
        base_sq_err = []

    ci_low, ci_high, p_value = _bootstrap_delta(
        base_sq_err=base_sq_err,
        recent_sq_err=recent_sq_err,
        baseline_brier=baseline.brier,
        alpha=alpha,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )

    # Significant degradation iff CI lower bound excludes zero on the worse side.
    significant = ci_low > 0.0
    material = effect_size >= low_threshold
    drift_detected = bool(significant and material)

    if not drift_detected:
        severity = DriftSeverity.NONE
    elif effect_size >= high_threshold:
        severity = DriftSeverity.HIGH
    else:
        severity = DriftSeverity.LOW

    # Build a provisional result so de_rating can be computed from it.
    provisional = DriftResult(
        drift_detected=drift_detected,
        severity=severity,
        insufficient_data=False,
        baseline_brier=baseline.brier,
        recent_brier=recent_brier,
        brier_delta=brier_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        de_rating=1.0,  # placeholder, replaced below
        recent_n=recent_n,
        effect_size=effect_size,
        seed=seed,
        meta=meta,
    )
    de_rating = confidence_de_rating(provisional, max_cut=max_de_rating_cut)

    return DriftResult(
        drift_detected=drift_detected,
        severity=severity,
        insufficient_data=False,
        baseline_brier=baseline.brier,
        recent_brier=recent_brier,
        brier_delta=brier_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        de_rating=de_rating,
        recent_n=recent_n,
        effect_size=effect_size,
        seed=seed,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Kelly-size de-rating
# ---------------------------------------------------------------------------

def confidence_de_rating(
    result: DriftResult,
    *,
    max_cut: float = 0.75,
    high_effect_ref: float = 0.80,
) -> float:
    """Kelly-size multiplier in [0, 1] that REDUCES sizing under drift.

    Properties (auditable, hammered by tests)
    ------------------------------------------
    * Bounded: always in ``[1 - max_cut, 1.0]`` ⊆ [0, 1].  NEVER > 1.0.
    * No drift (or insufficient data): returns exactly 1.0 (full size).
    * Conservative + monotone: a LARGER ``effect_size`` (worse calibration
      degradation) yields a multiplier that is ≤ the multiplier for any smaller
      effect — worse drift never sizes UP.

    The multiplier scales the cut linearly with the relative degradation
    ``effect_size``, saturating the full ``max_cut`` at ``high_effect_ref``
    relative degradation:

        de_rating = 1 - max_cut * min(1, effect_size / high_effect_ref)

    Parameters
    ----------
    result:
        A :class:`DriftResult`.  When ``not result.drift_detected`` (which
        includes the insufficient-data path) the multiplier is exactly 1.0.
    max_cut:
        Maximum fraction sizing may be cut by (in [0, 1]).  The de-rating floors
        at ``1 - max_cut``.
    high_effect_ref:
        Relative-degradation value at which the cut saturates to ``max_cut``.

    Returns
    -------
    float
        Multiplier in ``[1 - max_cut, 1.0]``.
    """
    if not (0.0 <= max_cut <= 1.0):
        raise ValueError(f"max_cut must be in [0, 1] (got {max_cut})")
    if high_effect_ref <= 0.0:
        raise ValueError(f"high_effect_ref must be > 0 (got {high_effect_ref})")

    # No drift / insufficient data → full size, exactly 1.0.
    if not result.drift_detected:
        return 1.0

    effect = result.effect_size
    # Guard against nan (cannot happen on the drift_detected path, but be safe).
    if effect != effect:  # nan check
        return 1.0

    frac = min(1.0, max(0.0, effect) / high_effect_ref)
    de_rating = 1.0 - max_cut * frac
    # Clamp to [1 - max_cut, 1.0] defensively.
    lo = 1.0 - max_cut
    if de_rating < lo:
        de_rating = lo
    if de_rating > 1.0:
        de_rating = 1.0
    return de_rating
