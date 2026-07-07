"""Deterministic OFFLINE tests for the A8 Manifold research-only fetcher.

Manifold is play money → RESEARCH ONLY; these tests prove the leakage-safety guarantee
and the honest parse/skip behavior without any network access (bet history is injected).
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.prediction_markets.manifold_history_fetcher import (
    ManifoldHistoryFetcher,
    ResolvedManifoldMarket,
    _ms_to_dt,
)

_CREATED = datetime(2025, 1, 1, tzinfo=timezone.utc)
_RESOLVED = datetime(2025, 1, 31, tzinfo=timezone.utc)


def _rm(outcome=1, created=_CREATED, resolved=_RESOLVED):
    return ResolvedManifoldMarket(
        market_id="mkt1", question="Will X happen?", outcome=outcome,
        created_time=created, resolution_time=resolved, category="General",
    )


def _tick(dt: datetime, p: float) -> dict:
    return {"t": dt.timestamp(), "p": p}


def test_research_only_marker():
    assert ManifoldHistoryFetcher.research_only is True


def test_parse_keeps_only_clean_resolved_binary():
    f = ManifoldHistoryFetcher()
    base = {"id": "a", "question": "q", "outcomeType": "BINARY", "isResolved": True,
            "createdTime": _CREATED.timestamp() * 1000, "resolutionTime": _RESOLVED.timestamp() * 1000}
    assert f._parse_resolved({**base, "resolution": "YES"}).outcome == 1
    assert f._parse_resolved({**base, "resolution": "NO"}).outcome == 0
    # dropped cases — never coerced into a 0/1
    assert f._parse_resolved({**base, "resolution": "MKT"}) is None
    assert f._parse_resolved({**base, "resolution": "CANCEL"}) is None
    assert f._parse_resolved({**base, "resolution": "YES", "isResolved": False}) is None
    assert f._parse_resolved({**base, "resolution": "YES", "outcomeType": "MULTIPLE_CHOICE"}) is None


def test_parse_derives_category_from_question():
    f = ManifoldHistoryFetcher()
    raw = {"id": "a", "question": "Will Bitcoin close above $100k?", "outcomeType": "BINARY",
           "isResolved": True, "resolution": "YES",
           "createdTime": _CREATED.timestamp() * 1000, "resolutionTime": _RESOLVED.timestamp() * 1000}
    assert f._parse_resolved(raw).category == "Crypto"


def test_decision_price_is_last_pre_decision_bet():
    f = ManifoldHistoryFetcher()
    lead = timedelta(days=5)
    decision_time = _RESOLVED - lead  # 2025-01-26
    history = [
        _tick(_CREATED + timedelta(days=1), 0.40),
        _tick(decision_time - timedelta(hours=1), 0.55),   # last tick before decision -> the price
        _tick(decision_time + timedelta(hours=1), 0.80),   # AFTER decision -> must be ignored
        _tick(_RESOLVED, 1.0),                             # at resolution -> must be ignored
    ]
    hm = f.to_historical_market(_rm(outcome=1), lead, bet_history=history)
    assert hm.market_price == 0.55
    assert hm.model_prob == 0.55
    assert hm.decision_time == decision_time
    assert hm.outcome == 1


def test_settled_outcome_never_becomes_the_decision_price():
    # Only ticks AT/AFTER resolution exist -> no pre-decision price -> RAISE, never use 1.0.
    f = ManifoldHistoryFetcher()
    lead = timedelta(days=5)
    history = [_tick(_RESOLVED, 1.0), _tick(_RESOLVED + timedelta(hours=1), 1.0)]
    with pytest.raises(ValueError, match="fabricate"):
        f.to_historical_market(_rm(outcome=1), lead, bet_history=history)


def test_no_pre_decision_bet_raises():
    f = ManifoldHistoryFetcher()
    lead = timedelta(days=5)
    decision_time = _RESOLVED - lead
    # only a bet AFTER the decision instant -> no qualifying pre-decision price
    history = [_tick(decision_time + timedelta(days=1), 0.7)]
    with pytest.raises(ValueError):
        f.to_historical_market(_rm(), lead, bet_history=history)


def test_decision_lead_predating_creation_raises():
    f = ManifoldHistoryFetcher()
    # lead longer than the whole market life -> decision_time <= created -> raise
    with pytest.raises(ValueError, match="predates market creation"):
        f.to_historical_market(_rm(), timedelta(days=60), bet_history=[_tick(_CREATED, 0.5)])


def test_build_skips_unsatisfiable_and_keeps_good():
    f = ManifoldHistoryFetcher()
    lead = timedelta(days=5)
    decision_time = _RESOLVED - lead
    good = _rm()
    # patch fetch_bet_history to serve per-market injected histories (no network)
    histories = {
        "mkt1": [_tick(decision_time - timedelta(hours=1), 0.6)],   # satisfiable
        "bad": [_tick(_RESOLVED, 1.0)],                              # only settled tick -> skip
    }
    f.fetch_bet_history = lambda mid, max_pages=20: histories.get(mid, [])
    bad = ResolvedManifoldMarket(market_id="bad", question="q", outcome=0,
                                 created_time=_CREATED, resolution_time=_RESOLVED, category="General")
    out = f.build_historical_markets([good, bad], lead)
    assert len(out) == 1
    assert out[0].market_id == "mkt1"
    assert out[0].market_price == 0.6


def test_ms_to_dt_guards_nan_inf_and_absent():
    assert _ms_to_dt(None) is None
    assert _ms_to_dt(float("nan")) is None
    assert _ms_to_dt(float("inf")) is None
    assert _ms_to_dt("2025") is None
    dt = _ms_to_dt(_CREATED.timestamp() * 1000)
    assert dt == _CREATED


def test_decision_price_bounds_enforced_by_historical_market():
    # An out-of-[0,1] probAfter is rejected by _last_pre_decision_price -> treated as no tick.
    f = ManifoldHistoryFetcher()
    lead = timedelta(days=5)
    decision_time = _RESOLVED - lead
    history = [_tick(decision_time - timedelta(hours=1), 1.5)]  # invalid prob
    with pytest.raises(ValueError):
        f.to_historical_market(_rm(), lead, bet_history=history)
