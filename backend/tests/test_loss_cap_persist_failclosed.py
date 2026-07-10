"""Regression (D3/D4 durability): a realized LOSS that cannot be DURABLY persisted must
fail CLOSED — trip the kill switch — so a restart cannot reset the accumulated loss budget.

The hard loss caps gate on `_realized_pnl_total` / `_realized_pnl_daily`, which are persisted
on every realization so a restart re-loads them. But `_persist_state` is best-effort: if the
durable store's `save` FAILS (e.g. the DB write primary is down while reads still work), the
loss lived only in memory. On the next restart `_rehydrate_state` loads the last GOOD row —
the PRE-loss counters — silently handing back loss headroom the cap already spent, and each
further un-persisted loss compounds the bypass.

The fix: when a realized loss cannot be durably recorded, `record_realized_pnl` trips the
in-memory kill switch (fail-closed), halting new orders this session and bounding the
un-persisted loss to that single realization. A profit / break-even update never trips (it
cannot spend loss headroom), and the paper default (no store attached) is unaffected.

Deterministic; no heavy deps.
"""

import pytest

from app.prediction_markets.execution import PredictionMarketExecutor


class _FailingSaveStore:
    """A store that rehydrates cleanly (no prior state) but whose SAVE always fails —
    modeling a reachable-for-reads / unavailable-for-writes durable store."""

    def load(self):
        return None  # no persisted state → clean rehydrate, no boot-time trip

    def save(self, snapshot):
        raise RuntimeError("simulated durable-store write failure")


class _OkStore:
    """A healthy store: rehydrates clean, saves succeed, and records the last snapshot."""

    def __init__(self):
        self.saved = None

    def load(self):
        return None

    def save(self, snapshot):
        self.saved = snapshot


def _executor(total_cap=1000.0, daily_cap=1000.0):
    # Caps set high so the losses under test do NOT breach a cap — this isolates the
    # persist-failure fail-closed branch from the ordinary cap-breach auto-trip.
    return PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=daily_cap, max_total_loss_usd=total_cap,
    )


def test_unpersistable_loss_trips_kill_switch_fail_closed():
    ex = _executor()
    ex.attach_state_store(_FailingSaveStore())
    assert not ex._kill_switch_active, "clean rehydrate must not pre-trip the kill switch"

    ex.record_realized_pnl(-5.0)  # a loss well under the cap; persist WILL fail

    assert ex._kill_switch_active, (
        "a realized loss that could not be durably persisted must fail CLOSED (halt), "
        "so a restart cannot reset the loss budget"
    )
    assert "loss-persist failure" in ex._kill_switch_reason
    # The in-memory counter still reflects the loss for THIS session's gate.
    assert ex._realized_pnl_total == pytest.approx(-5.0)


def test_persisted_loss_under_cap_does_not_trip():
    ex = _executor()
    store = _OkStore()
    ex.attach_state_store(store)

    ex.record_realized_pnl(-5.0)  # under the cap AND persisted fine

    assert not ex._kill_switch_active, (
        "a successfully-persisted loss under the cap must NOT trip the kill switch"
    )
    assert store.saved is not None, "a healthy store must have recorded the loss snapshot"
    assert store.saved["realized_pnl_total"] == pytest.approx(-5.0)


def test_paper_default_no_store_loss_does_not_trip():
    ex = _executor()  # no store attached — the paper default
    ex.record_realized_pnl(-5.0)
    assert not ex._kill_switch_active, (
        "the no-store paper path has nothing to persist and must never fail-closed on a loss"
    )
    assert ex._realized_pnl_total == pytest.approx(-5.0)


def test_profit_with_failing_store_does_not_trip():
    ex = _executor()
    ex.attach_state_store(_FailingSaveStore())
    ex.record_realized_pnl(+8.0)  # a PROFIT cannot spend loss headroom → never fail-closed
    assert not ex._kill_switch_active, (
        "a profit/break-even update must never trip, even if its persist fails"
    )


def test_breakeven_with_failing_store_does_not_trip():
    ex = _executor()
    ex.attach_state_store(_FailingSaveStore())
    ex.record_realized_pnl(0.0)
    assert not ex._kill_switch_active
