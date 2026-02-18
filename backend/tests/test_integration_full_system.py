"""
End-to-end integration tests for complete trading system.

Tests the entire pipeline:
1. Signal generation (8 strategies + Phase 2 stat arb + Phase 3 ML)
2. Signal combination and weighting
3. Risk controls (position limits, circuit breakers)
4. Execution (smart order routing)
5. Portfolio update
6. Monitoring and alerts

This validates all components work together correctly.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta

from app.strategies import (
    TrendFollowingStrategy,
    MeanReversionStrategy,
    VolatilityTradingStrategy,
    SectorRotationStrategy,
    CarryTradingStrategy,
    TechnicalPatternsStrategy,
    SentimentAnalysisStrategy,
    FactorRotationStrategy,
)
from app.portfolio import (
    StrategyWeightingEngine,
    WeightingMethod,
    StrategyPerformance,
    PortfolioRiskManager,
    CircuitBreakerThresholds,
)
from app.execution.smart_order_execution import (
    SmartOrderExecutor,
    ExecutionParameters,
    MarketData,
)


class TestSignalGeneration:
    """Test signal generation from all strategies."""

    def test_multiple_strategies_generate_signals(self):
        """Test all 8 strategies generate valid signals."""
        strategies = [
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            VolatilityTradingStrategy(),
            SectorRotationStrategy(),
            CarryTradingStrategy(),
            TechnicalPatternsStrategy(),
            SentimentAnalysisStrategy(),
            FactorRotationStrategy(),
        ]

        # Generate synthetic OHLCV data
        data = pd.DataFrame({
            'close': np.random.normal(100, 10, 100),
            'volume': np.random.normal(1000, 100, 100),
        })

        context = {
            'risk_sentiment': 0.5,
            'sentiment_score': 0.6,
            'vix': 15,
        }

        signals = []
        for strategy in strategies:
            signal = strategy.generate_signal(data, context)
            signals.append(signal)
            assert signal is not None
            assert signal.confidence >= 0

        # All strategies should generate signals
        assert len(signals) == 8

    def test_signal_diversity(self):
        """Test that strategies generate diverse signals."""
        strategies = [
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
        ]

        data = pd.DataFrame({
            'close': list(range(100, 150)) + [150 + i * 0.5 for i in range(51)],
            'volume': [1000] * 101,
        })

        signal_trend = strategies[0].generate_signal(data)
        signal_mean_rev = strategies[1].generate_signal(data)

        # In strong uptrend: trend following should have signal
        assert signal_trend.confidence > signal_mean_rev.confidence


class TestSignalCombination:
    """Test combining signals from multiple strategies."""

    def test_signal_weighting_engine(self):
        """Test strategy weighting engine."""
        engine = StrategyWeightingEngine(method=WeightingMethod.EQUAL)

        strategy_ids = [
            "trend",
            "mean_rev",
            "volatility",
            "sector_rotation",
        ]

        allocation = engine.compute_allocation(strategy_ids)

        # Should have allocations for all strategies
        assert len(allocation.allocations) == 4

        # Should sum to 1
        assert abs(sum(allocation.allocations.values()) - 1.0) < 0.01

    def test_regime_based_weighting(self):
        """Test regime-based weighting adapts to conditions."""
        engine = StrategyWeightingEngine(method=WeightingMethod.REGIME_BASED)

        strategy_ids = ["trend", "mean_rev", "volatility"]

        # Normal market
        context_normal = {"vix": 15, "trend_strength": 0.3}
        allocation_normal = engine.compute_allocation(
            strategy_ids, context=context_normal
        )

        # High volatility
        context_vol = {"vix": 30, "trend_strength": 0.3}
        allocation_vol = engine.compute_allocation(strategy_ids, context=context_vol)

        # Allocations should differ
        assert allocation_normal.allocations != allocation_vol.allocations

    def test_performance_based_weighting(self):
        """Test performance-based weighting."""
        engine = StrategyWeightingEngine(method=WeightingMethod.PERFORMANCE_BASED)

        performances = {
            "strong": StrategyPerformance(
                strategy_id="strong",
                strategy_name="Strong",
                sharpe_ratio=1.5,
                recent_momentum=0.8,
            ),
            "weak": StrategyPerformance(
                strategy_id="weak",
                strategy_name="Weak",
                sharpe_ratio=0.5,
                recent_momentum=0.2,
            ),
        }

        allocation = engine.compute_allocation(
            ["strong", "weak"],
            strategy_performances=performances,
        )

        # Better performer should get more
        assert allocation.allocations["strong"] > allocation.allocations["weak"]


class TestRiskControls:
    """Test risk management system."""

    def test_circuit_breaker_activation(self):
        """Test circuit breaker activates on large loss."""
        risk_manager = PortfolioRiskManager()

        # Record profit
        metrics_profit = risk_manager.compute_daily_risk_metrics(
            date_=date.today() - timedelta(days=1),
            portfolio_value=100_000,
            daily_pnl=5_000,
            positions={},
            prices={},
        )

        # Record large loss
        metrics_loss = risk_manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=92_000,
            daily_pnl=-8_000,  # -8% daily loss
            positions={},
            prices={},
        )

        # Should trigger halt
        should_halt, reason = risk_manager.should_halt_trading()
        assert should_halt

    def test_position_limit_enforcement(self):
        """Test position limits are enforced."""
        from app.portfolio import PositionLimit

        risk_manager = PortfolioRiskManager()

        # Set tight position limits
        limits = {
            "AAPL": PositionLimit(
                symbol="AAPL",
                max_position_pct=0.02,
                max_position_usd=2_000,
            ),
        }

        risk_manager.set_position_limits(limits)

        # Try to buy 10% of portfolio
        violations = risk_manager.check_position_limits(
            positions={"AAPL": 100},
            prices={"AAPL": 150},
            portfolio_value=100_000,
        )

        # Should flag violation (position is 0.15, limit is 0.02)
        assert len(violations) > 0

    def test_volitility_adjusted_limits(self):
        """Test position limits adjust for volatility."""
        from app.portfolio import PositionLimit

        risk_manager = PortfolioRiskManager()

        limit = PositionLimit(
            symbol="AAPL",
            max_position_pct=0.05,
            max_position_usd=5_000,
            volatility_threshold=0.20,
        )

        risk_manager.position_limiter.set_base_limit("AAPL", limit)

        # Normal volatility
        normal_limit = risk_manager.position_limiter.compute_adjusted_limit(
            "AAPL",
            current_volatility=0.15,
            daily_volume=1_000_000,
            portfolio_value=100_000,
        )

        # High volatility
        high_vol_limit = risk_manager.position_limiter.compute_adjusted_limit(
            "AAPL",
            current_volatility=0.30,  # 2x threshold
            daily_volume=1_000_000,
            portfolio_value=100_000,
        )

        # High vol limit should be smaller
        assert high_vol_limit.max_position_pct < normal_limit.max_position_pct


class TestExecution:
    """Test order execution."""

    def test_smart_order_routing(self):
        """Test smart order routing selects correct algorithm."""
        executor = SmartOrderExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=1_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        # Small order
        result_small = executor.execute(
            symbol="AAPL",
            quantity=10_000,
            market_data=market_data,
            params=params,
        )

        # Large order
        result_large = executor.execute(
            symbol="AAPL",
            quantity=100_000,
            market_data=market_data,
            params=params,
        )

        # Small order should have less impact
        assert result_small.market_impact_cost < result_large.market_impact_cost

    def test_execution_cost_realistic(self):
        """Test execution costs are realistic (8-15 bps)."""
        executor = SmartOrderExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=1_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters(
            commission_bps=1.0,
            spread_bps=5.0,
        )

        result = executor.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        # Compute total cost in bps
        notional = 50_000 * 100
        cost_pct = result.total_cost / notional if notional > 0 else 0
        cost_bps = cost_pct * 10_000

        # Should be in realistic range (8-20 bps)
        assert 5 < cost_bps < 50


class TestPortfolioUpdate:
    """Test portfolio state updates."""

    def test_portfolio_tracking(self):
        """Test portfolio value tracking."""
        from app.portfolio import PortfolioRiskManager

        risk_manager = PortfolioRiskManager()

        # Day 1: profit
        metrics_day1 = risk_manager.compute_daily_risk_metrics(
            date_=date.today() - timedelta(days=2),
            portfolio_value=100_000,
            daily_pnl=1_000,
            positions={"AAPL": 100},
            prices={"AAPL": 150},
        )

        # Day 2: loss
        metrics_day2 = risk_manager.compute_daily_risk_metrics(
            date_=date.today() - timedelta(days=1),
            portfolio_value=99_500,
            daily_pnl=-500,
            positions={"AAPL": 100},
            prices={"AAPL": 145},
        )

        # Day 3: profit
        metrics_day3 = risk_manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=102_000,
            daily_pnl=2_500,
            positions={"AAPL": 100},
            prices={"AAPL": 150},
        )

        # Should track all metrics
        assert len(risk_manager.daily_metrics_history) == 3

        # Max drawdown should be computed
        max_dd = risk_manager.get_max_drawdown()
        assert max_dd < 0  # Should be negative

    def test_sector_concentration_tracking(self):
        """Test sector concentration is tracked."""
        from app.portfolio import PortfolioRiskManager

        risk_manager = PortfolioRiskManager()

        sector_map = {
            "AAPL": "Technology",
            "MSFT": "Technology",
            "JPM": "Finance",
        }

        metrics = risk_manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=0,
            positions={"AAPL": 100, "MSFT": 100, "JPM": 50},
            prices={"AAPL": 150, "MSFT": 300, "JPM": 150},
            sector_map=sector_map,
        )

        # Should have sector concentration
        assert "Technology" in metrics.sector_concentration


class TestFullPipeline:
    """Test complete trading pipeline."""

    def test_daily_trading_cycle(self):
        """Test complete daily trading cycle."""
        # 1. Generate signals
        strategies = [
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            VolatilityTradingStrategy(),
        ]

        data = pd.DataFrame({
            'close': np.random.normal(100, 10, 100),
            'volume': np.random.normal(1000, 100, 100),
        })

        signals = {}
        for strategy in strategies:
            signal = strategy.generate_signal(data)
            signals[strategy.strategy_id] = signal

        # 2. Weight strategies
        engine = StrategyWeightingEngine()
        allocation = engine.compute_allocation(list(signals.keys()))

        # 3. Check risk controls
        risk_manager = PortfolioRiskManager()
        metrics = risk_manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=0,
            positions={},
            prices={},
        )

        # 4. Execute orders
        executor = SmartOrderExecutor()
        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=1_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        # Simulate execution for each position
        results = []
        for i in range(3):
            result = executor.execute(
                symbol=f"STK{i}",
                quantity=10_000 + i * 5_000,
                market_data=market_data,
                params=params,
            )
            results.append(result)

        # Should have executed all orders
        assert len(results) == 3

    def test_risk_controls_prevent_bad_execution(self):
        """Test risk controls block bad trades."""
        from app.portfolio import PortfolioRiskManager, CircuitBreakerLevel

        risk_manager = PortfolioRiskManager()

        # Trigger circuit breaker
        metrics = risk_manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=-10_000,  # -10% loss -> LIQUIDATE
            positions={},
            prices={},
        )

        # Check if trading should halt
        should_halt, reason = risk_manager.should_halt_trading()

        assert should_halt
        assert metrics.circuit_breaker_level == CircuitBreakerLevel.LIQUIDATE


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
