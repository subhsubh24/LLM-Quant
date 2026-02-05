"""
Tests for Execution Optimization - Phase 5

Tests cover:
- Time-of-day execution adjustment
- Liquidity crisis detection
- Execution failure recovery
- Real-time cost tracking
- Adaptive slippage modeling
"""

import pytest
from datetime import datetime, timedelta

from app.execution.execution_optimization import (
    TimeOfDayExecutor,
    LiquidityCrisisHandler,
    ExecutionFailureRecovery,
    RealTimeCostTracker,
    AdaptiveSlippageModel,
    OptimizedExecutionEngine,
    MARKET_PROFILES,
)


class TestTimeOfDayExecutor:
    """Test time-of-day execution adjustment."""

    def test_market_profiles_exist(self):
        """Test market profiles for all hours."""
        assert len(MARKET_PROFILES) > 0
        for hour, profile in MARKET_PROFILES.items():
            assert 9 <= hour <= 17
            assert 0 < profile.volume_factor < 2.0
            assert 0 < profile.spread_factor < 3.0

    def test_market_open_high_impact(self):
        """Test market open has high impact."""
        profile_open = MARKET_PROFILES.get(9)
        profile_mid = MARKET_PROFILES.get(14)

        assert profile_open.impact_factor > profile_mid.impact_factor

    def test_market_close_high_impact(self):
        """Test market close has high impact."""
        profile_close = MARKET_PROFILES.get(17)
        profile_mid = MARKET_PROFILES.get(14)

        assert profile_close.impact_factor > profile_mid.impact_factor

    def test_optimal_time(self):
        """Test optimal time detection."""
        profile_opt = MARKET_PROFILES.get(14)

        assert profile_opt.recommendation == "optimal"
        assert profile_opt.impact_factor == 1.0

    def test_adjust_urgency_at_open(self):
        """Test urgency increased at market open."""
        base_urgency = 0.5
        open_time = datetime(2024, 1, 1, 9, 30)

        adjusted = TimeOfDayExecutor.adjust_urgency(base_urgency, open_time)

        assert adjusted > base_urgency

    def test_adjust_urgency_at_optimal(self):
        """Test urgency decreased at optimal times."""
        base_urgency = 0.5
        optimal_time = datetime(2024, 1, 1, 14, 0)

        adjusted = TimeOfDayExecutor.adjust_urgency(base_urgency, optimal_time)

        assert adjusted < base_urgency

    def test_adjust_size_at_optimal(self):
        """Test size maintained/increased at optimal times."""
        target_size = 1000
        optimal_time = datetime(2024, 1, 1, 14, 0)

        adjusted = TimeOfDayExecutor.adjust_size(target_size, optimal_time)

        assert adjusted >= target_size * 0.8

    def test_adjust_size_at_open(self):
        """Test size increased at open (more liquidity)."""
        target_size = 1000
        open_time = datetime(2024, 1, 1, 9, 30)

        adjusted = TimeOfDayExecutor.adjust_size(target_size, open_time)

        assert adjusted > target_size


class TestLiquidityCrisisHandler:
    """Test liquidity crisis detection and handling."""

    def test_initialization(self):
        """Test initializes properly."""
        handler = LiquidityCrisisHandler()
        assert handler.daily_volume_threshold == 0.5
        assert not handler.in_crisis

    def test_normal_liquidity(self):
        """Test normal liquidity conditions."""
        handler = LiquidityCrisisHandler()

        is_crisis, severity = handler.detect_crisis(
            current_volume=1_000_000,
            historical_avg_volume=1_000_000,
        )

        assert not is_crisis
        assert severity == 0.0

    def test_liquidity_crisis_detection(self):
        """Test crisis detection when volume drops."""
        handler = LiquidityCrisisHandler()

        is_crisis, severity = handler.detect_crisis(
            current_volume=300_000,  # 30% of normal
            historical_avg_volume=1_000_000,
        )

        assert is_crisis
        assert severity > 0.4

    def test_crisis_severity_scaling(self):
        """Test severity scales with volume drop."""
        handler = LiquidityCrisisHandler()

        _, severity1 = handler.detect_crisis(400_000, 1_000_000)  # 40% of normal
        _, severity2 = handler.detect_crisis(200_000, 1_000_000)  # 20% of normal

        assert severity2 > severity1

    def test_adjust_for_crisis(self):
        """Test adjustment parameters in crisis."""
        handler = LiquidityCrisisHandler()
        handler.detect_crisis(300_000, 1_000_000)  # Trigger crisis

        target_size = 1000
        target_urgency = 0.8

        adjusted_size, adjusted_urgency = handler.adjust_for_crisis(target_size, target_urgency)

        # Both should be reduced
        assert adjusted_size < target_size
        assert adjusted_urgency < target_urgency


class TestExecutionFailureRecovery:
    """Test execution failure recovery with retries."""

    def test_initialization(self):
        """Test initializes properly."""
        recovery = ExecutionFailureRecovery()
        assert recovery.max_retries == 3
        assert recovery.initial_backoff == 2.0

    def test_should_retry(self):
        """Test retry decision logic."""
        recovery = ExecutionFailureRecovery()

        assert recovery.should_retry("order1", 0)
        assert recovery.should_retry("order1", 1)
        assert recovery.should_retry("order1", 2)
        assert not recovery.should_retry("order1", 3)

    def test_backoff_exponential(self):
        """Test exponential backoff."""
        recovery = ExecutionFailureRecovery(initial_backoff=2.0)

        backoff0 = recovery.compute_backoff(0)
        backoff1 = recovery.compute_backoff(1)
        backoff2 = recovery.compute_backoff(2)

        assert backoff1 == backoff0 * 2
        assert backoff2 == backoff1 * 2

    def test_backoff_capped(self):
        """Test backoff is capped at 60 seconds."""
        recovery = ExecutionFailureRecovery(initial_backoff=2.0)

        backoff10 = recovery.compute_backoff(10)

        assert backoff10 <= 60.0

    def test_retry_plan(self):
        """Test complete retry plan."""
        recovery = ExecutionFailureRecovery()

        plan = recovery.get_retry_plan("order1")

        assert len(plan) == 3
        assert plan[1] > plan[0]
        assert plan[2] > plan[1]


class TestRealTimeCostTracker:
    """Test real-time execution cost tracking."""

    def test_initialization(self):
        """Test initializes properly."""
        tracker = RealTimeCostTracker()
        assert len(tracker.execution_costs) == 0

    def test_record_execution(self):
        """Test recording execution."""
        tracker = RealTimeCostTracker()

        tracker.record_execution(
            order_id="order1",
            symbol="AAPL",
            quantity=1000,
            avg_price=100.0,
            reference_price=100.0,
            commission=10.0,
            market_impact=5.0,
            spread=2.0,
        )

        assert "order1" in tracker.execution_costs
        exec_cost = tracker.execution_costs["order1"]
        assert exec_cost['total_cost'] == 17.0

    def test_average_cost_bps(self):
        """Test average cost calculation."""
        tracker = RealTimeCostTracker()

        tracker.record_execution(
            "order1", "AAPL", 1000, 100.0, 100.0, 10.0, 5.0, 2.0
        )

        avg_bps = tracker.get_average_cost_bps()

        # 17 / (1000 * 100) * 10000 = 1.7 bps
        assert 1.5 < avg_bps < 2.0

    def test_cost_breakdown(self):
        """Test cost breakdown."""
        tracker = RealTimeCostTracker()

        tracker.record_execution(
            "order1", "AAPL", 1000, 100.0, 100.0, 10.0, 5.0, 2.0
        )

        breakdown = tracker.get_cost_breakdown()

        assert "commission_pct" in breakdown
        assert "market_impact_pct" in breakdown
        assert "spread_pct" in breakdown


class TestAdaptiveSlippageModel:
    """Test adaptive slippage modeling."""

    def test_initialization(self):
        """Test initializes properly."""
        model = AdaptiveSlippageModel()
        assert model.base_slippage_bps == 2.0

    def test_slippage_normal_conditions(self):
        """Test slippage estimation in normal conditions."""
        model = AdaptiveSlippageModel()

        slippage = model.estimate_slippage(
            order_size=50_000,
            daily_volume=1_000_000,
            current_volatility=0.15,
            spread_bps=5.0,
            is_market_open=False,
        )

        assert 0 < slippage < 100

    def test_slippage_high_participation(self):
        """Test higher slippage with high participation."""
        model = AdaptiveSlippageModel()

        slippage_low = model.estimate_slippage(
            10_000,
            1_000_000,
            0.15,
            5.0,
            False,
        )

        slippage_high = model.estimate_slippage(
            500_000,  # 50% of daily volume
            1_000_000,
            0.15,
            5.0,
            False,
        )

        assert slippage_high > slippage_low

    def test_slippage_at_market_open(self):
        """Test higher slippage at market open."""
        model = AdaptiveSlippageModel()

        slippage_closed = model.estimate_slippage(
            50_000, 1_000_000, 0.15, 5.0, False
        )

        slippage_open = model.estimate_slippage(
            50_000, 1_000_000, 0.15, 5.0, True
        )

        assert slippage_open > slippage_closed


class TestOptimizedExecutionEngine:
    """Test master execution optimization engine."""

    def test_initialization(self):
        """Test initializes properly."""
        engine = OptimizedExecutionEngine()
        assert engine.time_of_day is not None
        assert engine.liquidity_crisis is not None

    def test_optimize_normal_conditions(self):
        """Test optimization in normal conditions."""
        engine = OptimizedExecutionEngine()

        result = engine.optimize_execution(
            target_size=1000,
            target_urgency=0.5,
            current_time=datetime(2024, 1, 1, 14, 0),  # Optimal time
            current_volume=1_000_000,
            historical_avg_volume=1_000_000,
            current_volatility=0.15,
            spread_bps=5.0,
        )

        assert 'optimized_size' in result
        assert 'optimized_urgency' in result
        assert result['is_liquidity_crisis'] == False
        assert 'recommendation' in result

    def test_optimize_crisis_conditions(self):
        """Test optimization in crisis conditions."""
        engine = OptimizedExecutionEngine()

        result = engine.optimize_execution(
            target_size=1000,
            target_urgency=0.8,
            current_time=datetime(2024, 1, 1, 9, 30),  # Market open
            current_volume=300_000,  # Crisis volume
            historical_avg_volume=1_000_000,
            current_volatility=0.40,  # High volatility
            spread_bps=15.0,  # Wide spread
        )

        assert result['is_liquidity_crisis'] == True
        assert result['crisis_severity'] > 0.4
        assert result['optimized_size'] < 1000

    def test_optimization_recommendation(self):
        """Test execution recommendation."""
        engine = OptimizedExecutionEngine()

        result = engine.optimize_execution(
            1000, 0.2, datetime(2024, 1, 1, 14, 0),
            1_000_000, 1_000_000, 0.15, 5.0
        )

        assert result['recommendation'] in [
            "EXECUTE_QUICKLY",
            "PATIENT_EXECUTION",
            "NORMAL_VWAP",
            "REDUCE_SIZE",
            "DELAY_EXECUTION",
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
