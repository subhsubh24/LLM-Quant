"""Tests for regime_slice (ROADMAP F10 — backtest robustness / anti-overfitting).

DETERMINISTIC + PURE: constructs BacktestTrade records directly (no backtest run,
no network) and asserts the slicing, concentration map, and fragile flag.

The point of F10: an aggregate OOS PnL that clears the floor can HIDE a fragile edge
concentrated in one slice — these tests prove a concentrated corpus is FLAGGED and a
broad one is NOT.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.prediction_markets.regime_slice import (
    UNCATEGORIZED,
    analyze_regime_slices,
)
from app.prediction_markets.walk_forward import BacktestTrade

# A Monday, so _iso_monday(res) == res.date() for res on this day.
BASE_RES = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)


def _trade(market_id, pnl, *, budget=100.0, entry=0.5, horizon_days=5, res=BASE_RES):
    decision = res - timedelta(days=horizon_days)
    return BacktestTrade(
        market_id=market_id,
        decision_time=decision,
        resolution_time=res,
        side="YES",
        entry_price=entry,
        effective_cost=entry,
        contracts=(budget / entry) if entry else 0.0,
        budget_usd=budget,
        payout_usd=budget + pnl,
        pnl_usd=pnl,
        is_win=pnl > 0,
    )


def _week(n):
    """resolution_time n weeks after BASE_RES (distinct ISO-week buckets)."""
    return BASE_RES + timedelta(days=7 * n)


# ---------------------------------------------------------------------------
# Broad edge → NOT fragile
# ---------------------------------------------------------------------------
def test_broad_edge_is_not_fragile():
    cats = ["Crypto", "Politics", "Sports", "Weather", "Econ", "Tech", "World", "Science"]
    entries = [0.05, 0.15, 0.3, 0.4, 0.6, 0.7, 0.8, 0.95]      # spread across confidence bands
    horizons = [0.5, 2, 5, 20, 40, 5, 2, 20]                   # spread across horizon bands
    trades = [
        _trade(f"m{i}", +50.0, entry=entries[i], horizon_days=horizons[i], res=_week(i % 4))
        for i in range(8)
    ]
    cat_map = {f"m{i}": cats[i] for i in range(8)}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)

    assert rep.n_trades == 8
    assert rep.total_pnl_usd == 400.0
    assert rep.has_positive_edge is True
    assert rep.fragile is False
    assert any("broad" in r for r in rep.fragile_reasons)
    # every category holds an equal 1/8 of PnL → no bucket over threshold
    assert rep.top_category_pnl_share is not None and rep.top_category_pnl_share < 0.7


# ---------------------------------------------------------------------------
# Concentrated in one category → fragile (category + leave-one-out + single-market)
# ---------------------------------------------------------------------------
def test_single_category_edge_is_fragile():
    trades = [
        _trade("big", +300.0),                                     # Crypto
        _trade("p1", -20.0, res=_week(1), entry=0.3, horizon_days=2),   # Politics
        _trade("s1", -10.0, res=_week(2), entry=0.7, horizon_days=20),  # Sports
        _trade("w1", +5.0, res=_week(3), entry=0.8, horizon_days=40),   # Weather
    ]
    cat_map = {"big": "Crypto", "p1": "Politics", "s1": "Sports", "w1": "Weather"}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)

    assert rep.total_pnl_usd == 275.0 and rep.has_positive_edge is True
    assert rep.fragile is True
    joined = " | ".join(rep.fragile_reasons)
    assert "category" in joined
    assert "leave-one-out" in joined         # removing Crypto flips remaining to <= 0
    assert "single-market" in joined          # 'big' alone > 50% of net PnL


# ---------------------------------------------------------------------------
# One dimension concentrated at a time
# ---------------------------------------------------------------------------
def test_horizon_concentration_flagged_when_categories_broad():
    # 4 distinct categories + 4 distinct confidence bands + 2 weeks, but ALL 3-7d horizon.
    trades = [
        _trade("a", +25.0, entry=0.2, horizon_days=5, res=_week(0)),
        _trade("b", +25.0, entry=0.4, horizon_days=5, res=_week(0)),
        _trade("c", +25.0, entry=0.6, horizon_days=5, res=_week(1)),
        _trade("d", +25.0, entry=0.8, horizon_days=5, res=_week(1)),
    ]
    cat_map = {"a": "A", "b": "B", "c": "C", "d": "D"}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.fragile is True
    assert any(r.startswith("horizon:") for r in rep.fragile_reasons)
    # category is NOT the trigger (each category is only 25%)
    assert not any(r.startswith("category:") for r in rep.fragile_reasons)
    # all four horizon trades land in the same bucket
    horizon_labels = {s.label for s in rep.by_horizon if s.n_trades}
    assert horizon_labels == {"3-7d"}


def test_time_concentration_flagged():
    # All resolve in the SAME ISO week; category/horizon/confidence spread.
    trades = [
        _trade("a", +25.0, entry=0.2, horizon_days=1, res=BASE_RES),
        _trade("b", +25.0, entry=0.4, horizon_days=5, res=BASE_RES + timedelta(days=1)),
        _trade("c", +25.0, entry=0.6, horizon_days=20, res=BASE_RES + timedelta(days=2)),
        _trade("d", +25.0, entry=0.8, horizon_days=40, res=BASE_RES + timedelta(days=3)),
    ]
    cat_map = {"a": "A", "b": "B", "c": "C", "d": "D"}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.fragile is True
    assert any(r.startswith("time-window:") for r in rep.fragile_reasons)
    assert len([s for s in rep.by_time if s.n_trades]) == 1   # one week bucket


def test_single_market_concentration_flagged_when_categories_broad():
    # 'big' dominates net PnL but its category (Crypto) is offset by a loser, so no
    # category bucket exceeds threshold — isolating the single-market flag.
    trades = [
        _trade("big", +300.0, res=_week(0), entry=0.2, horizon_days=1),   # Crypto
        _trade("hedge", -250.0, res=_week(1), entry=0.4, horizon_days=5),  # Crypto
        _trade("p1", +150.0, res=_week(2), entry=0.6, horizon_days=20),    # Politics
        _trade("s1", +150.0, res=_week(3), entry=0.8, horizon_days=40),    # Sports
    ]
    cat_map = {"big": "Crypto", "hedge": "Crypto", "p1": "Politics", "s1": "Sports"}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.total_pnl_usd == 350.0
    assert rep.fragile is True
    assert any(r.startswith("single-market:") for r in rep.fragile_reasons)
    assert not any(r.startswith("category:") for r in rep.fragile_reasons)
    assert rep.top_market_pnl_share is not None and rep.top_market_pnl_share > 0.5


# ---------------------------------------------------------------------------
# Honest edge cases
# ---------------------------------------------------------------------------
def test_empty_input_is_clean_not_fragile():
    rep = analyze_regime_slices([])
    assert rep.n_trades == 0
    assert rep.total_pnl_usd == 0.0
    assert rep.has_positive_edge is False
    assert rep.fragile is False
    assert rep.by_category == () and rep.by_horizon == ()
    assert rep.top_category_pnl_share is None and rep.top_market_pnl_share is None


def test_negative_aggregate_is_not_flagged_fragile():
    trades = [_trade("a", -100.0), _trade("b", +10.0, res=_week(1))]
    rep = analyze_regime_slices(trades)
    assert rep.total_pnl_usd == -90.0
    assert rep.has_positive_edge is False
    assert rep.fragile is False
    assert any("no positive" in r.lower() for r in rep.fragile_reasons)


def test_absent_category_map_reports_uncategorized():
    rep = analyze_regime_slices([_trade("a", +50.0), _trade("b", +50.0, res=_week(1))])
    labels = {s.label for s in rep.by_category}
    assert labels == {UNCATEGORIZED}


# ---------------------------------------------------------------------------
# Bucketing correctness + determinism
# ---------------------------------------------------------------------------
def test_horizon_and_confidence_buckets_partition_correctly():
    trades = [
        _trade("h0", +1.0, entry=0.05, horizon_days=0.5, res=_week(0)),   # <=1d, 0-10%
        _trade("h1", +1.0, entry=0.2, horizon_days=2, res=_week(1)),      # 1-3d, 10-25%
        _trade("h2", +1.0, entry=0.4, horizon_days=5, res=_week(2)),      # 3-7d, 25-50%
        _trade("h3", +1.0, entry=0.6, horizon_days=15, res=_week(3)),     # 7-30d, 50-75%
        _trade("h4", +1.0, entry=0.85, horizon_days=45, res=_week(4)),    # >30d, 75-90%
        _trade("h5", +1.0, entry=0.97, horizon_days=45, res=_week(5)),    # >30d, 90-100%
    ]
    rep = analyze_regime_slices(trades)
    horizon = [s.label for s in rep.by_horizon]
    assert horizon == ["<=1d", "1-3d", "3-7d", "7-30d", ">30d"]   # ordered, >30d merged
    conf = [s.label for s in rep.by_confidence]
    assert conf == ["0-10%", "10-25%", "25-50%", "50-75%", "75-90%", "90-100%"]


def test_report_is_deterministic():
    trades = [
        _trade("big", +300.0),
        _trade("p1", -20.0, res=_week(1)),
        _trade("s1", +5.0, res=_week(2)),
    ]
    cat_map = {"big": "Crypto", "p1": "Politics", "s1": "Sports"}
    r1 = analyze_regime_slices(trades, category_by_market_id=cat_map)
    r2 = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert r1 == r2   # frozen dataclasses compare by value → bit-stable


def test_budget_concentration_shares_computed():
    trades = [
        _trade("a", +10.0, budget=800.0),                          # Crypto — dominant exposure
        _trade("b", +10.0, budget=100.0, res=_week(1)),            # Politics
        _trade("c", +10.0, budget=100.0, res=_week(2)),            # Sports
    ]
    cat_map = {"a": "Crypto", "b": "Politics", "c": "Sports"}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.total_gross_budget_usd == 1000.0
    assert rep.top_category_budget_share == 0.8      # Crypto 800/1000
    assert rep.top2_category_budget_share == 0.9     # Crypto + next 100
