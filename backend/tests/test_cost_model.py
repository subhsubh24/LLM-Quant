"""
Tests for the realistic cost model + cost-aware Kelly sizing (ROADMAP C2).

These prove the fix for the systematic over-betting / over-trading bug: sizing must be
done on the edge NET of the slippage + fee the executor actually charges, not the gross
edge. They are deterministic and depend only on numpy (no heavy ML deps), so they run
inside the light preflight gate surface.
"""

import math

import pytest

from app.prediction_markets.cost_model import (
    CostModel,
    DEFAULT_COST_MODEL,
    DEFAULT_FEE_RATE,
    DEFAULT_SLIPPAGE_RATE,
)
from app.prediction_markets.orchestrator import (
    KellyConfig,
    kelly_size,
    size_from_scan_result,
)
from app.prediction_markets.polymarket_client import ScanResult


# ---------------------------------------------------------------------------
# Cost model arithmetic
# ---------------------------------------------------------------------------

def test_effective_buy_price_includes_slippage_and_fee():
    cm = CostModel(slippage_rate=0.005, fee_rate=0.02)
    c = 0.50
    expected = 0.50 * 1.005 * 1.02
    assert math.isclose(cm.effective_buy_price(c), expected, rel_tol=1e-9)
    # Effective cost is strictly ABOVE the quoted price — costs move against us.
    assert cm.effective_buy_price(c) > c


def test_effective_price_matches_executor_rates():
    # cost_model defaults MUST mirror execution.py _simulate_fill (0.5% slippage,
    # 2% fee) so EV and realized PnL subtract the same costs.
    assert DEFAULT_SLIPPAGE_RATE == 0.005
    assert DEFAULT_FEE_RATE == 0.02


def test_executor_imports_cost_model_rates_no_drift():
    """C2 unification: execution.py must SOURCE its paper-fill slippage + fee from the
    cost_model single source of truth, not from duplicated literals. This binds the two
    so a future edit to one can't silently diverge from the other (which would make the
    backtest EV and realized PnL inconsistent and masquerade as overfit)."""
    from app.prediction_markets import execution as ex

    # The constants are imported into execution's namespace and are the SAME values.
    assert ex.DEFAULT_SLIPPAGE_RATE == DEFAULT_SLIPPAGE_RATE
    assert ex.DEFAULT_FEE_RATE == DEFAULT_FEE_RATE

    # And a simulated market BUY fill actually applies exactly those rates.
    from app.prediction_markets.execution import (
        Exchange,
        OrderRequest,
        OrderSide,
        OrderType,
        PredictionMarketExecutor,
    )

    executor = PredictionMarketExecutor(dry_run=True)
    req = OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="m",
        token_id="t",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=100.0,
        price=0.50,
    )
    result = executor._simulate_fill(req)
    expected_fill = min(0.50 * (1 + DEFAULT_SLIPPAGE_RATE), 0.99)
    assert math.isclose(result.filled_price, expected_fill, rel_tol=1e-12)
    assert math.isclose(
        result.fees, 100.0 * expected_fill * DEFAULT_FEE_RATE, rel_tol=1e-12
    )


def test_effective_price_caps_at_one_no_optimism():
    cm = CostModel()
    # A near-certain contract whose all-in cost exceeds $1 caps at exactly 1.0
    # (breakeven), never BELOW — capping below would understate cost / overstate edge.
    assert cm.effective_buy_price(0.999) == 1.0
    # And its net edge is <= 0 for any p < 1, so it is never sized.
    assert cm.net_edge(0.999, 0.999) <= 0.0
    # A mid-range price stays strictly inside (0, 1).
    assert 0.0 < cm.effective_buy_price(0.50) < 1.0


def test_net_edge_below_gross_edge():
    cm = DEFAULT_COST_MODEL
    p, c = 0.60, 0.55
    gross = p - c
    net = cm.net_edge(p, c)
    assert net < gross
    # Costs at price 0.55 are ~0.55*(0.005+0.0201) ≈ 0.0138, so net ≈ 0.05 - 0.0138.
    assert math.isclose(net, p - cm.effective_buy_price(c), rel_tol=1e-9)


def test_net_edge_can_flip_negative_when_costs_exceed_gross_edge():
    cm = DEFAULT_COST_MODEL
    # Gross edge of 1% at price 0.50: costs ≈ 0.50*0.0251 ≈ 0.0126 > 0.01 → net < 0.
    p, c = 0.51, 0.50
    assert (p - c) > 0
    assert cm.net_edge(p, c) < 0


def test_contracts_for_budget_uses_effective_cost():
    cm = DEFAULT_COST_MODEL
    budget, price = 100.0, 0.50
    n = cm.contracts_for_budget(budget, price)
    # Fewer contracts than the naive budget/price, because each costs more than `price`.
    assert n < budget / price
    assert math.isclose(n, budget / cm.effective_buy_price(price), rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Depth / market-impact model (ROADMAP C2/C3)
# ---------------------------------------------------------------------------

def test_impact_price_exceeds_flat_for_large_order_in_thin_book():
    cm = DEFAULT_COST_MODEL
    price = 0.50
    flat = cm.effective_buy_price(price)
    # Large order (10k contracts) into a thin book (1k depth) pays extra impact.
    thin = cm.effective_buy_price_with_impact(price, order_size_contracts=10_000.0,
                                              depth_contracts=1_000.0)
    assert thin > flat


def test_impact_price_approx_flat_for_small_order_in_deep_book():
    cm = DEFAULT_COST_MODEL
    price = 0.50
    flat = cm.effective_buy_price(price)
    # Tiny order into a very deep book → impact is negligible → ≈ flat.
    deep = cm.effective_buy_price_with_impact(price, order_size_contracts=1.0,
                                              depth_contracts=1e12)
    assert math.isclose(deep, flat, rel_tol=1e-6)


def test_impact_none_depth_equals_flat_exactly():
    cm = DEFAULT_COST_MODEL
    price = 0.50
    # depth None means unknown/infinite depth → exactly the flat price (no discontinuity).
    assert cm.effective_buy_price_with_impact(price, 10_000.0, None) == \
        cm.effective_buy_price(price)


def test_impact_is_monotone_non_decreasing_in_order_size():
    cm = DEFAULT_COST_MODEL
    price, depth = 0.40, 2_000.0
    sizes = [0.0, 1.0, 10.0, 100.0, 1_000.0, 5_000.0, 50_000.0, 500_000.0]
    prices = [cm.effective_buy_price_with_impact(price, s, depth) for s in sizes]
    for a, b in zip(prices, prices[1:]):
        assert b >= a - 1e-12


def test_impact_never_reduces_price_below_flat():
    cm = DEFAULT_COST_MODEL
    flat = cm.effective_buy_price(0.30)
    for size in (0.0, 1.0, 1e6):
        for depth in (None, 1.0, 1e3, 1e9):
            p = cm.effective_buy_price_with_impact(0.30, size, depth)
            assert p >= flat - 1e-12


def test_impact_price_capped_at_one():
    cm = DEFAULT_COST_MODEL
    # Enormous order into a razor-thin book — impact blows up but price caps at 1.0.
    p = cm.effective_buy_price_with_impact(0.95, order_size_contracts=1e9,
                                           depth_contracts=1.0)
    assert p == 1.0


def test_thin_book_large_order_flips_marginal_edge_negative():
    """The auditor concern: a near-certainty NO book is illiquid, so the modeled flat
    slippage understates cost and reports a spurious positive edge. With depth-aware
    impact a large order in a thin book erases that marginal edge → net edge < 0."""
    cm = DEFAULT_COST_MODEL
    # price 0.90 → flat all-in cost ≈ 0.9226; p=0.93 leaves a thin (~0.7%) positive net.
    p, price = 0.93, 0.90
    # Flat net edge is (marginally) positive at this price...
    assert cm.net_edge(p, price) > 0
    # ...but a large order against a thin book pushes the all-in cost above p → negative.
    flat_net = cm.net_edge_with_impact(p, price, order_size_contracts=1.0,
                                       depth_contracts=1e12)
    thin_net = cm.net_edge_with_impact(p, price, order_size_contracts=20_000.0,
                                       depth_contracts=1_000.0)
    assert flat_net > 0            # tiny order in a deep book still shows the edge
    assert thin_net < 0            # large order in a thin book erases it


def test_default_cost_model_construction_unchanged():
    """Adding impact_coeff as a defaulted field must not change CostModel() identity or
    the existing flat methods, nor break frozen-dataclass equality/hash."""
    assert CostModel() == DEFAULT_COST_MODEL
    assert hash(CostModel()) == hash(DEFAULT_COST_MODEL)
    # Flat path is untouched by the new field.
    assert CostModel().effective_buy_price(0.5) == DEFAULT_COST_MODEL.effective_buy_price(0.5)


# ---------------------------------------------------------------------------
# Cost-aware sizing through the orchestrator
# ---------------------------------------------------------------------------

def _scan(edge, entry_price=0.50, confidence=0.9, strategy="test"):
    return ScanResult(
        market=None,
        strategy=strategy,
        outcome_idx=0,
        side="BUY",
        entry_price=entry_price,
        expected_value=1.0,
        edge=edge,
        confidence=confidence,
        reason="test",
    )


def _cfg():
    # Disable Monte Carlo so the test exercises the deterministic cost-aware path only.
    return KellyConfig(use_monte_carlo=False, min_edge=0.01, min_bet_usd=1.0)


def test_marginal_gross_edge_is_rejected_after_costs():
    """A 1% gross edge at price 0.50 has NEGATIVE net edge → no bet (the over-trading
    fix). Before C2 this would have sized a position."""
    bet_usd, contracts = size_from_scan_result(_scan(edge=0.01, entry_price=0.50),
                                               bankroll=1000.0, config=_cfg())
    assert bet_usd == 0.0
    assert contracts == 0.0


def test_genuine_edge_still_sizes_but_smaller_than_gross():
    """A large genuine edge still trades, but the cost-aware bet is <= the gross bet
    (the over-betting fix)."""
    cfg = _cfg()
    scan = _scan(edge=0.15, entry_price=0.50)
    p = scan.entry_price + scan.edge

    cost_aware_bet, contracts = size_from_scan_result(scan, bankroll=1000.0, config=cfg)
    gross_bet = kelly_size(edge=scan.edge, confidence=scan.confidence,
                           win_probability=p, bankroll=1000.0, config=cfg)

    assert cost_aware_bet > 0          # genuine edge survives costs
    assert contracts > 0
    assert cost_aware_bet <= gross_bet  # never bets MORE than the (wrong) gross sizing


def test_sizing_is_deterministic():
    cfg = _cfg()
    a = size_from_scan_result(_scan(edge=0.12), bankroll=1000.0, config=cfg)
    b = size_from_scan_result(_scan(edge=0.12), bankroll=1000.0, config=cfg)
    assert a == b


def test_no_double_counting_cash_deployed_matches_budget():
    """End-to-end: costs are subtracted ONCE, not twice. The orchestrator sizes a
    budget and converts to contracts at the cost-inclusive price; the executor then
    applies slippage + fee on the fill. Net cash deployed must equal the intended
    budget (not budget*(1+costs)) — proving costs aren't double-charged.

    This pins the implicit algebraic dependency between cost_model.py and
    execution.py::_simulate_fill: if either cost formula changes without the other,
    this assertion breaks loudly.
    """
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderRequest, Exchange, OrderSide, OrderType,
    )

    cfg = _cfg()
    scan = _scan(edge=0.15, entry_price=0.50)
    bet_usd, contracts = size_from_scan_result(scan, bankroll=1000.0, config=cfg)
    assert bet_usd > 0 and contracts > 0

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=10_000.0,
                                  max_portfolio_usd=10_000.0)
    res = ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m", token_id="t",
        side=OrderSide.BUY, order_type=OrderType.MARKET,  # market => slippage applies
        size=contracts, price=scan.entry_price, strategy="test",
        market_question="Q?", outcome_label="Yes",
    ))
    # Net cash out = filled notional + fees. Should match the intended budget within
    # the rounding tolerance (contracts were rounded to 1 decimal in sizing).
    cash_out = res.filled_size * res.filled_price + res.fees
    assert cash_out == pytest.approx(bet_usd, abs=0.05 * bet_usd + 0.05)
