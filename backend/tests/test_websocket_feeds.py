"""Tests for the live WebSocket price-feed validation (deep-audit hardening).

DETERMINISTIC + OFFLINE: feeds raw JSON messages into PolymarketWSFeed._handle_message
and asserts that malformed prices never poison the in-memory cache.

The defect this pins: the live WS path did a bare ``float(change["price"])`` with NO
validation, so ``"inf"`` / ``"nan"`` / ``"1.5"`` / ``"-0.2"`` would silently corrupt the
price cache that strategies + the executor read. The batch discovery path is guarded by
DataQualityValidator; this feed was not. The fix rejects non-finite / out-of-[0,1] values
(keeping the last good price) and logs loudly.
"""

from __future__ import annotations

import json

from backend.app.prediction_markets.websocket_feeds import (
    PolymarketWSFeed,
    _coerce_nonneg,
    _coerce_prob,
)


# ---------------------------------------------------------------------------
# Pure coercion helpers
# ---------------------------------------------------------------------------
def test_coerce_prob_accepts_in_range():
    assert _coerce_prob("0.62", "price", "t") == 0.62
    assert _coerce_prob(0.0, "price", "t") == 0.0
    assert _coerce_prob(1.0, "price", "t") == 1.0


def test_coerce_prob_rejects_out_of_range_and_nonfinite():
    assert _coerce_prob("1.5", "price", "t") is None
    assert _coerce_prob("-0.2", "price", "t") is None
    assert _coerce_prob("inf", "price", "t") is None
    assert _coerce_prob("nan", "price", "t") is None
    assert _coerce_prob("not-a-number", "price", "t") is None
    assert _coerce_prob(None, "price", "t") is None


def test_coerce_nonneg_rejects_negative_and_nonfinite():
    assert _coerce_nonneg("10", "size", "t") == 10.0
    assert _coerce_nonneg("-1", "size", "t") is None
    assert _coerce_nonneg("inf", "size", "t") is None
    assert _coerce_nonneg("nan", "size", "t") is None


# ---------------------------------------------------------------------------
# _handle_message end-to-end
# ---------------------------------------------------------------------------
def _msg(changes):
    return json.dumps({"type": "price_change", "changes": changes})


def test_valid_price_change_updates_cache():
    feed = PolymarketWSFeed()
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 0.7, "bid": 0.69, "ask": 0.71}]))
    p = feed._prices["tokA"]
    assert p.price == 0.7
    assert p.bid == 0.69
    assert p.ask == 0.71


def test_out_of_range_price_does_not_poison_cache():
    feed = PolymarketWSFeed()
    # seed a good price first
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 0.7}]))
    # now a garbage update must be rejected, leaving the good price intact
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 1.5}]))
    assert feed._prices["tokA"].price == 0.7
    feed._handle_message(_msg([{"asset_id": "tokA", "price": "inf"}]))
    assert feed._prices["tokA"].price == 0.7
    feed._handle_message(_msg([{"asset_id": "tokA", "price": "nan"}]))
    assert feed._prices["tokA"].price == 0.7


def test_bad_bid_ask_skipped_but_valid_price_applied():
    feed = PolymarketWSFeed()
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 0.5, "bid": "inf", "ask": 2.0}]))
    p = feed._prices["tokA"]
    assert p.price == 0.5          # valid primary price applied
    assert p.bid == 0.0            # invalid bid rejected -> default unchanged
    assert p.ask == 0.0            # invalid ask rejected


def test_garbage_only_price_never_creates_a_poisoned_entry():
    feed = PolymarketWSFeed()
    feed._handle_message(_msg([{"asset_id": "tokNEW", "price": 9.9}]))
    # the update is skipped (continue) before commit; no entry is created at all
    assert "tokNEW" not in feed._prices


def test_last_trade_price_validation():
    feed = PolymarketWSFeed()
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 0.4}]))
    # valid last trade
    feed._handle_message(json.dumps({"type": "last_trade_price", "asset_id": "tokA", "price": 0.45, "size": 12}))
    assert feed._prices["tokA"].last_trade_price == 0.45
    assert feed._prices["tokA"].last_trade_size == 12.0
    # garbage last trade rejected (last good preserved)
    feed._handle_message(json.dumps({"type": "last_trade_price", "asset_id": "tokA", "price": "inf", "size": -5}))
    assert feed._prices["tokA"].last_trade_price == 0.45
    assert feed._prices["tokA"].last_trade_size == 12.0


def test_garbage_last_trade_does_not_refresh_timestamp():
    # A flood of all-invalid last-trade messages must NOT keep renewing the timestamp on a
    # stale cached quote (that would defeat the 300s staleness eviction). The timestamp only
    # advances when at least one field is accepted.
    feed = PolymarketWSFeed()
    feed._handle_message(_msg([{"asset_id": "tokA", "price": 0.4}]))
    feed._handle_message(json.dumps({"type": "last_trade_price", "asset_id": "tokA", "price": 0.45, "size": 12}))
    ts_after_good = feed._prices["tokA"].timestamp
    # an all-garbage last trade (bad price AND bad size) must leave the timestamp untouched
    feed._handle_message(json.dumps({"type": "last_trade_price", "asset_id": "tokA", "price": "inf", "size": -5}))
    assert feed._prices["tokA"].timestamp == ts_after_good
