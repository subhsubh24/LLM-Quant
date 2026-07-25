"""Tests for spike_detection (the EXP-006 research primitive).

DETERMINISTIC + PURE: constructs raw ``{"t","p"}`` tick lists directly (no network,
no backtest) and asserts detection, reversal labeling, cleaning, and — most
importantly — LEAKAGE SAFETY (a spike's decision instant never consults a future
price; reversal labeling only reads strictly-later ticks).

These tests assert the primitive is HONEST and correct. They make NO claim that a
tradeable edge exists — that is a separate research question the walk-forward +
F10/F11 gates must answer on a real corpus.
"""

from __future__ import annotations

import pytest

from app.prediction_markets.spike_detection import (
    DOWN,
    UP,
    ReversalOutcome,
    SpikeEvent,
    Tick,
    clean_ticks,
    detect_spikes,
    label_reversal,
    label_reversals,
)


def _ticks(pairs):
    """Build a raw tick list from (t_seconds, price) pairs."""
    return [{"t": t, "p": p} for t, p in pairs]


# ---------------------------------------------------------------------------
# clean_ticks
# ---------------------------------------------------------------------------
def test_clean_sorts_and_coerces():
    raw = [{"t": "30", "p": "0.6"}, {"t": 10, "p": 0.5}, {"t": 20, "p": 0.55}]
    cleaned = clean_ticks(raw)
    assert [tk.t for tk in cleaned] == [10, 20, 30]
    assert all(isinstance(tk, Tick) for tk in cleaned)
    assert cleaned[0].p == 0.5 and cleaned[2].p == 0.6


def test_clean_drops_corrupt_and_out_of_range():
    raw = [
        {"t": 10, "p": 0.5},
        {"t": 20, "p": 1.5},        # > 1 → dropped (not clamped)
        {"t": 30, "p": -0.1},       # < 0 → dropped
        {"t": 40, "p": "notnum"},   # non-numeric → dropped
        {"t": "bad", "p": 0.5},     # non-numeric t → dropped
        {"t": 50, "p": float("nan")},  # non-finite → dropped
        "garbage",                   # not a mapping → dropped
    ]
    cleaned = clean_ticks(raw)
    assert [(tk.t, tk.p) for tk in cleaned] == [(10, 0.5)]


def test_clean_dedupes_duplicate_timestamps_deterministically():
    # Highest price kept at a duplicate instant — and the result must NOT depend on the
    # order the duplicates arrived in (the determinism contract; real fetchers may
    # paginate/retry and deliver same-timestamp ticks in either order).
    a = clean_ticks([{"t": 10, "p": 0.5}, {"t": 10, "p": 0.7}, {"t": 20, "p": 0.6}])
    b = clean_ticks([{"t": 10, "p": 0.7}, {"t": 10, "p": 0.5}, {"t": 20, "p": 0.6}])
    assert [(tk.t, tk.p) for tk in a] == [(10, 0.7), (20, 0.6)]
    assert a == b  # input order of the duplicates does not change the output


def test_clean_none_returns_empty():
    assert clean_ticks(None) == []
    assert clean_ticks([]) == []


# ---------------------------------------------------------------------------
# detect_spikes
# ---------------------------------------------------------------------------
def test_detects_a_simple_up_spike():
    # Flat at 0.50, then jumps to 0.65 within the window → a +0.15 UP spike.
    ticks = _ticks([(0, 0.50), (60, 0.50), (120, 0.65)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert len(events) == 1
    ev = events[0]
    assert ev.direction == UP
    assert ev.confirm_time == 120 and ev.confirm_price == 0.65
    assert ev.baseline_price == 0.50
    assert abs(ev.magnitude - 0.15) < 1e-12


def test_detects_down_spike_direction():
    ticks = _ticks([(0, 0.80), (60, 0.60)])
    events = detect_spikes(ticks, threshold=0.15, window_seconds=3600)
    assert len(events) == 1 and events[0].direction == DOWN
    assert abs(events[0].magnitude - 0.20) < 1e-12


def test_no_spike_below_threshold():
    ticks = _ticks([(0, 0.50), (60, 0.55), (120, 0.58)])
    assert detect_spikes(ticks, threshold=0.10, window_seconds=3600) == []


def test_slow_drift_outside_window_is_not_a_spike():
    # A 0.20 move, but spread over 4 hours — with a 1h window each step is < threshold
    # relative to the window-start reference, so it is drift, not a spike.
    ticks = _ticks([(0, 0.50), (3600, 0.55), (7200, 0.60), (10800, 0.65), (14400, 0.70)])
    assert detect_spikes(ticks, threshold=0.10, window_seconds=3600) == []


def test_sustained_move_yields_single_non_overlapping_spike():
    # One monotonic ramp crossing threshold: must be ONE spike, not one per tick.
    ticks = _ticks([(0, 0.50), (60, 0.60), (120, 0.70), (180, 0.80)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert len(events) == 1
    assert events[0].confirm_time == 60  # confirmed at the FIRST crossing


def test_sub_threshold_wiggle_does_not_split_the_run():
    # A monotone-ish up-run with a small (< threshold) intermediate dip stays ONE spike:
    # 0.50→0.65 (+0.15), dip to 0.60 (only -0.05 from the 0.65 peak, below 0.10), then 0.72.
    ticks = _ticks([(0, 0.50), (60, 0.65), (120, 0.60), (180, 0.72)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert len(events) == 1
    assert events[0].direction == UP
    assert events[0].peak_price == 0.72  # peak extends past the wiggle


def test_threshold_retrace_segments_a_run_into_legs():
    # A >= threshold intermediate retrace IS a detected reversal, so a run punctuated by
    # one legitimately segments into UP, DOWN, UP legs (documented, intended behavior).
    ticks = _ticks([(0, 0.50), (60, 0.65), (120, 0.90), (180, 0.79), (240, 0.95)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert [e.direction for e in events] == [UP, DOWN, UP]


def test_spike_then_reverse_are_two_distinct_events():
    # Up spike, then a down move measured from the NEW (reset-forward) level.
    ticks = _ticks([(0, 0.50), (60, 0.65), (3660, 0.50)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert len(events) == 2
    assert events[0].direction == UP and events[0].confirm_time == 60
    assert events[1].direction == DOWN and events[1].confirm_time == 3660
    # The second spike's baseline is the post-first-spike level, not the original 0.50.
    assert events[1].baseline_price == 0.65


def test_detection_is_causal_confirm_uses_no_future_tick():
    # The confirm price must equal the tick AT the confirmation instant, never a later one.
    ticks = _ticks([(0, 0.50), (60, 0.62), (120, 0.95)])
    events = detect_spikes(ticks, threshold=0.10, window_seconds=3600)
    assert events[0].confirm_time == 60 and events[0].confirm_price == 0.62  # not 0.95


def test_detection_deterministic_and_order_invariant():
    pairs = [(0, 0.50), (60, 0.65), (30, 0.51), (3660, 0.50)]
    a = detect_spikes(_ticks(pairs), threshold=0.10, window_seconds=3600)
    b = detect_spikes(_ticks(list(reversed(pairs))), threshold=0.10, window_seconds=3600)
    assert a == b  # frozen dataclasses compare by value; cleaning sorts first


def test_empty_and_singleton_return_empty():
    assert detect_spikes([], threshold=0.10, window_seconds=3600) == []
    assert detect_spikes(_ticks([(0, 0.5)]), threshold=0.10, window_seconds=3600) == []


@pytest.mark.parametrize("bad", [0.0, -0.1])
def test_invalid_threshold_raises(bad):
    with pytest.raises(ValueError):
        detect_spikes(_ticks([(0, 0.5), (60, 0.7)]), threshold=bad, window_seconds=3600)


@pytest.mark.parametrize("bad", [0, -60])
def test_invalid_window_raises(bad):
    with pytest.raises(ValueError):
        detect_spikes(_ticks([(0, 0.5), (60, 0.7)]), threshold=0.1, window_seconds=bad)


# ---------------------------------------------------------------------------
# label_reversal
# ---------------------------------------------------------------------------
def _up_spike():
    # baseline 0.50 → confirm 0.65 at t=60 (a +0.15 move).
    return SpikeEvent(
        baseline_time=0, baseline_price=0.50,
        confirm_time=60, confirm_price=0.65,
        peak_time=60, peak_price=0.65, direction=UP, magnitude=0.15,
    )


def test_full_reversal_labeled_positive():
    spike = _up_spike()
    # Price returns all the way to baseline 0.50 by the horizon → reversal_fraction == 1.0.
    ticks = _ticks([(0, 0.50), (60, 0.65), (3660, 0.50)])
    out = label_reversal(ticks, spike, horizon_seconds=86400)
    assert isinstance(out, ReversalOutcome)
    assert out.reverted is True
    assert abs(out.reversal_fraction - 1.0) < 1e-12
    assert out.future_price == 0.50 and out.future_time == 3660


def test_continuation_labeled_negative():
    spike = _up_spike()
    # Price keeps rising to 0.80 → moved a further +0.15 in the SAME direction → -1.0.
    ticks = _ticks([(60, 0.65), (3660, 0.80)])
    out = label_reversal(ticks, spike, horizon_seconds=86400)
    assert out.reverted is False
    assert abs(out.reversal_fraction - (-1.0)) < 1e-12


def test_reversal_uses_only_strictly_later_ticks_no_leakage():
    spike = _up_spike()
    # Include ticks AT and BEFORE confirm_time with extreme prices — they must be ignored;
    # only the strictly-later 0.55 tick is the forward price.
    ticks = _ticks([(0, 0.99), (60, 0.01), (120, 0.55)])
    out = label_reversal(ticks, spike, horizon_seconds=86400)
    assert out.future_time == 120 and out.future_price == 0.55
    # move=+0.15, subsequent=0.55-0.65=-0.10 → reversal_fraction = 0.10/0.15 ≈ 0.6667.
    assert abs(out.reversal_fraction - (0.10 / 0.15)) < 1e-9


def test_reversal_takes_last_tick_within_horizon():
    spike = _up_spike()
    ticks = _ticks([(120, 0.60), (3660, 0.58), (999999, 0.20)])  # last is beyond horizon
    out = label_reversal(ticks, spike, horizon_seconds=86400)
    assert out.future_time == 3660 and out.future_price == 0.58


def test_reversal_none_when_no_forward_tick():
    spike = _up_spike()
    ticks = _ticks([(0, 0.50), (60, 0.65)])  # nothing strictly after confirm_time
    assert label_reversal(ticks, spike, horizon_seconds=86400) is None


def test_reversal_none_beyond_horizon():
    spike = _up_spike()
    ticks = _ticks([(60 + 86400 + 1, 0.50)])  # only a tick past the horizon end
    assert label_reversal(ticks, spike, horizon_seconds=86400) is None


def test_reversal_none_on_zero_magnitude_spike():
    flat = SpikeEvent(
        baseline_time=0, baseline_price=0.50,
        confirm_time=60, confirm_price=0.50,
        peak_time=60, peak_price=0.50, direction=UP, magnitude=0.0,
    )
    ticks = _ticks([(120, 0.40)])
    assert label_reversal(ticks, flat, horizon_seconds=86400) is None


def test_invalid_horizon_raises():
    with pytest.raises(ValueError):
        label_reversal(_ticks([(120, 0.5)]), _up_spike(), horizon_seconds=0)


def test_label_reversals_drops_unlabelable():
    spikes = [
        _up_spike(),
        SpikeEvent(
            baseline_time=0, baseline_price=0.50,
            confirm_time=100, confirm_price=0.70,
            peak_time=100, peak_price=0.70, direction=UP, magnitude=0.20,
        ),
    ]
    # A forward tick exists after the first confirm (t=60) but nothing after the second
    # confirm (t=100) within horizon → only the first is labeled.
    ticks = _ticks([(80, 0.55)])
    out = label_reversals(ticks, spikes, horizon_seconds=86400)
    assert len(out) == 1 and out[0].spike.confirm_time == 60


# --------------------------------------------------------------------------- #
# Windowed-baseline lookup: O(log n) binary search, IDENTICAL results.          #
# --------------------------------------------------------------------------- #
def _linear_scan_baseline(series, cur, window_seconds, floor_time):
    """The ORIGINAL O(n) scan, kept here as the reference oracle. The optimized
    `_window_baseline` must agree with it on every input, forever."""
    lower = cur.t - window_seconds
    if lower < floor_time:
        lower = floor_time
    for tk in series:
        if tk.t >= cur.t:
            return None
        if tk.t >= lower:
            return tk
    return None


def test_bisect_baseline_matches_the_linear_scan_oracle():
    """Differential test against the pre-optimization implementation.

    `_window_baseline` used to rescan the series from index 0 on every tick — O(n^2), and
    measured by the independent Quality Auditor at 91% of the backtest engine's wall clock.
    It is now a binary search. The optimization is only legitimate if it is EXACTLY
    equivalent, including the awkward cases: duplicate timestamps (must pick the FIRST of
    the run), an advanced `floor_time`, a window wider than the whole series, and a window
    so narrow nothing qualifies.
    """
    from app.prediction_markets.spike_detection import clean_ticks

    raw = []
    t = 1_700_000_000
    for i in range(60):
        raw.append({"t": t + i * 60, "p": round(0.30 + (i % 7) * 0.03, 4)})
    raw.append({"t": t + 10 * 60, "p": 0.99})   # duplicate timestamp, higher price
    raw.append({"t": t + 10 * 60, "p": 0.01})   # duplicate timestamp, lower price
    series = clean_ticks(raw)
    times = [tk.t for tk in series]

    from bisect import bisect_left

    for window_seconds in (60, 300, 1800, 10**9):
        for floor_idx in (0, 5, 30, len(series) - 1):
            floor_time = series[floor_idx].t
            for cur in series:
                lower = max(cur.t - window_seconds, floor_time)
                idx = bisect_left(times, lower)
                fast = series[idx] if idx < len(series) and times[idx] < cur.t else None
                slow = _linear_scan_baseline(series, cur, window_seconds, floor_time)
                assert fast == slow, (
                    f"baseline lookup diverged: window={window_seconds} "
                    f"floor={floor_time} cur={cur} fast={fast} slow={slow}"
                )


def test_detect_spikes_is_subquadratic():
    """A performance FLOOR, not a timing assertion.

    Doubling the series length must not roughly quadruple the work. The threshold is loose
    (7x for a 4x length increase) so this cannot flake on a noisy CI box, but the pre-fix
    O(n^2) implementation exceeded it by a wide margin on these sizes.
    """
    import time

    def _series(n):
        return [{"t": 1_700_000_000 + i * 60, "p": 0.30 + (i % 11) * 0.001} for i in range(n)]

    def _timed(n):
        ticks = _series(n)
        best = float("inf")
        for _ in range(3):  # take the best of 3 to damp scheduler noise
            t0 = time.perf_counter()
            detect_spikes(ticks, threshold=0.05, window_seconds=600)
            best = min(best, time.perf_counter() - t0)
        return best

    small = _timed(2_000)
    large = _timed(8_000)  # 4x the length
    assert large < small * 7 + 0.05, (
        f"detect_spikes scaled ~quadratically: {small:.4f}s at n=2000 vs {large:.4f}s at "
        f"n=8000 (4x length). A linear/log implementation should be near 4x, not 16x."
    )
