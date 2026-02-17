"""
Smart Order Execution Engine

Intelligent execution with realistic market impact modeling:
- VWAP (Volume Weighted Average Price) execution
- TWAP (Time Weighted Average Price) execution
- Smart order routing
- Market impact estimation
- Execution cost modeling

This ensures realistic execution costs in backtesting:
- Commission: 1-2 bps
- Spread: 2-10 bps (varies by size/liquidity)
- Market impact: 1-5 bps (varies by size/volatility)
- Total cost target: 8-15 bps for medium-sized orders

References:
- Almgren & Chriss (2001) "Optimal Execution of Portfolio Transactions"
- Gatheral (2010) "The Volatility Surface"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order execution type."""
    MARKET = "market"
    LIMIT = "limit"
    VWAP = "vwap"
    TWAP = "twap"
    SMART_ORDER = "smart_order"


class OrderSide(Enum):
    """Buy or sell."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class ExecutionParameters:
    """Execution algorithm parameters."""
    order_type: OrderType = OrderType.SMART_ORDER
    commission_bps: float = 1.0  # Basis points
    spread_bps: float = 5.0  # Estimated spread
    max_participation_rate: float = 0.10  # Max 10% of daily volume
    urgency: float = 0.5  # 0 = patient, 1.0 = urgent
    time_horizon_minutes: int = 60  # Execution window
    slippage_bps: float = 2.0  # Per-unit slippage


@dataclass
class MarketData:
    """Current market snapshot."""
    price: float
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float
    daily_volume: float
    volatility: float  # Annualized
    bid_ask_spread: float = 0.0

    def __post_init__(self):
        """Calculate spread if not provided."""
        if self.bid_ask_spread == 0 and self.bid > 0 and self.ask > 0:
            self.bid_ask_spread = (self.ask - self.bid) / self.price if self.price > 0 else 0


@dataclass
class ExecutionResult:
    """Result of order execution."""
    symbol: str
    side: OrderSide
    quantity: float
    avg_execution_price: float
    total_cost: float
    commission_cost: float
    market_impact_cost: float
    spread_cost: float
    execution_time_minutes: float = 0
    executed_at: datetime = field(default_factory=datetime.now)


class MarketImpactModel:
    """Estimate market impact from order size."""

    def __init__(self):
        """Initialize."""
        self.alpha = 1.5  # Impact parameter (increased for realistic market impact)
        self.beta = 1.5  # Impact exponent

    def estimate_impact(
        self,
        quantity: float,
        daily_volume: float,
        volatility: float,
    ) -> float:
        """
        Estimate market impact as percentage.

        Uses Almgren-Chriss model:
        impact = alpha * (Q/V)^beta * volatility

        Where:
        - Q = order quantity
        - V = daily volume
        - volatility = daily volatility
        """
        if daily_volume <= 0:
            return 0.01  # Conservative default 100 bps

        participation_rate = quantity / daily_volume
        participation_rate = min(participation_rate, 0.5)  # Cap at 50%

        # Impact calculation
        impact = self.alpha * (participation_rate ** self.beta) * volatility

        return impact


class ExecutionAlgorithm:
    """Base execution algorithm."""

    def execute(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
        params: ExecutionParameters,
    ) -> ExecutionResult:
        """Execute order. Override in subclasses."""
        raise NotImplementedError


class VWAPExecutor(ExecutionAlgorithm):
    """
    Volume Weighted Average Price execution.

    Participates proportionally to expected volume throughout the day.
    Best for: non-urgent orders, medium-sized positions.
    """

    def execute(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
        params: ExecutionParameters,
        historical_volumes: Optional[List[float]] = None,
    ) -> ExecutionResult:
        """
        Execute using VWAP algorithm.

        Participate at expected volume profile throughout day.
        """
        # Estimate average execution price
        # CRITICAL BUG FIX #6: spread_cost and impact_cost are fractions, need to multiply by price
        spread_cost = market_data.price * market_data.bid_ask_spread / 2
        avg_price = market_data.price + (spread_cost if quantity > 0 else -spread_cost)

        # Market impact estimation
        impact_model = MarketImpactModel()
        impact_cost_fraction = impact_model.estimate_impact(
            quantity,
            market_data.daily_volume,
            market_data.volatility,
        )
        # Convert fraction to dollar amount
        impact_cost = market_data.price * impact_cost_fraction
        avg_price += impact_cost if quantity > 0 else -impact_cost

        # Commission
        commission = (market_data.price * params.commission_bps / 10_000) * abs(quantity)

        # Total execution cost
        total_cost = abs(quantity) * (avg_price - market_data.price)

        return ExecutionResult(
            symbol=symbol,
            side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
            quantity=quantity,
            avg_execution_price=avg_price,
            total_cost=total_cost,
            commission_cost=commission,
            market_impact_cost=abs(quantity) * impact_cost,
            spread_cost=abs(quantity) * spread_cost,
            execution_time_minutes=params.time_horizon_minutes,
        )


class TWAPExecutor(ExecutionAlgorithm):
    """
    Time Weighted Average Price execution.

    Participates evenly over time horizon.
    Best for: urgent orders, breakout situations.
    """

    def execute(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
        params: ExecutionParameters,
    ) -> ExecutionResult:
        """Execute using TWAP algorithm."""
        # Similar to VWAP but assumes even volume distribution over time
        # CRITICAL BUG FIX #6: spread_cost is fraction, convert to dollars
        spread_cost = market_data.price * market_data.bid_ask_spread / 2
        avg_price = market_data.price + (spread_cost if quantity > 0 else -spread_cost)

        # Market impact (faster execution = higher impact)
        impact_model = MarketImpactModel()
        impact_cost_fraction = impact_model.estimate_impact(
            quantity,
            market_data.daily_volume,
            market_data.volatility,
        ) * 1.2  # 20% higher impact for TWAP (faster execution)
        # Convert fraction to dollars
        impact_cost = market_data.price * impact_cost_fraction
        avg_price += impact_cost if quantity > 0 else -impact_cost

        # Commission
        commission = (market_data.price * params.commission_bps / 10_000) * abs(quantity)

        # Total cost
        total_cost = abs(quantity) * (avg_price - market_data.price)

        return ExecutionResult(
            symbol=symbol,
            side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
            quantity=quantity,
            avg_execution_price=avg_price,
            total_cost=total_cost,
            commission_cost=commission,
            market_impact_cost=abs(quantity) * impact_cost,
            spread_cost=abs(quantity) * spread_cost,
            execution_time_minutes=params.time_horizon_minutes / 2,  # Faster than VWAP
        )


class SmartOrderExecutor(ExecutionAlgorithm):
    """
    Smart Order Routing - adaptively selects execution strategy.

    Chooses between VWAP, TWAP, or market orders based on:
    - Order size relative to daily volume
    - Urgency
    - Current market conditions
    """

    def __init__(self):
        """Initialize."""
        self.vwap = VWAPExecutor()
        self.twap = TWAPExecutor()

    def execute(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
        params: ExecutionParameters,
    ) -> ExecutionResult:
        """
        Smart routing: select best execution strategy.

        Decision logic:
        - Small order (< 2% daily vol): market order
        - Medium order (2-10% daily vol): VWAP
        - Large order (> 10% daily vol): TWAP
        - Urgent (urgency > 0.7): TWAP
        """
        # FIX #8: Add epsilon guard for division by zero
        participation_rate = abs(quantity) / max(market_data.daily_volume, 1e-8)

        # Route decision
        if participation_rate < 0.02:
            # Small order - execute quickly
            return self._execute_market_order(
                symbol, quantity, market_data, params
            )
        elif params.urgency > 0.7:
            # Urgent - use TWAP
            return self.twap.execute(symbol, quantity, market_data, params)
        elif participation_rate > 0.1:
            # Large order - use TWAP for patience
            return self.twap.execute(symbol, quantity, market_data, params)
        else:
            # Medium order - use VWAP (balanced)
            return self.vwap.execute(symbol, quantity, market_data, params)

    @staticmethod
    def _execute_market_order(
        symbol: str,
        quantity: float,
        market_data: MarketData,
        params: ExecutionParameters,
    ) -> ExecutionResult:
        """Execute market order."""
        # Use midpoint + small spread
        avg_price = market_data.price
        # FIX #8: Convert spread from fraction to dollar amount
        spread_cost = market_data.price * market_data.bid_ask_spread / 2

        avg_price += spread_cost if quantity > 0 else -spread_cost

        # Commission only
        commission = (market_data.price * params.commission_bps / 10_000) * abs(quantity)

        # Total cost
        total_cost = abs(quantity) * (avg_price - market_data.price)

        return ExecutionResult(
            symbol=symbol,
            side=OrderSide.BUY if quantity > 0 else OrderSide.SELL,
            quantity=quantity,
            avg_execution_price=avg_price,
            total_cost=total_cost,
            commission_cost=commission,
            market_impact_cost=0,  # Minimal impact for small orders
            spread_cost=abs(quantity) * spread_cost,
            execution_time_minutes=1,  # Quick execution
        )


class ExecutionCostAnalyzer:
    """Analyze execution costs and efficiency."""

    def __init__(self):
        """Initialize."""
        self.execution_history: List[ExecutionResult] = []

    def record_execution(self, result: ExecutionResult) -> None:
        """Record execution result."""
        self.execution_history.append(result)

    def get_average_execution_cost_bps(self) -> float:
        """Get average execution cost in basis points."""
        if not self.execution_history:
            return 0

        total_cost = 0
        total_notional = 0

        for result in self.execution_history:
            total_cost += abs(result.total_cost)
            total_notional += result.quantity * result.avg_execution_price

        if total_notional == 0:
            return 0

        cost_pct = total_cost / total_notional
        return cost_pct * 10_000  # Convert to basis points

    def get_slippage_bps(self) -> float:
        """Get average slippage (vs bid/ask) in basis points."""
        if not self.execution_history:
            return 0

        slippages = []
        for result in self.execution_history:
            # FIX #4: Slippage is the spread cost relative to notional value (not abs/relative price)
            # Spread cost is the difference between execution price and mid-price
            notional = result.quantity * result.avg_execution_price
            if notional > 1e-8:
                # Convert spread cost to basis points
                slippage_bps = (result.spread_cost / notional) * 10_000
                slippages.append(slippage_bps)

        return np.mean(slippages) if slippages else 0

    def get_summary(self) -> Dict[str, float]:
        """Get execution cost summary."""
        if not self.execution_history:
            return {}

        avg_cost_bps = self.get_average_execution_cost_bps()

        # Breakdown
        total_commission = sum(r.commission_cost for r in self.execution_history)
        total_impact = sum(r.market_impact_cost for r in self.execution_history)
        total_spread = sum(r.spread_cost for r in self.execution_history)
        total_cost = sum(r.total_cost for r in self.execution_history)

        return {
            "total_executions": len(self.execution_history),
            "avg_cost_bps": avg_cost_bps,
            "commission_bps": (
                total_commission / (total_cost + 1e-10) * 10_000
                if total_cost > 0
                else 0
            ),
            "market_impact_bps": (
                total_impact / (total_cost + 1e-10) * 10_000 if total_cost > 0 else 0
            ),
            "spread_bps": (
                total_spread / (total_cost + 1e-10) * 10_000 if total_cost > 0 else 0
            ),
            "total_cost": total_cost,
        }
