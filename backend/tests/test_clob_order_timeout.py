"""
LIVE-SAFETY (FACTORY_STANDARD §6): the py-clob-client order path must be TIME-BOUNDED.

`_place_via_clob_client` calls `create_and_sign_order` + `post_order` on py-clob-client,
which expose no timeout. `place_order` runs SYNCHRONOUSLY inside the orchestrator's async
scan loop, so a stalled venue socket would hang the ENTIRE bot indefinitely (no kill-switch
check, no further orders) — exactly the failure §6 forbids ("a graceful try/catch is useless
if the runtime hangs the function first"). The raw REST fallback is already bounded
(`timeout=15`); these tests prove the CLOB path is now bounded too, and — critically — that a
timeout is reported HONESTLY: REJECTED (never a fabricated fill), venue state flagged UNKNOWN.

Deterministic, no network, no py-clob-client dependency (a fake client stands in). The module
timeout is monkeypatched to a small value and the fake sleeps LONGER, so a bounded call
returns well before the fake would finish; an unbounded (pre-fix) call would block for the
full fake sleep. The wall-clock assertion is what proves the bound actually fired.
"""

import sys
import time
import types

import pytest

from app.prediction_markets import execution as execmod
from app.prediction_markets.execution import (
    Exchange,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PolymarketExecutor,
)


class _HangingClient:
    """Fake py-clob-client whose network call `post_order` stalls far longer than the bound."""

    def __init__(self, sleep_sec: float, hang_on: str = "post_order"):
        self._sleep = sleep_sec
        self._hang_on = hang_on

    def create_and_sign_order(self, order_args):
        if self._hang_on == "create_and_sign_order":
            time.sleep(self._sleep)
        return {"signed": True}

    def post_order(self, signed_order):
        if self._hang_on == "post_order":
            time.sleep(self._sleep)
        return {"status": "matched", "matchedAmount": "10", "orderID": "should-not-fill"}


class _FastFilledClient:
    """Fake client that returns a valid matched fill immediately (happy-path regression)."""

    def create_and_sign_order(self, order_args):
        return {"signed": True}

    def post_order(self, signed_order):
        return {"status": "matched", "matchedAmount": "10", "orderID": "ok-123"}


class _RaisingClient:
    """Fake client whose venue call raises (generic-error path must still REJECT, not leak)."""

    def create_and_sign_order(self, order_args):
        return {"signed": True}

    def post_order(self, signed_order):
        raise ConnectionResetError("connection reset by peer @ clob.polymarket.com:443")


@pytest.fixture(autouse=True)
def _stub_py_clob_client(monkeypatch):
    """`_place_via_clob_client` imports BUY/SELL from py-clob-client (a live-only dep not
    installed in CI). Stub the minimal module so the test exercises the ORDER path — not the
    ImportError branch. We inject the client object directly, so only the constants matter."""
    pkg = types.ModuleType("py_clob_client")
    order_builder = types.ModuleType("py_clob_client.order_builder")
    constants = types.ModuleType("py_clob_client.order_builder.constants")
    constants.BUY = "BUY"
    constants.SELL = "SELL"
    order_builder.constants = constants
    pkg.order_builder = order_builder
    monkeypatch.setitem(sys.modules, "py_clob_client", pkg)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder", order_builder)
    monkeypatch.setitem(sys.modules, "py_clob_client.order_builder.constants", constants)


def _executor():
    return PolymarketExecutor(api_key="k", api_secret="s", passphrase="p")


def _req():
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="0xmkt",
        token_id="tok",
        side=OrderSide.BUY,
        order_type=OrderType.GTC,
        size=10,
        price=0.50,
    )


def test_post_order_hang_is_bounded_and_rejected(monkeypatch):
    """A stalled post_order returns REJECTED within the bound — never a hang, never a fill."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()
    client = _HangingClient(sleep_sec=5.0, hang_on="post_order")

    started = time.monotonic()
    result = ex._place_via_clob_client(client, _req())
    elapsed = time.monotonic() - started

    # Bounded: returned in ~timeout, NOT after the full 5s fake sleep (pre-fix behaviour).
    assert elapsed < 2.0, f"call was not time-bounded (took {elapsed:.2f}s)"
    # Honest: a timeout is an UNKNOWN venue state → REJECTED, never a fabricated fill.
    assert result.status is OrderStatus.REJECTED
    assert result.filled_size == 0.0
    assert "timed out" in (result.error or "")
    # Error-message hygiene (§12): our own message, no venue host/stack leaked.
    assert "clob" not in (result.error or "").lower()


def test_create_and_sign_hang_is_bounded_and_rejected(monkeypatch):
    """The signing call is bounded too (both blocking venue calls are wrapped)."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()
    client = _HangingClient(sleep_sec=5.0, hang_on="create_and_sign_order")

    started = time.monotonic()
    result = ex._place_via_clob_client(client, _req())
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"signing call was not time-bounded (took {elapsed:.2f}s)"
    assert result.status is OrderStatus.REJECTED
    assert "timed out" in (result.error or "")


def test_fast_client_still_fills_normally(monkeypatch):
    """Regression: the timeout wrapper does not break the happy path — a fast fill is FILLED."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()

    result = ex._place_via_clob_client(_FastFilledClient(), _req())

    assert result.status is OrderStatus.FILLED
    assert result.filled_size == 10.0
    assert result.order_id == "ok-123"


def test_raising_client_still_rejected_via_generic_path(monkeypatch):
    """A raised venue error (not a timeout) still REJECTs and does not leak internals (§12)."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()

    result = ex._place_via_clob_client(_RaisingClient(), _req())

    assert result.status is OrderStatus.REJECTED
    # Only the exception TYPE is surfaced, never the message (which carries host:port).
    assert result.error == "ConnectionResetError"
    assert "polymarket.com" not in (result.error or "")


# --- cancel_order path (same live-safety bound; reachable from the async cancel endpoint) ---


class _HangingCancelClient:
    """Fake py-clob-client whose `cancel` network call stalls far longer than the bound."""

    def __init__(self, sleep_sec: float):
        self._sleep = sleep_sec

    def cancel(self, order_id):
        time.sleep(self._sleep)
        return {"canceled": True}


class _FastCancelClient:
    """Fake client that confirms the cancel immediately (happy-path regression)."""

    def cancel(self, order_id):
        return {"canceled": True}


def test_cancel_order_hang_is_bounded_and_reports_unconfirmed(monkeypatch):
    """A stalled cancel returns within the bound as UNCONFIRMED (False) — never a hang, never a
    fabricated success. `cancel_order` is reached from an `async def` endpoint that calls it
    synchronously, so an unbounded hang would freeze the whole event loop (the #330 failure)."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()
    monkeypatch.setattr(ex, "_get_clob_client", lambda: _HangingCancelClient(sleep_sec=5.0))

    started = time.monotonic()
    result = ex.cancel_order("order-should-not-hang")
    elapsed = time.monotonic() - started

    # Bounded: returned in ~timeout, NOT after the full 5s fake sleep (pre-fix behaviour).
    assert elapsed < 2.0, f"cancel was not time-bounded (took {elapsed:.2f}s)"
    # Honest: a timeout is an UNKNOWN venue state → UNCONFIRMED (False), never a fake success.
    assert result is False


def test_cancel_order_fast_path_still_confirms(monkeypatch):
    """Regression: the timeout wrapper does not break the happy path — a fast cancel confirms."""
    monkeypatch.setattr(execmod, "_CLOB_ORDER_TIMEOUT_SEC", 0.3)
    ex = _executor()
    monkeypatch.setattr(ex, "_get_clob_client", lambda: _FastCancelClient())

    assert ex.cancel_order("order-123") is True
