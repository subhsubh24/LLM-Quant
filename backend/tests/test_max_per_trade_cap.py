"""
Regression: the owner-facing MAX_PER_TRADE_USD ceiling must actually be ENFORCED.

`max_per_trade_usd` was defined in config (default $5) but read NOWHERE — so an owner
who set MAX_PER_TRADE_USD to bound single-order risk got zero protection; the only
per-order gate was `max_position_usd` (default $50, 10x looser). This wires it into the
execution gate and the production `get_executor` singleton.

These tests assert:
  * the executor REJECTS an order whose notional exceeds the per-trade cap even when it
    is below the per-position cap (the load-bearing new behavior),
  * the tighter per-trade ceiling wins and names itself in the rejection,
  * `None` disables the gate (bit-identical behavior for standalone/harness constructions),
  * `get_executor` reads the setting so the production path honors MAX_PER_TRADE_USD.
"""

import pytest

from app.prediction_markets.execution import (
    PredictionMarketExecutor,
    OrderRequest,
    OrderSide,
    OrderType,
    Exchange,
)


def _order(size: float, price: float = 0.50) -> OrderRequest:
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="m",
        token_id="t",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=size,
        price=price,
        strategy="test",
        market_question="Q?",
        outcome_label="Yes",
    )


def test_order_above_per_trade_cap_is_rejected_even_below_position_cap():
    # per-trade cap $5, per-position cap $50. A $10 notional order (size 20 @ 0.50) is
    # UNDER the position cap but OVER the per-trade cap -> must be rejected.
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0,
        max_per_trade_usd=5.0,
    )
    res = ex.execute(_order(size=20.0, price=0.50))  # notional = $10.00
    assert res.status.name == "REJECTED"
    assert "max per-trade" in (res.error or "")
    assert ex.positions == {}  # nothing booked


def test_order_at_or_below_per_trade_cap_is_allowed():
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0,
        max_per_trade_usd=5.0,
    )
    res = ex.execute(_order(size=10.0, price=0.50))  # notional = $5.00 == cap
    assert res.status.name != "REJECTED", res.error


def test_none_disables_the_per_trade_gate():
    # Standalone/harness default: no per-trade cap => a $10 order is bounded only by the
    # position cap ($50) and goes through, exactly as before this change.
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0,
        max_per_trade_usd=None,
    )
    res = ex.execute(_order(size=20.0, price=0.50))  # notional = $10.00
    assert res.status.name != "REJECTED", res.error


def _scan_result(edge: float = 0.10, entry_price: float = 0.50, confidence: float = 0.80):
    from unittest.mock import MagicMock
    from app.prediction_markets.polymarket_client import ScanResult

    return ScanResult(
        market=MagicMock(),  # sizing never reads .market
        strategy="test",
        outcome_idx=0,
        side="BUY",
        entry_price=entry_price,
        expected_value=confidence,
        edge=edge,
        confidence=confidence,
        reason="test",
    )


def test_kelly_bet_is_clamped_to_per_trade_cap_not_dropped():
    # The reviewer's catch: without a clamp, a normal Kelly bet (well above $5) would be
    # REJECTED outright at the gate, starving the paper-validation loop. The correct
    # behavior is to RESIZE down to the cap and still trade.
    from app.prediction_markets.orchestrator import size_from_scan_result, KellyConfig

    cfg = KellyConfig(use_monte_carlo=False)  # deterministic (no sim pricing)
    r = _scan_result()
    bet_uncapped, contracts_uncapped = size_from_scan_result(r, bankroll=1000.0, config=cfg)
    assert bet_uncapped > 5.0, "fixture must Kelly-size above the cap to be meaningful"

    bet_capped, contracts_capped = size_from_scan_result(
        r, bankroll=1000.0, config=cfg, max_per_trade_usd=5.0
    )
    assert bet_capped == pytest.approx(5.0)      # resized DOWN to the ceiling
    assert contracts_capped > 0                  # NOT dropped
    assert contracts_capped < contracts_uncapped


def test_clamped_order_passes_the_executor_gate():
    # The resized order's notional (= contracts*price < bet_usd <= cap) must PASS the
    # executor's per-trade gate — i.e. resize-then-execute, never gate-reject.
    from app.prediction_markets.orchestrator import size_from_scan_result, KellyConfig

    cfg = KellyConfig(use_monte_carlo=False)
    _bet, contracts = size_from_scan_result(
        _scan_result(), bankroll=1000.0, config=cfg, max_per_trade_usd=5.0
    )
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0, max_per_trade_usd=5.0
    )
    res = ex.execute(_order(size=contracts, price=0.50))
    assert res.status.name != "REJECTED", res.error


def test_none_cap_leaves_sizing_unchanged():
    from app.prediction_markets.orchestrator import size_from_scan_result, KellyConfig

    cfg = KellyConfig(use_monte_carlo=False)
    r = _scan_result()
    bet_none, _ = size_from_scan_result(r, bankroll=1000.0, config=cfg, max_per_trade_usd=None)
    bet_default, _ = size_from_scan_result(r, bankroll=1000.0, config=cfg)  # default None
    assert bet_none == pytest.approx(bet_default)
    assert bet_none > 5.0  # unclamped


def test_get_executor_wires_the_setting_from_config(monkeypatch):
    # The production singleton must READ MAX_PER_TRADE_USD from settings and pass it to the
    # executor (previously it was never wired, so the ceiling was inert on the real path).
    # Asserting the attribute proves the wiring without depending on the executor's DB
    # rehydration (order-level rejection is already covered by the direct-construction tests).
    import app.prediction_markets.execution as execution
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_per_trade_usd", 3.0, raising=False)
    monkeypatch.setattr(execution, "_executor", None, raising=False)
    try:
        ex = execution.get_executor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
        assert ex.max_per_trade_usd == pytest.approx(3.0)
    finally:
        execution._executor = None
