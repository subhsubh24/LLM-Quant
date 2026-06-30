"""Tests for PolymarketClient._parse_market outcome-array honesty (deep-audit hardening).

DETERMINISTIC + OFFLINE: no real network. Constructs raw Gamma-shaped dicts and asserts
the parser never FABRICATES a price for an incomplete/inconsistent market.

The defect this pins: the parser used to pad a missing token_id with "" and a missing or
garbage price with a hardcoded 0.5 — inventing a "tradeable 50/50" market out of nothing
(an Outcome at 0.5 passes DataQualityValidator since 0.5 ∈ [0,1], so the fabrication would
flow downstream as a real price; the data analog of a fake fill). The fix marks any such
market UNTRADEABLE (active=False) and logs loudly, mirroring the Kalshi one-sided-book fix.
"""

from __future__ import annotations

from backend.app.prediction_markets.polymarket_client import PolymarketClient


def _client() -> PolymarketClient:
    return PolymarketClient()


def _base_raw(**overrides):
    raw = {
        "id": "mkt-1",
        "conditionId": "cond-1",
        "question": "Will X happen?",
        "slug": "will-x",
        "description": "",
        "category": "test",
        "active": True,
        "closed": False,
        "outcomes": '["Yes","No"]',
        "outcomePrices": '["0.62","0.38"]',
        "clobTokenIds": '["tokA","tokB"]',
    }
    raw.update(overrides)
    return raw


# ---------------------------------------------------------------------------
# Happy path is unchanged (no false positives)
# ---------------------------------------------------------------------------
def test_well_formed_binary_market_is_tradeable_and_prices_preserved():
    m = _client()._parse_market(_base_raw())
    assert m.active is True
    assert [round(o.price, 6) for o in m.outcomes] == [0.62, 0.38]
    assert [o.token_id for o in m.outcomes] == ["tokA", "tokB"]


# ---------------------------------------------------------------------------
# Inconsistent arrays -> untradeable, no fabricated 0.5
# ---------------------------------------------------------------------------
def test_more_labels_than_prices_marks_untradeable_no_fabrication():
    # 3 labels but only 2 prices + 2 tokens -> the 3rd outcome would have been 0.5/"".
    raw = _base_raw(
        outcomes='["Yes","No","Maybe"]',
        outcomePrices='["0.62","0.38"]',
        clobTokenIds='["tokA","tokB"]',
    )
    m = _client()._parse_market(raw)
    assert m.active is False, "incomplete market must be marked untradeable"
    # the third outcome must NOT be a fabricated 0.5 tradeable price
    assert m.outcomes[2].price != 0.5
    assert m.outcomes[2].token_id == ""


def test_more_tokens_than_labels_marks_untradeable():
    raw = _base_raw(clobTokenIds='["tokA","tokB","tokC"]')
    m = _client()._parse_market(raw)
    assert m.active is False


def test_missing_token_id_marks_untradeable():
    raw = _base_raw(clobTokenIds='["tokA",""]')
    m = _client()._parse_market(raw)
    assert m.active is False


# ---------------------------------------------------------------------------
# Out-of-range / non-finite prices -> untradeable, never a tradeable fabricated value
# ---------------------------------------------------------------------------
def test_out_of_range_price_marks_untradeable():
    raw = _base_raw(outcomePrices='["1.5","0.38"]')
    m = _client()._parse_market(raw)
    assert m.active is False


def test_negative_price_marks_untradeable():
    raw = _base_raw(outcomePrices='["-0.2","0.38"]')
    m = _client()._parse_market(raw)
    assert m.active is False


def test_nan_price_marks_untradeable():
    # JSON has no NaN literal; emulate via CSV fallthrough that yields a non-finite float.
    raw = _base_raw(outcomePrices="nan,0.38")
    m = _client()._parse_market(raw)
    assert m.active is False
    # no outcome is left at the old hardcoded 0.5
    assert all(o.price != 0.5 for o in m.outcomes)


def test_already_closed_market_stays_untradeable_even_if_complete():
    raw = _base_raw(active=False)
    m = _client()._parse_market(raw)
    assert m.active is False
