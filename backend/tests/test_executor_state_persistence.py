"""
Tests for durable executor SAFETY-state persistence (ROADMAP D3/D4 / run-risk-readiness).

A backend restart must NOT silently un-trip a halted kill switch or reset the accumulated
realized-loss budget. These tests prove, on an in-memory SQLite engine:

  * a tripped kill switch REHYDRATES as tripped on a fresh executor;
  * accumulated daily/total realized PnL rehydrates;
  * a stale DAILY tally from a previous UTC day does NOT carry into a new day;
  * a bare executor (no store) is unaffected — fully isolated, fresh state (so the existing
    deterministic tests / runtime harness keep their isolation);
  * persistence is best-effort — a store whose save/load raises never breaks the trade path.

Deterministic, in-memory, no network.
"""

from datetime import datetime, timezone, timedelta

import pytest
from sqlmodel import create_engine

from backend.app.prediction_markets.execution import PredictionMarketExecutor
from backend.app.prediction_markets.executor_state_store import (
    ExecutorStateStore,
    PredictionExecutorStateRow,
    init_db,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    init_db(eng)
    return eng


def _executor_with_store(engine):
    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    ex.attach_state_store(ExecutorStateStore(engine=engine))
    return ex


def test_kill_switch_survives_restart(engine):
    ex = _executor_with_store(engine)
    ex.activate_kill_switch("manual-halt")
    assert ex.kill_switch_active

    # "Restart": a brand-new executor wired to the SAME store rehydrates.
    ex2 = _executor_with_store(engine)
    assert ex2.kill_switch_active is True
    assert ex2._kill_switch_reason == "manual-halt"


def test_deactivate_persists_across_restart(engine):
    ex = _executor_with_store(engine)
    ex.activate_kill_switch("halt")
    ex.deactivate_kill_switch()
    assert not ex.kill_switch_active

    ex2 = _executor_with_store(engine)
    assert ex2.kill_switch_active is False
    assert ex2._kill_switch_reason == ""


def test_realized_pnl_counters_survive_restart(engine):
    ex = _executor_with_store(engine)
    ex.record_realized_pnl(-7.50)
    ex.record_realized_pnl(-2.25)
    assert ex._realized_pnl_total == pytest.approx(-9.75)
    assert ex._realized_pnl_daily == pytest.approx(-9.75)

    ex2 = _executor_with_store(engine)
    assert ex2._realized_pnl_total == pytest.approx(-9.75)
    assert ex2._realized_pnl_daily == pytest.approx(-9.75)


def test_loss_cap_breach_rehydrates_as_tripped(engine):
    # Total cap $10; realize -$15 -> auto-trip. A restart must keep it halted.
    ex = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=1000.0, max_total_loss_usd=10.0,
    )
    ex.attach_state_store(ExecutorStateStore(engine=engine))
    ex.record_realized_pnl(-15.0)
    assert ex.kill_switch_active

    ex2 = PredictionMarketExecutor(
        dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=1000.0, max_total_loss_usd=10.0,
    )
    ex2.attach_state_store(ExecutorStateStore(engine=engine))
    assert ex2.kill_switch_active is True
    assert ex2._realized_pnl_total == pytest.approx(-15.0)


def test_stale_daily_tally_does_not_carry_into_new_day(engine):
    # Persist a daily loss dated to YESTERDAY; on rehydrate the day has rolled, so the
    # DAILY tally must reset to 0 (never carry a stale daily loss forward) while the
    # TOTAL is preserved.
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    store = ExecutorStateStore(engine=engine)
    store.save({
        "kill_switch_active": False,
        "kill_switch_reason": "",
        "kill_switch_time": None,
        "realized_pnl_total": -40.0,
        "realized_pnl_daily": -40.0,
        "loss_cap_day": yesterday,
    })

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    ex.attach_state_store(store)
    assert ex._realized_pnl_total == pytest.approx(-40.0)  # total preserved
    assert ex._realized_pnl_daily == pytest.approx(0.0)    # stale daily reset
    assert ex._loss_cap_day == datetime.now(timezone.utc).date()


def test_bare_executor_has_no_persistence_and_fresh_state(engine):
    # A bare executor (no store) must not be polluted by persisted state — the existing
    # tests / runtime harness rely on this isolation.
    seeded = _executor_with_store(engine)
    seeded.activate_kill_switch("halt")

    bare = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    assert bare.kill_switch_active is False
    assert bare._realized_pnl_total == 0.0
    # And a bare executor's mutations never touch the DB.
    bare.record_realized_pnl(-3.0)
    bare.activate_kill_switch("x")
    # The store still only has the seeded row's state, untouched by `bare`.
    reloaded = ExecutorStateStore(engine=engine).load()
    assert reloaded["kill_switch_reason"] == "halt"


def test_save_failure_is_best_effort_never_breaks_trade_path(engine):
    # A store that LOADS cleanly (empty) but whose SAVE raises must never break the trade
    # path — every mutation's persist is best-effort and swallows the error.
    class _SaveBoomStore:
        def load(self):
            return None  # empty -> clean rehydrate (no fail-safe trip)

        def save(self, state):
            raise RuntimeError("boom-save")

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    ex.attach_state_store(_SaveBoomStore())
    assert ex.kill_switch_active is False  # clean empty load -> NOT failed-closed
    ex.activate_kill_switch("halt")  # would call save -> raises internally -> swallowed
    ex.record_realized_pnl(-1.0)
    assert ex.kill_switch_active is True  # in-memory state still correct


def test_rehydrate_failure_fails_closed(engine):
    # FAIL SAFE: if the durable store is attached but its load() RAISES (e.g. the DB is
    # unreachable at startup), the executor cannot confirm there was no persisted halt —
    # it must BLOCK trading (kill switch ACTIVE) rather than silently resume with fresh,
    # un-halted state. Leaving fresh state would let a boot-time DB hiccup resurrect a
    # killed bot.
    class _LoadBoomStore:
        def load(self):
            raise RuntimeError("db-unreachable")

        def save(self, state):
            raise RuntimeError("db-unreachable")

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    ex.attach_state_store(_LoadBoomStore())
    assert ex.kill_switch_active is True
    assert ex._kill_switch_reason.startswith("state_rehydrate_failed")
    # And the gate honours it: any order is rejected while failed-closed.
    from backend.app.prediction_markets.execution import (
        OrderRequest, OrderSide, OrderType, Exchange,
    )
    res = ex.execute(OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m", token_id="t",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=1.0, price=0.5,
    ))
    assert res.status.name == "REJECTED"


def test_save_then_load_roundtrip_is_faithful(engine):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    store = ExecutorStateStore(engine=engine)
    store.save({
        "kill_switch_active": True,
        "kill_switch_reason": "loss_cap: TOTAL",
        "kill_switch_time": now,
        "realized_pnl_total": -12.34,
        "realized_pnl_daily": -5.0,
        "loss_cap_day": now.date().isoformat(),
    })
    got = store.load()
    assert got["kill_switch_active"] is True
    assert got["kill_switch_reason"] == "loss_cap: TOTAL"
    assert got["realized_pnl_total"] == pytest.approx(-12.34)
    assert got["realized_pnl_daily"] == pytest.approx(-5.0)
    assert got["loss_cap_day"] == now.date().isoformat()


def test_load_returns_none_when_empty(engine):
    assert ExecutorStateStore(engine=engine).load() is None
