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
    TOP_TRADES_PNL_CONCENTRATION,
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
# Edge split across BOTH near-certain (extreme-confidence) buckets → fragile.
# The single-bucket confidence check misses this; the extreme-confidence check catches it.
# ---------------------------------------------------------------------------
def test_edge_split_across_confidence_extremes_is_fragile():
    # All the edge lives in the two near-certain entry buckets (0-10% and 90-100%), split so
    # NEITHER alone exceeds the single-bucket 70% threshold (~56% and ~51%) — the exact blind
    # spot the single-bucket confidence check misses. Combined ~107% > 85% → the
    # extreme-confidence check flags it. Horizon/time are spread and no single market > 50%,
    # so confidence-extremes is the ONLY fragility source (proving the new check, not another).
    trades = [
        _trade("a1", +25.0, entry=0.05, horizon_days=2, res=_week(0)),   # 0-10%
        _trade("a2", +25.0, entry=0.05, horizon_days=20, res=_week(1)),  # 0-10%
        _trade("b1", +23.0, entry=0.95, horizon_days=2, res=_week(0)),   # 90-100%
        _trade("b2", +23.0, entry=0.95, horizon_days=20, res=_week(1)),  # 90-100%
        _trade("c1", -6.0, entry=0.40, horizon_days=5, res=_week(2)),    # 25-50% middle loss
    ]
    rep = analyze_regime_slices(trades)   # no category labels → category dimension not assessed
    assert rep.total_pnl_usd == 90.0 and rep.has_positive_edge is True
    assert rep.fragile is True
    assert any("confidence-extremes" in r for r in rep.fragile_reasons)
    # the single-bucket confidence check did NOT catch it (each extreme < 70%)...
    assert not any(r.startswith("confidence:") for r in rep.fragile_reasons)
    # ...nor did the single-market check (no market holds > 50% of net PnL).
    assert rep.top_market_pnl_share is not None and rep.top_market_pnl_share < 0.5


def test_moderate_extreme_share_below_threshold_not_flagged_by_extremes():
    # A broad edge with only MODEST extreme-confidence weight (each extreme ~25%, combined
    # 50% < 85%) must NOT trip the extreme-confidence flag — the check is conservative.
    trades = [
        _trade("a", +25.0, entry=0.05, horizon_days=2, res=_week(0)),    # 0-10%   (25%)
        _trade("b", +25.0, entry=0.95, horizon_days=20, res=_week(1)),   # 90-100% (25%)
        _trade("c", +25.0, entry=0.40, horizon_days=5, res=_week(2)),    # 25-50%  (25%)
        _trade("d", +25.0, entry=0.60, horizon_days=40, res=_week(3)),   # 50-75%  (25%)
    ]
    rep = analyze_regime_slices(trades)
    assert rep.has_positive_edge is True
    assert not any("confidence-extremes" in r for r in rep.fragile_reasons)


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


def test_absent_category_map_does_not_falsely_flag_category_fragility():
    """Regression (F10 review): with NO category labels every trade falls in the single
    UNCATEGORIZED bucket, so a category-concentration / leave-one-out flag would fire on
    EVERY profitable run — a structurally false FRAGILE. A corpus that is BROAD across
    horizon/confidence/time (only category is unknown) must NOT be flagged fragile, and the
    report must disclose that category slicing was not assessed."""
    # Spread across horizons, confidence bands, and weeks so no OTHER dimension concentrates.
    trades = [
        _trade("m0", +10.0, entry=0.15, horizon_days=0.5, res=_week(0)),
        _trade("m1", +10.0, entry=0.35, horizon_days=2, res=_week(1)),
        _trade("m2", +10.0, entry=0.60, horizon_days=5, res=_week(2)),
        _trade("m3", +10.0, entry=0.85, horizon_days=20, res=_week(3)),
    ]
    rep = analyze_regime_slices(trades)  # no category_by_market_id
    assert rep.has_positive_edge is True
    assert rep.fragile is False, rep.fragile_reasons
    assert not any(r.startswith("category:") for r in rep.fragile_reasons)
    assert not any(r.startswith("leave-one-out:") for r in rep.fragile_reasons)
    assert any("no category labels supplied" in r for r in rep.fragile_reasons)


def test_supplied_category_map_still_flags_single_category():
    """The fix must NOT weaken the real signal: when labels ARE supplied and all the edge
    is one real category, it is still flagged (category + leave-one-out)."""
    trades = [_trade("c0", +50.0, res=_week(0)), _trade("c1", +50.0, res=_week(1))]
    rep = analyze_regime_slices(trades, category_by_market_id={"c0": "Crypto", "c1": "Crypto"})
    assert rep.fragile is True
    joined = " | ".join(rep.fragile_reasons)
    assert "category:" in joined and "leave-one-out" in joined


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


def test_bucket_boundaries_are_exact():
    """Pin the EXACT edge values so a future `<=`→`<` flip (or an edge reorder) is caught.
    The `<=`-chains make each edge fall into the LOWER bucket; a hair above crosses up."""
    from app.prediction_markets.regime_slice import _confidence_label, _horizon_label

    def hz(days):
        return _horizon_label(_trade("x", 1.0, horizon_days=days))

    # horizon edges (1, 3, 7, 30) — inclusive of the lower bucket
    assert hz(1.0) == "<=1d" and hz(1.0001) == "1-3d"
    assert hz(3.0) == "1-3d" and hz(3.0001) == "3-7d"
    assert hz(7.0) == "3-7d" and hz(7.0001) == "7-30d"
    assert hz(30.0) == "7-30d" and hz(30.0001) == ">30d"

    def cf(p):
        return _confidence_label(_trade("x", 1.0, entry=p))

    # confidence edges (0.1, 0.25, 0.5, 0.75, 0.9) — inclusive of the lower bucket
    assert cf(0.1) == "0-10%" and cf(0.1001) == "10-25%"
    assert cf(0.25) == "10-25%" and cf(0.2501) == "25-50%"
    assert cf(0.5) == "25-50%" and cf(0.5001) == "50-75%"
    assert cf(0.75) == "50-75%" and cf(0.7501) == "75-90%"
    assert cf(0.9) == "75-90%" and cf(0.9001) == "90-100%"


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


# ---------------------------------------------------------------------------
# ROADMAP C9 — SINGLE-OBSERVATION dominance (drop-top-k / top-trade shares).
#
# Why this axis exists, in one sentence: on corrected EXP-006b the existing top-MARKET check
# PASSED (0.4715 vs a 0.50 threshold) while dropping the TWO largest trades moved the cell from
# `significant_positive` to `indistinguishable_from_zero` — the dominant trades lived in
# DIFFERENT markets, so no per-market or per-regime share could see them.
# ---------------------------------------------------------------------------
def _spread(i):
    """Kwargs that place trade i in a DIFFERENT category/horizon/confidence/time cell, so no
    EXISTING F10 dimension concentrates and a C9 flag can only come from the new axis."""
    entries = [0.05, 0.2, 0.4, 0.6, 0.8, 0.95]
    horizons = [0.5, 2, 5, 20, 40, 5]
    return {"entry": entries[i % 6], "horizon_days": horizons[i % 6], "res": _week(i % 7)}


def test_broad_edge_survives_drop_top2():
    """A genuinely broad result: 12 equal winners, so removing the two largest still leaves a
    clearly positive edge and neither C9 trigger fires."""
    trades = [_trade(f"m{i}", +25.0, **_spread(i)) for i in range(12)]
    cat_map = {f"m{i}": f"Cat{i % 6}" for i in range(12)}
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)

    assert rep.total_pnl_usd == 300.0
    # 12 equal winners → top-5 hold exactly 5/12, comfortably under the 50% threshold.
    assert rep.top1_trade_pnl_share == round(25.0 / 300.0, 6)
    assert rep.top5_trade_pnl_share == round(125.0 / 300.0, 6)
    assert rep.top10_trade_pnl_share == round(250.0 / 300.0, 6)
    assert rep.pnl_after_drop_top1_usd == 275.0
    assert rep.pnl_after_drop_top2_usd == 250.0
    assert rep.pnl_after_drop_top5_usd == 175.0
    assert rep.survives_drop_top2 is True
    assert rep.fragile is False, rep.fragile_reasons
    assert not any(r.startswith("top-trades:") for r in rep.fragile_reasons)
    assert not any(r.startswith("drop-top-2:") for r in rep.fragile_reasons)


def _exp006b_shaped():
    """The EXP-006b shape, reduced to 14 trades: two huge winners that ARE the whole result,
    each paired with an offsetting loser in the SAME market (a scale-in / second leg), plus ten
    small winners.

    The pairing is the whole point. Per-MARKET aggregation nets +900 against -400, so the
    dominant market holds only 40% of net PnL and the existing single-market check passes —
    exactly how the real EXP-006b passed at 0.4715 — while the two dominant TRADES hold 140% of
    it. Cells are spread so no regime dimension concentrates either.

    Net: (900-400) + (850-400) + 10x30 = +1250, and drop-top-2 = 1250 - 1750 = -500."""
    trades = [
        _trade("M1", +900.0, **_spread(0)), _trade("M1", -400.0, **_spread(0)),
        _trade("M2", +850.0, **_spread(1)), _trade("M2", -400.0, **_spread(1)),
    ] + [_trade(f"s{i}", +30.0, **_spread(i + 2)) for i in range(10)]
    small_cats = ("Sports", "Weather", "Econ", "Tech", "World")
    cat_map = {"M1": "Crypto", "M2": "Politics"}
    cat_map.update({f"s{i}": small_cats[i % 5] for i in range(10)})
    return trades, cat_map


def test_two_trades_carry_everything_flagged_while_top_market_check_passes():
    """The EXACT EXP-006b shape: C9 flags it while EVERY pre-existing F10 check passes."""
    trades, cat_map = _exp006b_shaped()
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)

    assert rep.n_trades == 14
    assert rep.total_pnl_usd == 1250.0 and rep.has_positive_edge is True
    assert rep.top1_trade_pnl_share == round(900.0 / 1250.0, 6)
    assert rep.top5_trade_pnl_share == round(1840.0 / 1250.0, 6)     # > 1.0: winners > net total
    assert rep.pnl_after_drop_top1_usd == 350.0
    assert rep.pnl_after_drop_top2_usd == -500.0
    assert rep.pnl_after_drop_top5_usd == -590.0
    assert rep.survives_drop_top2 is False
    assert rep.fragile is True

    # BOTH new triggers fire...
    assert any(r.startswith("drop-top-2:") for r in rep.fragile_reasons), rep.fragile_reasons
    assert any(r.startswith("top-trades:") for r in rep.fragile_reasons), rep.fragile_reasons
    # ...and the EXISTING checks all PASS — this is a blind spot, not a duplicate signal.
    assert not any(r.startswith("single-market:") for r in rep.fragile_reasons)
    assert not any(r.startswith("category:") for r in rep.fragile_reasons)
    assert not any(r.startswith("horizon:") for r in rep.fragile_reasons)
    assert not any(r.startswith("confidence") for r in rep.fragile_reasons)
    assert not any(r.startswith("time-window:") for r in rep.fragile_reasons)
    assert not any(r.startswith("leave-one-out:") for r in rep.fragile_reasons)


def test_top_market_check_alone_would_have_passed_this_corpus():
    """Pin the blind spot numerically: the single-MARKET share sits BELOW its 0.50 threshold
    (0.40 here, 0.4715 in the real EXP-006b) on a corpus whose top two TRADES hold 1.4x the
    entire net result. No per-market or per-regime statistic can see that."""
    from app.prediction_markets.regime_slice import (
        TOP_MARKET_PNL_CONCENTRATION,
        TOP_TRADES_PNL_CONCENTRATION,
    )

    trades, cat_map = _exp006b_shaped()
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.top_market_pnl_share == round(500.0 / 1250.0, 6)
    assert rep.top_market_pnl_share < TOP_MARKET_PNL_CONCENTRATION       # the check that passed
    top2_trade_share = (900.0 + 850.0) / 1250.0
    assert top2_trade_share > 1.0
    assert rep.top5_trade_pnl_share > TOP_TRADES_PNL_CONCENTRATION       # the check that catches


def test_drop_top_k_shares_are_none_on_negative_aggregate():
    """Vacuous-on-negative: a share of a non-positive total is UNDEFINED, so it must be None —
    never 0.0, which would read as 'no concentration'. The drop-top-k PnL LEVELS are still
    defined (plain subtraction) and are reported."""
    trades = [_trade(f"m{i}", -50.0, **_spread(i)) for i in range(8)] + [
        _trade("w", +100.0, **_spread(3))
    ]
    rep = analyze_regime_slices(trades)
    assert rep.total_pnl_usd == -300.0 and rep.has_positive_edge is False
    assert rep.top1_trade_pnl_share is None
    assert rep.top5_trade_pnl_share is None
    assert rep.top10_trade_pnl_share is None
    # survival is vacuous without an edge → None, NOT False
    assert rep.survives_drop_top2 is None
    # levels remain real numbers: drop the +100 then a -50
    assert rep.pnl_after_drop_top1_usd == -400.0
    assert rep.pnl_after_drop_top2_usd == -350.0
    assert rep.fragile is False


def test_zero_aggregate_shares_are_none():
    """Exactly-zero total is the same undefined-share case as negative (0/0 is not 0.0)."""
    trades = [_trade("a", +50.0, **_spread(0)), _trade("b", -50.0, **_spread(1)),
              _trade("c", 0.0, **_spread(2))]
    rep = analyze_regime_slices(trades)
    assert rep.total_pnl_usd == 0.0
    assert rep.top1_trade_pnl_share is None and rep.top5_trade_pnl_share is None
    assert rep.survives_drop_top2 is None


def test_empty_input_has_no_trade_concentration():
    rep = analyze_regime_slices([])
    assert rep.top1_trade_pnl_share is None
    assert rep.top5_trade_pnl_share is None
    assert rep.top10_trade_pnl_share is None
    assert rep.pnl_after_drop_top1_usd == 0.0
    assert rep.pnl_after_drop_top5_usd == 0.0
    assert rep.survives_drop_top2 is None


def test_top_share_counts_only_positive_contributors():
    """A LOSING trade is not a 'top contributor'. With only 3 winners among 12 trades, the top-5
    share must sum the 3 winners and stop — never pad with the least-bad losers (which would
    understate concentration) and never with zeros."""
    trades = [
        _trade("w1", +200.0, **_spread(0)),
        _trade("w2", +150.0, **_spread(1)),
        _trade("w3", +100.0, **_spread(2)),
    ] + [_trade(f"l{i}", -10.0, **_spread(i)) for i in range(9)]
    rep = analyze_regime_slices(trades)
    assert rep.total_pnl_usd == 360.0
    assert rep.top5_trade_pnl_share == round(450.0 / 360.0, 6)   # 3 winners only, > 1.0
    assert rep.top10_trade_pnl_share == round(450.0 / 360.0, 6)  # same — no losers added


def test_drop_top_k_ties_are_deterministic():
    """Ties must not depend on input order: the SUM of the k largest values is identical under
    any permutation of equal values, so shuffling tied trades yields a byte-identical axis."""
    a = [_trade(f"t{i}", +50.0, **_spread(i)) for i in range(6)]
    b = list(reversed(a))
    ra, rb = analyze_regime_slices(a), analyze_regime_slices(b)
    for r in (ra, rb):
        assert r.pnl_after_drop_top2_usd == 200.0
        assert r.top1_trade_pnl_share == round(50.0 / 300.0, 6)
    assert (ra.top1_trade_pnl_share, ra.top5_trade_pnl_share, ra.top10_trade_pnl_share,
            ra.pnl_after_drop_top1_usd, ra.pnl_after_drop_top2_usd, ra.pnl_after_drop_top5_usd,
            ra.survives_drop_top2) == (
        rb.top1_trade_pnl_share, rb.top5_trade_pnl_share, rb.top10_trade_pnl_share,
        rb.pnl_after_drop_top1_usd, rb.pnl_after_drop_top2_usd, rb.pnl_after_drop_top5_usd,
        rb.survives_drop_top2)


def test_trade_concentration_axis_is_deterministic():
    """Same input → same report, including the new fields (frozen dataclass value equality)."""
    trades = [_trade(f"m{i}", +25.0 * (i + 1), **_spread(i)) for i in range(12)]
    cat_map = {f"m{i}": f"Cat{i % 5}" for i in range(12)}
    r1 = analyze_regime_slices(trades, category_by_market_id=cat_map)
    r2 = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert r1 == r2
    assert r1.top5_trade_pnl_share is not None


def test_top_trades_check_not_assessed_below_arithmetic_floor():
    """Honesty guard: with fewer than 10 positive-contribution trades the top-5 share EXCEEDS
    50% arithmetically no matter how even the edge is (5 of p>=... pigeonhole), so firing there
    would be a structurally guaranteed false FRAGILE — the same class of bug the
    no-category-labels guard fixes. The report must DISCLOSE non-assessment, not silently pass
    and not flag."""
    trades = [_trade(f"m{i}", +25.0, **_spread(i)) for i in range(8)]
    rep = analyze_regime_slices(trades)
    assert rep.has_positive_edge is True
    # the share is still REPORTED (it is well-defined) ...
    assert rep.top5_trade_pnl_share == round(125.0 / 200.0, 6) > 0.5
    # ... but it does not trip fragility, and the non-assessment is disclosed.
    assert not any(r.startswith("top-trades:") for r in rep.fragile_reasons)
    assert any("top-trades concentration NOT assessed" in r for r in rep.fragile_reasons)
    # drop-top-2 IS assessed at this N and passes (6 of 8 winners remain).
    assert rep.survives_drop_top2 is True
    assert rep.fragile is False, rep.fragile_reasons


def test_drop_top2_not_assessed_when_fewer_than_three_trades():
    """With n <= 2 the drop leaves nothing, so a `drop-top-2` flag would be vacuous rather than
    evidence — disclosed, not fired."""
    trades = [_trade("a", +50.0, **_spread(0)), _trade("b", +50.0, **_spread(1))]
    rep = analyze_regime_slices(trades)
    assert rep.pnl_after_drop_top2_usd == 0.0
    assert not any(r.startswith("drop-top-2:") for r in rep.fragile_reasons)
    assert any("drop-top-2 NOT assessed" in r for r in rep.fragile_reasons)


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


# ---------------------------------------------------------------------------
# C9 — the axis must be INHERITABLE by a downstream gate, not just reported
# ---------------------------------------------------------------------------
# `spike_reversal_backtest._fade_f10_ok` is a hand-rolled parallel F10 gate that reads
# individual report fields, so a new axis here does not reach it automatically. A reviewer
# demonstrated the gap on the fixture below: this module said fragile=True on the top-trades
# axis while the fade gate returned ok=True, reasons=[] — C9's exact failure mode, still open.
# These tests pin the contract that closes it: the TRIGGERED reasons and the NON-ASSESSMENT
# disclosures are published as separate data, so one source of truth feeds both.
def test_triggered_c9_reasons_are_published_for_a_downstream_gate():
    trades, cat_map = _exp006b_shaped()
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)

    assert rep.fragile is True
    # Exactly the fragility-triggering C9 reasons, and nothing else.
    assert len(rep.trade_concentration_reasons) == 2
    assert any(r.startswith("top-trades:") for r in rep.trade_concentration_reasons)
    assert any(r.startswith("drop-top-2:") for r in rep.trade_concentration_reasons)
    # Every published reason must also appear in the headline list — one source of truth.
    for r in rep.trade_concentration_reasons:
        assert r in rep.fragile_reasons
    # A triggered run has nothing to disclose as un-assessed.
    assert rep.trade_concentration_disclosures == ()


def test_non_assessment_is_published_separately_and_never_reads_as_fragility():
    """Below the arithmetic floor the top-5 flag is withheld. That must be VISIBLE to a
    downstream gate as a disclosure, and must never leak into the fragility reasons — a
    skipped check reading as a passed check is the whole hazard."""
    # 4 evenly-spread winners: below _MIN_POSITIVE_TRADES_FOR_TOP_SHARE, drop-top-2 survives.
    trades = [_trade(f"m{i}", +100.0, **_spread(i)) for i in range(4)]
    rep = analyze_regime_slices(trades)

    assert rep.fragile is False
    assert rep.trade_concentration_reasons == ()
    assert len(rep.trade_concentration_disclosures) == 1
    assert rep.trade_concentration_disclosures[0].startswith("top-trades concentration NOT assessed")
    assert rep.trade_concentration_disclosures[0] in rep.fragile_reasons


def test_a_broad_result_publishes_neither_reasons_nor_disclosures():
    trades = [_trade(f"m{i}", +100.0, **_spread(i)) for i in range(20)]
    rep = analyze_regime_slices(trades)
    assert rep.fragile is False
    assert rep.trade_concentration_reasons == ()
    assert rep.trade_concentration_disclosures == ()


def test_the_top_trades_threshold_is_calibrated_not_merely_declared():
    """Pin the CALIBRATION, not just the constant.

    An auditor's mutation testing loosened `TOP_TRADES_PNL_CONCENTRATION` from 0.50 to 0.99 and
    the entire suite stayed green — at 0.99 the real EXP-006b cell (83% of net PnL in its five
    largest trades) would STOP flagging, which is the one calibration this whole axis exists to
    establish. A threshold nothing pins is a threshold anyone can quietly move.

    Two bracketing assertions, so the constant is bounded from both sides rather than merely
    stated: it must be tight enough to catch the real EXP-006b concentration (0.8267), and
    loose enough not to fire on a genuinely broad result.
    """
    assert TOP_TRADES_PNL_CONCENTRATION < 0.8267, (
        "must be tight enough to flag the real EXP-006b cell, whose 5 largest trades hold "
        "82.67% of net PnL — the case C9 was filed to catch"
    )

    # A genuinely broad result must NOT trip it: 20 equal winners put 25% in the top 5.
    broad = [_trade(f"m{i}", +50.0, **_spread(i)) for i in range(20)]
    rep = analyze_regime_slices(broad, category_by_market_id={f"m{i}": f"C{i % 6}" for i in range(20)})
    assert rep.top5_trade_pnl_share == round(5 / 20, 6)
    assert TOP_TRADES_PNL_CONCENTRATION > rep.top5_trade_pnl_share, (
        "must be loose enough not to flag an evenly-spread 20-winner result"
    )
    assert rep.fragile is False
    assert rep.trade_concentration_reasons == ()


def test_the_real_exp006b_concentration_would_trip_the_shipped_threshold():
    """The bracket above uses a literal (0.8267); this asserts the literal is the real number,
    by rebuilding the concentration from the same shape the fixture models. Keeps the
    calibration test from drifting into an assertion about a number nobody re-derives."""
    trades, cat_map = _exp006b_shaped()
    rep = analyze_regime_slices(trades, category_by_market_id=cat_map)
    assert rep.top5_trade_pnl_share is not None
    assert rep.top5_trade_pnl_share > TOP_TRADES_PNL_CONCENTRATION
    assert any(r.startswith("top-trades:") for r in rep.trade_concentration_reasons)
