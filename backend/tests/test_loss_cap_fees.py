"""
Regression tests for the loss-cap NET-OF-FEES fix (ROADMAP D3/D4 safety hardening).

Before this fix, the hard daily/total loss caps + kill switch gated on the GROSS price
move — ``(settlement/fill_price - avg_entry_price) * size`` — while the venue fees the
executor actually charges (2% of notional, ``_simulate_fill``) were tracked only in the
reporting-only ``total_fees`` field and NEVER subtracted from the loss-cap counters. So
the hard cap UNDERCOUNTED the true cash loss by exactly the fees: a position could lose
more real cash than the owner's configured ceiling before the kill switch tripped.

The fix nets the round-trip transaction cost into the ``record_realized_pnl`` counters
(the entry fee on resolution; entry + exit fees on a reduce), so the caps gate on TRUE
net cash PnL. Netting fees can only ever trip the cap EARLIER (at a slightly smaller
gross loss) — the conservative, safe direction. These tests are DETERMINISTIC and hit
NO network (paper/dry-run executor + a fake resolved market).

The boundary tests (``*_only_because_of_fees``) are the money proof: they fail on the
pre-fix code (gross loss under the cap → no trip) and pass after (net loss over the cap
→ trip), so they pin the exact behavior the safety fix delivers.
"""

import pytest

from app.prediction_markets.execution import (
    PredictionMarketExecutor,
    OrderRequest,
    OrderStatus,
    OrderSide,
    OrderType,
    Exchange,
)
from app.prediction_markets.cost_model import DEFAULT_FEE_RATE
from app.prediction_markets import polymarket_client as pmc


def _order(side, size, price, token="t1"):
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="m1",
        token_id=token,
        side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
        order_type=OrderType.LIMIT,  # LIMIT → no market-order slippage, exact prices
        size=size,
        price=price,
        strategy="test",
        market_question="Q?",
        outcome_label="Yes",
    )


def _executor(total_cap=1_000_000.0, daily_cap=1_000_000.0):
    return PredictionMarketExecutor(
        dry_run=True, max_position_usd=1_000.0, max_portfolio_usd=100_000.0,
        max_daily_loss_usd=daily_cap, max_total_loss_usd=total_cap,
    )


def _resolve(ex, token_id, settlement_price):
    """Drive the orchestrator resolution path for a single held token."""
    from app.prediction_markets.orchestrator import MarkToMarketEngine

    pos = ex.positions[token_id]
    market = pmc.Market(
        id="m1", condition_id="c", question="Q?", slug="q", description="",
        category="", end_date=None,
        outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=settlement_price,
                              midpoint=settlement_price, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_market_by_id(self, market_id):
            assert market_id == pos.market_id
            return market

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        MarkToMarketEngine(ex).check_resolutions()
    finally:
        pmc.PolymarketClient = orig


# ---------------------------------------------------------------------------
# record_realized_pnl netting semantics (the primitive)
# ---------------------------------------------------------------------------

def test_record_realized_pnl_subtracts_fees():
    ex = _executor()
    ex.record_realized_pnl(-10.0, fees=0.5)
    assert ex._realized_pnl_total == pytest.approx(-10.5)
    assert ex._realized_pnl_daily == pytest.approx(-10.5)


def test_record_realized_pnl_fee_reduces_a_win_too():
    # The counter tracks true NET cash PnL — a fee reduces a gain, not just a loss.
    ex = _executor()
    ex.record_realized_pnl(10.0, fees=0.5)
    assert ex._realized_pnl_total == pytest.approx(9.5)


def test_record_realized_pnl_fee_is_magnitude_only():
    # A fee always REDUCES PnL regardless of sign passed (defensive abs()).
    ex = _executor()
    ex.record_realized_pnl(-10.0, fees=-0.5)  # signed fee still reduces
    assert ex._realized_pnl_total == pytest.approx(-10.5)


def test_record_realized_pnl_default_fees_is_backward_compatible():
    # No fees arg → identical to the pre-fix gross behavior (every legacy caller safe).
    ex = _executor()
    ex.record_realized_pnl(-8.0)
    assert ex._realized_pnl_total == pytest.approx(-8.0)


# ---------------------------------------------------------------------------
# Resolution path (the DOMINANT binary-market loss path) nets the entry fee
# ---------------------------------------------------------------------------

def test_resolution_loss_nets_entry_fee():
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))            # cost basis $50; entry fee = 2% = $1.00
    _resolve(ex, next(iter(ex.positions)), 0.0)     # total loss
    # Gross -$50, net of the $1.00 entry fee = -$51.00 (resolution has no exit fill fee).
    expected_entry_fee = DEFAULT_FEE_RATE * 0.50 * 100
    assert expected_entry_fee == pytest.approx(1.0)
    assert ex._realized_pnl_total == pytest.approx(-51.0)


def test_resolution_win_nets_entry_fee():
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.40))            # cost basis $40; entry fee = $0.80
    _resolve(ex, next(iter(ex.positions)), 1.0)     # win, settles at $1
    # Gross +$60 ((1.0-0.4)*100), net of the $0.80 entry fee = +$59.20.
    assert ex._realized_pnl_total == pytest.approx(59.20)


def test_resolution_kill_switch_trips_ONLY_because_of_fees():
    # THE MONEY BOUNDARY (proven-fail on pre-fix code). Gross loss $10.00 is UNDER the
    # $10.10 cap (pre-fix: no trip). Net of the $0.20 entry fee the loss is $10.20 → OVER
    # the cap → the kill switch trips. This is exactly the undercount the fix closes.
    ex = _executor(total_cap=10.10)
    ex.execute(_order("BUY", 20, 0.50))             # cost basis $10; entry fee = $0.20
    assert not ex.kill_switch_active
    _resolve(ex, next(iter(ex.positions)), 0.0)     # gross -$10.00, net -$10.20
    assert ex._realized_pnl_total == pytest.approx(-10.20)
    assert ex.kill_switch_active                     # trips ONLY because fees are netted


# ---------------------------------------------------------------------------
# Reduce / SELL path nets BOTH the entry fee and the exit fill fee
# ---------------------------------------------------------------------------

def test_reduce_loss_nets_entry_and_exit_fees():
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))            # open; entry fee (on close) = 2% * $50
    ex.execute(_order("SELL", 100, 0.30))           # realize a loss, exit fill fee charged
    # Gross (0.30-0.50)*100 = -$20.00.
    # entry fee = 2% * 0.50 * 100 = $1.00; exit fee = 2% * 0.30 * 100 = $0.60.
    # net = -20.00 - 1.00 - 0.60 = -$21.60.
    assert ex._realized_pnl_total == pytest.approx(-21.60)


def test_reduce_kill_switch_trips_ONLY_because_of_fees():
    # Boundary on the reduce path. Gross loss $20.00 is UNDER the $21.00 cap (pre-fix: no
    # trip); net of the $1.00 entry + $0.60 exit fee it is $21.60 → OVER → trips.
    ex = _executor(total_cap=21.0)
    ex.execute(_order("BUY", 100, 0.50))
    assert not ex.kill_switch_active
    ex.execute(_order("SELL", 100, 0.30))
    assert ex._realized_pnl_total == pytest.approx(-21.60)
    assert ex.kill_switch_active


def test_partial_reduce_nets_proportional_entry_fee():
    # A PARTIAL reduce nets only the entry fee attributable to the REDUCED size.
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))            # 100 contracts @ 0.50
    ex.execute(_order("SELL", 40, 0.30))            # reduce 40
    # Gross (0.30-0.50)*40 = -$8.00.
    # entry fee for the 40 closed = 2% * 0.50 * 40 = $0.40; exit fee = 2% * 0.30 * 40 = $0.24.
    # net = -8.00 - 0.40 - 0.24 = -$8.64.
    assert ex._realized_pnl_total == pytest.approx(-8.64)
    assert ex.positions["t1"].size == pytest.approx(60.0)  # remainder still open
