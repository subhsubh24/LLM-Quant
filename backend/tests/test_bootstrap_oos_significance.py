"""Deterministic tests for the F11 tradeable-edge bootstrap significance gate."""

import math

from backend.app.prediction_markets.bootstrap_oos_significance import (
    OOSSignificance,
    bootstrap_oos_significance,
)


def _big(pnls):
    """Replicate a small pattern up to a >= min_trades sample without changing its mean."""
    return (pnls * 10)[:60] if len(pnls) * 10 >= 60 else pnls * 10


def test_insufficient_data_below_min_trades():
    r = bootstrap_oos_significance([5.0, -3.0, 4.0], min_trades=30)
    assert r.verdict == "insufficient_data"
    assert r.is_significant_edge is False
    assert r.n_trades == 3
    # point estimate is still reported honestly, CI is NaN (not fabricated)
    assert r.total_pnl_usd == 6.0
    assert math.isnan(r.total_ci_low) and math.isnan(r.total_ci_high)


def test_clear_positive_edge_is_significant():
    # Every trade wins a steady amount → the total CI cannot include 0.
    pnls = [2.0] * 50
    r = bootstrap_oos_significance(pnls, seed=1)
    assert r.verdict == "significant_positive"
    assert r.is_significant_edge is True
    assert r.total_ci_low > 0.0
    assert r.hit_rate == 1.0


def test_clear_negative_edge_is_significant_negative():
    pnls = [-2.0] * 50
    r = bootstrap_oos_significance(pnls, seed=1)
    assert r.verdict == "significant_negative"
    assert r.is_significant_edge is False
    assert r.total_ci_high < 0.0


def test_lucky_longshot_positive_total_is_noise():
    # A positive POINT total driven by a few big longshot wins amid many small losses:
    # 46 losses of -1 and 4 wins of +20 -> total = +34, but a real edge?  The bootstrap
    # total CI straddles 0 -> NOT a significant edge (the F11 point: a green sum is not proof).
    pnls = [-1.0] * 46 + [20.0] * 4
    r = bootstrap_oos_significance(pnls, seed=7)
    assert r.total_pnl_usd == 34.0            # the point estimate IS positive
    assert r.verdict == "indistinguishable_from_zero"
    assert r.is_significant_edge is False
    assert r.total_ci_low < 0.0 < r.total_ci_high


def test_determinism_same_seed_same_output():
    pnls = [1.0, -2.0, 3.0, -0.5, 4.0] * 12
    a = bootstrap_oos_significance(pnls, seed=99)
    b = bootstrap_oos_significance(pnls, seed=99)
    assert a == b
    assert isinstance(a, OOSSignificance)


def test_different_seed_changes_resample_but_not_point_estimate():
    pnls = [1.0, -2.0, 3.0, -0.5, 4.0] * 12
    a = bootstrap_oos_significance(pnls, seed=1)
    b = bootstrap_oos_significance(pnls, seed=2)
    assert a.total_pnl_usd == b.total_pnl_usd     # observed total is seed-independent
    assert a.hit_rate == b.hit_rate
    # the CI is a resample of the same data; with a moderate sample the bounds are close but
    # the underlying resample draws differ — at least one CI endpoint should move.
    assert (a.total_ci_low, a.total_ci_high) != (b.total_ci_low, b.total_ci_high)


def test_explicit_wins_override_pnl_sign():
    # A trade can realize +PnL yet be recorded a loss-by-rule (or vice-versa); the caller may
    # pass an explicit win vector. Hit-rate must follow `wins`, not the PnL sign.
    pnls = [1.0] * 40
    wins = [False] * 40
    r = bootstrap_oos_significance(pnls, wins=wins, seed=3)
    assert r.hit_rate == 0.0
    assert r.verdict == "significant_positive"   # PnL is still all +1


def test_misaligned_wins_raises():
    try:
        bootstrap_oos_significance([1.0, 2.0], wins=[True])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on misaligned pnls/wins")


def test_ci_brackets_the_mean():
    pnls = [3.0, -1.0, 2.0, -2.0, 5.0, -3.0] * 10
    r = bootstrap_oos_significance(pnls, seed=42)
    assert r.mean_ci_low <= r.mean_pnl_usd <= r.mean_ci_high
    assert r.total_ci_low <= r.total_pnl_usd <= r.total_ci_high
