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


def test_unrecognized_result_is_logged_loudly_empty_is_quiet(caplog):
    """SELF_VALIDATION claims an UNRECOGNIZED Kalshi status is logged LOUDLY. Honest fix:
    a NON-EMPTY unexpected result (e.g. 'void') → WARNING (owner must verify the contract);
    an EMPTY result (simply unresolved) → DEBUG (an ordinary skip, no noise)."""
    import logging
    f = KalshiHistoryFetcher()

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        assert f._parse_resolved(_kalshi_market("KXVOID-25MAR", result="void")) is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("UNRECOGNIZED" in r.getMessage() and "KXVOID-25MAR" in r.getMessage() for r in warnings)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        assert f._parse_resolved(_kalshi_market("KXOPEN-25MAR", result="")) is None
    # an empty (unresolved) result must NOT warn — only a quiet debug skip
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(r.levelno == logging.DEBUG and "unresolved" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# STRUCTURED STRIKE capture on the RESOLVED record (ROADMAP B8 — the historical #
# co-listed corpus needs resolved Kalshi crypto/scalar markets to carry the     #
# structured strike, exactly like the LIVE client #400, because their titles are #
# generic and the title-text parser finds nothing). Offline + deterministic.    #
# --------------------------------------------------------------------------- #
from app.prediction_markets.kalshi_history_fetcher import _finite_float  # noqa: E402
from app.prediction_markets.cross_venue_matcher import (  # noqa: E402
    extract_threshold,
    extract_threshold_from_structured_strike,
)


def _kalshi_crypto_raw(**over):
    """A real-shaped Kalshi crypto RESOLVED market: GENERIC title, strike only in the
    structured fields (the exact shape #400 documented for the live feed)."""
    raw = {
        "ticker": "KXBTCD-26JUL20-T73000",
        "title": "Bitcoin price on Jul 20, 2026?",   # generic — no strike in the text
        "category": "Crypto",
        "status": "finalized",
        "result": "yes",
        "volume": "5000",
        "close_time": RESOLUTION.isoformat().replace("+00:00", "Z"),
        "floor_strike": 73000,
        "strike_type": "greater",
    }
    raw.update(over)
    return raw


def test_finite_float_rejects_nan_inf_and_garbage():
    assert _finite_float("73000.5") == 73000.5
    assert _finite_float(73000) == 73000.0
    for bad in ("nan", "inf", "-inf", float("nan"), float("inf"), None, "abc", {}):
        assert _finite_float(bad) is None
    # A JSON boolean must NOT coerce to a 1.0/0.0 strike (float(True)==1.0 would smuggle a fake
    # strike past the matcher's own bool guard); an overflowing huge-int strike degrades to None
    # (keep the market, drop the un-representable strike) rather than raising.
    assert _finite_float(True) is None and _finite_float(False) is None
    assert _finite_float(10 ** 400) is None


def test_parse_resolved_captures_structured_strike():
    f = KalshiHistoryFetcher()
    rm = f._parse_resolved(_kalshi_crypto_raw())
    assert rm is not None
    assert rm.floor_strike == 73000.0
    assert rm.cap_strike is None
    assert rm.strike_type == "greater"


def test_parse_resolved_never_fabricates_a_garbage_strike():
    f = KalshiHistoryFetcher()
    # Non-finite / non-numeric / absent structured fields must degrade to None, never a guess.
    rm = f._parse_resolved(_kalshi_crypto_raw(floor_strike="not-a-number", strike_type=""))
    assert rm.floor_strike is None and rm.strike_type is None
    rm2 = f._parse_resolved(_kalshi_crypto_raw(floor_strike="inf"))
    assert rm2.floor_strike is None
    # A market with NO structured fields at all stays fully None (back-compat, byte-unchanged).
    plain = {k: v for k, v in _kalshi_crypto_raw().items() if k not in ("floor_strike", "strike_type")}
    rm3 = f._parse_resolved(plain)
    assert rm3.floor_strike is None and rm3.cap_strike is None and rm3.strike_type is None


def test_resolved_structured_strike_is_matcher_usable_where_title_is_not():
    """The blocker-moving property: the generic title yields NO title-text threshold, but the
    captured structured strike DOES yield the matcher's Threshold — so a resolved Kalshi crypto
    market can now pair on strike against a resolved Polymarket market whose strike is in its
    title. Without this capture the resolved record was strike-BLIND."""
    f = KalshiHistoryFetcher()
    rm = f._parse_resolved(_kalshi_crypto_raw())

    # Title-text parse finds nothing (generic title) — this is why the capture is needed.
    assert extract_threshold(rm.title) is None

    # The captured structured strike feeds the SAME matcher function the live path uses
    # (duck-typed over .title), yielding the confident directional strike.
    thr = extract_threshold_from_structured_strike(rm)
    assert thr is not None
    assert thr.value == 73000.0 and thr.direction == "up"
    assert thr.unit in ("currency", "percent")   # a real unit cue, never a "plain" guess


def test_resolved_between_strike_refuses_to_guess():
    """A range ("between", both bounds) is NOT a single confident strike — the matcher must
    return None rather than fabricate a one-sided pairing (honesty, mirrors the live path)."""
    f = KalshiHistoryFetcher()
    rm = f._parse_resolved(_kalshi_crypto_raw(floor_strike=70000, cap_strike=75000, strike_type="between"))
    assert rm.floor_strike == 70000.0 and rm.cap_strike == 75000.0 and rm.strike_type == "between"
    assert extract_threshold_from_structured_strike(rm) is None


# --------------------------------------------------------------------------- #
# HISTORICAL TIER (ROADMAP A3/B8/B9 — the deep `/historical/*` unblock).       #
# The LIVE `/markets?status=settled` feed only serves a rolling ~3-month       #
# window, so every prior probe missed the multi-year resolved history that     #
# funds a real Kalshi OOS corpus (EXP-009 employment calibration + the B8      #
# co-listed crypto ladder). These assert the deep tier is queried correctly    #
# AND that the current DOLLAR candlestick schema is parsed without fabricating. #
# Endpoint shapes are LIVE-CONFIRMED (HTTP 200 probes, this run).              #
# --------------------------------------------------------------------------- #
def test_historical_resolved_uses_historical_endpoint_no_status_filter():
    """historical=True must query /historical/markets (NOT /markets), forward the
    series_ticker, and NOT send a status filter (the historical tier serves only resolved
    markets and returned 0 when a status filter was passed)."""
    captured = {}

    def router(url, params):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return {"markets": [_kalshi_market("KXJOBLESS-22NOV05-C215", result="yes",
                                           status="finalized")], "cursor": None}

    fetcher = KalshiHistoryFetcher(session=FakeSession(router))
    out = fetcher.fetch_resolved_markets(
        limit=200, max_pages=2, series_ticker="KXJOBLESS", historical=True
    )
    assert len(out) == 1 and out[0].outcome == 1
    assert captured["url"] == f"{BASE_URL}/historical/markets"
    assert captured["params"]["series_ticker"] == "KXJOBLESS"
    assert "status" not in captured["params"]           # historical tier takes no status filter


def test_live_resolved_path_unchanged_still_status_settled():
    """Back-compat: the default (live) path still hits /markets with status=settled and
    NO series_ticker — byte-unchanged behaviour for every existing caller."""
    captured = {}

    def router(url, params):
        captured["url"] = url
        captured["params"] = dict(params or {})
        return {"markets": [_kalshi_market("KXA-25MAR", result="no")], "cursor": None}

    KalshiHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets(limit=50)
    assert captured["url"] == f"{BASE_URL}/markets"
    assert captured["params"]["status"] == "settled"
    assert "series_ticker" not in captured["params"]


def test_fetch_price_history_historical_uses_historical_candlesticks_endpoint():
    """historical=True routes to /historical/markets/{ticker}/candlesticks — the live
    /series/{s}/markets/{t}/candlesticks path 404s for a market past the cutoff."""
    session = FakeSession(lambda url, params: {"candlesticks": [
        {"end_period_ts": 100, "yes_ask": {"close": "0.6700"}}]})
    fetcher = KalshiHistoryFetcher(session=session)
    ticks = fetcher.fetch_price_history("KXJOBLESS-22NOV05-C215", 0, 1000, historical=True)
    url = session.calls[0]["url"]
    assert url == f"{BASE_URL}/historical/markets/KXJOBLESS-22NOV05-C215/candlesticks"
    assert "/series/" not in url
    assert ticks == [{"t": 100.0, "p": 0.67}]           # dollar string parsed as-is


def test_candle_dollar_schema_live_and_historical_not_divided_by_100():
    """The current Kalshi DOLLAR candlestick schema (both endpoints, live-confirmed) must be
    read as-is, NEVER /100. `close_dollars` (LIVE) and a bare decimal STRING (HISTORICAL) are
    both dollars in [0,1]. Pre-fix code divided nested objects by 100 → "0.6700" became a
    fabricated 0.0067 crowd price."""
    # LIVE schema: explicit *_dollars keys.
    assert _candle_price({"yes_ask": {"close_dollars": "0.2200"}}) == 0.22
    assert _candle_price({"price": {"mean_dollars": "0.5000"}}) == 0.50
    # HISTORICAL schema: bare keys, dollar-STRING values.
    assert _candle_price({"yes_ask": {"close": "0.6700"}}) == 0.67
    assert _candle_price({"yes_bid": {"close": "0.0300"}}) == 0.03
    # A genuine $1.00 dollar string is 1.0 (certain) — NOT mistaken for 1¢.
    assert _candle_price({"price": {"close": "1.0000"}}) == 1.0
    # $0.00 (a legit extreme) survives (presence, not truthiness).
    assert _candle_price({"yes_bid": {"close": "0.0000"}}) == 0.0


def test_candle_legacy_cents_whole_numbers_still_divided_by_100():
    """REGRESSION GUARD: the legacy integer CENTS schema (WHOLE numeric values) is unchanged —
    a whole NUMBER is cents (/100). The 1¢ legacy tick (number 1 → 0.01) stays distinct from a
    $1.00 dollar tick (string "1.0000" → 1.0) via wire type at the integer boundary."""
    assert _candle_price({"price": {"mean": 62}}) == 0.62        # whole number → cents
    assert _candle_price({"price": {"mean": 1}}) == 0.01         # 1¢ number, NOT 1.0
    assert _candle_price({"yes_ask": {"close": 40}}) == 0.40
    # An explicit *_dollars key wins over a bare key on the same object.
    assert _candle_price({"price": {"close_dollars": "0.4000", "close": 40}}) == 0.40


def test_bare_fractional_number_is_dollars_not_fabricated_cents():
    """HARDENING (adversarial-review break, all 5 gate agents flagged it): a bare NON-whole
    numeric value can only be DOLLARS — a real Kalshi legacy cents value is always a whole
    number in [0,100]. So if Kalshi ever serves a mid-range dollar as an unquoted JSON float
    (`{"close": 0.44}`, plausible API drift), it must read as 0.44, NOT 0.0044 (a silent 100x
    fabrication that would pass the [0,1] range gate). Pre-hardening the pure type check
    divided any bare number by 100."""
    assert _candle_price({"yes_ask": {"close": 0.44}}) == 0.44   # bare dollar float → as-is
    assert _candle_price({"price": {"mean": 0.6700}}) == 0.67    # bare dollar float → as-is
    # whole-number boundaries keep the legacy-cents reading (a NUMBER 0/1 is cents)
    assert _candle_price({"price": {"mean": 0}}) == 0.0
    assert _candle_price({"price": {"mean": 1}}) == 0.01


def test_historical_dollar_candle_feeds_leakage_safe_record():
    """End-to-end on the REAL historical shape: a dollar-string pre-decision candle becomes the
    leakage-safe market_price, routed through the /historical/* candlestick tier, and a tick at
    resolution is still excluded."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        assert "/historical/markets/" in url and "candlesticks" in url
        return {"candlesticks": [
            {"end_period_ts": pre, "yes_ask": {"close": "0.4400"}},                  # 0.44 pre
            {"end_period_ts": int(RESOLUTION.timestamp()), "yes_ask": {"close": "1.0000"}},  # settled — ignore
        ]}

    hm = KalshiHistoryFetcher(session=FakeSession(router)).to_historical_market(
        _resolved(outcome=1), decision_lead, historical=True
    )
    assert hm.market_price == 0.44
    assert hm.outcome == 1


def test_historical_volume_fp_fallback():
    """Historical markets serve `volume: null` and put the count in `volume_fp`; a record must
    still carry a real volume from the fallback (never silently 0)."""
    f = KalshiHistoryFetcher()
    raw = _kalshi_market("KXH-25MAR", result="yes")
    raw["volume"] = None
    raw["volume_fp"] = "874.00"
    rm = f._parse_resolved(raw)
    assert rm.volume == 874.0
    # When both are absent, volume is honestly 0.0 (not fabricated).
    raw2 = _kalshi_market("KXH2-25MAR", result="yes")
    raw2["volume"] = None
    rm2 = f._parse_resolved(raw2)
    assert rm2.volume == 0.0


# ===========================================================================
# EVENTS-BY-CATEGORY discovery (ROADMAP B8 / A3)
#
# EVERY fixture below encodes a response shape OBSERVED ON THE LIVE KALSHI API
# on 2026-07-27, not a documented one. That distinction is the whole reason this
# block exists: this module was previously burned by fixtures that encoded
# request-side filter words as if they were response values, so the adapter would
# have dropped every live market. The shapes pinned here are:
#   * /events              -> {"cursor": str, "events": [...], "milestones": []}
#                             and an EVENT carries NO "status" field of its own.
#   * /events/{ticker}     -> markets at the TOP LEVEL by default, but moved under
#                             {"event": {"markets": [...]}} when
#                             with_nested_markets=true is passed. Both are real.
#   * an event's MARKET    -> carries NO "category" field (the taxonomy is on the
#                             event) and its status is "finalized"/"active" —
#                             NOT the "settled"/"determined" the docs name.
#   * /series?category=X   -> {"series": [...]}, and an UNKNOWN category returns
#                             {"series": null} — null, not [] and not an error.
#   * /historical/markets  -> {"cursor": "", "markets": [...]}
# ===========================================================================
import logging  # noqa: E402  (kept with the block it serves)

from app.prediction_markets.kalshi_history_fetcher import (  # noqa: E402
    KNOWN_MARKET_STATUSES,
    POLITICAL_ECONOMIC_CATEGORIES,
    KalshiEvent,
    _parse_event,
)


def _kalshi_event(event_ticker, category="Politics", series_ticker=None, title=None):
    """A raw /events listing item in the LIVE shape (no `status` key — status is a
    request-side filter only, it is never echoed back on the event)."""
    return {
        "available_on_brokers": True,
        "category": category,
        "collateral_return_type": "MECNET",
        "event_ticker": event_ticker,
        "mutually_exclusive": True,
        "series_ticker": series_ticker or event_ticker.split("-")[0],
        "strike_period": "",
        "sub_title": "Before Jan 1, 2030",
        "title": title or f"Question for {event_ticker}?",
    }


def _event_market(ticker, result, status="finalized", close_time=None):
    """A raw market as returned UNDER AN EVENT: note the deliberate ABSENCE of a
    "category" key (live-observed) — that is what the event-category stamping in
    fetch_resolved_markets_by_category exists to supply."""
    return {
        "ticker": ticker,
        "title": f"Will {ticker} happen?",
        "status": status,
        "result": result,
        "close_time": close_time or RESOLUTION.isoformat().replace("+00:00", "Z"),
        "volume_fp": "14446.67",
        "yes_bid_dollars": "0.0000",
        "yes_ask_dollars": "1.0000",
    }


# ---------------------------------------------------------------------------
# /events paging: cursor termination and the max_pages bound
# ---------------------------------------------------------------------------
def test_events_paging_follows_cursor_then_terminates():
    """Two full pages then a short final page: the cursor must be forwarded on
    each subsequent request and the loop must STOP on the short page."""
    pages = [
        {"cursor": "CUR1", "events": [_kalshi_event(f"KXA{i}-30") for i in range(2)],
         "milestones": []},
        {"cursor": "CUR2", "events": [_kalshi_event(f"KXB{i}-30") for i in range(2)],
         "milestones": []},
        # Short page (1 < limit=2) — terminates even though a cursor is present.
        {"cursor": "CUR3", "events": [_kalshi_event("KXC0-30")], "milestones": []},
    ]
    seen_cursors = []

    def router(url, params):
        seen_cursors.append(params.get("cursor"))
        return pages[len(seen_cursors) - 1]

    session = FakeSession(router)
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        limit=2, max_pages=10
    )
    assert len(out) == 5
    assert seen_cursors == [None, "CUR1", "CUR2"]
    assert [e.event_ticker for e in out][:2] == ["KXA0-30", "KXA1-30"]


def test_events_paging_terminates_on_empty_cursor_string():
    """Kalshi returns "" (falsy, not None) for the LAST page's cursor — a truthiness
    test is required; an `is not None` test would loop until max_pages."""
    def router(url, params):
        return {"cursor": "", "events": [_kalshi_event(f"KX{i}-30") for i in range(3)],
                "milestones": []}

    session = FakeSession(router)
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        limit=3, max_pages=10
    )
    assert len(out) == 3
    assert len(session.calls) == 1  # stopped immediately on the empty cursor


def test_events_paging_respects_max_pages_bound():
    """A server that ALWAYS returns a full page + a fresh cursor must still stop at
    max_pages — the loop is bounded, never unbounded."""
    def router(url, params):
        return {"cursor": "ALWAYS-MORE",
                "events": [_kalshi_event(f"KX{i}-30") for i in range(2)],
                "milestones": []}

    session = FakeSession(router)
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        limit=2, max_pages=3
    )
    assert len(session.calls) == 3
    assert len(out) == 6


def test_every_events_request_uses_timeout_15():
    """The per-request deadline must be SHORTER than any run budget on every new
    endpoint too — events, series, event-detail and the historical join."""
    def router(url, params):
        if "/series" in url:
            return {"series": [{"ticker": "KXPOL", "category": "Politics"}]}
        if "/events/" in url:
            return {"event": {"markets": []}}
        if "/historical/markets" in url:
            return {"cursor": "", "markets": []}
        return {"cursor": "", "events": [_kalshi_event("KXA-30")], "milestones": []}

    session = FakeSession(router)
    f = KalshiHistoryFetcher(session=session)
    f.fetch_series_tickers("Politics")
    f.fetch_resolved_events(limit=5, max_pages=1)
    f.fetch_event_markets("KXA-30")
    f.fetch_event_markets("KXA-30", historical=True)
    assert session.calls, "no request was made"
    assert all(c["timeout"] == 15 for c in session.calls)


# ---------------------------------------------------------------------------
# Category filtering: forwarded server-side AND re-checked on the response
# ---------------------------------------------------------------------------
def test_category_is_forwarded_server_side_on_events_request():
    """The documented `category` parameter is FORWARDED on the /events request.
    (LIVE FINDING: Kalshi currently ACCEPTS and IGNORES it — a nonsense category
    returns the identical page — which is exactly why the response-side backstop in
    the next test is load-bearing. We still send it so the day Kalshi honours it the
    filtering moves server-side for free.)"""
    session = FakeSession(
        lambda url, params: {"cursor": "", "events": [], "milestones": []}
    )
    KalshiHistoryFetcher(session=session).fetch_resolved_events(
        categories=["Politics", "Economics"], limit=5, max_pages=1
    )
    params = session.calls[0]["params"]
    assert params["status"] == "settled"
    assert params["category"] == "Economics,Politics"  # sorted → deterministic
    assert params["limit"] == 5


def test_series_ticker_is_forwarded_server_side_on_events_request():
    """`series_ticker` IS a genuinely server-side filter on /events (live-verified: a
    nonsense series returns []), so it must reach the wire."""
    session = FakeSession(
        lambda url, params: {"cursor": "", "events": [], "milestones": []}
    )
    KalshiHistoryFetcher(session=session).fetch_resolved_events(
        series_ticker="KXNEXTUKPM", limit=5, max_pages=1
    )
    assert session.calls[0]["params"]["series_ticker"] == "KXNEXTUKPM"
    assert "/events" in session.calls[0]["url"]


def test_response_side_category_backstop_filters_the_ignored_server_filter():
    """Because Kalshi IGNORES ?category=, the server hands back a MIXED page. The
    response-side re-check on the category each event actually carries is what really
    selects — without it the 'political' universe would still be full of sport."""
    mixed = [
        _kalshi_event("KXPOL-30", category="Politics"),
        _kalshi_event("KXSPORT-30", category="Sports"),
        _kalshi_event("KXELEC-30", category="Elections"),
        _kalshi_event("KXENT-30", category="Entertainment"),
    ]
    session = FakeSession(
        lambda url, params: {"cursor": "", "events": mixed, "milestones": []}
    )
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        categories=["Politics", "Elections"], limit=10, max_pages=1
    )
    assert [e.event_ticker for e in out] == ["KXPOL-30", "KXELEC-30"]


def test_category_match_is_case_insensitive():
    session = FakeSession(
        lambda url, params: {"cursor": "",
                             "events": [_kalshi_event("KXPOL-30", category="Politics")],
                             "milestones": []}
    )
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        categories=["politics"], limit=10, max_pages=1
    )
    assert len(out) == 1


def test_series_by_category_is_a_real_server_side_filter():
    """/series?category= is the ONE endpoint whose category parameter genuinely
    filters (live-verified). It must be forwarded, and an UNKNOWN category returns
    {"series": null} — null, not [] — which must degrade to an empty list, not crash."""
    def router(url, params):
        if params.get("category") == "Politics":
            return {"series": [{"ticker": "KXHOUSEBILLS", "category": "Politics"},
                               {"ticker": "KXFTC", "category": "Politics"}]}
        return {"series": None}  # LIVE shape for an unknown category

    session = FakeSession(router)
    f = KalshiHistoryFetcher(session=session)
    assert f.fetch_series_tickers("Politics") == ["KXHOUSEBILLS", "KXFTC"]
    assert session.calls[0]["params"]["category"] == "Politics"
    assert "/series" in session.calls[0]["url"]
    assert f.fetch_series_tickers("Bogus") == []


def test_series_by_category_max_series_bound():
    session = FakeSession(
        lambda url, params: {"series": [{"ticker": f"KX{i}"} for i in range(50)]}
    )
    out = KalshiHistoryFetcher(session=session).fetch_series_tickers(
        "Politics", max_series=5
    )
    assert out == [f"KX{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# The events -> markets JOIN (both real response placements)
# ---------------------------------------------------------------------------
def test_event_markets_read_from_nested_placement():
    """With with_nested_markets=true the markets move UNDER "event" — reading only the
    top level would silently yield ZERO markets (this cost a live probe iteration)."""
    session = FakeSession(
        lambda url, params: {
            "event": {"event_ticker": "KXA-30",
                      "markets": [_event_market("KXA-30-X", "no")]},
            "markets": [],
        }
    )
    out = KalshiHistoryFetcher(session=session).fetch_event_markets("KXA-30")
    assert [m["ticker"] for m in out] == ["KXA-30-X"]
    assert session.calls[0]["params"]["with_nested_markets"] == "true"
    assert session.calls[0]["url"].endswith("/events/KXA-30")


def test_event_markets_read_from_top_level_placement():
    """/events/{t} returns markets at the TOP LEVEL in the default shape — the other
    real placement, which must parse identically."""
    session = FakeSession(
        lambda url, params: {
            "event": {"event_ticker": "KXA-30"},
            "markets": [_event_market("KXA-30-X", "yes"),
                        _event_market("KXA-30-Y", "no")],
        }
    )
    out = KalshiHistoryFetcher(session=session).fetch_event_markets("KXA-30")
    assert [m["ticker"] for m in out] == ["KXA-30-X", "KXA-30-Y"]


def test_event_markets_historical_route_hits_historical_endpoint():
    """The live and historical tiers are COMPLEMENTARY (live-probed over the same 60
    settled political events: 17 vs 18 events yielded markets), so the historical route
    must query /historical/markets?event_ticker=, not the event detail."""
    session = FakeSession(
        lambda url, params: {"cursor": "", "markets": [_event_market("KXA-30-X", "no")]}
    )
    out = KalshiHistoryFetcher(session=session).fetch_event_markets(
        "KXA-30", historical=True
    )
    assert [m["ticker"] for m in out] == ["KXA-30-X"]
    assert session.calls[0]["url"].endswith("/historical/markets")
    assert session.calls[0]["params"]["event_ticker"] == "KXA-30"


def test_event_markets_tolerates_missing_and_malformed_shapes():
    """A missing/None markets list must degrade to [] (never None, never a crash), and
    non-dict entries are dropped rather than fed to the parser."""
    f = KalshiHistoryFetcher(session=FakeSession(lambda url, params: {"event": {}}))
    assert f.fetch_event_markets("KXA-30") == []
    f2 = KalshiHistoryFetcher(session=FakeSession(lambda url, params: {"markets": None}))
    assert f2.fetch_event_markets("KXA-30") == []
    f3 = KalshiHistoryFetcher(
        session=FakeSession(lambda url, params: {"markets": ["junk", {"ticker": "KXA-30-X"}]})
    )
    assert f3.fetch_event_markets("KXA-30") == [{"ticker": "KXA-30-X"}]


def test_events_by_category_joins_events_to_resolved_markets():
    """The full discovery path: page /events, keep only the wanted categories, expand
    each surviving event to its markets, and parse ONLY unambiguous yes/no results."""
    def router(url, params):
        if "/events/" in url:
            ticker = url.rsplit("/", 1)[1]
            return {"event": {"markets": [
                _event_market(f"{ticker}-A", "yes"),
                _event_market(f"{ticker}-B", "no"),
                # An `active` market inside a status=settled EVENT is real and common
                # (live: 198 of 1026 markets across 150 settled political events).
                _event_market(f"{ticker}-C", "", status="active"),
            ]}}
        return {"cursor": "", "milestones": [], "events": [
            _kalshi_event("KXPOL-30", category="Politics"),
            _kalshi_event("KXSPORT-30", category="Sports"),
        ]}

    out = KalshiHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets_by_category(
        ["Politics"], limit=10, max_pages=1, max_events=10
    )
    assert [m.ticker for m in out] == ["KXPOL-30-A", "KXPOL-30-B"]
    assert [m.outcome for m in out] == [1, 0]
    # The SPORTS event was never even expanded to markets.
    assert all(not m.ticker.startswith("KXSPORT") for m in out)


def test_events_by_category_stamps_event_category_onto_markets():
    """A market under an event carries NO category of its own (live-observed), so the
    event's category must be stamped on so the shared correlation-bucket deriver gets a
    real input instead of falling through to "General"."""
    def router(url, params):
        if "/events/" in url:
            return {"event": {"markets": [_event_market("KXPOL-30-A", "yes")]}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30", category="Politics")],
                "milestones": []}

    out = KalshiHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets_by_category(
        ["Politics"], limit=10, max_pages=1, max_events=10
    )
    assert out[0].category == "Politics"


def test_events_by_category_does_not_mutate_the_api_payload():
    """The category stamp must land on a COPY — mutating the response dict a caller may
    still be holding is a silent action-at-a-distance bug."""
    raw = _event_market("KXPOL-30-A", "yes")

    def router(url, params):
        if "/events/" in url:
            return {"event": {"markets": [raw]}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30", category="Politics")],
                "milestones": []}

    KalshiHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets_by_category(
        ["Politics"], limit=10, max_pages=1, max_events=10
    )
    assert "category" not in raw


def test_events_by_category_respects_max_events_bound():
    """max_events HARD-BOUNDS the per-event fan-out (one request per event) so the
    worst case stays max_pages + max_events requests."""
    def router(url, params):
        if "/events/" in url:
            ticker = url.rsplit("/", 1)[1]
            return {"event": {"markets": [_event_market(f"{ticker}-A", "yes")]}}
        return {"cursor": "", "milestones": [],
                "events": [_kalshi_event(f"KXP{i}-30") for i in range(20)]}

    session = FakeSession(router)
    out = KalshiHistoryFetcher(session=session).fetch_resolved_markets_by_category(
        ["Politics"], limit=100, max_pages=1, max_events=4
    )
    event_detail_calls = [c for c in session.calls if "/events/" in c["url"]]
    assert len(event_detail_calls) == 4
    assert len(out) == 4


def test_events_by_category_deduplicates_by_ticker():
    """The same market can be reachable from more than one event query in a multi-series
    build; the corpus must not double-count it."""
    def router(url, params):
        if "/events/" in url:
            return {"event": {"markets": [_event_market("SHARED-A", "yes")]}}
        return {"cursor": "", "milestones": [],
                "events": [_kalshi_event("KXP1-30"), _kalshi_event("KXP2-30")]}

    out = KalshiHistoryFetcher(session=FakeSession(router)).fetch_resolved_markets_by_category(
        ["Politics"], limit=100, max_pages=1, max_events=10
    )
    assert [m.ticker for m in out] == ["SHARED-A"]


def test_events_by_category_default_is_the_preregistered_constant():
    """The default category set is the NAMED constant, so the common case is a declared
    pre-registration rather than an ad-hoc post-hoc subset (p-hacking caveat)."""
    assert POLITICAL_ECONOMIC_CATEGORIES == (
        "Politics", "Elections", "Economics", "Financials"
    )
    session = FakeSession(
        lambda url, params: {"cursor": "", "events": [], "milestones": []}
    )
    KalshiHistoryFetcher(session=session).fetch_resolved_markets_by_category(
        limit=5, max_pages=1
    )
    assert session.calls[0]["params"]["category"] == (
        "Economics,Elections,Financials,Politics"
    )


# ---------------------------------------------------------------------------
# LOUD failure: an unrecognized status/result is never silently dropped
# ---------------------------------------------------------------------------
def test_unrecognized_market_status_logs_loudly_and_market_survives(caplog):
    """An UNKNOWN status is a real contract surprise the owner must SEE — it logs at
    WARNING. It is NOT a reason to drop the market: the YES/NO outcome has only ever
    come from `result`, so dropping on a cosmetic status change would silently shrink
    the corpus (the BUILDS≠WORKS class of failure this module has already hit)."""
    def router(url, params):
        if "/events/" in url:
            return {"event": {"markets": [
                _event_market("KXPOL-30-A", "yes", status="quantum_superposition"),
            ]}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30")], "milestones": []}

    f = KalshiHistoryFetcher(session=FakeSession(router))
    with caplog.at_level(logging.WARNING):
        out = f.fetch_resolved_markets_by_category(["Politics"], limit=5, max_pages=1)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("UNRECOGNIZED status" in r.getMessage() for r in warnings)
    assert any("quantum_superposition" in r.getMessage() for r in warnings)
    assert [m.ticker for m in out] == ["KXPOL-30-A"]  # loud, NOT dropped


def test_known_statuses_do_not_log_and_absent_status_is_silent(caplog):
    """The live-observed statuses must stay quiet, and so must an ABSENT status —
    nothing surprising happened, and a WARNING per market would drown the real one."""
    def router(url, params):
        if "/events/" in url:
            markets = [_event_market(f"KXPOL-30-{i}", "yes", status=s)
                       for i, s in enumerate(sorted(KNOWN_MARKET_STATUSES))]
            no_status = _event_market("KXPOL-30-NS", "no")
            del no_status["status"]
            markets.append(no_status)
            return {"event": {"markets": markets}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30")], "milestones": []}

    f = KalshiHistoryFetcher(session=FakeSession(router))
    with caplog.at_level(logging.WARNING):
        f.fetch_resolved_markets_by_category(["Politics"], limit=5, max_pages=1)
    assert not [r for r in caplog.records
                if r.levelno >= logging.WARNING and "status" in r.getMessage()]


def test_unrecognized_result_scalar_logs_loudly_through_the_events_path(caplog):
    """`scalar` is a REAL result value observed live on the /historical tier (3 markets
    in a 150-event census). It is not yes/no, so it must be skipped — but LOUDLY."""
    def router(url, params):
        if "/historical/markets" in url:
            return {"cursor": "", "markets": [_event_market("KXUHCCONVICT-30", "scalar")]}
        return {"cursor": "", "events": [_kalshi_event("KXUHCCONVICT-30")],
                "milestones": []}

    f = KalshiHistoryFetcher(session=FakeSession(router))
    with caplog.at_level(logging.WARNING):
        out = f.fetch_resolved_markets_by_category(
            ["Politics"], limit=5, max_pages=1, historical=True
        )
    assert out == []
    assert any("UNRECOGNIZED result" in r.getMessage() and "scalar" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.WARNING)


# ---------------------------------------------------------------------------
# The anti-leakage guarantee is UNCHANGED through the new discovery path
# ---------------------------------------------------------------------------
def test_events_path_records_use_pre_resolution_tick_not_settled_result():
    """END-TO-END on the new path with the REAL candlestick shape: discovery →
    events→markets join → the SAME leakage-safe assembly. The market resolved YES but
    the pre-decision crowd price was $0.62, so market_price MUST be 0.62 — never 1.0."""
    decision_lead = timedelta(days=3)
    decision_time = RESOLUTION - decision_lead
    pre = int((decision_time - timedelta(hours=1)).timestamp())

    def router(url, params):
        if "candlesticks" in url:
            return {"candlesticks": [
                {"end_period_ts": pre,
                 "price": {"previous_dollars": "0.6200"},
                 "yes_ask": {"close_dollars": "0.6200"},
                 "yes_bid": {"close_dollars": "0.6100"}},
                # Tick AT resolution carrying the settled answer — must be excluded.
                {"end_period_ts": int(RESOLUTION.timestamp()),
                 "yes_ask": {"close_dollars": "1.0000"}},
            ]}
        if "/events/" in url:
            return {"event": {"markets": [_event_market("KXPOL-30-A", "yes")]}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30")], "milestones": []}

    f = KalshiHistoryFetcher(session=FakeSession(router))
    resolved = f.fetch_resolved_markets_by_category(["Politics"], limit=5, max_pages=1)
    records = f.build_historical_markets(resolved, decision_lead)

    assert len(records) == 1
    rec = records[0]
    assert rec.market_id == "KXPOL-30-A"
    assert rec.market_price == 0.62          # pre-resolution crowd price
    assert rec.outcome == 1                  # settled answer, NEVER the price
    assert rec.decision_time < rec.resolution_time
    assert rec.category == "Politics"


def test_events_path_refuses_a_post_resolution_tick_and_skips_loudly(caplog):
    """The leakage guard is untouched by the new discovery path: when the ONLY tick is
    at/after resolution there is no honest decision price, so the record is SKIPPED with
    a loud warning — never fabricated from the settled result."""
    decision_lead = timedelta(days=3)

    def router(url, params):
        if "candlesticks" in url:
            return {"candlesticks": [
                # At resolution (excluded) and after it (excluded) — nothing else.
                {"end_period_ts": int(RESOLUTION.timestamp()),
                 "yes_ask": {"close_dollars": "1.0000"}},
                {"end_period_ts": int((RESOLUTION + timedelta(hours=2)).timestamp()),
                 "yes_ask": {"close_dollars": "1.0000"}},
            ]}
        if "/events/" in url:
            return {"event": {"markets": [_event_market("KXPOL-30-A", "yes")]}}
        return {"cursor": "", "events": [_kalshi_event("KXPOL-30")], "milestones": []}

    f = KalshiHistoryFetcher(session=FakeSession(router))
    resolved = f.fetch_resolved_markets_by_category(["Politics"], limit=5, max_pages=1)
    assert len(resolved) == 1

    with caplog.at_level(logging.WARNING):
        records = f.build_historical_markets(resolved, decision_lead)
    assert records == []
    assert any("no leakage-safe price" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.WARNING)

    # And the single-record path RAISES rather than fabricating.
    with pytest.raises(ValueError, match="refusing to fabricate"):
        f.to_historical_market(resolved[0], decision_lead)


# ---------------------------------------------------------------------------
# _parse_event: honest degradation, never invention
# ---------------------------------------------------------------------------
def test_parse_event_requires_event_ticker_only():
    assert _parse_event({"event_ticker": "KXA-30"}) == KalshiEvent(
        event_ticker="KXA-30", series_ticker="", category="", title=""
    )
    assert _parse_event({"category": "Politics"}) is None
    assert _parse_event("not-a-dict") is None


def test_parse_event_null_category_degrades_rather_than_being_guessed():
    """LIVE-OBSERVED: one event in a 1600-event census had a null category. It must
    become "" (and therefore fail any allowlist) — never be guessed into a bucket."""
    ev = _parse_event({"event_ticker": "KXA-30", "category": None, "title": None})
    assert ev.category == ""
    session = FakeSession(
        lambda url, params: {"cursor": "",
                             "events": [{"event_ticker": "KXA-30", "category": None}],
                             "milestones": []}
    )
    out = KalshiHistoryFetcher(session=session).fetch_resolved_events(
        categories=["Politics"], limit=5, max_pages=1
    )
    assert out == []
