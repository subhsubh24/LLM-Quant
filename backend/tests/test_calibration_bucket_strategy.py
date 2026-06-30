"""Tests for calibration_bucket_strategy — the first model_prob != crowd alpha.

These prove the HONESTY contract (abstain on insufficient data, raise on no data, never
fabricate a rate), LEAKAGE-safety inside walk_forward, DETERMINISTIC reproduction, that
it RECOVERS a known injected calibration bias out-of-sample, and that it trades ~nothing
on a WELL-CALIBRATED crowd (no fake edge). All synthetic + offline — no network.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets.calibration_bucket_strategy import (
    BucketStat,
    CalibrationBucketModel,
    CalibrationBucketStrategy,
    default_bucket_edges,
    fit_model_from_history,
    make_calibration_bucket_strategy,
)
from app.prediction_markets.polymarket_client import Market, Outcome
from app.prediction_markets.strategies import StrategyConfig
from app.prediction_markets.walk_forward import (
    HistoricalMarket,
    MarketView,
    walk_forward_backtest,
)

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _hm(mid: str, day: float, price: float, outcome: int, hold_days: float = 2.0) -> HistoricalMarket:
    dt = BASE + timedelta(days=day)
    return HistoricalMarket(
        market_id=mid,
        decision_time=dt,
        resolution_time=dt + timedelta(days=hold_days),
        market_price=price,
        model_prob=price,  # seeded to crowd; the STRATEGY overrides it with the bucket rate
        outcome=outcome,
    )


def _bucket_markets(prefix: str, start_day: float, price: float, yes_rate: float, n: int):
    """n markets at ``price``; EXACTLY ``round(yes_rate*n)`` resolve YES, spread evenly
    (Bresenham) so wins aren't clustered in one window."""
    n_yes = round(yes_rate * n)
    out = []
    for i in range(n):
        outcome = 1 if ((i + 1) * n_yes) // n != (i * n_yes) // n else 0
        out.append(_hm(f"{prefix}_{i}", start_day + i * 0.25, price, outcome))
    return out


# ---------------------------------------------------------------------------
# Model: fit / predict / abstain / raise
# ---------------------------------------------------------------------------
def test_fit_recovers_empirical_bucket_rate():
    # 40 markets at 0.65 (bucket [0.6,0.7)), 85% resolve YES.
    train = _bucket_markets("t", 0.0, 0.65, 0.85, 40)
    model = CalibrationBucketModel(min_bucket_n=20).fit(train)
    rate = model.predict(0.65)
    assert rate is not None
    # round(0.85*40)=34 YES / 40 = 0.85 exactly
    assert rate == pytest.approx(0.85, abs=1e-9)


def test_predict_abstains_when_bucket_undersampled():
    train = _bucket_markets("t", 0.0, 0.65, 0.85, 10)  # only 10 < min_bucket_n
    model = CalibrationBucketModel(min_bucket_n=30).fit(train)
    assert model.predict(0.65) is None  # uncalibrated -> abstain, never fabricate


def test_predict_abstains_outside_bucket_range():
    train = _bucket_markets("t", 0.0, 0.65, 0.85, 40)
    model = CalibrationBucketModel(edges=[0.6, 0.7], min_bucket_n=20).fit(train)
    assert model.predict(0.65) is not None
    assert model.predict(0.50) is None   # below range
    assert model.predict(0.95) is None   # above range


def test_fit_raises_on_empty_training():
    model = CalibrationBucketModel()
    with pytest.raises(ValueError):
        model.fit([])


def test_predict_before_fit_raises():
    model = CalibrationBucketModel()
    with pytest.raises(ValueError):
        model.predict(0.5)


def test_fit_is_order_invariant():
    train = _bucket_markets("t", 0.0, 0.65, 0.85, 40)
    a = CalibrationBucketModel(min_bucket_n=20).fit(train).stats
    b = CalibrationBucketModel(min_bucket_n=20).fit(list(reversed(train))).stats
    assert a == b  # pure integer counting in a fixed bucket order — input-order-invariant


def test_strategy_fn_refits_on_each_call():
    # The closure must build a FRESH model each call (no shared mutable state): re-using
    # the SAME StrategyFn on a different corpus must use the NEW corpus's calibration.
    strat = make_calibration_bucket_strategy(min_bucket_n=20, min_edge=0.02)
    view = MarketView("v", BASE, market_price=0.65, model_prob=0.65)
    biased = _bucket_markets("b", 0.0, 0.65, 0.85, 40)      # crowd underprices → trade YES
    calibrated = _bucket_markets("c", 0.0, 0.65, 0.65, 40)  # well-calibrated → no trade
    d1 = strat(biased, view)
    d2 = strat(calibrated, view)
    d3 = strat(biased, view)  # back to biased — must trade again (no stale stale stats)
    assert d1.trade is True and d1.side == "YES"
    assert d2.trade is False
    assert d3.trade is True


def test_strategy_fn_abstains_on_empty_training():
    # An empty training set (e.g. the first OOS window) must ABSTAIN, never raise.
    strat = make_calibration_bucket_strategy(min_bucket_n=20)
    view = MarketView("v", BASE, market_price=0.65, model_prob=0.65)
    assert strat([], view) == strat([], view)  # deterministic
    assert strat([], view).trade is False


def test_bucket_boundaries_map_consistently():
    model = CalibrationBucketModel(min_bucket_n=1)
    model.fit([_hm("x", 0, 0.65, 1)])
    # left-inclusive [lo,hi): 0.7 belongs to bucket [0.7,0.8), not [0.6,0.7)
    assert model._bucket_index(0.65) == 6
    assert model._bucket_index(0.70) == 7
    assert model._bucket_index(0.0) == 0
    assert model._bucket_index(1.0) == 9   # last bucket inclusive on the right
    assert model._bucket_index(1.0001) is None
    assert model._bucket_index(-0.01) is None


def test_invalid_edges_rejected():
    with pytest.raises(ValueError):
        CalibrationBucketModel(edges=[0.5])           # < 2 edges
    with pytest.raises(ValueError):
        CalibrationBucketModel(edges=[0.5, 0.5])      # not strictly increasing
    with pytest.raises(ValueError):
        CalibrationBucketModel(edges=[-0.1, 0.5])     # out of [0,1]
    with pytest.raises(ValueError):
        CalibrationBucketModel(min_bucket_n=0)


def test_default_edges_shape():
    edges = default_bucket_edges()
    assert edges[0] == 0.0 and edges[-1] == 1.0
    assert len(edges) == 11


# ---------------------------------------------------------------------------
# Walk-forward: recovers an injected OOS edge; leakage-safe; deterministic
# ---------------------------------------------------------------------------
def _corpus(price: float, true_rate: float):
    """A corpus at one price bucket whose true YES-rate is ``true_rate``.

    Training era (days 0..15, resolves before the first OOS window opens at day 28 with
    train_min_days=28): 60 markets. OOS era: one faithful batch of 20 markets per 7-day
    window at days 30, 37, 44, 51, 58, 65 — n=20 represents ``true_rate`` honestly (a
    tiny n=2 batch can only express 50%/100%, which would itself BE a miscalibration)."""
    markets = _bucket_markets("train", 0.0, price, true_rate, 60)
    for w, day in enumerate((30, 37, 44, 51, 58, 65)):
        markets += _bucket_markets(f"oos{w}", float(day), price, true_rate, 20)
    return markets


def _biased_corpus():
    """Crowd UNDERPRICES favorites in bucket [0.6,0.7): price 0.65 but true YES-rate 0.85."""
    return _corpus(0.65, 0.85)


def test_walk_forward_recovers_injected_edge():
    markets = _biased_corpus()
    strat = make_calibration_bucket_strategy(min_bucket_n=20, min_edge=0.02)
    res = walk_forward_backtest(markets, strat, seed=7)
    # The model learns P[YES]=0.85 in the [0.6,0.7) bucket and bets YES (0.85 vs crowd
    # 0.65) — a large cost-net edge — winning ~85% of the time → POSITIVE total PnL.
    assert res.n_trades > 0
    assert res.total_pnl_usd > 0.0


def test_walk_forward_is_deterministic():
    markets = _biased_corpus()
    strat1 = make_calibration_bucket_strategy(min_bucket_n=20)
    strat2 = make_calibration_bucket_strategy(min_bucket_n=20)
    r1 = walk_forward_backtest(markets, strat1, seed=7)
    r2 = walk_forward_backtest(markets, strat2, seed=7)
    assert r1.seed_hash == r2.seed_hash
    assert r1.total_pnl_usd == r2.total_pnl_usd
    assert r1.n_trades == r2.n_trades
    assert [t.market_id for t in r1.trades] == [t.market_id for t in r2.trades]


def test_walk_forward_no_fake_edge_on_well_calibrated_crowd():
    # Crowd price 0.65 AND true YES-rate 0.65 → model_prob ~= crowd → net edge < 0 on
    # both sides after costs → the strategy trades ~nothing (no fabricated edge).
    # NOTE (honest scope): this is the IDEALIZED case — the synthetic empirical rate lands
    # exactly on the price (0.65 divides evenly), so trades are exactly 0. On a real
    # finite-sample well-calibrated crowd the empirical rate jitters off the penny and the
    # strategy WILL place some noise trades — which lose to costs on average (no systematic
    # edge). That empirical behaviour is deferred to a real OOS run (per the module
    # docstring); see test_cost_band_suppresses_subthreshold_miscalibration for the
    # load-bearing mechanism (the cost band eats sub-threshold miscalibration).
    markets = _corpus(0.65, 0.65)
    strat = make_calibration_bucket_strategy(min_bucket_n=20, min_edge=0.02)
    res = walk_forward_backtest(markets, strat, seed=7)
    assert res.n_trades == 0
    assert res.total_pnl_usd == pytest.approx(0.0, abs=1e-9)


def test_cost_band_suppresses_subthreshold_miscalibration():
    # A SMALL miscalibration (crowd 0.65, true rate 0.66 — 1 cent) is within the cost band
    # (cost_model.net_edge(0.66, 0.65) ~= -0.006 < min_edge), so the strategy must ABSTAIN
    # rather than trade noise. This is the mechanism that keeps it from manufacturing an
    # edge from tiny crowd imperfections — the honest load-bearing assumption.
    markets = _corpus(0.65, 0.66)
    strat = make_calibration_bucket_strategy(min_bucket_n=20, min_edge=0.02)
    res = walk_forward_backtest(markets, strat, seed=7)
    assert res.n_trades == 0


def test_walk_forward_abstains_when_no_calibrated_bucket():
    # Too few training markets per bucket to ever calibrate (min_bucket_n high) → 0 trades.
    markets = _biased_corpus()
    strat = make_calibration_bucket_strategy(min_bucket_n=10_000)
    res = walk_forward_backtest(markets, strat, seed=7)
    assert res.n_trades == 0


# ---------------------------------------------------------------------------
# Live wrapper: honest abstain without a fitted model; never fabricates a signal
# ---------------------------------------------------------------------------
def _market(mid: str, yes_price: float, *, yes_label: str = "Yes", no_label: str = "No") -> Market:
    return Market(
        id=mid,
        condition_id=f"c_{mid}",
        question=f"Will event {mid} happen?",
        slug=mid,
        description="",
        category="test",
        end_date=BASE + timedelta(days=3),
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label=yes_label, price=yes_price, midpoint=yes_price, volume=1000.0),
            Outcome(token_id=f"{mid}_no", label=no_label, price=round(1.0 - yes_price, 4), midpoint=round(1.0 - yes_price, 4), volume=1000.0),
        ],
        total_volume=2000.0,
        liquidity=2000.0,
        active=True,
        closed=False,
        resolved=False,
    )


def test_live_wrapper_abstains_without_model():
    strat = CalibrationBucketStrategy(client=None, config=StrategyConfig(), model=None)
    assert strat.scan([_market("m1", 0.65)]) == []


def test_live_wrapper_abstains_with_unfitted_model():
    strat = CalibrationBucketStrategy(
        client=None, config=StrategyConfig(), model=CalibrationBucketModel()
    )
    assert strat.scan([_market("m1", 0.65)]) == []


def test_live_wrapper_emits_signal_on_miscalibrated_bucket():
    model = fit_model_from_history(_bucket_markets("t", 0.0, 0.65, 0.85, 40), min_bucket_n=20)
    strat = CalibrationBucketStrategy(client=None, config=StrategyConfig(), model=model, min_edge=0.02)
    results = strat.scan([_market("m1", 0.65)])
    assert len(results) == 1
    r = results[0]
    assert r.strategy == "calibration_bucket"
    assert r.side == "BUY"
    # model says 0.85 (the empirical bucket rate), not the crowd 0.65 — this IS model != crowd
    assert r.expected_value == pytest.approx(0.85, abs=1e-9)
    assert r.edge > 0.0


def test_live_wrapper_skips_untradeable_market_even_with_in_range_price():
    # A market the parser marked untradeable (active=False — e.g. inconsistent/incomplete
    # outcome arrays) must NOT produce a signal, even though its YES price is a real in-range
    # value the same fitted model trades on the tradeable version. This keeps the parser's
    # honesty guard (active=False) from leaking through this consumer once it is wired.
    import dataclasses

    model = fit_model_from_history(_bucket_markets("t", 0.0, 0.65, 0.85, 40), min_bucket_n=20)
    strat = CalibrationBucketStrategy(client=None, config=StrategyConfig(), model=model, min_edge=0.02)
    tradeable = _market("m1", 0.65)
    assert len(strat.scan([tradeable])) == 1  # control: tradeable version DOES signal
    assert strat.scan([dataclasses.replace(tradeable, active=False)]) == []
    assert strat.scan([dataclasses.replace(tradeable, closed=True)]) == []


def test_live_wrapper_no_signal_on_uncalibrated_market():
    model = fit_model_from_history(_bucket_markets("t", 0.0, 0.65, 0.85, 40), edges=[0.6, 0.7], min_bucket_n=20)
    strat = CalibrationBucketStrategy(client=None, config=StrategyConfig(), model=model, min_edge=0.02)
    # 0.30 is outside the single [0.6,0.7) bucket → abstain
    assert strat.scan([_market("m2", 0.30)]) == []


def test_live_wrapper_skips_non_yes_no_market():
    model = fit_model_from_history(_bucket_markets("t", 0.0, 0.65, 0.85, 40), min_bucket_n=20)
    strat = CalibrationBucketStrategy(client=None, config=StrategyConfig(), model=model)
    # labels aren't YES/NO → the model (defined on P[YES]) refuses rather than guessing
    assert strat.scan([_market("m3", 0.65, yes_label="Candidate A", no_label="Candidate B")]) == []
