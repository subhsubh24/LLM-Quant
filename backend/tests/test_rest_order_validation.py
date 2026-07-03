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


def test_filled_result_carries_entry_price():
    # A REST FILLED result must carry filled_price = the limit price (a limit order fills
    # at or better than its limit). It previously defaulted to 0.0 — a live fill would then
    # build a Position with avg_entry_price=0.0, so realized PnL = settlement*size (all gain,
    # no cost basis) and the entry fee 0, corrupting the loss-cap / kill-switch counters.
    # PROVEN to FAIL pre-fix (filled_price defaulted 0.0). Mirrors the CLOB path.
    ex = _executor({"success": True, "orderID": "abc", "status": "matched", "matchedAmount": 10})
    req = _req()
    res = ex._place_via_rest(req)
    assert res.status == OrderStatus.FILLED
    assert res.filled_price == pytest.approx(req.price)
    assert req.price > 0.0  # guard the assertion is non-vacuous


def test_filled_result_none_price_does_not_produce_none_fill():
    # req.price is Optional[float] and None is schema-valid for GTC/FOK — the order is then
    # submitted at the `req.price or 0.50` default (execution.py order-build). A FILLED result
    # must reflect that effective submitted price, NEVER None: a None filled_price would build
    # a Position with avg_entry_price=None and crash the downstream market_value / PnL math
    # (float * None) AFTER a real order was placed. (Reviewer-A catch.)
    ex = _executor({"success": True, "orderID": "abc", "status": "matched", "matchedAmount": 5})
    req = OrderRequest(
        exchange=Exchange.POLYMARKET, market_id="0xmkt", token_id="tok",
        side=OrderSide.BUY, order_type=OrderType.GTC, size=5, price=None,
    )
    res = ex._place_via_rest(req)
    assert res.status == OrderStatus.FILLED
    assert res.filled_price is not None
    assert res.filled_price == pytest.approx(0.50)  # the effective submitted limit


def test_connection_exception_error_is_type_only_not_raw_internals():
    # Error-message hygiene (§12): when the venue call raises (a connection/timeout error),
    # OrderResult.error must expose only the exception TYPE, never the raw str (which leaks
    # host:port / requests internals) — this field reaches the execute HTTP response
    # (routes.py:479). PROVEN to FAIL pre-fix (error was str(e) containing the hostname).
    import requests as _requests

    class _RaisingSession:
        headers: dict = {}

        def post(self, *a, **k):
            raise _requests.ConnectionError(
                "HTTPSConnectionPool(host='clob.polymarket.com', port=443): Max retries exceeded"
            )

    ex = PolymarketExecutor(api_key="k", api_secret="s", passphrase="p")
    ex.session = _RaisingSession()
    ex._build_auth_headers = lambda *a, **k: {}
    res = ex._place_via_rest(_req())
    assert res.status == OrderStatus.REJECTED
    assert res.error == "ConnectionError"
    assert "polymarket.com" not in (res.error or "")
    assert "port" not in (res.error or "")


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
