"""
Integration of statistical arbitrage strategies with main trading system.

This module connects stat arb engines to:
- Portfolio optimizer for position sizing
- Risk manager for hedge ratio validation
- Execution system for pairs trading

Usage:
    stat_arb = create_stat_arb_system(prices, sectors)
    recommendations = stat_arb.get_recommendations()
    positions = stat_arb.generate_positions(capital=100000)
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import numpy as np
import pandas as pd
import logging

from .stat_arb_engine import StatArbEngine, PairSignal

logger = logging.getLogger(__name__)


class StatArbPortfolioManager:
    """
    Manages stat arb positions as portfolio-level allocations.

    Converts pair signals into coordinated long-short positions:
    - Long-short position in ratio specified by hedge ratio
    - Position sizing based on volatility and capital allocation
    - Correlation limits between hedge pairs
    """

    def __init__(
        self,
        capital: float = 100_000,
        max_pairs_active: int = 10,
        capital_per_pair: float = 10_000,
        leverage: float = 1.0,
    ):
        """
        Initialize portfolio manager.

        Args:
            capital: Total capital available
            max_pairs_active: Maximum concurrent pairs trades
            capital_per_pair: Capital allocated per pair
            leverage: Leverage for positions (1.0 = no leverage)
        """
        self.capital = capital
        self.max_pairs_active = max_pairs_active
        self.capital_per_pair = capital_per_pair
        self.leverage = leverage
        self.active_positions: Dict[str, Dict] = {}

    def size_pair_position(
        self,
        pair_signal: PairSignal,
        available_capital: float
    ) -> Tuple[float, float]:
        """
        Size a pair position based on capital and volatility.

        Args:
            pair_signal: Pair signal with volatility estimate
            available_capital: Capital available for this position

        Returns:
            (size_a, size_b) in dollars
        """
        # Allocate capital to this pair
        pair_capital = min(self.capital_per_pair, available_capital)

        # Adjust for position volatility (lower vol = larger position)
        vol_target = 0.15  # Target 15% annual vol
        if pair_signal.expected_volatility > 0:
            vol_scaling = vol_target / pair_signal.expected_volatility
            vol_scaling = np.clip(vol_scaling, 0.5, 2.0)  # Limit scaling
            pair_capital *= vol_scaling

        # Size based on hedge ratio
        # If hedge_ratio = 1.5, then for each $X in B, we need $1.5X in A
        hedge_ratio = pair_signal.position_ratio_a_to_b

        # Half of capital in A, half in B (by hedge-adjusted value)
        size_b = pair_capital * 0.5 / (1 + hedge_ratio)
        size_a = size_b * hedge_ratio

        return size_a, size_b

    def generate_position_orders(
        self,
        pair_signals: List[PairSignal],
        current_positions: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict]:
        """
        Generate execution orders for pair positions.

        Args:
            pair_signals: Signals from stat arb engine
            current_positions: Current open positions

        Returns:
            List of order dicts with {symbol, side, size, pair_id}
        """
        orders = []
        current_positions = current_positions or {}

        # Filter to actionable signals
        actionable = [
            s for s in pair_signals
            if s.action in ["BUY_A_SELL_B", "SELL_A_BUY_B"]
        ]

        # Sort by confidence
        actionable.sort(key=lambda x: x.confidence, reverse=True)

        # Take top N pairs
        active_pairs = actionable[:self.max_pairs_active]

        available_capital = self.capital
        for pair_signal in active_pairs:
            pair_id = f"{pair_signal.symbol_a}_{pair_signal.symbol_b}"

            # Size position
            size_a, size_b = self.size_pair_position(pair_signal, available_capital)
            available_capital -= (size_a + size_b)

            if pair_signal.action == "BUY_A_SELL_B":
                # Long A, short B
                orders.append({
                    "pair_id": pair_id,
                    "symbol": pair_signal.symbol_a,
                    "side": "BUY",
                    "size": size_a / 100,  # Assume price ~100
                    "confidence": pair_signal.confidence,
                })
                orders.append({
                    "pair_id": pair_id,
                    "symbol": pair_signal.symbol_b,
                    "side": "SELL",
                    "size": size_b / 100,
                    "confidence": pair_signal.confidence,
                })

            elif pair_signal.action == "SELL_A_BUY_B":
                # Short A, long B
                orders.append({
                    "pair_id": pair_id,
                    "symbol": pair_signal.symbol_a,
                    "side": "SELL",
                    "size": size_a / 100,
                    "confidence": pair_signal.confidence,
                })
                orders.append({
                    "pair_id": pair_id,
                    "symbol": pair_signal.symbol_b,
                    "side": "BUY",
                    "size": size_b / 100,
                    "confidence": pair_signal.confidence,
                })

        # Generate close orders for stopped pairs
        for pair_id, position in current_positions.items():
            if pair_id not in [o["pair_id"] for o in orders if "pair_id" in o]:
                # Pair no longer recommended, close it
                if position.get("side_a") == "BUY":
                    orders.append({
                        "pair_id": pair_id,
                        "symbol": position["symbol_a"],
                        "side": "SELL",
                        "size": position["size_a"],
                        "type": "CLOSE",
                    })
                elif position.get("side_a") == "SELL":
                    orders.append({
                        "pair_id": pair_id,
                        "symbol": position["symbol_a"],
                        "side": "BUY",
                        "size": position["size_a"],
                        "type": "CLOSE",
                    })

                if position.get("side_b") == "BUY":
                    orders.append({
                        "pair_id": pair_id,
                        "symbol": position["symbol_b"],
                        "side": "SELL",
                        "size": position["size_b"],
                        "type": "CLOSE",
                    })
                elif position.get("side_b") == "SELL":
                    orders.append({
                        "pair_id": pair_id,
                        "symbol": position["symbol_b"],
                        "side": "BUY",
                        "size": position["size_b"],
                        "type": "CLOSE",
                    })

        return orders

    def validate_correlation_limits(
        self,
        pair_signals: List[PairSignal],
        prices: pd.DataFrame,
        max_correlation: float = 0.80,
    ) -> List[PairSignal]:
        """
        Filter pairs to ensure they're uncorrelated (reduce portfolio correlation).

        Args:
            pair_signals: Candidate pairs
            prices: Price data for correlation calculation
            max_correlation: Maximum allowed correlation between legs

        Returns:
            Filtered list of non-correlated pairs
        """
        filtered = []

        for signal in pair_signals:
            try:
                # Get price returns
                ret_a = prices[signal.symbol_a].pct_change().dropna().iloc[-60:]
                ret_b = prices[signal.symbol_b].pct_change().dropna().iloc[-60:]

                if len(ret_a) < 30 or len(ret_b) < 30:
                    filtered.append(signal)
                    continue

                # Correlation between A and B returns
                corr = ret_a.corr(ret_b)

                # Acceptable if correlation is low (pairs should be independent)
                if abs(corr) <= max_correlation:
                    filtered.append(signal)
                else:
                    logger.info(
                        f"Filtering pair {signal.symbol_a}-{signal.symbol_b} "
                        f"due to high correlation: {corr:.3f}"
                    )

            except Exception as e:
                logger.warning(f"Error validating pair correlation: {e}")
                filtered.append(signal)

        return filtered


class StatArbMetrics:
    """Compute performance metrics for stat arb strategies."""

    @staticmethod
    def compute_pair_pnl(
        entry_price_a: float,
        entry_price_b: float,
        current_price_a: float,
        current_price_b: float,
        size_a: float,
        size_b: float,
        side_a: str,  # BUY or SELL
        side_b: str,
    ) -> float:
        """
        Compute P&L for a pair position.

        Args:
            entry_price_a, entry_price_b: Entry prices
            current_price_a, current_price_b: Current prices
            size_a, size_b: Position sizes
            side_a, side_b: Position sides

        Returns:
            P&L in dollars
        """
        # Leg A P&L
        if side_a == "BUY":
            pnl_a = (current_price_a - entry_price_a) * size_a
        else:
            pnl_a = (entry_price_a - current_price_a) * size_a

        # Leg B P&L
        if side_b == "BUY":
            pnl_b = (current_price_b - entry_price_b) * size_b
        else:
            pnl_b = (entry_price_b - current_price_b) * size_b

        return pnl_a + pnl_b

    @staticmethod
    def portfolio_hedge_ratio(
        pair_signals: List[PairSignal]
    ) -> Dict[str, float]:
        """
        Compute overall portfolio hedge ratios.

        Returns:
            Dict of long_exposure -> short_exposure ratio
        """
        long_exposure = 0
        short_exposure = 0

        for signal in pair_signals:
            if signal.action == "BUY_A_SELL_B":
                long_exposure += 1
                short_exposure += signal.position_ratio_a_to_b
            elif signal.action == "SELL_A_BUY_B":
                short_exposure += 1
                long_exposure += signal.position_ratio_a_to_b

        hedge_ratio = long_exposure / (short_exposure + 1e-10)

        return {
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
            "hedge_ratio": hedge_ratio,
        }


def create_stat_arb_system(
    prices: pd.DataFrame,
    sectors: Optional[Dict[str, str]] = None,
    capital: float = 100_000,
    max_pairs: int = 10,
) -> Tuple[StatArbEngine, StatArbPortfolioManager]:
    """
    Factory function to create and initialize stat arb system.

    Args:
        prices: Price data
        sectors: Optional sector mapping
        capital: Total capital
        max_pairs: Max concurrent pairs

    Returns:
        (engine, portfolio_manager)
    """
    engine = StatArbEngine(
        lookback_days=252,
        use_pairs_trading=True,
        use_correlation_arb=False,
        pairs_per_strategy=30,
    )

    manager = StatArbPortfolioManager(
        capital=capital,
        max_pairs_active=max_pairs,
        capital_per_pair=capital / max_pairs,
        leverage=1.0,
    )

    return engine, manager
