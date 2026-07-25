"""spike_detection.py — intraday price-spike detection + reversal labeling
(the EXP-006 research primitive: "price-reversal after hype-driven spikes").

WHY THIS EXISTS
`docs/growth/RESEARCH_MEMORY.md` (Research Run 20/21) surfaced EXP-006 — a
falsifiable hypothesis that a Polymarket political market's YES price, after a
sharp hype-driven spike, tends to *partially reverse* rather than persist. Run 21
pinned down that the raw intraday tick primitive already exists
(`PolymarketHistoryFetcher.fetch_price_history` returns the full
``[{"t": <unix_s>, "p": <0..1>}, ...]`` series), and named the ONLY missing
pieces as:

  (a) a spike-DETECTION function over a tick series (a threshold-Δ crossing
      within a rolling time window), and
  (b) a reversal-LABELING function (how much of the spike move reverted over a
      forward horizon).

This module is exactly (a) + (b). It is a research/measurement primitive, NOT a
strategy.

HONEST SCOPE — READ THIS
- **NO EDGE IS CLAIMED.** This module detects and *labels* events. It computes no
  PnL, sizes no trade, and is wired into NO live/paper trading path. Whether the
  labeled reversals constitute a validated, cost-net, out-of-sample edge is an
  open research question the walk-forward + F10/F11 gates must answer on a real
  corpus — and every prior candidate in this family has been REFUTED by those
  gates. Building the detector does not move the business-case constraint; it
  only unblocks the honest test of EXP-006.
- **LEAKAGE-SAFE BY CONSTRUCTION.** Detection is *causal*: a spike is confirmed at
  the FIRST tick whose trailing-window move crosses the threshold — that
  ``confirm_time`` is the earliest instant the spike is knowable, i.e. the only
  defensible decision instant for any backtest built on top of this. Reversal
  labeling looks ONLY at ticks STRICTLY AFTER ``confirm_time``. No function here
  ever reads a price from the future of the instant it reports as the decision
  time. If the forward horizon has no qualifying later tick, labeling RETURNS
  ``None`` — it never fabricates a future price.

DETERMINISTIC + PURE: stdlib only, no I/O, frozen dataclasses, stable ordering.
The same tick list always produces the same events, so this is reproducible and
fixture-testable (network lives only in the fetcher that produces the ticks).
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import isfinite
from typing import List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Named, defensible defaults (no magic numbers).
# ---------------------------------------------------------------------------
# A spike is a move of at least this many probability points (ABSOLUTE Δ on the
# 0..1 price scale) within the rolling window. 0.10 = a 10-point YES move, a
# genuinely sharp intraday jump for a liquid political market — not routine
# minute-to-minute noise. Callers should sweep this; it is not a tuned value.
DEFAULT_SPIKE_THRESHOLD: float = 0.10
# Rolling look-back window for the move, in seconds. 3600 = the move must occur
# within one hour to count as a "spike" (vs a slow drift). Callers sweep this.
DEFAULT_WINDOW_SECONDS: int = 3600
# Forward horizon over which reversal is measured, in seconds. 86400 = 24h.
DEFAULT_REVERSAL_HORIZON_SECONDS: int = 86400

# A prediction-market price is a probability. Ticks outside [PRICE_MIN, PRICE_MAX]
# (or non-finite) are corrupt and are DROPPED, never clamped (clamping would
# invent a plausible-looking price the venue never printed).
PRICE_MIN: float = 0.0
PRICE_MAX: float = 1.0

# Threshold comparisons are made with this tolerance so a move of EXACTLY the
# threshold counts. Prediction-market prices are cent-discrete, so exact-threshold
# moves (e.g. 0.50 → 0.60 == 0.10) genuinely occur; binary float makes that
# subtraction 0.0999999…, and a naive ``>=`` would silently drop the real move.
_THRESHOLD_EPS: float = 1e-9

UP = "UP"
DOWN = "DOWN"


# ---------------------------------------------------------------------------
# Value types (immutable)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tick:
    """One cleaned price observation: unix seconds + probability in [0, 1]."""

    t: int
    p: float


@dataclass(frozen=True)
class SpikeEvent:
    """A detected, CAUSALLY-CONFIRMED price spike.

    ``baseline_*`` is the reference point at the start of the trailing window.
    ``confirm_*`` is the DECISION INSTANT: the FIRST tick at which the move from the
    baseline crossed the threshold — the only causally-knowable entry point, and the
    price any backtest built on this must enter at. ``peak_*`` is the extreme the move
    reached before it ended (a sustained run extends the peak; it does NOT open a new
    spike). ``magnitude`` is the ABSOLUTE full move ``|peak_price - baseline_price|``;
    ``direction`` is UP or DOWN.

    NOTE the confirm/peak split is what keeps this leakage-safe AND non-double-counting:
    a directional run that never retraces by >= ``threshold`` is ONE event (confirm at
    the first crossing, peak at its top), NOT one per tick — sub-threshold wiggles inside
    the run do not split it. A retrace of >= ``threshold`` from the peak is deliberately a
    SEPARATE event (it is itself a detected reversal — exactly what EXP-006 studies), so a
    long move punctuated by real threshold-sized reversals yields several events, one per
    directional leg. Reversal labeling still measures from the *causal* confirm price,
    never the peak (which is only known after the fact).
    """

    baseline_time: int
    baseline_price: float
    confirm_time: int
    confirm_price: float
    peak_time: int
    peak_price: float
    direction: str
    magnitude: float


@dataclass(frozen=True)
class ReversalOutcome:
    """The forward label for a single ``SpikeEvent``.

    Measured STRICTLY after ``spike.confirm_time`` (leakage-safe). ``future_price``
    is the last tick at-or-before ``confirm_time + horizon`` and strictly after
    ``confirm_time``. ``reversal_fraction`` is the signed fraction of the spike
    move that reverted:

        move       = confirm_price - baseline_price          (signed)
        subsequent = future_price  - confirm_price           (signed)
        reversal_fraction = -subsequent / move

    So ``+1.0`` == fully reverted back to the baseline, ``0.0`` == held the spike
    level, and negative == continued in the SAME direction (the spike compounded).
    ``reverted`` is simply ``reversal_fraction > 0``.
    """

    spike: SpikeEvent
    future_time: int
    future_price: float
    reversal_fraction: float
    reverted: bool


# ---------------------------------------------------------------------------
# Tick cleaning (deterministic)
# ---------------------------------------------------------------------------
def clean_ticks(ticks: Sequence[Mapping]) -> List[Tick]:
    """Coerce a raw ``[{"t":..,"p":..}, ...]`` list into sorted, valid ``Tick``s.

    Deterministic cleaning rules (each applied for a reason, not cosmetics):
    - a tick whose ``t`` or ``p`` cannot be coerced to a finite number is DROPPED
      (corrupt row — not fabricated into a guess);
    - a ``p`` outside ``[PRICE_MIN, PRICE_MAX]`` is DROPPED (a probability cannot
      be < 0 or > 1; clamping would invent a price the venue never printed);
    - ticks are sorted by ``(t, p)`` ascending (real CLOB responses are ordered, but
      we never rely on the caller for that);
    - on an exact duplicate timestamp, the HIGHEST price is kept — a fixed tiebreak
      that depends ONLY on the values, never on the caller's input order, so the same
      logical tick set always yields the same series (duplicate timestamps are a rare
      pagination/retry artifact and usually carry identical prices anyway).
    """
    if not ticks:
        return []
    cleaned: List[Tick] = []
    for raw in ticks:
        if not isinstance(raw, Mapping):
            continue
        t_raw = raw.get("t")
        p_raw = raw.get("p")
        try:
            t = int(t_raw)
            p = float(p_raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(p) or p < PRICE_MIN or p > PRICE_MAX:
            continue
        cleaned.append(Tick(t=t, p=p))

    # Sort by (t, p) so among equal timestamps the order — and therefore the kept
    # value — is fixed by the DATA, not the caller's input order. Keeping the last per
    # timestamp then deterministically keeps the highest price.
    cleaned.sort(key=lambda tk: (tk.t, tk.p))
    deduped: List[Tick] = []
    for tk in cleaned:
        if deduped and deduped[-1].t == tk.t:
            deduped[-1] = tk  # highest price at this instant (input-order-independent)
        else:
            deduped.append(tk)
    return deduped


# ---------------------------------------------------------------------------
# (a) Spike detection — causal, leakage-safe, non-overlapping
# ---------------------------------------------------------------------------
def detect_spikes(
    ticks: Sequence[Mapping],
    *,
    threshold: float = DEFAULT_SPIKE_THRESHOLD,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> List[SpikeEvent]:
    """Detect threshold-Δ price spikes over a rolling time window.

    A spike is CONFIRMED at the first tick ``i`` whose move relative to the
    reference price at the start of the trailing ``window_seconds`` reaches
    ``threshold`` in absolute value. Detection is *causal* — only ticks at or
    before ``i`` are consulted — so ``confirm_time`` is a valid decision instant.

    Events are NON-OVERLAPPING: an open spike EXTENDS through sub-threshold wiggles
    (tracking its peak) and only CLOSES when the price retraces from that peak by
    >= ``threshold``. So a directional run that never retraces that far is ONE spike,
    while a genuine >= ``threshold`` retrace both closes the spike and (if it clears the
    threshold from the new reference) opens the opposite one — each directional leg of a
    move is its own event.

    Raises ``ValueError`` on a non-positive ``threshold`` or ``window_seconds``.
    Returns ``[]`` for an empty/too-short series (never raises on thin data).
    """
    if threshold <= 0:
        raise ValueError(f"threshold must be positive: {threshold}")
    if window_seconds <= 0:
        raise ValueError(f"window_seconds must be positive: {window_seconds}")

    series = clean_ticks(ticks)
    if len(series) < 2:
        return []

    events: List[SpikeEvent] = []
    # Ticks strictly before `floor_time` are never eligible as a baseline. It only ever
    # advances forward (to a closed spike's peak), so a completed move is never
    # re-detected from a stale earlier reference.
    floor_time = series[0].t
    # Currently-open spike (None between spikes): the baseline it opened from, its
    # direction, the causal confirm tick, and the running peak (extreme so far).
    open_baseline: Optional[Tick] = None
    open_dir = UP
    open_confirm: Optional[Tick] = None
    open_peak: Optional[Tick] = None

    # Timestamps hoisted once for the binary search below. `series` is immutable for the
    # rest of this call, so this stays in lockstep with it.
    times = [tk.t for tk in series]

    def _window_baseline(cur: Tick) -> Optional[Tick]:
        """Earliest tick in ``[max(cur.t - window, floor_time), cur.t)`` — the
        reference at the start of the trailing window. ``None`` if none qualifies.

        This used to scan `series` from index 0 on every call, making detection O(n^2).
        Measured by the independent Quality Auditor at 91% of the backtest engine's wall
        clock. `series` is sorted ascending by `clean_ticks`, so the first qualifying tick
        is found by binary search instead — same tick, same result, O(log n).

        Equivalence with the old scan: it returned the first `tk` with `tk.t >= lower`,
        breaking once `tk.t >= cur.t`. `bisect_left` on `lower` yields exactly that first
        index; the `< cur.t` check reproduces the break. This holds for every case,
        including `idx == 0`, `idx == len(series)`, and `lower > cur.t` (both return None).
        Note it is correct PER CALL and does NOT lean on `lower` advancing monotonically,
        so the mutation of `floor_time` between iterations cannot invalidate it.

        (`clean_ticks` dedups by timestamp upstream, so `times` is strictly increasing and
        the duplicate-timestamp tie-break question never arises here in practice —
        `bisect_left` would pick the first of a run regardless, which is what the old scan
        did.)
        """
        lower = cur.t - window_seconds
        if lower < floor_time:
            lower = floor_time
        idx = bisect_left(times, lower)
        if idx < len(series) and times[idx] < cur.t:
            return series[idx]
        return None

    def _try_open(cur: Tick) -> bool:
        nonlocal open_baseline, open_dir, open_confirm, open_peak
        base = _window_baseline(cur)
        if base is None:
            return False
        move = cur.p - base.p
        if abs(move) < threshold - _THRESHOLD_EPS:
            return False
        open_baseline = base
        open_dir = UP if move > 0 else DOWN
        open_confirm = cur
        open_peak = cur
        return True

    def _emit() -> None:
        assert open_baseline is not None and open_confirm is not None and open_peak is not None
        events.append(
            SpikeEvent(
                baseline_time=open_baseline.t,
                baseline_price=open_baseline.p,
                confirm_time=open_confirm.t,
                confirm_price=open_confirm.p,
                peak_time=open_peak.t,
                peak_price=open_peak.p,
                direction=open_dir,
                magnitude=abs(open_peak.p - open_baseline.p),
            )
        )

    for i in range(1, len(series)):
        cur = series[i]
        if open_baseline is None:
            _try_open(cur)
            continue
        # In an open spike: extend the peak on continuation, else check for a
        # threshold RETRACE from the peak, which closes the spike.
        extends = (open_dir == UP and cur.p >= open_peak.p) or (
            open_dir == DOWN and cur.p <= open_peak.p
        )
        if extends:
            open_peak = cur
            continue
        if abs(cur.p - open_peak.p) >= threshold - _THRESHOLD_EPS:
            _emit()
            floor_time = open_peak.t  # next spike is measured from the peak forward
            open_baseline = None
            # This same retrace tick may itself open the OPPOSITE spike.
            _try_open(cur)

    if open_baseline is not None:
        _emit()
    return events


# ---------------------------------------------------------------------------
# (b) Reversal labeling — strictly forward-looking, leakage-safe
# ---------------------------------------------------------------------------
def label_reversal(
    ticks: Sequence[Mapping],
    spike: SpikeEvent,
    *,
    horizon_seconds: int = DEFAULT_REVERSAL_HORIZON_SECONDS,
) -> Optional[ReversalOutcome]:
    """Label how much of ``spike`` reverted over the forward ``horizon_seconds``.

    Uses ONLY ticks strictly after ``spike.confirm_time`` (the decision instant),
    up to and including ``confirm_time + horizon_seconds``. The forward price is
    the LAST such tick (closest to the horizon end without exceeding it).

    Returns ``None`` if no tick exists strictly after ``confirm_time`` within the
    horizon (honest "cannot label" — never fabricates a future price), or if the
    spike magnitude is zero (no move to revert).

    Raises ``ValueError`` on a non-positive ``horizon_seconds``.
    """
    if horizon_seconds <= 0:
        raise ValueError(f"horizon_seconds must be positive: {horizon_seconds}")

    move = spike.confirm_price - spike.baseline_price
    if move == 0:
        return None

    series = clean_ticks(ticks)
    horizon_end = spike.confirm_time + horizon_seconds
    future: Optional[Tick] = None
    for tk in series:
        if tk.t <= spike.confirm_time:
            continue
        if tk.t > horizon_end:
            break
        future = tk  # keep advancing to the last tick within the horizon
    if future is None:
        return None

    subsequent = future.p - spike.confirm_price
    reversal_fraction = -subsequent / move
    return ReversalOutcome(
        spike=spike,
        future_time=future.t,
        future_price=future.p,
        reversal_fraction=reversal_fraction,
        reverted=reversal_fraction > 0,
    )


def label_reversals(
    ticks: Sequence[Mapping],
    spikes: Sequence[SpikeEvent],
    *,
    horizon_seconds: int = DEFAULT_REVERSAL_HORIZON_SECONDS,
) -> List[ReversalOutcome]:
    """Label every spike, DROPPING those with no qualifying forward tick.

    Convenience batch wrapper over :func:`label_reversal`. The returned list is in
    spike order but may be shorter than ``spikes`` (un-labelable spikes are
    honestly omitted rather than filled with a placeholder).
    """
    out: List[ReversalOutcome] = []
    for sp in spikes:
        outcome = label_reversal(ticks, sp, horizon_seconds=horizon_seconds)
        if outcome is not None:
            out.append(outcome)
    return out
