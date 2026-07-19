"""Tests for spike_reversal_backtest.py — the EXP-006 fade-the-spike backtest.

The engine must be HONEST the same way walk_forward is:
- it RECOVERS a genuine cost-net reversion edge on a mean-reverting corpus and calls it
  a validated candidate ONLY when N >= floor AND F11 significant AND F10 non-fragile;
- it reports EDGE-NOT-PROVEN on a momentum corpus (spikes continue, not revert) and on a
  too-small sample, never fabricating an edge;
- a round-trip at an unchanged price LOSES the two-way cost (the hurdle);
- it FLAGS single-market concentration (F10) — the Run 21 caution;
- it is LEAKAGE-SAFE (exit strictly after entry; future-of-horizon ticks don't change a
  trade) and DETERMINISTIC (same input -> identical trades + verdict).
"""

from __future__ import annotations

from backend.app.prediction_markets.cost_model import DEFAULT_COST_MODEL, CostModel
from backend.app.prediction_markets.spike_reversal_backtest import (
    FadeSpikeConfig,
    backtest_fade_the_spike,
)

# One market = 3 ticks: baseline, confirm (>= threshold move within the window), and a
# forward tick inside the horizon. Timestamps are staggered per market so trades spread
# across weeks (no time-window concentration in the "validated" fixture).
_STAGGER_S = 3 * 86400          # 3 days between markets
_CONFIRM_DT = 1800             # confirm 30min after baseline (inside the 3600 window)
_HORIZON_HIT_DT = 5400         # forward tick 90min after baseline (inside the 24h horizon)
_MOVE = 0.15                   # spike magnitude (> the 0.10 default threshold)
_REVERT = 0.075                # how far it reverts by the forward tick (half the move)


def _reverting_market(base_t: int, band: float, direction: str) -> list[dict]:
    """A market whose spike PARTIALLY REVERTS by the forward tick.

    ``band`` is the faded-side entry price we want (so the confidence-slice spreads across
    bands as the caller varies it). UP spike -> fade NO at price ``band`` -> YES confirm =
    ``1 - band``; DOWN spike -> fade YES at price ``band`` -> YES confirm = ``band``.
    """
    if direction == "UP":
        confirm = 1.0 - band
        baseline = confirm - _MOVE
        forward = confirm - _REVERT          # reverts DOWN toward baseline
    else:
        confirm = band
        baseline = confirm + _MOVE
        forward = confirm + _REVERT          # reverts UP toward baseline
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def _momentum_market(base_t: int, band: float, direction: str) -> list[dict]:
    """A market whose spike CONTINUES (does not revert) — the fade should LOSE."""
    if direction == "UP":
        confirm = 1.0 - band
        baseline = confirm - _MOVE
        forward = confirm + _REVERT          # keeps rising (momentum)
    else:
        confirm = band
        baseline = confirm + _MOVE
        forward = confirm - _REVERT          # keeps falling (momentum)
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


# Bands chosen to span several confidence buckets (10-25 / 25-50 / 50-75 / 75-90) so a
# recovered edge is BROAD, not concentrated in one crowd-confidence band.
_BANDS = [0.2, 0.3, 0.45, 0.6, 0.7, 0.8]
_DIRS = ["UP", "DOWN"]


def _corpus(builder, n_markets: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for i in range(n_markets):
        band = _BANDS[i % len(_BANDS)]
        direction = _DIRS[i % len(_DIRS)]
        out[f"m{i:04d}"] = builder(i * _STAGGER_S, band, direction)
    return out


# ---------------------------------------------------------------------------
# effective_sell_price — the new cost-model exit leg
# ---------------------------------------------------------------------------
def test_effective_sell_price_charges_two_way_friction():
    cm = DEFAULT_COST_MODEL
    p = 0.40
    # Selling returns LESS than the quoted price (slippage + fee against us).
    assert cm.effective_sell_price(p) < p
    # A round trip at an unchanged price is a strict LOSS (buy costs more than sell returns).
    assert cm.effective_buy_price(p) > cm.effective_sell_price(p)
    # Zero-cost model -> proceeds == price (no friction).
    free = CostModel(slippage_rate=0.0, fee_rate=0.0)
    assert free.effective_sell_price(p) == p


def test_effective_sell_price_bounds():
    cm = DEFAULT_COST_MODEL
    assert cm.effective_sell_price(0.0) == 0.0        # nothing to sell
    assert 0.0 <= cm.effective_sell_price(1.0) <= 1.0  # never above par
    # Monotone non-decreasing in price.
    assert cm.effective_sell_price(0.3) < cm.effective_sell_price(0.6)


# ---------------------------------------------------------------------------
# Recovers a real cost-net reversion edge -> VALIDATED candidate
# ---------------------------------------------------------------------------
def test_recovers_reversion_edge_validated_when_broad_and_significant():
    corpus = _corpus(_reverting_market, 120)
    res = backtest_fade_the_spike(corpus)
    assert res.n_trades == 120                      # one trade per market (cap = 1)
    assert res.total_pnl_usd > 0
    assert res.hit_rate == 1.0                      # every reversion clears costs here
    assert res.significance.verdict == "significant_positive"
    assert res.significance.total_ci_low > 0
    # The raw report flags horizon (all fade holds are <=1d — structural for a single-
    # horizon strategy), but every INFORMATIVE axis is broad, so the fade F10 gate passes.
    assert res.regime is not None
    assert all("horizon" in r or "still apply" in r for r in res.regime.fragile_reasons)
    assert res.is_validated_edge is True
    assert "VALIDATED-CANDIDATE" in res.verdict


# ---------------------------------------------------------------------------
# Momentum corpus -> the fade LOSES -> EDGE-NOT-PROVEN
# ---------------------------------------------------------------------------
def test_momentum_corpus_is_not_an_edge():
    corpus = _corpus(_momentum_market, 120)
    res = backtest_fade_the_spike(corpus)
    assert res.n_trades == 120
    assert res.total_pnl_usd < 0                    # fading momentum loses
    assert res.significance.verdict != "significant_positive"
    assert res.is_validated_edge is False
    assert "EDGE-NOT-PROVEN" in res.verdict


# ---------------------------------------------------------------------------
# Cost hurdle: a round-trip at an UNCHANGED price loses the two-way cost
# ---------------------------------------------------------------------------
def test_round_trip_unchanged_price_loses_costs():
    # Spike then return to EXACTLY the confirm price by the forward tick: zero gross move,
    # so the only PnL is the (negative) two-way cost.
    def _flat(base_t, band, direction):
        confirm = (1.0 - band) if direction == "UP" else band
        baseline = confirm - _MOVE if direction == "UP" else confirm + _MOVE
        return [
            {"t": base_t, "p": round(baseline, 4)},
            {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
            {"t": base_t + _HORIZON_HIT_DT, "p": round(confirm, 4)},  # back to confirm
        ]

    res = backtest_fade_the_spike(_corpus(_flat, 20))
    assert res.n_trades == 20
    assert res.total_pnl_usd < 0
    assert all(t.pnl_usd < 0 for t in res.trades)


# ---------------------------------------------------------------------------
# F10 single-market concentration is FLAGGED (Run 21 caution)
# ---------------------------------------------------------------------------
def test_single_market_concentration_is_flagged_fragile():
    # One market reverts HUGELY (big PnL), two barely (tiny PnL): the big one dominates.
    big = [
        {"t": 0, "p": 0.50},
        {"t": _CONFIRM_DT, "p": 0.80},              # +0.30 UP spike
        {"t": _HORIZON_HIT_DT, "p": 0.52},          # reverts almost fully -> large fade PnL
    ]

    def _tiny(base_t):
        return [
            {"t": base_t, "p": 0.50},
            {"t": base_t + _CONFIRM_DT, "p": 0.62},  # +0.12 UP spike (just over threshold)
            {"t": base_t + _HORIZON_HIT_DT, "p": 0.605},  # reverts a sliver -> tiny PnL
        ]

    corpus = {"big": big, "t1": _tiny(_STAGGER_S), "t2": _tiny(2 * _STAGGER_S)}
    res = backtest_fade_the_spike(corpus)
    assert res.total_pnl_usd > 0                    # there IS a positive aggregate...
    assert res.regime is not None and res.regime.fragile  # ...but it's concentrated
    assert res.regime.top_market_pnl_share is not None and res.regime.top_market_pnl_share > 0.5
    assert res.is_validated_edge is False           # concentration blocks validation


# ---------------------------------------------------------------------------
# Sufficient-N gate: a small positive sample is NOT a validated edge
# ---------------------------------------------------------------------------
def test_small_sample_is_edge_not_proven_even_if_positive():
    res = backtest_fade_the_spike(_corpus(_reverting_market, 12))
    assert res.n_trades == 12
    assert res.total_pnl_usd > 0                     # positive point estimate...
    assert res.significance.verdict == "insufficient_data"  # ...but below the floor
    assert res.is_validated_edge is False


# ---------------------------------------------------------------------------
# Per-market trade cap (concentration cap by construction)
# ---------------------------------------------------------------------------
def test_max_trades_per_market_cap():
    # A market with TWO distinct spikes (up-leg then a threshold retrace down-leg).
    multi = [
        {"t": 0, "p": 0.50},
        {"t": 1000, "p": 0.65},        # UP spike #1 confirms
        {"t": 2000, "p": 0.50},        # >=0.10 retrace -> closes #1, opens DOWN spike #2
        {"t": 3000, "p": 0.55},        # forward tick for both
        {"t": 90000, "p": 0.55},       # ensure a labelable forward tick within horizon
    ]
    corpus = {"multi": multi}
    one = backtest_fade_the_spike(corpus, config=FadeSpikeConfig(max_trades_per_market=1))
    assert one.n_spikes_detected >= 2               # detector saw both legs
    assert one.n_trades == 1                         # but only one traded (cap)
    two = backtest_fade_the_spike(corpus, config=FadeSpikeConfig(max_trades_per_market=2))
    assert two.n_trades >= 1 and two.n_trades <= 2   # cap raised -> may take more
    assert two.n_trades >= one.n_trades


# ---------------------------------------------------------------------------
# Leakage safety + determinism
# ---------------------------------------------------------------------------
def test_exit_strictly_after_entry_and_no_lookahead():
    corpus = _corpus(_reverting_market, 30)
    res = backtest_fade_the_spike(corpus)
    assert res.n_trades == 30
    for t in res.trades:
        assert t.exit_time > t.confirm_time          # exit is strictly forward

    # Appending ticks BEYOND the horizon must not change any trade (causal / forward-bounded).
    horizon = FadeSpikeConfig().horizon_seconds
    poisoned = {}
    for mid, ticks in corpus.items():
        confirm_t = ticks[1]["t"]
        poisoned[mid] = list(ticks) + [
            {"t": confirm_t + horizon + 10_000, "p": 0.99}  # far-future spike, must be ignored
        ]
    res2 = backtest_fade_the_spike(poisoned)
    assert res2.total_pnl_usd == res.total_pnl_usd
    assert [t.pnl_usd for t in res2.trades] == [t.pnl_usd for t in res.trades]


def test_deterministic():
    corpus = _corpus(_reverting_market, 50)
    a = backtest_fade_the_spike(corpus)
    b = backtest_fade_the_spike(corpus)
    assert a.total_pnl_usd == b.total_pnl_usd
    assert a.verdict == b.verdict
    assert [t.pnl_usd for t in a.trades] == [t.pnl_usd for t in b.trades]
    assert a.significance.total_ci_low == b.significance.total_ci_low


# ---------------------------------------------------------------------------
# Empty / unlabelable corpora degrade honestly
# ---------------------------------------------------------------------------
def test_empty_corpus_is_honest_null():
    res = backtest_fade_the_spike({})
    assert res.n_trades == 0
    assert res.total_pnl_usd == 0.0
    assert res.regime is None
    assert res.is_validated_edge is False
    assert "EDGE-NOT-PROVEN" in res.verdict


def test_spike_with_no_forward_tick_is_dropped_not_fabricated():
    # A spike confirms but there is NO tick after it within the horizon -> unlabelable.
    corpus = {
        "m": [
            {"t": 0, "p": 0.50},
            {"t": _CONFIRM_DT, "p": 0.65},   # spike confirms; no later tick at all
        ]
    }
    res = backtest_fade_the_spike(corpus)
    assert res.n_spikes_detected == 1
    assert res.n_spikes_unlabelable == 1
    assert res.n_trades == 0                  # dropped, never filled at a fabricated price


def test_config_validation_rejects_bad_params():
    import pytest

    for bad in (
        {"threshold": 0.0},
        {"window_seconds": 0},
        {"horizon_seconds": -1},
        {"budget_per_trade_usd": 0.0},
        {"max_trades_per_market": 0},
        {"min_trades_for_edge": 0},
    ):
        with pytest.raises(ValueError):
            FadeSpikeConfig(**bad)
