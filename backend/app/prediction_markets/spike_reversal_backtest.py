"""spike_reversal_backtest.py — the EXP-006 fade-the-spike strategy backtest
(the cost-net, leakage-safe, F10/F11-gated PnL layer on top of ``spike_detection``).

WHY THIS EXISTS
``docs/growth/RESEARCH_MEMORY.md`` (Runs 20–26) grew EXP-006 — the falsifiable
hypothesis that a Polymarket political market's YES price, after a sharp hype-driven
spike, tends to *partially revert* rather than persist — but the pilot stalled at a
**raw lag-1 autocorrelation probe** (N=14–67): NO strategy code, NO cost model, NO
F10/F11 gate. The independent Quality Auditor named the exact next step
(``docs/quality/QUALITY_SCORECARD.md``, business_case_strength gap): *"EXP-006 must
reach N≥100 with a full strategy + cost model + F10 (non-fragile) + F11 (CI excludes 0)
walk_forward cost-net"*. This module is that layer.

It turns each detected, causally-confirmed spike into a **fade trade** — a bet the move
partially reverts — priced end-to-end through the single-source-of-truth
``cost_model`` (entry AND exit legs), aggregated into a realized per-trade PnL vector,
and run through the SAME two integrity gates every real corpus is: F11 bootstrap
significance (``bootstrap_oos_significance`` — is the PnL distinguishable from zero?) and
F10 regime-slice fragility (``regime_slice`` — is the edge broad, or propped up by one
market/bucket?). It ships the **per-trade concentration cap** the Run 21 caution demanded
FROM DAY ONE (the biggest 2024 political spike did NOT revert — an N=1 concentration
risk), two ways at once: EQUAL-WEIGHT sizing (a fixed dollar budget per trade, so no
single market can dominate by size) and a hard ``max_trades_per_market`` cap (so a market
that spikes repeatedly cannot flood the sample with correlated bets).

HONEST SCOPE — READ THIS
- **NO EDGE IS CLAIMED by this module.** It is a measurement engine, exactly like
  ``walk_forward``: fed a genuinely mean-reverting tick corpus it recovers the reversion
  edge net of costs; fed a random walk or a momentum corpus it reports ~0 or NEGATIVE (the
  round-trip cost hurdle bites). Whether EXP-006 is a *validated* edge is an empirical
  question answered ONLY by running this on a real, point-in-time, non-survivorship
  intraday-tick corpus of sufficient N — and the every-prior-candidate-refuted prior
  applies. ``is_validated_edge`` is TRUE only when N ≥ the pre-registered floor AND F11 is
  ``significant_positive`` AND F10 is non-fragile; anything else is ``edge-not-proven``,
  which is an honest result, not a failure.
- **LEAKAGE-SAFE BY CONSTRUCTION**, inherited from ``spike_detection``: entry is at the
  spike's ``confirm_time`` (the earliest instant the spike is knowable — detection is
  causal, consulting only ticks at or before it), and the exit price is
  ``label_reversal``'s forward price, which reads ONLY ticks STRICTLY AFTER
  ``confirm_time``. No function here reads a price from the future of the instant it trades
  at. A spike with no qualifying forward tick is DROPPED (never filled at a fabricated
  price).
- **COST-NET, single source of truth.** Both legs price through ``cost_model``: entry at
  ``effective_buy_price`` (slippage + fee against us on the way in), exit at
  ``effective_sell_price`` (slippage + fee against us on the way out). A round-trip at an
  unchanged price books the two-way cost as a loss — the hurdle the reversion must clear.

DETERMINISTIC + PURE: stdlib + the two in-repo gate modules, no I/O, frozen dataclasses,
markets iterated in sorted id order, bootstrap seeded. Same ticks + same config ⇒ same
trades ⇒ same verdict, so this is reproducible and fixture-testable (network lives only in
the fetcher that produces the ticks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Mapping, Optional, Sequence

from .bootstrap_oos_significance import OOSSignificance, bootstrap_oos_significance
from .cost_model import DEFAULT_COST_MODEL, CostModel
from .regime_slice import (
    CATEGORY_PNL_CONCENTRATION,
    CONFIDENCE_PNL_CONCENTRATION,
    EXTREME_CONFIDENCE_PNL_CONCENTRATION,
    HORIZON_PNL_CONCENTRATION,
    TIME_PNL_CONCENTRATION,
    TOP_MARKET_PNL_CONCENTRATION,
    RegimeSliceReport,
    SlicePnL,
    analyze_regime_slices,
)
from .spike_detection import (
    DEFAULT_REVERSAL_HORIZON_SECONDS,
    DEFAULT_SPIKE_THRESHOLD,
    DEFAULT_WINDOW_SECONDS,
    UP,
    detect_spikes,
    label_reversal,
)
from .walk_forward import BacktestTrade


# ---------------------------------------------------------------------------
# Config — named, defensible defaults (no magic numbers).
# ---------------------------------------------------------------------------
# The pre-registered minimum event count below which NO positive result can be called a
# validated edge, however green the point estimate. Matches the 100-event floor the
# EXP-006 pilot writeups and the Quality Auditor both pin (RESEARCH_MEMORY Runs 20–26).
DEFAULT_MIN_TRADES_FOR_EDGE: int = 100
# EQUAL-WEIGHT position size, in USD, deployed on EVERY fade trade. Fixed (not Kelly) BY
# DESIGN: equal sizing removes size-driven PnL concentration entirely, so a single lucky
# market cannot dominate the total by betting bigger — the concentration failure mode that
# sank the bucket-calibration family. F10 still checks residual per-market concentration.
DEFAULT_BUDGET_PER_TRADE_USD: float = 100.0
# Per-MARKET trade cap — the Run 21 N=1 concentration caution made structural. A market
# that spikes many times cannot flood the sample with correlated bets on the same
# underlying event; only its first ``max_trades_per_market`` spikes (in time order) trade.
# KEEP THIS AT 1 for any edge claim: raising it feeds MULTIPLE correlated same-market trades
# into the F11 bootstrap as if they were independent draws, over-stating significance (the
# F10 single-market check only partially compensates). >1 is for exploratory sweeps only.
DEFAULT_MAX_TRADES_PER_MARKET: int = 1
# Minimum realized hit-rate for a validated edge — the 4th criterion the Quality Auditor's
# validated-edge bar names alongside N>=floor, F11 significant, F10 non-fragile. Enforced so
# a positive total driven by a few large asymmetric wins at a sub-50% hit-rate is NOT called
# a validated candidate (it may be, but it must clear this too, matching the stated bar).
MIN_HIT_RATE_FOR_EDGE: float = 0.50
# Magnitude (salience) strata for the spike-size breakdown REPORT, in ABSOLUTE probability
# points of the full move |peak - baseline|. These bands are for HUMAN-READABLE display only
# (the ``strata`` field); they do NOT drive the size-robustness gate (which is config-independent
# — see ``_size_robustness``), so a caller sweeping edges cannot disable the gate by collapsing
# all magnitudes into one bin. Round, first-principles boundaries — a 15/25/40-point intraday
# move is a moderate / large / extreme swing — NOT tuned on any result. The three edges yield
# four report bands: [0,0.15), [0.15,0.25), [0.25,0.40), [0.40, ∞). (No spike magnitude is ever
# below the configured spike ``threshold``, so the first band is nominally [0,..) but in practice
# starts at ``threshold``.)
DEFAULT_MAGNITUDE_STRATUM_EDGES: tuple[float, ...] = (0.15, 0.25, 0.40)
# The size-robustness gate (Run 21's LOAD-BEARING N=1 caution: *the biggest 2024 political spike
# did NOT revert — it kept trending*) tests the LARGEST spikes by RANK, not by the caller's report
# bands — so no ``magnitude_stratum_edges`` choice can turn it off. The "largest-spike cohort" is
# the top this-fraction of realized trades by |move|; rank-based means the cohort always holds a
# real share of the sample (it never goes sparse in the tail, and it cannot be binned away).
LARGE_SPIKE_COHORT_FRACTION: float = 1.0 / 3.0
# The largest-spike cohort needs at least this many trades before its result is trusted enough to
# call it a losing REGIME; below it the gate ABSTAINS (and says so) rather than judging on noise.
# The cohort is judged by the SAME bootstrap-significance test the aggregate uses (F11), not a bare
# sign test, so a cohort that is only negative by sampling variance is NOT flagged. Not tuned.
MIN_STRATUM_TRADES_FOR_FRAGILITY: int = 20
# Below this span between the smallest and largest realized |move|, the corpus has effectively ONE
# spike size, so size-robustness is structurally unassessable (like the single-valued horizon axis
# the F10 check excludes) — the gate ABSTAINS WITH DISCLOSURE rather than pretending to assess it.
# One cent: prediction-market prices are ~cent-discrete, so a narrower span is not real dispersion.
MIN_MAGNITUDE_DISPERSION: float = 0.01
# The two near-certain confidence bands, mirroring regime_slice._EXTREME_CONFIDENCE_LABELS
# (defined locally rather than importing a private name; the vocabulary is stable).
_EXTREME_CONF_LABELS: tuple[str, str] = ("0-10%", "90-100%")


def _validate_magnitude_edges(edges: Sequence[float]) -> None:
    """Shared precondition for the report-band edges — strictly increasing, inside (0, 1).

    Used by both ``FadeSpikeConfig.__post_init__`` and the public ``stratify_by_magnitude`` so a
    direct caller of the latter gets the SAME loud rejection instead of silently dead/overlapping
    bands (the module's never-fabricate ethos). These edges only shape the human-readable report;
    the size-robustness GATE does not use them (it is rank-based), so bad edges cannot mis-gate."""
    if not edges:
        raise ValueError("magnitude edges must be non-empty")
    for a, b in zip(edges, edges[1:]):
        if not (b > a):
            raise ValueError(f"magnitude edges must be strictly increasing: {tuple(edges)}")
    if edges[0] <= 0.0 or edges[-1] >= 1.0:
        raise ValueError(f"magnitude edges must lie strictly within (0, 1): {tuple(edges)}")


@dataclass(frozen=True)
class FadeSpikeConfig:
    """Parameters for the fade-the-spike backtest. All swept, none tuned-in secret."""

    threshold: float = DEFAULT_SPIKE_THRESHOLD
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    horizon_seconds: int = DEFAULT_REVERSAL_HORIZON_SECONDS
    budget_per_trade_usd: float = DEFAULT_BUDGET_PER_TRADE_USD
    max_trades_per_market: int = DEFAULT_MAX_TRADES_PER_MARKET
    min_trades_for_edge: int = DEFAULT_MIN_TRADES_FOR_EDGE
    # Salience/magnitude strata edges (absolute |peak-baseline| move), swept not tuned.
    magnitude_stratum_edges: tuple[float, ...] = DEFAULT_MAGNITUDE_STRATUM_EDGES
    # F11 bootstrap knobs (passed straight through — seeded ⇒ deterministic).
    bootstrap_n: int = 2000
    bootstrap_seed: int = 12345
    cost_model: CostModel = field(default=DEFAULT_COST_MODEL)

    def __post_init__(self) -> None:
        if self.threshold <= 0:
            raise ValueError(f"threshold must be positive: {self.threshold}")
        if self.window_seconds <= 0:
            raise ValueError(f"window_seconds must be positive: {self.window_seconds}")
        if self.horizon_seconds <= 0:
            raise ValueError(f"horizon_seconds must be positive: {self.horizon_seconds}")
        if self.budget_per_trade_usd <= 0:
            raise ValueError(f"budget_per_trade_usd must be positive: {self.budget_per_trade_usd}")
        if self.max_trades_per_market < 1:
            raise ValueError(f"max_trades_per_market must be >= 1: {self.max_trades_per_market}")
        if self.min_trades_for_edge < 1:
            raise ValueError(f"min_trades_for_edge must be >= 1: {self.min_trades_for_edge}")
        _validate_magnitude_edges(self.magnitude_stratum_edges)


# ---------------------------------------------------------------------------
# Value types (immutable)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FadeTrade:
    """One realized fade-the-spike trade: enter at the spike's causal confirm instant,
    exit at the forward horizon price, cost-net both legs.

    A spike UP (YES ran up) is faded by BUYING NO (betting YES falls back); a spike DOWN
    is faded by BUYING YES. ``entry_basis``/``exit_basis`` are the RAW quoted prices of the
    FADED side at entry and exit; ``entry_cost``/``exit_proceeds`` are those prices after
    the cost model's two-way friction. PnL is ``contracts * (exit_proceeds - entry_cost)``.
    """

    market_id: str
    category: Optional[str]
    spike_direction: str        # UP or DOWN — the spike that was faded
    faded_side: str             # "NO" (faded an UP spike) or "YES" (faded a DOWN spike)
    confirm_time: int           # unix seconds — the causal entry instant
    exit_time: int              # unix seconds — the forward horizon exit instant
    entry_basis: float          # raw quoted price of the faded side at entry
    exit_basis: float           # raw quoted price of the faded side at exit
    entry_cost: float           # all-in per-contract cost (slippage + fee, buy leg)
    exit_proceeds: float        # per-contract proceeds (slippage + fee, sell leg)
    contracts: float
    budget_usd: float           # cash deployed at entry (== contracts * entry_cost)
    pnl_usd: float              # contracts * (exit_proceeds - entry_cost)
    is_win: bool
    reversal_fraction: float    # signed fraction of the spike move that reverted (label)
    spike_magnitude: float      # absolute |peak - baseline| move of the faded spike (salience)


@dataclass(frozen=True)
class MagnitudeStratum:
    """The fade's realized behaviour within one spike-SIZE band — the salience breakdown that
    makes the Run 21 caution auditable. A ``mean_reversal_fraction`` near +1 means spikes in this
    size band fully reverted; near 0 they held; NEGATIVE means they COMPOUNDED (persisted), which
    is exactly the large-spike failure mode the caution flags. ``total_pnl_usd`` is the cost-net
    fade PnL earned in the band. Empty bands report ``None`` for the means/hit-rate (never a
    fabricated 0).

    POST-HOC KEY — READ THIS: the band is keyed on ``spike_magnitude`` = ``|peak - baseline|``,
    and the peak can EXTEND past the trade's ``confirm_time`` entry (a run that keeps going lifts
    the peak), so which band a trade lands in is NOT knowable at decision time. That is fine here —
    this is a RETROSPECTIVE DIAGNOSTIC (and the tightening-only size-robustness gate), never a
    pre-trade filter: nothing sizes or selects a trade by its band. Do NOT repurpose these bands
    for a live/pre-trade sizing decision — the key would be look-ahead there."""

    label: str
    lo: float                              # inclusive lower |move| edge
    hi: Optional[float]                    # exclusive upper edge (None = open-ended top band)
    n_trades: int
    total_pnl_usd: float
    hit_rate: Optional[float]
    mean_reversal_fraction: Optional[float]
    mean_magnitude: Optional[float]


@dataclass(frozen=True)
class SpikeReversalResult:
    """The full, honest verdict of a fade-the-spike backtest.

    ``is_validated_edge`` is the AND of three independent gates — sufficient N, F11
    significance (CI on total PnL excludes zero on the POSITIVE side), and F10
    non-fragility (the edge is broad, not propped up by one market/bucket). Any single
    gate failing ⇒ ``edge-not-proven`` (an honest result). It never depends on the raw
    point estimate alone.
    """

    trades: tuple[FadeTrade, ...]
    n_trades: int
    n_markets_traded: int
    total_pnl_usd: float
    hit_rate: Optional[float]              # fraction of winning trades (None when n == 0)
    n_markets_scanned: int
    n_spikes_detected: int
    n_spikes_unlabelable: int              # spikes with no qualifying forward tick (dropped)
    significance: OOSSignificance          # F11
    regime: Optional[RegimeSliceReport]    # F10 (None only when there are zero trades)
    strata: tuple[MagnitudeStratum, ...]   # per-spike-size reversion breakdown (report, Run 21)
    size_robustness: str                   # machine-readable status of the size-robustness gate:
                                           # "assessed…" / "UNASSESSED…" / "FRAGILE…" — so a reader
                                           # (or the JSON) can tell whether the largest-spike check
                                           # actually ran, without diffing runs.
    is_validated_edge: bool
    verdict: str                           # human-readable, always honest


# ---------------------------------------------------------------------------
# Backtest (pure, deterministic)
# ---------------------------------------------------------------------------
def _utc(unix_seconds: int) -> datetime:
    """Unix seconds → tz-aware UTC datetime (regime_slice buckets on datetimes)."""
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def _fade_trade(
    market_id: str,
    category: Optional[str],
    spike_direction: str,
    confirm_price: float,
    exit_price: float,
    confirm_time: int,
    exit_time: int,
    reversal_fraction: float,
    spike_magnitude: float,
    cfg: FadeSpikeConfig,
) -> Optional[FadeTrade]:
    """Build one cost-net fade trade, or None if it cannot be sized sensibly.

    UP spike → fade by buying NO (basis ``1 - price``); DOWN spike → fade by buying YES
    (basis ``price``). Both legs price through ``cfg.cost_model``. Returns None when the
    entry cost is degenerate (basis at 0/1 → the cost model pins the cost at breakeven and
    no position clears), so a fabricated zero-size fill is never emitted.
    """
    cm = cfg.cost_model
    if spike_direction == UP:
        faded_side = "NO"
        entry_basis = 1.0 - confirm_price
        exit_basis = 1.0 - exit_price
    else:
        faded_side = "YES"
        entry_basis = confirm_price
        exit_basis = exit_price

    # A basis at or outside (0, 1) has no tradeable two-sided price — skip rather than
    # invent a fill. (Ticks are already range-validated in [0,1] by clean_ticks, so this
    # only trips at the exact 0/1 boundary.)
    if not (0.0 < entry_basis < 1.0):
        return None

    entry_cost = cm.effective_buy_price(entry_basis)
    if not (0.0 < entry_cost < 1.0):
        # At the near-certain boundary the buy cost pins to 1.0 (breakeven) — no position
        # can profit, so there is nothing to trade. Honest skip, not a zero-size phantom.
        return None
    contracts = cfg.budget_per_trade_usd / entry_cost
    if contracts <= 0.0:
        return None
    exit_proceeds = cm.effective_sell_price(exit_basis)
    deployed = contracts * entry_cost
    pnl = contracts * (exit_proceeds - entry_cost)
    return FadeTrade(
        market_id=market_id,
        category=category,
        spike_direction=spike_direction,
        faded_side=faded_side,
        confirm_time=confirm_time,
        exit_time=exit_time,
        entry_basis=entry_basis,
        exit_basis=exit_basis,
        entry_cost=entry_cost,
        exit_proceeds=exit_proceeds,
        contracts=contracts,
        budget_usd=deployed,
        pnl_usd=pnl,
        is_win=pnl > 0.0,
        reversal_fraction=reversal_fraction,
        spike_magnitude=spike_magnitude,
    )


def _to_backtest_trades(trades: Sequence[FadeTrade]) -> List[BacktestTrade]:
    """Adapt ``FadeTrade``s into ``walk_forward.BacktestTrade`` records so the SAME F10
    ``analyze_regime_slices`` concentration/fragility check that gates every real corpus
    applies here unchanged — no bespoke concentration logic to drift out of sync.

    The mapping is faithful: ``decision_time``=confirm instant, ``resolution_time``=exit
    instant (so the horizon-band slice is the real hold), ``entry_price``=the faded side's
    entry basis (so the confidence-band slice reflects the price actually bought),
    ``budget_usd``/``pnl_usd``/``is_win``/``category`` carried through verbatim.
    """
    out: List[BacktestTrade] = []
    for t in trades:
        out.append(
            BacktestTrade(
                market_id=t.market_id,
                decision_time=_utc(t.confirm_time),
                resolution_time=_utc(t.exit_time),
                side=t.faded_side,
                entry_price=t.entry_basis,
                effective_cost=t.entry_cost,
                contracts=t.contracts,
                budget_usd=t.budget_usd,
                # payout is not a $1 settlement here (we exit at a mark, not resolution);
                # store gross exit value so payout - budget == pnl stays self-consistent.
                payout_usd=t.budget_usd + t.pnl_usd,
                pnl_usd=t.pnl_usd,
                is_win=t.is_win,
                category=t.category,
            )
        )
    return out


def _top_pnl_share(slices: Sequence[SlicePnL]) -> Optional[float]:
    """Largest single-bucket share of positive net PnL across ``slices`` (None if no edge)."""
    shares = [s.pnl_share for s in slices if s.pnl_share is not None]
    return max(shares) if shares else None


def _stratum_bounds(
    edges: Sequence[float],
) -> List[tuple[str, float, Optional[float]]]:
    """Turn ascending interior edges into (label, lo, hi) bands: [0,e0), [e0,e1), …, [e_last, ∞)."""
    bounds: List[tuple[str, float, Optional[float]]] = []
    lo = 0.0
    for e in edges:
        bounds.append((f"{lo:.2f}-{e:.2f}", lo, e))
        lo = e
    bounds.append((f">={lo:.2f}", lo, None))
    return bounds


def stratify_by_magnitude(
    trades: Sequence[FadeTrade],
    edges: Sequence[float] = DEFAULT_MAGNITUDE_STRATUM_EDGES,
) -> tuple[MagnitudeStratum, ...]:
    """Break realized fade trades into spike-SIZE bands (by ``|peak - baseline|`` magnitude).

    Pure + deterministic: bands are fixed by ``edges``, membership by magnitude alone. Reports,
    per band, the trade count, cost-net PnL, hit-rate, mean signed reversal fraction, and mean
    magnitude — the visibility that makes the Run 21 large-spike-persistence caution auditable
    (does the reversion hold across sizes, or only for small spikes?). Empty bands report ``None``
    for the means (never a fabricated 0). A band assigns membership left-inclusive/right-exclusive,
    with an open-ended top band, so every magnitude lands in exactly one band.

    This is a REPORT only — the size-robustness GATE does not consult these bands (it is rank-based,
    see ``_size_robustness``), so the ``edges`` here cannot mis-gate. ``edges`` are still validated
    (strictly increasing, in (0, 1)) so a direct caller gets a loud error, not silent dead bands."""
    _validate_magnitude_edges(edges)
    bounds = _stratum_bounds(list(edges))
    buckets: List[List[FadeTrade]] = [[] for _ in bounds]
    for t in trades:
        # Prices are tick-discrete, so a magnitude is a genuine multiple of the tick; round for
        # BAND ASSIGNMENT ONLY (never PnL) so float subtraction noise (e.g. 0.70-0.55=0.14999997)
        # can't scatter an exactly-on-edge cluster across two bands. Membership is
        # left-inclusive / right-exclusive with an open-ended top band.
        m = round(t.spike_magnitude, 6)
        placed = False
        for i, (_, lo, hi) in enumerate(bounds):
            if m >= lo and (hi is None or m < hi):
                buckets[i].append(t)
                placed = True
                break
        if not placed:  # pragma: no cover - open-ended top band always catches
            buckets[-1].append(t)
    out: List[MagnitudeStratum] = []
    for (label, lo, hi), bucket in zip(bounds, buckets):
        n = len(bucket)
        if n:
            total = round(sum(t.pnl_usd for t in bucket), 6)
            hit = round(sum(1 for t in bucket if t.is_win) / n, 6)
            mean_rev = round(sum(t.reversal_fraction for t in bucket) / n, 6)
            mean_mag = round(sum(t.spike_magnitude for t in bucket) / n, 6)
        else:
            total, hit, mean_rev, mean_mag = 0.0, None, None, None
        out.append(
            MagnitudeStratum(
                label=label,
                lo=lo,
                hi=hi,
                n_trades=n,
                total_pnl_usd=total,
                hit_rate=hit,
                mean_reversal_fraction=mean_rev,
                mean_magnitude=mean_mag,
            )
        )
    return tuple(out)


def _size_robustness(
    trades: Sequence[FadeTrade], *, seed: int, n_bootstrap: int
) -> tuple[List[str], str]:
    """Data-driven size-robustness gate for the Run 21 N=1 caution — *the biggest spikes may
    PERSIST, not revert*, so a positive AGGREGATE can be a small-spike artifact.

    Returns ``(fragile_reasons, status)``. ``fragile_reasons`` (fed into the F10 gate) is non-empty
    ONLY when the LARGEST spikes genuinely fail; ``status`` is an always-set machine-readable note.

    CONFIG-INDEPENDENT BY DESIGN (closing the edges loophole an auditor proved): the cohort of
    "largest spikes" is chosen by RANK on the realized ``spike_magnitude`` — the top
    ``LARGE_SPIKE_COHORT_FRACTION`` of trades by |move| — NOT by the caller's report bands, so no
    ``magnitude_stratum_edges`` choice can collapse the check away. Rank-based also means the cohort
    always holds ~a third of the sample, so it never goes sparse in the tail (it has real power at
    the N>=100 edge floor).

    SIGNIFICANCE-AWARE, not a bare sign test: the largest-spike cohort is judged by the SAME
    bootstrap-significance test the aggregate is (F11). It is flagged ONLY when its cost-net PnL is
    ``significant_negative`` (CI excludes 0 on the negative side) — a cohort that is negative only by
    sampling variance is NOT flagged.

    ABSTAINS WITH DISCLOSURE (never a silent pass) when size-robustness is structurally
    unassessable: (a) no real magnitude dispersion (span < ``MIN_MAGNITUDE_DISPERSION`` — one spike
    size), or (b) the largest-spike cohort has < ``MIN_STRATUM_TRADES_FOR_FRAGILITY`` trades. In both
    cases ``status`` says ``UNASSESSED`` so a reader knows the largest-spike regime was NOT cleared."""
    if not trades:
        return [], "UNASSESSED: no trades"
    mags = [t.spike_magnitude for t in trades]
    if max(mags) - min(mags) < MIN_MAGNITUDE_DISPERSION:
        return [], (
            f"UNASSESSED: no spike-size dispersion (|move| span "
            f"{max(mags) - min(mags):.4f} < {MIN_MAGNITUDE_DISPERSION}) — one spike size only"
        )
    # Largest-spike cohort by RANK (ties broken by market_id for determinism).
    ordered = sorted(trades, key=lambda t: (t.spike_magnitude, t.market_id))
    k = max(1, round(len(ordered) * LARGE_SPIKE_COHORT_FRACTION))
    cohort = ordered[-k:]
    if len(cohort) < MIN_STRATUM_TRADES_FOR_FRAGILITY:
        return [], (
            f"UNASSESSED: largest-spike cohort N={len(cohort)} < "
            f"{MIN_STRATUM_TRADES_FOR_FRAGILITY} (too few big spikes to judge)"
        )
    cohort_lo = min(t.spike_magnitude for t in cohort)
    sig = bootstrap_oos_significance(
        [t.pnl_usd for t in cohort],
        [t.is_win for t in cohort],
        min_trades=MIN_STRATUM_TRADES_FOR_FRAGILITY,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    if sig.verdict == "significant_negative":
        reason = (
            f"size-robustness: the LARGEST-spike cohort (top {k} by |move|, magnitude "
            f">= {cohort_lo:.3f}, N={len(cohort)}) fade is SIGNIFICANTLY NEGATIVE "
            f"(net ${sig.total_pnl_usd:,.2f}, 95% CI [{sig.total_ci_low}, {sig.total_ci_high}]) — "
            f"the reversion does NOT hold for the biggest spikes (Run 21 caution)"
        )
        return [reason], "FRAGILE: largest-spike cohort fade is significantly negative"
    return [], (
        f"assessed: largest-spike cohort (N={len(cohort)}, magnitude >= {cohort_lo:.3f}) "
        f"not significantly negative ({sig.verdict})"
    )


def _fade_f10_ok(
    regime: RegimeSliceReport,
    *,
    categories_known: bool,
    exclude_horizon: bool,
    size_fragile: Sequence[str] = (),
) -> tuple[bool, List[str]]:
    """F10 fragility for a fade-the-spike run, optionally excluding the horizon dimension.

    Fade-the-spike at the default horizon (≤ 1 day) is a SINGLE short-horizon strategy —
    every trade exits inside the reversal horizon, so the horizon-band slice is structurally
    single-valued and carries NO information about robustness. Judging it "fragile" for
    100%-in-one-horizon-bucket is a false positive for this strategy class — exactly the
    reasoning ``regime_slice`` itself already uses to EXCLUDE category-slicing when no
    category labels are supplied. So horizon is excluded ONLY when ``exclude_horizon`` (the
    caller passes True only when the configured horizon keeps all holds in one bucket); if
    the horizon is swept ABOVE one day the holds genuinely spread across buckets and the
    horizon check RE-ENGAGES (it is informative again). Every other genuinely-informative
    axis is always kept and load-bearing: SINGLE-MARKET concentration (the Run 21 caution —
    the primary failure mode), confidence-band (single-bucket AND the extreme-two-bucket
    combined check), time-window, and category (when labeled). This does NOT weaken the
    gate; it removes one axis only while it is structurally non-informative.

    Returns ``(ok, reasons)`` where ``ok`` is True only when the edge is broad on every
    informative axis (and there IS a positive edge to assess).
    """
    reasons: List[str] = []
    if not regime.has_positive_edge:
        # No positive aggregate to assess — not a validated edge, but not "fragile" either;
        # the F11 / sufficient-N gates already reject a non-positive result.
        return False, ["aggregate net PnL <= 0: no positive edge to assess"]

    # Single-market — the load-bearing concentration check for this strategy.
    if (
        regime.top_market_pnl_share is not None
        and regime.top_market_pnl_share > TOP_MARKET_PNL_CONCENTRATION
    ):
        reasons.append(
            f"single-market: {regime.top_market_pnl_share:.0%} of net PnL from ONE market "
            f"> {TOP_MARKET_PNL_CONCENTRATION:.0%}"
        )
    # Confidence-band + time-window (informative for a single-horizon strategy).
    conf_share = _top_pnl_share(regime.by_confidence)
    if conf_share is not None and conf_share > CONFIDENCE_PNL_CONCENTRATION:
        reasons.append(f"confidence-band: {conf_share:.0%} of net PnL in one band > {CONFIDENCE_PNL_CONCENTRATION:.0%}")
    # Extreme-confidence: the two near-certain entry buckets COMBINED (a split across both
    # extremes each single-bucket check can miss). Retained from regime_slice (tightening-only).
    extreme_pnl = sum(
        s.net_pnl_usd for s in regime.by_confidence if s.label in _EXTREME_CONF_LABELS
    )
    extreme_share = (extreme_pnl / regime.total_pnl_usd) if regime.total_pnl_usd > 0 else 0.0
    if extreme_share > EXTREME_CONFIDENCE_PNL_CONCENTRATION:
        reasons.append(
            f"confidence-extremes: {extreme_share:.0%} of net PnL in the near-certain "
            f"bands ({'/'.join(_EXTREME_CONF_LABELS)}) > {EXTREME_CONFIDENCE_PNL_CONCENTRATION:.0%}"
        )
    time_share = _top_pnl_share(regime.by_time)
    if time_share is not None and time_share > TIME_PNL_CONCENTRATION:
        reasons.append(f"time-window: {time_share:.0%} of net PnL in one week > {TIME_PNL_CONCENTRATION:.0%}")
    # Horizon — only when it is informative (holds actually spread across buckets).
    if not exclude_horizon:
        horizon_share = _top_pnl_share(regime.by_horizon)
        if horizon_share is not None and horizon_share > HORIZON_PNL_CONCENTRATION:
            reasons.append(f"horizon: {horizon_share:.0%} of net PnL in one band > {HORIZON_PNL_CONCENTRATION:.0%}")
    # Category — only when real labels were supplied (else it is the single-bucket no-info case).
    if categories_known:
        cat_share = _top_pnl_share(regime.by_category)
        if cat_share is not None and cat_share > CATEGORY_PNL_CONCENTRATION:
            reasons.append(f"category: {cat_share:.0%} of net PnL in one category > {CATEGORY_PNL_CONCENTRATION:.0%}")
    # Size/salience robustness — the Run 21 caution as a load-bearing gate axis: a reversion edge
    # that vanishes (or reverses) for the LARGEST spikes is size-fragile. Config-independent
    # (rank-based) + significance-aware; computed by _size_robustness and passed in as reasons.
    reasons.extend(size_fragile)

    return (not reasons), reasons


def backtest_fade_the_spike(
    ticks_by_market: Mapping[str, Sequence[Mapping]],
    *,
    config: Optional[FadeSpikeConfig] = None,
    category_by_market: Optional[Mapping[str, str]] = None,
) -> SpikeReversalResult:
    """Run the fade-the-spike backtest over a corpus of per-market intraday tick series.

    ``ticks_by_market`` maps ``market_id`` → its raw ``[{"t": unix_s, "p": 0..1}, ...]``
    tick list (the exact shape ``PolymarketHistoryFetcher.fetch_price_history`` returns).
    For each market (iterated in SORTED id order for determinism) it detects causally-
    confirmed spikes, fades the first ``max_trades_per_market`` of them (equal-weight,
    concentration-capped), labels each reversal STRICTLY forward, and books the cost-net
    PnL. It then runs F11 significance + F10 fragility on the realized trades and returns
    an honest ``is_validated_edge`` verdict.

    Leakage-safe by construction (see module docstring). Deterministic: same ticks + same
    config ⇒ identical trades, PnL, and verdict.
    """
    cfg = config or FadeSpikeConfig()
    cat_map = dict(category_by_market or {})

    trades: List[FadeTrade] = []
    n_scanned = 0
    n_spikes = 0
    n_unlabelable = 0

    for market_id in sorted(ticks_by_market.keys()):
        ticks = ticks_by_market[market_id]
        n_scanned += 1
        category = cat_map.get(market_id)
        spikes = detect_spikes(
            ticks, threshold=cfg.threshold, window_seconds=cfg.window_seconds
        )
        n_spikes += len(spikes)
        taken = 0
        for spike in spikes:
            if taken >= cfg.max_trades_per_market:
                break
            outcome = label_reversal(ticks, spike, horizon_seconds=cfg.horizon_seconds)
            if outcome is None:
                n_unlabelable += 1
                continue
            trade = _fade_trade(
                market_id=market_id,
                category=category,
                spike_direction=spike.direction,
                confirm_price=spike.confirm_price,
                exit_price=outcome.future_price,
                confirm_time=spike.confirm_time,
                exit_time=outcome.future_time,
                reversal_fraction=outcome.reversal_fraction,
                spike_magnitude=spike.magnitude,
                cfg=cfg,
            )
            if trade is None:
                continue
            trades.append(trade)
            taken += 1

    # Deterministic order for the realized vector + downstream gates.
    trades.sort(key=lambda t: (t.confirm_time, t.market_id))
    n = len(trades)
    total_pnl = round(sum(t.pnl_usd for t in trades), 6)
    hit_rate = (sum(1 for t in trades if t.is_win) / n) if n else None
    n_markets_traded = len({t.market_id for t in trades})

    # Salience breakdown (Run 21 caution): how the fade behaves across spike-SIZE bands (report).
    strata = stratify_by_magnitude(trades, cfg.magnitude_stratum_edges)
    # Size-robustness GATE (config-independent, rank-based, significance-aware): does the fade
    # hold for the LARGEST spikes, or is a positive aggregate a small-spike artifact? Always
    # produces a machine-readable status, even when it abstains.
    size_fragile, size_status = _size_robustness(
        trades, seed=cfg.bootstrap_seed, n_bootstrap=cfg.bootstrap_n
    )

    # F11 — is the realized total distinguishable from zero? (seeded ⇒ reproducible)
    significance = bootstrap_oos_significance(
        [t.pnl_usd for t in trades],
        [t.is_win for t in trades],
        min_trades=cfg.min_trades_for_edge,
        n_bootstrap=cfg.bootstrap_n,
        seed=cfg.bootstrap_seed,
    )

    # F10 — is a positive edge broad, or propped up by one market/bucket? Category labels
    # are passed only when supplied (else the check honestly skips category-slicing).
    regime: Optional[RegimeSliceReport] = None
    if n:
        bt = _to_backtest_trades(trades)
        cat_by_id = (
            {t.market_id: cat_map[t.market_id] for t in trades if t.market_id in cat_map}
            if category_by_market is not None
            else None
        )
        regime = analyze_regime_slices(bt, category_by_market_id=cat_by_id)

    # Honest AND-of-gates verdict — never the point estimate alone. The four criteria match
    # the Quality Auditor's validated-edge bar: sufficient N, F11 significant_positive, F10
    # non-fragile, and a hit-rate meaningfully above 50%.
    enough_n = n >= cfg.min_trades_for_edge
    f11_ok = significance.is_significant_edge
    hit_rate_ok = hit_rate is not None and hit_rate > MIN_HIT_RATE_FOR_EDGE
    f10_ok = False
    f10_reasons: List[str] = []
    if regime is not None:
        # Exclude the horizon axis ONLY while it is structurally single-valued (holds all
        # land in the <=1d bucket, i.e. the horizon is <= one day). A swept-up horizon
        # re-engages the check (holds spread across buckets → it becomes informative).
        exclude_horizon = cfg.horizon_seconds <= DEFAULT_REVERSAL_HORIZON_SECONDS
        f10_ok, f10_reasons = _fade_f10_ok(
            regime,
            categories_known=category_by_market is not None,
            exclude_horizon=exclude_horizon,
            size_fragile=size_fragile,
        )
    is_validated = bool(enough_n and f11_ok and f10_ok and hit_rate_ok)

    if is_validated:
        verdict = (
            f"VALIDATED-CANDIDATE: fade-the-spike net +${total_pnl:,.2f} over {n} trades "
            f"({n_markets_traded} markets); F11 significant_positive "
            f"(total CI [{significance.total_ci_low}, {significance.total_ci_high}]); "
            f"F10 non-fragile; size-robustness [{size_status}]. Advance to a forward paper "
            f"window before any live claim."
        )
    else:
        reasons = []
        if not enough_n:
            reasons.append(f"N={n} < pre-registered floor {cfg.min_trades_for_edge}")
        if not f11_ok:
            reasons.append(f"F11 verdict={significance.verdict} (not significant_positive)")
        if n and not hit_rate_ok:
            reasons.append(f"hit-rate {hit_rate} <= {MIN_HIT_RATE_FOR_EDGE:.0%} floor")
        if n and not f10_ok and regime is not None:
            reasons.append("F10 fragile (horizon dim excluded — single-horizon strategy): " + "; ".join(f10_reasons))
        elif not n:
            reasons.append("no trades produced (no labelable spikes in corpus)")
        verdict = (
            f"EDGE-NOT-PROVEN: fade-the-spike net ${total_pnl:,.2f} over {n} trades — "
            + "; ".join(reasons)
            + f". [size-robustness: {size_status}]"
            + ". Honest null / not-yet — NOT go-live evidence."
        )

    return SpikeReversalResult(
        trades=tuple(trades),
        n_trades=n,
        n_markets_traded=n_markets_traded,
        total_pnl_usd=total_pnl,
        hit_rate=round(hit_rate, 6) if hit_rate is not None else None,
        n_markets_scanned=n_scanned,
        n_spikes_detected=n_spikes,
        n_spikes_unlabelable=n_unlabelable,
        significance=significance,
        regime=regime,
        strata=strata,
        size_robustness=size_status,
        is_validated_edge=is_validated,
        verdict=verdict,
    )


__all__ = [
    "DEFAULT_MIN_TRADES_FOR_EDGE",
    "DEFAULT_BUDGET_PER_TRADE_USD",
    "DEFAULT_MAX_TRADES_PER_MARKET",
    "DEFAULT_MAGNITUDE_STRATUM_EDGES",
    "MIN_HIT_RATE_FOR_EDGE",
    "MIN_STRATUM_TRADES_FOR_FRAGILITY",
    "FadeSpikeConfig",
    "FadeTrade",
    "MagnitudeStratum",
    "SpikeReversalResult",
    "backtest_fade_the_spike",
    "stratify_by_magnitude",
]
