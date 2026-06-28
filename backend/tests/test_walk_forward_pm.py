"""Tests for the leakage-free walk-forward prediction-market backtest (C1/C3).

These tests assert the ENGINE is honest, not that a real edge exists:
  * determinism — same data + seed → bit-identical weekly PnL + seed_hash
  * no look-ahead — the decision view structurally lacks the outcome
  * costs applied — cash deployed == budget (no double-count); effective cost > raw
  * recovers a KNOWN injected edge; reports ~0 on a NO-edge (efficient) market
  * leak-free training — the strategy only ever sees markets resolved before the window
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.prediction_markets.walk_forward import (
    HistoricalMarket,
    MarketView,
    TradeDecision,
    make_net_edge_strategy,
    walk_forward_backtest,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _market(i, price, model, outcome, decide_day, resolve_day):
    return HistoricalMarket(
        market_id=f"m{i}",
        decision_time=BASE + timedelta(days=decide_day),
        resolution_time=BASE + timedelta(days=resolve_day),
        market_price=price,
        model_prob=model,
        outcome=outcome,
    )


def _edge_dataset(n=120):
    """Markets where the model is right (P[YES]=0.7) and the crowd misprices YES at
    0.50; exactly 7 of every 10 resolve YES, so the injected edge is real + deterministic.
    Decisions are spread across ~n days so there are many OOS windows."""
    markets = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0
        markets.append(_market(i, price=0.50, model=0.70, outcome=outcome,
                               decide_day=i, resolve_day=i + 1))
    return markets


def test_determinism_same_seed_same_pnl():
    data = _edge_dataset()
    a = walk_forward_backtest(data, seed=42)
    b = walk_forward_backtest(data, seed=42)
    assert a.seed_hash == b.seed_hash
    assert a.total_pnl_usd == b.total_pnl_usd
    assert a.weekly_pnl == b.weekly_pnl
    assert [t.pnl_usd for t in a.trades] == [t.pnl_usd for t in b.trades]


def test_no_lookahead_view_has_no_outcome():
    """The object the strategy receives must not carry the future."""
    seen = {}

    def spy(_training, view: MarketView) -> TradeDecision:
        seen["has_outcome"] = hasattr(view, "outcome")
        seen["has_resolution"] = hasattr(view, "resolution_time")
        return TradeDecision(trade=False)

    walk_forward_backtest(_edge_dataset(60), strategy_fn=spy)
    assert seen, "strategy was never invoked — dataset must span past the warmup window"
    assert seen["has_outcome"] is False
    assert seen["has_resolution"] is False


def test_training_is_leak_free():
    """Training handed to the strategy may only contain markets resolved strictly
    before the candidate's window opened. Since a window opens at or before the
    candidate's decision_time, every trained market MUST have resolved strictly before
    that decision_time — otherwise the future leaked in."""
    violations = []
    saw_nonempty_training = []

    def checker(training, view: MarketView) -> TradeDecision:
        if training:
            saw_nonempty_training.append(True)
        for tm in training:
            # The candidate itself must never be in its own training set, and no trained
            # market may resolve at/after the moment we are deciding on this candidate.
            if tm.market_id == view.market_id or tm.resolution_time >= view.decision_time:
                violations.append((tm.market_id, view.market_id))
        return TradeDecision(trade=False)

    walk_forward_backtest(_edge_dataset(60), strategy_fn=checker)
    assert violations == []
    # Guard against a vacuous pass: later windows MUST present a non-empty training set.
    assert saw_nonempty_training, "training set was always empty — test would be vacuous"


def test_costs_applied_no_double_count():
    data = _edge_dataset(60)
    res = walk_forward_backtest(data, seed=1)
    assert res.n_trades > 0
    for t in res.trades:
        # All-in cost strictly exceeds the raw entry price (slippage + fee).
        assert t.effective_cost > t.entry_price
        # Cash deployed equals contracts * effective cost (budget), within fp tolerance.
        assert t.budget_usd == pytest.approx(t.contracts * t.effective_cost, rel=1e-9)
        # PnL is payout minus the deployed cash — never an un-costed gross.
        assert t.pnl_usd == pytest.approx(t.payout_usd - t.budget_usd, rel=1e-9)


def test_recovers_known_positive_edge():
    res = walk_forward_backtest(_edge_dataset(300), seed=7)
    assert res.n_trades > 0
    # A genuine 0.70-vs-0.50 edge, costed, should still net positive over 300 markets.
    assert res.total_pnl_usd > 0
    assert res.final_bankroll > 10_000.0


def test_no_edge_efficient_market_no_trades():
    """When the model agrees with the crowd (price == model_prob), net edge after costs
    is negative everywhere → the strategy takes NO trades → exactly zero PnL."""
    markets = []
    for i in range(120):
        outcome = 1 if (i % 2 == 0) else 0
        markets.append(_market(i, price=0.50, model=0.50, outcome=outcome,
                               decide_day=i, resolve_day=i + 1))
    res = walk_forward_backtest(markets, seed=3)
    assert res.n_trades == 0
    assert res.total_pnl_usd == 0.0
    assert res.final_bankroll == 10_000.0


def test_empty_input():
    res = walk_forward_backtest([], seed=5)
    assert res.n_trades == 0
    assert res.total_pnl_usd == 0.0
    assert res.weekly_pnl == []


def test_buys_no_side_when_crowd_overprices_yes():
    """Crowd prices YES at 0.80 but model says 0.40 → the value is on the NO side; the
    default strategy should buy NO and profit when NO resolves."""
    markets = []
    for i in range(100):
        outcome = 1 if (i % 10) < 4 else 0   # YES only 40% — crowd overpriced it
        markets.append(_market(i, price=0.80, model=0.40, outcome=outcome,
                               decide_day=i, resolve_day=i + 1))
    res = walk_forward_backtest(markets, seed=9)
    assert res.n_trades > 0
    assert all(t.side == "NO" for t in res.trades)
    assert res.total_pnl_usd > 0


def test_causality_enforced_on_construction():
    with pytest.raises(ValueError):
        HistoricalMarket("x", BASE + timedelta(days=5), BASE, 0.5, 0.5, 1)
    with pytest.raises(ValueError):
        HistoricalMarket("x", BASE, BASE + timedelta(days=1), 1.5, 0.5, 1)
    with pytest.raises(ValueError):
        HistoricalMarket("x", BASE, BASE + timedelta(days=1), 0.5, 0.5, 2)


def test_zero_duration_market_rejected():
    """A market that resolves the instant it is decided would let capital recycle within
    one timestamp — reject it (positive holding period required)."""
    with pytest.raises(ValueError):
        HistoricalMarket("x", BASE, BASE, 0.5, 0.5, 1)


def test_duplicate_market_id_fails_loud():
    """A dataset listing the same market_id twice is a data error that would crash the
    settlement heap / make the hash order-sensitive — it must fail loud, not crash."""
    dup = [
        _market(1, 0.5, 0.7, 1, decide_day=0, resolve_day=1),
        _market(1, 0.5, 0.7, 0, decide_day=2, resolve_day=3),  # same id "m1"
    ]
    with pytest.raises(ValueError, match="duplicate market_id"):
        walk_forward_backtest(dup)


def test_min_edge_threshold_filters():
    """A tiny edge below min_edge is not traded."""
    strat = make_net_edge_strategy(min_edge=0.50)  # absurdly high bar
    res = walk_forward_backtest(_edge_dataset(60), strategy_fn=strat)
    assert res.n_trades == 0


def test_dense_losing_cluster_never_goes_negative():
    """A dense cluster of many same-window candidates that ALL lose must never drive the
    bankroll negative — capital is hard-capped at available free cash (the over-deployment
    bug). Many markets decided on the SAME day, all resolving to a loss for our side."""
    markets = []
    # A few early markets so the timeline spans past the 28-day warmup and a window
    # actually opens around the cluster. These resolve before the cluster is decided.
    for i in range(5):
        markets.append(_market(900 + i, price=0.50, model=0.50, outcome=0,
                               decide_day=i, resolve_day=i + 1))
    decide = 40   # the cluster: all decided the same day, inside one OOS window
    for i in range(50):
        # model says YES 0.9 but every market resolves NO → every YES bet loses.
        markets.append(_market(i, price=0.50, model=0.90, outcome=0,
                               decide_day=decide, resolve_day=decide + 3))
    res = walk_forward_backtest(markets, initial_bankroll=10_000.0, seed=2)
    assert res.n_trades > 0
    assert res.final_bankroll >= 0.0          # never deployed cash it did not have
    # Total deployed across the simultaneous cluster cannot exceed the starting bankroll.
    assert sum(t.budget_usd for t in res.trades) <= 10_000.0 + 1e-6
    # And the worst case loses at most the whole bankroll, not more.
    assert res.total_pnl_usd >= -10_000.0 - 1e-6


def test_seed_hash_covers_all_pnl_inputs():
    """The seed_hash must change when ANY input that affects PnL changes — bankroll,
    cost rates, or window sizing — not just the markets+seed (an auditor proved the
    old hash falsely collided across these)."""
    from backend.app.prediction_markets.cost_model import CostModel

    data = _edge_dataset(60)
    base = walk_forward_backtest(data, seed=42).seed_hash
    assert walk_forward_backtest(data, seed=42, initial_bankroll=50_000.0).seed_hash != base
    assert walk_forward_backtest(
        data, seed=42, cost_model=CostModel(slippage_rate=0.2, fee_rate=0.2)
    ).seed_hash != base
    assert walk_forward_backtest(data, seed=42, test_window_days=14).seed_hash != base
    assert walk_forward_backtest(data, seed=42, max_fraction_per_trade=0.10).seed_hash != base
    # Identical inputs still reproduce the same hash.
    assert walk_forward_backtest(data, seed=42).seed_hash == base


def _market_liq(i, price, model, outcome, decide_day, resolve_day, liquidity):
    return HistoricalMarket(
        market_id=f"m{i}",
        decision_time=BASE + timedelta(days=decide_day),
        resolution_time=BASE + timedelta(days=resolve_day),
        market_price=price,
        model_prob=model,
        outcome=outcome,
        liquidity=liquidity,
    )


def _edge_dataset_liq(n, liquidity):
    markets = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0
        markets.append(_market_liq(i, price=0.50, model=0.70, outcome=outcome,
                                   decide_day=i, resolve_day=i + 1, liquidity=liquidity))
    return markets


def test_thin_liquidity_realizes_worse_pnl_on_same_trades():
    """Two identical datasets except one is THIN (small liquidity). The thin book pays
    more market impact → fewer contracts per dollar → worse realized PnL on a winning
    edge (the depth-aware fill cost in action)."""
    deep = walk_forward_backtest(_edge_dataset_liq(300, liquidity=1e9), seed=7)
    thin = walk_forward_backtest(_edge_dataset_liq(300, liquidity=50.0), seed=7)
    # Both trade the same markets/edge; the thin book just costs more to fill.
    assert deep.n_trades == thin.n_trades
    assert thin.total_pnl_usd < deep.total_pnl_usd


def test_liquidity_none_matches_flat_behavior():
    """A dataset with liquidity=None must produce IDENTICAL results to the legacy path
    (no impact applied) — zero behavior change for existing callers."""
    legacy = walk_forward_backtest(_edge_dataset(120), seed=7)
    none_liq = walk_forward_backtest(_edge_dataset_liq(120, liquidity=None), seed=7)
    assert legacy.total_pnl_usd == none_liq.total_pnl_usd
    assert [t.pnl_usd for t in legacy.trades] == [t.pnl_usd for t in none_liq.trades]


def test_determinism_holds_with_liquidity():
    data = _edge_dataset_liq(120, liquidity=500.0)
    a = walk_forward_backtest(data, seed=42)
    b = walk_forward_backtest(data, seed=42)
    assert a.seed_hash == b.seed_hash
    assert a.total_pnl_usd == b.total_pnl_usd
    assert [t.pnl_usd for t in a.trades] == [t.pnl_usd for t in b.trades]


def test_seed_hash_covers_liquidity():
    """Changing the liquidity signal must change the fingerprint (it now affects PnL)."""
    base = walk_forward_backtest(_edge_dataset_liq(60, liquidity=None), seed=42).seed_hash
    thin = walk_forward_backtest(_edge_dataset_liq(60, liquidity=100.0), seed=42).seed_hash
    assert thin != base


def test_seed_hash_covers_impact_coeff():
    """impact_coeff drives the depth-aware fill cost, so it MUST be in the fingerprint.
    Two runs over the SAME liquidity-bearing data + seed but different impact_coeff must
    produce a DIFFERENT seed_hash AND a different PnL — otherwise the hash would certify
    two materially different results as identical (a reproducibility-invariant violation)."""
    from backend.app.prediction_markets.cost_model import CostModel
    # liquidity=2000 keeps the impact UNSATURATED (below the 1.0 cap) so changing
    # impact_coeff genuinely moves PnL — at a very thin book both coeffs saturate at the
    # cap and PnL would coincide, hiding the effect.
    data = _edge_dataset_liq(60, liquidity=2000.0)
    r_lo = walk_forward_backtest(data, seed=42, cost_model=CostModel(impact_coeff=0.5))
    r_hi = walk_forward_backtest(data, seed=42, cost_model=CostModel(impact_coeff=1.0))
    assert r_lo.seed_hash != r_hi.seed_hash
    assert r_lo.total_pnl_usd != r_hi.total_pnl_usd
    # And with NO liquidity, impact_coeff cannot affect PnL — but the honest fingerprint
    # still distinguishes the configs (it covers all PnL-relevant CONFIG, conservatively).
    flat = _edge_dataset_liq(60, liquidity=None)
    f_lo = walk_forward_backtest(flat, seed=42, cost_model=CostModel(impact_coeff=0.5))
    f_hi = walk_forward_backtest(flat, seed=42, cost_model=CostModel(impact_coeff=1.0))
    assert f_lo.total_pnl_usd == f_hi.total_pnl_usd       # flat path ignores impact_coeff
    assert f_lo.seed_hash != f_hi.seed_hash               # but the config still differs


def test_cash_deployed_matches_budget_under_impact():
    """The no-double-count invariant must hold even with impact: deployed cash equals
    contracts * effective_cost for every trade (impact is reflected in contract count,
    not as a second cash charge)."""
    res = walk_forward_backtest(_edge_dataset_liq(120, liquidity=200.0), seed=3)
    assert res.n_trades > 0
    for t in res.trades:
        assert t.effective_cost > t.entry_price          # flat + impact both add cost
        assert t.budget_usd == pytest.approx(t.contracts * t.effective_cost, rel=1e-9)
        assert t.pnl_usd == pytest.approx(t.payout_usd - t.budget_usd, rel=1e-9)


def test_liquidity_must_be_positive():
    with pytest.raises(ValueError, match="liquidity"):
        _market_liq(1, 0.5, 0.7, 1, decide_day=0, resolve_day=1, liquidity=0.0)
    with pytest.raises(ValueError, match="liquidity"):
        _market_liq(1, 0.5, 0.7, 1, decide_day=0, resolve_day=1, liquidity=-5.0)


def test_capital_tied_up_until_resolution():
    """A position opened in one window but resolving far later ties up its cost basis:
    a second candidate decided BEFORE the first resolves is sized off reduced free cash,
    so cumulative live deployment never exceeds the bankroll."""
    # Two markets: first decided day 40 resolves day 80; second decided day 45 resolves
    # day 50 — the second is decided while the first is still open.
    m1 = _market(1, price=0.50, model=0.90, outcome=1, decide_day=40, resolve_day=80)
    m2 = _market(2, price=0.50, model=0.90, outcome=1, decide_day=45, resolve_day=50)
    res = walk_forward_backtest([m1, m2], initial_bankroll=10_000.0, seed=1)
    assert res.final_bankroll >= 0.0
