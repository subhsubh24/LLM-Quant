"""
Adaptive Learning Engine for Quantitative Trading

Implements reinforcement learning and online learning algorithms:
1. Online Factor Weight Learning - weights adapt based on signal accuracy
2. Thompson Sampling - Bayesian bandit for regime/strategy selection
3. Adaptive Kelly - real-time win rate tracking for position sizing
4. Performance Attribution - tracks which factors contribute to P&L

This creates a feedback loop where the bot learns from its trades.
"""

import math
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Detected market regimes."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


@dataclass
class TradeOutcome:
    """Record of a trade outcome for learning."""
    symbol: str
    asset_class: str  # crypto or stock
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    holding_period_hours: float
    factors_at_entry: Dict[str, float]  # Factor values when trade was opened
    factor_weights_at_entry: Dict[str, float]  # Weights used
    regime_at_entry: MarketRegime
    signal_strength: float  # Composite score at entry
    was_profitable: bool


@dataclass
class FactorPerformance:
    """Tracks performance of a single factor."""
    name: str
    total_trades: int = 0
    profitable_trades: int = 0
    total_pnl: float = 0.0
    avg_contribution: float = 0.0  # Average weighted contribution when profitable
    # Bayesian parameters for Thompson Sampling
    alpha: float = 1.0  # Successes + prior
    beta: float = 1.0   # Failures + prior
    # Recent performance (exponential moving average)
    ema_accuracy: float = 0.5
    ema_alpha: float = 0.1  # Learning rate for EMA

    @property
    def win_rate(self) -> float:
        """Empirical win rate."""
        if self.total_trades == 0:
            return 0.5
        return self.profitable_trades / self.total_trades

    @property
    def bayesian_win_rate(self) -> float:
        """Bayesian estimate of win rate (posterior mean)."""
        return self.alpha / (self.alpha + self.beta)

    def sample_win_rate(self) -> float:
        """Thompson Sampling: sample from posterior Beta distribution."""
        return np.random.beta(self.alpha, self.beta)

    def update(self, was_profitable: bool, contribution: float):
        """Update factor performance with new trade outcome."""
        self.total_trades += 1
        if was_profitable:
            self.profitable_trades += 1
            self.alpha += 1
        else:
            self.beta += 1

        self.total_pnl += contribution

        # Update EMA of accuracy
        outcome = 1.0 if was_profitable else 0.0
        self.ema_accuracy = self.ema_alpha * outcome + (1 - self.ema_alpha) * self.ema_accuracy

        # Update average contribution
        if self.total_trades > 0:
            self.avg_contribution = self.total_pnl / self.total_trades


@dataclass
class RegimePerformance:
    """Tracks strategy performance in different market regimes."""
    regime: MarketRegime
    strategies_tried: Dict[str, int] = field(default_factory=dict)
    strategies_success: Dict[str, int] = field(default_factory=dict)
    # Thompson Sampling parameters per strategy
    strategy_alpha: Dict[str, float] = field(default_factory=dict)
    strategy_beta: Dict[str, float] = field(default_factory=dict)

    def update(self, strategy: str, was_profitable: bool):
        """Update regime-strategy performance."""
        if strategy not in self.strategies_tried:
            self.strategies_tried[strategy] = 0
            self.strategies_success[strategy] = 0
            self.strategy_alpha[strategy] = 1.0
            self.strategy_beta[strategy] = 1.0

        self.strategies_tried[strategy] += 1
        if was_profitable:
            self.strategies_success[strategy] += 1
            self.strategy_alpha[strategy] += 1
        else:
            self.strategy_beta[strategy] += 1

    def sample_best_strategy(self) -> Optional[str]:
        """Thompson Sampling: select strategy by sampling from posteriors."""
        if not self.strategy_alpha:
            return None

        best_strategy = None
        best_sample = -1

        for strategy in self.strategy_alpha:
            sample = np.random.beta(
                self.strategy_alpha[strategy],
                self.strategy_beta[strategy]
            )
            if sample > best_sample:
                best_sample = sample
                best_strategy = strategy

        return best_strategy


class AdaptiveLearningEngine:
    """
    Main adaptive learning engine that implements:
    1. Online factor weight optimization
    2. Thompson Sampling for regime-based strategy selection
    3. Real-time win rate tracking for adaptive Kelly
    4. Performance attribution across factors
    """

    def __init__(
        self,
        learning_rate: float = 0.05,
        min_trades_for_adaptation: int = 10,
        weight_decay: float = 0.001,
        exploration_bonus: float = 0.1,
    ):
        """
        Initialize the adaptive learning engine.

        Args:
            learning_rate: How fast weights adapt (0.01-0.1 typical)
            min_trades_for_adaptation: Minimum trades before adapting weights
            weight_decay: L2 regularization to prevent extreme weights
            exploration_bonus: Bonus for under-explored factors (UCB-style)
        """
        self.learning_rate = learning_rate
        self.min_trades_for_adaptation = min_trades_for_adaptation
        self.weight_decay = weight_decay
        self.exploration_bonus = exploration_bonus

        # Factor performance tracking
        self.factor_performance: Dict[str, FactorPerformance] = {}

        # Regime performance tracking
        self.regime_performance: Dict[MarketRegime, RegimePerformance] = {
            regime: RegimePerformance(regime=regime)
            for regime in MarketRegime
        }

        # Asset class performance
        self.asset_win_rates: Dict[str, Dict] = {
            "crypto": {"wins": 0, "total": 0, "ema_win_rate": 0.5},
            "stocks": {"wins": 0, "total": 0, "ema_win_rate": 0.5},
        }

        # Trade history for learning
        self.trade_history: deque = deque(maxlen=1000)

        # Current adapted weights (will be updated over time)
        self.adapted_weights: Dict[str, Dict[str, float]] = {
            "crypto": {},
            "stocks": {},
        }

        # Regime detection state
        self.current_regime: MarketRegime = MarketRegime.UNKNOWN
        self.regime_history: deque = deque(maxlen=100)

        # Learning statistics
        self.total_updates: int = 0
        self.last_update_time: Optional[datetime] = None

        logger.info("AdaptiveLearningEngine initialized with RL capabilities")

    def record_trade_outcome(self, outcome: TradeOutcome):
        """
        Record a completed trade and update all learning components.
        This is the main feedback loop entry point.
        """
        self.trade_history.append(outcome)

        # 1. Update factor performance
        self._update_factor_performance(outcome)

        # 2. Update regime-strategy performance
        self._update_regime_performance(outcome)

        # 3. Update asset class win rates
        self._update_asset_win_rates(outcome)

        # 4. Adapt factor weights if enough data
        if len(self.trade_history) >= self.min_trades_for_adaptation:
            self._adapt_factor_weights(outcome.asset_class)

        self.total_updates += 1
        self.last_update_time = datetime.now()

        logger.info(
            f"📚 LEARNED from {outcome.symbol}: "
            f"{'WIN' if outcome.was_profitable else 'LOSS'} "
            f"({outcome.pnl_pct:+.2f}%) | "
            f"Total trades learned: {self.total_updates}"
        )

    def _update_factor_performance(self, outcome: TradeOutcome):
        """Update individual factor performance metrics."""
        for factor_name, factor_value in outcome.factors_at_entry.items():
            if factor_name not in self.factor_performance:
                self.factor_performance[factor_name] = FactorPerformance(name=factor_name)

            # Calculate factor's contribution to this trade
            weight = outcome.factor_weights_at_entry.get(factor_name, 0)
            contribution = factor_value * weight * outcome.pnl_pct

            self.factor_performance[factor_name].update(
                was_profitable=outcome.was_profitable,
                contribution=contribution
            )

    def _update_regime_performance(self, outcome: TradeOutcome):
        """Update regime-specific strategy performance."""
        regime = outcome.regime_at_entry
        # Use mode as strategy identifier
        strategy = outcome.asset_class  # Could be more granular

        self.regime_performance[regime].update(
            strategy=strategy,
            was_profitable=outcome.was_profitable
        )

    def _update_asset_win_rates(self, outcome: TradeOutcome):
        """Update win rates per asset class for Adaptive Kelly."""
        asset_class = outcome.asset_class
        if asset_class not in self.asset_win_rates:
            self.asset_win_rates[asset_class] = {"wins": 0, "total": 0, "ema_win_rate": 0.5}

        stats = self.asset_win_rates[asset_class]
        stats["total"] += 1
        if outcome.was_profitable:
            stats["wins"] += 1

        # Update EMA of win rate
        ema_alpha = 0.1
        win_indicator = 1.0 if outcome.was_profitable else 0.0
        stats["ema_win_rate"] = ema_alpha * win_indicator + (1 - ema_alpha) * stats["ema_win_rate"]

    def _adapt_factor_weights(self, asset_class: str):
        """
        Online Gradient Descent for factor weight adaptation.
        Increases weights for factors that predict profitable trades.
        """
        if asset_class not in self.adapted_weights:
            self.adapted_weights[asset_class] = {}

        # Get recent trades for this asset class
        recent_trades = [
            t for t in self.trade_history
            if t.asset_class == asset_class
        ][-50:]  # Last 50 trades

        if len(recent_trades) < self.min_trades_for_adaptation:
            return

        # Calculate gradient for each factor
        for factor_name, perf in self.factor_performance.items():
            if perf.total_trades < 5:
                continue  # Not enough data

            # Current weight (or default)
            current_weight = self.adapted_weights[asset_class].get(factor_name, 0.1)

            # Gradient: increase weight if factor predicts well
            # Use Thompson Sampling win rate for stability
            sampled_accuracy = perf.sample_win_rate()

            # Gradient = (accuracy - 0.5) * learning_rate
            # If accuracy > 0.5, increase weight; if < 0.5, decrease
            gradient = (sampled_accuracy - 0.5) * self.learning_rate

            # Add exploration bonus for under-explored factors (UCB-style)
            exploration = self.exploration_bonus / math.sqrt(perf.total_trades + 1)

            # Apply weight decay (L2 regularization)
            decay = -self.weight_decay * current_weight

            # Update weight
            new_weight = current_weight + gradient + exploration + decay

            # Clamp to reasonable range
            new_weight = max(0.01, min(0.5, new_weight))

            self.adapted_weights[asset_class][factor_name] = new_weight

        # Normalize weights to sum to 1
        total = sum(self.adapted_weights[asset_class].values())
        if total > 0:
            for factor in self.adapted_weights[asset_class]:
                self.adapted_weights[asset_class][factor] /= total

    def get_adapted_weights(self, asset_class: str, base_weights: Dict[str, float]) -> Dict[str, float]:
        """
        Get factor weights adapted by learning.
        Blends base weights with learned adaptations.

        Args:
            asset_class: 'crypto' or 'stocks'
            base_weights: Original static weights from mode config

        Returns:
            Adapted weights dictionary
        """
        if len(self.trade_history) < self.min_trades_for_adaptation:
            # Not enough data yet, use base weights
            return base_weights

        adapted = self.adapted_weights.get(asset_class, {})
        if not adapted:
            return base_weights

        # Blend: 70% base + 30% adapted (gradually trust learning more)
        blend_ratio = min(0.5, len(self.trade_history) / 200)  # Max 50% adapted

        blended = {}
        all_factors = set(base_weights.keys()) | set(adapted.keys())

        for factor in all_factors:
            base = base_weights.get(factor, 0.05)
            adapt = adapted.get(factor, base)
            blended[factor] = (1 - blend_ratio) * base + blend_ratio * adapt

        # Normalize
        total = sum(blended.values())
        if total > 0:
            blended = {k: v / total for k, v in blended.items()}

        return blended

    def get_adaptive_kelly(self, asset_class: str, base_kelly: float) -> float:
        """
        Get Kelly Criterion adjusted by actual win rate.

        Args:
            asset_class: 'crypto' or 'stocks'
            base_kelly: Kelly size from static calculation

        Returns:
            Adjusted Kelly size
        """
        stats = self.asset_win_rates.get(asset_class, {"ema_win_rate": 0.5, "total": 0})

        if stats["total"] < 10:
            # Not enough data, use base Kelly with safety margin
            return base_kelly * 0.5

        # Use EMA win rate for Kelly calculation
        win_rate = stats["ema_win_rate"]

        # Estimate win/loss ratio from recent trades
        recent = [t for t in self.trade_history if t.asset_class == asset_class][-30:]
        if recent:
            wins = [t.pnl_pct for t in recent if t.was_profitable]
            losses = [abs(t.pnl_pct) for t in recent if not t.was_profitable]

            avg_win = np.mean(wins) if wins else 3.0
            avg_loss = np.mean(losses) if losses else 2.0
            win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.5
        else:
            win_loss_ratio = 1.5

        # Kelly formula: f* = (p * b - q) / b
        # where p = win prob, q = 1-p, b = win/loss ratio
        q = 1 - win_rate
        kelly = (win_rate * win_loss_ratio - q) / win_loss_ratio

        # Apply fractional Kelly (half Kelly for safety)
        kelly = kelly * 0.5

        # Clamp to reasonable range
        kelly = max(0.01, min(0.25, kelly))

        return kelly

    def select_strategy_for_regime(self, regime: MarketRegime) -> Tuple[str, float]:
        """
        Thompson Sampling to select best strategy for current regime.

        Returns:
            (strategy_name, confidence)
        """
        regime_perf = self.regime_performance.get(regime)
        if not regime_perf or not regime_perf.strategy_alpha:
            return ("balanced", 0.5)

        best_strategy = regime_perf.sample_best_strategy()
        if not best_strategy:
            return ("balanced", 0.5)

        # Calculate confidence from posterior
        alpha = regime_perf.strategy_alpha[best_strategy]
        beta = regime_perf.strategy_beta[best_strategy]
        confidence = alpha / (alpha + beta)

        return (best_strategy, confidence)

    def detect_regime(self, prices: List[float], volatility: float) -> MarketRegime:
        """
        Detect current market regime from price data.
        """
        if len(prices) < 20:
            return MarketRegime.UNKNOWN

        # Calculate trend
        returns = np.diff(prices) / np.maximum(np.array(prices[:-1]), 1e-8)
        avg_return = np.mean(returns[-10:])
        trend_strength = abs(avg_return) * 100

        # Calculate volatility percentile
        historical_vol = np.std(returns) * np.sqrt(252) * 100

        # Hurst exponent for mean reversion detection
        # Simplified: use autocorrelation
        if len(returns) >= 20:
            autocorr = np.corrcoef(returns[:-1], returns[1:])[0, 1]
        else:
            autocorr = 0

        # Classify regime
        if historical_vol > 50:  # High vol threshold
            regime = MarketRegime.HIGH_VOLATILITY
        elif historical_vol < 20:  # Low vol threshold
            regime = MarketRegime.LOW_VOLATILITY
        elif avg_return > 0.005:  # 0.5% average daily return
            regime = MarketRegime.TRENDING_UP
        elif avg_return < -0.005:
            regime = MarketRegime.TRENDING_DOWN
        elif autocorr < -0.2:  # Negative autocorrelation = mean reverting
            regime = MarketRegime.MEAN_REVERTING
        else:
            regime = MarketRegime.UNKNOWN

        self.current_regime = regime
        self.regime_history.append((datetime.now(), regime))

        return regime

    def get_factor_insights(self) -> List[Dict[str, Any]]:
        """Get insights about factor performance for display."""
        insights = []

        for name, perf in sorted(
            self.factor_performance.items(),
            key=lambda x: x[1].bayesian_win_rate,
            reverse=True
        ):
            if perf.total_trades < 3:
                continue

            insights.append({
                "factor": name,
                "trades": perf.total_trades,
                "win_rate": round(perf.win_rate * 100, 1),
                "bayesian_win_rate": round(perf.bayesian_win_rate * 100, 1),
                "total_pnl": round(perf.total_pnl, 2),
                "ema_accuracy": round(perf.ema_accuracy * 100, 1),
                "rating": "🟢" if perf.bayesian_win_rate > 0.55 else "🟡" if perf.bayesian_win_rate > 0.45 else "🔴",
            })

        return insights

    def get_regime_insights(self) -> Dict[str, Any]:
        """Get insights about regime performance."""
        return {
            "current_regime": self.current_regime.value,
            "regime_history_length": len(self.regime_history),
            "regime_performance": {
                regime.value: {
                    "strategies": dict(perf.strategies_tried),
                    "success": dict(perf.strategies_success),
                }
                for regime, perf in self.regime_performance.items()
                if perf.strategies_tried
            }
        }

    def get_learning_summary(self) -> Dict[str, Any]:
        """Get summary of learning progress."""
        return {
            "total_trades_learned": len(self.trade_history),
            "total_updates": self.total_updates,
            "last_update": self.last_update_time.isoformat() if self.last_update_time else None,
            "current_regime": self.current_regime.value,
            "asset_win_rates": {
                asset: {
                    "win_rate": round(stats["ema_win_rate"] * 100, 1),
                    "total_trades": stats["total"],
                }
                for asset, stats in self.asset_win_rates.items()
            },
            "top_factors": self.get_factor_insights()[:5],
            "adapted_weights": {
                asset: {k: round(v, 3) for k, v in weights.items()}
                for asset, weights in self.adapted_weights.items()
                if weights
            },
            "learning_status": (
                "🎓 LEARNING ACTIVE" if len(self.trade_history) >= self.min_trades_for_adaptation
                else f"📚 COLLECTING DATA ({len(self.trade_history)}/{self.min_trades_for_adaptation})"
            ),
        }

    def save_state(self) -> Dict[str, Any]:
        """Serialize learning state for persistence."""
        return {
            "factor_performance": {
                name: {
                    "total_trades": perf.total_trades,
                    "profitable_trades": perf.profitable_trades,
                    "total_pnl": perf.total_pnl,
                    "alpha": perf.alpha,
                    "beta": perf.beta,
                    "ema_accuracy": perf.ema_accuracy,
                }
                for name, perf in self.factor_performance.items()
            },
            "asset_win_rates": self.asset_win_rates,
            "adapted_weights": self.adapted_weights,
            "total_updates": self.total_updates,
        }

    def load_state(self, state: Dict[str, Any]):
        """Restore learning state from persistence."""
        if "factor_performance" in state:
            for name, data in state["factor_performance"].items():
                perf = FactorPerformance(name=name)
                perf.total_trades = data.get("total_trades", 0)
                perf.profitable_trades = data.get("profitable_trades", 0)
                perf.total_pnl = data.get("total_pnl", 0)
                perf.alpha = data.get("alpha", 1.0)
                perf.beta = data.get("beta", 1.0)
                perf.ema_accuracy = data.get("ema_accuracy", 0.5)
                self.factor_performance[name] = perf

        if "asset_win_rates" in state:
            self.asset_win_rates = state["asset_win_rates"]

        if "adapted_weights" in state:
            self.adapted_weights = state["adapted_weights"]

        if "total_updates" in state:
            self.total_updates = state["total_updates"]

        logger.info(f"Loaded learning state: {self.total_updates} previous updates")


# Singleton instance
_learning_engine: Optional[AdaptiveLearningEngine] = None


def get_learning_engine() -> AdaptiveLearningEngine:
    """Get singleton learning engine instance."""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = AdaptiveLearningEngine()
    return _learning_engine
