"""
Strategy Framework - Core Infrastructure for 30+ Independent Strategies

This framework allows unlimited independent strategies to:
- Operate autonomously
- Be backtested independently
- Report performance independently
- Be weighted optimally
- Fail gracefully without affecting others

Architecture: Each strategy implements BaseStrategy and registers with StrategyRegistry.
All strategies are weighted via StrategyWeighting based on risk-adjusted performance.

References:
- Schwager (2012) "Market Wizards" - Multi-strategy approach
- Almgren & Chriss (2001) - Portfolio optimization with constraints
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging
from uuid import uuid4

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    """Strategy status."""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    BACKTEST = "backtest"
    LIVE = "live"


@dataclass
class StrategySignal:
    """Signal from a single strategy."""
    strategy_id: str
    strategy_name: str
    timestamp: datetime

    # Position
    symbols: Dict[str, float] = field(default_factory=dict)  # ticker -> score (-1 to 1)
    target_weights: Dict[str, float] = field(default_factory=dict)  # ticker -> weight

    # Confidence
    confidence: float = 0.5  # 0-1, how confident in this signal
    conviction: float = 0.0  # Strength of conviction

    # Risk metrics
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    sharpe_estimate: float = 0.0

    # Metadata
    reason: str = ""
    update_frequency: str = "daily"  # How often this signal updates

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "timestamp": self.timestamp.isoformat(),
            "symbols": {k: round(v, 4) for k, v in self.symbols.items()},
            "target_weights": {k: round(v, 4) for k, v in self.target_weights.items()},
            "confidence": round(self.confidence, 3),
            "conviction": round(self.conviction, 3),
            "expected_return": round(self.expected_return, 4),
            "expected_volatility": round(self.expected_volatility, 4),
            "sharpe_estimate": round(self.sharpe_estimate, 2),
            "reason": self.reason,
        }


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy."""
    strategy_id: str
    strategy_name: str

    # Returns
    total_return: float = 0.0
    annual_return: float = 0.0
    monthly_returns: List[float] = field(default_factory=list)

    # Risk
    volatility: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0

    # Correlation
    correlation_with_market: float = 0.0
    correlation_with_benchmark: float = 0.0

    # Tracking
    last_updated: datetime = field(default_factory=datetime.now)
    samples: int = 0  # Number of data points

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "total_return": round(self.total_return, 4),
            "annual_return": round(self.annual_return, 4),
            "volatility": round(self.volatility, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "calmar_ratio": round(self.calmar_ratio, 2),
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2),
            "correlation_market": round(self.correlation_with_market, 3),
            "last_updated": self.last_updated.isoformat(),
        }


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Every strategy must implement:
    - generate_signal(): produce trading signal
    - validate_signal(): ensure signal is valid
    - get_metrics(): return performance metrics
    - backtest(): validate on historical data
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        update_frequency: str = "daily",
        position_limit: float = 0.05,
        max_leverage: float = 1.5,
        enabled: bool = True,
    ):
        """
        Initialize strategy.

        Args:
            name: Strategy name (e.g., "Mean Reversion")
            description: What this strategy does
            update_frequency: "daily" | "weekly" | "intraday"
            position_limit: Max position per symbol
            max_leverage: Max portfolio leverage
            enabled: Whether strategy is active
        """
        self.strategy_id = str(uuid4())[:8]
        self.name = name
        self.description = description
        self.update_frequency = update_frequency
        self.position_limit = position_limit
        self.max_leverage = max_leverage
        self.enabled = enabled

        self.status = StrategyStatus.ACTIVE if enabled else StrategyStatus.DISABLED
        self.metrics = StrategyMetrics(strategy_id=self.strategy_id, strategy_name=name)
        self.last_signal_time: Optional[datetime] = None
        self.error_count = 0
        self.max_errors = 10  # Disable after 10 errors

        logger.info(f"Initialized strategy: {name} ({self.strategy_id})")

    @abstractmethod
    def generate_signal(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs: Any,
    ) -> StrategySignal:
        """
        Generate trading signal.

        Args:
            prices: DataFrame with dates x tickers
            volumes: Optional volume data
            **kwargs: Additional strategy-specific data

        Returns:
            StrategySignal with positions and weights
        """
        pass

    def validate_signal(self, signal: StrategySignal) -> bool:
        """
        Validate signal before use.

        Checks:
        - Position limits respected
        - Weights sum to ~1
        - Confidence is valid
        - No NaN values
        """
        try:
            # Check weights sum to 1
            total_weight = sum(signal.target_weights.values())
            if abs(total_weight - 1.0) > 0.01:
                logger.warning(
                    f"Signal weights don't sum to 1: {total_weight:.3f}"
                )
                # Auto-normalize
                if total_weight > 0:
                    signal.target_weights = {
                        k: v / total_weight for k, v in signal.target_weights.items()
                    }

            # Check position limits
            for ticker, weight in signal.target_weights.items():
                if weight > self.position_limit:
                    logger.warning(
                        f"Position {ticker} ({weight:.1%}) exceeds "
                        f"limit ({self.position_limit:.1%})"
                    )

            # Check for NaN
            for v in signal.target_weights.values():
                if np.isnan(v) or np.isinf(v):
                    logger.error("Invalid weight value (NaN/Inf)")
                    return False

            # Check confidence
            if signal.confidence < 0 or signal.confidence > 1:
                logger.warning(f"Invalid confidence: {signal.confidence}")
                signal.confidence = np.clip(signal.confidence, 0, 1)

            return True

        except Exception as e:
            logger.error(f"Signal validation failed: {e}")
            return False

    @abstractmethod
    def backtest(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> StrategyMetrics:
        """
        Backtest strategy on historical data.

        Should use walk-forward validation to prevent look-ahead bias.
        """
        pass

    def update_metrics(
        self,
        returns: pd.Series,
        trades: Optional[List[Dict]] = None,
        market_returns: Optional[pd.Series] = None,
    ) -> None:
        """
        Update performance metrics.

        Args:
            returns: Daily returns from this strategy
            trades: List of trades executed
            market_returns: Market benchmark returns for correlation
        """
        if len(returns) == 0:
            return

        # Returns
        self.metrics.total_return = (np.exp(np.sum(np.log(1 + returns))) - 1)
        self.metrics.annual_return = (
            (1 + self.metrics.total_return) ** (252 / len(returns)) - 1
        )
        self.metrics.monthly_returns = returns.resample("M").apply(
            lambda x: (1 + x).prod() - 1
        ).tolist()

        # Risk
        self.metrics.volatility = returns.std() * np.sqrt(252)
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        self.metrics.max_drawdown = np.min(drawdown)

        # Ratios
        self.metrics.sharpe_ratio = (
            self.metrics.annual_return / (self.metrics.volatility + 1e-10)
        )
        downside_std = returns[returns < 0].std() * np.sqrt(252)
        self.metrics.sortino_ratio = (
            self.metrics.annual_return / (downside_std + 1e-10)
        )
        self.metrics.calmar_ratio = (
            self.metrics.annual_return / (abs(self.metrics.max_drawdown) + 1e-10)
        )

        # Trade stats
        if trades:
            self.metrics.total_trades = len(trades)
            pnls = [t.get("pnl", 0) for t in trades]
            winners = [p for p in pnls if p > 0]
            losers = [p for p in pnls if p < 0]

            self.metrics.winning_trades = len(winners)
            self.metrics.losing_trades = len(losers)
            self.metrics.win_rate = len(winners) / (len(trades) + 1e-10)
            self.metrics.avg_win = np.mean(winners) if winners else 0
            self.metrics.avg_loss = np.mean(losers) if losers else 0

            gross_profit = sum(winners) if winners else 0
            gross_loss = abs(sum(losers)) if losers else 0
            self.metrics.profit_factor = gross_profit / (gross_loss + 1e-10)

        # Correlation
        if market_returns is not None:
            common_idx = returns.index.intersection(market_returns.index)
            if len(common_idx) > 0:
                self.metrics.correlation_with_market = returns.loc[common_idx].corr(
                    market_returns.loc[common_idx]
                )

        self.metrics.last_updated = datetime.now()
        self.metrics.samples = len(returns)

    def get_metrics(self) -> StrategyMetrics:
        """Get current performance metrics."""
        return self.metrics

    def record_error(self) -> None:
        """Record strategy error."""
        self.error_count += 1
        if self.error_count >= self.max_errors:
            logger.warning(
                f"Strategy {self.name} disabled due to {self.error_count} errors"
            )
            self.status = StrategyStatus.DISABLED
            self.enabled = False

    def is_healthy(self) -> bool:
        """Check if strategy is healthy."""
        return (
            self.enabled
            and self.status not in [StrategyStatus.DISABLED]
            and self.error_count < self.max_errors
        )

    def __repr__(self) -> str:
        return (
            f"Strategy({self.name}, status={self.status.name}, "
            f"sharpe={self.metrics.sharpe_ratio:.2f})"
        )


class StrategyRegistry:
    """
    Central registry for all strategies.

    Manages:
    - Strategy registration
    - Strategy lifecycle (enable/disable)
    - Strategy health monitoring
    - Strategy discovery
    """

    def __init__(self):
        """Initialize registry."""
        self.strategies: Dict[str, BaseStrategy] = {}
        self.active_strategies: List[str] = []

    def register(self, strategy: BaseStrategy) -> str:
        """
        Register a strategy.

        Args:
            strategy: BaseStrategy instance

        Returns:
            Strategy ID
        """
        self.strategies[strategy.strategy_id] = strategy
        if strategy.enabled:
            self.active_strategies.append(strategy.strategy_id)

        logger.info(f"Registered strategy: {strategy.name} ({strategy.strategy_id})")
        return strategy.strategy_id

    def unregister(self, strategy_id: str) -> None:
        """Unregister a strategy."""
        if strategy_id in self.strategies:
            del self.strategies[strategy_id]
            if strategy_id in self.active_strategies:
                self.active_strategies.remove(strategy_id)

    def get_strategy(self, strategy_id: str) -> Optional[BaseStrategy]:
        """Get strategy by ID."""
        return self.strategies.get(strategy_id)

    def get_all_strategies(self) -> List[BaseStrategy]:
        """Get all registered strategies."""
        return list(self.strategies.values())

    def get_active_strategies(self) -> List[BaseStrategy]:
        """Get only active strategies."""
        return [
            self.strategies[sid]
            for sid in self.active_strategies
            if sid in self.strategies
            and self.strategies[sid].is_healthy()
        ]

    def enable_strategy(self, strategy_id: str) -> None:
        """Enable a strategy."""
        if strategy_id in self.strategies:
            self.strategies[strategy_id].enabled = True
            self.strategies[strategy_id].status = StrategyStatus.ACTIVE
            if strategy_id not in self.active_strategies:
                self.active_strategies.append(strategy_id)

    def disable_strategy(self, strategy_id: str) -> None:
        """Disable a strategy."""
        if strategy_id in self.strategies:
            self.strategies[strategy_id].enabled = False
            self.strategies[strategy_id].status = StrategyStatus.DISABLED
            if strategy_id in self.active_strategies:
                self.active_strategies.remove(strategy_id)

    def get_summary(self) -> Dict[str, Any]:
        """Get registry summary."""
        return {
            "total_strategies": len(self.strategies),
            "active_strategies": len(self.active_strategies),
            "strategies": [
                {
                    "name": s.name,
                    "id": s.strategy_id,
                    "status": s.status.name,
                    "sharpe": s.metrics.sharpe_ratio,
                    "return": s.metrics.annual_return,
                }
                for s in self.get_active_strategies()
            ],
        }


class StrategyExecutor:
    """
    Executes strategies independently.

    Each strategy:
    - Generates its own signal
    - Is validated independently
    - Contributes to portfolio independently
    - Fails gracefully without affecting others
    """

    def __init__(self, registry: StrategyRegistry):
        """Initialize executor."""
        self.registry = registry
        self.signals: Dict[str, StrategySignal] = {}
        self.errors: Dict[str, str] = {}

    def execute_all(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        **kwargs: Any,
    ) -> Dict[str, StrategySignal]:
        """
        Execute all active strategies.

        Each strategy runs independently. If one fails, others continue.

        Returns:
            Dict of strategy_id -> signal
        """
        self.signals = {}
        self.errors = {}

        for strategy in self.registry.get_active_strategies():
            try:
                signal = strategy.generate_signal(prices, volumes, **kwargs)

                # Validate signal
                if strategy.validate_signal(signal):
                    self.signals[strategy.strategy_id] = signal
                else:
                    self.errors[strategy.strategy_id] = "Signal validation failed"
                    strategy.record_error()

            except Exception as e:
                logger.error(f"Strategy {strategy.name} execution failed: {e}")
                self.errors[strategy.strategy_id] = str(e)
                strategy.record_error()

        logger.info(
            f"Executed {len(self.signals)}/{len(self.registry.get_active_strategies())} "
            f"strategies successfully"
        )

        return self.signals

    def get_signals(self) -> Dict[str, StrategySignal]:
        """Get latest signals."""
        return self.signals

    def get_errors(self) -> Dict[str, str]:
        """Get execution errors."""
        return self.errors
