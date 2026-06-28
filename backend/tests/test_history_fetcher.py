"""Tests for polymarket_history_fetcher (ROADMAP A2 / EXP-001).

DETERMINISTIC + OFFLINE: no real network. A ``FakeSession`` returns canned JSON
keyed by (url, params) and RECORDS the timeout passed to every ``.get`` call.

These tests assert the two things that make this module trustworthy:
  * it parses REAL settled markets correctly and REJECTS ambiguous ones; and
  * the anti-leakage guarantee — ``market_price`` comes from a PRE-resolution
    snapshot, never the settled outcome price, and we RAISE rather than fabricate.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.prediction_markets.polymarket_history_fetcher import (
    CLOB_API,
    GAMMA_API,
    PolymarketHistoryFetcher,
    ResolvedMarket,
)
from backend.app.prediction_markets.walk_forward import (
    HistoricalMarket,
    walk_forward_backtest,
)

RESOLUTION = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Records every ``.get`` (url, params, timeout) and replies from a routing fn.

    ``router(url, params) -> payload`` (a Python object that json() returns). The
    default headers dict mimics requests.Session so .headers.update() works.
    """

    def __init__(self, router):
        self.router = router
        self.headers = {}
        self.calls = []  # list of dicts: {url, params, timeout}

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.router(url, params))


def _gamma_market(market_id, outcome_prices, *, end_date=None, outcomes=None, token_ids=None):
    """A raw Gamma /markets row, with JSON-string-encoded parallel arrays."""
    return {
        "id": market_id,
        "conditionId": f"cond-{market_id}",
        "question": f"Question {market_id}?",
        "category": "politics",
        "outcomes": json.dumps(outcomes or ["Yes", "No"]),
        "outcomePrices": json.dumps(outcome_prices),
        "clobTokenIds": json.dumps(token_ids or [f"yes-{market_id}", f"no-{market_id}"]),
        "endDate": end_date or RESOLUTION.isoformat().replace("+00:00", "Z"),
        "volume": "12345.6",
        "liquidity": "789.0",
    }


def _resolved(outcome=1, token="yes-1"):
    return ResolvedMarket(
        market_id="1",
        condition_id="cond-1",
        question="Q?",
        category="politics",
        yes_token_id=token,
        no_token_id="no-1",
        resolution_time=RESOLUTION,
        outcome=outcome,
        volume=1000.0,
        liquidity=50.0,
    )


# ---------------------------------------------------------------------------
# Parsing: settled YES / NO, and rejection of ambiguous markets
# ---------------------------------------------------------------------------
def test_parses_yes_and_no_won_markets():
    rows = [
        _gamma_market("yeswin", ["1", "0"]),  # YES resolved → outcome 1
        _gamma_market("nowin", ["0", "1"]),   # NO resolved  → outcome 0
    ]

    def router(url, params):
        if params and params.get("offset", 0) == 0:
            return rows
        return []  # second page empty → paging stops

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=500, max_pages=5)

    by_id = {m.market_id: m for m in out}
    assert by_id["yeswin"].outcome == 1
    assert by_id["nowin"].outcome == 0
    assert by_id["yeswin"].yes_token_id == "yes-yeswin"


def test_rejects_unsettled_market():
    rows = [_gamma_market("ambiguous", ["0.6", "0.4"])]  # not settled → skipped

    def router(url, params):
        if params and params.get("offset", 0) == 0:
            return rows
        return []

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=500, max_pages=5)
    assert out == []


def test_accepts_rounded_settled_market():
    """A market settling to a rounded 0.98/0.02 (not exact 1.0/0.0) must be ACCEPTED as
    YES (the float-slop guard on SETTLE_TOL keeps it from being wrongly dropped)."""
    rows = [_gamma_market("rounded", ["0.98", "0.02"])]

    def router(url, params):
        return rows if (params and params.get("offset", 0) == 0) else []

    out = PolymarketHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets(
        limit=500, max_pages=5
    )
    assert len(out) == 1 and out[0].outcome == 1


def test_rejects_sum_violation():
    """Prices each near a settled value but NOT summing to ~1 (e.g. 0.99/0.99) are
    ambiguous and must be skipped — this exercises the sum-to-1 arm of the guard, distinct
    from the individual-price arm exercised by the 0.6/0.4 case."""
    rows = [_gamma_market("sumbad", ["0.99", "0.99"])]

    def router(url, params):
        return rows if (params and params.get("offset", 0) == 0) else []

    out = PolymarketHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets(
        limit=500, max_pages=5
    )
    assert out == []


def test_rejects_non_binary_market():
    rows = [_gamma_market("multi", ["1", "0", "0"], outcomes=["A", "B", "C"],
                          token_ids=["t1", "t2", "t3"])]

    def router(url, params):
        if params and params.get("offset", 0) == 0:
            return rows
        return []

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    assert fetcher.fetch_resolved_markets(limit=500, max_pages=5) == []


# ---------------------------------------------------------------------------
# Anti-leakage: PRE-resolution snapshot, never the settled price
# ---------------------------------------------------------------------------
def test_uses_pre_resolution_snapshot_not_resolved_price():
    """Market resolved YES (outcome 1, settled price 1.0), but the crowd price at
    decision time was 0.80. market_price MUST be 0.80, NOT 1.0."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre_tick_ts = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        assert url == f"{CLOB_API}/prices-history"
        return {"history": [
            {"t": pre_tick_ts, "p": 0.80},
            # a tick AT resolution carrying the settled price — must be ignored.
            {"t": int(RESOLUTION.timestamp()), "p": 1.0},
        ]}

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    hm = fetcher.to_historical_market(_resolved(outcome=1), decision_lead)

    assert hm.market_price == 0.80           # crowd snapshot, NOT the settled 1.0
    assert hm.model_prob == 0.80             # naive baseline defaults to crowd price
    assert hm.outcome == 1


def test_raises_when_only_post_resolution_ticks():
    """A price history with ONLY a tick at/after resolution → no leakage-safe
    snapshot exists → to_historical_market RAISES (never fabricates)."""
    decision_lead = timedelta(days=3)

    def router(url, params):
        return {"history": [
            {"t": int(RESOLUTION.timestamp()), "p": 1.0},          # AT resolution
            {"t": int((RESOLUTION + timedelta(hours=1)).timestamp()), "p": 1.0},
        ]}

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(outcome=1), decision_lead)


def test_build_historical_markets_skips_leaky():
    """Batch helper skips the market with no leakage-safe price and keeps the good
    one, returning only leakage-safe records."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    good_tick = int((decision_time - timedelta(hours=1)).timestamp())

    good = ResolvedMarket("good", "c", "q", "politics", "yes-good", "no-good",
                          RESOLUTION, 1, 100.0, 10.0)
    bad = ResolvedMarket("bad", "c", "q", "politics", "yes-bad", "no-bad",
                         RESOLUTION, 0, 100.0, 10.0)

    def router(url, params):
        token = params.get("market")
        if token == "yes-good":
            return {"history": [{"t": good_tick, "p": 0.42}]}
        return {"history": [{"t": int(RESOLUTION.timestamp()), "p": 0.0}]}  # post-only

    fetcher = PolymarketHistoryFetcher(session=FakeSession(router))
    out = fetcher.build_historical_markets([good, bad], decision_lead)

    assert [m.market_id for m in out] == ["good"]
    assert out[0].market_price == 0.42


# ---------------------------------------------------------------------------
# Produced records are valid + consumable by the backtest
# ---------------------------------------------------------------------------
def test_decision_time_strictly_before_resolution():
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())

    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.55}]})
    )
    hm = fetcher.to_historical_market(_resolved(), decision_lead)
    assert hm.decision_time < hm.resolution_time


def test_produced_record_feeds_walk_forward():
    """A produced HistoricalMarket runs through walk_forward_backtest without error."""
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())

    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.55}]})
    )
    hm = fetcher.to_historical_market(_resolved(), decision_lead)
    assert isinstance(hm, HistoricalMarket)
    assert hm.market_price == 0.55          # the pre-resolution tick, not the settled price

    # train_min_days=0 so at least one OOS window actually fires on this single market
    # (the default 28d would yield 0 windows and the backtest would silently do nothing,
    # making the assertion vacuous). Assert the engine consumed the record, produced a
    # 16-char fingerprint over >=1 window, and is REPRODUCIBLE (same input → same hash).
    result_a = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    result_b = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    assert isinstance(result_a.seed_hash, str) and len(result_a.seed_hash) == 16
    assert result_a.n_windows >= 1
    assert result_a.seed_hash == result_b.seed_hash   # deterministic / reproducible


# ---------------------------------------------------------------------------
# Safety rules: timeout=15 on every call, and max_pages bounds the loop
# ---------------------------------------------------------------------------
def test_every_get_uses_timeout_15():
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())
    session = FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.5}]})

    fetcher = PolymarketHistoryFetcher(session=session)
    fetcher.fetch_price_history("yes-1", 0, 1)
    fetcher.to_historical_market(_resolved(), decision_lead)

    assert session.calls  # something was fetched
    assert all(c["timeout"] == 15 for c in session.calls)


def test_fetch_loop_respects_max_pages():
    """FakeSession always returns a FULL page → without a bound the loop is infinite.
    max_pages must cap the number of Gamma calls."""
    full_page = [_gamma_market(f"m{i}", ["1", "0"]) for i in range(500)]

    session = FakeSession(lambda u, p: full_page)
    fetcher = PolymarketHistoryFetcher(session=session)
    fetcher.fetch_resolved_markets(limit=500, max_pages=3)

    gamma_calls = [c for c in session.calls if c["url"] == f"{GAMMA_API}/markets"]
    assert len(gamma_calls) == 3
