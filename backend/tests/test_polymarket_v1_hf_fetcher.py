"""Tests for polymarket_v1_hf_fetcher (ROADMAP A6 — HuggingFace Polymarket-v1).

DETERMINISTIC + OFFLINE: no network, no heavy deps (datasets/pyarrow are NOT
imported — the pure ``assemble_historical_markets`` operates on plain row dicts).

These tests assert the two things that make this module trustworthy:
  * it groups daily rows into resolved markets and REJECTS ambiguous/inconsistent ones; and
  * the anti-leakage guarantee — ``market_price`` comes from a PRE-resolution daily
    tick, NEVER the settled outcome, we RAISE/skip rather than fabricate, and a
    NaN timestamp cannot poison the selection (the finiteness hardening).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.prediction_markets.polymarket_v1_hf_fetcher import (
    HFFieldSpec,
    assemble_historical_markets,
    _last_pre_decision_price,
    _parse_dt,
    _settled_outcome,
)
from app.prediction_markets.walk_forward import walk_forward_backtest

RES = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
LEAD = timedelta(days=5)


def _row(market_id, day_offset, price, *, outcome="yes", res=RES, category="Politics"):
    """A realistic daily_aligned row (default HFFieldSpec column names)."""
    ts = res - timedelta(days=day_offset)
    return {
        "market_id": market_id,
        "date": ts.isoformat().replace("+00:00", "Z"),
        "price": price,
        "resolution_time": res.isoformat().replace("+00:00", "Z"),
        "outcome": outcome,
        "category": category,
        "question": f"Q {market_id}?",
    }


# ---------------------------------------------------------------------------
# Happy path + anti-leakage
# ---------------------------------------------------------------------------
def test_assembles_leakage_safe_record():
    # decision_time = RES - 5d. Ticks at 8d/6d before RES are pre-decision; the 6d
    # tick (0.62) is the LAST at-or-before decision → the decision price.
    rows = [
        _row("m1", 8, 0.55),
        _row("m1", 6, 0.62),   # last pre-decision tick
        _row("m1", 3, 0.80),   # AFTER decision (closer to resolution) — must NOT be used
    ]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert len(out) == 1
    hm = out[0]
    assert hm.market_id == "m1"
    assert hm.decision_time == RES - LEAD
    assert hm.resolution_time == RES
    assert hm.market_price == pytest.approx(0.62)
    assert hm.model_prob == pytest.approx(0.62)  # naive crowd baseline
    assert hm.outcome == 1


def test_never_uses_settled_outcome_as_price():
    # outcome resolves YES (=1) but the only pre-decision tick is 0.6 — the decision
    # price MUST be 0.6, never the settled 1.0 (that would be look-ahead leakage).
    rows = [_row("m1", 7, 0.60, outcome="yes")]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert len(out) == 1
    assert out[0].market_price == pytest.approx(0.60)
    assert out[0].outcome == 1
    assert out[0].market_price != 1.0


def test_skips_market_with_no_pre_decision_tick():
    # Every tick is AFTER the decision instant → no leakage-safe price → skipped.
    rows = [_row("m1", 2, 0.9), _row("m1", 1, 0.95)]  # both within 5d of RES
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert out == []


def test_excludes_tick_at_or_after_resolution():
    # A tick exactly at resolution (day_offset=0) is contaminated by settlement and
    # must be rejected even though it is <= decision_time is false; only the 6d tick counts.
    rows = [
        _row("m1", 6, 0.40),
        _row("m1", 0, 1.0),   # AT resolution — excluded
    ]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert len(out) == 1
    assert out[0].market_price == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# NaN-timestamp poisoning (the A6/A7/A3 finiteness hardening)
# ---------------------------------------------------------------------------
def test_nan_timestamp_does_not_poison_price_selection():
    # A NaN timestamp fails every ordered comparison silently; without the finiteness
    # guard it would pin best_t=NaN and block the real 0.62 tick, returning 0.99.
    hist = [
        {"t": float("nan"), "p": 0.99},   # malformed — must be rejected
        {"t": 1000.0, "p": 0.55},
        {"t": 1200.0, "p": 0.62},         # real last pre-decision tick
    ]
    price = _last_pre_decision_price(hist, decision_ts=1300.0, resolution_ts=1500.0)
    assert price == pytest.approx(0.62)


def test_inf_timestamp_rejected():
    hist = [{"t": float("inf"), "p": 0.99}, {"t": 1000.0, "p": 0.50}]
    price = _last_pre_decision_price(hist, decision_ts=1300.0, resolution_ts=1500.0)
    assert price == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Reconciliation / honesty guards
# ---------------------------------------------------------------------------
def test_skips_ambiguous_outcome():
    # A daily row whose outcome is 0.6 (neither settled 0 nor 1) parses to None → the
    # market has zero valid rows → not assembled.
    rows = [dict(_row("m1", 6, 0.6), outcome=0.6)]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert out == []


def test_skips_inconsistent_outcome_across_rows():
    rows = [_row("m1", 8, 0.5, outcome="yes"), _row("m1", 6, 0.5, outcome="no")]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert out == []  # inconsistent outcome → skipped, never guessed


def test_category_filter_is_pre_registered():
    rows = [_row("m1", 6, 0.6, category="Politics"), _row("m2", 6, 0.6, category="Sports")]
    out = assemble_historical_markets(rows, decision_lead=LEAD, categories=["politics"])
    assert [m.market_id for m in out] == ["m1"]


def test_strict_first_row_schema_mismatch_raises_with_keys():
    bad = {"wrong": "shape", "cols": 1}
    with pytest.raises(ValueError, match="missing a 'market_id' field"):
        assemble_historical_markets([bad], decision_lead=LEAD)


def test_multiple_markets_assembled_independently():
    rows = [
        _row("m1", 7, 0.30, outcome="no"),
        _row("m2", 7, 0.70, outcome="yes"),
    ]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    by_id = {m.market_id: m for m in out}
    assert by_id["m1"].market_price == pytest.approx(0.30) and by_id["m1"].outcome == 0
    assert by_id["m2"].market_price == pytest.approx(0.70) and by_id["m2"].outcome == 1


def test_assembled_records_feed_walk_forward_and_reproduce():
    # Build a small corpus spread over time so walk_forward makes >=1 window, and
    # assert bit-for-bit reproduction (same data -> same seed_hash).
    rows = []
    for i in range(12):
        res = datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(days=3 * i)
        rows.append(_row(f"m{i}", 5, 0.5 + 0.02 * (i % 3), res=res))
    corpus = assemble_historical_markets(rows, decision_lead=timedelta(days=2))
    assert len(corpus) == 12
    r1 = walk_forward_backtest(corpus, seed=42)
    r2 = walk_forward_backtest(corpus, seed=42)
    assert r1.seed_hash == r2.seed_hash
    assert r1.total_pnl_usd == r2.total_pnl_usd


# ---------------------------------------------------------------------------
# Leaf helpers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (True, 1), (False, 0),
        ("yes", 1), ("NO", 0), ("true", 1), ("false", 0), ("Y", 1), ("n", 0),
        (1, 1), (0, 0), (0.99, 1), (0.01, 0), ("1", 1), ("0", 0),
        (0.6, None), ("maybe", None), (float("nan"), None), (None, None),
    ],
)
def test_settled_outcome_mapping(value, expected):
    assert _settled_outcome(value) == expected


def test_parse_dt_iso_and_unix():
    iso = _parse_dt("2026-03-20T12:00:00Z")
    assert iso == datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    unix = _parse_dt(1_800_000_000)  # ~2027
    assert unix is not None and unix.tzinfo is not None
    assert _parse_dt("not-a-date") is None
    assert _parse_dt(float("nan")) is None
    assert _parse_dt(None) is None


def test_decision_lead_must_be_positive():
    with pytest.raises(ValueError, match="decision_lead must be positive"):
        assemble_historical_markets([_row("m1", 6, 0.5)], decision_lead=timedelta(0))
