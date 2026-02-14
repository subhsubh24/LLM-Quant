"""
Paper Trading System - Live Simulation

Implements a realistic paper trading environment:
- Daily signal generation from all 3 sources (signals, arb, ensemble)
- Real-time portfolio updates
- Trade execution with realistic costs
- Risk control integration
- Performance monitoring
- Results persistence

This is the main entry point for live paper trading validation.

The paper trader:
1. Pulls market data (daily)
2. Generates signals (all sources)
3. Checks risk controls
4. Executes trades (with realistic costs)
5. Updates performance metrics
6. Generates alerts
7. Persists results

References:
- Pardo (2008) "The Evaluation and Optimization of Trading Strategies"
- de Prado et al. (2018) "Advances in Financial Machine Learning"
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PaperTradingConfig:
    """Configuration for paper trader."""
    initial_capital: float = 100_000
    rebalance_frequency: str = "weekly"  # 'daily' | 'weekly' | 'monthly'
    commission_bps: float = 1.0
    slippage_bps: float = 5.0
    max_position_pct: float = 0.05
    max_sector_pct: float = 0.25
    max_leverage: float = 1.5
    daily_loss_limit_pct: float = 5.0
    weekly_loss_limit_pct: float = 10.0
    max_drawdown_limit_pct: float = 15.0


@dataclass
class PaperTradingSession:
    """A paper trading session (trading session record)."""
    session_id: str
    start_date: date
    end_date: Optional[date] = None
    initial_capital: float = 100_000
    final_capital: float = 0
    total_return_pct: float = 0
    sharpe_ratio: float = 0
    max_drawdown_pct: float = 0
    total_trades: int = 0
    config: PaperTradingConfig = field(default_factory=PaperTradingConfig)
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct * 100, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 2),
            "total_trades": self.total_trades,
            "days_traded": (self.end_date - self.start_date).days if self.end_date else 0,
        }


class PaperTrader:
    """
    Main paper trading engine.

    Orchestrates daily trading:
    1. Generate signals (multi-source)
    2. Check risk controls
    3. Execute trades
    4. Update portfolio
    5. Track performance
    6. Generate alerts
    """

    def __init__(
        self,
        config: PaperTradingConfig = None,
        signal_generator: Optional[Callable] = None,
        stat_arb_generator: Optional[Callable] = None,
        ensemble_predictor: Optional[Callable] = None,
        risk_control_system: Optional[Any] = None,
        execution_model: Optional[Any] = None,
        monitoring_system: Optional[Any] = None,
    ):
        """
        Initialize paper trader.

        Args:
            config: Trading configuration
            signal_generator: Function to generate factor signals
            stat_arb_generator: Function to generate stat arb signals
            ensemble_predictor: Function to predict returns (ML ensemble)
            risk_control_system: RiskControlSystem instance
            execution_model: ExecutionModel instance
            monitoring_system: Monitoring system instance
        """
        self.config = config or PaperTradingConfig()
        self.signal_generator = signal_generator
        self.stat_arb_generator = stat_arb_generator
        self.ensemble_predictor = ensemble_predictor
        self.risk_control_system = risk_control_system
        self.execution_model = execution_model
        self.monitoring_system = monitoring_system

        # State
        self.session: Optional[PaperTradingSession] = None
        self.portfolio_value = self.config.initial_capital
        self.cash = self.config.initial_capital
        self.positions: Dict[str, float] = {}  # ticker -> shares
        self.daily_pnl = 0

        logger.info(f"Paper trader initialized with ${self.config.initial_capital:,.0f} capital")

    def start_session(self, session_id: str, start_date: date) -> PaperTradingSession:
        """
        Start a new paper trading session.

        Args:
            session_id: Unique session identifier
            start_date: Session start date

        Returns:
            PaperTradingSession
        """
        self.session = PaperTradingSession(
            session_id=session_id,
            start_date=start_date,
            initial_capital=self.config.initial_capital,
            config=self.config,
        )

        self.portfolio_value = self.config.initial_capital
        self.cash = self.config.initial_capital
        self.positions = {}

        logger.info(f"Started paper trading session: {session_id}")
        return self.session

    def daily_update(
        self,
        current_date: date,
        prices: Dict[str, float],
        volumes: Dict[str, float],
        signal_inputs: Dict[str, Any],  # Data needed for signal generation
    ) -> Dict[str, Any]:
        """
        Execute daily paper trading update.

        Args:
            current_date: Current trading date
            prices: Dict of ticker -> current price
            volumes: Dict of ticker -> daily volume
            signal_inputs: Data for signal generation

        Returns:
            Dict with daily results
        """
        logger.info(f"Daily update: {current_date}")

        # Step 1: Generate signals from all sources
        signals = self._generate_all_signals(signal_inputs)

        # Step 2: Combine signals
        combined_scores = self._combine_signals(signals)

        # Step 3: Compute target portfolio weights
        target_weights = self._compute_target_weights(combined_scores)

        # Step 4: Check risk controls
        risk_checks = self._check_risk_controls(target_weights, prices, current_date)

        if risk_checks.get("circuit_breaker_triggered"):
            logger.warning(f"Circuit breaker triggered on {current_date}")
            target_weights = {}  # Don't trade

        # Step 5: Execute rebalancing
        trades = self._execute_rebalancing(current_date, target_weights, prices, volumes)

        # Step 6: Update portfolio
        daily_result = self._update_portfolio(current_date, prices, trades)

        # Step 7: Generate alerts
        if self.monitoring_system:
            self._check_alerts(daily_result)

        logger.info(
            f"Daily result: PnL=${daily_result['daily_pnl']:+,.0f} | "
            f"Trades: {len(trades)} | "
            f"Portfolio: ${self.portfolio_value:,.0f}"
        )

        return daily_result

    def _generate_all_signals(self, signal_inputs: Dict[str, Any]) -> Dict[str, Dict]:
        """Generate signals from all three sources."""
        signals = {}

        # Source 1: Factor signals
        if self.signal_generator:
            try:
                signals["factors"] = self.signal_generator(signal_inputs)
            except Exception as e:
                logger.warning(f"Factor signal generation failed: {e}")
                signals["factors"] = {}

        # Source 2: Stat arb signals
        if self.stat_arb_generator:
            try:
                signals["stat_arb"] = self.stat_arb_generator(signal_inputs)
            except Exception as e:
                logger.warning(f"Stat arb signal generation failed: {e}")
                signals["stat_arb"] = {}

        # Source 3: ML ensemble predictions
        if self.ensemble_predictor:
            try:
                signals["ensemble"] = self.ensemble_predictor(signal_inputs)
            except Exception as e:
                logger.warning(f"Ensemble prediction failed: {e}")
                signals["ensemble"] = {}

        return signals

    def _combine_signals(self, signals: Dict[str, Dict]) -> Dict[str, float]:
        """
        Combine signals from all sources.

        Simple combination: equal weight averaging (can be improved)
        """
        combined = {}

        # Equal weighting across sources
        weights = {
            "factors": 0.4,
            "stat_arb": 0.3,
            "ensemble": 0.3,
        }

        for source, source_signals in signals.items():
            weight = weights.get(source, 0)

            for ticker, score in source_signals.items():
                if ticker not in combined:
                    combined[ticker] = 0
                combined[ticker] += score * weight

        # Normalize
        if combined:
            max_score = max(abs(v) for v in combined.values())
            if max_score > 0:
                combined = {k: v / max_score for k, v in combined.items()}

        return combined

    def _compute_target_weights(self, combined_scores: Dict[str, float]) -> Dict[str, float]:
        """
        Compute target portfolio weights from scores.

        Simple approach: weight by score ranking
        """
        if not combined_scores:
            return {}

        # Rank by score (highest = best)
        ranked = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)

        # Allocate weights
        n_stocks = min(len(ranked), 20)  # Top 20 stocks
        weights = {}

        for i, (ticker, score) in enumerate(ranked[:n_stocks]):
            # Weight decays with rank (best gets more)
            weight = (1.0 - i / n_stocks) ** 2
            weights[ticker] = weight

        # Normalize
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        # Apply position limit
        weights = {
            k: min(v, self.config.max_position_pct) for k, v in weights.items()
        }

        return weights

    def _check_risk_controls(
        self,
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        current_date: date,
    ) -> Dict[str, Any]:
        """Check all risk controls."""
        if not self.risk_control_system:
            return {"circuit_breaker_triggered": False}

        # Create positions dict from weights
        positions = {
            ticker: (self.portfolio_value * weight) / (prices.get(ticker, 1) + 1e-10)
            for ticker, weight in target_weights.items()
        }

        # Check limits (placeholder - would use actual returns)
        # In real implementation, would pass actual daily returns
        violations = self.risk_control_system.position_limits.check_position_limits(
            positions, self.portfolio_value
        )

        return {
            "circuit_breaker_triggered": len(violations) > 0,
            "violations": violations,
        }

    def _execute_rebalancing(
        self,
        current_date: date,
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        volumes: Dict[str, float],
    ) -> List[Dict]:
        """Execute portfolio rebalancing trades."""
        trades = []

        # Compute target quantities
        target_quantities = {}

        for ticker, weight in target_weights.items():
            if ticker in prices:
                target_value = self.portfolio_value * weight
                target_qty = target_value / prices[ticker]
                target_quantities[ticker] = target_qty

        # Generate trades
        for ticker in set(list(self.positions.keys()) + list(target_quantities.keys())):
            current_qty = self.positions.get(ticker, 0)
            target_qty = target_quantities.get(ticker, 0)
            quantity_change = target_qty - current_qty

            if abs(quantity_change) > 0.01:  # Only trade if meaningful
                try:
                    price = prices[ticker]
                    volume = volumes.get(ticker, 1e6)

                    side = "BUY" if quantity_change > 0 else "SELL"

                    # Simulate execution (placeholder)
                    executed_price = price  # Would use execution_model if available

                    trade = {
                        "date": current_date,
                        "ticker": ticker,
                        "side": side,
                        "quantity": abs(quantity_change),
                        "price": price,
                        "executed_price": executed_price,
                        "commission": price * abs(quantity_change) * (self.config.commission_bps / 10_000),
                        "pnl": 0,  # Will be computed later
                    }

                    trades.append(trade)

                    # Update positions immediately
                    if side == "BUY":
                        self.positions[ticker] = self.positions.get(ticker, 0) + quantity_change
                        self.cash -= executed_price * quantity_change + trade["commission"]
                    else:
                        # CRITICAL BUG FIX #5: SELL logic was inverted
                        # quantity_change is already negative for sells (target - current)
                        # So we add it to positions (which decreases since it's negative)
                        self.positions[ticker] = self.positions.get(ticker, 0) + quantity_change
                        # Cash goes UP when we sell (subtract negative = add positive)
                        self.cash -= executed_price * quantity_change + trade["commission"]

                except Exception as e:
                    logger.warning(f"Error trading {ticker}: {e}")

        return trades

    def _update_portfolio(
        self,
        current_date: date,
        prices: Dict[str, float],
        trades: List[Dict],
    ) -> Dict[str, Any]:
        """Update portfolio and compute daily metrics."""
        # Compute new portfolio value
        new_portfolio_value = self.cash

        for ticker, shares in self.positions.items():
            if ticker in prices:
                new_portfolio_value += shares * prices[ticker]

        # Daily P&L
        self.daily_pnl = new_portfolio_value - self.portfolio_value
        daily_return = self.daily_pnl / (self.portfolio_value + 1e-10)

        self.portfolio_value = new_portfolio_value

        return {
            "date": current_date,
            "portfolio_value": new_portfolio_value,
            "daily_pnl": self.daily_pnl,
            "daily_return_pct": daily_return,
            "trades": trades,
            "positions": self.positions.copy(),
        }

    def _check_alerts(self, daily_result: Dict[str, Any]) -> None:
        """Check for alert conditions."""
        if not self.monitoring_system:
            return

        # Check daily loss
        self.monitoring_system.alert_manager.check_daily_loss(
            daily_result["daily_pnl"],
            daily_result["portfolio_value"],
        )

    def end_session(self) -> PaperTradingSession:
        """End the current paper trading session."""
        if not self.session:
            raise ValueError("No active session")

        self.session.end_date = date.today()
        self.session.final_capital = self.portfolio_value
        self.session.total_return_pct = (
            (self.portfolio_value - self.config.initial_capital)
            / self.config.initial_capital
        )
        self.session.last_updated = datetime.now()

        logger.info(
            f"Ended session {self.session.session_id}: "
            f"Return={self.session.total_return_pct:+.2%}"
        )

        return self.session

    def save_session(self, filepath: str) -> None:
        """Save session to file."""
        if not self.session:
            raise ValueError("No active session")

        with open(filepath, "w") as f:
            json.dump(self.session.to_dict(), f, indent=2)

        logger.info(f"Session saved to {filepath}")

    def get_status(self) -> Dict[str, Any]:
        """Get current trading status."""
        return {
            "portfolio_value": self.portfolio_value,
            "cash": self.cash,
            "positions": self.positions,
            "daily_pnl": self.daily_pnl,
            "session_id": self.session.session_id if self.session else None,
            "start_date": self.session.start_date.isoformat() if self.session else None,
        }
