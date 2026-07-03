"""
Tests for hard daily/total loss caps enforced at the execution gate + kill-switch
auto-trip on breach (ROADMAP D3/D4).

Caps gate on REALIZED loss and AUTO-TRIP the kill switch — they are enforced in code at
the order boundary, not merely declared in config. Deterministic; no heavy deps.
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


def _order(side, size, price):
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="m1",
        token_id="t1",
        side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
        order_type=OrderType.LIMIT,
        size=size,
        price=price,
        strategy="test",
        market_question="Q?",
        outcome_label="Yes",
    )


def _executor(total_cap=10.0, daily_cap=1000.0):
    return PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=daily_cap, max_total_loss_usd=total_cap,
    )


def test_caps_default_from_settings():
    # When not overridden, caps resolve from config (MAX_*_LOSS_USD), not None.
    ex = PredictionMarketExecutor(dry_run=True)
    assert isinstance(ex.max_daily_loss_usd, float) and ex.max_daily_loss_usd > 0
    assert isinstance(ex.max_total_loss_usd, float) and ex.max_total_loss_usd > 0


def test_total_loss_cap_auto_trips_kill_switch():
    ex = _executor(total_cap=10.0)
    ex.execute(_order("BUY", 100, 0.50))          # open long 100 @ 0.50
    assert not ex.kill_switch_active               # no loss yet
    ex.execute(_order("SELL", 100, 0.10))         # realize ~ -$40 (> $10 total cap)
    assert ex.kill_switch_active                    # AUTO-TRIPPED
    assert "loss_cap" in ex._kill_switch_reason


def test_subsequent_order_blocked_after_cap_breach():
    ex = _executor(total_cap=10.0)
    ex.execute(_order("BUY", 100, 0.50))
    ex.execute(_order("SELL", 100, 0.10))
    res = ex.execute(_order("BUY", 1, 0.50))
    assert res.status == OrderStatus.REJECTED
    assert "LOSS CAP" in (res.error or "") or "KILL SWITCH" in (res.error or "")


def test_daily_loss_cap_auto_trips():
    ex = _executor(total_cap=10000.0, daily_cap=10.0)
    ex.execute(_order("BUY", 100, 0.50))
    ex.execute(_order("SELL", 100, 0.10))         # ~ -$40 daily (> $10 daily cap)
    assert ex.kill_switch_active


def test_no_false_trip_under_cap():
    ex = _executor(total_cap=100.0)               # -$40 loss stays under $100
    ex.execute(_order("BUY", 100, 0.50))
    ex.execute(_order("SELL", 100, 0.10))
    assert not ex.kill_switch_active


def test_record_realized_pnl_tracks_closed_positions():
    # Realized PnL must survive position close (the bug total_pnl-over-open-positions has).
    ex = _executor(total_cap=1000.0)
    ex.record_realized_pnl(-5.0)
    ex.record_realized_pnl(-3.0)
    assert ex._realized_pnl_total == pytest.approx(-8.0)
    assert not ex.kill_switch_active               # under cap
    ex.record_realized_pnl(-1000.0)               # now breach
    assert ex.kill_switch_active


def test_gate_check_independent_of_realization_path():
    # Even if losses are recorded directly (e.g. a future resolution path), the GATE
    # rejects the next order — defense-in-depth, not only the realization auto-trip.
    ex = _executor(total_cap=10.0)
    assert not ex.kill_switch_active               # precondition: clean at construction
    ex._realized_pnl_total = -50.0                 # simulate accumulated realized loss
    res = ex.execute(_order("BUY", 1, 0.50))
    assert res.status == OrderStatus.REJECTED
    assert "LOSS CAP" in (res.error or "")
    assert ex.kill_switch_active                    # gate also auto-tripped


def test_resolution_loss_feeds_cap_and_auto_trips():
    """Resolution is the PRIMARY loss path for binary markets. A losing market
    resolution must feed the executor's realized-PnL counter and AUTO-TRIP the kill
    switch — otherwise the dominant loss path bypasses the cap entirely (the exact
    hole an adversarial auditor found). Regression test for that fix.
    """
    from app.prediction_markets.orchestrator import MarkToMarketEngine
    from app.prediction_markets import polymarket_client as pmc

    ex = _executor(total_cap=10.0)
    ex.execute(_order("BUY", 100, 0.50))            # open long 100 @ 0.50
    assert not ex.kill_switch_active
    token_id = next(iter(ex.positions))
    pos = ex.positions[token_id]

    # Fake a RESOLVED market where our token lost (settlement price 0.0).
    lost = pmc.Market(
        id="m", condition_id="c", question="Q?", slug="q", description="",
        category="", end_date=None,
        outcomes=[pmc.Outcome(token_id=token_id, label="Yes", price=0.0,
                              midpoint=0.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        # Resolution looks the market up by its Gamma numeric id (NOT slug); the
        # fake asserts the RIGHT id is passed so a revert to get_market_by_slug
        # (which never matches a numeric id in prod) fails loud here.
        def get_market_by_id(self, market_id):
            assert market_id == pos.market_id
            return lost

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        engine = MarkToMarketEngine(ex)
        engine.check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # Gross -$50 (0 - 0.50)*100, NET of the entry fee the caps now subtract (2% of the
    # $50 cost basis = $1.00): -$51.00. Beyond the $10 cap either way.
    assert ex._realized_pnl_total == pytest.approx(-51.0)
    assert ex.kill_switch_active                      # resolution loss AUTO-TRIPPED
    assert token_id not in ex.positions               # position closed


def test_daily_window_resets_on_new_utc_day():
    # The daily realized-loss tally must reset when the UTC day rolls over (so a new
    # day starts with a fresh daily budget), while the TOTAL tally persists.
    import datetime as _dt
    ex = _executor(total_cap=10_000.0, daily_cap=100.0)
    ex.record_realized_pnl(-40.0)                  # under daily cap
    assert ex._realized_pnl_daily == pytest.approx(-40.0)
    assert not ex.kill_switch_active
    # Force a day rollover, then any record() call should reset the daily tally first.
    ex._loss_cap_day = _dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc).date()
    ex.record_realized_pnl(0.0)
    assert ex._realized_pnl_daily == pytest.approx(0.0)   # daily reset
    assert ex._realized_pnl_total == pytest.approx(-40.0)  # total persists
