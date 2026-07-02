"""Tests for kalshi_history_fetcher.KalshiHistoryFetcher (ROADMAP A3).

DETERMINISTIC + OFFLINE: no real network. A FakeSession returns canned JSON and
records every .get() call so we can assert timeout=15.

These tests assert the two things that make this module trustworthy:
  * it parses REAL Kalshi resolved markets correctly and REJECTS ambiguous ones; and
  * the anti-leakage guarantee — ``market_price`` comes from a PRE-resolution
    snapshot, never the settled result, and we RAISE rather than fabricate.

Modelled on backend/tests/test_history_fetcher.py (same FakeSession pattern).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets.kalshi_history_fetcher import (
    KALSHI_BASE_URL,
    KalshiHistoryFetcher,
    KalshiResolvedMarket,
    _candle_price,
    _last_pre_decision_price,
    _series_ticker,
)
from app.prediction_markets.walk_forward import (
    HistoricalMarket,
    walk_forward_backtest,
)

RESOLUTION = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
BASE_URL = KALSHI_BASE_URL


# ---------------------------------------------------------------------------
# Fake HTTP infrastructure
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    """Records every .get (url, params, timeout) and replies from a routing fn.

    ``router(url, params) -> payload``. The default headers dict mimics
    requests.Session so .headers.update() works.
    """

    def __init__(self, router):
        self.router = router
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.router(url, params))


def _kalshi_market(
    ticker,
    result,
    status="finalized",
    category="politics",
    close_time=None,
    volume=12345.0,
):
    """Build a minimal raw Kalshi /markets item."""
    return {
        "ticker": ticker,
        "title": f"Question {ticker}?",
        "category": category,
        "status": status,
        "result": result,
        "volume": str(volume),
        "close_time": close_time or RESOLUTION.isoformat().replace("+00:00", "Z"),
    }


def _resolved(outcome=1, ticker="KXTEST-25MAR"):
    return KalshiResolvedMarket(
        ticker=ticker,
        title="Q?",
        category="politics",
        resolution_time=RESOLUTION,
        outcome=outcome,
        volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Parsing: settled YES / NO, and rejection of ambiguous markets
# ---------------------------------------------------------------------------
def test_parses_yes_and_no_resolved_markets():
    raws = [
        _kalshi_market("KXYES-25MAR", result="yes"),
        _kalshi_market("KXNO-25MAR",  result="no"),
    ]

    def router(url, params):
        if "candlesticks" in url:
            return {}
        offset = (params or {}).get("cursor") or None
        if offset is None:
            return {"markets": raws, "cursor": None}
        return {"markets": []}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=5)
    by_ticker = {m.ticker: m for m in out}

    assert by_ticker["KXYES-25MAR"].outcome == 1
    assert by_ticker["KXNO-25MAR"].outcome == 0


def test_rejects_empty_result_market():
    """A market with result='' (unresolved) must be skipped."""
    raws = [_kalshi_market("KXPENDING-25MAR", result="")]

    def router(url, params):
        return {"markets": raws, "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=5)
    assert out == []


def test_rejects_unknown_result_market():
    """result='void' / any non-yes/no string must be skipped."""
    raws = [_kalshi_market("KXVOID-25MAR", result="void")]

    def router(url, params):
        return {"markets": raws, "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=5)
    assert out == []


def test_rejects_market_missing_ticker():
    """A raw market without a 'ticker' field must be silently skipped."""
    raws = [{"result": "yes", "status": "finalized", "close_time": RESOLUTION.isoformat()}]

    def router(url, params):
        return {"markets": raws, "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=5)
    assert out == []


def test_rejects_market_missing_close_time():
    """A market with no close_time/expiration_time must be skipped."""
    raw = {
        "ticker": "KXNODATE-25MAR",
        "result": "yes",
        "status": "finalized",
        "category": "test",
        "volume": "100",
        # no close_time, no expiration_time
    }

    def router(url, params):
        return {"markets": [raw], "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=5)
    assert out == []


def test_category_filter():
    """markets with a non-matching category are dropped when categories filter supplied."""
    raws = [
        _kalshi_market("KXPOL-25MAR", result="yes", category="politics"),
        _kalshi_market("KXSPO-25MAR", result="no",  category="sports"),
    ]

    def router(url, params):
        return {"markets": raws, "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(limit=10, max_pages=1, categories=["politics"])
    assert len(out) == 1
    assert out[0].ticker == "KXPOL-25MAR"


# ---------------------------------------------------------------------------
# Anti-leakage: PRE-resolution snapshot, NEVER the settled result
# ---------------------------------------------------------------------------
def test_uses_pre_resolution_snapshot_not_settled_result():
    """Market resolved YES (outcome 1), but the crowd price at decision time was 0.75.
    market_price MUST be 0.75, NOT 1.0 (the settled result)."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre_tick_ts = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        return {
            "history": [
                {"t": pre_tick_ts, "p": 0.75},
                # Tick AT resolution with settled price — must be excluded.
                {"t": int(RESOLUTION.timestamp()), "p": 1.0},
            ]
        }

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    hm = fetcher.to_historical_market(_resolved(outcome=1), decision_lead)

    assert hm.market_price == 0.75   # pre-resolution crowd price, NOT the result
    assert hm.model_prob == 0.75     # naive baseline defaults to crowd price
    assert hm.outcome == 1


def test_fetch_uses_settled_status_filter():
    """Resolved-market discovery must request status='settled' (a VALID Kalshi filter
    value) — NOT 'finalized', which Kalshi does not accept (would return nothing)."""
    session = FakeSession(lambda url, params: {"markets": [], "cursor": None})
    KalshiHistoryFetcher(session=session).fetch_resolved_markets(limit=10, max_pages=1)
    markets_calls = [c for c in session.calls if "candlesticks" not in c["url"]]
    assert markets_calls, "no /markets request was made"
    assert markets_calls[0]["params"]["status"] == "settled"


def test_zero_price_pre_decision_tick_survives():
    """A legitimate pre-decision tick with p=0 (YES≈0) must be USED, not dropped by a
    falsy-`or` chain (which would force a spurious 'no pre-resolution tick' raise)."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre_tick_ts = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        return {"history": [{"t": pre_tick_ts, "p": 0}]}  # p==0 is valid AND falsy

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    hm = fetcher.to_historical_market(_resolved(outcome=0), decision_lead)
    assert hm.market_price == 0.0  # the p=0 tick was used, not silently dropped


def test_raises_when_only_post_resolution_ticks():
    """A price history with ONLY a tick at/after resolution -> no leakage-safe
    snapshot -> to_historical_market RAISES (never fabricates)."""
    decision_lead = timedelta(days=3)

    def router(url, params):
        return {
            "history": [
                {"t": int(RESOLUTION.timestamp()), "p": 1.0},
                {"t": int((RESOLUTION + timedelta(hours=1)).timestamp()), "p": 1.0},
            ]
        }

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(outcome=1), decision_lead)


def test_raises_when_no_ticks_at_all():
    """Empty price history -> RAISES, never fabricates."""
    decision_lead = timedelta(days=3)

    def router(url, params):
        return {"history": []}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(outcome=1), decision_lead)


def test_raises_when_only_future_ticks():
    """Ticks strictly AFTER decision_time but before resolution -> not usable as
    decision-time price -> RAISES."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    # Tick is 1 hour AFTER decision_time but before resolution.
    future_tick = int((decision_time + timedelta(hours=1)).timestamp())

    def router(url, params):
        return {"history": [{"t": future_tick, "p": 0.80}]}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(outcome=1), decision_lead)


def test_settled_result_never_used_as_decision_price():
    """The market price at decision_time must NEVER equal the settled result (1.0 or 0.0)
    when the only valid tick is pre-resolution and genuinely uncertain."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre_tick_ts = int((decision_time - timedelta(hours=2)).timestamp())

    def router(url, params):
        return {
            "history": [
                {"t": pre_tick_ts, "p": 0.65},   # the genuine pre-resolution price
                {"t": int(RESOLUTION.timestamp()), "p": 1.0},  # settled — must be excluded
            ]
        }

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    hm = fetcher.to_historical_market(_resolved(outcome=1), decision_lead)

    # The result (1.0) must NOT be the market price.
    assert hm.market_price != 1.0
    assert hm.market_price == 0.65


# ---------------------------------------------------------------------------
# Build batch: skips leaky, keeps good
# ---------------------------------------------------------------------------
def test_build_historical_markets_skips_leaky_keeps_good():
    """Batch helper skips the market with no leakage-safe price and keeps the good one."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    good_tick = int((decision_time - timedelta(hours=1)).timestamp())

    good = KalshiResolvedMarket("KXGOOD", "Good Q?", "politics", RESOLUTION, 1, 100.0)
    bad  = KalshiResolvedMarket("KXBAD",  "Bad Q?",  "politics", RESOLUTION, 0, 100.0)

    def router(url, params):
        if "KXGOOD" in url:
            return {"history": [{"t": good_tick, "p": 0.42}]}
        # KXBAD: only a tick at resolution (post-resolution) -> no valid pre-decision tick
        return {"history": [{"t": int(RESOLUTION.timestamp()), "p": 0.0}]}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.build_historical_markets([good, bad], decision_lead)

    assert [m.market_id for m in out] == ["KXGOOD"]
    assert out[0].market_price == 0.42


# ---------------------------------------------------------------------------
# Produced records are valid + consumable by the backtest
# ---------------------------------------------------------------------------
def test_decision_time_strictly_before_resolution():
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())

    fetcher = KalshiHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.55}]})
    )
    hm = fetcher.to_historical_market(_resolved(), decision_lead)
    assert hm.decision_time < hm.resolution_time


def test_produced_record_feeds_walk_forward():
    """A produced HistoricalMarket runs through walk_forward_backtest without error."""
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())

    fetcher = KalshiHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.55}]})
    )
    hm = fetcher.to_historical_market(_resolved(), decision_lead)
    assert isinstance(hm, HistoricalMarket)
    assert hm.market_price == 0.55  # the pre-resolution tick, not the settled result

    # train_min_days=0 so at least one OOS window fires on this single market.
    result_a = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    result_b = walk_forward_backtest([hm], train_min_days=0, test_window_days=7)
    assert isinstance(result_a.seed_hash, str) and len(result_a.seed_hash) == 16
    assert result_a.n_windows >= 1
    assert result_a.seed_hash == result_b.seed_hash  # deterministic


def test_produced_records_are_well_formed():
    """All HistoricalMarket fields are populated with valid values."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(hours=2)).timestamp())

    fetcher = KalshiHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.63}]})
    )
    hm = fetcher.to_historical_market(_resolved(outcome=0), decision_lead)

    assert hm.market_id == "KXTEST-25MAR"
    assert 0.0 <= hm.market_price <= 1.0
    assert 0.0 <= hm.model_prob <= 1.0
    assert hm.outcome in (0, 1)
    assert hm.decision_time < hm.resolution_time
    assert hm.market_price == 0.63


# ---------------------------------------------------------------------------
# Safety rules: timeout=15 on every call, max_pages bounds loop
# ---------------------------------------------------------------------------
def test_every_get_uses_timeout_15():
    decision_lead = timedelta(days=2)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(minutes=30)).timestamp())

    def router(url, params):
        if "candlesticks" in url:
            return {"history": [{"t": tick, "p": 0.5}]}
        return {"markets": [], "cursor": None}

    session = FakeSession(router)
    fetcher = KalshiHistoryFetcher(session=session)
    fetcher.fetch_price_history("KXTEST", 0, 1)
    fetcher.to_historical_market(_resolved(), decision_lead)

    assert session.calls
    assert all(c["timeout"] == 15 for c in session.calls)


def test_fetch_loop_respects_max_pages():
    """Always-full pages -> without max_pages bound the loop is infinite.
    max_pages must cap the number of /markets calls."""
    full_page = [_kalshi_market(f"KX{i}-25MAR", result="yes") for i in range(200)]

    def router(url, params):
        if "candlesticks" in url:
            return {}
        return {"markets": full_page, "cursor": "next"}  # always returns a cursor

    session = FakeSession(router)
    fetcher = KalshiHistoryFetcher(session=session)
    fetcher.fetch_resolved_markets(limit=200, max_pages=3)

    markets_calls = [c for c in session.calls if c["url"].endswith("/markets")]
    assert len(markets_calls) == 3


# ---------------------------------------------------------------------------
# Pure helper: _last_pre_decision_price
# ---------------------------------------------------------------------------
def test_last_pre_decision_price_picks_latest_valid():
    """Should return the LATEST tick at/before decision_ts and strictly before resolution_ts."""
    decision_ts = 1000.0
    resolution_ts = 2000.0
    history = [
        {"t": 800.0, "p": 0.40},
        {"t": 900.0, "p": 0.60},   # latest valid
        {"t": 1100.0, "p": 0.80},  # after decision_ts -> excluded
        {"t": 2000.0, "p": 1.0},   # at resolution -> excluded
    ]
    assert _last_pre_decision_price(history, decision_ts, resolution_ts) == 0.60


def test_last_pre_decision_price_none_when_no_valid_ticks():
    decision_ts = 1000.0
    resolution_ts = 2000.0
    history = [
        {"t": 2000.0, "p": 1.0},  # at resolution -> excluded
        {"t": 2100.0, "p": 1.0},  # after resolution -> excluded
    ]
    assert _last_pre_decision_price(history, decision_ts, resolution_ts) is None


def test_last_pre_decision_price_excludes_out_of_range_prices():
    """Ticks with p < 0 or p > 1 are invalid and must not be selected."""
    decision_ts = 1000.0
    resolution_ts = 2000.0
    history = [
        {"t": 500.0, "p": 1.5},   # p > 1.0 -> invalid
        {"t": 600.0, "p": -0.1},  # p < 0.0 -> invalid
    ]
    assert _last_pre_decision_price(history, decision_ts, resolution_ts) is None


def test_last_pre_decision_price_at_exactly_decision_ts():
    """A tick exactly at decision_ts should be accepted (at-or-before rule)."""
    decision_ts = 1000.0
    resolution_ts = 2000.0
    history = [{"t": 1000.0, "p": 0.55}]  # exactly at decision_ts -> valid
    assert _last_pre_decision_price(history, decision_ts, resolution_ts) == 0.55


# ---------------------------------------------------------------------------
# invalid decision_lead
# ---------------------------------------------------------------------------
def test_zero_decision_lead_raises():
    fetcher = KalshiHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": []})
    )
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(), timedelta(0))


def test_negative_decision_lead_raises():
    fetcher = KalshiHistoryFetcher(
        session=FakeSession(lambda u, p: {"history": []})
    )
    with pytest.raises(ValueError):
        fetcher.to_historical_market(_resolved(), timedelta(days=-1))


# ---------------------------------------------------------------------------
# Import check: HistoricalMarket comes from walk_forward (not redefined)
# ---------------------------------------------------------------------------
def test_imports_historical_market_from_walk_forward():
    from app.prediction_markets import walk_forward as wf
    from app.prediction_markets import kalshi_history_fetcher as khf

    assert khf.HistoricalMarket is wf.HistoricalMarket


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def test_assembled_records_are_reproducible():
    """Same input + FakeSession -> identical HistoricalMarket every run."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    tick = int((decision_time - timedelta(hours=1)).timestamp())

    def make_fetcher():
        return KalshiHistoryFetcher(
            session=FakeSession(lambda u, p: {"history": [{"t": tick, "p": 0.71}]})
        )

    hm_a = make_fetcher().to_historical_market(_resolved(), decision_lead)
    hm_b = make_fetcher().to_historical_market(_resolved(), decision_lead)

    assert hm_a.market_price == hm_b.market_price
    assert hm_a.outcome == hm_b.outcome
    assert hm_a.decision_time == hm_b.decision_time
    assert hm_a.resolution_time == hm_b.resolution_time


# ---------------------------------------------------------------------------
# A3 / OA-15 — correct candlesticks endpoint (the /history 404 fix)
# ---------------------------------------------------------------------------
def test_fetch_price_history_hits_candlesticks_endpoint():
    """The price fetch MUST call /series/{series}/markets/{ticker}/candlesticks (the
    endpoint that returns HTTP 200) — NOT /markets/{ticker}/history (which 404s and
    returned 0 records). series_ticker is the prefix before the first '-'."""
    session = FakeSession(lambda url, params: {"candlesticks": [{"end_period_ts": 100, "price": {"mean": 55}}]})
    fetcher = KalshiHistoryFetcher(session=session)
    fetcher.fetch_price_history("KXBTC-25DEC-T50000", 0, 1000)

    assert len(session.calls) == 1
    url = session.calls[0]["url"]
    assert url == f"{BASE_URL}/series/KXBTC/markets/KXBTC-25DEC-T50000/candlesticks"
    assert "/history" not in url                      # the dead 404 endpoint is gone
    assert session.calls[0]["params"]["period_interval"] == 60   # Kalshi-required


def test_series_ticker_derivation():
    assert _series_ticker("KXBTC-25DEC-T50000") == "KXBTC"
    assert _series_ticker("KXPRES-2028") == "KXPRES"
    assert _series_ticker("SINGLE") == "SINGLE"       # no '-' → its own series


def test_candlestick_nested_price_object_in_cents():
    """A real Kalshi candlestick carries a nested `price` object in CENTS; _candle_price
    normalises cents→[0,1] UNCONDITIONALLY for the nested objects (returns [0,1] directly)."""
    assert _candle_price({"price": {"mean": 62, "close": 60}}) == 0.62    # 62¢ → 0.62, mean preferred
    assert _candle_price({"yes_ask": {"close": 40}}) == 0.40              # 40¢ ask fallback
    assert _candle_price({"p": 0.33}) == 0.33                             # flat fraction shape
    assert _candle_price({"price": {}}) is None                          # nothing usable
    # p==0 (0¢) must SURVIVE (presence, not truthiness)
    assert _candle_price({"price": {"mean": 0}}) == 0.0

    session = FakeSession(lambda url, params: {"candlesticks": [
        {"end_period_ts": 500, "price": {"mean": 62}},   # 62¢ → 0.62
        {"end_period_ts": 600, "price": {"mean": 0}},    # 0¢  → 0.0 (survives)
    ]})
    ticks = KalshiHistoryFetcher(session=session).fetch_price_history("KXABC-1", 0, 1000)
    assert ticks == [{"t": 500.0, "p": 0.62}, {"t": 600.0, "p": 0.0}]


def test_one_cent_nested_price_not_fabricated_as_certainty():
    """REGRESSION (auditor break): a 1¢ nested candle price (0.01 probability, a legit
    longshot) must normalise to 0.01 — NOT a fabricated 1.0. Proven to FAIL on pre-fix code,
    where the flat >1.0 heuristic left the raw cents value 1 → p=1.0 (a fabricated 100%
    -certain crowd price that passes the [0,1] DQV gate silently)."""
    assert _candle_price({"price": {"mean": 1}}) == 0.01
    assert _candle_price({"yes_bid": {"close": 1}}) == 0.01
    assert _candle_price({"price": {"mean": 0.5}}) == 0.005   # sub-cent mean, still cents
    session = FakeSession(lambda url, params: {"candlesticks": [
        {"end_period_ts": 500, "price": {"mean": 1}},        # 1¢ → 0.01, NOT 1.0
    ]})
    ticks = KalshiHistoryFetcher(session=session).fetch_price_history("KXABC-1", 0, 1000)
    assert ticks == [{"t": 500.0, "p": 0.01}]


def test_candlestick_endpoint_feeds_leakage_safe_record():
    """End-to-end: a candlestick pre-decision tick becomes the leakage-safe market_price,
    and a tick at resolution is excluded."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        assert "candlesticks" in url
        return {"candlesticks": [
            {"end_period_ts": pre, "price": {"mean": 44}},                 # 0.44 pre-decision
            {"end_period_ts": int(RESOLUTION.timestamp()), "price": {"mean": 100}},  # settled — ignore
        ]}

    hm = KalshiHistoryFetcher(session=FakeSession(router)).to_historical_market(
        _resolved(outcome=1), decision_lead
    )
    assert hm.market_price == 0.44
    assert hm.outcome == 1


def test_nan_timestamp_does_not_poison_decision_price():
    """A NaN candlestick timestamp must not pin best_t=NaN and block real ticks (the
    finiteness hardening). Proven to FAIL on pre-fix code (returns 0.99)."""
    hist = [
        {"t": float("nan"), "p": 0.99},
        {"t": 1000.0, "p": 0.55},
        {"t": 1200.0, "p": 0.62},
    ]
    assert _last_pre_decision_price(hist, decision_ts=1300.0, resolution_ts=1500.0) == 0.62
