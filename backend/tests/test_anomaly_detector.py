"""
Tests for anomaly detection - Phase 15

Validates:
- Statistical anomaly detection (3-sigma)
- Feature importance tracking
- Cost attribution analysis
- Comprehensive anomaly monitor
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

from app.monitoring.anomaly_detector import (
    AnomalyEvent,
    StatisticalAnomalyDetector,
    FeatureImportanceTracker,
    CostAttributionEngine,
    ComprehensiveAnomalyMonitor,
)


class TestAnomalyEvent:
    """Test anomaly event dataclass."""

    def test_create_anomaly_event(self):
        """Test creating anomaly event."""
        event = AnomalyEvent(
            timestamp=datetime.now(),
            metric_name='sharpe_ratio',
            value=5.0,
            threshold_upper=4.0,
            threshold_lower=2.0,
            severity=0.8,
            description='Sharpe ratio abnormally high',
        )

        assert event.metric_name == 'sharpe_ratio'
        assert event.severity == 0.8


class TestStatisticalAnomalyDetector:
    """Test statistical anomaly detection."""

    def test_initialization(self):
        """Test detector initializes."""
        detector = StatisticalAnomalyDetector(
            lookback_window=252,
            num_sigmas=3.0,
            min_history=30,
        )
        assert detector is not None

    def test_add_observation(self):
        """Test adding observations."""
        detector = StatisticalAnomalyDetector()

        # Add normal observations
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        assert 'metric1' in detector.metric_history
        assert len(detector.metric_history['metric1']) == 50

    def test_detect_high_anomaly(self):
        """Test detecting high anomaly (above 3-sigma)."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add normal observations (mean=0, std=1)
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        # Add anomalous value (way above threshold)
        anomaly = detector.detect_anomaly('metric1', 10.0)

        assert anomaly is not None
        assert anomaly.value == 10.0
        assert anomaly.severity > 0.5

    def test_detect_low_anomaly(self):
        """Test detecting low anomaly (below -3 sigma)."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add normal observations
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(5, 1))

        # Add anomalous low value
        anomaly = detector.detect_anomaly('metric1', -5.0)

        assert anomaly is not None
        assert anomaly.severity > 0.5

    def test_no_anomaly_within_threshold(self):
        """Test no anomaly for values within thresholds."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add normal observations
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        # Value within threshold
        anomaly = detector.detect_anomaly('metric1', 0.5)

        assert anomaly is None

    def test_get_thresholds(self):
        """Test getting thresholds."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Add observations
        for i in range(50):
            detector.add_observation('metric1', np.random.normal(0, 1))

        thresholds = detector.get_thresholds('metric1')

        assert thresholds is not None
        assert 'mean' in thresholds
        assert 'std' in thresholds
        assert 'upper_threshold' in thresholds
        assert 'lower_threshold' in thresholds
        assert thresholds['upper_threshold'] > thresholds['mean']
        assert thresholds['lower_threshold'] < thresholds['mean']

    def test_insufficient_history(self):
        """Test no anomaly detection with insufficient history."""
        detector = StatisticalAnomalyDetector(min_history=30)

        # Add only 10 observations
        for i in range(10):
            detector.add_observation('metric1', np.random.normal(0, 1))

        anomaly = detector.detect_anomaly('metric1', 10.0)

        assert anomaly is None


class TestFeatureImportanceTracker:
    """Test feature importance tracking."""

    def test_initialization(self):
        """Test tracker initializes."""
        tracker = FeatureImportanceTracker(window_size=63)
        assert tracker is not None

    def test_add_importances(self):
        """Test adding importance snapshots."""
        tracker = FeatureImportanceTracker()

        importances = {
            'feature_1': 0.5,
            'feature_2': 0.3,
            'feature_3': 0.2,
        }

        tracker.add_importances(importances, timestamp=datetime.now())

        assert len(tracker.importance_history) == 3
        assert tracker.importance_history['feature_1'][0] == 0.5

    def test_get_average_importance(self):
        """Test getting average importance."""
        tracker = FeatureImportanceTracker(window_size=10)

        # Add multiple snapshots
        for i in range(20):
            importances = {
                'feature_1': 0.5 + np.random.normal(0, 0.05),
                'feature_2': 0.3 + np.random.normal(0, 0.05),
            }
            tracker.add_importances(importances)

        avg = tracker.get_average_importance()

        assert 'feature_1' in avg
        assert 'feature_2' in avg
        assert avg['feature_1'] > avg['feature_2']  # feature_1 more important

    def test_detect_importance_shift(self):
        """Test detecting significant importance shifts."""
        tracker = FeatureImportanceTracker(window_size=10)

        # Add snapshots with stable importance
        for i in range(20):
            importances = {
                'feature_1': 0.5,
                'feature_2': 0.3,
            }
            tracker.add_importances(importances)

        # Add snapshots with shifted importance
        for i in range(10):
            importances = {
                'feature_1': 0.2,  # Dropped from 0.5
                'feature_2': 0.6,  # Increased from 0.3
            }
            tracker.add_importances(importances)

        shifts = tracker.detect_importance_shift(threshold=0.2)

        # Should detect significant shifts
        assert len(shifts) > 0

    def test_get_top_features(self):
        """Test getting top N features."""
        tracker = FeatureImportanceTracker()

        # Add snapshots
        for i in range(10):
            importances = {
                'feature_1': 0.7,
                'feature_2': 0.2,
                'feature_3': 0.1,
            }
            tracker.add_importances(importances)

        top = tracker.get_top_features(n=2)

        assert len(top) <= 2
        assert top[0][0] == 'feature_1'  # Most important


class TestCostAttributionEngine:
    """Test cost attribution analysis."""

    def test_initialization(self):
        """Test engine initializes."""
        engine = CostAttributionEngine(window_size=63)
        assert engine is not None

    def test_add_execution_costs(self):
        """Test adding execution costs."""
        engine = CostAttributionEngine()

        engine.add_execution_costs(
            total_cost_bps=5.0,
            spread_cost_bps=1.0,
            participation_cost_bps=2.0,
            market_impact_bps=1.5,
            slippage_cost_bps=0.3,
            vix_premium_bps=0.2,
        )

        assert len(engine.cost_history) == 1

    def test_get_cost_breakdown(self):
        """Test getting cost breakdown."""
        engine = CostAttributionEngine()

        # Add multiple costs
        for i in range(10):
            engine.add_execution_costs(
                total_cost_bps=5.0 + np.random.normal(0, 0.5),
                spread_cost_bps=1.0,
                participation_cost_bps=2.0,
                market_impact_bps=1.5,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.2,
            )

        breakdown = engine.get_cost_breakdown()

        assert 'spread_cost_bps' in breakdown
        assert 'participation_cost_bps' in breakdown
        assert breakdown['spread_cost_bps'] == pytest.approx(1.0, abs=0.1)

    def test_get_cost_trends(self):
        """Test getting cost trends."""
        engine = CostAttributionEngine(window_size=10)

        # Add costs with trend
        for i in range(20):
            cost = 5.0 + i * 0.1  # Increasing trend
            engine.add_execution_costs(
                total_cost_bps=cost,
                spread_cost_bps=1.0,
                participation_cost_bps=2.0,
                market_impact_bps=1.5,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.2,
            )

        trends = engine.get_cost_trends()

        assert 'total_cost' in trends
        # Should detect increasing trend
        assert trends['total_cost']['trend_pct'] > 0

    def test_identify_cost_drivers(self):
        """Test identifying cost drivers."""
        engine = CostAttributionEngine()

        # Add costs where participation dominates
        for i in range(5):
            engine.add_execution_costs(
                total_cost_bps=5.0,
                spread_cost_bps=0.5,
                participation_cost_bps=3.0,  # Largest
                market_impact_bps=0.8,
                slippage_cost_bps=0.3,
                vix_premium_bps=0.4,
            )

        drivers = engine.identify_cost_drivers()

        # First driver should be participation
        assert drivers[0]['component'] == 'participation'
        assert drivers[0]['cost_bps'] > drivers[1]['cost_bps']


class TestComprehensiveMonitor:
    """Test comprehensive anomaly monitor."""

    def test_initialization(self):
        """Test monitor initializes."""
        monitor = ComprehensiveAnomalyMonitor()
        assert monitor is not None

    def test_monitor_sharpe_ratio(self):
        """Test monitoring Sharpe ratio."""
        monitor = ComprehensiveAnomalyMonitor()

        # Add normal Sharpe values
        for i in range(50):
            monitor.monitor_sharpe_ratio(np.random.normal(3.0, 0.5))

        # Should be healthy
        status = monitor.get_health_status()
        assert status['status'] in ['HEALTHY', 'CAUTION']

        # Add anomalous value
        monitor.monitor_sharpe_ratio(10.0)

        # Should detect
        status = monitor.get_health_status()
        assert status['anomaly_count'] > 0

    def test_monitor_drawdown(self):
        """Test monitoring drawdown."""
        monitor = ComprehensiveAnomalyMonitor()

        # Add normal drawdowns
        for i in range(50):
            monitor.monitor_drawdown(np.random.normal(-0.05, 0.02))

        # Add extreme drawdown
        monitor.monitor_drawdown(-0.40)

        status = monitor.get_health_status()
        assert status['anomaly_count'] > 0

    def test_monitor_volatility(self):
        """Test monitoring volatility."""
        monitor = ComprehensiveAnomalyMonitor()

        # Add normal volatilities
        for i in range(50):
            monitor.monitor_volatility(np.random.normal(0.15, 0.03))

        # Add spike
        monitor.monitor_volatility(0.80)

        status = monitor.get_health_status()
        assert status['anomaly_count'] > 0

    def test_get_health_status(self):
        """Test health status computation."""
        monitor = ComprehensiveAnomalyMonitor()

        status = monitor.get_health_status()

        assert 'status' in status
        assert 'anomaly_count' in status
        assert 'avg_severity' in status
        assert status['status'] in ['HEALTHY', 'CAUTION', 'WARNING', 'CRITICAL']

    def test_get_alert_summary(self):
        """Test getting alert summary."""
        monitor = ComprehensiveAnomalyMonitor()

        # Induce some anomalies
        for i in range(50):
            monitor.monitor_sharpe_ratio(np.random.normal(3.0, 0.5))
            monitor.monitor_volatility(np.random.normal(0.15, 0.03))

        # Add anomalies
        monitor.monitor_sharpe_ratio(8.0)
        monitor.monitor_volatility(0.60)

        alerts = monitor.get_alert_summary(max_alerts=5)

        assert len(alerts) > 0
        assert all('timestamp' in a for a in alerts)
        assert all('severity' in a for a in alerts)

    def test_health_status_with_many_anomalies(self):
        """Test status with many anomalies."""
        monitor = ComprehensiveAnomalyMonitor()

        # Add many anomalies
        for i in range(30):
            monitor.monitor_sharpe_ratio(10.0)
            monitor.monitor_drawdown(-0.50)

        status = monitor.get_health_status()

        # Should be critical or warning
        assert status['status'] in ['CRITICAL', 'WARNING']
        assert status['anomaly_count'] > 20


class TestAnomalyIntegration:
    """Integration tests for anomaly detection."""

    def test_full_monitoring_pipeline(self):
        """Test complete monitoring pipeline."""
        monitor = ComprehensiveAnomalyMonitor()

        # Simulate trading day
        for hour in range(8, 17):
            # Normal metrics
            sharpe = np.random.normal(3.0, 0.3)
            drawdown = np.random.normal(-0.03, 0.01)
            vol = np.random.normal(0.15, 0.02)
            corr = np.random.normal(0.35, 0.05)

            monitor.monitor_sharpe_ratio(sharpe)
            monitor.monitor_drawdown(drawdown)
            monitor.monitor_volatility(vol)
            monitor.monitor_correlation(corr)

        # At end of day
        status = monitor.get_health_status()

        assert 'status' in status
        assert status['anomaly_count'] >= 0

    def test_anomaly_severity_scaling(self):
        """Test that severity scales with magnitude."""
        detector = StatisticalAnomalyDetector(num_sigmas=3.0)

        # Build baseline
        for i in range(50):
            detector.add_observation('metric', np.random.normal(0, 1))

        # Mild anomaly
        mild = detector.detect_anomaly('metric', 4.0)
        assert mild is not None

        # Strong anomaly
        strong = detector.detect_anomaly('metric', 10.0)
        assert strong is not None

        # Strong should be more severe
        assert strong.severity > mild.severity
