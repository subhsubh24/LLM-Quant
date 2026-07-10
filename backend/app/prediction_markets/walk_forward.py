"""walk_forward.py — leakage-free, deterministic walk-forward backtest for
prediction markets (ROADMAP C1 + C3).

WHY THIS EXISTS
The binding constraint for go-live is a *validated out-of-sample edge*. That requires
a backtest that is (a) **leakage-free** — the trade decision can never see the
resolution outcome or any post-decision data; (b) **walk-forward / out-of-sample** —
the model is only ever calibrated on markets that resolved *before* the test window;
and (c) **deterministic/reproducible** — the same data + seed produce a bit-identical
weekly-PnL series, so a "good backtest" can be re-run and audited rather than taken on
faith. This module is the ENGINE for that. It does NOT invent an edge: fed
zero-information data it reports ~zero PnL; fed a real alpha it measures what survives
realistic costs.

HONEST SCOPE
This is the engine, not a validated result. There is no real historical
resolved-market dataset committed to the repo yet, so running this on synthetic data
proves the engine is *honest* (recovers a known edge, reports ~0 on no edge, never
leaks, reproduces) — it does NOT by itself satisfy the "validated OOS edge >= floor"
DoD box. That box stays unchecked until this runs on real resolved Polymarket history.

LEAKAGE GUARD (structural, not by convention)
The per-market trade decision is handed a frozen ``MarketView`` that DOES NOT contain
the ``outcome``. Only the engine retains the ``outcome`` and uses it solely to *settle*
a position at ``resolution_time``. A strategy literally cannot read the future because
the field is not in the object it receives. The training set passed to the strategy is
filtered to markets that resolved strictly before the test window opens.

COSTS
All fills are priced through ``prediction_markets.cost_model`` — the single source of
truth that the live/paper executor also uses — so backtest EV and realized PnL subtract
the SAME fees + slippage (a divergence would otherwise masquerade as overfit).
"""

from __future__ import annotations

import hashlib
import heapq
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Sequence

from .cost_model import DEFAULT_COST_MODEL, CostModel


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HistoricalMarket:
    """One resolved binary prediction market, as seen in history.

    ``market_price`` is the crowd's P[YES] observable at ``decision_time`` (the naive
    baseline). ``model_prob`` is the strategy's estimated P[YES] at ``decision_time``,
    computed from information available *up to* ``decision_time`` only (the caller is
    responsible for that — typically by deriving it inside ``strategy_fn``; this field
    is a convenience for the default strategy). ``outcome`` (1 = YES resolved true,
    0 = NO) is known ONLY at ``resolution_time`` and is never exposed to the decision.
    """

    market_id: str
    decision_time: datetime
    resolution_time: datetime
    market_price: float          # crowd P[YES] at decision_time, in [0, 1]
    model_prob: float            # strategy P[YES] at decision_time, in [0, 1]
    outcome: int                 # 1 if YES resolved true, else 0
    # OPTIONAL order-book depth signal (in contracts) observable at decision_time. When
    # present it feeds the SIMPLIFIED market-impact model in cost_model so a large order
    # in a THIN market pays realistic size/depth slippage. Defaulted to None so every
    # existing positional/keyword construction (tests + fetcher) is unchanged, and a None
    # market is priced at the FLAT rate exactly as before (zero behavior change).
    liquidity: Optional[float] = None
    # OPTIONAL coarse correlation category (Crypto / Politics / Sports / …, via
    # market_category.derive_market_category), carried from the resolved-history fetcher so
    # the F10 regime-slice report can assess CATEGORY concentration on real OOS trades (an
    # aggregate edge concentrated in one category is NOT robust). It is pure METADATA — it
    # never enters the decision (leakage-neutral) NOR the PnL, so it is deliberately EXCLUDED
    # from _seed_hash (reproducibility invariant: category=None vs a value → identical hash).
    # Defaulted to None so every existing construction is byte-unchanged.
    category: Optional[str] = None
    # RESEARCH-ONLY provenance flag. TRUE marks a record sourced from a PLAY-MONEY venue
    # (e.g. Manifold, A8) — usable for METHOD validation only, and which must NEVER count
    # toward the real-money profit floor / go-live-eligibility (a play-money edge does not
    # transfer to real money). It is a STRUCTURAL guardrail: the real-money OOS floor lane
    # (scripts/validate_real_oos.evaluate) REFUSES any record with this set, so a play-money
    # corpus can never inflate the floor even by an accidental copy-paste — replacing the
    # prior convention-only (module-name + comment) marker (named A8 follow-up). Pure
    # METADATA: it never enters the decision (leakage-neutral) NOR the PnL, so — like
    # `category` — it is EXCLUDED from _seed_hash (reproducibility invariant: the flag never
    # changes a hash or a number). Defaulted to False so every existing construction is
    # byte-unchanged and real-money records are unaffected.
    research_only: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.market_price <= 1.0):
            raise ValueError(f"market_price out of [0,1]: {self.market_price}")
        if not (0.0 <= self.model_prob <= 1.0):
            raise ValueError(f"model_prob out of [0,1]: {self.model_prob}")
        if self.outcome not in (0, 1):
            raise ValueError(f"outcome must be 0/1: {self.outcome}")
        if self.liquidity is not None and not (self.liquidity > 0.0):
            # Depth must be a positive number of contracts when supplied; a non-positive
            # depth is a data error (the impact model divides by it).
            raise ValueError(f"liquidity (depth) must be > 0 when set: {self.liquidity}")
        if self.resolution_time <= self.decision_time:
            # Strictly positive holding period. A market that "resolves" the instant it
            # is decided is not a real tradeable opportunity and would let capital be
            # recycled within a single timestamp (an unrealistic free lunch).
            raise ValueError(
                "resolution_time must be strictly after decision_time (positive duration)"
            )


@dataclass(frozen=True)
class MarketView:
    """The leakage-safe view a strategy is allowed to see at decision time.

    Deliberately EXCLUDES ``outcome`` and ``resolution_time`` details beyond what is
    knowable at the decision instant. A strategy cannot look ahead because the future
    is simply not present in this object.
    """

    market_id: str
    decision_time: datetime
    market_price: float
    model_prob: float


@dataclass(frozen=True)
class TradeDecision:
    """A strategy's decision for a single market. ``trade=False`` means skip."""

    trade: bool
    side: str = "YES"            # "YES" or "NO" — which side to buy
    kelly_fraction: float = 0.0  # fraction of bankroll to deploy (pre-cap)


@dataclass(frozen=True)
class BacktestTrade:
    """A filled paper trade and its realized settlement."""

    market_id: str
    decision_time: datetime
    resolution_time: datetime
    side: str
    entry_price: float           # raw crowd price for the bought side
    effective_cost: float        # all-in per-contract cost (costs included)
    contracts: float
    budget_usd: float            # cash actually deployed
    payout_usd: float            # gross payout at resolution
    pnl_usd: float               # payout - budget
    is_win: bool
    # Coarse correlation category carried from the traded market (None when unlabeled), so
    # per-category realized-PnL concentration (F10) can be attributed. Metadata only.
    category: Optional[str] = None


@dataclass(frozen=True)
class WalkForwardResult:
    trades: list[BacktestTrade]
    weekly_pnl: list[tuple[date, float]]   # (iso-monday, realized PnL that week)
    total_pnl_usd: float
    n_trades: int
    final_bankroll: float
    seed: int
    seed_hash: str
    n_windows: int


# A strategy receives (training markets resolved before the test window, the view of a
# candidate market) and returns a TradeDecision. The training set lets it calibrate
# WITHOUT look-ahead; the view lets it act WITHOUT seeing the outcome.
StrategyFn = Callable[[Sequence[HistoricalMarket], MarketView], TradeDecision]


# ---------------------------------------------------------------------------
# Default strategy: net-edge Kelly on the model's probability
# ---------------------------------------------------------------------------
def make_net_edge_strategy(
    cost_model: CostModel = DEFAULT_COST_MODEL,
    min_edge: float = 0.02,
    kelly_fraction: float = 0.25,
) -> StrategyFn:
    """A deterministic strategy that buys the side whose net-of-cost edge clears
    ``min_edge``, sized at fractional Kelly on the net edge.

    It uses ``view.model_prob`` as P[YES] and ``view.market_price`` as the cost basis.
    It does NOT consult the training set (it trusts the provided model_prob); a real
    alpha would recalibrate model_prob from ``training`` here. Kept simple + honest so
    the engine's correctness is what the tests assert.
    """

    def strategy(training: Sequence[HistoricalMarket], view: MarketView) -> TradeDecision:
        p_yes = view.model_prob
        # Net edge on each side, costs included (price basis = the side's raw price).
        yes_edge = cost_model.net_edge(p_yes, view.market_price)
        no_price = 1.0 - view.market_price
        no_edge = cost_model.net_edge(1.0 - p_yes, no_price)

        side, edge, basis = ("YES", yes_edge, view.market_price)
        if no_edge > yes_edge:
            side, edge, basis = ("NO", no_edge, no_price)

        if edge < min_edge:
            return TradeDecision(trade=False)

        # Fractional Kelly on net odds b = (1 - c_eff)/c_eff with win prob q.
        c_eff = cost_model.effective_buy_price(basis)
        if c_eff <= 0.0 or c_eff >= 1.0:
            return TradeDecision(trade=False)
        b = (1.0 - c_eff) / c_eff
        q = p_yes if side == "YES" else (1.0 - p_yes)
        full_kelly = (b * q - (1.0 - q)) / b
        if full_kelly <= 0.0:
            return TradeDecision(trade=False)
        return TradeDecision(
            trade=True, side=side, kelly_fraction=min(full_kelly * kelly_fraction, 1.0)
        )

    return strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _iso_monday(d: datetime) -> date:
    """The Monday (ISO week start) of ``d``'s week, as a date."""
    day = d.date()
    return day - timedelta(days=day.weekday())


def _to_view(m: HistoricalMarket) -> MarketView:
    return MarketView(
        market_id=m.market_id,
        decision_time=m.decision_time,
        market_price=m.market_price,
        model_prob=m.model_prob,
    )


def _settle(
    m: HistoricalMarket, decision: TradeDecision, budget_usd: float, cost_model: CostModel
) -> Optional[BacktestTrade]:
    """Settle a decided trade against the (engine-only) outcome. Returns None if the
    decision was to skip or sizing collapsed to zero."""
    if not decision.trade or budget_usd <= 0.0:
        return None

    if decision.side == "YES":
        basis = m.market_price
        win = m.outcome == 1
    else:
        basis = 1.0 - m.market_price
        win = m.outcome == 0

    # COST BASIS — flat vs depth-aware. When the market carries a depth signal
    # (``m.liquidity``), price the fill through the SIMPLIFIED market-impact model so a
    # large order in a thin book pays realistic size/depth slippage. Otherwise use the
    # flat rate (UNCHANGED behavior for liquidity=None markets and all existing tests).
    #
    # NO-DOUBLE-COUNT / cash==budget invariant. The impact-inclusive per-contract cost
    # depends on the order size, which is itself what we are solving for (budget / cost)
    # — a circular dependency. We break it WITHOUT a fixed-point solve and WITHOUT
    # charging impact twice, in a fixed, documented order of operations:
    #   1. size a *representative* order at the FLAT price (size0 = budget / c_flat);
    #   2. evaluate the impact-inclusive per-contract cost ONCE at that representative
    #      size (c_eff = effective_buy_price_with_impact(basis, size0, depth));
    #   3. size the FINAL contracts from the budget at that single c_eff
    #      (contracts = budget / c_eff), and deploy exactly contracts * c_eff.
    # Because the final cash is budget/c_eff * c_eff, deployed == budget EXACTLY — the
    # impact is reflected in the *number of contracts* (a thin book buys fewer contracts
    # per dollar and therefore earns a smaller payout), not added as a second cash charge
    # on top of the budget. Impact is computed once at a representative size, so it is
    # neither double-counted nor self-referential.
    if m.liquidity is None:
        c_eff = cost_model.effective_buy_price(basis)
        contracts = cost_model.contracts_for_budget(budget_usd, basis)
    else:
        size0 = cost_model.contracts_for_budget(budget_usd, basis)
        c_eff = cost_model.effective_buy_price_with_impact(basis, size0, m.liquidity)
        contracts = budget_usd / c_eff if c_eff > 0.0 else 0.0
    if contracts <= 0.0:
        return None
    # Each contract pays $1 on a win, $0 on a loss. Cash deployed == budget (the
    # cost model converts budget -> contracts at the all-in cost, so no double-count).
    deployed = contracts * c_eff
    payout = contracts * (1.0 if win else 0.0)
    pnl = payout - deployed
    return BacktestTrade(
        market_id=m.market_id,
        decision_time=m.decision_time,
        resolution_time=m.resolution_time,
        side=decision.side,
        entry_price=basis,
        effective_cost=c_eff,
        contracts=contracts,
        budget_usd=deployed,
        payout_usd=payout,
        pnl_usd=pnl,
        is_win=win,
        category=m.category,
    )


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------
def walk_forward_backtest(
    markets: Sequence[HistoricalMarket],
    strategy_fn: Optional[StrategyFn] = None,
    *,
    initial_bankroll: float = 10_000.0,
    train_min_days: int = 28,
    test_window_days: int = 7,
    max_fraction_per_trade: float = 0.05,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    seed: int = 42,
) -> WalkForwardResult:
    """Run an expanding-window walk-forward backtest with realistic capital accounting.

    DECISIONS (leak-free, walk-forward): the timeline is sliced into consecutive
    ``test_window_days`` OOS windows starting ``train_min_days`` after the first
    decision. For each window, TRAIN = every market that *resolved strictly before* the
    window opens (no future leak); each candidate whose ``decision_time`` falls in the
    window is shown only its ``MarketView`` (no outcome) plus TRAIN, and the strategy
    decides.

    CAPITAL (event-driven, no over-deployment): opening a position TIES UP its cost
    basis until the market resolves — a real account cannot redeploy unsettled cash.
    The engine therefore simulates cash flow in chronological event order: at a
    position's ``decision_time`` it debits the deployed cash; at ``resolution_time`` it
    credits the payout. A position is sized at ``min(kelly_fraction,
    max_fraction_per_trade)`` of current EQUITY (free cash + committed cost basis) but
    is HARD-CAPPED at available free cash, so the bankroll can never go negative and a
    dense cluster of same-window candidates cannot deploy more than 100% of capital
    (the over-deployment bug an earlier batch-settled version had). Realized PnL is
    attributed to the ISO week of ``resolution_time``.

    Determinism: events are processed in a stable ``(time, market_id, seq)`` order;
    settlement is pure arithmetic; ``market_id`` is required unique. ``seed_hash``
    fingerprints the DATA + the numeric CONFIG (seed, bankroll, cost rates, window
    sizing). It deliberately does NOT fingerprint the ``strategy_fn`` callable (an
    arbitrary closure cannot be hashed reliably), so a hash match proves identical PnL
    only when compared across runs that used the SAME strategy. Given that, identical
    inputs ⇒ identical hash ⇒ identical PnL. A STOCHASTIC ``strategy_fn`` that draws from
    the global ``random`` / ``numpy.random`` streams is made reproducible because this
    function seeds BOTH from ``seed`` before running (below); the default strategy is
    deterministic, so the seeding is a no-op for it.
    """
    strategy = strategy_fn or make_net_edge_strategy(cost_model=cost_model)
    # Determinism (the seed_hash contract: same data + seed ⇒ identical PnL). The engine's
    # own accounting is pure arithmetic, but a STOCHASTIC strategy_fn may draw from the
    # global RNG — the documented way ``seed`` is "consumed". Previously nothing seeded the
    # RNG, so the docstring's "a stochastic strategy may consume seed" was FALSE: two runs
    # with the same seed diverged while the seed_hash still MATCHED (a silent reproducibility
    # violation). Seed both streams here so a stochastic strategy is genuinely reproducible.
    # numpy is best-effort (a numpy-free strategy needs no numpy seed; numpy is a CI dep).
    random.seed(seed)
    try:
        import numpy as _np

        _np.random.seed(seed % (2**32))
    except ImportError:  # numpy absent → nothing to seed (stdlib random already seeded)
        pass
    # market_id must be unique: it is the settlement/heap key and the hash sort key, so a
    # duplicate would crash the heap (comparing un-orderable trades) and make the config
    # fingerprint order-sensitive. A real resolved-market dataset that lists a market
    # twice is a data-quality error — fail loud rather than crash cryptically.
    ids = [m.market_id for m in markets]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate market_id(s) in dataset: {dupes}")
    cfg_hash = _seed_hash(
        markets, seed, initial_bankroll, cost_model, train_min_days,
        test_window_days, max_fraction_per_trade,
    )
    if not markets:
        return WalkForwardResult(
            trades=[], weekly_pnl=[], total_pnl_usd=0.0, n_trades=0,
            final_bankroll=initial_bankroll, seed=seed,
            seed_hash=cfg_hash, n_windows=0,
        )

    ordered = sorted(markets, key=lambda m: (m.decision_time, m.market_id))
    start = ordered[0].decision_time
    end = max(m.decision_time for m in ordered)

    # Build OOS window boundaries.
    window_starts: list[datetime] = []
    cursor = start + timedelta(days=train_min_days)
    while cursor <= end:
        window_starts.append(cursor)
        cursor += timedelta(days=test_window_days)

    # Phase 1 — decide trades window-by-window (leak-free). Collect intents in
    # chronological decision order; capital is NOT consulted here, only the signal.
    intents: list[tuple[HistoricalMarket, TradeDecision]] = []
    for w_start in window_starts:
        w_end = w_start + timedelta(days=test_window_days)
        train = [m for m in ordered if m.resolution_time < w_start]
        for m in (mm for mm in ordered if w_start <= mm.decision_time < w_end):
            decision = strategy(train, _to_view(m))
            if decision.trade:
                intents.append((m, decision))
    intents.sort(key=lambda im: (im[0].decision_time, im[0].market_id))

    # Phase 2 — event-driven cash simulation. Opens debit cash at decision_time;
    # resolutions credit payout at resolution_time. Never deploy beyond free cash.
    cash = initial_bankroll
    committed = 0.0                      # cost basis of still-open positions
    settled: list[BacktestTrade] = []
    # min-heap keyed (resolution_time, market_id, seq); seq is a monotonic tie-breaker so
    # the BacktestTrade payload is NEVER compared (it is not orderable).
    pending: list[tuple[datetime, str, int, BacktestTrade]] = []
    seq = 0

    def _drain_until(when: datetime) -> None:
        nonlocal cash, committed
        while pending and pending[0][0] <= when:
            _, _, _, tr = heapq.heappop(pending)
            cash += tr.payout_usd
            committed -= tr.budget_usd
            settled.append(tr)

    for m, decision in intents:
        # Realize every resolution that happened at/before this open. (Markets have a
        # strictly positive duration, so a position never resolves at the instant it
        # opens — no intra-instant capital recycling.)
        _drain_until(m.decision_time)
        equity = cash + committed
        frac = min(max(decision.kelly_fraction, 0.0), max_fraction_per_trade)
        budget = min(equity * frac, cash)     # HARD free-cash cap — no over-deployment
        if budget <= 0.0:
            continue
        trade = _settle(m, decision, budget, cost_model)
        if trade is None:
            continue
        cash -= trade.budget_usd
        committed += trade.budget_usd
        heapq.heappush(pending, (trade.resolution_time, trade.market_id, seq, trade))
        seq += 1

    # Drain any positions still open at the end of the timeline.
    while pending:
        _, _, _, tr = heapq.heappop(pending)
        cash += tr.payout_usd
        committed -= tr.budget_usd
        settled.append(tr)

    settled.sort(key=lambda t: (t.resolution_time, t.market_id))
    weekly = _weekly_pnl(settled)
    total = sum(t.pnl_usd for t in settled)
    return WalkForwardResult(
        trades=settled,
        weekly_pnl=weekly,
        total_pnl_usd=total,
        n_trades=len(settled),
        final_bankroll=cash,             # committed is 0 after draining → cash == equity
        seed=seed,
        seed_hash=cfg_hash,
        n_windows=len(window_starts),
    )


def _weekly_pnl(trades: Sequence[BacktestTrade]) -> list[tuple[date, float]]:
    buckets: dict[date, float] = {}
    for t in trades:
        wk = _iso_monday(t.resolution_time)
        buckets[wk] = buckets.get(wk, 0.0) + t.pnl_usd
    return sorted(buckets.items(), key=lambda kv: kv[0])


def _seed_hash(
    markets: Sequence[HistoricalMarket],
    seed: int,
    initial_bankroll: float,
    cost_model: CostModel,
    train_min_days: int,
    test_window_days: int,
    max_fraction_per_trade: float,
) -> str:
    """A stable fingerprint of the DATA + numeric CONFIG that affect PnL — the markets,
    the seed, the bankroll, the cost rates, and the window sizing. It does NOT cover the
    ``strategy_fn`` callable (an arbitrary closure cannot be hashed), so two runs with
    different strategies can share a hash — compare hashes only across same-strategy
    runs. ``market_id`` is required unique by the caller, so the ``(decision_time,
    market_id)`` sort key is a total order and the fingerprint is input-order-invariant."""
    payload = {
        "seed": seed,
        "initial_bankroll": round(initial_bankroll, 12),
        "slippage_rate": round(cost_model.slippage_rate, 12),
        "fee_rate": round(cost_model.fee_rate, 12),
        # impact_coeff drives effective_buy_price_with_impact, which changes PnL for any
        # liquidity-bearing market — so it MUST be in the fingerprint or two runs with
        # different impact but identical data/seed would share a hash yet diverge in PnL
        # (a reproducibility-invariant violation). Covered by test_seed_hash_covers_impact_coeff.
        "impact_coeff": round(cost_model.impact_coeff, 12),
        "train_min_days": train_min_days,
        "test_window_days": test_window_days,
        "max_fraction_per_trade": round(max_fraction_per_trade, 12),
        "markets": [
            # liquidity is included so determinism/fingerprint covers the depth signal
            # that now affects fill cost. Existing markets have liquidity=None → stored as
            # JSON null, a stable representation, so same-data runs keep consistent hashes
            # and the cost-rate-change hash test still holds. NOTE: m.category is
            # deliberately NOT fingerprinted — it is regime-slice metadata that never affects
            # a decision or PnL, so including it would needlessly break the pinned real-data
            # reproduction hash (8dc358439ffb5746). Same-data runs must hash identically
            # whether or not categories are labeled (test_walk_forward_category pins this).
            [m.market_id, m.decision_time.isoformat(), m.resolution_time.isoformat(),
             round(m.market_price, 12), round(m.model_prob, 12), m.outcome,
             None if m.liquidity is None else round(m.liquidity, 12)]
            for m in sorted(markets, key=lambda x: (x.decision_time, x.market_id))
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


__all__ = [
    "HistoricalMarket", "MarketView", "TradeDecision", "BacktestTrade",
    "WalkForwardResult", "StrategyFn", "make_net_edge_strategy",
    "walk_forward_backtest",
]
