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

from .cost_model import DEFAULT_COST_MODEL, POLYMARKET_FEE_RATES, CostModel

# When the per-category exposure cap sizes a trade DOWN, a position smaller than this fraction of
# the starting bankroll is treated as "dust" and SKIPPED — so a sub-cent capped fill can't count
# as a full unit toward the F11 minimum-trades significance floor. 1e-4 of a $10k bankroll = $1.
# Applies ONLY on the capped path, so the cap=None reproduction contract is byte-for-byte unchanged.
_CAP_DUST_FLOOR_FRACTION: float = 1e-4

# The label an UNCATEGORIZED market buckets into for BOTH per-category caps.
_UNCATEGORIZED_KEY: str = "__uncategorized__"


def _cat_key_for_fingerprint(category: Optional[str]) -> str:
    """The single definition of "which per-category bucket does this market fall in".

    Deliberately module-level and shared by BOTH the cap sizing logic (via the inner
    ``_cat_key``) and ``_seed_hash``'s ``market_categories`` fingerprint. Two copies of this
    rule could drift, and a drift between "what the caps bucket on" and "what the hash
    fingerprints" would silently re-open the very reproducibility hole the fingerprint exists
    to close — so there is exactly one.
    """
    return category if category is not None else _UNCATEGORIZED_KEY


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
    # OPTIONAL coarse correlation category, carried from ``HistoricalMarket.category`` so a
    # cost model with a per-category ``fee_schedule`` (EXP-010) can price the decision-side
    # fee correctly. Pure decision-time METADATA (the category IS knowable at decision time
    # — it is a static property of the market, never the outcome), so it is leakage-neutral.
    # Defaulted to None so every existing MarketView construction is unchanged, and with the
    # default (flat) cost model the field is ignored entirely (bit-identical behavior).
    category: Optional[str] = None


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
        # Net edge on each side, costs included (price basis = the side's raw price). The
        # category is threaded so a per-category ``fee_schedule`` prices the fee correctly;
        # with the default (flat) cost model it is ignored (bit-identical). Both legs of the
        # SAME market share one category (the fee is symmetric in p<->(1-p) anyway).
        cat = view.category
        yes_edge = cost_model.net_edge(p_yes, view.market_price, category=cat)
        no_price = 1.0 - view.market_price
        no_edge = cost_model.net_edge(1.0 - p_yes, no_price, category=cat)

        side, edge, basis = ("YES", yes_edge, view.market_price)
        if no_edge > yes_edge:
            side, edge, basis = ("NO", no_edge, no_price)

        if edge < min_edge:
            return TradeDecision(trade=False)

        # Fractional Kelly on net odds b = (1 - c_eff)/c_eff with win prob q.
        c_eff = cost_model.effective_buy_price(basis, category=cat)
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
        category=m.category,
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
    # Category is threaded so a per-category ``fee_schedule`` (EXP-010) prices the fill fee;
    # with the default (flat) cost model it is ignored, so the fill is bit-identical. The
    # real per-contract fee is symmetric in p<->(1-p), so the YES/NO ``basis`` split above
    # does not change it.
    cat = m.category
    if m.liquidity is None:
        c_eff = cost_model.effective_buy_price(basis, category=cat)
        contracts = cost_model.contracts_for_budget(budget_usd, basis, category=cat)
    else:
        size0 = cost_model.contracts_for_budget(budget_usd, basis, category=cat)
        c_eff = cost_model.effective_buy_price_with_impact(basis, size0, m.liquidity, category=cat)
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
    category_exposure_cap: Optional[float] = None,
    cumulative_category_budget_cap: Optional[float] = None,
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

    CONCENTRATION (optional ``category_exposure_cap``): a live-style per-CATEGORY risk
    control. Total CONCURRENTLY-committed cost basis in any one ``market.category`` may not
    exceed ``category_exposure_cap`` × current equity at the instant a position opens; a trade
    that would breach it is SIZED DOWN to the remaining room (skipped if room ≤ a tiny dust
    floor). ``None`` (default) disables it — behaviour and ``seed_hash`` are then byte-identical
    to before, so every pinned reproduction hash holds; a set cap enters the fingerprint
    (results legitimately differ). Unlabeled markets share one ``__uncategorized__`` bucket.

    SCOPE — READ THIS (what it does and does NOT address). Research Run 22 diagnosed the
    REFUTED bucket family's F10 concentration as "many small CORRELATED trades in one category,
    not one oversized bet — a per-TRADE notional cap is a no-op", and named a per-category
    EXPOSURE cap as the fix. IMPORTANT: F10's ``top_category_budget_share`` is a CUMULATIVE
    measure (Σ budget over the WHOLE backtest ÷ total), whereas THIS cap bounds CONCURRENT
    open exposure at an instant. They are different quantities: because positions settle and
    free room, a category can cycle unbounded CUMULATIVE volume through recycled room while a
    concurrent cap never binds. So this cap bounds instantaneous/liquidity-style concentration;
    it does NOT, by construction, bound the cumulative same-category budget share F10 gates on.

    CUMULATIVE de-concentration (optional ``cumulative_category_budget_cap``): the faithful
    control the concurrent cap could not provide. It bounds each category's LIFETIME budget
    SHARE — Σ per-category budget ÷ Σ total budget, the EXACT quantity F10's
    ``top_category_budget_share`` measures — by sizing every trade DOWN so the running
    post-trade share never exceeds the cap (the first deployed trade in the whole book is
    bootstrap-exempt because its share is 1.0 by definition; its fixed budget is diluted away as
    turnover grows, so the realized top share converges to the cap). This finally enables the
    honest test Research Runs 20-22 named: "does DE-CONCENTRATING rescue the REFUTED family?"
    The remaining ingredient is a corpus whose alpha is net-POSITIVE-but-fragile (F10
    concentration is only assessable on a positive aggregate) — the committed frozen corpus is
    net-NEGATIVE, so on it BOTH caps are moot (no concentration control can manufacture an edge
    from a losing signal), and that corpus stays the filed next step. Like the concurrent cap
    this is a RISK CONTROL, not an edge — it can only REDUCE/reallocate exposure, never
    manufacture PnL. It is a NO-OP when the book has <2 distinct categories (a share cap has
    nowhere to reallocate on a single-category / all-uncategorized book — mirroring F10's own
    categories-known exclusion) or when the cap is >=1.0 (no constraint); a no-op hashes
    identically to no cap. ``None`` (default) leaves ``seed_hash`` byte-identical to before.

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
    if category_exposure_cap is not None and not (0.0 < category_exposure_cap <= 1.0):
        raise ValueError(
            f"category_exposure_cap must be in (0, 1] or None: {category_exposure_cap}"
        )
    if cumulative_category_budget_cap is not None and not (
        0.0 < cumulative_category_budget_cap <= 1.0
    ):
        raise ValueError(
            "cumulative_category_budget_cap must be in (0, 1] or None: "
            f"{cumulative_category_budget_cap}"
        )
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
    # EFFECTIVE cumulative cap. A per-category budget-SHARE cap is only meaningful when there
    # are >=2 distinct categories to reallocate BETWEEN — on a single-category book (including
    # the common all-``None`` / all-``__uncategorized__`` corpus a frozen file without category
    # labels produces) a share cap has nowhere to move budget, so demanding share<=cap<1 would
    # choke the whole book to the one bootstrap trade (and then falsely read its 100% share as a
    # cap breach). So it is a NO-OP below 2 categories — mirroring F10's own ``categories_known``
    # exclusion (regime_slice refuses to gate category concentration when labels are absent).
    # ``cap==1.0`` (100% share = no constraint) is likewise a no-op. Using the EFFECTIVE cap for
    # BOTH the sizing AND the fingerprint keeps the contract clean: a no-op cap hashes identically
    # to no cap (no phantom hash change), and a binding cap enters the fingerprint. The decision
    # is a pure function of the DATA (category set), never of strategy_fn, so the hash stays
    # data+config-only.
    _distinct_cats = {_cat_key_for_fingerprint(m.category) for m in markets}
    effective_cumulative_cap: Optional[float] = (
        cumulative_category_budget_cap
        if (cumulative_category_budget_cap is not None
            and cumulative_category_budget_cap < 1.0
            and len(_distinct_cats) >= 2)
        else None
    )
    cfg_hash = _seed_hash(
        markets, seed, initial_bankroll, cost_model, train_min_days,
        test_window_days, max_fraction_per_trade, category_exposure_cap,
        effective_cumulative_cap,
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
    # Committed cost basis broken out by correlation category, so the exposure cap can bound
    # how much capital is tied up in any ONE category at once. Kept in sync with ``committed``
    # (their values always sum) on every open/drain, whether or not the cap is enabled.
    committed_by_cat: dict[str, float] = {}
    # CUMULATIVE (lifetime) deployment trackers for the optional
    # ``cumulative_category_budget_cap``. Unlike ``committed_by_cat`` these are NEVER
    # decremented on settlement — they accrue the total budget EVER deployed, per category and
    # in aggregate, so the cap can bound the SAME cumulative per-category budget share F10
    # (regime_slice.top_category_budget_share = Σ per-cat budget ÷ Σ total budget) gates on.
    cum_deployed_total = 0.0
    cum_deployed_by_cat: dict[str, float] = {}
    settled: list[BacktestTrade] = []
    # min-heap keyed (resolution_time, market_id, seq); seq is a monotonic tie-breaker so
    # the BacktestTrade payload is NEVER compared (it is not orderable).
    pending: list[tuple[datetime, str, int, BacktestTrade]] = []
    seq = 0

    # Delegates to the module-level definition so the cap bucketing and the seed_hash
    # category fingerprint can never disagree (see _cat_key_for_fingerprint).
    _cat_key = _cat_key_for_fingerprint

    def _drain_until(when: datetime) -> None:
        nonlocal cash, committed
        while pending and pending[0][0] <= when:
            _, _, _, tr = heapq.heappop(pending)
            cash += tr.payout_usd
            committed -= tr.budget_usd
            committed_by_cat[_cat_key(tr.category)] -= tr.budget_usd
            settled.append(tr)

    for m, decision in intents:
        # Realize every resolution that happened at/before this open. (Markets have a
        # strictly positive duration, so a position never resolves at the instant it
        # opens — no intra-instant capital recycling.)
        _drain_until(m.decision_time)
        equity = cash + committed
        frac = min(max(decision.kelly_fraction, 0.0), max_fraction_per_trade)
        budget = min(equity * frac, cash)     # HARD free-cash cap — no over-deployment
        if category_exposure_cap is not None:
            # Bound total committed basis in THIS category to cap × equity. Size the trade
            # DOWN to the remaining room rather than dropping it outright (a partial position
            # still contributes to a broad edge; a breach is what we refuse). NOTE: which
            # specific same-category, same-instant candidate "wins" the remaining room is an
            # artifact of the (decision_time, market_id, seq) order, not a risk-based choice —
            # so a capped run's realized PnL carries an order-dependent component. DUST GUARD:
            # if the room only admits a near-zero "dust" position, SKIP it rather than let a
            # sub-cent trade count as a full unit toward the F11 min-trades significance floor.
            cat = _cat_key(m.category)
            cat_room = category_exposure_cap * equity - committed_by_cat.get(cat, 0.0)
            budget = min(budget, cat_room)
            if budget < _CAP_DUST_FLOOR_FRACTION * initial_bankroll:
                continue
        if effective_cumulative_cap is not None:
            # CUMULATIVE (lifetime) per-category budget-SHARE cap — the faithful
            # de-concentration control Research Runs 20-22 named but never built. The concurrent
            # ``category_exposure_cap`` above bounds INSTANTANEOUS open exposure; because
            # positions settle and free room, a category can still cycle unbounded CUMULATIVE
            # volume, so the concurrent cap does NOT bound F10's
            # ``top_category_budget_share`` = Σ per-cat budget ÷ Σ total budget. THIS cap does:
            # it sizes each trade DOWN so the running post-trade share
            # (cum_cat + b) / (cum_total + b) never exceeds the cap. Solving that equality for
            # the admissible budget b gives room = (cap·cum_total − cum_cat) / (1 − cap); a trade
            # sized to exactly that room lands the category's cumulative share ON the cap line.
            # BOOTSTRAP: the share of the FIRST deployed trade in the whole book is 1.0 by
            # definition (it is the entire book), so no share cap < 1.0 can admit it — the first
            # trade (``cum_deployed_total == 0``) is therefore exempt. Its fixed budget is diluted
            # by later turnover, so the realized top share converges to the cap as total turnover
            # grows (residual slack ≤ first_trade_budget ÷ total_budget — asserted in the tests,
            # not hidden). This is a RISK CONTROL: it can only REDUCE a category's cumulative
            # share, never manufacture PnL — on a net-NEGATIVE corpus it cannot create an edge.
            capc = effective_cumulative_cap
            ccat = _cat_key(m.category)
            if cum_deployed_total > 0.0:
                cum_room = (
                    capc * cum_deployed_total - cum_deployed_by_cat.get(ccat, 0.0)
                ) / (1.0 - capc)
                budget = min(budget, cum_room)
                if budget < _CAP_DUST_FLOOR_FRACTION * initial_bankroll:
                    continue
        if budget <= 0.0:
            continue
        trade = _settle(m, decision, budget, cost_model)
        if trade is None:
            continue
        cash -= trade.budget_usd
        committed += trade.budget_usd
        committed_by_cat[_cat_key(trade.category)] = (
            committed_by_cat.get(_cat_key(trade.category), 0.0) + trade.budget_usd
        )
        # Accrue LIFETIME deployment (never decremented on settlement) so the cumulative cap
        # bounds the same Σ-budget share F10 gates on.
        cum_deployed_total += trade.budget_usd
        cum_deployed_by_cat[_cat_key(trade.category)] = (
            cum_deployed_by_cat.get(_cat_key(trade.category), 0.0) + trade.budget_usd
        )
        heapq.heappush(pending, (trade.resolution_time, trade.market_id, seq, trade))
        seq += 1

    # Drain any positions still open at the end of the timeline.
    while pending:
        _, _, _, tr = heapq.heappop(pending)
        cash += tr.payout_usd
        committed -= tr.budget_usd
        committed_by_cat[_cat_key(tr.category)] -= tr.budget_usd
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
    category_exposure_cap: Optional[float] = None,
    cumulative_category_budget_cap: Optional[float] = None,
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
            # (category_exposure_cap + the per-market category labels are added below ONLY
            # when set/active — see notes.)
            # liquidity is included so determinism/fingerprint covers the depth signal
            # that now affects fill cost. Existing markets have liquidity=None → stored as
            # JSON null, a stable representation, so same-data runs keep consistent hashes
            # and the cost-rate-change hash test still holds. NOTE: m.category is NOT in
            # this row — it is fingerprinted separately, and only when a per-category cap is
            # active (see the ``market_categories`` block below). Keeping it out of the row
            # is what preserves the pinned cap-free reproduction hash 8dc358439ffb5746.
            [m.market_id, m.decision_time.isoformat(), m.resolution_time.isoformat(),
             round(m.market_price, 12), round(m.model_prob, 12), m.outcome,
             None if m.liquidity is None else round(m.liquidity, 12)]
            for m in sorted(markets, key=lambda x: (x.decision_time, x.market_id))
        ],
    }
    # Added ONLY when set: an enabled cap changes PnL, so it MUST enter the fingerprint;
    # but omitting the key entirely when None keeps the payload — and therefore the pinned
    # reproduction hashes — byte-identical for every existing (cap-free) run.
    if category_exposure_cap is not None:
        payload["category_exposure_cap"] = round(category_exposure_cap, 12)
    # Same byte-identical-when-None discipline: an enabled cumulative cap changes PnL so it
    # MUST enter the fingerprint, but omitting the key when None keeps every pinned cap-free
    # reproduction hash unchanged.
    if cumulative_category_budget_cap is not None:
        payload["cumulative_category_budget_cap"] = round(cumulative_category_budget_cap, 12)
    # Same byte-identical-when-None discipline for the EXP-010 real fee schedule: a set
    # fee_schedule changes the per-fill fee (feeRate·p·(1-p) instead of the flat fee_rate) and
    # therefore PnL, so it MUST enter the fingerprint or two runs with identical data/seed but
    # different fee models would share a hash yet diverge in PnL. Omitting the key when None
    # (the default) keeps every pinned flat-model reproduction hash (b3a8d5e0e9579853 / …)
    # byte-identical. The schedule's PnL-affecting identity = its default fallback rate + the
    # per-category rate map. Covered by test_seed_hash_covers_fee_schedule.
    if cost_model.fee_schedule is not None:
        payload["fee_schedule"] = {
            "default_fee_rate": round(cost_model.fee_schedule.default_fee_rate, 12),
            "rates": {k: round(v, 12) for k, v in sorted(POLYMARKET_FEE_RATES.items())},
        }
    # PER-MARKET CATEGORY LABELS — added ONLY when a per-category cap is active.
    #
    # This closes a real reproducibility hole (found by the independent Quality Auditor,
    # 2026-07-24). Category is regime-slice metadata and is genuinely PnL-IRRELEVANT while
    # BOTH caps are off — which is why it stays out of the market row above and why every
    # pinned cap-free hash (8dc358439ffb5746, b3a8d5e0e9579853, 79a4cca4b966138f) is
    # byte-identical before and after this block.
    #
    # But the moment EITHER cap is active, category becomes PnL-DETERMINING: the concurrent
    # lane sizes a trade down by ``cat_room`` (see ``_cat_key``/``committed_by_cat`` above)
    # and the cumulative lane by ``cum_room``. Two datasets identical in every other
    # fingerprinted field and differing ONLY in their category labels then produce
    # materially different trade counts and PnL (measured up to 3.9x) — and, before this
    # fix, the SAME seed_hash. A reviewer comparing hashes was actively misled. Note the
    # ``effective_cumulative_cap`` mitigation does NOT cover this: it keys on the
    # distinct-category COUNT, so a same-count/different-assignment relabel defeats it.
    #
    # The labels are fingerprinted through ``_cat_key`` (not the raw field) because that is
    # exactly the value the cap logic buckets on — ``None`` and the literal
    # ``"__uncategorized__"`` are the same bucket and so must hash the same. Ordering
    # follows the same total ``(decision_time, market_id)`` sort as the market rows, so the
    # fingerprint stays input-order-invariant. Covered by
    # ``test_seed_hash_covers_category_when_cap_active``.
    if category_exposure_cap is not None or cumulative_category_budget_cap is not None:
        payload["market_categories"] = [
            _cat_key_for_fingerprint(m.category)
            for m in sorted(markets, key=lambda x: (x.decision_time, x.market_id))
        ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


__all__ = [
    "HistoricalMarket", "MarketView", "TradeDecision", "BacktestTrade",
    "WalkForwardResult", "StrategyFn", "make_net_edge_strategy",
    "walk_forward_backtest",
]
