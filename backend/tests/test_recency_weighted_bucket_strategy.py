"""Tests for recency_weighted_bucket_strategy — the pre-registered B4a-revised alpha.

These prove:
  * the HONESTY contract (abstain on under-sampled buckets, raise on no data, never
    fabricate a rate, never signal without a fitted model);
  * the MECHANISM — recency-weighting tracks a TIME-VARYING true rate better than an
    all-time (EXP-002-style) average, which is the diagnosed reason EXP-002 was refuted;
  * LEAKAGE-safety + DETERMINISM inside walk_forward;
  * that it recovers a known injected (stationary) OOS edge and trades ~nothing on a
    well-calibrated stationary crowd (no fabricated edge).
All synthetic + offline — no network. Whether recency-weighting beats the crowd on REAL
data is an empirical question answered ONLY by a real OOS run (see the module docstring).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets.calibration_bucket_strategy import CalibrationBucketModel
from app.prediction_markets.polymarket_client import Market, Outcome
from app.prediction_markets.recency_weighted_bucket_strategy import (
    RecencyBucketStat,
    RecencyWeightedBucketModel,
    RecencyWeightedBucketStrategy,
    default_bucket_edges,
    fit_recency_model_from_history,
    make_recency_weighted_bucket_strategy,
)
from app.prediction_markets.strategies import StrategyConfig
from app.prediction_markets.walk_forward import (
    HistoricalMarket,
    MarketView,
    walk_forward_backtest,
)

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _hm(mid: str, day: float, price: float, outcome: int, hold_days: float = 2.0) -> HistoricalMarket:
    """A HistoricalMarket resolving at BASE+day (decision hold_days earlier)."""
    resolve = BASE + timedelta(days=day)
    return HistoricalMarket(
        market_id=mid,
        decision_time=resolve - timedelta(days=hold_days),
        resolution_time=resolve,
        market_price=price,
        model_prob=price,  # seeded to crowd; the STRATEGY overrides it with the bucket rate
        outcome=outcome,
    )


def _batch(prefix: str, resolve_day: float, price: float, yes_rate: float, n: int,
           spread: float = 0.01):
    """n markets at ``price`` resolving near ``resolve_day`` (each ``spread`` days apart);
    EXACTLY round(yes_rate*n) resolve YES, spread evenly (Bresenham) so wins aren't
    clustered. ``spread=0.0`` makes every market the SAME age (perfectly uniform weights)."""
    n_yes = round(yes_rate * n)
    out = []
    for i in range(n):
        outcome = 1 if ((i + 1) * n_yes) // n != (i * n_yes) // n else 0
        out.append(_hm(f"{prefix}_{i}", resolve_day + i * spread, price, outcome))
    return out


# ---------------------------------------------------------------------------
# Model: fit / predict / abstain / raise
# ---------------------------------------------------------------------------
def test_uniform_recency_equals_unweighted_rate():
    """When every training market is the same age, recency weights are uniform and the
    weighted rate equals the plain empirical rate; effective_n equals the count."""
    train = _batch("t", 10.0, 0.65, 0.85, 40, spread=0.0)   # all resolve at the SAME instant
    as_of = BASE + timedelta(days=12)
    model = RecencyWeightedBucketModel(min_effective_n=20).fit(train, as_of)
    st = [s for s in model.stats if s.lo == 0.6][0]
    assert st.yes_rate == pytest.approx(0.85, abs=1e-9)   # round(0.85*40)=34/40
    assert st.effective_n == pytest.approx(40.0, rel=1e-6)  # uniform weights → eff_n == n
    assert model.predict(0.65) == pytest.approx(0.85, abs=1e-9)


def test_recency_tracks_time_varying_rate_better_than_static():
    """THE mechanism test. A bucket whose true YES-rate DRIFTED from 10% (old) to 60%
    (recent). The recency-weighted rate lands near the RECENT truth (0.60); the all-time
    EXP-002 average lags near the diluted blend (~0.27). This is the exact failure mode
    that refuted EXP-002 (a lagging average vs a time-varying rate)."""
    old = _batch("old", 15.0, 0.30, 0.10, 80)     # resolved ~day 15, 10% YES
    recent = _batch("rec", 305.0, 0.30, 0.60, 40)  # resolved ~day 305, 60% YES
    train = old + recent
    as_of = BASE + timedelta(days=315)

    recency = RecencyWeightedBucketModel(half_life_days=60.0, min_effective_n=30).fit(
        train, as_of
    )
    r = recency.predict(0.30)
    assert r is not None
    # Recency-weighted rate is pulled toward the RECENT 60%, far from the static blend.
    assert 0.50 < r < 0.62

    # The all-time (EXP-002) average of the SAME corpus lags near (8+24)/120 = 0.267.
    static = CalibrationBucketModel(min_bucket_n=30).fit(train)
    s = static.predict(0.30)
    assert s == pytest.approx((8 + 24) / 120.0, abs=0.02)

    # Recency is materially closer to the recent truth than the static average.
    assert abs(r - 0.60) < abs(s - 0.60)


def test_shorter_half_life_weights_recent_more():
    """Monotonicity: a SHORTER half-life discounts old data faster, so the predicted rate
    moves CLOSER to the recent-era rate."""
    old = _batch("old", 15.0, 0.30, 0.10, 80)
    recent = _batch("rec", 305.0, 0.30, 0.60, 40)
    train = old + recent
    as_of = BASE + timedelta(days=315)
    fast = RecencyWeightedBucketModel(half_life_days=15.0, min_effective_n=20).fit(train, as_of).predict(0.30)
    slow = RecencyWeightedBucketModel(half_life_days=180.0, min_effective_n=20).fit(train, as_of).predict(0.30)
    assert fast is not None and slow is not None
    # Faster decay → closer to the recent 0.60 (higher), slower decay → nearer the blend.
    assert fast > slow
    assert abs(fast - 0.60) < abs(slow - 0.60)


def test_effective_n_floor_abstains_on_few_heavy_weights():
    """A handful of heavily-weighted recent markets does NOT clear the effective-sample
    floor (Kish n_eff), so the model abstains rather than trusting a noisy rate."""
    train = _batch("r", 305.0, 0.30, 0.60, 10)   # 10 recent markets, all ~full weight
    as_of = BASE + timedelta(days=308)
    model = RecencyWeightedBucketModel(half_life_days=60.0, min_effective_n=30).fit(train, as_of)
    st = [s for s in model.stats if s.lo == 0.3][0]
    assert st.effective_n < 30.0
    assert model.predict(0.30) is None   # under-sampled → abstain, never fabricate


def test_weight_clamps_non_positive_age():
    """A training market that (defensively) appears to resolve at/after as_of gets weight
    1.0 — never a >1 (inflating) or negative weight."""
    train = [_hm("a", 10.0, 0.65, 1)]
    # as_of BEFORE the resolution → age negative → clamped to 0 → weight 1.0 → eff_n 1.
    model = RecencyWeightedBucketModel(min_effective_n=1).fit(train, BASE + timedelta(days=5))
    st = [s for s in model.stats if s.lo == 0.6][0]
    assert st.weighted_n == pytest.approx(1.0, abs=1e-9)
    assert st.effective_n == pytest.approx(1.0, abs=1e-9)


def test_fit_raises_on_empty_training():
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel().fit([], BASE)


def test_predict_before_fit_raises():
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel().predict(0.5)


def test_predict_out_of_range_abstains():
    model = RecencyWeightedBucketModel(edges=[0.6, 0.7], min_effective_n=1).fit(
        [_hm("a", 10.0, 0.65, 1)], BASE + timedelta(days=12)
    )
    assert model.predict(0.65) is not None
    assert model.predict(0.40) is None
    assert model.predict(0.95) is None


def test_fit_is_order_invariant():
    train = _batch("t", 10.0, 0.65, 0.85, 40)
    as_of = BASE + timedelta(days=12)
    a = RecencyWeightedBucketModel(min_effective_n=20).fit(train, as_of).stats
    b = RecencyWeightedBucketModel(min_effective_n=20).fit(list(reversed(train)), as_of).stats
    # Same buckets, same (weighted_n, yes_rate, effective_n) to floating precision.
    assert [(s.lo, round(s.yes_rate, 12), round(s.weighted_n, 9)) for s in a] == \
           [(s.lo, round(s.yes_rate, 12), round(s.weighted_n, 9)) for s in b]


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel(edges=[0.5])
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel(edges=[0.5, 0.5])
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel(edges=[-0.1, 0.5])
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel(half_life_days=0.0)
    with pytest.raises(ValueError):
        RecencyWeightedBucketModel(min_effective_n=0.0)


def test_default_edges_shape():
    edges = default_bucket_edges()
    assert edges[0] == 0.0 and edges[-1] == 1.0 and len(edges) == 11


def test_convenience_fitter():
    train = _batch("t", 10.0, 0.65, 0.85, 40, spread=0.0)
    model = fit_recency_model_from_history(train, BASE + timedelta(days=12), min_effective_n=20)
    assert model.fitted and model.predict(0.65) == pytest.approx(0.85, abs=1e-9)


# ---------------------------------------------------------------------------
# Walk-forward: recovers a stationary injected edge; no fake edge; deterministic
# ---------------------------------------------------------------------------
def _corpus(price: float, true_rate: float):
    """A stationary corpus at one price bucket. Training era resolves before the first OOS
    window (day 28); OOS batches of 20 per 7-day window."""
    markets = _batch("train", 12.0, price, true_rate, 60)
    for w, day in enumerate((30, 37, 44, 51, 58, 65)):
        markets += _batch(f"oos{w}", float(day) + 2.0, price, true_rate, 20)
    return markets


def test_walk_forward_recovers_injected_stationary_edge():
    # Crowd underprices favorites: price 0.65 but true YES-rate 0.85 (stationary). The
    # recency model learns ~0.85 and bets YES → positive OOS PnL.
    markets = _corpus(0.65, 0.85)
    strat = make_recency_weighted_bucket_strategy(min_effective_n=20, min_edge=0.02)
    res = walk_forward_backtest(markets, strat, seed=7)
    assert res.n_trades > 0
    assert res.total_pnl_usd > 0.0


def test_walk_forward_no_fake_edge_on_well_calibrated_crowd():
    # Crowd price 0.65 AND true YES-rate 0.65 → model_prob ~= crowd → the idealized
    # synthetic rate lands exactly on the price → 0 trades (no fabricated edge).
    markets = _corpus(0.65, 0.65)
    strat = make_recency_weighted_bucket_strategy(min_effective_n=20, min_edge=0.02)
    res = walk_forward_backtest(markets, strat, seed=7)
    assert res.n_trades == 0
    assert res.total_pnl_usd == pytest.approx(0.0, abs=1e-9)


def test_walk_forward_is_deterministic():
    markets = _corpus(0.65, 0.85)
    r1 = walk_forward_backtest(markets, make_recency_weighted_bucket_strategy(min_effective_n=20), seed=7)
    r2 = walk_forward_backtest(markets, make_recency_weighted_bucket_strategy(min_effective_n=20), seed=7)
    assert r1.seed_hash == r2.seed_hash
    assert r1.total_pnl_usd == r2.total_pnl_usd
    assert r1.n_trades == r2.n_trades
    assert [t.market_id for t in r1.trades] == [t.market_id for t in r2.trades]


def test_strategy_fn_refits_and_abstains_on_empty():
    strat = make_recency_weighted_bucket_strategy(min_effective_n=20, min_edge=0.02)
    view = MarketView("v", BASE + timedelta(days=20), market_price=0.65, model_prob=0.65)
    biased = _batch("b", 12.0, 0.65, 0.85, 60)
    calibrated = _batch("c", 12.0, 0.65, 0.65, 60)
    assert strat(biased, view).trade is True
    assert strat(calibrated, view).trade is False
    assert strat([], view).trade is False   # empty training → abstain, never raise


# ---------------------------------------------------------------------------
# Live wrapper: abstains without a model; honest tradeability gate
# ---------------------------------------------------------------------------
def _market(mid: str, yes_price: float, *, active: bool = True, closed: bool = False) -> Market:
    no_price = round(1.0 - yes_price, 4)
    return Market(
        id=mid, condition_id=f"c-{mid}", question=f"Q {mid}?", slug=f"s-{mid}",
        description="", category="", end_date=None,
        outcomes=[Outcome(token_id=f"yes-{mid}", label="Yes", price=yes_price, midpoint=yes_price, volume=1000.0),
                  Outcome(token_id=f"no-{mid}", label="No", price=no_price, midpoint=no_price, volume=1000.0)],
        total_volume=100000.0, liquidity=5000.0, active=active, closed=closed, resolved=False,
    )


def test_live_wrapper_abstains_without_model():
    strat = RecencyWeightedBucketStrategy(client=None, config=StrategyConfig())
    assert strat.scan([_market("m", 0.30)]) == []   # model=None → honest empty


def test_live_wrapper_fires_with_fitted_model_but_respects_active_flag():
    # Fit a model that will surface a big YES edge on the [0.3,0.4) bucket (true 60% vs
    # crowd 0.30), then confirm it signals on a tradeable market and ABSTAINS on the SAME
    # market marked untradeable (active=False) — the parser's tradeability signal wins.
    train = _batch("rec", 305.0, 0.30, 0.60, 60)
    model = fit_recency_model_from_history(train, BASE + timedelta(days=308), half_life_days=60.0, min_effective_n=20)
    strat = RecencyWeightedBucketStrategy(client=None, config=StrategyConfig(), model=model, min_edge=0.02)

    live = strat.scan([_market("m", 0.30)])
    assert len(live) == 1 and live[0].strategy == "recency_weighted_bucket"
    assert strat.scan([_market("m", 0.30, active=False)]) == []
    assert strat.scan([_market("m", 0.30, closed=True)]) == []
