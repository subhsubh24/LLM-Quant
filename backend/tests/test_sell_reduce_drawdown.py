"""Regression tests: the SELL/partial-reduce path feeds the per-strategy drawdown circuit.

ROADMAP D2 / the QUALITY_SCORECARD correctness_reliability A->A+ gap: the resolution path
(MTM engine) already fed ``risk_manager.record_pnl``, but the SELL/partial-reduce path in
``PredictionMarketExecutor._update_position`` realized PnL that reached ONLY the executor's
global hard loss caps — never the strategy's own drawdown auto-disable. So a strategy bleeding
on REDUCES tripped the global kill switch but never its own per-strategy disable.

These tests pin the fix (executor.risk_manager wired + fed on reduce) and would FAIL on the
pre-fix code (the reduce never advanced the strategy's realized-trade counter / drawdown value).
"""

from app.prediction_markets.execution import (
    Exchange,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PredictionMarketExecutor,
)
from app.prediction_markets.risk_manager import RiskManager


def _executor_with_rm():
    ex = PredictionMarketExecutor(dry_run=True)
    rm = RiskManager()
    ex.risk_manager = rm
    return ex, rm


def _seed_long(ex, token="tok1", strategy="flash_crash", size=10.0, entry=0.60):
    ex.positions[token] = Position(
        exchange=Exchange.POLYMARKET, market_id="mkt1", token_id=token,
        market_question="Q?", outcome_label="Yes", side="long", size=size,
        avg_entry_price=entry, current_price=entry, unrealized_pnl=0.0, realized_pnl=0.0,
        strategy=strategy,
    )


def _sell(ex, token="tok1", filled_price=0.40, filled_size=10.0):
    """Drive a SELL fill that reduces the seeded long through _update_position."""
    req_side = OrderSide.SELL
    result = OrderResult(
        order_id="o1", exchange=Exchange.POLYMARKET, market_id="mkt1", token_id=token,
        side=req_side, order_type=OrderType.MARKET, size=filled_size, price=filled_price,
        status=OrderStatus.FILLED, filled_size=filled_size, filled_price=filled_price, fees=0.0,
    )
    from app.prediction_markets.execution import OrderRequest
    req = OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="mkt1", token_id=token, side=req_side,
        order_type=OrderType.MARKET, size=filled_size, price=filled_price, strategy="flash_crash",
    )
    ex._update_position(req, result)


def test_sell_reduce_feeds_risk_manager_record_pnl():
    ex, rm = _executor_with_rm()
    _seed_long(ex)
    _sell(ex)                                  # sell 10 @ 0.40, entry 0.60 -> pnl = -2.0
    # The reduce realized a loss AND fed the per-strategy drawdown circuit (pre-fix: 0).
    assert rm._strategy_trades["flash_crash"] == 1
    assert abs(rm._strategy_current_value["flash_crash"] - (-2.0)) < 1e-9


def test_sell_reduce_can_disable_a_bleeding_strategy():
    """A strategy that bleeds on REDUCES alone (never resolving) trips its OWN drawdown
    auto-disable — not merely the global kill switch. This is the whole point of D2."""
    ex, rm = _executor_with_rm()
    # trade 1: a winning close (via the risk manager directly) establishes the peak at +100.
    rm.record_pnl("flash_crash", +100.0)
    # trades 2-5: four losing reduces of -5.0 each, driven through the executor SELL path.
    # entry 0.60, sell 10 contracts @ 0.10 -> (0.10-0.60)*10 = -5.0 realized each.
    for i in range(4):
        tok = f"t{i}"
        _seed_long(ex, token=tok, size=10.0, entry=0.60)
        _sell(ex, token=tok, filled_price=0.10, filled_size=10.0)
    # 100 -> 80 over 5 realized trades == exactly the 20% drawdown at min_trades=5 -> disabled,
    # and it got there entirely through the SELL/reduce path (pre-fix: never disabled).
    assert rm._strategy_trades["flash_crash"] == 5
    assert "flash_crash" in rm._disabled_strategies


def test_reduce_records_exactly_once_no_double_count():
    ex, rm = _executor_with_rm()
    _seed_long(ex)
    _sell(ex, filled_size=4.0)                  # partial reduce -> exactly ONE record_pnl
    assert rm._strategy_trades["flash_crash"] == 1


def test_no_risk_manager_is_a_safe_noop():
    ex = PredictionMarketExecutor(dry_run=True)   # risk_manager stays None
    assert ex.risk_manager is None
    _seed_long(ex)
    _sell(ex)                                      # must not raise
    # the executor-level caps still saw the realized loss (unchanged behavior)
    assert ex._realized_pnl_total < 0


def test_orchestrator_wires_executor_risk_manager():
    from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
    orch = PredictionMarketOrchestrator()
    assert orch.executor.risk_manager is orch.risk_manager
