"""
SIDE-EFFECT INTEGRITY for the Polymarket REST order fallback (ROADMAP G2/F4.1, D1 fix).

An HTTP 200 from the CLOB REST `/order` endpoint is NOT proof the order was accepted —
the JSON body can carry success=false / errorMsg on a 200. Reporting OPEN off the status
code alone fabricates a resting order that never existed (and would later be settled as a
real position). These tests prove `_place_via_rest` VALIDATES the body:

  * venue refusal (success=false / errorMsg)  -> REJECTED (no fake resting order)
  * malformed / non-dict body                 -> REJECTED
  * unconfirmed acknowledgement (no id/ok)    -> REJECTED (never assume a fill)
  * confirmed match with size>0               -> FILLED
  * genuine acknowledgement (order id / live) -> OPEN

Deterministic, no network (a fake session returns canned bodies). `_build_auth_headers`
is stubbed so the test exercises ONLY the response-validation logic.
"""

import pytest

from app.prediction_markets.execution import (
    PolymarketExecutor,
    OrderRequest,
    OrderStatus,
    OrderSide,
    OrderType,
    Exchange,
)


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeSession:
    def __init__(self, body):
        self._body = body
        self.headers = {}

    def post(self, *a, **k):
        return _FakeResponse(self._body)


def _executor(body):
    ex = PolymarketExecutor(api_key="k", api_secret="s", passphrase="p")
    ex.session = _FakeSession(body)
    ex._build_auth_headers = lambda *a, **k: {}  # bypass HMAC signing; test parsing only
    return ex


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


def test_venue_refusal_success_false_rejected():
    ex = _executor({"success": False, "errorMsg": "insufficient balance"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED
    assert "insufficient balance" in (res.error or "")


def test_venue_error_field_rejected():
    ex = _executor({"error": "bad token"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED


def test_non_dict_body_rejected():
    ex = _executor(["not", "a", "dict"])
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED
    assert "malformed" in (res.error or "")


def test_empty_ack_rejected_never_assumes_open():
    # 200 with an empty body and no order id / success — must NOT be reported as a
    # resting OPEN order (the exact bug this fix closes).
    ex = _executor({})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED


def test_confirmed_match_is_filled():
    ex = _executor({"success": True, "orderID": "abc", "status": "matched", "matchedAmount": 10})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.FILLED
    assert res.order_id == "abc"
    assert res.filled_size == pytest.approx(10.0)


def test_matched_with_unparseable_size_rejected():
    ex = _executor({"success": True, "orderID": "abc", "status": "matched", "matchedAmount": "NaNish"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED


def test_genuine_ack_with_order_id_is_open():
    ex = _executor({"orderID": "xyz", "status": "live"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.OPEN
    assert res.order_id == "xyz"


def test_matched_zero_falls_through_to_open_with_order_id():
    # "matched" with a zero fill is not a fill; with an order id it rests OPEN (mirrors
    # the CLOB path), never FILLED.
    ex = _executor({"orderID": "abc", "status": "matched", "matchedAmount": 0})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.OPEN


def test_matched_non_finite_size_rejected():
    ex = _executor({"orderID": "abc", "status": "matched", "matchedAmount": "inf"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED


@pytest.mark.parametrize("st", ["rejected", "cancelled", "canceled", "expired"])
def test_terminal_status_rejected_even_with_order_id(st):
    # An order id echoed alongside a terminal NEGATIVE status must NOT be reported OPEN.
    ex = _executor({"orderID": "abc", "status": st})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED


def test_success_true_without_match_is_open():
    ex = _executor({"success": True, "orderID": "oid"})
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.OPEN


def test_unauthenticated_rejected():
    ex = PolymarketExecutor()  # no creds
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED
    assert "credentials" in (res.error or "").lower()
