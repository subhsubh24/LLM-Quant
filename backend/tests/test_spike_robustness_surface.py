"""Tests for the EXP-006 config robustness surface (spike_robustness_surface).

These pin the honesty-load-bearing behaviour: determinism, that the surface only tabulates
(never overrides) the fade engine's own verdict, that it NEVER claims an edge at the family
level (in-sample), and that the pre-registered grid is what it says it is.
"""

from __future__ import annotations

import math

import pytest

from backend.app.prediction_markets.spike_detection import (
    DEFAULT_REVERSAL_HORIZON_SECONDS,
    DEFAULT_SPIKE_THRESHOLD,
    DEFAULT_WINDOW_SECONDS,
)
from backend.app.prediction_markets.spike_reversal_backtest import (
    FadeSpikeConfig,
    backtest_fade_the_spike,
)
from backend.app.prediction_markets.spike_robustness_surface import (
    PRE_REGISTERED_HORIZONS_SECONDS,
    PRE_REGISTERED_THRESHOLDS,
    PRE_REGISTERED_WINDOWS_SECONDS,
    RobustnessSurface,
    SurfaceCell,
    run_robustness_surface,
    summarize,
)


def _corpus(n_markets: int, *, move: float, revert: float, direction: str = "UP"):
    """A deterministic tick corpus: baseline → confirm (a `move` spike) → forward (reverts
    `revert` toward baseline, or continues if `revert` is negative). Staggered in time so
    each market's single spike is independent. Detectable at the default 0.10 threshold and
    labelable within the default 24h horizon."""
    confirm_dt, forward_dt, stagger = 1800, 5400, 3 * 86400
    out = {}
    for i in range(n_markets):
        base = i * stagger
        if direction == "UP":
            confirm = 0.55
            baseline = confirm - move
            forward = confirm - revert
        else:
            confirm = 0.45
            baseline = confirm + move
            forward = confirm + revert
        out[f"m{i:04d}"] = [
            {"t": base, "p": round(baseline, 4)},
            {"t": base + confirm_dt, "p": round(confirm, 4)},
            {"t": base + forward_dt, "p": round(forward, 4)},
        ]
    return out


def _broad_reverting_corpus(n_markets: int = 140):
    """A broad, deterministic corpus whose spikes PARTIALLY REVERT beyond round-trip cost — a
    known injected edge the engine recovers as VALIDATED at the default cell. Bands + directions
    are varied so the edge is broad (spread across confidence bands, weeks, both directions) and
    the moderate 0.15 magnitude (< the 0.25 large-spike cut) keeps the size-robustness screen from
    flagging it. Mirrors run_spike_reversal's synthetic demo."""
    bands = [0.2, 0.3, 0.45, 0.6, 0.7, 0.8]
    dirs = ["UP", "DOWN"]
    move, revert = 0.15, 0.075
    stagger, confirm_dt, forward_dt = 3 * 86400, 1800, 5400
    out = {}
    for i in range(n_markets):
        band = bands[i % len(bands)]
        direction = dirs[i % len(dirs)]
        base = i * stagger
        if direction == "UP":
            confirm = 1.0 - band
            baseline = confirm - move
            forward = confirm - revert
        else:
            confirm = band
            baseline = confirm + move
            forward = confirm + revert
        out[f"syn{i:04d}"] = [
            {"t": base, "p": round(baseline, 4)},
            {"t": base + confirm_dt, "p": round(confirm, 4)},
            {"t": base + forward_dt, "p": round(forward, 4)},
        ] + [
            # A forward tick at EACH swept horizon — `require_full_horizon` needs the series
            # to cover the horizon before a trade is booked. Same price at each, so the exit
            # price is unchanged; without these the surface produces zero trades everywhere.
            {"t": base + confirm_dt + h, "p": round(forward, 4)}
            for h in PRE_REGISTERED_HORIZONS_SECONDS
        ]
    return out


def test_default_grid_size_and_membership():
    surface = run_robustness_surface(_corpus(5, move=0.15, revert=0.075))
    assert surface.k_cells == (
        len(PRE_REGISTERED_THRESHOLDS)
        * len(PRE_REGISTERED_WINDOWS_SECONDS)
        * len(PRE_REGISTERED_HORIZONS_SECONDS)
    )
    assert surface.k_cells == 60
    # Exactly one cell is the pre-registered DEFAULT (0.10 / 1h / 24h).
    defaults = [c for c in surface.cells if c.is_default]
    assert len(defaults) == 1
    dc = defaults[0]
    assert dc.threshold == DEFAULT_SPIKE_THRESHOLD
    assert dc.window_seconds == DEFAULT_WINDOW_SECONDS
    assert dc.horizon_seconds == DEFAULT_REVERSAL_HORIZON_SECONDS
    assert surface.default_cell == dc


def test_all_horizons_at_or_below_default():
    # Load-bearing for a fair F10 (the horizon-axis exclusion is only legitimate ≤ 1 day).
    assert all(h <= DEFAULT_REVERSAL_HORIZON_SECONDS for h in PRE_REGISTERED_HORIZONS_SECONDS)


def test_cells_in_fixed_sorted_order():
    surface = run_robustness_surface(_corpus(4, move=0.15, revert=0.05))
    keys = [(c.threshold, c.window_seconds, c.horizon_seconds) for c in surface.cells]
    assert keys == sorted(keys)


def test_deterministic():
    corpus = _corpus(8, move=0.18, revert=0.09)
    a = run_robustness_surface(corpus)
    b = run_robustness_surface(corpus)
    assert a.cells == b.cells
    assert a.family_verdict == b.family_verdict
    assert a.n_validated == b.n_validated
    assert a.chance_green_expectation == b.chance_green_expectation


def test_default_cell_matches_standalone_engine():
    # The surface must TABULATE the engine verbatim, never re-derive. The default cell must
    # equal a direct backtest_fade_the_spike(default config) call on the same corpus.
    corpus = _corpus(12, move=0.2, revert=0.1)
    surface = run_robustness_surface(corpus)
    dc = surface.default_cell
    assert dc is not None
    res = backtest_fade_the_spike(corpus, config=FadeSpikeConfig())
    assert dc.n_trades == res.n_trades
    assert dc.total_pnl_usd == res.total_pnl_usd
    assert dc.hit_rate == res.hit_rate
    assert dc.f11_verdict == res.significance.verdict
    assert dc.is_validated_edge == res.is_validated_edge


def test_momentum_corpus_is_family_null_strong():
    # Spikes that COMPOUND (negative revert) never revert → zero validated cells → strong null.
    surface = run_robustness_surface(_corpus(15, move=0.2, revert=-0.1))
    assert surface.n_validated == 0
    assert surface.validated_cells == ()
    assert surface.family_verdict == "FAMILY-NULL-STRONG"


def test_never_claims_edge_at_family_level():
    # Whatever the corpus, the family verdict is one of the three honest strings and there is
    # NO revenue / validated-edge field on the surface object itself.
    surface = run_robustness_surface(_corpus(10, move=0.15, revert=0.1))
    assert surface.family_verdict in {
        "FAMILY-NULL-STRONG",
        "FAMILY-NULL-WITHIN-CHANCE",
        "HYPOTHESES-FLAGGED-NOT-AN-EDGE",
    }
    for banned in ("weekly_pnl_paper", "total_trades", "arr_year1", "is_validated_edge"):
        assert not hasattr(surface, banned)
    # A validated cell (if any) is only ever surfaced as a HYPOTHESIS, never an edge claim.
    if surface.n_validated > 0:
        assert surface.family_verdict != "FAMILY-NULL-STRONG"


def test_within_chance_when_validated_not_beyond_chance():
    # Land the WITHIN-CHANCE branch deterministically: a 1-cell grid over a broad reverting
    # corpus validates its single cell (N>=100, F11 significant_positive, F10 non-fragile,
    # hit>50%), so n_validated=1, chance_ceiling=ceil(1*alpha/2)=1, 1<=1 => WITHIN-CHANCE.
    surface = run_robustness_surface(
        _broad_reverting_corpus(140),
        thresholds=[0.10],
        windows_seconds=[3600],
        horizons_seconds=[86400],
    )
    assert surface.k_cells == 1
    assert surface.n_validated == 1, surface.cells[0]
    assert math.ceil(surface.chance_green_expectation) == 1
    assert surface.family_verdict == "FAMILY-NULL-WITHIN-CHANCE"
    # And the validated cell is a HYPOTHESIS only — the summary flags it, never claims an edge.
    assert "NOT an edge" in summarize(surface)


def test_validated_cell_is_never_gate_fragile():
    # The gate F10 column can never contradict validity: a validated cell is F10 non-fragile.
    surface = run_robustness_surface(
        _broad_reverting_corpus(140),
        thresholds=[0.10],
        windows_seconds=[3600],
        horizons_seconds=[86400],
    )
    for c in surface.cells:
        if c.is_validated_edge:
            assert c.f10_gate_fragile is False


def test_chance_expectation_is_k_times_half_alpha():
    # Descriptor contract: chance ≈ K · alpha/2. Recover alpha from a single engine run.
    corpus = _corpus(5, move=0.15, revert=0.05)
    surface = run_robustness_surface(corpus)
    res = backtest_fade_the_spike(corpus, config=FadeSpikeConfig())
    expected = round(surface.k_cells * (res.significance.alpha / 2.0), 4)
    assert surface.chance_green_expectation == expected


def test_categories_engage_f10_gate_category_axis():
    # The GATE F10 engages the category axis only when labels are supplied. Put ALL markets in
    # ONE category over a broad reverting corpus: with categories, a positive cell picks up a
    # "category:" gate-fragility reason (100% in one category > 70%); without, the category axis
    # is silently skipped so no such reason appears.
    corpus = _broad_reverting_corpus(120)
    cats = {mid: "OnlyCat" for mid in corpus}
    with_cats = run_robustness_surface(corpus, category_by_market=cats)
    without = run_robustness_surface(corpus)
    with_reasons = " ".join(r for c in with_cats.cells for r in c.f10_gate_reasons)
    without_reasons = " ".join(r for c in without.cells for r in c.f10_gate_reasons)
    assert "category:" in with_reasons
    assert "category:" not in without_reasons


def test_custom_small_grid():
    corpus = _corpus(6, move=0.18, revert=0.09)
    surface = run_robustness_surface(
        corpus,
        thresholds=[0.10],
        windows_seconds=[3600],
        horizons_seconds=[86400],
    )
    assert surface.k_cells == 1
    assert surface.cells[0].is_default is True


def test_summarize_always_states_in_sample_and_selection_ban():
    surface = run_robustness_surface(_corpus(5, move=0.15, revert=0.05))
    text = summarize(surface)
    assert "IN-SAMPLE" in text
    assert "FAMILY VERDICT" in text
    # The p-hacking / selection ban must be visible in the caveats.
    assert "SELECTION FORBIDDEN" in text


def test_result_types():
    surface = run_robustness_surface(_corpus(3, move=0.15, revert=0.05))
    assert isinstance(surface, RobustnessSurface)
    assert all(isinstance(c, SurfaceCell) for c in surface.cells)
    # Frozen dataclasses — cannot be mutated after construction.
    with pytest.raises(Exception):
        surface.cells[0].n_trades = 999  # type: ignore[misc]
