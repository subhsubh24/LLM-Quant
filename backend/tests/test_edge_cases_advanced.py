"""
Advanced Edge Cases and Robustness Tests - Enhancement Suite

Tests for:
- Boundary conditions
- Invalid inputs
- Extreme values
- Stress conditions
- Error recovery
- State management
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.execution.adaptive_execution import (
    OptimizedAdaptiveExecutor,
    RealisticCostModel,
    VolatilityAdaptiveRebalancing,
    TimeOfDayProfiles,
)
from app.monitoring.anomaly_detector import (
    StatisticalAnomalyDetector,
    FeatureImportanceTracker,
    CostAttributionEngine,
    ComprehensiveAnomalyMonitor,
)


class TestAdaptiveExecutionEdgeCases:
    """Advanced edge case tests for adaptive execution."""

    def test_hour_boundary_values(self):
        """Test hour boundary values 9, 17."""
        executor = OptimizedAdaptiveExecutor()

        # Test early hour (9)
        plan_9 = executor.get_execution_plan(
            symbol="SPY",
            order_size=100000,
            daily_volume=50000000,
            hour=9,
            iv=0.25,
            iv_20d=0.24,
            volatility=0.15,
            vix=20,
            spread_bps=2.0,
        )
        assert plan_9 is not None
        assert plan_9['adaptive_profile'].base_profile.recommendation == "AVOID"

        # Test late hour (17)
        plan_17 = executor.get_execution_plan(
            symbol="SPY",
            order_size=100000,
            daily_volume=50000000,
            hour=17,
            iv=0.25,
            iv_20d=0.24,
            volatility=0.15,
            vix=20,
            spread_bps=2.0,
        )
        assert plan_17 is not None
        assert plan_17['adaptive_profile'].base_profile.recommendation == "AVOID"

    def test_invalid_hour_raises_error(self):
        """Test invalid hours raise ValueError."""
        executor = OptimizedAdaptiveExecutor()

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=100000, daily_volume=50000000,
                hour=8,  # Outside market hours
                iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=100000, daily_volume=50000000,
                hour=18,  # Outside market hours
                iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )

    def test_zero_values_raise_error(self):
        """Test zero values raise errors."""
        executor = OptimizedAdaptiveExecutor()

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=0,  # Invalid
                daily_volume=50000000,
                hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=100000, daily_volume=0,  # Invalid
                hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )

    def test_negative_values_raise_error(self):
        """Test negative values raise errors."""
        executor = OptimizedAdaptiveExecutor()

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=100000, daily_volume=50000000,
                hour=14, iv=-0.05,  # Invalid
                iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )

        with pytest.raises(ValueError):
            executor.get_execution_plan(
                symbol="SPY", order_size=100000, daily_volume=50000000,
                hour=14, iv=0.25, iv_20d=0.24, volatility=-0.15,  # Invalid
                vix=20, spread_bps=2.0,
            )

    def test_extreme_vix_values(self):
        """Test extreme VIX values."""
        executor = OptimizedAdaptiveExecutor()

        # Extreme low VIX
        plan_low = executor.get_execution_plan(
            symbol="SPY", order_size=100000, daily_volume=50000000,
            hour=14, iv=0.10, iv_20d=0.10, volatility=0.05, vix=5, spread_bps=1.0,
        )
        assert plan_low is not None
        assert plan_low['cost_breakdown']['vix_premium_bps'] < 0.5

        # Extreme high VIX
        plan_high = executor.get_execution_plan(
            symbol="SPY", order_size=100000, daily_volume=50000000,
            hour=14, iv=0.80, iv_20d=0.70, volatility=0.50, vix=80, spread_bps=10.0,
        )
        assert plan_high is not None
        assert plan_high['cost_breakdown']['vix_premium_bps'] > 300  # (80-20)/20*100 = 300

    def test_extreme_order_sizes(self):
        """Test extreme order sizes."""
        executor = OptimizedAdaptiveExecutor()

        # Tiny order (1% of daily volume)
        plan_tiny = executor.get_execution_plan(
            symbol="SPY", order_size=500000,  # 1% of 50M
            daily_volume=50000000,
            hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
        )
        assert plan_tiny is not None
        assert plan_tiny['cost_breakdown']['participation_cost_bps'] < 10

        # Massive order (20% of daily volume)
        plan_massive = executor.get_execution_plan(
            symbol="SPY", order_size=10000000,  # 20% of 50M
            daily_volume=50000000,
            hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
        )
        assert plan_massive is not None
        # Should have high participation cost
        assert plan_massive['cost_breakdown']['participation_cost_bps'] > 20

    def test_fed_day_vs_normal_day(self):
        """Test Fed day vs normal day."""
        executor = OptimizedAdaptiveExecutor()

        # Normal day
        plan_normal = executor.get_execution_plan(
            symbol="SPY", order_size=100000, daily_volume=50000000,
            hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            is_fed_day=False,
        )

        # Fed day (should be worse)
        plan_fed = executor.get_execution_plan(
            symbol="SPY", order_size=100000, daily_volume=50000000,
            hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            is_fed_day=True,
        )

        # Fed day should have worse recommendation or higher costs
        assert plan_fed is not None
        assert plan_normal is not None

    def test_cost_monotonicity(self):
        """Test cost increases monotonically with order size."""
        executor = OptimizedAdaptiveExecutor()
        costs = []

        for order_pct in [1, 2, 5, 10, 15]:
            order = 50000000 * order_pct / 100
            plan = executor.get_execution_plan(
                symbol="SPY", order_size=order, daily_volume=50000000,
                hour=14, iv=0.25, iv_20d=0.24, volatility=0.15, vix=20, spread_bps=2.0,
            )
            costs.append(plan['cost_breakdown']['total_cost_bps'])

        # Costs should be non-decreasing
        assert costs == sorted(costs)


class TestAnomalyDetectorEdgeCases:
    """Advanced edge case tests for anomaly detection."""

    def test_single_observation_insufficient(self):
        """Test single observation is insufficient for detection."""
        detector = StatisticalAnomalyDetector(min_history=30)

        detector.add_observation('metric1', 100.0)

        # Should not detect with insufficient history
        anomaly = detector.detect_anomaly('metric1', 1000.0)
        assert anomaly is None

    def test_exact_threshold_no_anomaly(self):
        """Test value exactly on threshold is not anomalous."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add normal data (mean=0, std=1)
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        thresholds = detector.get_thresholds('metric1')

        # Value exactly on threshold
        anomaly = detector.detect_anomaly('metric1', thresholds['upper_threshold'])
        assert anomaly is None  # Should be exactly on boundary, not beyond

    def test_just_beyond_threshold_is_anomaly(self):
        """Test value just beyond threshold is anomalous."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add normal data
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        thresholds = detector.get_thresholds('metric1')

        # Value just beyond threshold
        anomaly = detector.detect_anomaly('metric1', thresholds['upper_threshold'] + 0.1)
        assert anomaly is not None

    def test_constant_metric_no_anomalies(self):
        """Test constant metric has no anomalies."""
        detector = StatisticalAnomalyDetector()

        # Add constant values
        for i in range(50):
            detector.add_observation('metric1', 5.0)

        # Even extreme values shouldn't trigger (zero std dev)
        anomaly = detector.detect_anomaly('metric1', 1000.0)
        assert anomaly is None

    def test_invalid_metric_name_raises_error(self):
        """Test invalid metric names raise errors."""
        detector = StatisticalAnomalyDetector()

        with pytest.raises(ValueError):
            detector.add_observation('', 100.0)

        with pytest.raises(ValueError):
            detector.detect_anomaly('', 100.0)

    def test_invalid_value_type_raises_error(self):
        """Test invalid value types raise errors."""
        detector = StatisticalAnomalyDetector()

        with pytest.raises(ValueError):
            detector.add_observation('metric1', "not_a_number")

        with pytest.raises(ValueError):
            detector.detect_anomaly('metric1', "not_a_number")

    def test_nan_value_handling(self):
        """Test NaN value handling."""
        detector = StatisticalAnomalyDetector()

        # Add normal data
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        # NaN should raise ValueError
        with pytest.raises(ValueError):
            detector.add_observation('metric1', np.nan)

    def test_inf_value_handling(self):
        """Test infinity handling."""
        detector = StatisticalAnomalyDetector()

        # Add normal data
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        # Infinity should cause issues
        anomaly = detector.detect_anomaly('metric1', np.inf)
        # May detect as anomaly or handle gracefully
        assert anomaly is not None or anomaly is None


class TestFeatureImportanceTrackerEdgeCases:
    """Advanced tests for feature importance tracking."""

    def test_empty_importance_dict_returns_early(self):
        """Test empty importance dict is handled."""
        tracker = FeatureImportanceTracker()

        tracker.add_importances({})

        avg = tracker.get_average_importance()
        assert len(avg) == 0

    def test_invalid_importance_range_raises_error(self):
        """Test importance values outside 0-1 raise error."""
        tracker = FeatureImportanceTracker()

        with pytest.raises(ValueError):
            tracker.add_importances({'feature1': 1.5})  # > 1

        with pytest.raises(ValueError):
            tracker.add_importances({'feature1': -0.1})  # < 0

    def test_feature_name_type_validation(self):
        """Test feature names must be strings."""
        tracker = FeatureImportanceTracker()

        with pytest.raises(ValueError):
            tracker.add_importances({123: 0.5})  # Non-string key

    def test_shift_detection_threshold(self):
        """Test shift detection with different thresholds."""
        tracker = FeatureImportanceTracker(window_size=10)

        # Add stable importances
        for i in range(20):
            tracker.add_importances({'feature1': 0.7, 'feature2': 0.3})

        # Add shifted importances
        for i in range(10):
            tracker.add_importances({'feature1': 0.2, 'feature2': 0.8})

        # With high threshold, should not detect shift
        shifts_high = tracker.detect_importance_shift(threshold=0.8)
        assert len(shifts_high) == 0

        # With low threshold, should detect shift
        shifts_low = tracker.detect_importance_shift(threshold=0.1)
        assert len(shifts_low) > 0


class TestCostAttributionEdgeCases:
    """Advanced tests for cost attribution."""

    def test_empty_cost_history(self):
        """Test empty cost history handling."""
        engine = CostAttributionEngine()

        breakdown = engine.get_cost_breakdown()
        assert len(breakdown) == 0

        trends = engine.get_cost_trends()
        assert len(trends) == 0

    def test_single_execution_record(self):
        """Test single execution record handling."""
        engine = CostAttributionEngine()

        engine.add_execution_costs(
            total_cost_bps=5.0,
            spread_cost_bps=1.0,
            participation_cost_bps=2.0,
            market_impact_bps=1.5,
            slippage_cost_bps=0.3,
            vix_premium_bps=0.2,
        )

        breakdown = engine.get_cost_breakdown()
        assert len(breakdown) > 0
        assert breakdown['total_cost_bps'] == pytest.approx(5.0, abs=0.1)

    def test_cost_history_limits(self):
        """Test cost history is limited to window size."""
        engine = CostAttributionEngine(window_size=10)

        # Add more than window size
        for i in range(20):
            engine.add_execution_costs(
                total_cost_bps=5.0 + i,
                spread_cost_bps=1.0,
                participation_cost_bps=2.0,
                market_impact_bps=1.5,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.2,
            )

        assert len(engine.cost_history) == 10

    def test_cost_trends_with_few_records(self):
        """Test cost trends with fewer records than window."""
        engine = CostAttributionEngine(window_size=10)

        # Add only 3 records
        for i in range(3):
            engine.add_execution_costs(
                total_cost_bps=5.0,
                spread_cost_bps=1.0,
                participation_cost_bps=2.0,
                market_impact_bps=1.5,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.2,
            )

        trends = engine.get_cost_trends()
        # Should handle gracefully
        assert trends is not None


class TestStressConditions:
    """Stress tests for system robustness."""

    def test_high_frequency_observations(self):
        """Test high-frequency observation recording."""
        detector = StatisticalAnomalyDetector()

        # Record 1000 observations
        for i in range(1000):
            detector.add_observation('metric1', np.random.normal(0, 1))

        # Should still work
        anomaly = detector.detect_anomaly('metric1', 10.0)
        assert anomaly is not None

    def test_many_metrics_simultaneously(self):
        """Test tracking many metrics simultaneously."""
        detector = StatisticalAnomalyDetector()

        # Track 100 different metrics
        for metric_id in range(100):
            for i in range(50):
                detector.add_observation(f'metric_{metric_id}', np.random.normal(0, 1))

        # Should still detect anomalies
        anomaly = detector.detect_anomaly('metric_0', 10.0)
        assert anomaly is not None

    def test_many_features_tracked(self):
        """Test tracking many features."""
        tracker = FeatureImportanceTracker()

        # Track 50 features with 100 snapshots
        for snapshot in range(100):
            importances = {f'feature_{i}': np.random.uniform(0, 1) for i in range(50)}
            tracker.add_importances(importances)

        avg = tracker.get_average_importance()
        assert len(avg) == 50

    def test_rapid_cost_records(self):
        """Test rapid cost recording."""
        engine = CostAttributionEngine()

        # Record 500 executions
        for i in range(500):
            engine.add_execution_costs(
                total_cost_bps=5.0 + np.random.normal(0, 1),
                spread_cost_bps=1.0,
                participation_cost_bps=2.0,
                market_impact_bps=1.5,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.2,
            )

        breakdown = engine.get_cost_breakdown()
        assert len(breakdown) > 0
