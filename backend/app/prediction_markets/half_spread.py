"""
half_spread.py — MEASURED bid/ask half-spreads for Polymarket, by price band.

WHY THIS EXISTS (ROADMAP C8 — the binding methodological constraint):
Every backtest in this repo is built on Polymarket's CLOB ``/prices-history`` series,
and that series returns the book **MIDPOINT**, not a traded price. This was established
three independent ways: live (``/prices-history`` 0.1965 == ``/midpoint`` 0.1965 against a
0.196/0.197 book), structurally (42.7% of the EXP-006b corpus's ticks carry four decimals —
the signature of a half-tick mid, against only 12.6% sitting on the 0.01 grid), and by the
venue's own API semantics.

A backtest that enters and exits at the mid therefore never pays the spread. Its entire
crossing cost is ``DEFAULT_SLIPPAGE_RATE = 0.005`` — a flat 0.5% of price. Measured against
real books the true half-spread is 5x-33x larger, and it is worst exactly in the low-price
band where both refuted strategy families concentrated their signal. Until entry and exit
pay a MEASURED half-spread at the traded price level, a result in this family does not mean
much: the EXP-006b breakeven cost multiple was 5.93x/8.33x with F11 significance lost at
1.7x/2.9x, so a 5x understatement is not a rounding error, it is the whole verdict.

WHAT THIS MODULE IS — AND IS NOT
It is a lookup from price to a measured half-spread, sourced from two INDEPENDENT real
measurements (below), with the sample size and provenance attached to every single band so
a reader can see instantly which numbers rest on 62 books and which rest on 2. It is NOT a
theory of spreads, NOT calibrated to any strategy, and NOT tuned — nothing in here was
chosen because it made a result look better. The models are exported side by side precisely
so a re-score can report the verdict across the plausible SPAN of the cost estimate instead
of picking the single number that happens to be most convenient.

THE TWO MEASUREMENTS
1. ``SOURCE_747BOOK`` — 747 live Polymarket political books, measured 2026-07-26 by an
   adversarial auditor during the EXP-006b gate and recorded in
   ``docs/autonomous-loop/EXP006B_RESULT.md``. Much the larger sample, but it covers only
   prices below 0.30 and its PER-BAND sample sizes were never published (only the 747
   total), so every band carries ``n=None`` here rather than an invented count.
2. ``SOURCE_DEPTH_PROBE`` — 62 live two-sided books captured by ``scripts/capacity_probe.py``
   on 2026-07-26 and COMMITTED at ``data/depth_probe_polymarket.json``. Smaller, but it is
   reproducible offline from committed bytes (``derive_bands_from_depth_probe`` regenerates
   its table exactly), it spans the whole [0, 1] price range, and it carries a real per-band
   ``n``. Two of its bands rest on n=2 and n=3 — stated, not hidden.

DEFINITION (fixed here so the two tables are compared like for like):
``half_spread_fraction = ((best_ask - best_bid) / 2) / mid``, banded by ``mid``. The
747-book table was banded by best ask rather than mid; at these spreads the two banding
choices differ only for quotes sitting on a band edge, but it IS a definitional difference
and it is one reason the two tables disagree in the thin bands.

DIRECTION OF ERROR: both samples are drawn from OPEN, volume-ordered (i.e. LIQUID) markets.
Depth and tightness at the liquid end OVERSTATE a random market's, so these half-spreads are
if anything an UNDER-estimate of the true cost. Every model here is therefore a LOWER bound
on crossing cost, and a strategy that dies under them dies harder in reality. That asymmetry
is the reason this module is safe to use for refutation and NOT sufficient to establish an
edge on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# Provenance labels, kept as constants so a band's source is a checked value rather than a
# free-text string a future edit could silently drift.
SOURCE_747BOOK = "747-live-political-books-2026-07-26 (EXP006B_RESULT.md)"
SOURCE_DEPTH_PROBE = "62-live-two-sided-books-2026-07-26 (data/depth_probe_polymarket.json)"
SOURCE_CONSERVATIVE = "per-band max(747book, depth_probe)"
# NOT a measurement: the theoretical tightest-possible crossing cost (half of one tick).
SOURCE_TICK_FLOOR = "theoretical half-tick FLOOR (a bound, not a measurement)"


@dataclass(frozen=True)
class SpreadBand:
    """One measured price band: ``[lo, hi)`` pays ``half_spread_frac`` of price per leg.

    ``n`` is the number of books behind the measurement, or ``None`` when the source
    published only an aggregate sample size. It is metadata for the reader — it never
    enters the arithmetic — but it is carried on every band because a 0.135 fraction backed
    by n=2 and one backed by n=747 are not the same claim, and a cost model that hides the
    difference invites exactly the false confidence this repo keeps having to correct.
    """

    lo: float
    hi: float
    half_spread_frac: float
    n: Optional[int]
    source: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.lo < self.hi):
            raise ValueError(f"band bounds must satisfy 0 <= lo < hi: [{self.lo}, {self.hi})")
        if self.half_spread_frac < 0.0:
            raise ValueError(f"half_spread_frac must be >= 0: {self.half_spread_frac}")
        if self.n is not None and self.n < 1:
            raise ValueError(f"n must be None or >= 1: {self.n}")


@dataclass(frozen=True)
class HalfSpreadModel:
    """A price -> measured half-spread lookup, plus its provenance.

    Bands must be sorted, non-overlapping and gapless, and must cover [0, 1]; the
    constructor enforces all of that rather than trusting the caller, because a silent gap
    would fall through to a fabricated default and a fabricated cost is exactly the class of
    defect this module exists to remove.
    """

    name: str
    bands: tuple[SpreadBand, ...]

    def __post_init__(self) -> None:
        if not self.bands:
            raise ValueError("a HalfSpreadModel needs at least one band")
        prev_hi = 0.0
        for b in self.bands:
            if abs(b.lo - prev_hi) > 1e-12:
                raise ValueError(
                    f"bands must be gapless and sorted: expected lo={prev_hi}, got {b.lo}"
                )
            prev_hi = b.hi
        if prev_hi < 1.0:
            raise ValueError(f"bands must cover up to price 1.0; they stop at {prev_hi}")

    def frac_for(self, price: float) -> float:
        """Measured half-spread as a FRACTION of price, for the band containing ``price``.

        Prices are clamped into [0, 1] before lookup: an out-of-range quote is a data
        defect the ingest layer already rejects, and inventing an extrapolated spread for
        one would be a fabrication. The final band is treated as closed on the right so
        ``price == 1.0`` resolves rather than falling off the end.
        """
        p = min(max(price, 0.0), 1.0)
        for b in self.bands:
            if b.lo <= p < b.hi:
                return b.half_spread_frac
        return self.bands[-1].half_spread_frac

    def half_spread_usd(self, price: float) -> float:
        """Measured half-spread in PRICE UNITS (dollars per contract) at ``price``.

        This is the amount a marketable order gives up crossing to the touch on ONE leg —
        the quantity the midpoint-based backtests never paid. There is deliberately no
        floor at half a tick: a floor would be an invented number, and the measurements
        already carry whatever the real tick grid imposed on them.
        """
        p = min(max(price, 0.0), 1.0)
        return p * self.frac_for(p)

    def band_for(self, price: float) -> SpreadBand:
        """The full band record (fraction + n + source) covering ``price``.

        Exposed so a re-score can report WHICH measurement priced each trade, making a
        result that leans on an n=2 band visible instead of buried.
        """
        p = min(max(price, 0.0), 1.0)
        for b in self.bands:
            if b.lo <= p < b.hi:
                return b
        return self.bands[-1]


# ---------------------------------------------------------------------------
# Measurement 1 — 747 live political books (EXP006B_RESULT.md, 2026-07-26)
# ---------------------------------------------------------------------------
# The auditor's published table covers only prices below 0.30, which is the band the fade
# and bucket families actually traded. Above 0.30 this source is SILENT, and rather than
# extrapolate it we fill those bands from the depth probe and label them accordingly — an
# extrapolated spread would be an invented number wearing a measured source's name.
_747BOOK_MEASURED: tuple[tuple[float, float, float], ...] = (
    (0.00, 0.01, 0.167),
    (0.01, 0.02, 0.045),
    (0.02, 0.05, 0.025),
    (0.05, 0.10, 0.058),
    (0.10, 0.30, 0.031),
)

# ---------------------------------------------------------------------------
# Measurement 2 — the committed 62-book depth probe (data/depth_probe_polymarket.json)
# ---------------------------------------------------------------------------
# These are the EXACT values `derive_bands_from_depth_probe` recomputes from the committed
# artifact; the test suite asserts the two agree, so this table cannot drift away from the
# bytes it claims to summarize. Note n=2 in [0.02, 0.05) and n=3 in [0.01, 0.02) and
# [0.05, 0.10) — those three medians are weak evidence and are marked as such.
_DEPTH_PROBE_MEASURED: tuple[tuple[float, float, float, int], ...] = (
    (0.00, 0.01, 0.126984, 12),
    (0.01, 0.02, 0.130435, 3),
    (0.02, 0.05, 0.135204, 2),
    (0.05, 0.10, 0.066667, 3),
    (0.10, 0.30, 0.032258, 7),
    (0.30, 0.70, 0.010025, 8),
    (0.70, 0.90, 0.005780, 7),
    (0.90, 0.98, 0.005464, 5),
    (0.98, 1.00, 0.000503, 15),
)

# The band grid every model shares, so the three models are directly comparable band by band.
BAND_EDGES: tuple[tuple[float, float], ...] = tuple(
    (lo, hi) for lo, hi, _f, _n in _DEPTH_PROBE_MEASURED
)


def _depth_probe_bands() -> tuple[SpreadBand, ...]:
    return tuple(
        SpreadBand(lo=lo, hi=hi, half_spread_frac=frac, n=n, source=SOURCE_DEPTH_PROBE)
        for lo, hi, frac, n in _DEPTH_PROBE_MEASURED
    )


def _747book_bands() -> tuple[SpreadBand, ...]:
    """The 747-book table below 0.30, completed above 0.30 from the depth probe.

    Each band keeps the source it actually came from, so the completion is visible in the
    output rather than smoothed into a single provenance claim.
    """
    measured = {(lo, hi): frac for lo, hi, frac in _747BOOK_MEASURED}
    bands: list[SpreadBand] = []
    for lo, hi, probe_frac, probe_n in _DEPTH_PROBE_MEASURED:
        if (lo, hi) in measured:
            bands.append(
                SpreadBand(
                    lo=lo,
                    hi=hi,
                    half_spread_frac=measured[(lo, hi)],
                    n=None,  # per-band n was never published; do not invent one
                    source=SOURCE_747BOOK,
                )
            )
        else:
            bands.append(
                SpreadBand(
                    lo=lo,
                    hi=hi,
                    half_spread_frac=probe_frac,
                    n=probe_n,
                    source=SOURCE_DEPTH_PROBE,
                )
            )
    return tuple(bands)


def _conservative_bands() -> tuple[SpreadBand, ...]:
    """Per band, the LARGER of the two measured fractions.

    Cost is the one direction where over-stating is safe: it can only shrink a claimed
    edge, never manufacture one. This model is the right one to judge a POSITIVE result
    against. It is NOT the right one to judge a negative result against — a signal killed
    only by the conservative model has not been refuted, it has been out-assumed, which is
    why the re-score harness reports all three.
    """
    a = {(b.lo, b.hi): b for b in _747book_bands()}
    bands: list[SpreadBand] = []
    for b in _depth_probe_bands():
        other = a[(b.lo, b.hi)]
        pick = b if b.half_spread_frac >= other.half_spread_frac else other
        bands.append(
            SpreadBand(
                lo=b.lo,
                hi=b.hi,
                half_spread_frac=pick.half_spread_frac,
                n=pick.n,
                source=f"{SOURCE_CONSERVATIVE} -> {pick.source}",
            )
        )
    return tuple(bands)


def _tick_floor_bands() -> tuple[SpreadBand, ...]:
    """The theoretical MINIMUM half-spread: one tick, everywhere.

    This is a BOUND, not a measurement and not a rival model. Polymarket quotes on a $0.01
    grid over most of the range and a $0.001 grid in the tails, so half of one tick is the
    tightest spread any marketable order could possibly cross — nothing can beat it. It is
    exported because an adversarial auditor made the fair point that reporting only the two
    measured models reports one end of the plausible span: it shows where the result dies
    but never where it survives, and a reader cannot tell whether the margin is a landslide
    or a whisker. Under this floor the EXP-006b th=0.15 cell DOES retain F11 significance,
    which is the honest other end of the range.

    Do NOT read it as a cost estimate. It assumes every market trades at the tightest
    quote observed anywhere, when the probe's own distribution puts 0.001 at the p25 of the
    LIQUID end of the market — so it is a floor that no real execution population reaches.
    """
    bands: list[SpreadBand] = []
    for lo, hi, _frac, _n in _DEPTH_PROBE_MEASURED:
        mid = (lo + hi) / 2.0
        tick = 0.01 if 0.10 <= mid <= 0.90 else 0.001
        # Expressed as a fraction of the band midpoint so it plugs into the same lookup.
        bands.append(
            SpreadBand(
                lo=lo,
                hi=hi,
                half_spread_frac=(tick / 2.0) / mid,
                n=None,
                source=SOURCE_TICK_FLOOR,
            )
        )
    return tuple(bands)


POLYMARKET_HALF_SPREAD_747BOOK = HalfSpreadModel(name="747book", bands=_747book_bands())
POLYMARKET_HALF_SPREAD_DEPTH_PROBE = HalfSpreadModel(
    name="depth_probe", bands=_depth_probe_bands()
)
POLYMARKET_HALF_SPREAD_CONSERVATIVE = HalfSpreadModel(
    name="conservative", bands=_conservative_bands()
)
POLYMARKET_HALF_SPREAD_TICK_FLOOR = HalfSpreadModel(
    name="tick_floor", bands=_tick_floor_bands()
)

# The two independent MEASUREMENTS plus their conservative combination. These are the models
# a cost claim may rest on. The tick floor is deliberately NOT in here — it is a bound, and
# mixing it in would invite someone to quote it as a cost estimate.
MODELS: "dict[str, HalfSpreadModel]" = {
    "747book": POLYMARKET_HALF_SPREAD_747BOOK,
    "depth_probe": POLYMARKET_HALF_SPREAD_DEPTH_PROBE,
    "conservative": POLYMARKET_HALF_SPREAD_CONSERVATIVE,
}

# Reported alongside the models so the span has BOTH ends, never treated as one of them.
BOUNDS: "dict[str, HalfSpreadModel]" = {
    "tick_floor": POLYMARKET_HALF_SPREAD_TICK_FLOOR,
}


# ---------------------------------------------------------------------------
# Offline reproduction from the committed probe artifact
# ---------------------------------------------------------------------------
def _median(values: Sequence[float]) -> float:
    """Median with the repo's usual explicit tie handling (no statistics import needed).

    Written out rather than imported so this module has zero dependencies beyond the
    standard dataclasses/typing surface and can be reasoned about by an auditor in one read.
    """
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise ValueError("median of an empty sequence")
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def derive_bands_from_depth_probe(rows: Sequence[dict]) -> tuple[SpreadBand, ...]:
    """Recompute the depth-probe band table from raw probe rows.

    ``rows`` is the ``rows`` array of ``data/depth_probe_polymarket.json``: each row carries
    a real two-sided ``best_bid``/``best_ask`` (the probe REFUSES a one-sided book rather
    than fabricating a 0/1 quote, so every row here is a genuine quote).

    A band with no rows raises rather than silently returning a default — a missing
    measurement must surface, not quietly become a number. The rounding to six places
    matches the committed table so the equality assertion in the tests is exact rather than
    tolerance-based.
    """
    bands: list[SpreadBand] = []
    for lo, hi in BAND_EDGES:
        fracs: list[float] = []
        for r in rows:
            bid = float(r["best_bid"])
            ask = float(r["best_ask"])
            mid = (bid + ask) / 2.0
            if mid <= 0.0:
                continue
            if lo <= mid < hi:
                fracs.append(((ask - bid) / 2.0) / mid)
        if not fracs:
            raise ValueError(
                f"no probe rows fall in band [{lo}, {hi}) — the committed table cannot be "
                "reproduced from these rows"
            )
        bands.append(
            SpreadBand(
                lo=lo,
                hi=hi,
                half_spread_frac=round(_median(fracs), 6),
                n=len(fracs),
                source=SOURCE_DEPTH_PROBE,
            )
        )
    return tuple(bands)
