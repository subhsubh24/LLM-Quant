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

from app.prediction_markets.polymarket_history_fetcher import (
    CLOB_API,
    GAMMA_API,
    PolymarketHistoryFetcher,
    ResolvedMarket,
    _last_pre_decision_price,
)
from app.prediction_markets.walk_forward import (
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


def test_pager_respects_gamma_100_row_cap():
    """Gamma silently caps each /markets response at 100 rows regardless of the requested
    ``limit`` (verified live). A pager that used ``limit`` as the stride and stopped on
    ``len(data) < limit`` would see the first (capped) 100-row page as "short"
    (100 < 500) and stop after ONE page — silently under-sampling by up to ``max_pages``
    worth of history. The pager must cap its per-page stride to the real cap and keep
    paging. Proven to FAIL pre-fix (returns only 100 rows across a single ``limit=500``
    page)."""
    CAP = 100
    corpus = [_gamma_market(f"m{i}", ["1", "0"]) for i in range(250)]

    def router(url, params):
        offset = (params or {}).get("offset", 0)
        # Emulate Gamma: ignore the requested limit, return <= 100 rows from offset.
        return corpus[offset:offset + CAP]

    session = FakeSession(router)
    out = PolymarketHistoryFetcher(session=session).fetch_resolved_markets(limit=500, max_pages=5)

    # All 250 markets fetched across pages of 100/100/50 — NOT truncated to 100.
    assert len(out) == 250
    # The pager capped its stride to the real Gamma page size and advanced offsets in
    # steps of 100 (not 500), so no rows were skipped or re-fetched, and it stopped on the
    # genuinely short final page (50 < 100) rather than on the first (capped) page.
    gamma_calls = [c for c in session.calls if c["url"] == f"{GAMMA_API}/markets"]
    assert [c["params"]["offset"] for c in gamma_calls] == [0, 100, 200]
    assert all(c["params"]["limit"] == 100 for c in gamma_calls)


# ---------------------------------------------------------------------------
# A7 — POINT-IN-TIME / earlier-life sampling
# ---------------------------------------------------------------------------
START = RESOLUTION - timedelta(days=8)   # an 8-day market life


def _resolved_with_start(*, start=START, token="yes-1", outcome=1):
    return ResolvedMarket(
        market_id="1", condition_id="cond-1", question="Q?", category="politics",
        yes_token_id=token, no_token_id="no-1", resolution_time=RESOLUTION,
        outcome=outcome, volume=1000.0, liquidity=50.0, start_date=start,
    )


def test_startdate_parsed_into_resolved_market():
    """The Gamma startDate is captured on ResolvedMarket (None when absent)."""
    with_start = dict(
        _gamma_market("1", ["1", "0"]),
        startDate=START.isoformat().replace("+00:00", "Z"),
    )
    fetcher = PolymarketHistoryFetcher(session=FakeSession(lambda u, p: [with_start] if (p and p.get("offset", 0) == 0) else []))
    out = fetcher.fetch_resolved_markets(limit=500, max_pages=2)
    assert len(out) == 1 and out[0].start_date == START
    # and a market with NO startDate parses to start_date=None (honest, no fabrication)
    fetcher2 = PolymarketHistoryFetcher(session=FakeSession(lambda u, p: [_gamma_market("2", ["1", "0"])] if (p and p.get("offset", 0) == 0) else []))
    out2 = fetcher2.fetch_resolved_markets(limit=500, max_pages=2)
    assert len(out2) == 1 and out2[0].start_date is None


def test_fraction_zero_samples_at_market_open():
    """fraction=0.0 → decision_time == start_date (maximum edge headroom)."""
    tick = int((START - timedelta(hours=1)).timestamp())  # a tick just before open
    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.50}]})
    )
    hm = fetcher.to_historical_market_at_fraction(_resolved_with_start(), fraction=0.0)
    assert hm.decision_time == START
    assert hm.market_price == 0.50


def test_fraction_midpoint_samples_earlier_than_a_short_lead():
    """fraction=0.5 draws the decision at the MIDDLE of the market's life; the price is
    still the last PRE-decision tick, and a later (closer-to-resolution) tick is ignored."""
    decision_time = START + 0.5 * (RESOLUTION - START)   # == RESOLUTION - 4d
    pre = int((decision_time - timedelta(days=1)).timestamp())   # before decision
    post = int((decision_time + timedelta(days=1)).timestamp())  # after decision — ignore
    settled = int(RESOLUTION.timestamp())                        # at resolution — ignore

    def router(url, params):
        assert url == f"{CLOB_API}/prices-history"
        return {"history": [
            {"t": pre, "p": 0.62},
            {"t": post, "p": 0.88},
            {"t": settled, "p": 1.0},
        ]}

    hm = PolymarketHistoryFetcher(session=FakeSession(router)).to_historical_market_at_fraction(
        _resolved_with_start(), fraction=0.5
    )
    assert hm.decision_time == decision_time
    assert hm.market_price == 0.62          # last PRE-decision tick, not 0.88 and not 1.0
    assert hm.decision_time < hm.resolution_time


def test_fraction_leakage_guard_holds_even_when_sampled_early():
    """No tick at/after resolution is ever used, regardless of how early decision_time is."""
    decision_time = START + 0.1 * (RESOLUTION - START)
    pre = int((decision_time - timedelta(hours=6)).timestamp())

    def router(url, params):
        return {"history": [
            {"t": pre, "p": 0.30},
            {"t": int(RESOLUTION.timestamp()), "p": 1.0},   # settled — must NOT be used
        ]}

    hm = PolymarketHistoryFetcher(session=FakeSession(router)).to_historical_market_at_fraction(
        _resolved_with_start(), fraction=0.1
    )
    assert hm.market_price == 0.30


def test_fraction_without_start_date_raises():
    """A market with no captured start_date cannot be life-fraction sampled — RAISES,
    never fabricates a start."""
    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": 0, "p": 0.5}]})
    )
    with pytest.raises(ValueError, match="no start_date"):
        fetcher.to_historical_market_at_fraction(_resolved_with_start(start=None), fraction=0.5)


def test_fraction_out_of_range_raises():
    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": 0, "p": 0.5}]})
    )
    for bad in (-0.1, 1.0, 1.5):
        with pytest.raises(ValueError, match="fraction must be"):
            fetcher.to_historical_market_at_fraction(_resolved_with_start(), fraction=bad)


def test_build_at_fraction_skips_markets_without_start_or_price():
    """Batch helper keeps only leakage-safe fraction records, skipping no-start /
    no-pre-decision-tick markets (loud warning)."""
    decision_time = START + 0.5 * (RESOLUTION - START)
    good_tick = int((decision_time - timedelta(hours=1)).timestamp())
    good = _resolved_with_start(token="yes-good")
    no_start = ResolvedMarket("2", "c", "q", "politics", "yes-2", "no-2", RESOLUTION,
                              1, 100.0, 10.0)  # start_date defaults None

    def router(url, params):
        if params.get("market") == "yes-good":
            return {"history": [{"t": good_tick, "p": 0.44}]}
        return {"history": [{"t": int(RESOLUTION.timestamp()), "p": 0.0}]}

    out = PolymarketHistoryFetcher(session=FakeSession(router)).build_historical_markets_at_fraction(
        [good, no_start], fraction=0.5
    )
    assert [m.market_id for m in out] == ["1"]
    assert out[0].market_price == 0.44


def test_fraction_sampling_is_reproducible():
    decision_time = START + 0.25 * (RESOLUTION - START)
    tick = int((decision_time - timedelta(hours=2)).timestamp())
    fetcher = PolymarketHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.55}]})
    )
    hm = fetcher.to_historical_market_at_fraction(_resolved_with_start(), fraction=0.25)
    r1 = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    r2 = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    assert r1.seed_hash == r2.seed_hash and r1.total_pnl_usd == r2.total_pnl_usd


# ---------------------------------------------------------------------------
# NaN-timestamp finiteness hardening of the anti-leakage core (data-integrity)
# ---------------------------------------------------------------------------
def test_nan_timestamp_does_not_poison_decision_price():
    """A NaN timestamp fails every ordered comparison silently; WITHOUT the finiteness
    guard it pins best_t=NaN and blocks every later real tick → returns the fabricated
    0.99. This test is proven to FAIL on pre-fix code (returns 0.99 instead of 0.62)."""
    hist = [
        {"t": float("nan"), "p": 0.99},   # malformed API tick
        {"t": 1000.0, "p": 0.55},
        {"t": 1200.0, "p": 0.62},         # the true last pre-decision tick
    ]
    price = _last_pre_decision_price(hist, decision_ts=1300.0, resolution_ts=1500.0)
    assert price == 0.62


def test_inf_timestamp_rejected_from_decision_price():
    hist = [{"t": float("inf"), "p": 0.99}, {"t": 900.0, "p": 0.44}]
    assert _last_pre_decision_price(hist, decision_ts=1000.0, resolution_ts=1500.0) == 0.44


def test_order_param_forwarded_default_and_override():
    """The Gamma sort field is forwarded. Default is 'endDate' (back-compat); callers can
    pass order='volumeNum' to harvest markets that actually traded (OA-11 real-data run)."""
    session = FakeSession(lambda u, p: [])
    fetcher = PolymarketHistoryFetcher(session=session)

    fetcher.fetch_resolved_markets(limit=10, max_pages=1)
    assert session.calls[-1]["params"]["order"] == "endDate"

    fetcher.fetch_resolved_markets(limit=10, max_pages=1, order="volumeNum")
    assert session.calls[-1]["params"]["order"] == "volumeNum"


# ---------------------------------------------------------------------------
# tag_id: Gamma SERVER-SIDE category filter — the fix for the volumeNum per-category
# sampling ceiling (EXP-005 Sports N~135). It MUST be the INTEGER tag_id: verified live
# 2026-07-10 that Gamma silently ignores a string `tag` but honors integer `tag_id`. Every
# paged request must carry it; absent by default (back-compat). Filtering at the source (not
# just the local `categories` filter) is what lets a niche category reach testable N.
# ---------------------------------------------------------------------------
def test_tag_id_absent_by_default():
    """Back-compat: no tag_id arg → no 'tag_id' key on any Gamma request."""
    session = FakeSession(lambda u, p: [])
    PolymarketHistoryFetcher(session=session).fetch_resolved_markets(limit=10, max_pages=1)
    assert "tag_id" not in session.calls[-1]["params"]


def test_tag_id_forwarded_to_every_page():
    """tag_id must reach Gamma on EVERY page (server-side filter), so the whole max_pages
    budget is spent inside the target category rather than on the globally highest-volume
    markets that starve it.

    Fixture forces >1 page: page 0 returns a FULL page (page_size=10 rows) so the
    short-page-break does NOT fire, and page 1 (offset=10) returns a short page so paging
    stops after recording it — exercising the tag_id on ≥2 recorded requests."""
    page0 = [_gamma_market(f"s{i}", ["1", "0"]) for i in range(10)]  # full page → continue
    page1 = [_gamma_market("s10", ["1", "0"])]                        # short page → stop

    def router(url, params):
        off = params.get("offset", 0)
        if off == 0:
            return page0
        if off == 10:
            return page1
        return []

    session = FakeSession(router)
    fetcher = PolymarketHistoryFetcher(session=session)
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=3, order="volumeNum", tag_id=100639)

    assert len(session.calls) >= 2, f"tag_id test must exercise >1 page, got {len(session.calls)}"
    for call in session.calls:
        assert call["params"].get("tag_id") == 100639, (
            f"tag_id missing/wrong on a paged request: {call['params']}"
        )
    # The filter does not break parsing — the 11 settled markets all yield records.
    assert [m.market_id for m in out] == [f"s{i}" for i in range(10)] + ["s10"]
