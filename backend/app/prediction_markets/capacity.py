"""capacity.py — how much money can this bot actually deploy before its own order eats
the edge? (ROADMAP / QUALITY_SCORECARD `backtest_integrity` residual (b).)

WHY THIS EXISTS
The $104k/yr floor (`$2,000/wk`) has never been capacity-tested. Every committed OOS
artifact carries `liquidity: null`, so `cost_model`'s market-impact path has never been
exercised on real data and no capacity curve existed anywhere in the repo. A strategy that
clears the floor at $100/trade and dies at $5,000/trade has not cleared the floor — it has
cleared a paper-sized version of it.

WHY THIS IS A SENSITIVITY ANALYSIS AND NOT A MEASUREMENT (read this before quoting a number)
Polymarket does **not** serve retrospective depth. Verified live 2026-07-26 against the
public API:

  * Gamma `/markets?closed=true` returns `liquidity`, `liquidityNum` and `liquidityClob` all
    **null** on resolved markets (checked on the five highest-volume resolved Politics
    markets, incl. ids 253591 / 253597 / 511754).
  * CLOB `/book?token_id=...` returns **HTTP 404** for a resolved market's token.
  * Both fields are populated and the book is a real ladder for **open** markets
    (e.g. id 703258, `liquidity` 883,678.27, 19 bid / 104 ask levels).

So the `liquidity: null` on all 187 frozen records is **not** a threading bug in our fetcher
that could be fixed by carrying a field through — the venue does not retain the value. Depth
at a past decision instant is unobtainable after the fact, full stop. It is capturable going
FORWARD (see `scripts/capacity_probe.py`), which is the buildable path to a measured curve.

Until such a forward capture exists, the only honest analysis is: **sweep the depth we cannot
observe, and report at what depth the conclusion changes.** That is what this module does. It
answers "how deep would the book have to be for a given per-trade size to be affordable", not
"here is the capacity". The impact coefficient is likewise an uncalibrated, deliberately
conservative placeholder (`DEFAULT_IMPACT_COEFF`), so it is a sweep axis too, never a
constant to hide behind.

Pure, deterministic, stdlib-only. Prices every fill through the SAME `cost_model` the live
executor and the backtest use — a capacity curve computed off a different cost model would
be measuring nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from .cost_model import DEFAULT_COST_MODEL, CostModel

# Binary-search resolution for `max_budget_within_drag`. 60 halvings of a bracket that
# starts at most at 1e9 resolves to well below a cent, so the answer is exact for any
# question anyone would ask of it, and the loop is hard-bounded (never `while True`).
_SEARCH_ITERS = 60


@dataclass(frozen=True)
class CapacityPoint:
    """One (budget, depth) cell: what the impact model charges for that order size."""

    budget_usd: float
    contracts_flat: float
    """Contracts the budget buys at the FLAT all-in price (the size the backtest assumes)."""
    flat_cost_per_contract: float
    impacted_cost_per_contract: float
    impact_drag_usd: float
    """Extra dollars paid for the SAME contract count because the book is finite."""
    impact_drag_fraction: float
    """`impact_drag_usd / budget_usd` — the share of the stake lost to own-order impact."""


@dataclass(frozen=True)
class CapacityCurve:
    """A budget sweep at one (price, depth, impact_coeff) assumption."""

    market_price: float
    depth_contracts: float
    impact_coeff: float
    points: tuple[CapacityPoint, ...]


def capacity_point(
    market_price: float,
    budget_usd: float,
    depth_contracts: float,
    *,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    impact_coeff: Optional[float] = None,
    category: Optional[str] = None,
) -> CapacityPoint:
    """Price one order size against one assumed depth.

    The comparison is held at CONSTANT CONTRACT COUNT: we take the contracts the flat model
    says the budget buys, then ask what those same contracts cost once the book is finite.
    That isolates impact as a dollar drag. (The alternative — holding dollars constant and
    reporting fewer contracts — measures the same thing less legibly, and invites double
    counting against a strategy that already sized in dollars.)
    """
    if not (0.0 <= market_price <= 1.0):
        raise ValueError(f"market_price out of [0,1]: {market_price}")
    if budget_usd < 0.0:
        raise ValueError(f"budget_usd must be >= 0: {budget_usd}")
    if not (depth_contracts > 0.0):
        # Depth is a divisor in the impact model. A non-positive depth is a data error, and
        # silently treating it as "no impact" would report infinite capacity on an empty
        # book — the exact direction of error this module exists to prevent.
        raise ValueError(f"depth_contracts must be > 0: {depth_contracts}")

    flat = cost_model.effective_buy_price(market_price, category)
    if flat <= 0.0:
        raise ValueError(f"flat all-in price must be > 0, got {flat} at p={market_price}")
    contracts = budget_usd / flat
    impacted = cost_model.effective_buy_price_with_impact(
        market_price, contracts, depth_contracts, impact_coeff, category
    )
    drag = (impacted - flat) * contracts
    return CapacityPoint(
        budget_usd=budget_usd,
        contracts_flat=contracts,
        flat_cost_per_contract=flat,
        impacted_cost_per_contract=impacted,
        impact_drag_usd=drag,
        impact_drag_fraction=(drag / budget_usd) if budget_usd > 0.0 else 0.0,
    )


def capacity_curve(
    market_price: float,
    depth_contracts: float,
    budgets_usd: Sequence[float],
    *,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    impact_coeff: Optional[float] = None,
    category: Optional[str] = None,
) -> CapacityCurve:
    """Sweep order size at a fixed depth. Report-all; selects nothing."""
    coeff = cost_model.impact_coeff if impact_coeff is None else impact_coeff
    pts = tuple(
        capacity_point(
            market_price, b, depth_contracts,
            cost_model=cost_model, impact_coeff=impact_coeff, category=category,
        )
        for b in budgets_usd
    )
    return CapacityCurve(
        market_price=market_price,
        depth_contracts=depth_contracts,
        impact_coeff=coeff,
        points=pts,
    )


def max_budget_within_drag(
    market_price: float,
    depth_contracts: float,
    max_drag_fraction: float,
    *,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    impact_coeff: Optional[float] = None,
    category: Optional[str] = None,
    upper_bound_usd: float = 1e9,
) -> float:
    """Largest per-trade budget whose own-order impact drag stays within a tolerance.

    THE capacity number: "at this depth, I can put at most $X to work per trade before more
    than `max_drag_fraction` of the stake is eaten by my own order."

    `impact_fraction` is monotone non-decreasing in size (up to its clamp), and drag rises
    with it, so a bisection on budget is sound. If even `upper_bound_usd` stays within
    tolerance the bound is returned — the caller is told the search saturated rather than
    handed a fabricated infinity.
    """
    if not (0.0 < max_drag_fraction < 1.0):
        raise ValueError(f"max_drag_fraction must be in (0,1): {max_drag_fraction}")

    def drag(b: float) -> float:
        return capacity_point(
            market_price, b, depth_contracts,
            cost_model=cost_model, impact_coeff=impact_coeff, category=category,
        ).impact_drag_fraction

    if drag(upper_bound_usd) <= max_drag_fraction:
        return upper_bound_usd
    lo, hi = 0.0, upper_bound_usd
    for _ in range(_SEARCH_ITERS):
        mid = (lo + hi) / 2.0
        if drag(mid) <= max_drag_fraction:
            lo = mid
        else:
            hi = mid
    return lo


@dataclass(frozen=True)
class FloorFeasibility:
    """Can a weekly-dollar target be reached at this depth, per-trade edge and trade rate?"""

    weekly_target_usd: float
    trades_per_week: int
    edge_fraction_per_trade: float
    """Net edge as a fraction of the deployed stake (AFTER flat costs, BEFORE impact)."""
    naive_budget_per_trade_usd: float
    """What the stake would be if impact were free — i.e. what a flat-cost backtest implies.
    Shown for contrast; it is NOT the answer, and treating it as one is the error this
    whole module exists to catch."""
    required_budget_per_trade_usd: float
    """Smallest stake whose AFTER-IMPACT PnL actually reaches the per-trade target.
    ``inf`` when no stake can (impact grows faster than the edge)."""
    impact_drag_usd_per_trade: float
    """Drag at the required stake (at the PEAK stake when the target is unreachable)."""
    net_pnl_per_trade_usd: float
    """Per-trade PnL after impact at that stake."""
    achieved_weekly_usd: float
    max_achievable_weekly_usd: float
    """The most this signal can EVER earn per week at this depth and trade rate, at the
    profit-maximising stake. Impact rises super-linearly in size while the edge rises
    linearly, so this ceiling is finite — deploying more capital past it earns LESS."""
    peak_budget_per_trade_usd: float
    """The stake achieving that ceiling."""
    feasible: bool
    """True only if the target is met AFTER impact at an attainable stake."""
    binding_reason: str


def floor_feasibility(
    weekly_target_usd: float,
    trades_per_week: int,
    edge_fraction_per_trade: float,
    market_price: float,
    depth_contracts: float,
    *,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    impact_coeff: Optional[float] = None,
    category: Optional[str] = None,
) -> FloorFeasibility:
    """Turn a weekly-dollar floor into a capacity question and answer it honestly.

    Given a target, a trade rate and a per-trade edge, this computes the stake each trade
    must carry, then charges that stake the impact it would really pay at the assumed depth.
    The point is the failure mode a flat-cost backtest cannot see: an edge that is real at
    $100/trade and NEGATIVE at the size the floor actually requires.

    `edge_fraction_per_trade` is an INPUT, not something this module can produce. It must
    come from a validated OOS result. Feeding it a backtest's in-sample edge produces a
    capacity number about a fictional strategy — this function will compute it correctly and
    the answer will still be meaningless.
    """
    if trades_per_week <= 0:
        raise ValueError(f"trades_per_week must be > 0: {trades_per_week}")
    if weekly_target_usd <= 0.0:
        raise ValueError(f"weekly_target_usd must be > 0: {weekly_target_usd}")
    if edge_fraction_per_trade <= 0.0:
        # A non-positive edge has no capacity question: no size makes a losing signal pay.
        # Saying so is the honest answer; solving for a budget would divide by it.
        return FloorFeasibility(
            weekly_target_usd=weekly_target_usd,
            trades_per_week=trades_per_week,
            edge_fraction_per_trade=edge_fraction_per_trade,
            naive_budget_per_trade_usd=float("inf"),
            required_budget_per_trade_usd=float("inf"),
            impact_drag_usd_per_trade=0.0,
            net_pnl_per_trade_usd=0.0,
            achieved_weekly_usd=0.0,
            max_achievable_weekly_usd=0.0,
            peak_budget_per_trade_usd=0.0,
            feasible=False,
            binding_reason=(
                "edge_fraction_per_trade <= 0: there is no validated positive edge to size, "
                "so capacity is not the binding constraint — the edge is"
            ),
        )

    per_trade_target = weekly_target_usd / trades_per_week
    naive_budget = per_trade_target / edge_fraction_per_trade

    def net_at(b: float) -> float:
        """After-impact PnL for a stake of `b`. The edge scales LINEARLY in size while
        impact scales super-linearly (~b^1.5 under the sqrt model), so this rises, peaks and
        then falls — which is precisely the capacity ceiling a flat-cost backtest cannot see.
        """
        if b <= 0.0:
            return 0.0
        gross = b * edge_fraction_per_trade
        pt = capacity_point(
            market_price, b, depth_contracts,
            cost_model=cost_model, impact_coeff=impact_coeff, category=category,
        )
        return gross - pt.impact_drag_usd

    # Locate the profit-maximising stake. A coarse logarithmic scan followed by local
    # refinement, rather than a ternary search: the impact fraction is CLAMPED at
    # DEFAULT_MAX_IMPACT_FRACTION, so the curve is not guaranteed strictly unimodal over the
    # whole range and a ternary search could walk off the flat region. The scan is
    # deterministic and hard-bounded.
    lo_exp, hi_exp = -2, 9  # $0.01 .. $1e9
    grid = [10.0 ** (lo_exp + i * (hi_exp - lo_exp) / 220.0) for i in range(221)]
    peak_b = max(grid, key=net_at)
    # Refine within one grid step either side.
    step = peak_b * (10.0 ** ((hi_exp - lo_exp) / 220.0) - 1.0)
    lo_r, hi_r = max(1e-9, peak_b - step), peak_b + step
    for _ in range(_SEARCH_ITERS):
        m1 = lo_r + (hi_r - lo_r) / 3.0
        m2 = hi_r - (hi_r - lo_r) / 3.0
        if net_at(m1) < net_at(m2):
            lo_r = m1
        else:
            hi_r = m2
    peak_b = (lo_r + hi_r) / 2.0
    peak_net = net_at(peak_b)
    max_weekly = peak_net * trades_per_week

    # SATURATION CHECK — refuse to report a ceiling that does not exist.
    #
    # The "impact grows super-linearly so a finite peak exists" reasoning holds only while
    # `impact_fraction` is UNSATURATED. Once it hits its clamp (`DEFAULT_MAX_IMPACT_FRACTION`)
    # the impacted price plateaus near $1 while contracts still grow linearly with budget, so
    # drag becomes LINEAR with slope `(1-flat)/flat`. If `edge_fraction_per_trade` exceeds
    # that slope, `net_at` increases without bound and there is NO peak — the grid search
    # would then return wherever it happened to stop (its 1e9 upper bound) dressed up as
    # "the most this signal can EVER earn". An adversarial reviewer reproduced exactly that:
    # a $1.12bn "peak" and a $112m/wk "ceiling" at price 0.95 / edge 0.037.
    #
    # That regime is not exotic — `(1-flat)/flat` shrinks as price -> 1, and this bot's own
    # NearCertaintyStrategy trades above 0.90 with a default `min_edge` of 0.02, so the
    # crossover sits around price 0.965, inside its operating envelope.
    #
    # Reporting a fabricated unbounded capacity is the precise failure this module exists to
    # prevent, so we detect it and say so instead.
    _flat = cost_model.effective_buy_price(market_price, category)
    _saturated_slope = (1.0 - _flat) / _flat if _flat > 0.0 else float("inf")
    if edge_fraction_per_trade > _saturated_slope and net_at(peak_b * 10.0) > peak_net:
        return FloorFeasibility(
            weekly_target_usd=weekly_target_usd,
            trades_per_week=trades_per_week,
            edge_fraction_per_trade=edge_fraction_per_trade,
            naive_budget_per_trade_usd=naive_budget,
            required_budget_per_trade_usd=float("nan"),
            impact_drag_usd_per_trade=float("nan"),
            net_pnl_per_trade_usd=float("nan"),
            achieved_weekly_usd=float("nan"),
            max_achievable_weekly_usd=float("inf"),
            peak_budget_per_trade_usd=float("inf"),
            feasible=False,
            binding_reason=(
                f"NO CAPACITY CEILING EXISTS under this model at price {market_price:.4f}: "
                f"the assumed per-trade edge ({edge_fraction_per_trade:.4f}) exceeds the "
                f"saturated-impact slope ({_saturated_slope:.4f}), so modelled profit grows "
                f"without bound in size. That is a MODEL ARTIFACT — the impact fraction is "
                f"clamped at {1.0:.1f}, and a real book does not let an order of arbitrary "
                f"size fill at a bounded price. Treat this as 'the impact model does not "
                f"apply here', NOT as unlimited capacity, and use a real book walk "
                f"(`walk_book`) instead."
            ),
        )

    if peak_net < per_trade_target:
        # Unreachable at ANY stake: past the peak, more capital earns less.
        pt_peak = capacity_point(
            market_price, peak_b, depth_contracts,
            cost_model=cost_model, impact_coeff=impact_coeff, category=category,
        )
        reason = (
            f"UNREACHABLE at any stake: the most this signal can earn at depth "
            f"{depth_contracts:,.0f} is ${peak_net:,.2f}/trade (${max_weekly:,.2f}/wk at "
            f"{trades_per_week} trades/wk) at a ${peak_b:,.2f} stake, against a "
            f"${per_trade_target:,.2f}/trade target. Beyond that stake, own-order impact "
            f"grows faster than the edge and MORE capital earns LESS."
        )
        return FloorFeasibility(
            weekly_target_usd=weekly_target_usd,
            trades_per_week=trades_per_week,
            edge_fraction_per_trade=edge_fraction_per_trade,
            naive_budget_per_trade_usd=naive_budget,
            required_budget_per_trade_usd=float("inf"),
            impact_drag_usd_per_trade=pt_peak.impact_drag_usd,
            net_pnl_per_trade_usd=peak_net,
            achieved_weekly_usd=max_weekly,
            max_achievable_weekly_usd=max_weekly,
            peak_budget_per_trade_usd=peak_b,
            feasible=False,
            binding_reason=reason,
        )

    # Reachable: bisect on [0, peak] for the SMALLEST stake that clears the target. `net_at`
    # is increasing on that interval (the peak is its maximum), so bisection is sound, and
    # the smallest sufficient stake is the right answer — it minimises capital at risk.
    lo, hi = 0.0, peak_b
    for _ in range(_SEARCH_ITERS):
        mid = (lo + hi) / 2.0
        if net_at(mid) >= per_trade_target:
            hi = mid
        else:
            lo = mid
    required = hi
    pt_req = capacity_point(
        market_price, required, depth_contracts,
        cost_model=cost_model, impact_coeff=impact_coeff, category=category,
    )
    net_req = net_at(required)
    achieved = net_req * trades_per_week
    return FloorFeasibility(
        weekly_target_usd=weekly_target_usd,
        trades_per_week=trades_per_week,
        edge_fraction_per_trade=edge_fraction_per_trade,
        naive_budget_per_trade_usd=naive_budget,
        required_budget_per_trade_usd=required,
        impact_drag_usd_per_trade=pt_req.impact_drag_usd,
        net_pnl_per_trade_usd=net_req,
        achieved_weekly_usd=achieved,
        max_achievable_weekly_usd=max_weekly,
        peak_budget_per_trade_usd=peak_b,
        feasible=True,
        binding_reason=(
            f"target met after impact at a ${required:,.2f} stake "
            f"({required / naive_budget:.2f}x the ${naive_budget:,.2f} a flat-cost backtest "
            f"would imply); headroom to ${max_weekly:,.2f}/wk at the ${peak_b:,.2f} peak"
        ),
    )


# --------------------------------------------------------------------------- #
# Empirical impact — walking a REAL ladder, with no model parameter at all.     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BookWalk:
    """The true cost of taking `contracts` off a real ask ladder."""

    contracts_requested: float
    contracts_filled: float
    """Less than requested when the visible ladder is exhausted — never silently padded."""
    touch_price: float
    average_fill_price: float
    realized_impact_fraction: float
    """`average_fill / touch - 1`. The MEASURED impact. No coefficient involved."""
    exhausted_book: bool


def walk_book(levels: Sequence[dict], contracts: float) -> BookWalk:
    """Fill `contracts` against a real best-first ask ladder and report what it truly cost.

    This is the ground truth the parametric `impact_fraction` model is trying to approximate.
    Feeding it a captured ladder yields an impact number that depends on NO free parameter,
    which is the only honest way to ask whether `DEFAULT_IMPACT_COEFF` resembles this venue.

    Levels must be best-first (`PolymarketClient.get_order_book` normalizes them). If the
    ladder is exhausted the walk reports `exhausted_book=True` and the partial fill rather
    than extrapolating — an extrapolated tail would be exactly the invented number this
    module exists to avoid.
    """
    if contracts <= 0.0:
        raise ValueError(f"contracts must be > 0: {contracts}")
    if not levels:
        raise ValueError("cannot walk an empty ladder")
    touch = float(levels[0]["price"])
    if not (touch > 0.0):
        raise ValueError(f"touch price must be > 0: {touch}")
    # VALIDATE THE LADDER SHAPE. `touch = levels[0]` is load-bearing, so a worst-first (or
    # otherwise unsorted) ladder would silently produce NEGATIVE realized impact — "buying
    # more made it cheaper" — contradicting the invariant the sibling parametric model
    # enforces. `get_order_book` normalizes order today, so this cannot fire through the
    # live client; it is guarded because this function is public and the named next step is
    # to wire it into the live impact path, where a future caller with a hand-built or
    # third-venue ladder would otherwise introduce a silent pricing bug.
    prices = [float(lvl["price"]) for lvl in levels]
    if any(b < a for a, b in zip(prices, prices[1:])):
        raise ValueError(
            "ask ladder must be best-first (non-decreasing price); got "
            f"{prices[:5]}... — an unsorted ladder yields negative realized impact"
        )
    if any(float(lvl["size"]) <= 0.0 for lvl in levels):
        raise ValueError("every ladder level must carry a positive size")

    remaining = contracts
    spend = 0.0
    filled = 0.0
    for lvl in levels:
        if remaining <= 0.0:
            break
        take = min(remaining, float(lvl["size"]))
        spend += take * float(lvl["price"])
        filled += take
        remaining -= take
    exhausted = remaining > 0.0
    avg = spend / filled if filled > 0.0 else touch
    return BookWalk(
        contracts_requested=contracts,
        contracts_filled=filled,
        touch_price=touch,
        average_fill_price=avg,
        realized_impact_fraction=(avg / touch) - 1.0,
        exhausted_book=exhausted,
    )


def implied_impact_coeff(
    levels: Sequence[dict], contracts: float, depth_contracts: float
) -> Optional[float]:
    """The `impact_coeff` that would reproduce a ladder's MEASURED impact.

    Inverts `impact = coeff * sqrt(size / depth)` against the realized impact from
    `walk_book`, giving `coeff = realized / sqrt(size / depth)`. Running this across many
    real books is how `DEFAULT_IMPACT_COEFF` stops being a placeholder.

    Returns None when the walk exhausted the visible ladder — a partial fill's realized
    impact UNDERSTATES the true cost of the requested size (the unfilled remainder would
    have been the most expensive part), so inverting it would produce a coefficient that is
    too LOW, i.e. wrong in the dangerous direction. Refusing is the honest answer.
    """
    if depth_contracts <= 0.0:
        raise ValueError(f"depth_contracts must be > 0: {depth_contracts}")
    walk = walk_book(levels, contracts)
    if walk.exhausted_book:
        return None
    denom = math.sqrt(contracts / depth_contracts)
    if denom <= 0.0:
        return None
    return walk.realized_impact_fraction / denom


__all__ = [
    "CapacityPoint", "CapacityCurve", "FloorFeasibility", "BookWalk",
    "capacity_point", "capacity_curve", "max_budget_within_drag", "floor_feasibility",
    "walk_book", "implied_impact_coeff",
]
