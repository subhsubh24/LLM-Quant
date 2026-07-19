"""
cost_model.py — the single source of truth for prediction-market trading costs.

WHY THIS EXISTS (ROADMAP C2 — realistic cost model):
The Kelly sizing in ``orchestrator.py`` previously sized on the GROSS edge
(``win_probability - market_price``), ignoring the fees + slippage that the executor
actually charges on every fill. That is a systematic OVER-BETTING and OVER-TRADING
bug: a contract bought at price ``c`` does not cost ``c`` — it costs
``c * (1 + slippage) * (1 + fee_rate)`` once the executor's market-order slippage and
the venue fee are applied (see ``execution.py::_simulate_fill``). Sizing on gross edge
both (a) bets more than full-Kelly on real (net) odds and (b) takes trades whose gross
edge is positive but whose NET edge — after costs — is zero or negative.

This module computes the **cost-inclusive effective price** and the **net-of-cost
edge**, so the EV/Kelly math is honest: a trade is only taken (and only sized) on the
edge that survives realistic costs. Keeping the rates here, in one place, means the
backtest, paper sizing, and (later) the live EV all subtract the SAME costs — a
prerequisite for the realized-vs-backtest reconciliation in the learning loop (VISION).

The default rates mirror the executor's current paper-fill costs so that EV and
realized PnL stay consistent (a divergence would otherwise read as false overfit). When
the real venue fee schedule / order-book depth is wired, update these in ONE place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# Canonical paper/most-conservative cost rates. These MATCH execution.py's
# _simulate_fill (market-order slippage 0.5%; Polymarket-style fee 2% of notional) so
# the edge/EV calc subtracts exactly the costs the executor will charge.
DEFAULT_SLIPPAGE_RATE = 0.005   # market-order slippage, fraction of price
DEFAULT_FEE_RATE = 0.02         # venue fee, fraction of traded notional

# Default market-impact coefficient for the depth/order-book model (see
# CostModel.effective_buy_price_with_impact). This is a SIMPLIFIED, NOT-CALIBRATED
# parameter: at impact_coeff = 0.5, an order equal to the visible depth (size == depth)
# pays an extra ~50% (sqrt mode) of the slipped price as impact before the cap. It is
# deliberately CONSERVATIVE (over-states cost when depth is uncertain) — the safe
# direction for capacity claims. Tune in ONE place when real book depth is wired.
DEFAULT_IMPACT_COEFF = 0.5
# Hard cap on the impact fraction so a pathological size/depth ratio cannot push the
# all-in cost arbitrarily high; the per-contract price is independently capped at 1.0.
DEFAULT_MAX_IMPACT_FRACTION = 1.0
# Floor on depth to keep the size/depth ratio finite when depth -> 0.
_DEPTH_EPS = 1e-9


@dataclass(frozen=True)
class CostModel:
    """Realistic per-trade cost parameters for prediction-market fills."""

    slippage_rate: float = DEFAULT_SLIPPAGE_RATE
    fee_rate: float = DEFAULT_FEE_RATE
    # SIMPLIFIED order-book-depth / market-impact coefficient. Defaulted so existing
    # ``CostModel()`` construction, ``DEFAULT_COST_MODEL``, and frozen-dataclass
    # equality/hash are all unchanged for callers that never set it. Used ONLY by the
    # *_with_impact methods below; the flat-rate path (effective_buy_price / net_edge /
    # contracts_for_budget) ignores it entirely, so existing behavior is BIT-IDENTICAL.
    impact_coeff: float = DEFAULT_IMPACT_COEFF

    def effective_buy_price(self, market_price: float) -> float:
        """All-in cost per YES contract when buying at ``market_price``.

        Applies market-order slippage (price moves against us) and the venue fee on the
        traded notional. The result is the true cost basis used for honest EV/Kelly:
        on a win the contract pays $1, so the net odds are ``(1 - c_eff) / c_eff``.
        """
        slipped = market_price * (1.0 + self.slippage_rate)
        c_eff = slipped * (1.0 + self.fee_rate)
        # A contract whose all-in cost is >= $1 has no possible profit (it pays at most
        # $1). Cap at exactly 1.0 (breakeven), NOT just below it — capping below would
        # understate the cost and report an optimistic (slightly positive) edge in the
        # near-certain regime. At 1.0, net_edge = p - 1.0 < 0 for any p < 1, so such a
        # contract is correctly never sized. Floor above 0 to keep odds finite.
        return min(max(c_eff, 1e-6), 1.0)

    def net_edge(self, win_probability: float, market_price: float) -> float:
        """Edge net of costs, in price units: ``win_probability - effective_cost``.

        This is what the Kelly sizer and the ``min_edge`` filter should screen on. A
        trade whose GROSS edge (``win_probability - market_price``) is positive but
        whose net edge is <= 0 is a losing trade after costs and must be skipped.
        """
        return win_probability - self.effective_buy_price(market_price)

    def effective_sell_price(self, market_price: float) -> float:
        """All-in PROCEEDS per contract when SELLING (closing a position) at ``market_price``.

        The exit analogue of ``effective_buy_price``. Selling a market order also pays the
        cost of crossing the spread — slippage moves the fill AGAINST us (down, on a sale) —
        and the venue fee is taken out of the notional we receive. So a contract sold at
        quoted price ``p`` returns ``p * (1 - slippage) * (1 - fee)``, NOT ``p``. This is the
        symmetric friction to the buy leg: ``effective_buy_price`` charges ``+slippage``/
        ``+fee`` on entry; this charges ``-slippage``/``-fee`` on exit. A round-trip
        (buy then sell at an UNCHANGED price) therefore books a LOSS equal to the two-way
        cost — the honest hurdle any short-horizon mark-to-market strategy must clear before
        it can be called an edge (fade-the-spike, spread capture, any exit-before-resolution).

        Floored at 0.0 (proceeds cannot be negative) and capped at 1.0 (a contract is worth
        at most $1 at resolution, so it can never be sold for more than par). At ``p = 0`` the
        proceeds are 0; the result is continuous and monotone non-decreasing in ``p``.
        """
        deslipped = market_price * (1.0 - self.slippage_rate)
        proceeds = deslipped * (1.0 - self.fee_rate)
        # Clamp into [0, 1]: proceeds are never negative and never exceed par ($1). Unlike the
        # BUY cap (which pins the near-certain cost at exactly breakeven 1.0 to avoid optimism),
        # the SELL floor at 0.0 is the conservative direction — it never overstates proceeds.
        return min(max(proceeds, 0.0), 1.0)

    def contracts_for_budget(self, budget_usd: float, market_price: float) -> float:
        """How many contracts ``budget_usd`` actually buys, costs included.

        ``budget_usd`` is the capital we intend to deploy. Because the executor charges
        slippage + fee, the real number of contracts is ``budget / effective_cost`` —
        NOT ``budget / market_price`` (which would overstate the position and cause us
        to deploy more cash than intended).
        """
        c_eff = self.effective_buy_price(market_price)
        if c_eff <= 0:
            return 0.0
        return budget_usd / c_eff

    # -----------------------------------------------------------------------
    # SIMPLIFIED order-book-depth / market-impact model (ROADMAP C2/C3)
    # -----------------------------------------------------------------------
    # WHY: the flat slippage above is a single fixed fraction regardless of how big the
    # order is relative to the book. That UNDERSTATES cost for a large order in a thin
    # market — exactly the "near-certainty NO books are illiquid" regime an auditor
    # flagged, where a marginal positive net edge is really erased by the impact of
    # walking a shallow book. This adds a size/depth-aware ADD-ON on top of the flat
    # rate. It is a TOY model (not calibrated to real books): we approximate walking the
    # book to progressively worse prices by a closed-form impact fraction that GROWS with
    # the order's size relative to visible depth. Real ``polymarket_client.OrderBook``
    # depth can feed ``depth_contracts`` later; until then this is intentionally
    # CONSERVATIVE (over-states cost when depth is uncertain) — the safe direction for
    # capacity / edge-survival claims.
    def impact_fraction(
        self,
        order_size_contracts: float,
        depth_contracts: Optional[float],
        impact_coeff: Optional[float] = None,
    ) -> float:
        """Extra slippage fraction (of the slipped price) from walking a finite book.

        Model: ``impact = impact_coeff * sqrt(size / depth)``, clamped to
        ``[0, DEFAULT_MAX_IMPACT_FRACTION]``. Sqrt (concave) impact is the standard
        conservative shape — impact per unit size grows sublinearly, matching that the
        first contracts hit the best quotes and only a large sweep reaches deep levels.

        Continuity to the flat rate: as ``depth_contracts -> infinity`` (a very deep book
        relative to the order) the ratio ``size/depth -> 0`` so ``impact -> 0`` smoothly,
        with NO discontinuity — the all-in price reduces continuously to the flat
        ``effective_buy_price``. ``depth=None`` is treated as "unknown/infinite depth" and
        returns 0 impact (flat behavior), so liquidity-less callers are unchanged.

        It is always >= 0, so impact can only ADD cost, never reduce it.
        """
        if depth_contracts is None:
            return 0.0
        if order_size_contracts <= 0.0:
            return 0.0
        coeff = self.impact_coeff if impact_coeff is None else impact_coeff
        if coeff <= 0.0:
            return 0.0
        ratio = order_size_contracts / max(depth_contracts, _DEPTH_EPS)
        frac = coeff * math.sqrt(max(ratio, 0.0))
        # Clamp into [0, max] — monotone non-decreasing in size up to the cap, then flat.
        return min(max(frac, 0.0), DEFAULT_MAX_IMPACT_FRACTION)

    def effective_buy_price_with_impact(
        self,
        market_price: float,
        order_size_contracts: float,
        depth_contracts: Optional[float],
        impact_coeff: Optional[float] = None,
    ) -> float:
        """All-in cost per contract INCLUDING size/depth market impact.

        Built strictly ON TOP of the flat ``effective_buy_price`` so that flat price is a
        hard FLOOR: the impact term only ever adds. Concretely, impact is applied to the
        slipped price (price after flat slippage) and added on, then the venue fee is
        applied to the impacted notional, and the result is capped at $1.0 (breakeven)
        exactly like the flat path. When ``depth_contracts`` is None or huge relative to
        the order, impact -> 0 and this returns exactly the flat ``effective_buy_price``
        (no discontinuity).
        """
        flat = self.effective_buy_price(market_price)
        impact = self.impact_fraction(order_size_contracts, depth_contracts, impact_coeff)
        if impact <= 0.0:
            return flat
        slipped = market_price * (1.0 + self.slippage_rate)
        impacted = slipped * (1.0 + impact)
        c_eff = impacted * (1.0 + self.fee_rate)
        # Floor at the flat all-in price (never reduce below it) and cap at 1.0 (breakeven),
        # matching effective_buy_price's no-optimism cap.
        return min(max(c_eff, flat), 1.0)

    def net_edge_with_impact(
        self,
        win_probability: float,
        market_price: float,
        order_size_contracts: float,
        depth_contracts: Optional[float],
        impact_coeff: Optional[float] = None,
    ) -> float:
        """Edge net of costs INCLUDING market impact: ``win_probability - impacted_cost``.

        The size-aware analogue of ``net_edge``. A marginal positive net edge can flip
        NEGATIVE here once a large order in a thin book pays realistic impact — the
        intended guard against over-stating capacity in illiquid near-certainty books.
        """
        return win_probability - self.effective_buy_price_with_impact(
            market_price, order_size_contracts, depth_contracts, impact_coeff
        )


# Module-level default instance (canonical costs).
DEFAULT_COST_MODEL = CostModel()
