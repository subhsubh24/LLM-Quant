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
DEFAULT_MAX_TRADES_PER_MARKET: int = 1


@dataclass(frozen=True)
class FadeSpikeConfig:
    """Parameters for the fade-the-spike backtest. All swept, none tuned-in secret."""

    threshold: float = DEFAULT_SPIKE_THRESHOLD
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    horizon_seconds: int = DEFAULT_REVERSAL_HORIZON_SECONDS
    budget_per_trade_usd: float = DEFAULT_BUDGET_PER_TRADE_USD
    max_trades_per_market: int = DEFAULT_MAX_TRADES_PER_MARKET
    min_trades_for_edge: int = DEFAULT_MIN_TRADES_FOR_EDGE
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


def _fade_f10_ok(regime: RegimeSliceReport, categories_known: bool) -> tuple[bool, List[str]]:
    """F10 fragility for a fade-the-spike run, EXCLUDING the horizon dimension.

    Fade-the-spike is by design a SINGLE short-horizon strategy — every trade exits inside
    the reversal horizon (≤ 1 day here), so the horizon-band slice is structurally
    single-valued and carries NO information about robustness. Judging it "fragile" for
    100%-in-one-horizon-bucket is a false positive for this strategy class — exactly the
    reasoning ``regime_slice`` itself already uses to EXCLUDE category-slicing when no
    category labels are supplied. Every OTHER, genuinely-informative dimension is kept and
    load-bearing: SINGLE-MARKET concentration (the Run 21 caution — the primary failure
    mode), confidence-band, time-window, and category (when labeled). This does NOT weaken
    the gate; it removes one non-informative axis and keeps the ones that can actually
    reveal a propped-up edge.

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
    time_share = _top_pnl_share(regime.by_time)
    if time_share is not None and time_share > TIME_PNL_CONCENTRATION:
        reasons.append(f"time-window: {time_share:.0%} of net PnL in one week > {TIME_PNL_CONCENTRATION:.0%}")
    # Category — only when real labels were supplied (else it is the single-bucket no-info case).
    if categories_known:
        cat_share = _top_pnl_share(regime.by_category)
        if cat_share is not None and cat_share > CATEGORY_PNL_CONCENTRATION:
            reasons.append(f"category: {cat_share:.0%} of net PnL in one category > {CATEGORY_PNL_CONCENTRATION:.0%}")

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

    # Honest AND-of-gates verdict — never the point estimate alone.
    enough_n = n >= cfg.min_trades_for_edge
    f11_ok = significance.is_significant_edge
    f10_ok = False
    f10_reasons: List[str] = []
    if regime is not None:
        f10_ok, f10_reasons = _fade_f10_ok(regime, categories_known=category_by_market is not None)
    is_validated = bool(enough_n and f11_ok and f10_ok)

    if is_validated:
        verdict = (
            f"VALIDATED-CANDIDATE: fade-the-spike net +${total_pnl:,.2f} over {n} trades "
            f"({n_markets_traded} markets); F11 significant_positive "
            f"(total CI [{significance.total_ci_low}, {significance.total_ci_high}]); "
            f"F10 non-fragile. Advance to a forward paper window before any live claim."
        )
    else:
        reasons = []
        if not enough_n:
            reasons.append(f"N={n} < pre-registered floor {cfg.min_trades_for_edge}")
        if not f11_ok:
            reasons.append(f"F11 verdict={significance.verdict} (not significant_positive)")
        if n and not f10_ok and regime is not None:
            reasons.append("F10 fragile (horizon dim excluded — single-horizon strategy): " + "; ".join(f10_reasons))
        elif not n:
            reasons.append("no trades produced (no labelable spikes in corpus)")
        verdict = (
            f"EDGE-NOT-PROVEN: fade-the-spike net ${total_pnl:,.2f} over {n} trades — "
            + "; ".join(reasons)
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
        is_validated_edge=is_validated,
        verdict=verdict,
    )


__all__ = [
    "DEFAULT_MIN_TRADES_FOR_EDGE",
    "DEFAULT_BUDGET_PER_TRADE_USD",
    "DEFAULT_MAX_TRADES_PER_MARKET",
    "FadeSpikeConfig",
    "FadeTrade",
    "SpikeReversalResult",
    "backtest_fade_the_spike",
]
