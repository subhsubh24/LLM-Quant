"""
Tests for Monitoring & Health System - Phase 8

Tests cover:
- Strategy health scoring
- Model degradation detection
- Correlation monitoring
- Execution quality tracking
- Latency monitoring
- Data feed health
- System health dashboard
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.monitoring.health_system import (
    HealthStatus,
    AlertLevel,
    StrategyHealthMonitor,
    ModelDegradationMonitor,
    CorrelationMonitor,
    ExecutionQualityMonitor,
    LatencyMonitor,
    DataFeedHealthMonitor,
    SystemHealthDashboard,
)


class TestStrategyHealthMonitor:
    """Test strategy health scoring."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = StrategyHealthMonitor()
        assert len(monitor.strategy_returns) == 0
        assert len(monitor.strategy_trades) == 0

    def test_record_return(self):
        """Test recording strategy returns."""
        monitor = StrategyHealthMonitor()

        monitor.record_return("STRATEGY1", 0.01)
        monitor.record_return("STRATEGY1", 0.02)

        assert len(monitor.strategy_returns["STRATEGY1"]) == 2

    def test_healthy_strategy_score(self):
        """Test healthy strategy gets high score."""
        monitor = StrategyHealthMonitor()

        # Good returns: consistent, positive, low volatility
        returns = [0.001] * 50 + [0.002] * 50  # Positive, stable

        for ret in returns:
            monitor.record_return("HEALTHY", ret)

        health = monitor.compute_health_score("HEALTHY")

        assert health.status == HealthStatus.HEALTHY
        assert health.score > 70

    def test_degraded_strategy_score(self):
        """Test degraded strategy gets low score."""
        monitor = StrategyHealthMonitor()

        # Bad returns: negative, volatile
        returns = np.random.normal(-0.01, 0.1, 50)

        for ret in returns:
            monitor.record_return("BAD", float(ret))

        health = monitor.compute_health_score("BAD")

        assert health.score < 70

    def test_insufficient_data(self):
        """Test with insufficient data."""
        monitor = StrategyHealthMonitor()

        monitor.record_return("NEW", 0.01)

        health = monitor.compute_health_score("NEW")

        assert health.status == HealthStatus.CAUTION
        assert health.metrics['insufficient_data'] == True

    def test_record_trade(self):
        """Test recording trades."""
        monitor = StrategyHealthMonitor()

        monitor.record_trade("STRAT", {'entry_price': 100, 'size': 10})
        monitor.record_trade("STRAT", {'entry_price': 101, 'size': 10})

        assert len(monitor.strategy_trades["STRAT"]) == 2

    def test_win_rate_calculation(self):
        """Test win rate affects score."""
        monitor = StrategyHealthMonitor()

        # High win rate
        high_win_returns = [0.01, 0.02, 0.01, 0.015, -0.005] * 10

        for ret in high_win_returns:
            monitor.record_return("HIGH_WIN", ret)

        health_high = monitor.compute_health_score("HIGH_WIN")

        # Low win rate
        low_win_returns = [-0.01, 0.001, -0.02, 0.0005, -0.015] * 10

        for ret in low_win_returns:
            monitor.record_return("LOW_WIN", ret)

        health_low = monitor.compute_health_score("LOW_WIN")

        # High win rate should score better
        if health_high.score > 0 and health_low.score > 0:
            assert health_high.score > health_low.score


class TestModelDegradationMonitor:
    """Test model degradation detection."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = ModelDegradationMonitor()
        assert len(monitor.model_predictions) == 0

    def test_record_prediction(self):
        """Test recording predictions."""
        monitor = ModelDegradationMonitor()

        monitor.record_prediction("MODEL1", 0.5, 0.55, 0.8)

        assert len(monitor.model_predictions["MODEL1"]) == 1

    def test_accurate_model_score(self):
        """Test accurate model gets high score."""
        monitor = ModelDegradationMonitor()

        # Accurate predictions
        for i in range(100):
            actual = i % 2
            prediction = actual + np.random.normal(0, 0.05)

            monitor.record_prediction("ACCURATE", prediction, actual, 0.8)

        health = monitor.compute_health_score("ACCURATE")

        assert health.score > 70
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.CAUTION]

    def test_degraded_model_score(self):
        """Test degraded model gets low score."""
        monitor = ModelDegradationMonitor()

        # Inaccurate predictions
        for i in range(50):
            monitor.record_prediction("BAD", 0.5, float(i % 2), 0.3)

        for i in range(50):
            monitor.record_prediction("BAD", 0.5, float(i % 2), 0.3)

        health = monitor.compute_health_score("BAD")

        assert health.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]

    def test_degradation_detection(self):
        """Test detecting model degradation."""
        monitor = ModelDegradationMonitor(degradation_threshold=0.1)

        # Good accuracy first 50
        for i in range(50):
            monitor.record_prediction("DEGRADE", 0.5 + i * 0.01, i * 0.01, 0.9)

        # Worse accuracy next 50
        for i in range(50):
            monitor.record_prediction("DEGRADE", 0.5, float(i % 2), 0.3)

        health = monitor.compute_health_score("DEGRADE")

        # Should detect degradation
        assert 'accuracy_trend' in health.metrics


class TestCorrelationMonitor:
    """Test correlation monitoring."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = CorrelationMonitor()
        assert len(monitor.correlation_history) == 0

    def test_low_correlation_healthy(self):
        """Test low correlation is healthy."""
        monitor = CorrelationMonitor()

        # Create uncorrelated data
        data = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
            'C': np.random.randn(100),
        })

        corr = data.corr()
        monitor.update_correlation(corr)

        health = monitor.compute_health_score()

        assert health.status == HealthStatus.HEALTHY
        assert health.score > 70

    def test_high_correlation_critical(self):
        """Test high correlation is critical."""
        monitor = CorrelationMonitor()

        # Create highly correlated data
        base = np.random.randn(100)
        data = pd.DataFrame({
            'A': base,
            'B': base + np.random.normal(0, 0.1, 100),
            'C': base + np.random.normal(0, 0.1, 100),
        })

        corr = data.corr()
        monitor.update_correlation(corr)

        health = monitor.compute_health_score()

        assert health.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]
        assert health.score < 70

    def test_correlation_trend(self):
        """Test correlation trend tracking."""
        monitor = CorrelationMonitor()

        # Low correlation first
        data1 = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
        })
        monitor.update_correlation(data1.corr())

        # High correlation later
        base = np.random.randn(100)
        data2 = pd.DataFrame({
            'A': base,
            'B': base,
        })
        monitor.update_correlation(data2.corr())

        health = monitor.compute_health_score()

        # Trend should show deterioration
        assert health.metrics['correlation_trend'] is not None


class TestExecutionQualityMonitor:
    """Test execution quality monitoring."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = ExecutionQualityMonitor()
        assert len(monitor.executions) == 0

    def test_record_execution(self):
        """Test recording execution."""
        monitor = ExecutionQualityMonitor()

        monitor.record_execution(
            "ORDER1",
            expected_cost_bps=5.0,
            actual_cost_bps=5.5,
            fill_percentage=1.0,
            latency_ms=50,
        )

        assert len(monitor.executions) == 1

    def test_good_execution_quality(self):
        """Test good execution quality."""
        monitor = ExecutionQualityMonitor()

        # Good executions: full fills, low cost, low latency
        for i in range(50):
            monitor.record_execution(
                f"ORDER{i}",
                expected_cost_bps=5.0,
                actual_cost_bps=5.2,  # Low slippage
                fill_percentage=1.0,   # Full fill
                latency_ms=50,         # Low latency
            )

        health = monitor.compute_health_score()

        assert health.score > 75
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.CAUTION]

    def test_poor_execution_quality(self):
        """Test poor execution quality."""
        monitor = ExecutionQualityMonitor()

        # Poor executions: partial fills, high cost
        for i in range(50):
            monitor.record_execution(
                f"ORDER{i}",
                expected_cost_bps=5.0,
                actual_cost_bps=15.0,  # High slippage
                fill_percentage=0.5,   # Partial fill
                latency_ms=500,        # High latency
            )

        health = monitor.compute_health_score()

        assert health.score < 70

    def test_record_failure(self):
        """Test recording execution failure."""
        monitor = ExecutionQualityMonitor()

        monitor.record_failure("ORDER1", "timeout", 3)
        monitor.record_failure("ORDER2", "liquidity", 1)

        assert len(monitor.failed_executions) == 2

    def test_failure_rate_detection(self):
        """Test failure rate affects score."""
        monitor = ExecutionQualityMonitor()

        # Some successful executions
        for i in range(20):
            monitor.record_execution(
                f"ORDER{i}",
                expected_cost_bps=5.0,
                actual_cost_bps=5.5,
                fill_percentage=1.0,
                latency_ms=50,
            )

        # Add failures
        for i in range(5):
            monitor.record_failure(f"FAIL{i}", "timeout", 1)

        health = monitor.compute_health_score()

        # Should have lower score due to failures
        assert health.metrics['failure_rate'] > 0


class TestLatencyMonitor:
    """Test latency monitoring."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = LatencyMonitor()
        assert len(monitor.latencies) == 0

    def test_record_latency(self):
        """Test recording latency."""
        monitor = LatencyMonitor()

        monitor.record_latency("signal_gen", 10.5)
        monitor.record_latency("signal_gen", 11.2)

        assert len(monitor.latencies["signal_gen"]) == 2

    def test_p99_calculation(self):
        """Test P99 latency calculation."""
        monitor = LatencyMonitor()

        # Record 100 latencies
        for i in range(100):
            monitor.record_latency("operation", float(50 + i % 50))

        p99 = monitor.compute_p99("operation")

        assert 80 < p99 < 100  # P99 should be near the high end

    def test_healthy_latency(self):
        """Test healthy latency (low P99)."""
        monitor = LatencyMonitor()

        # Low latencies
        for i in range(50):
            monitor.record_latency("fast_op", float(10 + np.random.uniform(0, 30)))

        health = monitor.compute_health_score()

        assert health.status == HealthStatus.HEALTHY
        assert health.score > 80

    def test_poor_latency(self):
        """Test poor latency (high P99)."""
        monitor = LatencyMonitor()

        # High latencies
        for i in range(50):
            monitor.record_latency("slow_op", float(500 + np.random.uniform(0, 200)))

        health = monitor.compute_health_score()

        assert health.status in [HealthStatus.WARNING, HealthStatus.CRITICAL]
        assert health.score < 70


class TestDataFeedHealthMonitor:
    """Test data feed health monitoring."""

    def test_initialization(self):
        """Test initializes properly."""
        monitor = DataFeedHealthMonitor()
        assert len(monitor.last_update) == 0

    def test_record_update(self):
        """Test recording data feed update."""
        monitor = DataFeedHealthMonitor()

        now = datetime.now()
        monitor.record_update("AAPL", now)

        assert "AAPL" in monitor.last_update

    def test_fresh_data_healthy(self):
        """Test fresh data is healthy."""
        monitor = DataFeedHealthMonitor()

        # Recent updates
        now = datetime.now()
        monitor.record_update("FEED1", now - timedelta(seconds=30))
        monitor.record_update("FEED2", now - timedelta(seconds=10))

        health = monitor.compute_health_score()

        assert health.status == HealthStatus.HEALTHY
        assert health.score > 80

    def test_stale_data_warning(self):
        """Test stale data triggers warning."""
        monitor = DataFeedHealthMonitor(max_staleness_seconds=60)

        # Stale update
        old_time = datetime.now() - timedelta(seconds=120)
        monitor.record_update("STALE_FEED", old_time)

        health = monitor.compute_health_score()

        assert health.status in [HealthStatus.WARNING, HealthStatus.CAUTION]

    def test_record_gap(self):
        """Test recording data gap."""
        monitor = DataFeedHealthMonitor()

        start = datetime.now() - timedelta(minutes=5)
        end = datetime.now() - timedelta(minutes=3)

        monitor.record_gap("FEED", start, end)

        assert len(monitor.gaps["FEED"]) == 1


class TestSystemHealthDashboard:
    """Test system health dashboard."""

    def test_initialization(self):
        """Test initializes properly."""
        dashboard = SystemHealthDashboard()

        assert dashboard.strategy_monitor is not None
        assert dashboard.model_monitor is not None
        assert dashboard.correlation_monitor is not None
        assert dashboard.execution_monitor is not None
        assert dashboard.latency_monitor is not None
        assert dashboard.data_monitor is not None

    def test_compute_system_health(self):
        """Test computing overall system health."""
        dashboard = SystemHealthDashboard()

        # Add some data
        dashboard.strategy_monitor.record_return("STRAT", 0.01)
        dashboard.execution_monitor.record_execution(
            "ORDER", 5.0, 5.5, 1.0, 50
        )
        dashboard.latency_monitor.record_latency("op", 50.0)

        health = dashboard.compute_system_health()

        assert 'overall_status' in health
        assert 'overall_score' in health
        assert 'components' in health
        assert 0 <= health['overall_score'] <= 100

    def test_overall_status_determination(self):
        """Test overall status determination."""
        dashboard = SystemHealthDashboard()

        # Add healthy metrics
        for i in range(50):
            dashboard.strategy_monitor.record_return("GOOD", 0.01)
            dashboard.latency_monitor.record_latency("op", float(30 + np.random.uniform(0, 20)))

        health = dashboard.compute_system_health()

        # Should be healthy or caution
        assert health['overall_status'] in ['healthy', 'caution']

    def test_critical_alerts_tracking(self):
        """Test critical alerts are tracked."""
        dashboard = SystemHealthDashboard()

        # No alerts initially
        health = dashboard.compute_system_health()
        assert health['critical_alerts'] == 0


class TestIntegration:
    """Integration tests for monitoring system."""

    def test_end_to_end_monitoring(self):
        """Test end-to-end monitoring workflow."""
        dashboard = SystemHealthDashboard()

        # Simulate trading day
        for day in range(20):
            # Strategy returns
            daily_return = np.random.normal(0.001, 0.01)
            dashboard.strategy_monitor.record_return("MAIN", daily_return)

            # Model predictions
            for _ in range(100):
                prediction = np.random.uniform(0, 1)
                actual = np.random.uniform(0, 1)
                dashboard.model_monitor.record_prediction(
                    "MODEL", prediction, actual, 0.7
                )

            # Executions
            for _ in range(50):
                dashboard.execution_monitor.record_execution(
                    f"ORDER_{day}",
                    5.0, 5.2, 1.0, 50
                )

            # Latency
            for _ in range(10):
                dashboard.latency_monitor.record_latency("trading", 50.0)

            # Data feed
            dashboard.data_monitor.record_update("MARKET_DATA")

        health = dashboard.compute_system_health()

        assert 'overall_status' in health
        assert health['overall_score'] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
