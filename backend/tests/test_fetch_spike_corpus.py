"""Offline tests for scripts/fetch_spike_corpus.py — the EXP-006 real-corpus builder.

The builder reuses the audited leakage-safe ``PolymarketHistoryFetcher`` verbatim; the ONLY
new logic is (a) chunking a long hourly fetch into <=15-day windows and merging, and (b)
truncating each series strictly before ``resolution_time - leakage_margin`` so no fade exit
can read a post-resolution settlement pin. These tests pin BOTH with a fake fetcher — no
network. The truncation test is the load-bearing leakage guard.
"""

import importlib.util
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

# Load the script module by path (scripts/ is not a package).
_SPEC = importlib.util.spec_from_file_location(
    "fetch_spike_corpus",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_spike_corpus.py",
)
fsc = importlib.util.module_from_spec(_SPEC)
sys.modules["fetch_spike_corpus"] = fsc
_SPEC.loader.exec_module(fsc)


class _FakeFetcher:
    """Records the (start, end) windows it is asked for and returns canned ticks per call."""

    def __init__(self, ticks_for):
        self.calls = []
        self._ticks_for = ticks_for  # callable(start, end) -> list[{"t","p"}]

    def fetch_price_history(self, token_id, start_ts, end_ts, fidelity=60):
        self.calls.append((start_ts, end_ts))
        return self._ticks_for(start_ts, end_ts)


def test_chunking_splits_long_window_and_merges_sorted_deduped():
    # A 40-day window must be paged in <=15-day (CHUNK_DAYS) chunks: 3 calls.
    start = 1_000_000
    end = start + 40 * 86400
    # Each chunk returns one tick at its own start, plus a shared duplicate timestamp.
    dup_t = start + 5
    f = _FakeFetcher(lambda s, e: [{"t": s, "p": 0.5}, {"t": dup_t, "p": 0.7}])
    out = fsc._chunked_price_history(f, "tok", start, end)
    assert len(f.calls) == 3  # 40/15 -> 3 windows
    # Windows tile [start, end) with a 15-day stride, no gap/overlap in coverage.
    assert f.calls[0][0] == start
    assert f.calls[-1][1] == end
    # Output is sorted by t and de-duplicated (dup_t appears once).
    ts = [x["t"] for x in out]
    assert ts == sorted(ts)
    assert ts.count(dup_t) == 1


def _rm(resolution, start=None, token="yes"):
    return SimpleNamespace(
        market_id="m1", yes_token_id=token, resolution_time=resolution, start_date=start,
    )


def test_build_series_truncates_strictly_before_settlement_margin():
    res = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
    margin_s = 24 * 3600
    cutoff = int(res.timestamp()) - margin_s
    # The fetch is asked for [.., cutoff]; a malicious/edge fetcher returns ticks AT and AFTER
    # the cutoff (and after resolution). The builder MUST drop every tick >= cutoff.
    def ticks(s, e):
        return [
            {"t": cutoff - 3600, "p": 0.4},   # clean, kept
            {"t": cutoff, "p": 0.99},          # AT cutoff -> dropped
            {"t": cutoff + 3600, "p": 1.0},    # after cutoff -> dropped
            {"t": int(res.timestamp()), "p": 1.0},  # settlement pin -> dropped
        ]
    f = _FakeFetcher(ticks)
    series = fsc._build_series(f, _rm(res), window_cap_days=30, leakage_margin_seconds=margin_s)
    assert series, "expected the clean pre-cutoff tick to survive"
    assert all(tk["t"] < cutoff for tk in series), "NO tick may be at/after the settlement margin"
    assert max(tk["t"] for tk in series) == cutoff - 3600
    # The fetch window itself never extends past the cutoff.
    assert all(end <= cutoff for _, end in f.calls)


def test_build_series_respects_start_date_lower_bound():
    res = datetime(2025, 6, 1, tzinfo=timezone.utc)
    start = res - timedelta(days=3)  # market lived only 3 days
    margin_s = 24 * 3600
    f = _FakeFetcher(lambda s, e: [{"t": s, "p": 0.5}])
    fsc._build_series(f, _rm(res, start=start), window_cap_days=120, leakage_margin_seconds=margin_s)
    # Even with a 120-day cap, the fetch starts no earlier than the real market start.
    assert f.calls[0][0] >= int(start.timestamp())


def test_build_series_empty_when_start_after_cutoff():
    res = datetime(2025, 6, 1, tzinfo=timezone.utc)
    # start_date only 1h before resolution, margin 24h -> start >= cutoff -> nothing to fetch.
    start = res - timedelta(hours=1)
    f = _FakeFetcher(lambda s, e: [{"t": s, "p": 0.5}])
    series = fsc._build_series(f, _rm(res, start=start), window_cap_days=120, leakage_margin_seconds=24 * 3600)
    assert series == []
    assert f.calls == []  # short-circuits before any network call
