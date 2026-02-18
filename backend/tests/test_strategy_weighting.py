"""
Tests for strategy weighting and optimization engine.

Tests cover:
- Equal weighting
- Performance-based weighting
- Risk parity weighting
- Regime-based weighting
- Correlation constraints
"""

import pytest
from datetime import date

from app.portfolio.strategy_weighting import (
    WeightingMethod,
    StrategyAllocation,
    StrategyPerformance,
    EqualWeightingOptimizer,
    PerformanceBasedOptimizer,
    RiskParityOptimizer,
    RegimeBasedOptimizer,
    CorrelationConstraint,
    StrategyWeightingEngine,
)


class TestEqualWeightingOptimizer:
    """Test equal weighting optimizer."""

    def test_equal_weights(self):
        """Test equal weighting."""
        optimizer = EqualWeightingOptimizer()

        strategies = ["trend", "mean_reversion", "volatility"]
        weights = optimizer.compute_weights(strategies)

        assert len(weights) == 3
        assert all(abs(w - 1/3) < 0.01 for w in weights.values())

    def test_empty_strategies(self):
        """Test with empty strategies."""
        optimizer = EqualWeightingOptimizer()
        weights = optimizer.compute_weights([])

        assert len(weights) == 0


class TestPerformanceBasedOptimizer:
    """Test performance-based optimizer."""

    def test_performance_weighting(self):
        """Test performance-based weighting."""
        optimizer = PerformanceBasedOptimizer()

        perf = {
            "trend": StrategyPerformance(
                strategy_id="trend",
                strategy_name="Trend",
                sharpe_ratio=1.5,
                recent_momentum=0.8,
            ),
            "mean_rev": StrategyPerformance(
                strategy_id="mean_rev",
                strategy_name="Mean Rev",
                sharpe_ratio=0.8,
                recent_momentum=0.4,
            ),
        }

        weights = optimizer.compute_weights(perf)

        # Better performer should get more weight
        assert weights["trend"] > weights["mean_rev"]

    def test_weights_sum_to_one(self):
        """Test weights sum to 1."""
        optimizer = PerformanceBasedOptimizer()

        perf = {
            "s1": StrategyPerformance("s1", "S1", sharpe_ratio=1.0),
            "s2": StrategyPerformance("s2", "S2", sharpe_ratio=0.5),
            "s3": StrategyPerformance("s3", "S3", sharpe_ratio=0.8),
        }

        weights = optimizer.compute_weights(perf)

        assert abs(sum(weights.values()) - 1.0) < 0.01


class TestRiskParityOptimizer:
    """Test risk parity optimizer."""

    def test_risk_parity_weighting(self):
        """Test risk parity weighting."""
        optimizer = RiskParityOptimizer()

        perf = {
            "low_vol": StrategyPerformance(
                strategy_id="low_vol",
                strategy_name="Low Vol",
                volatility=0.10,
            ),
            "high_vol": StrategyPerformance(
                strategy_id="high_vol",
                strategy_name="High Vol",
                volatility=0.20,
            ),
        }

        weights = optimizer.compute_weights(perf)

        # Low vol should get more weight
        assert weights["low_vol"] > weights["high_vol"]

    def test_weights_normalized(self):
        """Test weights are normalized."""
        optimizer = RiskParityOptimizer()

        perf = {
            "s1": StrategyPerformance("s1", "S1", volatility=0.15),
            "s2": StrategyPerformance("s2", "S2", volatility=0.20),
        }

        weights = optimizer.compute_weights(perf)

        assert abs(sum(weights.values()) - 1.0) < 0.01


class TestRegimeBasedOptimizer:
    """Test regime-based optimizer."""

    def test_regime_detection_normal(self):
        """Test regime detection under normal conditions."""
        optimizer = RegimeBasedOptimizer()

        context = {
            "vix": 15,
            "trend_strength": 0.3,
            "correlation": 0.5,
        }

        regime = optimizer.detect_regime(context)

        assert regime == "normal"

    def test_regime_detection_high_vol(self):
        """Test regime detection under high volatility."""
        optimizer = RegimeBasedOptimizer()

        context = {
            "vix": 30,
            "trend_strength": 0.3,
            "correlation": 0.5,
        }

        regime = optimizer.detect_regime(context)

        assert regime == "high_volatility"

    def test_regime_detection_trending(self):
        """Test regime detection in trending market."""
        optimizer = RegimeBasedOptimizer()

        context = {
            "vix": 15,
            "trend_strength": 0.8,
            "correlation": 0.5,
        }

        regime = optimizer.detect_regime(context)

        assert regime == "trending"

    def test_regime_weights(self):
        """Test weights are adjusted by regime."""
        optimizer = RegimeBasedOptimizer()

        strategies = ["trend", "mean_rev"]
        context = {
            "vix": 15,
            "trend_strength": 0.8,
            "correlation": 0.5,
        }

        weights = optimizer.compute_weights(strategies, context)

        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 0.01


class TestCorrelationConstraint:
    """Test correlation constraints."""

    def test_no_constraint_applied(self):
        """Test no constraint when correlation is low."""
        constraint = CorrelationConstraint(max_correlation_sum=5.0)

        weights = {"s1": 0.5, "s2": 0.5}
        correlations = {("s1", "s2"): 0.2}

        constrained = constraint.constrain_weights(weights, correlations)

        assert abs(constrained["s1"] - 0.5) < 0.1

    def test_constraint_applied(self):
        """Test constraint when correlation is high."""
        constraint = CorrelationConstraint(max_correlation_sum=0.1)

        weights = {"s1": 0.5, "s2": 0.5}
        correlations = {("s1", "s2"): 0.9}

        constrained = constraint.constrain_weights(weights, correlations)

        # Total weight should be reduced
        total = sum(constrained.values())
        assert total <= 1.0


class TestStrategyWeightingEngine:
    """Test strategy weighting engine."""

    def test_engine_initialization(self):
        """Test engine initializes."""
        engine = StrategyWeightingEngine()
        assert engine.method == WeightingMethod.PERFORMANCE_BASED

    def test_equal_weight_allocation(self):
        """Test equal weight allocation."""
        engine = StrategyWeightingEngine(method=WeightingMethod.EQUAL)

        strategies = ["trend", "mean_rev", "vol"]
        allocation = engine.compute_allocation(strategies)

        assert len(allocation.allocations) == 3
        assert abs(sum(allocation.allocations.values()) - 1.0) < 0.01

    def test_performance_based_allocation(self):
        """Test performance-based allocation."""
        engine = StrategyWeightingEngine(method=WeightingMethod.PERFORMANCE_BASED)

        performances = {
            "trend": StrategyPerformance("trend", "Trend", sharpe_ratio=1.5),
            "mean_rev": StrategyPerformance("mean_rev", "MR", sharpe_ratio=0.5),
        }

        allocation = engine.compute_allocation(
            ["trend", "mean_rev"],
            strategy_performances=performances,
        )

        assert allocation.allocations["trend"] > allocation.allocations["mean_rev"]

    def test_risk_parity_allocation(self):
        """Test risk parity allocation."""
        engine = StrategyWeightingEngine(method=WeightingMethod.RISK_PARITY)

        performances = {
            "low_vol": StrategyPerformance("low_vol", "LV", volatility=0.10),
            "high_vol": StrategyPerformance("high_vol", "HV", volatility=0.20),
        }

        allocation = engine.compute_allocation(
            ["low_vol", "high_vol"],
            strategy_performances=performances,
        )

        assert allocation.allocations["low_vol"] > allocation.allocations["high_vol"]

    def test_regime_based_allocation(self):
        """Test regime-based allocation."""
        engine = StrategyWeightingEngine(method=WeightingMethod.REGIME_BASED)

        context = {
            "vix": 30,
            "trend_strength": 0.3,
            "correlation": 0.5,
        }

        allocation = engine.compute_allocation(
            ["trend", "mean_rev", "vol"],
            context=context,
        )

        assert len(allocation.allocations) == 3

    def test_diversification_score(self):
        """Test diversification score calculation."""
        weights = {"s1": 0.25, "s2": 0.25, "s3": 0.25, "s4": 0.25}
        score = StrategyWeightingEngine._compute_diversification_score(weights)

        # Perfect diversification should score high
        assert score > 0.7

    def test_concentrated_diversification_score(self):
        """Test diversification score for concentrated portfolio."""
        weights = {"s1": 0.9, "s2": 0.1}
        score = StrategyWeightingEngine._compute_diversification_score(weights)

        # Concentrated portfolio should score low
        assert score < 0.3

    def test_allocation_history(self):
        """Test allocation history tracking."""
        engine = StrategyWeightingEngine()

        for _ in range(3):
            engine.compute_allocation(["trend", "mean_rev"])

        assert len(engine.allocation_history) == 3

    def test_method_switching(self):
        """Test switching weighting methods."""
        engine = StrategyWeightingEngine(method=WeightingMethod.EQUAL)

        assert engine.method == WeightingMethod.EQUAL

        engine.switch_method(WeightingMethod.RISK_PARITY)

        assert engine.method == WeightingMethod.RISK_PARITY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
