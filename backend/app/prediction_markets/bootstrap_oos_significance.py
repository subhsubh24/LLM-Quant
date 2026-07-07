"""Bootstrap significance on the TRADEABLE out-of-sample edge (ROADMAP F11).

The B2 calibration eval (``calibration.evaluate_calibration``) already gates a
*calibration* claim behind a paired-bootstrap CI on the per-market Brier difference.
This module does the SAME for the *tradeable* claim: it puts a deterministic bootstrap
confidence interval around the realized per-trade PnL (and the hit-rate) of a
walk-forward backtest, so a positive backtest PnL is only ever called an "edge" when
the CI **excludes zero**.

Why this is necessary (the money analog of B2): a walk-forward run reports a bare point
estimate — e.g. "net +$3,330 over 108 trades". At the sample sizes we can reach
(N ~ 50–800 resolved markets), a positive total can easily be noise: a handful of
lucky longshot wins dominate the sum. A point estimate CANNOT distinguish a real edge
from a lucky draw; a CI can. F10 (``regime_slice``) already flags *concentration*
(is the PnL propped up by one bucket?); F11 is the orthogonal *significance* question
(is the PnL distinguishable from zero at all?). An honest edge must clear BOTH.

Design (mirrors ``calibration._paired_bootstrap_ci``):
- Resample the realized per-trade PnL vector WITH REPLACEMENT ``n_bootstrap`` times
  (seeded ``random.Random`` → fully reproducible, deterministic inputs → deterministic
  output). Each resample draws ``n`` trades (n = the real trade count) and we record its
  TOTAL and its MEAN. The percentile interval of the resampled totals is the CI on the
  realized total PnL over N trades; likewise for the mean and the hit-rate.
- The verdict is intentionally conservative and tri-state (plus an insufficient-N state):
  ``insufficient_data`` (n < ``min_trades``) → ``significant_positive`` (CI on total > 0)
  → ``significant_negative`` (CI on total < 0) → ``indistinguishable_from_zero``.
  Only ``significant_positive`` is a candidate edge; everything else is NOT go-live
  evidence, however large the point estimate.

This is a diagnostic on ALREADY-realized trades. It never fabricates a trade, never
changes sizing, and takes no live action — it only attaches an honesty gate to the
number a real OOS run reports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class OOSSignificance:
    """The bootstrap significance verdict on a set of realized OOS trades.

    All monetary fields are in USD. ``*_ci_low``/``*_ci_high`` are the
    (alpha/2, 1-alpha/2) percentile bounds of the seeded bootstrap distribution.
    ``verdict`` is one of: ``insufficient_data``, ``significant_positive``,
    ``significant_negative``, ``indistinguishable_from_zero``.
    """

    n_trades: int
    total_pnl_usd: float                    # the observed point estimate (payout - budget summed)
    mean_pnl_usd: Optional[float]           # observed mean per-trade PnL (None only when n == 0)
    hit_rate: Optional[float]               # observed fraction of winning trades (None only when n == 0)
    # CI bounds are None (never NaN) when not assessed (insufficient_data) — mirrors
    # regime_slice's "not assessed -> None" convention so json.dumps stays RFC-8259 valid
    # (NaN is not legal JSON and breaks jq / non-Python parsers).
    total_ci_low: Optional[float]
    total_ci_high: Optional[float]
    mean_ci_low: Optional[float]
    mean_ci_high: Optional[float]
    hit_rate_ci_low: Optional[float]
    hit_rate_ci_high: Optional[float]
    alpha: float
    n_bootstrap: int
    min_trades: int
    verdict: str
    is_significant_edge: bool     # True ONLY when verdict == "significant_positive"


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an ASCENDING-sorted sequence (q in [0,1]).

    Self-contained (mirrors ``calibration._percentile``) so this module carries no
    cross-module coupling to a private helper.
    """
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def bootstrap_oos_significance(
    pnls: Sequence[float],
    wins: Optional[Sequence[bool]] = None,
    *,
    alpha: float = 0.05,
    n_bootstrap: int = 2000,
    min_trades: int = 30,
    seed: int = 12345,
) -> OOSSignificance:
    """Bootstrap CI + tri-state verdict on realized per-trade OOS PnL and hit-rate.

    ``pnls`` is the realized per-trade PnL vector (e.g. ``[t.pnl_usd for t in
    result.trades]``). ``wins`` is the aligned per-trade win indicator (defaults to
    ``pnl > 0`` when omitted). Deterministic: same inputs + same ``seed`` → same output.

    The CI on the TOTAL resamples ``n`` trades with replacement and sums each resample,
    giving the sampling distribution of the realized total over ``n`` trades. The verdict
    is driven by the TOTAL CI (the quantity the profit floor is stated in), and is
    ``insufficient_data`` below ``min_trades`` regardless of the point estimate — a small
    sample can never be a validated edge, however green it looks.
    """
    n = len(pnls)
    if wins is None:
        wins = [p > 0.0 for p in pnls]
    if len(wins) != n:
        raise ValueError(f"pnls ({n}) and wins ({len(wins)}) must align")

    total = float(sum(pnls))
    mean = total / n if n else float("nan")
    hit = (sum(1 for w in wins if w) / n) if n else float("nan")

    if n < max(1, min_trades):
        # Not enough trades to bootstrap a meaningful CI — refuse to call it anything. CI
        # bounds (and mean/hit-rate at n==0) are None, NOT NaN: NaN is not legal JSON and
        # a downstream json.dumps of this block would emit an invalid `NaN` token that jq
        # and non-Python parsers reject. None mirrors regime_slice's "not assessed" convention.
        return OOSSignificance(
            n_trades=n, total_pnl_usd=round(total, 4),
            mean_pnl_usd=round(mean, 6) if n else None,
            hit_rate=round(hit, 6) if n else None,
            total_ci_low=None, total_ci_high=None,
            mean_ci_low=None, mean_ci_high=None,
            hit_rate_ci_low=None, hit_rate_ci_high=None,
            alpha=alpha, n_bootstrap=n_bootstrap, min_trades=min_trades,
            verdict="insufficient_data", is_significant_edge=False,
        )

    rng = random.Random(seed)
    totals: list[float] = []
    means: list[float] = []
    hits: list[float] = []
    win_ints = [1 if w else 0 for w in wins]
    for _ in range(n_bootstrap):
        s = 0.0
        w = 0
        for _ in range(n):
            idx = rng.randrange(n)
            s += pnls[idx]
            w += win_ints[idx]
        totals.append(s)
        means.append(s / n)
        hits.append(w / n)
    totals.sort()
    means.sort()
    hits.sort()

    lo_q, hi_q = alpha / 2.0, 1.0 - alpha / 2.0
    total_lo, total_hi = _percentile(totals, lo_q), _percentile(totals, hi_q)
    mean_lo, mean_hi = _percentile(means, lo_q), _percentile(means, hi_q)
    hit_lo, hit_hi = _percentile(hits, lo_q), _percentile(hits, hi_q)

    if total_lo > 0.0:
        verdict = "significant_positive"
    elif total_hi < 0.0:
        verdict = "significant_negative"
    else:
        verdict = "indistinguishable_from_zero"

    return OOSSignificance(
        n_trades=n,
        total_pnl_usd=round(total, 4),
        mean_pnl_usd=round(mean, 6),
        hit_rate=round(hit, 6),
        total_ci_low=round(total_lo, 4), total_ci_high=round(total_hi, 4),
        mean_ci_low=round(mean_lo, 6), mean_ci_high=round(mean_hi, 6),
        hit_rate_ci_low=round(hit_lo, 6), hit_rate_ci_high=round(hit_hi, 6),
        alpha=alpha, n_bootstrap=n_bootstrap, min_trades=min_trades,
        verdict=verdict, is_significant_edge=(verdict == "significant_positive"),
    )
