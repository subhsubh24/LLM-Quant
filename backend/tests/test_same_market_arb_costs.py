"""
Tests for SameMarketArbitrageStrategy cost-model honesty fix (ROADMAP B5).

The strategy used to compute its arbitrage edge as a flat additive
``edge = discount - 0.02``, which ignores slippage and is optimistic relative to
the canonical (multiplicative) cost model the executor actually charges. The fix
computes the TRUE net edge for buying ALL outcomes of a market:

    net_edge = 1.0 - sum_outcomes effective_buy_price(outcome.price)

These tests are pure/deterministic (no network): they build fake Market/Outcome
objects, mirroring the construction style in test_prediction_markets.py.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets.polymarket_client import Market, Outcome
from app.prediction_markets.strategies import (
    SameMarketArbitrageStrategy,
    StrategyConfig,
)
from app.prediction_markets.cost_model import DEFAULT_COST_MODEL


# ============================================================
# Fixtures / helpers
# ============================================================

def _make_binary_market(yes_price: float, no_price: float, mid: str = "bin1") -> Market:
    """Binary market with explicit YES and NO prices (so the sum can be < 1)."""
    end_date = datetime.now(timezone.utc) + timedelta(hours=48)
    return Market(
        id=mid,
        condition_id=mid,
        question="Will X happen?",
        slug=mid,
        description="",
        category="Test",
        end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price, midpoint=yes_price, volume=10_000),
            Outcome(token_id=f"{mid}_no", label="No", price=no_price, midpoint=no_price, volume=10_000),
        ],
        total_volume=10_000,
        liquidity=50_000,
        active=True,
        closed=False,
        resolved=False,
        resolution_source="polymarket",
        tags=[],
        neg_risk=False,
    )


def _make_multi_market(prices, mid: str = "multi1", neg_risk: bool = True) -> Market:
    """Multi-outcome (>2) market with the given per-outcome prices."""
    end_date = datetime.now(timezone.utc) + timedelta(hours=48)
    outcomes = [
        Outcome(
            token_id=f"{mid}_{i}",
            label=f"Out{i}",
            price=p,
            midpoint=p,
            volume=10_000,
        )
        for i, p in enumerate(prices)
    ]
    return Market(
        id=mid,
        condition_id=mid,
        question="Which outcome?",
        slug=mid,
        description="",
        category="Test",
        end_date=end_date,
        outcomes=outcomes,
        total_volume=10_000,
        liquidity=50_000,
        active=True,
        closed=False,
        resolved=False,
        resolution_source="polymarket",
        tags=[],
        neg_risk=neg_risk,
    )


def _make_strategy(min_discount: float = 0.01) -> SameMarketArbitrageStrategy:
    # client is unused by scan() (prices are already enriched on the Market objects).
    config = StrategyConfig(min_liquidity=500.0)
    return SameMarketArbitrageStrategy(client=None, config=config, min_discount=min_discount)


def _expected_net_edge(market: Market) -> float:
    return 1.0 - sum(
        DEFAULT_COST_MODEL.effective_buy_price(o.price) for o in market.outcomes
    )


def _old_additive_edge(market: Market) -> float:
    """The previous (optimistic) formula: discount - 0.02."""
    price_sum = sum(o.price for o in market.outcomes)
    return (1.0 - price_sum) - 0.02


# ============================================================
# 1. Binary market with a large discount -> FIRES, edge == cost-model net edge
# ============================================================

def test_binary_large_discount_fires_with_costmodel_edge():
    # YES + NO = 0.90 (10% gross discount). After multiplicative costs there is still
    # a positive net edge, so the strategy must fire.
    market = _make_binary_market(yes_price=0.45, no_price=0.45)
    strat = _make_strategy()

    results = strat.scan([market])

    assert len(results) == 1, "large-discount binary arb should fire exactly once"
    res = results[0]
    assert res.strategy == "same_market_arb"
    assert res.outcome_idx == -1  # BUY-all semantics preserved
    assert res.side == "BUY"
    assert res.expected_value == 1.0

    expected = _expected_net_edge(market)
    assert res.edge == pytest.approx(expected), (
        f"reported edge {res.edge} must equal 1.0 - sum(effective_buy_price) = {expected}"
    )
    assert res.edge > 0
    # And it must be STRICTLY more conservative than the old additive formula.
    assert res.edge <= _old_additive_edge(market) + 1e-12


# ============================================================
# 2. Binary market with a tiny discount -> does NOT fire (costs erase the edge)
# ============================================================

def test_binary_tiny_discount_does_not_fire():
    # Pick a sum in the window where the OLD additive formula (discount - 0.02) is
    # positive (sum < 0.98) but the real multiplicative net edge is non-positive
    # (sum >= ~0.9755 since cost factor ~1.0251). sum = 0.978 satisfies both.
    market = _make_binary_market(yes_price=0.489, no_price=0.489)
    price_sum = sum(o.price for o in market.outcomes)
    assert price_sum == pytest.approx(0.978)

    old_edge = _old_additive_edge(market)
    net_edge = _expected_net_edge(market)
    assert old_edge > 0, "old additive formula would have fired on this market"
    assert net_edge <= 0, "real (cost-model) net edge must be non-positive here"

    strat = _make_strategy()
    results = strat.scan([market])
    assert results == [], "tiny-discount arb must NOT fire once real costs are charged"


def test_binary_985_sum_does_not_fire():
    # The exact 0.985 sum named in the spec: tiny discount that real costs erase.
    market = _make_binary_market(yes_price=0.4925, no_price=0.4925)
    assert sum(o.price for o in market.outcomes) == pytest.approx(0.985)
    assert _expected_net_edge(market) <= 0
    strat = _make_strategy()
    assert strat.scan([market]) == []


# ============================================================
# 3. Multi-outcome analog
# ============================================================

def test_multi_large_discount_fires():
    # 4 outcomes summing to 0.88 -> healthy discount, net edge positive.
    market = _make_multi_market([0.22, 0.22, 0.22, 0.22])
    assert sum(o.price for o in market.outcomes) == pytest.approx(0.88)
    strat = _make_strategy()

    results = strat.scan([market])
    assert len(results) == 1
    res = results[0]
    assert res.outcome_idx == -1
    expected = _expected_net_edge(market)
    assert res.edge == pytest.approx(expected)
    assert res.edge > 0
    assert res.edge <= _old_additive_edge(market) + 1e-12


def test_multi_tiny_discount_does_not_fire():
    # 4 outcomes summing to 0.978 -> old additive edge +0.002 (fires), real net edge <= 0.
    market = _make_multi_market([0.2445, 0.2445, 0.2445, 0.2445])
    assert sum(o.price for o in market.outcomes) == pytest.approx(0.978)
    assert _old_additive_edge(market) > 0
    assert _expected_net_edge(market) <= 0
    strat = _make_strategy()
    assert strat.scan([market]) == []


def test_multi_non_neg_risk_does_not_fire_even_with_discount():
    # A multi-outcome basket that is NOT neg_risk may be a non-exhaustive candidate set,
    # so "buy all -> exactly one pays $1" is NOT guaranteed. Even with a fat discount the
    # strategy must REFUSE to fire (adversarial-audit MECE guard).
    market = _make_multi_market([0.22, 0.22, 0.22, 0.22], neg_risk=False)
    assert _expected_net_edge(market) > 0  # the discount itself would otherwise fire
    strat = _make_strategy()
    assert strat.scan([market]) == []


def test_multi_neg_risk_with_discount_fires():
    # The same prices, but a genuine neg_risk (MECE) basket -> fires.
    market = _make_multi_market([0.22, 0.22, 0.22, 0.22], neg_risk=True)
    strat = _make_strategy()
    assert len(strat.scan([market])) == 1


# ============================================================
# 4. Monotonicity / strict conservatism: new_edge <= old additive edge
# ============================================================

def test_strict_conservatism_new_edge_le_old_additive():
    # For every arbitrage-relevant price_sum (those passing the discount pre-filter),
    # the cost-model net edge must be <= the old additive edge (discount - 0.02).
    # We sweep binary sums across the relevant regime.
    strat = _make_strategy()
    for price_sum in [0.80, 0.85, 0.90, 0.95, 0.97, 0.98, 0.985, 0.99]:
        half = price_sum / 2.0
        market = _make_binary_market(yes_price=half, no_price=half)
        new_edge = _expected_net_edge(market)
        old_edge = _old_additive_edge(market)
        assert new_edge <= old_edge + 1e-12, (
            f"price_sum={price_sum}: new_edge={new_edge} must be <= old_edge={old_edge}"
        )
        # If the strategy fires, the reported edge equals the cost-model net edge.
        results = strat.scan([market])
        if results:
            assert results[0].edge == pytest.approx(new_edge)
            assert results[0].edge <= old_edge + 1e-12


def test_conservatism_holds_for_multi():
    strat = _make_strategy()
    for per in [0.20, 0.22, 0.24, 0.245, 0.2475]:
        market = _make_multi_market([per, per, per, per])
        new_edge = _expected_net_edge(market)
        old_edge = _old_additive_edge(market)
        assert new_edge <= old_edge + 1e-12
        _ = strat.scan([market])  # exercise the path


# ============================================================
# 5. Determinism: identical markets -> identical results across two scans
# ============================================================

def test_determinism_two_scans_identical():
    markets = [
        _make_binary_market(yes_price=0.45, no_price=0.45, mid="d_bin"),
        _make_multi_market([0.22, 0.22, 0.22, 0.22], mid="d_multi"),
    ]
    strat = _make_strategy()

    r1 = strat.scan(markets)
    r2 = strat.scan(markets)

    assert len(r1) == len(r2) == 2
    for a, b in zip(r1, r2):
        assert a.market.id == b.market.id
        assert a.edge == b.edge
        assert a.entry_price == b.entry_price
        assert a.outcome_idx == b.outcome_idx
        assert a.reason == b.reason
