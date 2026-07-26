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
    DEFAULT_MAGNITUDE_STRATUM_EDGES,
    FadeSpikeConfig,
    MagnitudeStratum,
    backtest_fade_the_spike,
    stratify_by_magnitude,
)

# One market = 3 ticks: baseline, confirm (>= threshold move within the window), and a
# forward tick inside the horizon. Timestamps are staggered per market so trades spread
# across weeks (no time-window concentration in the "validated" fixture).
_STAGGER_S = 3 * 86400          # 3 days between markets (> the 24h series span)
_CONFIRM_DT = 1800             # confirm 30min after baseline (inside the 3600 window)
# Forward tick placed AT the 24h horizon measured from CONFIRM (not 90min after baseline).
# The engine now requires the series to actually COVER the horizon before it will book a
# trade (`require_full_horizon`, added after an adversarial audit found end-of-data exits
# booking settlement-adjacent prices as "reversion"). A fixture that stops 90 minutes in
# no longer produces trades — and a fixture that silently produces zero trades pins nothing.
_HORIZON_HIT_DT = _CONFIRM_DT + 86400
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
        # Covers a SWEPT horizon up to 3 days. Out of range (and inert) for the default
        # 24h horizon, but without it a swept-horizon test yields ZERO trades under
        # `require_full_horizon` and would silently assert nothing.
        {"t": base_t + _CONFIRM_DT + 3 * 86400, "p": round(forward, 4)},
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
        # Covers a SWEPT horizon up to 3 days. Out of range (and inert) for the default
        # 24h horizon, but without it a swept-horizon test yields ZERO trades under
        # `require_full_horizon` and would silently assert nothing.
        {"t": base_t + _CONFIRM_DT + 3 * 86400, "p": round(forward, 4)},
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
        # A tick AT each spike's own 24h horizon end (confirm 1000 -> 87400,
        # confirm 2000 -> 88400) so `require_full_horizon` can label both legs.
        {"t": 87400, "p": 0.55},
        {"t": 88400, "p": 0.55},
    ]
    corpus = {"multi": multi}
    one = backtest_fade_the_spike(corpus, config=FadeSpikeConfig(max_trades_per_market=1))
    assert one.n_spikes_detected >= 2               # detector saw both legs
    assert one.n_trades == 1                         # but only one traded (cap)
    two = backtest_fade_the_spike(corpus, config=FadeSpikeConfig(max_trades_per_market=2))
    assert two.n_trades >= 1 and two.n_trades <= 2   # cap raised -> may take more
    assert two.n_trades >= one.n_trades


# ---------------------------------------------------------------------------
# Hit-rate gate: a positive, significant total at a SUB-50% hit-rate is NOT validated
# ---------------------------------------------------------------------------
def _big_revert(base_t: int, band: float, direction: str) -> list[dict]:
    """A LARGE reversion (big fade win)."""
    move, revert = 0.15, 0.12
    if direction == "UP":
        confirm = 1.0 - band
        baseline, forward = confirm - move, confirm - revert
    else:
        confirm = band
        baseline, forward = confirm + move, confirm + revert
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def _small_momentum(base_t: int, band: float, direction: str) -> list[dict]:
    """A small continuation (small fade loss)."""
    move, cont = 0.15, 0.02
    if direction == "UP":
        confirm = 1.0 - band
        baseline, forward = confirm - move, confirm + cont
    else:
        confirm = band
        baseline, forward = confirm + move, confirm - cont
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def test_sub_50pct_hit_rate_is_not_validated_even_if_significant():
    # 50 big winners + 70 small losers: net POSITIVE and F11-significant, but hit-rate < 50%.
    corpus: dict[str, list[dict]] = {}
    for k in range(50):
        corpus[f"w{k:04d}"] = _big_revert(k * _STAGGER_S, _BANDS[k % len(_BANDS)], _DIRS[k % 2])
    for k in range(70):
        corpus[f"l{k:04d}"] = _small_momentum((50 + k) * _STAGGER_S, _BANDS[k % len(_BANDS)], _DIRS[k % 2])
    res = backtest_fade_the_spike(corpus)
    assert res.n_trades == 120
    assert res.total_pnl_usd > 0                       # positive aggregate
    assert res.hit_rate is not None and res.hit_rate < 0.5
    assert res.significance.verdict == "significant_positive"   # and F11-significant
    assert res.is_validated_edge is False              # ...but the hit-rate gate blocks it
    assert "hit-rate" in res.verdict


# ---------------------------------------------------------------------------
# Horizon check RE-ENGAGES when the horizon is swept above one day
# ---------------------------------------------------------------------------
def test_horizon_check_reengages_when_horizon_swept_above_one_day():
    corpus = _corpus(_reverting_market, 120)
    # Default (<=24h) horizon: horizon axis excluded -> validates.
    assert backtest_fade_the_spike(corpus).is_validated_edge is True
    # Sweep the horizon to 3 days: holds are now assessed on the horizon axis, and since all
    # forward ticks are ~1.5h out they ALL fall in the <=1d band -> horizon-concentrated ->
    # the (now-informative) horizon check fires and blocks validation.
    cfg = FadeSpikeConfig(horizon_seconds=3 * 86400)
    res = backtest_fade_the_spike(corpus, config=cfg)
    assert res.is_validated_edge is False
    assert "horizon" in res.verdict


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
    # Strata still partition into the four report bands, every one empty and NON-fabricated.
    assert len(res.strata) == len(DEFAULT_MAGNITUDE_STRATUM_EDGES) + 1
    assert all(
        s.n_trades == 0
        and s.total_pnl_usd == 0.0
        and s.hit_rate is None
        and s.mean_reversal_fraction is None
        and s.mean_magnitude is None
        for s in res.strata
    )
    assert res.size_robustness.startswith("UNASSESSED")   # no trades -> unassessable, disclosed


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
        {"magnitude_stratum_edges": ()},              # empty
        {"magnitude_stratum_edges": (0.25, 0.15)},    # not increasing
        {"magnitude_stratum_edges": (0.0, 0.3)},      # <= 0
        {"magnitude_stratum_edges": (0.3, 1.0)},      # >= 1
    ):
        with pytest.raises(ValueError):
            FadeSpikeConfig(**bad)


# ===========================================================================
# EXP-006 magnitude / salience stratification (Run 21 N=1 caution made auditable)
# The size-robustness GATE is config-independent (rank-based) + significance-aware.
# ===========================================================================
def test_magnitude_strata_reported_and_partition_all_trades():
    # The broad reverting corpus has a UNIFORM spike size (_MOVE=0.15) — every trade lands in
    # exactly ONE magnitude report band. Strata still report, partition every trade, sums match.
    res = backtest_fade_the_spike(_corpus(_reverting_market, 120))
    assert res.n_trades == 120
    assert sum(s.n_trades for s in res.strata) == res.n_trades
    assert round(sum(s.total_pnl_usd for s in res.strata), 4) == round(res.total_pnl_usd, 4)
    populated = [s for s in res.strata if s.n_trades > 0]
    assert len(populated) == 1                          # uniform 0.15 magnitude -> one band
    for s in res.strata:                                # empty bands never fabricate a mean
        if s.n_trades == 0:
            assert s.hit_rate is None and s.mean_reversal_fraction is None


def test_no_large_spikes_size_robustness_abstains_with_disclosure():
    # This broad reverting corpus has only 0.15 moves — all BELOW the fixed large-spike cut (0.25),
    # so there is no biggest-spike regime to test -> ABSTAIN-BENIGN, but DISCLOSE it (not a silent
    # pass). The genuinely-broad edge still validates, and the verdict explicitly says UNASSESSED.
    res = backtest_fade_the_spike(_corpus(_reverting_market, 120))
    assert res.is_validated_edge is True
    assert res.size_robustness.startswith("UNASSESSED")
    assert "no large spikes" in res.size_robustness
    assert "UNASSESSED" in res.verdict                  # disclosed in the human verdict too


# Band-parametrized builders so winners AND losers spread across confidence buckets (keeps the
# STANDARD F10 axes non-fragile, isolating the size-robustness gate as the sole driver below).
def _small_revert_b(base_t: int, band: float, direction: str) -> list[dict]:
    """A SMALL spike (~0.12 |move|) that reverts -> fade WINS. `band` sets the faded-side price."""
    move, revert = 0.12, 0.08
    if direction == "UP":
        confirm, baseline, forward = 1.0 - band, (1.0 - band) - move, (1.0 - band) - revert
    else:
        confirm, baseline, forward = band, band + move, band + revert
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def _large_persist_b(base_t: int, band: float, direction: str) -> list[dict]:
    """A LARGE spike (~0.30 |move|) that CONTINUES -> fade LOSES. `band` sets the faded-side price
    (kept in [0.35, 0.65] so baseline stays in range for the big move)."""
    move, cont = 0.30, 0.05
    if direction == "UP":
        confirm, baseline, forward = 1.0 - band, (1.0 - band) - move, (1.0 - band) + cont
    else:
        confirm, baseline, forward = band, band + move, band - cont
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


_LARGE_BANDS = [0.2, 0.35, 0.5, 0.65]       # wide spread across confidence buckets; large-move safe


def _large_flat_b(base_t: int, band: float, direction: str) -> list[dict]:
    """A LARGE spike (~0.30 |move|) whose price HOLDS the spike level (forward == confirm) — the
    fade loses only the round-trip COST (a small loss), same magnitude as the reverter."""
    move = 0.30
    if direction == "UP":
        confirm, baseline, forward = 1.0 - band, (1.0 - band) - move, 1.0 - band
    else:
        confirm, baseline, forward = band, band + move, band
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def _mixed_corpus(n_small: int, n_large: int, large_builder) -> dict[str, list[dict]]:
    corpus: dict[str, list[dict]] = {}
    for k in range(n_small):
        corpus[f"s{k:04d}"] = _small_revert_b(k * _STAGGER_S, _LARGE_BANDS[k % 4], _DIRS[k % 2])
    for k in range(n_large):
        corpus[f"L{k:04d}"] = large_builder((n_small + k) * _STAGGER_S, _LARGE_BANDS[k % 4], _DIRS[k % 2])
    return corpus


def test_large_spike_persist_regime_flags_size_fragility():
    # 70 small revert-winners + 50 large persist-losers: positive AGGREGATE, but the whole edge is
    # a small-spike artifact — the LARGEST-magnitude cohort loses. The config-independent,
    # significance-aware size-robustness gate must catch it and BLOCK validation.
    res = backtest_fade_the_spike(_mixed_corpus(70, 50, _large_persist_b))
    assert res.n_trades == 120
    assert res.total_pnl_usd > 0                            # positive aggregate...
    assert res.size_robustness.startswith("FRAGILE")       # ...largest spikes significantly negative
    assert res.is_validated_edge is False
    assert "SIGNIFICANTLY NEGATIVE" in res.verdict


def test_size_robustness_is_config_independent_no_edges_loophole():
    # THE loophole an auditor proved: the OLD edges-driven check could be disabled by choosing
    # report edges that collapse all magnitudes into one bin. The gate is now RANK-based, so the
    # SAME size-fragile corpus is flagged under default edges AND under collapse-everything edges.
    corpus = _mixed_corpus(70, 50, _large_persist_b)
    default_res = backtest_fade_the_spike(corpus)
    collapse_cfg = FadeSpikeConfig(magnitude_stratum_edges=(0.90, 0.95, 0.99))  # bins nothing apart
    collapse_res = backtest_fade_the_spike(corpus, config=collapse_cfg)
    # Report bands differ, but the GATE verdict is identical — edges cannot turn it off.
    assert default_res.is_validated_edge is False
    assert collapse_res.is_validated_edge is False
    assert default_res.size_robustness.startswith("FRAGILE")
    assert collapse_res.size_robustness.startswith("FRAGILE")


def test_size_robustness_is_the_sole_validation_blocker():
    # N>=floor, F11 significant_positive, hit-rate>50%, and every STANDARD F10 axis broad (bands +
    # times + distinct markets spread; horizon is structurally excluded) — the ONLY thing that flips
    # is_validated to False is the size-robustness gate. This isolates the verdict-flipping path (an
    # over-determined test could pass even if the magnitude reason never reached is_validated).
    res = backtest_fade_the_spike(_mixed_corpus(90, 45, _large_persist_b))
    assert res.significance.verdict == "significant_positive"   # F11 passes
    assert res.hit_rate is not None and res.hit_rate > 0.5      # hit-rate passes
    assert res.size_robustness.startswith("FRAGILE")           # size-robustness is the blocker
    assert res.is_validated_edge is False
    assert "SIGNIFICANTLY NEGATIVE" in res.verdict
    # Sole driver: NONE of the standard F10 fragility axes appears in the verdict — only size.
    for other in ("confidence:", "time-window:", "single-market:", "category:", "confidence-extremes:"):
        assert other not in res.verdict


def _large_revert_b(base_t: int, band: float, direction: str) -> list[dict]:
    """A LARGE spike (~0.30 |move|) that REVERTS -> fade WINS (same magnitude as the flat loser).
    For a DOWN spike, reverting means the price moves back UP toward baseline (forward > confirm)."""
    move, revert = 0.30, 0.12
    if direction == "UP":
        confirm, baseline, forward = 1.0 - band, (1.0 - band) - move, (1.0 - band) - revert
    else:
        confirm, baseline, forward = band, band + move, band + revert
    return [
        {"t": base_t, "p": round(baseline, 4)},
        {"t": base_t + _CONFIRM_DT, "p": round(confirm, 4)},
        {"t": base_t + _HORIZON_HIT_DT, "p": round(forward, 4)},
    ]


def test_size_robustness_flags_minority_persist_tail():
    # THE audit counterexamples: a LOSING huge-spike tail — at ANY size, including a small MINORITY
    # (5-13 events) that a fixed-count/fraction cohort diluted with small-spike winners until it read
    # insignificant and PASSED — must NEVER ship a green VALIDATED-CANDIDATE. The magnitude-defined
    # PURE large-spike set catches it at every tail size: >= floor via significance, < floor via the
    # net-negative sign (underpowered but disclosed + blocking). Every huge spike here persists/loses;
    # the aggregate is positive (a small-spike artifact).
    for n_small, n_huge in [(100, 5), (100, 8), (100, 10), (100, 13),
                            (90, 15), (95, 20), (100, 25), (110, 30)]:
        res = backtest_fade_the_spike(_mixed_corpus(n_small, n_huge, _large_persist_b))
        assert res.total_pnl_usd > 0                       # positive aggregate (small-spike artifact)
        assert res.significance.verdict == "significant_positive"
        assert res.size_robustness.startswith("FRAGILE"), (n_small, n_huge, res.size_robustness)
        assert res.is_validated_edge is False              # the losing tail blocks it — no dilution


def test_well_sampled_but_insignificant_large_cohort_not_flagged():
    # The largest-spike cohort is well-sampled but its fade is NOT significantly negative:
    # same-magnitude large spikes ALTERNATE reverter (win) / flat holder (small cost loss), so the
    # top-MIN_STRATUM cohort is a ~50/50 mix straddling zero. A bare sign test would fire on the
    # losing names; the significance-aware gate must NOT flag it (the R2 variance-false-flag fix).
    corpus: dict[str, list[dict]] = {}
    for k in range(60):
        corpus[f"s{k:04d}"] = _small_revert_b(k * _STAGGER_S, _LARGE_BANDS[k % 4], _DIRS[k % 2])
    for k in range(40):        # same magnitude (0.30); even -> revert/win, odd -> flat/cost-loss
        builder = _large_revert_b if k % 2 == 0 else _large_flat_b
        corpus[f"L{k:04d}"] = builder((60 + k) * _STAGGER_S, _LARGE_BANDS[k % 4], _DIRS[k % 2])
    res = backtest_fade_the_spike(corpus)
    assert not res.size_robustness.startswith("FRAGILE")   # mixed large cohort not flagged
    assert "not significantly negative" in res.size_robustness
    assert "SIGNIFICANTLY NEGATIVE" not in res.verdict


def test_stratify_by_magnitude_is_pure_boundary_correct_and_validates_edges():
    import pytest

    res = backtest_fade_the_spike(_mixed_corpus(40, 40, _large_persist_b))
    a = stratify_by_magnitude(res.trades)
    b = stratify_by_magnitude(res.trades)
    assert a == b                                       # pure / deterministic
    assert all(isinstance(s, MagnitudeStratum) for s in a)
    assert len(a) == len(DEFAULT_MAGNITUDE_STRATUM_EDGES) + 1
    assert sum(s.n_trades for s in a) == res.n_trades
    for s in a:
        assert s.lo >= 0.0
        if s.hi is not None:
            assert s.hi > s.lo
    # The public helper validates its own edges (never silent dead/overlapping bands).
    for bad in [(), (0.25, 0.15), (0.0, 0.3), (0.3, 1.0)]:
        with pytest.raises(ValueError):
            stratify_by_magnitude(res.trades, edges=bad)


def test_spike_magnitude_recorded_on_every_trade():
    res = backtest_fade_the_spike(_corpus(_reverting_market, 10))
    assert res.n_trades == 10
    # _MOVE is the full move; peak == confirm here (forward reverts), so magnitude ~ _MOVE.
    for t in res.trades:
        assert t.spike_magnitude > 0.0
        assert abs(t.spike_magnitude - _MOVE) < 1e-6


def test_engine_refuses_a_trade_whose_horizon_is_not_covered_by_data():
    """ENGINE-LEVEL coverage for `require_full_horizon` (a re-review proved the call site
    at `spike_reversal_backtest` had NONE: flipping it to False left all 38 tests green,
    so the actual production wiring that fixed the leakage was untested).

    A market whose ticks stop shortly after the spike must produce NO trade. Before the
    guard it produced one, exiting at the last available tick — which on a resolved market
    sits adjacent to settlement, so the trade booked the terminal pinned quote as
    "reversion". That path carried 39% of EXP-006b's raw net PnL.
    """
    truncated = {
        "m0": [
            {"t": 0, "p": 0.50},
            {"t": 1800, "p": 0.65},     # spike confirms
            {"t": 5400, "p": 0.9995},   # last tick, ~1h later — a settlement-shaped print
        ]
    }
    res = backtest_fade_the_spike(truncated)
    assert res.n_spikes_detected >= 1, "fixture must detect a spike, else this pins nothing"
    assert res.n_trades == 0, (
        "the engine must REFUSE a trade whose 24h horizon is not covered by data — "
        "exiting at the last available tick books a settlement-adjacent price as reversion"
    )


def test_engine_takes_the_trade_once_the_horizon_is_covered():
    """The complement, so the guard cannot pass by simply refusing everything."""
    covered = {
        "m0": [
            {"t": 0, "p": 0.50},
            {"t": 1800, "p": 0.65},
            {"t": 5400, "p": 0.60},
            {"t": 1800 + 86400, "p": 0.58},   # a tick AT the horizon
        ]
    }
    res = backtest_fade_the_spike(covered)
    assert res.n_trades == 1
