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
def test_present_but_ambiguous_outcome_skips_whole_market():
    # A daily row whose outcome is 0.6 (a present-but-ambiguous value) is KEPT with an
    # outcome=None contested marker → the whole market is skipped (never assembled from
    # the clean survivors), even when other rows of the same market look cleanly settled.
    rows = [
        _row("m1", 8, 0.5, outcome="yes"),   # clean
        dict(_row("m1", 6, 0.6), outcome=0.6),  # present-but-ambiguous → contests the market
    ]
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


# ---------------------------------------------------------------------------
# Anti-leakage under JITTERED resolution_time (the auditor's break — min-cutoff fix)
# ---------------------------------------------------------------------------
def test_jittered_resolution_does_not_leak_post_resolution_tick():
    """Daily rows disagree on resolution_time (within the 1-day tolerance). Using MAX as
    the cutoff would admit a tick that is AFTER the earliest true resolution but before the
    max → a post-resolution price leaks as the decision price. Using MIN (the fix), the
    later tick is excluded and the honest pre-resolution 0.50 is chosen. Proven to return
    0.99 (the leak) on the pre-fix max-cutoff code."""
    T = RES
    rows = [
        # tick at T-2h, resolution=T
        _row("m1", 2 / 24, 0.50, res=T),
        # tick at T+10h (10h AFTER the earliest resolution T), resolution=T+20h (jitter)
        _row("m1", 10 / 24, 0.99, res=T + timedelta(hours=20)),
    ]
    out = assemble_historical_markets(rows, decision_lead=timedelta(hours=1))
    assert len(out) == 1
    assert out[0].market_price == pytest.approx(0.50)   # NOT the post-resolution 0.99
    assert out[0].resolution_time == T                  # the EARLIEST (safe) resolution


def test_empty_corpus_raises_on_schema_format_mismatch():
    """Rows arrive but every one fails to parse (here: PERCENT prices 0-100 that fail the
    [0,1] range) → 0 usable → RAISE loudly rather than silently returning [] (so a real
    first-download unit/format mismatch surfaces, per the 'verify schema on first download'
    promise). Absent columns are already caught by the strict-first-row check; this covers
    present-but-wrong-UNIT values."""
    rows = [dict(_row(f"m{i}", 6, 0.5), price=55.0) for i in range(3)]
    with pytest.raises(ValueError, match="0 were usable"):
        assemble_historical_markets(rows, decision_lead=LEAD)


def test_empty_corpus_raises_even_with_category_filter():
    """The wipeout guard fires on a genuine parse failure EVEN with a category filter set
    (the filter is applied per-market later, so it never empties by_market itself)."""
    rows = [dict(_row(f"m{i}", 6, 0.5, category="Politics"), price=55.0) for i in range(3)]
    with pytest.raises(ValueError, match="0 were usable"):
        assemble_historical_markets(rows, decision_lead=LEAD, categories=["politics"])


# ---------------------------------------------------------------------------
# NULL / void outcome (a present column with a null value != an absent column)
# ---------------------------------------------------------------------------
def test_null_void_outcome_row_skips_whole_market():
    """A void market whose outcome column is PRESENT but NULL (the natural void encoding)
    must SKIP the whole market — never silently drop the void row and assemble an outcome
    from the clean survivors (the re-opened survivorship hole an auditor found)."""
    rows = [
        _row("m1", 8, 0.4, outcome="yes"),        # clean survivor
        _row("m1", 6, 0.5, outcome="yes"),        # clean survivor
        dict(_row("m1", 4, 0.6), outcome=None),   # VOID: present column, null value
    ]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert out == []


def test_null_void_outcome_first_row_does_not_crash_corpus():
    """A void (null-outcome) row landing FIRST must NOT strict-raise the whole corpus — its
    market is skipped and OTHER markets still assemble (order-independence; the auditor's
    order-dependent whole-corpus-crash finding)."""
    rows = [
        dict(_row("mvoid", 6, 0.5), outcome=None),   # void, FIRST (strict) — must not crash
        _row("good", 6, 0.7, outcome="yes"),         # a clean market
    ]
    out = assemble_historical_markets(rows, decision_lead=LEAD)
    assert [m.market_id for m in out] == ["good"]


def test_missing_outcome_column_raises_on_first_row():
    """An entirely ABSENT outcome column (not a null value) is a schema problem → strict
    raise with the actual keys, distinct from a present-but-null void marker."""
    r = _row("m1", 6, 0.5)
    del r["outcome"]
    with pytest.raises(ValueError, match="missing an 'outcome' field"):
        assemble_historical_markets([r], decision_lead=LEAD)


def test_millisecond_epoch_timestamps_parse():
    """Millisecond-epoch timestamps (a very common trade-archive format) are auto-detected
    and scaled to seconds rather than overflowing to a silent all-skip."""
    def ms(dt):
        return int(dt.timestamp() * 1000)

    row = {
        "market_id": "m1",
        "date": ms(RES - timedelta(days=7)),
        "price": 0.6,
        "resolution_time": ms(RES),
        "outcome": "yes",
        "category": "X",
    }
    out = assemble_historical_markets([row], decision_lead=LEAD)
    assert len(out) == 1 and out[0].market_price == pytest.approx(0.6)


def test_duplicate_timestamp_selection_is_deterministic():
    """Two ticks at the SAME timestamp with different prices, delivered in both orders,
    yield the SAME market_price (ticks are sorted by (t, p) before selection)."""
    r1 = _row("m1", 6, 0.30)
    r2 = _row("m1", 6, 0.70)
    a = assemble_historical_markets([r1, r2], decision_lead=LEAD)
    b = assemble_historical_markets([r2, r1], decision_lead=LEAD)
    assert a[0].market_price == b[0].market_price


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
