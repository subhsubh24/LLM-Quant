"""
Tests for monitoring and paper trading systems.

Tests cover:
- Alert generation and management
- Performance tracking and metrics
- Dashboard data generation
- Paper trading execution
- Session management
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta

from app.monitoring.monitoring import (
    Alert,
    AlertLevel,
    AlertType,
    DailyMetrics,
    AlertManager,
    PerformanceTracker,
    DashboardData,
)
from app.trading.paper_trader import (
    PaperTradingConfig,
    PaperTradingSession,
    PaperTrader,
)


class TestAlertManager:
    """Test alert management."""

    def test_alert_manager_initialization(self):
        """Test alert manager initializes."""
        manager = AlertManager(
            daily_loss_threshold_pct=5.0,
            weekly_loss_threshold_pct=10.0,
        )

        assert manager.daily_loss_threshold_pct == 5.0
        assert len(manager.alerts) == 0

    def test_daily_loss_alert(self):
        """Test daily loss alert triggers."""
        manager = AlertManager(daily_loss_threshold_pct=5.0)

        # 6% daily loss
        alert = manager.check_daily_loss(daily_pnl=-6_000, portfolio_value=100_000)

        assert alert is not None
        assert alert.alert_type == AlertType.LOSS_THRESHOLD
        assert alert.level == AlertLevel.CRITICAL

    def test_volatility_spike_alert(self):
        """Test volatility spike alert."""
        manager = AlertManager(volatility_spike_threshold=2.0)

        # Current vol is 3x normal
        alert = manager.check_volatility_spike(
            current_volatility=0.30,
            normal_volatility=0.10,
        )

        assert alert is not None
        assert alert.alert_type == AlertType.VOLATILITY_SPIKE
        assert alert.level == AlertLevel.WARNING

    def test_drawdown_alert(self):
        """Test drawdown alert."""
        manager = AlertManager(max_drawdown_warning=0.10)

        alert = manager.check_drawdown(current_drawdown=-0.12)

        assert alert is not None
        assert alert.alert_type == AlertType.DRAWDOWN_WARNING

    def test_get_recent_alerts(self):
        """Test getting recent alerts."""
        manager = AlertManager()

        # Generate some alerts
        manager.check_daily_loss(-6_000, 100_000)
        manager.check_volatility_spike(0.30, 0.10)

        recent = manager.get_recent_alerts(hours=1)
        assert len(recent) >= 2


class TestPerformanceTracker:
    """Test performance tracking."""

    def test_tracker_initialization(self):
        """Test performance tracker initializes."""
        tracker = PerformanceTracker(initial_capital=100_000)

        assert tracker.initial_capital == 100_000
        assert len(tracker.daily_metrics) == 0

    def test_add_daily_result(self):
        """Test adding daily result."""
        tracker = PerformanceTracker(initial_capital=100_000)

        # Record a day with profit
        metrics = tracker.add_daily_result(
            date=date(2024, 1, 1),
            opening_value=100_000,
            closing_value=101_000,  # +1% profit
            trades=[
                {"pnl": 500},
                {"pnl": 500},
            ],
        )

        assert metrics.daily_pnl == 1_000
        assert metrics.daily_return_pct == 0.01
        assert len(tracker.daily_metrics) == 1

    def test_multiple_days_tracking(self):
        """Test tracking multiple days."""
        tracker = PerformanceTracker(initial_capital=100_000)

        # Record multiple days
        dates = pd.date_range("2024-01-01", periods=5)

        for i, dt in enumerate(dates):
            closing = 100_000 * (1.01 ** (i + 1))  # +1% daily
            tracker.add_daily_result(
                date=dt.date(),
                opening_value=100_000 * (1.01 ** i),
                closing_value=closing,
                trades=[],
            )

        assert len(tracker.daily_metrics) == 5

    def test_summary_metrics(self):
        """Test summary metrics generation."""
        tracker = PerformanceTracker(initial_capital=100_000)

        for i in range(10):
            tracker.add_daily_result(
                date=date(2024, 1, 1 + i),
                opening_value=100_000 * (1.01 ** i),
                closing_value=100_000 * (1.01 ** (i + 1)),
                trades=[],
            )

        summary = tracker.get_summary_metrics()

        assert "total_return_pct" in summary
        assert "annualized_return_pct" in summary
        assert "volatility_annualized_pct" in summary
        assert "sharpe_ratio" in summary


class TestDashboardData:
    """Test dashboard data generation."""

    def test_dashboard_overview(self):
        """Test dashboard overview generation."""
        tracker = PerformanceTracker(initial_capital=100_000)
        alert_mgr = AlertManager()

        tracker.add_daily_result(
            date=date(2024, 1, 1),
            opening_value=100_000,
            closing_value=101_000,
            trades=[],
        )

        dashboard = DashboardData(tracker, alert_mgr)
        overview = dashboard.get_overview()

        assert "current_date" in overview
        assert "portfolio_value" in overview
        assert "daily_pnl" in overview

    def test_dashboard_equity_curve(self):
        """Test equity curve data generation."""
        tracker = PerformanceTracker(initial_capital=100_000)
        alert_mgr = AlertManager()

        for i in range(5):
            tracker.add_daily_result(
                date=date(2024, 1, 1 + i),
                opening_value=100_000 * (1.01 ** i),
                closing_value=100_000 * (1.01 ** (i + 1)),
                trades=[],
            )

        dashboard = DashboardData(tracker, alert_mgr)
        equity = dashboard.get_equity_curve()

        assert len(equity["dates"]) == 5
        assert len(equity["values"]) == 5


class TestPaperTradingConfig:
    """Test paper trading configuration."""

    def test_config_initialization(self):
        """Test config initializes."""
        config = PaperTradingConfig(
            initial_capital=100_000,
            commission_bps=1.0,
        )

        assert config.initial_capital == 100_000
        assert config.commission_bps == 1.0


class TestPaperTradingSession:
    """Test paper trading sessions."""

    def test_session_initialization(self):
        """Test session initializes."""
        config = PaperTradingConfig(initial_capital=100_000)

        session = PaperTradingSession(
            session_id="test_session_001",
            start_date=date(2024, 1, 1),
            initial_capital=100_000,
            config=config,
        )

        assert session.session_id == "test_session_001"
        assert session.initial_capital == 100_000

    def test_session_to_dict(self):
        """Test session serialization."""
        config = PaperTradingConfig()

        session = PaperTradingSession(
            session_id="test_001",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            initial_capital=100_000,
            final_capital=105_000,
            total_return_pct=0.05,
            config=config,
        )

        session_dict = session.to_dict()

        assert session_dict["session_id"] == "test_001"
        assert session_dict["total_return_pct"] == 5.0


class TestPaperTrader:
    """Test paper trader functionality."""

    def test_paper_trader_initialization(self):
        """Test paper trader initializes."""
        config = PaperTradingConfig(initial_capital=100_000)
        trader = PaperTrader(config=config)

        assert trader.portfolio_value == 100_000
        assert trader.cash == 100_000

    def test_start_session(self):
        """Test starting a paper trading session."""
        config = PaperTradingConfig(initial_capital=100_000)
        trader = PaperTrader(config=config)

        session = trader.start_session(
            session_id="test_001",
            start_date=date(2024, 1, 1),
        )

        assert session.session_id == "test_001"
        assert trader.session is not None

    def test_combine_signals(self):
        """Test combining signals from multiple sources."""
        trader = PaperTrader()

        signals = {
            "factors": {"AAPL": 0.8, "MSFT": 0.6},
            "stat_arb": {"AAPL": 0.7, "MSFT": 0.5},
            "ensemble": {"AAPL": 0.9, "MSFT": 0.4},
        }

        combined = trader._combine_signals(signals)

        assert "AAPL" in combined
        assert "MSFT" in combined
        # Combined scores should be positive
        assert combined["AAPL"] > 0
        assert combined["MSFT"] > 0

    def test_compute_target_weights(self):
        """Test computing target portfolio weights."""
        trader = PaperTrader()

        scores = {
            "AAPL": 0.9,
            "MSFT": 0.7,
            "GOOGL": 0.5,
            "AMZN": 0.3,
        }

        weights = trader._compute_target_weights(scores)

        # Total weight should sum to 1
        assert abs(sum(weights.values()) - 1.0) < 0.01
        # AAPL should have more weight than GOOGL
        assert weights["AAPL"] >= weights["GOOGL"]

    def test_daily_update(self):
        """Test daily update execution."""
        config = PaperTradingConfig(initial_capital=100_000)
        trader = PaperTrader(config=config)

        trader.start_session(session_id="test_001", start_date=date(2024, 1, 1))

        # Mock data
        prices = {
            "AAPL": 150.0,
            "MSFT": 300.0,
            "GOOGL": 100.0,
        }
        volumes = {
            "AAPL": 50_000_000,
            "MSFT": 30_000_000,
            "GOOGL": 20_000_000,
        }
        signal_inputs = {
            "prices": prices,
            "volumes": volumes,
        }

        # Mock signal generators
        trader.signal_generator = lambda x: {"AAPL": 0.8, "MSFT": 0.6}

        result = trader.daily_update(
            current_date=date(2024, 1, 1),
            prices=prices,
            volumes=volumes,
            signal_inputs=signal_inputs,
        )

        assert "portfolio_value" in result
        assert "daily_pnl" in result

    def test_end_session(self):
        """Test ending a paper trading session."""
        config = PaperTradingConfig(initial_capital=100_000)
        trader = PaperTrader(config=config)

        trader.start_session(session_id="test_001", start_date=date(2024, 1, 1))

        # Simulate some trading
        trader.portfolio_value = 105_000

        session = trader.end_session()

        assert session.end_date is not None
        assert session.final_capital == 105_000
        assert session.total_return_pct > 0

    def test_get_status(self):
        """Test getting trader status."""
        config = PaperTradingConfig(initial_capital=100_000)
        trader = PaperTrader(config=config)

        trader.start_session(session_id="test_001", start_date=date(2024, 1, 1))

        status = trader.get_status()

        assert "portfolio_value" in status
        assert "cash" in status
        assert "positions" in status
        assert status["session_id"] == "test_001"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
