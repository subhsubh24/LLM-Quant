"""Tests for `prediction_markets.capacity` — the capacity / market-impact analysis.

DETERMINISTIC + OFFLINE. No network, no fixtures beyond literals.

What these pin, in priority order:
  1. The module never reports MORE capacity than the impact model implies (the dangerous
     direction — an overstated capacity is how a paper-sized edge gets mistaken for a
     fundable one).
  2. It refuses to fabricate an answer where none exists (non-positive depth, non-positive
     edge) rather than returning a plausible number.
  3. The bisection in `max_budget_within_drag` really is the boundary it claims.
"""

from __future__ import annotations

import pytest

from app.prediction_markets.capacity import (
    implied_impact_coeff,
    walk_book,
    capacity_curve,
    capacity_point,
    floor_feasibility,
    max_budget_within_drag,
)
from app.prediction_markets.cost_model import DEFAULT_COST_MODEL, CostModel


# --------------------------------------------------------------------------- #
# 1. capacity_point — impact only ever ADDS cost, and grows with size.         #
# --------------------------------------------------------------------------- #
def test_impact_drag_is_never_negative():
    """Impact can only add cost. A negative drag would mean trading big is CHEAPER."""
    for budget in (1.0, 100.0, 10_000.0, 1_000_000.0):
        pt = capacity_point(0.50, budget, depth_contracts=10_000.0)
        assert pt.impact_drag_usd >= 0.0
        assert pt.impacted_cost_per_contract >= pt.flat_cost_per_contract


def test_drag_is_monotone_non_decreasing_in_size():
    """A bigger order can never pay LESS impact at the same depth — this is the property
    the bisection in max_budget_within_drag depends on."""
    prev = -1.0
    for budget in (10.0, 100.0, 1_000.0, 10_000.0, 100_000.0):
        frac = capacity_point(0.40, budget, depth_contracts=5_000.0).impact_drag_fraction
        assert frac >= prev, f"drag fell as size rose at budget={budget}"
        prev = frac


def test_deeper_book_is_never_more_expensive():
    """More depth must weakly reduce impact — the sign check on the whole model."""
    shallow = capacity_point(0.30, 50_000.0, depth_contracts=1_000.0)
    deep = capacity_point(0.30, 50_000.0, depth_contracts=1_000_000.0)
    assert deep.impact_drag_usd <= shallow.impact_drag_usd


def test_very_deep_book_converges_to_the_flat_cost():
    """As depth -> infinity the impacted price must reduce CONTINUOUSLY to the flat price,
    so a capacity analysis never disagrees with the flat-cost backtest in the limit."""
    pt = capacity_point(0.50, 100.0, depth_contracts=1e18)
    # Relative convergence: the impacted price must agree with the flat price to ~1e-7,
    # and the drag must be a vanishing share of the stake. Asserted relatively rather than
    # against an absolute dollar epsilon, because the sqrt model approaches zero smoothly
    # and never reaches it — there is no depth at which impact is exactly free.
    assert pt.impacted_cost_per_contract == pytest.approx(pt.flat_cost_per_contract, rel=1e-7)
    assert pt.impact_drag_fraction < 1e-7


def test_drag_is_nonzero_even_on_a_very_deep_book():
    """The sqrt model has NO threshold below which impact is free. At depth 1e9 a $3,333
    stake still pays real drag. This is the property that makes `naive_budget` (the stake a
    flat-cost backtest implies) systematically too small — pinned so nobody 'optimises' the
    model into a free-below-X shortcut."""
    pt = capacity_point(0.50, 3_333.33, depth_contracts=1e9)
    assert pt.impact_drag_usd > 0.0


def test_zero_impact_coeff_reduces_to_flat():
    pt = capacity_point(0.50, 10_000.0, depth_contracts=10.0, impact_coeff=0.0)
    assert pt.impact_drag_usd == 0.0


# --------------------------------------------------------------------------- #
# 2. Refusals — never fabricate an answer.                                     #
# --------------------------------------------------------------------------- #
def test_non_positive_depth_raises_rather_than_reporting_infinite_capacity():
    """Depth is a divisor. Treating depth<=0 as 'no impact' would report INFINITE capacity
    on an empty book — the single most dangerous possible output of this module."""
    with pytest.raises(ValueError, match="depth_contracts"):
        capacity_point(0.50, 100.0, depth_contracts=0.0)
    with pytest.raises(ValueError, match="depth_contracts"):
        capacity_point(0.50, 100.0, depth_contracts=-5.0)


def test_out_of_range_price_raises():
    with pytest.raises(ValueError, match="market_price"):
        capacity_point(1.5, 100.0, depth_contracts=100.0)


def test_bad_drag_tolerance_raises():
    for bad in (0.0, 1.0, -0.1, 2.0):
        with pytest.raises(ValueError, match="max_drag_fraction"):
            max_budget_within_drag(0.50, 1_000.0, bad)


# --------------------------------------------------------------------------- #
# 3. max_budget_within_drag — the boundary is real.                            #
# --------------------------------------------------------------------------- #
def test_max_budget_is_the_actual_boundary():
    """At the returned budget the drag must be within tolerance, and materially above it
    the drag must EXCEED tolerance. Otherwise the 'capacity' is not a boundary at all."""
    tol = 0.05
    b = max_budget_within_drag(0.50, depth_contracts=20_000.0, max_drag_fraction=tol)
    assert 0.0 < b < 1e9, "expected an interior solution for this depth"
    inside = capacity_point(0.50, b * 0.99, 20_000.0).impact_drag_fraction
    outside = capacity_point(0.50, b * 1.10, 20_000.0).impact_drag_fraction
    assert inside <= tol
    assert outside > tol


def test_saturated_search_returns_the_bound_not_a_fabricated_infinity():
    """If even the upper bound is within tolerance, the BOUND is returned — the caller can
    see the search saturated instead of being handed a made-up number."""
    b = max_budget_within_drag(
        0.50, depth_contracts=1e15, max_drag_fraction=0.5, upper_bound_usd=1_000.0
    )
    assert b == 1_000.0


def test_tighter_tolerance_never_permits_a_larger_budget():
    strict = max_budget_within_drag(0.50, 10_000.0, 0.01)
    loose = max_budget_within_drag(0.50, 10_000.0, 0.10)
    assert strict <= loose


# --------------------------------------------------------------------------- #
# 4. capacity_curve — report-all, select-none.                                 #
# --------------------------------------------------------------------------- #
def test_curve_reports_every_requested_budget_in_order():
    budgets = [100.0, 1_000.0, 10_000.0]
    curve = capacity_curve(0.45, 5_000.0, budgets)
    assert [p.budget_usd for p in curve.points] == budgets
    assert curve.impact_coeff == DEFAULT_COST_MODEL.impact_coeff


def test_curve_records_the_impact_coeff_actually_used():
    """The coefficient is an UNCALIBRATED placeholder, so every curve must carry the value
    it was computed at — a curve without its coefficient is not interpretable."""
    curve = capacity_curve(0.45, 5_000.0, [100.0], impact_coeff=0.9)
    assert curve.impact_coeff == 0.9


# --------------------------------------------------------------------------- #
# 5. floor_feasibility — the business-case question.                           #
# --------------------------------------------------------------------------- #
def test_non_positive_edge_is_refused_not_sized():
    """The project's actual state: no validated positive edge. Capacity is then NOT the
    binding constraint, and the module must say so rather than solve for a budget (which
    would divide by a non-positive edge)."""
    r = floor_feasibility(
        weekly_target_usd=2_000.0, trades_per_week=40, edge_fraction_per_trade=-0.02,
        market_price=0.50, depth_contracts=10_000.0,
    )
    assert r.feasible is False
    assert "no validated positive edge" in r.binding_reason
    assert r.required_budget_per_trade_usd == float("inf")


def test_deep_book_small_target_is_feasible_and_costs_more_than_the_naive_stake():
    """A reachable target: the required stake must EXCEED the naive flat-cost stake, because
    impact has to be paid out of the same gross edge."""
    r = floor_feasibility(
        weekly_target_usd=2_000.0, trades_per_week=100, edge_fraction_per_trade=0.05,
        market_price=0.50, depth_contracts=1e9,
    )
    assert r.feasible is True
    assert r.naive_budget_per_trade_usd == pytest.approx(400.0)
    assert r.required_budget_per_trade_usd > r.naive_budget_per_trade_usd
    assert r.achieved_weekly_usd >= r.weekly_target_usd


def test_thin_book_makes_the_same_target_infeasible():
    """THE failure mode this module exists to expose: identical target, identical edge,
    identical trade rate — only the book is thin — and the floor is no longer reachable."""
    deep = floor_feasibility(
        weekly_target_usd=2_000.0, trades_per_week=20, edge_fraction_per_trade=0.03,
        market_price=0.50, depth_contracts=1e9,
    )
    thin = floor_feasibility(
        weekly_target_usd=2_000.0, trades_per_week=20, edge_fraction_per_trade=0.03,
        market_price=0.50, depth_contracts=50.0,
    )
    assert deep.feasible is True
    assert thin.feasible is False
    assert thin.max_achievable_weekly_usd < deep.max_achievable_weekly_usd
    assert "UNREACHABLE at any stake" in thin.binding_reason


def test_capacity_ceiling_is_real_more_capital_earns_less_past_the_peak():
    """The core capacity claim: past the profit-maximising stake, MORE capital earns LESS.
    If this fails the module is not measuring a ceiling at all."""
    r = floor_feasibility(
        weekly_target_usd=100.0, trades_per_week=10, edge_fraction_per_trade=0.03,
        market_price=0.50, depth_contracts=500.0,
    )
    peak = r.peak_budget_per_trade_usd
    assert peak > 0.0

    def net(b):
        gross = b * 0.03
        return gross - capacity_point(0.50, b, 500.0).impact_drag_usd

    assert net(peak) >= net(peak * 2.0)
    assert net(peak) >= net(peak * 10.0)
    assert net(peak) >= net(peak * 0.5)


def test_wildly_oversized_target_on_a_tiny_book_is_unreachable_at_any_stake():
    """A large target against a 10-contract book. The honest answer is not "you need a huge
    stake" — it is that NO stake reaches it, because past the peak more capital earns less.
    The reason string must say that rather than quote an unreachable required budget."""
    r = floor_feasibility(
        weekly_target_usd=50_000.0, trades_per_week=5, edge_fraction_per_trade=0.01,
        market_price=0.50, depth_contracts=10.0,
    )
    assert r.feasible is False
    assert r.required_budget_per_trade_usd == float("inf")
    assert "UNREACHABLE at any stake" in r.binding_reason
    # The naive flat-cost stake IS finite and would look perfectly reasonable — which is
    # exactly the false comfort a flat-cost backtest gives.
    assert r.naive_budget_per_trade_usd == pytest.approx(1_000_000.0)
    assert r.max_achievable_weekly_usd < r.weekly_target_usd


def test_invalid_trade_rate_and_target_raise():
    with pytest.raises(ValueError, match="trades_per_week"):
        floor_feasibility(2_000.0, 0, 0.05, 0.50, 1_000.0)
    with pytest.raises(ValueError, match="weekly_target_usd"):
        floor_feasibility(0.0, 10, 0.05, 0.50, 1_000.0)


# --------------------------------------------------------------------------- #
# 6. The cost model is the SAME one the engine uses.                           #
# --------------------------------------------------------------------------- #
def test_flat_cost_matches_the_shared_cost_model_exactly():
    """A capacity curve computed off a different cost model measures nothing. The flat leg
    must be bit-identical to what the backtest and the live executor charge."""
    price = 0.37
    pt = capacity_point(price, 100.0, 1_000.0)
    assert pt.flat_cost_per_contract == DEFAULT_COST_MODEL.effective_buy_price(price)


def test_a_custom_cost_model_is_honoured():
    cm = CostModel(slippage_rate=0.02, fee_rate=0.05)
    pt = capacity_point(0.50, 100.0, 1_000.0, cost_model=cm)
    assert pt.flat_cost_per_contract == cm.effective_buy_price(0.50)
    assert pt.flat_cost_per_contract > DEFAULT_COST_MODEL.effective_buy_price(0.50)


# --------------------------------------------------------------------------- #
# 7. walk_book — MEASURED impact off a real ladder, with no free parameter.    #
# --------------------------------------------------------------------------- #
def test_walk_book_fills_at_the_touch_when_the_touch_is_deep_enough():
    """A small order absorbed entirely by the best level pays ZERO impact — this is the
    common case on a liquid book and the reason a single global impact coefficient
    over-charges the median market."""
    w = walk_book([{"price": 0.20, "size": 10_000.0}, {"price": 0.21, "size": 5_000.0}], 500.0)
    assert w.average_fill_price == pytest.approx(0.20)
    assert w.realized_impact_fraction == pytest.approx(0.0)
    assert w.exhausted_book is False


def test_walk_book_averages_across_levels_it_actually_consumes():
    """500 at 0.20 then 500 at 0.30 must average 0.25 — the arithmetic that makes this a
    measurement rather than a model."""
    w = walk_book([{"price": 0.20, "size": 500.0}, {"price": 0.30, "size": 500.0}], 1_000.0)
    assert w.average_fill_price == pytest.approx(0.25)
    assert w.realized_impact_fraction == pytest.approx(0.25)
    assert w.contracts_filled == pytest.approx(1_000.0)


def test_walk_book_reports_a_partial_fill_rather_than_extrapolating():
    """When the visible ladder runs out, the walk must say so and report what it COULD
    fill. Extrapolating the tail would invent the most expensive part of the order."""
    w = walk_book([{"price": 0.50, "size": 10.0}], 100.0)
    assert w.exhausted_book is True
    assert w.contracts_filled == pytest.approx(10.0)
    assert w.contracts_requested == pytest.approx(100.0)


def test_walk_book_refuses_empty_or_nonpositive_input():
    with pytest.raises(ValueError, match="empty ladder"):
        walk_book([], 10.0)
    with pytest.raises(ValueError, match="contracts"):
        walk_book([{"price": 0.5, "size": 10.0}], 0.0)


def test_implied_coeff_inverts_the_sqrt_model():
    """coeff = realized_impact / sqrt(size/depth). Checked against hand arithmetic:
    realized 0.25, size 1000, depth 4000 -> sqrt(0.25)=0.5 -> coeff 0.5."""
    levels = [{"price": 0.20, "size": 500.0}, {"price": 0.30, "size": 500.0}]
    c = implied_impact_coeff(levels, 1_000.0, 4_000.0)
    assert c == pytest.approx(0.5)


def test_implied_coeff_refuses_a_partial_fill():
    """A partial fill's realized impact UNDERSTATES the true cost of the requested size, so
    inverting it yields a coefficient that is too LOW — wrong in the dangerous direction.
    Returning None is the honest answer."""
    assert implied_impact_coeff([{"price": 0.5, "size": 10.0}], 100.0, 1_000.0) is None


# --------------------------------------------------------------------------- #
# 8. Saturated-impact regime — refuse a ceiling that does not exist.           #
#    (Adversarial-review finding: the module's own worst failure mode.)        #
# --------------------------------------------------------------------------- #
def test_saturated_impact_regime_is_refused_not_reported_as_unlimited_capacity():
    """`impact_fraction` is CLAMPED at 1.0. Past saturation the impacted price plateaus while
    contracts still grow linearly, so drag becomes LINEAR — and an edge above that linear
    slope makes modelled profit grow without bound. The peak search would then return its own
    upper bound dressed up as "the most this signal can EVER earn".

    A reviewer reproduced exactly that at price 0.95 / edge 0.0369: a $1.12bn "peak" and a
    $112m/wk "ceiling". That regime is not exotic — the crossover sits near price 0.965, and
    NearCertaintyStrategy trades above 0.90 with a default min_edge of 0.02.

    Emitting a fabricated unbounded capacity is the precise failure this module exists to
    prevent, so it must be named as a model artifact.
    """
    r = floor_feasibility(
        weekly_target_usd=100.0, trades_per_week=10, edge_fraction_per_trade=0.0369,
        market_price=0.95, depth_contracts=100.0,
    )
    assert r.feasible is False, "an unbounded model artifact must never read as feasible"
    assert "NO CAPACITY CEILING EXISTS" in r.binding_reason
    assert "MODEL ARTIFACT" in r.binding_reason
    # And it must NOT hand back a finite, quotable dollar ceiling.
    assert r.max_achievable_weekly_usd == float("inf")


def test_the_saturation_guard_does_not_fire_in_the_normal_regime():
    """The complement — at a mid price with a modest edge the ordinary peak logic still
    applies, so the guard cannot silently swallow every real answer."""
    r = floor_feasibility(
        weekly_target_usd=100.0, trades_per_week=10, edge_fraction_per_trade=0.03,
        market_price=0.50, depth_contracts=500.0,
    )
    assert "NO CAPACITY CEILING EXISTS" not in r.binding_reason
    assert r.peak_budget_per_trade_usd < float("inf")


def test_walk_book_rejects_a_worst_first_ladder():
    """`touch = levels[0]` is load-bearing. A worst-first ladder silently produced NEGATIVE
    realized impact — "buying more made it cheaper" — contradicting the invariant the sibling
    parametric model enforces. Guarded because this function is public and the named next
    step wires it into the live impact path."""
    with pytest.raises(ValueError, match="best-first"):
        walk_book([{"price": 0.30, "size": 500.0}, {"price": 0.20, "size": 500.0}], 1_000.0)


def test_walk_book_rejects_non_positive_level_sizes():
    """A negative size produced a negative `contracts_filled`, violating the documented
    partial-fill invariant."""
    with pytest.raises(ValueError, match="positive size"):
        walk_book([{"price": 0.50, "size": -10.0}], 5.0)
