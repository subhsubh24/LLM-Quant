"""Regression tests for the per-strategy drawdown auto-disable circuit (ROADMAP D2).

The drawdown-based auto-disable gates on ``trades >= strategy_disable_min_trades``.
The trade COUNTER (``_strategy_trades``) used to be incremented only inside
``record_execution`` from ``result.raw_response.get("strategy")`` — but the venue /
dry-run order payload never carries a ``strategy`` tag, so the counter stayed 0 and the
gate could NEVER pass. The auto-disable was therefore structurally dead: a strategy could
blow through an arbitrary drawdown and never be disabled.

The fix counts each realized (closed) trade in ``record_pnl`` (the only call site that
receives the real strategy name). These tests pin the fixed behaviour and would FAIL on
the pre-fix code (``trades`` never reaches ``min_trades`` -> never disabled).
"""

from backend.app.prediction_markets.risk_manager import RiskManager, RiskConfig


def _drawdown_sequence(rm: RiskManager, strategy: str):
    """Establish a peak, then draw down 20% over enough closed trades to arm the gate.

    peak=100 after the first winning close, then 4 losses of -5 bring the value to 80,
    i.e. exactly a 20% drawdown after 5 realized trades (== the default min_trades).
    """
    rm.record_pnl(strategy, +100.0)  # trade 1: current=peak=100
    rm.record_pnl(strategy, -5.0)    # trade 2: 95  (5% dd)
    rm.record_pnl(strategy, -5.0)    # trade 3: 90  (10% dd)
    rm.record_pnl(strategy, -5.0)    # trade 4: 85  (15% dd)
    rm.record_pnl(strategy, -5.0)    # trade 5: 80  (20% dd) -> disable fires here


def test_strategy_disabled_after_drawdown_over_min_trades():
    """A strategy that draws down >= threshold over >= min_trades closed trades is disabled."""
    rm = RiskManager()
    assert rm.config.strategy_disable_min_trades == 5
    assert rm.config.strategy_disable_drawdown == 0.20

    _drawdown_sequence(rm, "flash_crash")

    # The counter now advances on every closed trade, so the min_trades gate is satisfied
    # and the >=20% drawdown trips the disable.
    assert rm._strategy_trades["flash_crash"] == 5
    assert "flash_crash" in rm._disabled_strategies


def test_drawdown_below_min_trades_does_not_disable():
    """The gate must still respect min_trades: a big drawdown in too FEW trades is ignored."""
    rm = RiskManager()
    # Peak then a single -30 close: 30% drawdown, but only 2 trades (< min_trades=5).
    rm.record_pnl("market_making", +100.0)  # trade 1: peak=100
    rm.record_pnl("market_making", -30.0)   # trade 2: 70 (30% dd) but trades=2
    assert rm._strategy_trades["market_making"] == 2
    assert "market_making" not in rm._disabled_strategies


def test_no_drawdown_never_disables():
    """A profitable strategy (new peak each trade) is never disabled regardless of count."""
    rm = RiskManager()
    for _ in range(10):
        rm.record_pnl("near_certainty", +5.0)  # monotonically rising -> current always == peak
    assert rm._strategy_trades["near_certainty"] == 10
    assert "near_certainty" not in rm._disabled_strategies


def test_counter_independent_across_strategies():
    """Each strategy's trade counter is isolated (no cross-contamination)."""
    rm = RiskManager()
    rm.record_pnl("a", +10.0)
    rm.record_pnl("a", -1.0)
    rm.record_pnl("b", +10.0)
    assert rm._strategy_trades["a"] == 2
    assert rm._strategy_trades["b"] == 1
    # Neither hit the drawdown+min_trades gate.
    assert not rm._disabled_strategies
