"""
Execution modeling for realistic backtesting.

Models:
- Transaction costs (commissions, spreads)
- Market impact / slippage
- Execution constraints
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


@dataclass
class TradeOrder:
    """Represents a trade order."""
    ticker: str
    side: str  # 'buy' or 'sell'
    shares: float
    notional: float  # Dollar value
    price: float
    weight_change: float  # Change in portfolio weight


@dataclass
class ExecutedTrade:
    """Represents an executed trade with costs."""
    ticker: str
    side: str
    shares: float
    notional: float
    price: float
    execution_price: float  # Price after slippage
    transaction_cost: float
    slippage_cost: float
    total_cost: float


class TransactionCostModel:
    """
    Models transaction costs for trades.

    Components:
    1. Fixed/proportional commission
    2. Bid-ask spread cost
    3. Market impact (depends on trade size and liquidity)
    """

    def __init__(
        self,
        commission_bps: float = 10.0,  # 10 bps = 0.10%
        spread_bps: float = 5.0,  # Half-spread
        impact_coefficient: float = 0.1  # Market impact scaling
    ):
        """
        Args:
            commission_bps: Commission in basis points
            spread_bps: Half spread in basis points
            impact_coefficient: Market impact coefficient
        """
        self.commission_rate = commission_bps / 10000.0
        self.spread_rate = spread_bps / 10000.0
        self.impact_coefficient = impact_coefficient

    def estimate_cost(
        self,
        notional: float,
        daily_volume: Optional[float] = None,
        volatility: Optional[float] = None
    ) -> Tuple[float, Dict[str, float]]:
        """
        Estimate total transaction cost.

        Args:
            notional: Trade dollar value
            daily_volume: Average daily dollar volume (optional)
            volatility: Stock volatility (optional)

        Returns:
            Tuple of (total_cost, breakdown_dict)
        """
        # Commission
        commission = notional * self.commission_rate

        # Spread cost
        spread_cost = notional * self.spread_rate

        # Market impact (if volume data available)
        impact_cost = 0.0
        if daily_volume is not None and daily_volume > 0:
            # Square-root market impact model
            participation_rate = notional / daily_volume
            impact_bps = self.impact_coefficient * np.sqrt(participation_rate) * 10000

            # Adjust for volatility
            if volatility is not None:
                impact_bps *= (volatility / 0.20)  # Scale vs 20% vol baseline

            impact_cost = notional * (impact_bps / 10000)

        total = commission + spread_cost + impact_cost

        breakdown = {
            "commission": commission,
            "spread": spread_cost,
            "impact": impact_cost,
            "total": total,
            "total_bps": (total / notional * 10000) if notional > 0 else 0
        }

        return total, breakdown


class ExecutionModel:
    """
    Models trade execution with costs and slippage.

    Used in backtesting to simulate realistic execution.
    """

    def __init__(
        self,
        cost_model: Optional[TransactionCostModel] = None,
        slippage_bps: float = 5.0,
        volatility_impact: bool = True
    ):
        """
        Args:
            cost_model: Transaction cost model
            slippage_bps: Base slippage in basis points
            volatility_impact: Whether to scale slippage by volatility
        """
        self.cost_model = cost_model or TransactionCostModel()
        self.slippage_rate = slippage_bps / 10000.0
        self.volatility_impact = volatility_impact

    def compute_trades(
        self,
        current_weights: pd.Series,
        target_weights: pd.Series,
        portfolio_value: float,
        prices: pd.Series
    ) -> List[TradeOrder]:
        """
        Compute trades needed to move from current to target weights.

        Args:
            current_weights: Current portfolio weights
            target_weights: Target portfolio weights
            portfolio_value: Total portfolio value
            prices: Current prices for each ticker

        Returns:
            List of TradeOrder objects
        """
        # Align indices
        all_tickers = set(current_weights.index) | set(target_weights.index)
        current = current_weights.reindex(all_tickers).fillna(0)
        target = target_weights.reindex(all_tickers).fillna(0)

        trades = []
        for ticker in all_tickers:
            weight_change = target[ticker] - current[ticker]

            if abs(weight_change) < 0.001:  # Skip tiny changes
                continue

            if ticker not in prices.index:
                logger.warning(f"No price for {ticker}, skipping trade")
                continue

            price = prices[ticker]
            notional = abs(weight_change) * portfolio_value
            shares = notional / price

            trade = TradeOrder(
                ticker=ticker,
                side="buy" if weight_change > 0 else "sell",
                shares=shares,
                notional=notional,
                price=price,
                weight_change=weight_change
            )
            trades.append(trade)

        return trades

    def execute_trades(
        self,
        trades: List[TradeOrder],
        volumes: Optional[pd.Series] = None,
        volatilities: Optional[pd.Series] = None,
        random_seed: Optional[int] = None
    ) -> Tuple[List[ExecutedTrade], float]:
        """
        Simulate trade execution with costs and slippage.

        Args:
            trades: List of trade orders
            volumes: Average daily dollar volumes
            volatilities: Stock volatilities
            random_seed: Random seed for slippage simulation

        Returns:
            Tuple of (executed_trades, total_cost)
        """
        if random_seed is not None:
            np.random.seed(random_seed)

        executed = []
        total_cost = 0.0

        for trade in trades:
            # Get volume and volatility if available
            volume = volumes[trade.ticker] if volumes is not None and trade.ticker in volumes else None
            vol = volatilities[trade.ticker] if volatilities is not None and trade.ticker in volatilities else 0.20

            # Compute slippage
            slippage_rate = self.slippage_rate
            if self.volatility_impact and vol:
                slippage_rate *= (vol / 0.20)  # Scale vs 20% baseline

            # Add some randomness to slippage
            slippage_rate *= (1 + np.random.uniform(-0.3, 0.3))

            # Slippage direction: buy = pay more, sell = receive less
            if trade.side == "buy":
                execution_price = trade.price * (1 + slippage_rate)
            else:
                execution_price = trade.price * (1 - slippage_rate)

            slippage_cost = abs(execution_price - trade.price) * trade.shares

            # Transaction cost
            tx_cost, _ = self.cost_model.estimate_cost(trade.notional, volume, vol)

            total_trade_cost = tx_cost + slippage_cost
            total_cost += total_trade_cost

            executed.append(ExecutedTrade(
                ticker=trade.ticker,
                side=trade.side,
                shares=trade.shares,
                notional=trade.notional,
                price=trade.price,
                execution_price=execution_price,
                transaction_cost=tx_cost,
                slippage_cost=slippage_cost,
                total_cost=total_trade_cost
            ))

        return executed, total_cost

    def estimate_turnover_cost(
        self,
        current_weights: pd.Series,
        target_weights: pd.Series,
        portfolio_value: float
    ) -> Tuple[float, float]:
        """
        Estimate cost of rebalancing without executing.

        Returns:
            Tuple of (turnover_pct, estimated_cost)
        """
        # Align indices
        all_tickers = set(current_weights.index) | set(target_weights.index)
        current = current_weights.reindex(all_tickers).fillna(0)
        target = target_weights.reindex(all_tickers).fillna(0)

        # Total turnover (sum of absolute weight changes)
        turnover = (target - current).abs().sum() / 2  # Divide by 2 since buys = sells

        # Estimate cost as simple bps
        total_cost_bps = (self.cost_model.commission_rate + self.slippage_rate) * 10000
        estimated_cost = turnover * portfolio_value * (total_cost_bps / 10000)

        return turnover, estimated_cost

    def generate_trade_summary(
        self,
        executed_trades: List[ExecutedTrade]
    ) -> Dict:
        """Generate summary statistics for executed trades."""
        if not executed_trades:
            return {
                "n_trades": 0,
                "total_notional": 0,
                "total_cost": 0,
                "avg_cost_bps": 0,
            }

        n_trades = len(executed_trades)
        total_notional = sum(t.notional for t in executed_trades)
        total_cost = sum(t.total_cost for t in executed_trades)
        avg_cost_bps = (total_cost / total_notional * 10000) if total_notional > 0 else 0

        buys = [t for t in executed_trades if t.side == "buy"]
        sells = [t for t in executed_trades if t.side == "sell"]

        return {
            "n_trades": n_trades,
            "n_buys": len(buys),
            "n_sells": len(sells),
            "total_notional": total_notional,
            "buy_notional": sum(t.notional for t in buys),
            "sell_notional": sum(t.notional for t in sells),
            "total_cost": total_cost,
            "avg_cost_bps": avg_cost_bps,
            "commission_cost": sum(t.transaction_cost for t in executed_trades),
            "slippage_cost": sum(t.slippage_cost for t in executed_trades),
        }
