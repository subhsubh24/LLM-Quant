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


# ---------------------------------------------------------------------------
# The COMPLEMENT of the above: the cap-BREACH auto-trip path. A loss that breaches a
# cap AUTO-TRIPS the kill switch via activate_kill_switch(), whose persist is
# best-effort. If THAT write fails transiently, the trip must be RETRIED on subsequent
# activity so a recovered store durably records it — otherwise a readable-but-stale
# restart (the store recovered, so _rehydrate_state does NOT raise) silently un-trips
# the halt and resets the loss budget.
# ---------------------------------------------------------------------------


class _FlakySaveStore:
    """Rehydrates clean; the first ``fail_first`` saves FAIL, then saves succeed and
    record the last snapshot — models a durable store momentarily unwritable at trip
    time that then RECOVERS."""

    def __init__(self, fail_first: int = 1):
        self._remaining_failures = fail_first
        self.saved = None

    def load(self):
        return None

    def save(self, snapshot):
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("simulated transient durable-store write failure")
        self.saved = dict(snapshot)


class _PreloadedStore:
    """A store that rehydrates from a supplied snapshot (models the durable row a
    restart reads); saves are accepted no-ops."""

    def __init__(self, snapshot):
        self._snapshot = snapshot

    def load(self):
        return self._snapshot

    def save(self, snapshot):
        pass


def _low_cap_executor():
    # Caps LOW so the loss under test BREACHES the total cap → the auto-trip path
    # (activate_kill_switch), the complement of the high-cap non-breach branch above.
    return PredictionMarketExecutor(
        dry_run=True, max_position_usd=60.0, max_portfolio_usd=500.0,
        max_daily_loss_usd=10.0, max_total_loss_usd=25.0,
    )


def test_auto_trip_failed_persist_is_retried_at_order_gate_and_survives_restart():
    """The load-bearing durability fix for the cap-breach AUTO-TRIP path.

    A loss that breaches a cap auto-trips the kill switch via activate_kill_switch(),
    whose persist is best-effort. If that write FAILS transiently, pre-fix the trip lived
    only in memory: a halted bot merely REJECTS subsequent orders (no persist on that
    path — the scan loop keeps calling execute()), so once the store RECOVERS and the
    process restarts, _rehydrate_state loads the last GOOD (pre-trip) readable row and
    silently un-trips the halt. The fix retries the pending write at the order gate, so
    the recovered store durably records the trip and a restart re-loads it.

    Non-tautological: with the retry removed, the `store.saved` / `_safety_persist_pending`
    assertions below FAIL (the rejected order never re-persists).
    """
    from app.prediction_markets.execution import (
        OrderRequest, OrderSide, OrderType, Exchange,
    )

    store = _FlakySaveStore(fail_first=1)
    ex = _low_cap_executor()
    ex.attach_state_store(store)
    assert not ex._kill_switch_active, "clean rehydrate must not pre-trip"

    # A loss that breaches the $25 total cap → _enforce_loss_caps → activate_kill_switch,
    # whose (first, transient) persist FAILS — the trip is in-memory only.
    ex.record_realized_pnl(-30.0)
    assert ex._kill_switch_active, "a cap breach must auto-trip the kill switch"
    assert ex._safety_persist_pending, "a FAILED trip-persist must mark a pending retry"
    assert store.saved is None, "the failed write left NO durable trip record yet"

    # Store has recovered. The next order attempt hits _check_risk → retries the pending
    # persist (durably recording the trip), then the active kill switch rejects the order.
    req = OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="m1", token_id="t1",
        side=OrderSide.BUY, order_type=OrderType.LIMIT, size=10.0, price=0.5,
        strategy="test", market_question="Q?", outcome_label="Yes",
    )
    result = ex.execute(req)
    assert not result.is_success, "the kill switch must still reject the order"
    assert not ex._safety_persist_pending, "the order attempt must have self-healed the persist"
    assert store.saved is not None, "the recovered store must now hold a durable snapshot"
    assert store.saved["kill_switch_active"] is True, "the durable record must reflect the TRIP"

    # Restart: a fresh executor loading that durable row REHYDRATES as halted — the trip
    # is no longer lost across the restart.
    ex2 = _low_cap_executor()
    ex2.attach_state_store(_PreloadedStore(store.saved))
    assert ex2._kill_switch_active, "the durably-recorded trip must survive the restart"
