"""Tests for the ROADMAP C8 measured half-spread cost model.

Three things have to hold and each is worth more than a green tick:

1. The DEFAULT path is untouched. Every number this repo has published was produced with
   no half-spread model, so if ``CostModel()`` moved by a single float the whole committed
   history would silently become unreproducible. Asserted bit-exactly, not to a tolerance.
2. The committed band table really is what the committed probe bytes say. A hand-typed
   table that drifts from its source is a fabricated measurement wearing a real one's name,
   so ``derive_bands_from_depth_probe`` regenerates it from ``data/depth_probe_polymarket.json``
   and the two must agree exactly.
3. A set half-spread model enters ``_seed_hash``. It is PnL-determining, and this repo has
   already shipped this exact collision class twice (category in C6, fee_schedule in #413).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.prediction_markets import half_spread as hs
from app.prediction_markets.cost_model import DEFAULT_COST_MODEL, CostModel
from app.prediction_markets.walk_forward import HistoricalMarket, walk_forward_backtest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "data" / "depth_probe_polymarket.json"


# ---------------------------------------------------------------------------
# 1. The default path is byte-identical
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("price", [0.0, 0.005, 0.037, 0.1, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0])
def test_default_cost_model_is_unchanged_by_the_new_field(price: float) -> None:
    """With no half-spread model the arithmetic must be the pre-C8 arithmetic exactly.

    Recomputed here from the raw rates rather than compared against a golden constant, so
    the assertion pins the FORMULA and not a snapshot of it.
    """
    cm = CostModel()
    assert cm.half_spread_model is None
    expected_buy = min(
        max(price * (1.0 + cm.slippage_rate) * (1.0 + cm.fee_rate), 1e-6), 1.0
    )
    expected_sell = min(max(price * (1.0 - cm.slippage_rate) * (1.0 - cm.fee_rate), 0.0), 1.0)
    assert cm.effective_buy_price(price) == expected_buy
    assert cm.effective_sell_price(price) == expected_sell


def test_default_cost_model_singleton_still_compares_equal() -> None:
    """``DEFAULT_COST_MODEL`` is a frozen dataclass used as a default argument all over the
    engine; adding a defaulted field must not disturb its equality or hash."""
    assert DEFAULT_COST_MODEL == CostModel()
    assert hash(DEFAULT_COST_MODEL) == hash(CostModel())


# ---------------------------------------------------------------------------
# 2. The committed table reproduces from the committed bytes
# ---------------------------------------------------------------------------
def test_depth_probe_table_reproduces_from_committed_artifact() -> None:
    rows = json.loads(PROBE_PATH.read_text())["rows"]
    derived = hs.derive_bands_from_depth_probe(rows)
    pinned = hs.POLYMARKET_HALF_SPREAD_DEPTH_PROBE.bands
    assert len(derived) == len(pinned)
    for d, p in zip(derived, pinned):
        assert (d.lo, d.hi, d.half_spread_frac, d.n) == (p.lo, p.hi, p.half_spread_frac, p.n)


def test_every_committed_probe_row_is_a_real_two_sided_quote() -> None:
    """The band medians are only meaningful if no row is a fabricated 0/1 book.

    The probe refuses a one-sided book rather than inventing a quote, so this asserts the
    property the derivation silently relies on instead of trusting the docstring.
    """
    rows = json.loads(PROBE_PATH.read_text())["rows"]
    assert rows
    for r in rows:
        assert 0.0 < float(r["best_bid"]) < float(r["best_ask"]) <= 1.0


def test_derive_raises_rather_than_defaulting_when_a_band_is_empty() -> None:
    """A band with no measurement must SURFACE, never quietly become a number."""
    one_row = [{"best_bid": 0.40, "best_ask": 0.41}]
    with pytest.raises(ValueError, match="no probe rows fall in band"):
        hs.derive_bands_from_depth_probe(one_row)


# ---------------------------------------------------------------------------
# 3. Model structure and lookup
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(hs.MODELS))
def test_models_cover_the_whole_price_range_with_no_gap(name: str) -> None:
    model = hs.MODELS[name]
    prev = 0.0
    for b in model.bands:
        assert b.lo == pytest.approx(prev)
        prev = b.hi
    assert prev >= 1.0
    # Every price in [0, 1] resolves to a band, including the closed right edge.
    for p in (0.0, 0.0001, 0.3, 0.9799, 0.98, 1.0):
        assert model.band_for(p) is not None
        assert model.half_spread_usd(p) >= 0.0


def test_gapped_bands_are_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="gapless"):
        hs.HalfSpreadModel(
            name="broken",
            bands=(
                hs.SpreadBand(0.0, 0.4, 0.01, 1, "t"),
                hs.SpreadBand(0.5, 1.0, 0.01, 1, "t"),
            ),
        )


def test_bands_must_reach_price_one() -> None:
    with pytest.raises(ValueError, match="cover up to price 1.0"):
        hs.HalfSpreadModel(name="short", bands=(hs.SpreadBand(0.0, 0.5, 0.01, 1, "t"),))


def test_conservative_model_is_the_per_band_max_of_the_two_measurements() -> None:
    a = {(b.lo, b.hi): b.half_spread_frac for b in hs.POLYMARKET_HALF_SPREAD_747BOOK.bands}
    d = {(b.lo, b.hi): b.half_spread_frac for b in hs.POLYMARKET_HALF_SPREAD_DEPTH_PROBE.bands}
    for b in hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE.bands:
        assert b.half_spread_frac == max(a[(b.lo, b.hi)], d[(b.lo, b.hi)])


def test_per_band_sample_size_is_never_invented() -> None:
    """The 747-book source published no per-band n; those bands must carry None, not a
    fabricated count. The depth-probe bands must carry a real one."""
    by_source = {}
    for b in hs.POLYMARKET_HALF_SPREAD_747BOOK.bands:
        by_source.setdefault(b.source, []).append(b.n)
    assert all(n is None for n in by_source[hs.SOURCE_747BOOK])
    assert all(isinstance(n, int) and n >= 1 for n in by_source[hs.SOURCE_DEPTH_PROBE])


def test_out_of_range_prices_clamp_rather_than_extrapolate() -> None:
    m = hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE
    assert m.frac_for(-5.0) == m.frac_for(0.0)
    assert m.frac_for(7.0) == m.frac_for(1.0)


# ---------------------------------------------------------------------------
# 4. Cost behaviour with a model set
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(hs.MODELS))
@pytest.mark.parametrize("price", [0.005, 0.015, 0.035, 0.075, 0.2, 0.5, 0.8])
def test_measured_spread_is_costlier_than_the_flat_rate_below_the_near_certain_bands(
    name: str, price: float
) -> None:
    """Below 0.90 the measured crossing cost must be at least the flat stand-in.

    An earlier version of this test claimed the property held "across every traded band" and
    stopped its grid at 0.8, which made the claim true only because it never looked. It is
    FALSE in the near-certain bands — see the test below — and the fade family does trade
    there on its exit leg. Scoped honestly rather than quietly asserted.
    """
    flat = CostModel()
    measured = CostModel(half_spread_model=hs.MODELS[name])
    assert measured.effective_buy_price(price) >= flat.effective_buy_price(price)
    assert measured.effective_sell_price(price) <= flat.effective_sell_price(price)


@pytest.mark.parametrize("name", sorted(hs.MODELS))
@pytest.mark.parametrize("price", [0.985, 0.99, 0.995])
def test_measured_spread_is_CHEAPER_on_the_exit_leg_above_098(
    name: str, price: float
) -> None:
    """The inversion, asserted rather than hidden.

    Above 0.98 the real book is very tight — the probe measured a median half-spread
    fraction of 0.000503, ten times cheaper than the flat 0.5%-of-price stand-in. So there
    the measured model is a DISCOUNT, not a surcharge, and it shows on the SELL leg (the buy
    leg is pinned at the $1.00 breakeven cap under both models, so the difference is
    invisible there).

    An adversarial auditor found the original blanket claim — "never cheaper than the flat
    rate across every traded band" — false here, and it mattered because the EXP-006b fade
    family exits legs in exactly this range. They quantified it: +$1.29 of extra proceeds
    across those legs, against a -$887.89 total correction. Immaterial to the verdict, and
    asserted anyway, because a cost model whose whole claim to trust is "it errs in the safe
    direction" has to name the place where it does not.
    """
    flat = CostModel()
    measured = CostModel(half_spread_model=hs.MODELS[name])
    assert measured.effective_sell_price(price) > flat.effective_sell_price(price)


@pytest.mark.parametrize("name", sorted(hs.MODELS))
@pytest.mark.parametrize("price", [0.92, 0.95, 0.97])
def test_the_inversion_does_not_reach_below_098(name: str, price: float) -> None:
    """Bound the exception: between 0.90 and 0.98 the measured model is still the costlier
    one, so the discount above is confined to the top band rather than a general property of
    the near-certain regime."""
    flat = CostModel()
    measured = CostModel(half_spread_model=hs.MODELS[name])
    assert measured.effective_buy_price(price) > flat.effective_buy_price(price)
    assert measured.effective_sell_price(price) < flat.effective_sell_price(price)


def test_sell_proceeds_never_go_negative_in_the_sub_cent_band() -> None:
    """A 16.7% half-spread on a 0.003 quote is a real measurement; proceeds still cannot be
    negative, and the floor must not leak into a negative price."""
    cm = CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE)
    for p in (0.0, 0.0005, 0.003, 0.009):
        assert 0.0 <= cm.effective_sell_price(p) <= 1.0


def test_round_trip_is_a_loss_at_an_unchanged_price() -> None:
    cm = CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE)
    for p in (0.05, 0.2, 0.5, 0.9):
        assert cm.effective_sell_price(p) < cm.effective_buy_price(p)


def test_impact_path_still_floors_at_the_flat_all_in_price() -> None:
    """Impact remains a separate ADD-ON; with a half-spread model set it must still never
    return less than the model's own no-impact price."""
    cm = CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE)
    base = cm.effective_buy_price(0.2)
    assert cm.effective_buy_price_with_impact(0.2, 100.0, None) == base
    assert cm.effective_buy_price_with_impact(0.2, 1000.0, 500.0) > base


# ---------------------------------------------------------------------------
# 5. The reproducibility fingerprint covers it (the C6 / #413 collision class)
# ---------------------------------------------------------------------------
def _toy_markets(n: int = 40) -> list:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        out.append(
            HistoricalMarket(
                market_id=f"m{i:03d}",
                decision_time=base + timedelta(days=i),
                resolution_time=base + timedelta(days=i + 10),
                market_price=0.05 + 0.01 * (i % 8),
                model_prob=0.30,
                outcome=i % 4 == 0,
                category="Politics",
            )
        )
    return out


def test_seed_hash_covers_the_half_spread_model() -> None:
    """Two runs identical in data, seed and every other config, differing ONLY in the
    half-spread model, must NOT share a fingerprint. Proven non-tautological by also
    asserting the PnL genuinely differs — a hash difference on identical results would be
    noise, not coverage."""
    markets = _toy_markets()
    flat = walk_forward_backtest(markets, seed=42, cost_model=CostModel())
    measured = walk_forward_backtest(
        markets,
        seed=42,
        cost_model=CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE),
    )
    assert flat.total_pnl_usd != measured.total_pnl_usd
    assert flat.seed_hash != measured.seed_hash


def test_two_different_half_spread_models_do_not_collide() -> None:
    markets = _toy_markets()
    a = walk_forward_backtest(
        markets, seed=42, cost_model=CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_747BOOK)
    )
    b = walk_forward_backtest(
        markets,
        seed=42,
        cost_model=CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_DEPTH_PROBE),
    )
    assert a.seed_hash != b.seed_hash


def test_no_half_spread_model_leaves_the_fingerprint_untouched() -> None:
    """The added-only-when-set discipline: with no model set, the payload key is ABSENT.

    An auditor pointed out that an earlier docstring here claimed the test was "pinned
    against the frozen-corpus headline hash", which it was not — it compared two trivially
    equivalent constructions and would not have caught a fingerprint regression at all. It
    now pins a literal, so it would.
    """
    markets = _toy_markets()
    a = walk_forward_backtest(markets, seed=42)
    b = walk_forward_backtest(markets, seed=42, cost_model=CostModel())
    assert a.seed_hash == b.seed_hash
    # The literal that makes this test load-bearing: change the no-model payload in any way
    # and this fails, instead of passing because both sides changed together.
    assert a.seed_hash == "c65b567902ead7eb", a.seed_hash


def test_half_spread_run_is_deterministic() -> None:
    markets = _toy_markets()
    cm = CostModel(half_spread_model=hs.POLYMARKET_HALF_SPREAD_CONSERVATIVE)
    a = walk_forward_backtest(markets, seed=42, cost_model=cm)
    b = walk_forward_backtest(markets, seed=42, cost_model=cm)
    assert a.seed_hash == b.seed_hash
    assert a.total_pnl_usd == b.total_pnl_usd
    assert [t.pnl_usd for t in a.trades] == [t.pnl_usd for t in b.trades]
