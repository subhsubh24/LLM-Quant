"""Tests for kalshi_client.KalshiClient (ROADMAP A3).

DETERMINISTIC + OFFLINE: no real network. A FakeSession returns canned JSON
and records every .get() call so we can assert timeout=15.

Coverage:
  * Field mapping: every Market/Outcome field correctly parsed from raw Kalshi JSON.
  * Price conversion: Kalshi cent prices -> probabilities (yes_bid=48, yes_ask=52 -> 0.50).
  * YES + NO prices sum to exactly 1.0 (binary market invariant).
  * Status mapping: "open" -> active; "finalized"/"settled" -> closed+resolved;
    "closed" -> closed-not-resolved.
  * Outcomes are well-formed Outcome objects with YES and NO labels.
  * fetched_at is timezone-aware UTC.
  * Malformed market (missing ticker) is skipped gracefully.
  * Every HTTP call uses timeout=15.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.prediction_markets.kalshi_client import KalshiClient
from app.prediction_markets.polymarket_client import Market, Outcome


# ---------------------------------------------------------------------------
# Fake HTTP infrastructure (no real network)
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Records every .get (url, params, timeout) and returns canned payload."""

    def __init__(self, payload):
        self._payload = payload
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self._payload)


def _make_raw_market(
    ticker="KXTEST-25DEC",
    title="Will X happen?",
    subtitle="A subtitle",
    yes_bid=48,
    yes_ask=52,
    volume=10000.0,
    status="open",
    result="",
    category="politics",
    close_time="2025-12-25T12:00:00Z",
):
    """Build a minimal raw Kalshi /markets item."""
    return {
        "ticker": ticker,
        "title": title,
        "subtitle": subtitle,
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": 100 - yes_ask,
        "no_ask": 100 - yes_bid,
        "volume": volume,
        "status": status,
        "result": result,
        "category": category,
        "close_time": close_time,
    }


def _markets_response(*raw_markets):
    return {"markets": list(raw_markets)}


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------
def test_parse_market_field_mapping():
    raw = _make_raw_market(
        ticker="KXFOO-25JAN",
        title="Will foo happen?",
        subtitle="A description",
        category="sports",
        yes_bid=60,
        yes_ask=64,
        volume=5000.0,
        status="open",
        close_time="2025-01-31T18:00:00Z",
    )
    session = FakeSession(_markets_response(raw))
    client = KalshiClient(session=session)
    markets = client.get_markets(limit=10)

    assert len(markets) == 1
    m = markets[0]
    assert isinstance(m, Market)
    assert m.id == "KXFOO-25JAN"
    assert m.condition_id == "KXFOO-25JAN"
    assert m.slug == "kxfoo-25jan"
    assert m.question == "Will foo happen?"
    assert m.description == "A description"
    assert m.category == "sports"
    assert m.total_volume == 5000.0
    assert m.liquidity == 0.0
    assert m.resolution_source == "kalshi"
    assert m.neg_risk is False
    assert m.end_date is not None
    assert m.end_date.year == 2025


def test_parse_market_outcomes_well_formed():
    raw = _make_raw_market(yes_bid=30, yes_ask=34)
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]

    assert len(m.outcomes) == 2
    yes_out, no_out = m.outcomes
    assert isinstance(yes_out, Outcome)
    assert isinstance(no_out, Outcome)
    assert yes_out.label == "Yes"
    assert no_out.label == "No"
    assert yes_out.token_id == "KXTEST-25DEC-YES"
    assert no_out.token_id == "KXTEST-25DEC-NO"


# ---------------------------------------------------------------------------
# Price conversion: cents -> probabilities
# ---------------------------------------------------------------------------
def test_price_conversion_midpoint():
    """yes_bid=48, yes_ask=52 -> mid=50 cents -> YES=0.50, NO=0.50."""
    raw = _make_raw_market(yes_bid=48, yes_ask=52)
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]

    yes_out = m.outcomes[0]
    no_out = m.outcomes[1]
    assert abs(yes_out.price - 0.50) < 1e-9
    assert abs(no_out.price - 0.50) < 1e-9


def test_price_conversion_asymmetric():
    """yes_bid=70, yes_ask=74 -> mid=72 cents -> YES=0.72, NO=0.28."""
    raw = _make_raw_market(yes_bid=70, yes_ask=74)
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]

    yes_price = m.outcomes[0].price
    no_price = m.outcomes[1].price
    assert abs(yes_price - 0.72) < 1e-9
    assert abs(no_price - 0.28) < 1e-9


def test_price_conversion_near_zero():
    """yes_bid=2, yes_ask=4 -> mid=3 cents -> YES=0.03, NO=0.97."""
    raw = _make_raw_market(yes_bid=2, yes_ask=4)
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]

    assert abs(m.outcomes[0].price - 0.03) < 1e-9
    assert abs(m.outcomes[1].price - 0.97) < 1e-9


def test_price_conversion_near_one():
    """yes_bid=96, yes_ask=98 -> mid=97 cents -> YES=0.97, NO=0.03."""
    raw = _make_raw_market(yes_bid=96, yes_ask=98)
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]

    assert abs(m.outcomes[0].price - 0.97) < 1e-9
    assert abs(m.outcomes[1].price - 0.03) < 1e-9


# ---------------------------------------------------------------------------
# YES + NO sum to 1
# ---------------------------------------------------------------------------
def test_yes_no_sum_to_one():
    """Binary market invariant: YES + NO must sum to exactly 1.0."""
    for yes_bid, yes_ask in [(10, 14), (48, 52), (80, 84), (0, 2), (98, 100)]:
        raw = _make_raw_market(yes_bid=yes_bid, yes_ask=yes_ask)
        session = FakeSession(_markets_response(raw))
        m = KalshiClient(session=session).get_markets()[0]
        total = sum(o.price for o in m.outcomes)
        assert abs(total - 1.0) < 1e-9, (
            f"YES+NO should sum to 1.0, got {total} for yes_bid={yes_bid}, yes_ask={yes_ask}"
        )


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------
def test_status_open():
    raw = _make_raw_market(status="open")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True
    assert m.closed is False
    assert m.resolved is False


def test_status_finalized():
    raw = _make_raw_market(status="finalized", result="yes")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.closed is True
    assert m.resolved is True


def test_status_settled():
    raw = _make_raw_market(status="settled", result="no")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.closed is True
    assert m.resolved is True


def test_status_closed_not_resolved():
    raw = _make_raw_market(status="closed", result="")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.closed is True
    assert m.resolved is False


def test_status_unknown_defaults():
    raw = _make_raw_market(status="something_unknown")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.closed is False
    assert m.resolved is False


# --- Real Kalshi response-side contract values (NOT the request-side filter words).
# These are the values a live /markets response actually carries; a prior cut only
# handled the request-FILTER words ("open"/"finalized") and would have dropped every
# live market. (Offline-validated against the documented contract; verify on first run.)
def test_status_active_is_the_real_tradeable_value():
    """Live Kalshi response markets carry status 'active' (not 'open')."""
    raw = _make_raw_market(status="active")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True
    assert m.closed is False
    assert m.resolved is False


def test_status_determined_is_resolved():
    """'determined' (winner decided, awaiting settlement) is resolved, not still-live."""
    raw = _make_raw_market(status="determined", result="yes")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.resolved is True


# --- One-sided / empty order books must not fabricate a midpoint or a fake 50/50.
def test_one_sided_book_uses_the_quoted_side():
    """yes_bid=95, no ask → YES≈0.95 (use the quoted side, never average with 0)."""
    raw = _make_raw_market(yes_bid=95, yes_ask=0, status="active")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert abs(m.outcomes[0].price - 0.95) < 1e-9
    assert m.active is True  # one real quote → still tradeable


def test_last_price_fallback_when_no_book():
    """No bid/ask but a last_price → use it (80¢ → 0.80)."""
    raw = _make_raw_market(yes_bid=0, yes_ask=0, status="active")
    raw["last_price"] = 80
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert abs(m.outcomes[0].price - 0.80) < 1e-9
    assert m.active is True


def test_no_quote_market_is_forced_untradeable_not_fabricated_5050():
    """A 0/0 book with no last_price must NOT present a tradeable 0.50 market."""
    raw = _make_raw_market(yes_bid=0, yes_ask=0, status="active")  # no last_price
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False  # forced untradeable despite 'active' status
    # YES+NO still internally consistent (placeholder), but it can never be traded.
    assert abs((m.outcomes[0].price + m.outcomes[1].price) - 1.0) < 1e-9


def test_out_of_range_bid_ask_not_clamped_to_fabricated_certainty():
    """An out-of-range cent quote (>100) must be REJECTED, not silently clamped to a
    fabricated 1.0 certain-outcome price. yes_bid=150 (a glitch/contract change) with no
    valid last_price -> untradeable, never a tradeable 100%-YES market invented from
    garbage. Mirrors the last_price branch's existing (0,100] bound."""
    raw = _make_raw_market(yes_bid=150, yes_ask=160, status="active")  # both out of range
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False  # rejected -> has_quote False -> untradeable
    # And it did NOT surface a fabricated certain-YES price.
    assert m.outcomes[0].price != 1.0


def test_out_of_range_bid_falls_back_to_valid_ask():
    """One garbage side (yes_bid=150) must be dropped while the valid side (yes_ask=40)
    still prices the market — the out-of-range value must never poison the midpoint."""
    raw = _make_raw_market(yes_bid=150, yes_ask=40, status="active")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True                       # the valid ask keeps it tradeable
    assert abs(m.outcomes[0].price - 0.40) < 1e-9  # priced from the valid side alone


# ---------------------------------------------------------------------------
# CURRENT dollar-string quote schema (yes_bid_dollars / yes_ask_dollars / ...).
# As of 2026-07 the live elections API returns the legacy cents fields as null and
# carries the real quote ONLY in the *_dollars fields (each already a probability in
# [0,1]). A cents-only read marked EVERY live market untradeable — these lock in the
# dual-schema behaviour + the honesty rule (a 0/missing dollar quote is not a 50/50).
# ---------------------------------------------------------------------------
def _dollar_raw_market(
    ticker="KXBTCMAXY-26DEC31-99999.99",
    title="Will BTC reach $100k?",
    status="active",
    yes_bid_dollars="0.1400",
    yes_ask_dollars="0.1500",
    last_price_dollars=None,
    volume_fp="1185441.10",
    close_time="2026-12-31T12:00:00Z",
):
    """A raw Kalshi market in the CURRENT schema: cents fields null, quotes in *_dollars."""
    raw = {
        "ticker": ticker,
        "title": title,
        "subtitle": "",
        "yes_bid": None,
        "yes_ask": None,
        "last_price": None,
        "volume": None,
        "status": status,
        "result": "",
        "category": "Crypto",
        "close_time": close_time,
        "yes_bid_dollars": yes_bid_dollars,
        "yes_ask_dollars": yes_ask_dollars,
        "volume_fp": volume_fp,
    }
    if last_price_dollars is not None:
        raw["last_price_dollars"] = last_price_dollars
    return raw


def test_dollar_schema_midpoint_prices_the_market():
    """cents null, yes_bid_dollars=0.14 / yes_ask_dollars=0.15 -> YES mid = 0.145."""
    raw = _dollar_raw_market()
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True  # a real dollar quote keeps it tradeable
    assert abs(m.outcomes[0].price - 0.145) < 1e-9
    assert abs((m.outcomes[0].price + m.outcomes[1].price) - 1.0) < 1e-9


def test_dollar_schema_is_the_regression_guard_for_the_live_api():
    """The exact live-API shape (cents all null) must NOT mark the market untradeable —
    this is the bug the fix closes: a cents-only read returned has_quote=False here."""
    raw = _dollar_raw_market(yes_bid_dollars="0.1000", yes_ask_dollars="0.1100")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True
    assert abs(m.outcomes[0].price - 0.105) < 1e-9


def test_dollar_schema_one_sided_uses_quoted_side():
    """Only yes_bid_dollars quoted -> use it (never average with a missing side)."""
    raw = _dollar_raw_market(yes_bid_dollars="0.9500", yes_ask_dollars=None)
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True
    assert abs(m.outcomes[0].price - 0.95) < 1e-9


def test_dollar_schema_last_price_fallback():
    """No dollar book but a last_price_dollars -> use it (0.80)."""
    raw = _dollar_raw_market(yes_bid_dollars=None, yes_ask_dollars=None,
                             last_price_dollars="0.8000")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is True
    assert abs(m.outcomes[0].price - 0.80) < 1e-9


def test_zero_dollar_quote_is_forced_untradeable_not_fabricated_5050():
    """A '0.0000' dollar quote is a no-book placeholder, NOT a tradeable 0% market —
    it must fall through to untradeable, mirroring the 0-cent honesty rule."""
    raw = _dollar_raw_market(yes_bid_dollars="0.0000", yes_ask_dollars="0.0000")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False  # forced untradeable despite 'active' status
    assert abs((m.outcomes[0].price + m.outcomes[1].price) - 1.0) < 1e-9


def test_out_of_range_dollar_quote_rejected_not_clamped():
    """A garbage dollar quote (>1, e.g. a schema glitch) must be REJECTED, never clamped
    to a fabricated certainty."""
    raw = _dollar_raw_market(yes_bid_dollars="1.5000", yes_ask_dollars="1.6000")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False
    assert m.outcomes[0].price != 1.0


def test_legacy_cents_take_precedence_over_dollars_when_both_present():
    """Back-compat: if BOTH schemas carry a usable quote, the legacy cents win (existing
    callers/fixtures are unchanged). cents mid 0.50 beats dollars 0.145."""
    raw = _dollar_raw_market()
    raw["yes_bid"], raw["yes_ask"] = 48, 52  # legacy cents present
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert abs(m.outcomes[0].price - 0.50) < 1e-9


def test_volume_fp_fallback_when_legacy_volume_null():
    """Volume falls back to the fixed-point string field when legacy `volume` is null."""
    raw = _dollar_raw_market(volume_fp="1234.50")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert abs(m.total_volume - 1234.50) < 1e-9


def test_no_quote_on_either_schema_is_untradeable():
    """Neither cents nor dollars quoted -> untradeable, never a fabricated 50/50."""
    raw = _dollar_raw_market(yes_bid_dollars=None, yes_ask_dollars=None)
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.active is False


def test_series_ticker_is_forwarded_as_a_query_param():
    """Per-series discovery (the B8 co-listed numeric universe is reachable only
    per-series) forwards series_ticker to the /markets query."""
    session = FakeSession(_markets_response(_dollar_raw_market()))
    KalshiClient(session=session).get_markets(series_ticker="KXBTCMAXY", status="open")
    assert session.calls, "expected at least one HTTP call"
    params = session.calls[0]["params"]
    assert params.get("series_ticker") == "KXBTCMAXY"
    assert session.calls[0]["timeout"] == 15  # the hard per-request deadline still holds


# ---------------------------------------------------------------------------
# fetched_at is timezone-aware UTC
# ---------------------------------------------------------------------------
def test_fetched_at_is_timezone_aware_utc():
    raw = _make_raw_market()
    session = FakeSession(_markets_response(raw))
    m = KalshiClient(session=session).get_markets()[0]
    assert m.fetched_at is not None
    assert m.fetched_at.tzinfo is not None
    # Should be UTC (offset 0)
    assert m.fetched_at.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# Malformed market (missing ticker) is skipped gracefully
# ---------------------------------------------------------------------------
def test_missing_ticker_skipped_gracefully():
    """A market with no ticker field must be skipped, not crash the batch."""
    good = _make_raw_market(ticker="KXGOOD-25DEC")
    bad = {"title": "No ticker here", "yes_bid": 50, "yes_ask": 50, "status": "open"}
    session = FakeSession(_markets_response(bad, good))
    markets = KalshiClient(session=session).get_markets()
    # Only the good market survives.
    assert len(markets) == 1
    assert markets[0].id == "KXGOOD-25DEC"


def test_empty_markets_list_returns_empty():
    session = FakeSession({"markets": []})
    markets = KalshiClient(session=session).get_markets()
    assert markets == []


def test_missing_markets_key_returns_empty():
    """If the response is a dict with no 'markets' key, return []."""
    session = FakeSession({"error": "not found"})
    markets = KalshiClient(session=session).get_markets()
    assert markets == []


def test_null_response_returns_empty():
    session = FakeSession(None)
    markets = KalshiClient(session=session).get_markets()
    assert markets == []


# ---------------------------------------------------------------------------
# Every HTTP call uses timeout=15
# ---------------------------------------------------------------------------
def test_every_get_uses_timeout_15():
    raw = _make_raw_market()
    session = FakeSession(_markets_response(raw))
    KalshiClient(session=session).get_markets()
    assert session.calls
    assert all(c["timeout"] == 15 for c in session.calls)


# ---------------------------------------------------------------------------
# Import check: Market and Outcome come from polymarket_client (not redefined)
# ---------------------------------------------------------------------------
def test_imports_market_outcome_from_polymarket_client():
    """KalshiClient must import (not redefine) Market and Outcome from polymarket_client."""
    from app.prediction_markets import polymarket_client as pm
    from app.prediction_markets import kalshi_client as kc

    # The Market/Outcome names used in kalshi_client must be the SAME objects.
    assert kc.Market is pm.Market
    assert kc.Outcome is pm.Outcome


# ---------------------------------------------------------------------------
# Multiple markets in a single response
# ---------------------------------------------------------------------------
def test_multiple_markets_parsed():
    raws = [
        _make_raw_market(ticker=f"KX{i}-25DEC", yes_bid=40 + i, yes_ask=44 + i)
        for i in range(5)
    ]
    session = FakeSession(_markets_response(*raws))
    markets = KalshiClient(session=session).get_markets()
    assert len(markets) == 5
    ids = {m.id for m in markets}
    assert ids == {f"KX{i}-25DEC" for i in range(5)}


# ---------------------------------------------------------------------------
# Non-finite volume must NOT survive into the Market. `_to_float(...) or 0.0`
# would keep a NaN (NaN is truthy), and a NaN/inf volume slips past the
# strategy volume filter (`NaN < min_volume` is False) — the same
# invented-data-into-the-decision class the Polymarket parser guards against.
# ---------------------------------------------------------------------------
def test_nan_volume_falls_back_to_zero():
    raw = _make_raw_market(volume="nan")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.total_volume == 0.0
    assert m.total_volume == m.total_volume  # not NaN


def test_inf_volume_falls_back_to_zero():
    raw = _make_raw_market(volume="Infinity")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.total_volume == 0.0
    assert m.volume_below(1000.0) is True  # 0.0 is genuinely below → filter works


def test_finite_volume_still_parsed():
    raw = _make_raw_market(volume="4200.5")
    m = KalshiClient(session=FakeSession(_markets_response(raw))).get_markets()[0]
    assert m.total_volume == 4200.5


# ---------------------------------------------------------------------------
# Structured strike parsing (ROADMAP B8) — floor_strike/cap_strike/strike_type
# ---------------------------------------------------------------------------
def test_parse_market_structured_strike_greater():
    """A real-shaped Kalshi crypto market carries its strike ONLY in the structured
    floor_strike/strike_type fields (generic title). The parser must capture them."""
    raw = _make_raw_market(
        ticker="KXBTCD-26JUL06-T72249.99",
        title="Bitcoin price on Jul 6, 2026?",  # generic title, no strike in text
        category="Financials",
        yes_bid=3,
        yes_ask=5,
    )
    raw["floor_strike"] = 72249.99
    raw["strike_type"] = "greater"
    client = KalshiClient(session=FakeSession(_markets_response(raw)))
    m = client.get_markets(limit=10)[0]
    assert m.floor_strike == 72249.99
    assert m.cap_strike is None
    assert m.strike_type == "greater"


def test_parse_market_structured_strike_less():
    """A cap-defined (<=) market captures cap_strike + strike_type."""
    raw = _make_raw_market(ticker="KXETHD-26JUL06-C4000", title="Ethereum price?")
    raw["cap_strike"] = 4000.0
    raw["strike_type"] = "less"
    client = KalshiClient(session=FakeSession(_markets_response(raw)))
    m = client.get_markets(limit=10)[0]
    assert m.cap_strike == 4000.0
    assert m.floor_strike is None
    assert m.strike_type == "less"


def test_parse_market_no_strike_fields_defaults_none():
    """A market with NO structured strike fields (e.g. a plain political market) leaves
    all three fields None — backward-compatible with every pre-B8 payload."""
    raw = _make_raw_market()  # no strike fields
    client = KalshiClient(session=FakeSession(_markets_response(raw)))
    m = client.get_markets(limit=10)[0]
    assert m.floor_strike is None
    assert m.cap_strike is None
    assert m.strike_type is None


def test_parse_market_strike_type_normalized_and_garbage_floor_is_none():
    """strike_type is lower/stripped; a non-finite/garbage floor_strike coerces to None
    (never fabricated) while a valid strike_type is still preserved."""
    raw = _make_raw_market(ticker="KXBTCMAXY-26DEC31-T110000", title="Bitcoin max this year?")
    raw["floor_strike"] = "not-a-number"
    raw["strike_type"] = "  Greater  "
    client = KalshiClient(session=FakeSession(_markets_response(raw)))
    m = client.get_markets(limit=10)[0]
    assert m.floor_strike is None  # garbage coerced away, not fabricated
    assert m.strike_type == "greater"  # normalized
