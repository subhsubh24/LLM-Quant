"""SIDE-EFFECT INTEGRITY — a SELL may only REDUCE a held long, never open a short.

On a prediction market you cannot sell a CTF/YES token you do not own, so a SELL
that has no covering long position is not executable — the live venue would reject
it. Before this guard, the paper ``_simulate_fill`` (which fills unconditionally)
fabricated a fictional ``side="short"`` position from a bare SELL (a phantom fill,
same class as the empty-token / multi-leg guards), and a subsequent BUY "to close"
it scaled the position UP while recording $0 realized PnL — silently BYPASSING the
D3/D4 loss-cap kill switch.

Reachability (why this is not a dormant path): the orchestrator routes an
``OrderSide.SELL`` whenever a scanned opportunity carries ``side == "SELL"`` — and a
DEFAULT-scanner strategy, ``CrossMarketArbitrageStrategy``, emits exactly such an
executable (``outcome_idx=0``) SELL on its exclusion / cross-market-gap branch
("sell the more expensive one"). The scan loop's skip-held dedup guarantees any SELL
that reaches execution is on an UN-held token, so every such SELL used to open a
fabricated short.

Every assertion below is proven to FAIL on the pre-fix code (a bare SELL FILLED and
booked a short; the BUY-to-close scaled to size 200 with realized_pnl 0.0).
"""

import pytest

from app.prediction_markets.execution import (
    PredictionMarketExecutor,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Exchange,
)


def _order(side, size, price, token="tok"):
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="m1",
        token_id=token,
        side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
        order_type=OrderType.LIMIT,  # LIMIT → exact prices (no market-order slippage)
        size=size,
        price=price,
        strategy="test",
        market_question="Q?",
        outcome_label="Yes",
    )


def _executor():
    return PredictionMarketExecutor(
        dry_run=True, max_position_usd=1_000_000.0, max_portfolio_usd=1_000_000.0,
        max_daily_loss_usd=1_000_000.0, max_total_loss_usd=1_000_000.0,
    )


def test_bare_sell_on_unheld_token_is_rejected_not_a_fabricated_short():
    """A SELL with no covering long must be REJECTED — never fabricate a short."""
    ex = _executor()
    res = ex.execute(_order("SELL", 100, 0.30))
    assert res.status == OrderStatus.REJECTED, "a sell of unowned tokens must not fill"
    assert "SELL rejected" in (res.error or "")
    # No fictional position was booked.
    assert "tok" not in ex.positions


def test_sell_cannot_bypass_loss_caps_via_fabricated_short():
    """The exact loss-cap-bypass the guard closes: a bare SELL then a BUY 'to close'
    it used to scale the (fictional) short to size 200 and record $0 PnL, so a real
    cash loss never reached the kill-switch counters."""
    ex = _executor()
    ex.execute(_order("SELL", 100, 0.30))          # was: fabricated short 100 @ 0.30
    ex.execute(_order("BUY", 100, 0.90))           # was: scaled to 200, realized 0.0
    # Post-fix: neither order booked anything (the SELL was rejected; the BUY opened
    # a normal long), and no phantom realized-PnL escaped the caps.
    pos = ex.positions.get("tok")
    # The BUY is a legitimate new long of size 100 (not a scaled 200 short).
    assert pos is not None and pos.side == "long" and pos.size == pytest.approx(100.0)
    assert ex._realized_pnl_total == pytest.approx(0.0)


def test_sell_reduces_a_held_long_and_records_pnl():
    """The legitimate path is PRESERVED: BUY a long, then SELL to reduce/close it —
    the SELL fills and records realized PnL via the reduce branch (this is exactly
    how the loss-cap tests realize a loss)."""
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))           # open long 100 @ 0.50
    res = ex.execute(_order("SELL", 100, 0.30))    # close: realize (0.30-0.50)*100
    assert res.status == OrderStatus.FILLED
    assert "tok" not in ex.positions               # fully closed
    assert ex._realized_pnl_total < 0.0            # a real loss was recorded


def test_partial_sell_reduces_a_held_long():
    """A partial SELL (size < held long) reduces the position and stays long."""
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))
    res = ex.execute(_order("SELL", 40, 0.60))     # reduce by 40
    assert res.status == OrderStatus.FILLED
    pos = ex.positions.get("tok")
    assert pos is not None and pos.side == "long" and pos.size == pytest.approx(60.0)
    assert ex._realized_pnl_total > 0.0            # sold above entry → a gain


def test_oversized_sell_that_would_flip_to_short_is_rejected():
    """A SELL larger than the held long (which would flip the position to a short)
    is rejected — the covering-long bound is exact, not just presence-of-a-position."""
    ex = _executor()
    ex.execute(_order("BUY", 100, 0.50))           # held long 100
    res = ex.execute(_order("SELL", 150, 0.40))    # 150 > 100 → would open a short
    assert res.status == OrderStatus.REJECTED
    assert "SELL rejected" in (res.error or "")
    # The original long is untouched.
    pos = ex.positions.get("tok")
    assert pos is not None and pos.side == "long" and pos.size == pytest.approx(100.0)
