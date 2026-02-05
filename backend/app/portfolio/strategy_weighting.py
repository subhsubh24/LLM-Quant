"""
Strategy Weighting & Optimization Engine

Intelligently combines signals from 10+ independent strategies:
- Equal weighting baseline
- Performance-based weighting (Sharpe-optimal)
- Risk parity weighting (volatility-adjusted)
- Regime-based weighting (adapts to market conditions)
- Diversification penalty (reduces concentration risk)

This ensures:
- Strategies fail independently without affecting others
- Portfolio benefit from diversification
- Optimal capital allocation to best performers
- Dynamic adaptation to market regimes

References:
- Markowitz (1952) - Portfolio optimization
- Sharpe (1966) - Capital allocation model
- Black & Litterman (1992) - Bayesian portfolio construction
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class WeightingMethod(Enum):
    """Strategy weighting methods."""
    EQUAL = "equal"
    PERFORMANCE_BASED = "performance_based"
    RISK_PARITY = "risk_parity"
    REGIME_BASED = "regime_based"
    INVERSE_VOLATILITY = "inverse_volatility"


@dataclass
class StrategyAllocation:
    """Strategy allocation result."""
    date: date
    method: WeightingMethod
    allocations: Dict[str, float]  # strategy_id -> weight
    justification: str = ""
    optimization_score: float = 0.0


@dataclass
class StrategyPerformance:
    """Strategy performance metrics for optimization."""
    strategy_id: str
    strategy_name: str
    returns: List[float] = field(default_factory=list)
    sharpe_ratio: float = 0.0
    volatility: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.5
    correlation_avg: float = 0.0
    recent_momentum: float = 0.0  # How well strategy performed recently


class EqualWeightingOptimizer:
    """Simple equal weighting across all strategies."""

    def compute_weights(
        self,
        strategy_ids: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Compute equal weights."""
        n = len(strategy_ids)
        if n == 0:
            return {}

        weight = 1.0 / n
        return {strategy_id: weight for strategy_id in strategy_ids}


class PerformanceBasedOptimizer:
    """Allocate capital based on Sharpe-ratio-adjusted performance."""

    def __init__(self, lookback_days: int = 60):
        """Initialize."""
        self.lookback_days = lookback_days

    def compute_weights(
        self,
        strategy_performances: Dict[str, StrategyPerformance],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        Compute weights based on Sharpe ratios.

        Higher Sharpe = more capital allocation.
        Minimum allocation: 5% (prevent abandoning strategies in drawdown).
        """
        if not strategy_performances:
            return {}

        # Compute allocation scores
        scores = {}
        min_sharpe = 0.5

        for strategy_id, perf in strategy_performances.items():
            # Use recent momentum (more responsive to current performance)
            # Combine with Sharpe (more stable)
            score = 0.6 * max(perf.sharpe_ratio, min_sharpe) + 0.4 * perf.recent_momentum
            scores[strategy_id] = max(score, 0.1)

        # Normalize
        total_score = sum(scores.values())
        if total_score == 0:
            return {sid: 1.0 / len(scores) for sid in scores.keys()}

        weights = {sid: score / total_score for sid, score in scores.items()}

        # Apply minimum allocation (don't completely abandon strategies)
        min_weight = 0.05
        for strategy_id in weights:
            weights[strategy_id] = max(weights[strategy_id], min_weight)

        # Renormalize
        total = sum(weights.values())
        weights = {sid: w / total for sid, w in weights.items()}

        return weights


class RiskParityOptimizer:
    """Allocate capital for equal risk contribution."""

    def compute_weights(
        self,
        strategy_performances: Dict[str, StrategyPerformance],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        Compute risk parity weights.

        Allocate inversely proportional to volatility
        so each strategy contributes equally to portfolio risk.
        """
        if not strategy_performances:
            return {}

        # Compute inverse volatility weights
        weights = {}
        for strategy_id, perf in strategy_performances.items():
            vol = max(perf.volatility, 0.01)  # Avoid division by zero
            weights[strategy_id] = 1.0 / vol

        # Normalize
        total = sum(weights.values())
        if total == 0:
            return {sid: 1.0 / len(weights) for sid in weights.keys()}

        weights = {sid: w / total for sid, w in weights.items()}
        return weights


class RegimeBasedOptimizer:
    """Allocate based on market regime."""

    def __init__(self):
        """Initialize."""
        self.regime_strategy_map = {
            "high_volatility": ["volatility_trading", "mean_reversion"],
            "trending": ["trend_following", "carry_trading"],
            "mean_reverting": ["mean_reversion", "technical_patterns"],
            "risk_off": ["sector_rotation", "carry_trading"],
            "normal": [
                "trend_following",
                "mean_reversion",
                "volatility_trading",
                "sector_rotation",
            ],
        }

    def detect_regime(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Detect current market regime.

        Regimes:
        - high_volatility: VIX > 25
        - trending: Strong directional movement
        - mean_reverting: Range-bound with reversions
        - risk_off: Flight to safety
        - normal: Normal conditions
        """
        if not context:
            return "normal"

        vix = context.get("vix", 15)
        trend_strength = context.get("trend_strength", 0)
        correlation = context.get("correlation", 0.5)

        if vix > 25:
            return "high_volatility"
        elif vix < 12 and correlation < 0.3:
            return "mean_reverting"
        elif abs(trend_strength) > 0.6:
            return "trending"
        elif context.get("risk_sentiment", 0) < -0.5:
            return "risk_off"

        return "normal"

    def compute_weights(
        self,
        strategy_ids: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Compute regime-based weights."""
        if not strategy_ids:
            return {}

        regime = self.detect_regime(context)
        preferred_strategies = self.regime_strategy_map.get(regime, strategy_ids)

        # Allocate more to strategies suited for this regime
        weights = {}
        base_weight = 1.0 / len(strategy_ids)

        for strategy_id in strategy_ids:
            if strategy_id in preferred_strategies:
                # Preferred strategies get 1.5x allocation
                weights[strategy_id] = base_weight * 1.5
            else:
                # Others get reduced allocation
                weights[strategy_id] = base_weight * 0.5

        # Normalize
        total = sum(weights.values())
        weights = {sid: w / total for sid, w in weights.items()}

        return weights


class CorrelationConstraint:
    """Enforce correlation-based constraints on strategy allocation."""

    def __init__(self, max_correlation_sum: float = 3.0):
        """
        Initialize.

        Args:
            max_correlation_sum: Maximum allowed sum of pairwise correlations
                                 (lower = more diversification required)
        """
        self.max_correlation_sum = max_correlation_sum

    def constrain_weights(
        self,
        weights: Dict[str, float],
        correlations: Dict[Tuple[str, str], float],
    ) -> Dict[str, float]:
        """
        Adjust weights to reduce correlation concentration.

        If strategies are too correlated, reduce their combined allocation.
        """
        if not weights or not correlations:
            return weights

        # Compute correlation concentration metric
        correlation_sum = 0
        for (sid1, sid2), corr in correlations.items():
            correlation_sum += weights[sid1] * weights[sid2] * corr

        if correlation_sum > self.max_correlation_sum:
            # Reduce allocation to most correlated strategies
            reduction_factor = self.max_correlation_sum / correlation_sum
            weights = {sid: w * reduction_factor for sid, w in weights.items()}

            # Normalize and add noise to break ties
            total = sum(weights.values())
            weights = {sid: w / total for sid, w in weights.items()}

        return weights


class StrategyWeightingEngine:
    """Master strategy weighting engine."""

    def __init__(self, method: WeightingMethod = WeightingMethod.PERFORMANCE_BASED):
        """Initialize."""
        self.method = method
        self.equal_optimizer = EqualWeightingOptimizer()
        self.performance_optimizer = PerformanceBasedOptimizer()
        self.risk_parity_optimizer = RiskParityOptimizer()
        self.regime_optimizer = RegimeBasedOptimizer()
        self.correlation_constraint = CorrelationConstraint()

        self.allocation_history: List[StrategyAllocation] = []

    def compute_allocation(
        self,
        strategy_ids: List[str],
        strategy_performances: Optional[Dict[str, StrategyPerformance]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategyAllocation:
        """
        Compute optimal strategy allocation.

        Args:
            strategy_ids: List of strategy identifiers
            strategy_performances: Performance metrics for each strategy
            context: Market context (regime, volatility, etc.)

        Returns:
            StrategyAllocation with weights and justification
        """
        if not strategy_ids:
            return StrategyAllocation(
                date=date.today(),
                method=self.method,
                allocations={},
            )

        # Compute base weights based on method
        if self.method == WeightingMethod.EQUAL:
            weights = self.equal_optimizer.compute_weights(strategy_ids, context)
            justification = "Equal weighting across all strategies"

        elif self.method == WeightingMethod.PERFORMANCE_BASED:
            if not strategy_performances:
                weights = self.equal_optimizer.compute_weights(strategy_ids)
                justification = "Performance data unavailable, using equal weights"
            else:
                weights = self.performance_optimizer.compute_weights(
                    strategy_performances, context
                )
                top_3 = sorted(
                    weights.items(), key=lambda x: x[1], reverse=True
                )[:3]
                justification = f"Performance-based: top {[s for s, _ in top_3]}"

        elif self.method == WeightingMethod.RISK_PARITY:
            if not strategy_performances:
                weights = self.equal_optimizer.compute_weights(strategy_ids)
            else:
                weights = self.risk_parity_optimizer.compute_weights(
                    strategy_performances
                )
            justification = "Risk parity: equal risk contribution"

        elif self.method == WeightingMethod.REGIME_BASED:
            regime = self.regime_optimizer.detect_regime(context)
            weights = self.regime_optimizer.compute_weights(
                strategy_ids, context
            )
            justification = f"Regime-based ({regime})"

        else:
            weights = self.equal_optimizer.compute_weights(strategy_ids)
            justification = "Default equal weighting"

        # Apply correlation constraints if available
        if context and "correlations" in context:
            weights = self.correlation_constraint.constrain_weights(
                weights, context["correlations"]
            )
            justification += " [correlation-constrained]"

        # Compute optimization score (0-1, higher = better diversification)
        diversification_score = self._compute_diversification_score(weights)

        allocation = StrategyAllocation(
            date=date.today(),
            method=self.method,
            allocations=weights,
            justification=justification,
            optimization_score=diversification_score,
        )

        self.allocation_history.append(allocation)
        return allocation

    @staticmethod
    def _compute_diversification_score(weights: Dict[str, float]) -> float:
        """
        Compute Herfindahl-Hirschman Index (HHI) as diversification score.

        HHI = sum(w_i^2), ranges from 0 (perfect diversification) to 1 (concentrated).
        Diversification score = 1 - HHI (so 1 is perfect diversification).
        """
        if not weights:
            return 0

        hhi = sum(w**2 for w in weights.values())
        return 1.0 - hhi

    def get_allocation_summary(self) -> Dict[str, Any]:
        """Get summary of recent allocations."""
        if not self.allocation_history:
            return {}

        latest = self.allocation_history[-1]

        return {
            "date": latest.date.isoformat(),
            "method": latest.method.value,
            "allocations": latest.allocations,
            "diversification_score": latest.optimization_score,
            "justification": latest.justification,
        }

    def switch_method(self, new_method: WeightingMethod) -> None:
        """Switch to a different weighting method."""
        self.method = new_method
        logger.info(f"Switched to {new_method.value} weighting method")
