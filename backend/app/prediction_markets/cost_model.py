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

from dataclasses import dataclass


# Canonical paper/most-conservative cost rates. These MATCH execution.py's
# _simulate_fill (market-order slippage 0.5%; Polymarket-style fee 2% of notional) so
# the edge/EV calc subtracts exactly the costs the executor will charge.
DEFAULT_SLIPPAGE_RATE = 0.005   # market-order slippage, fraction of price
DEFAULT_FEE_RATE = 0.02         # venue fee, fraction of traded notional


@dataclass(frozen=True)
class CostModel:
    """Realistic per-trade cost parameters for prediction-market fills."""

    slippage_rate: float = DEFAULT_SLIPPAGE_RATE
    fee_rate: float = DEFAULT_FEE_RATE

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


# Module-level default instance (canonical costs).
DEFAULT_COST_MODEL = CostModel()
