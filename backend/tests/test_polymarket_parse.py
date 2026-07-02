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


# ============================================================
# get_order_book: no fabricated spread from an empty / one-sided / malformed book
# (deep-audit 2026-07-01 — the data analog of a fake fill; mirrors the Kalshi
# one-sided-book fix and the #101 parse-honesty fix). An empty book used to
# fabricate best_bid=0.0 / best_ask=1.0 -> a bogus 100%-wide spread a strategy reads
# as a real quote (strategies.py uses book.spread).
# ============================================================

def _client_with_book(book_data):
    """A PolymarketClient whose CLOB _get returns a fixed book payload."""
    c = _client()
    c._get = lambda *a, **k: book_data  # type: ignore[assignment]
    return c


def test_order_book_empty_returns_none_no_fabricated_spread():
    c = _client_with_book({"bids": [], "asks": []})
    assert c.get_order_book("tok") is None


def test_order_book_one_sided_returns_none():
    # Bids only (no asks) must NOT fabricate best_ask=1.0 / spread~1.0.
    c = _client_with_book({"bids": [{"price": "0.40", "size": "100"}], "asks": []})
    assert c.get_order_book("tok") is None
    # Asks only (no bids) is equally not a two-sided quote.
    c2 = _client_with_book({"bids": [], "asks": [{"price": "0.60", "size": "100"}]})
    assert c2.get_order_book("tok") is None


def test_order_book_non_finite_level_is_dropped():
    # An 'inf'/'nan' price must never enter the book. Here the only ask is inf -> the
    # ask side is empty after cleaning -> one-sided -> None (no inf in best_ask/spread).
    c = _client_with_book({
        "bids": [{"price": "0.40", "size": "100"}],
        "asks": [{"price": "inf", "size": "100"}],
    })
    assert c.get_order_book("tok") is None


def test_order_book_out_of_range_and_bad_size_dropped():
    # Price > 1 and non-positive size are invalid levels; dropped. With a valid level
    # remaining on each side the book is honest.
    c = _client_with_book({
        "bids": [{"price": "1.50", "size": "100"}, {"price": "0.45", "size": "50"}],
        "asks": [{"price": "0.55", "size": "0"}, {"price": "0.55", "size": "50"}],
    })
    book = c.get_order_book("tok")
    assert book is not None
    assert book.best_bid == 0.45 and book.best_ask == 0.55
    assert book.spread == 0.55 - 0.45
    assert all(0.0 <= b["price"] <= 1.0 and b["size"] > 0 for b in book.bids)
    assert all(0.0 <= a["price"] <= 1.0 and a["size"] > 0 for a in book.asks)


def test_order_book_valid_two_sided_preserved():
    c = _client_with_book({
        "bids": [{"price": "0.48", "size": "200"}],
        "asks": [{"price": "0.52", "size": "150"}],
    })
    book = c.get_order_book("tok")
    assert book is not None
    assert book.best_bid == 0.48 and book.best_ask == 0.52
    assert abs(book.spread - 0.04) < 1e-9


def test_get_market_by_id_queries_the_id_filter_not_slug():
    # Resolution stores the numeric Gamma id; get_market_by_id must query the ``id``
    # filter (the field positions carry), not the slug filter.
    c = _client()
    seen = {}

    def _fake_get(url, params=None):
        seen["params"] = params
        return None  # no market; we only assert the query param here

    c._get = _fake_get  # type: ignore[assignment]
    assert c.get_market_by_id("253591") is None
    assert seen["params"] == {"id": "253591"}
    # Empty id short-circuits without a query.
    seen.clear()
    assert c.get_market_by_id("") is None
    assert "params" not in seen


# ---------------------------------------------------------------------------
# A genuinely MISSING outcomePrices field must NOT be fabricated as 50/50
# ---------------------------------------------------------------------------
def test_missing_outcomePrices_field_marks_untradeable_no_fabrication():
    # outcomes + clobTokenIds are present + consistent (2 each), but the
    # ``outcomePrices`` KEY is entirely ABSENT (Gamma schema drift / a partial row).
    # PRE-FIX: raw.get("outcomePrices", "0.5,0.5") fabricated [0.5, 0.5] -> length
    # matches labels -> parse_incomplete stayed False -> active=True with invented
    # 50/50 prices that pass DataQualityValidator (the data analog of a fake fill).
    # POST-FIX: absent -> [] -> length mismatch -> untradeable.
    raw = _base_raw()
    del raw["outcomePrices"]
    m = _client()._parse_market(raw)
    assert m.active is False
    # no outcome carries a fabricated 0.5 as a real (tradeable) price
    assert all(o.price != 0.5 for o in m.outcomes)


def test_present_outcomePrices_still_parsed_normally():
    # Control: when the field IS present the happy path is unchanged (guards against
    # the fix over-reaching and breaking well-formed markets).
    m = _client()._parse_market(_base_raw())
    assert m.active is True
    assert [round(o.price, 6) for o in m.outcomes] == [0.62, 0.38]


def test_missing_outcomes_field_marks_untradeable_no_fabricated_labels():
    # outcomePrices + clobTokenIds present + consistent (2 each) but the ``outcomes``
    # KEY is ABSENT. PRE-FIX: raw.get("outcomes", "Yes,No") fabricated ["Yes","No"] ->
    # length-matched -> active=True with INVENTED labels (a non-Yes/No market would be
    # mislabeled, misassigning trade semantics). POST-FIX: absent -> [] -> mismatch ->
    # untradeable.
    raw = _base_raw()
    del raw["outcomes"]
    m = _client()._parse_market(raw)
    assert m.active is False


def test_all_outcome_arrays_absent_is_untradeable_not_empty_active():
    # Every parallel array absent: pre-fix defaults ("Yes,No" + "0.5,0.5" + []) produced a
    # mismatch already, but the <2-outcomes guard also pins the degenerate case where all
    # three are absent/empty (n_labels==0) so it can never emit active=True with 0 outcomes.
    raw = _base_raw()
    del raw["outcomes"]
    del raw["outcomePrices"]
    del raw["clobTokenIds"]
    m = _client()._parse_market(raw)
    assert m.active is False
    assert len(m.outcomes) < 2
