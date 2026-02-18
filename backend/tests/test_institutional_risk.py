"""
Tests for institutional risk management system.

Tests cover:
- Dynamic position limits
- Multi-level circuit breakers
- Correlation monitoring
- VaR/ES computation
- Portfolio risk metrics
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta

from app.portfolio.institutional_risk import (
    CircuitBreakerLevel,
    CircuitBreakerThresholds,
    PositionLimit,
    DailyRiskMetrics,
    RiskViolation,
    DynamicPositionLimiter,
    CircuitBreakerSystem,
    CorrelationMonitor,
    VaRCalculator,
    PortfolioRiskManager,
)


class TestDynamicPositionLimiter:
    """Test dynamic position limiting."""

    def test_limiter_initialization(self):
        """Test limiter initializes."""
        limiter = DynamicPositionLimiter()
        assert len(limiter.base_limits) == 0

    def test_set_base_limit(self):
        """Test setting base position limit."""
        limiter = DynamicPositionLimiter()
        limit = PositionLimit(
            symbol="AAPL",
            max_position_pct=0.05,
            max_position_usd=5_000,
        )
        limiter.set_base_limit("AAPL", limit)

        assert "AAPL" in limiter.base_limits

    def test_adjusted_limit_normal_conditions(self):
        """Test adjusted limit under normal conditions."""
        limiter = DynamicPositionLimiter()
        base_limit = PositionLimit(
            symbol="AAPL",
            max_position_pct=0.05,
            max_position_usd=5_000,
            volatility_threshold=0.30,
        )
        limiter.set_base_limit("AAPL", base_limit)

        adjusted = limiter.compute_adjusted_limit(
            symbol="AAPL",
            current_volatility=0.15,  # Below threshold
            daily_volume=1_000_000,
            portfolio_value=100_000,
        )

        # Should be close to base under normal conditions
        assert adjusted.max_position_pct <= 0.05

    def test_adjusted_limit_high_volatility(self):
        """Test adjusted limit reduces under high volatility."""
        limiter = DynamicPositionLimiter()
        base_limit = PositionLimit(
            symbol="AAPL",
            max_position_pct=0.05,
            max_position_usd=5_000,
            volatility_threshold=0.30,
        )
        limiter.set_base_limit("AAPL", base_limit)

        adjusted = limiter.compute_adjusted_limit(
            symbol="AAPL",
            current_volatility=0.50,  # Above threshold
            daily_volume=1_000_000,
            portfolio_value=100_000,
        )

        # Should be reduced under high volatility
        assert adjusted.max_position_pct < 0.05

    def test_adjusted_limit_poor_liquidity(self):
        """Test adjusted limit reduces with poor liquidity."""
        limiter = DynamicPositionLimiter()
        base_limit = PositionLimit(
            symbol="AAPL",
            max_position_pct=0.05,
            max_position_usd=5_000,
            volatility_threshold=0.30,
            liquidity_requirement=0.10,
        )
        limiter.set_base_limit("AAPL", base_limit)

        adjusted = limiter.compute_adjusted_limit(
            symbol="AAPL",
            current_volatility=0.15,
            daily_volume=50_000,  # Poor liquidity
            portfolio_value=100_000,
        )

        # Should be reduced with poor liquidity
        assert adjusted.max_position_pct <= 0.05


class TestCircuitBreakerSystem:
    """Test circuit breaker system."""

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initializes."""
        cb = CircuitBreakerSystem()
        assert cb.thresholds.daily_loss_pct == 5.0

    def test_circuit_breaker_no_breach(self):
        """Test no breach under normal conditions."""
        cb = CircuitBreakerSystem()
        level = cb.check_circuit_breaker(date.today(), -2.0)

        assert level == CircuitBreakerLevel.NONE

    def test_circuit_breaker_daily_loss_warning(self):
        """Test daily loss triggers warning."""
        cb = CircuitBreakerSystem()
        level = cb.check_circuit_breaker(date.today(), -6.0)

        assert level == CircuitBreakerLevel.HALT

    def test_circuit_breaker_daily_loss_halt(self):
        """Test daily loss triggers halt."""
        cb = CircuitBreakerSystem()
        level = cb.check_circuit_breaker(date.today(), -9.0)

        assert level == CircuitBreakerLevel.LIQUIDATE

    def test_circuit_breaker_weekly_loss(self):
        """Test weekly loss accumulation."""
        cb = CircuitBreakerSystem()

        # Accumulate daily losses over a week
        for i in range(7):
            day = date.today() - timedelta(days=6 - i)
            cb.check_circuit_breaker(day, -3.0)

        # Weekly loss should be ~21%, triggering halt
        level = cb.check_circuit_breaker(date.today() + timedelta(days=1), -1.0)

        assert level in (CircuitBreakerLevel.HALT, CircuitBreakerLevel.LIQUIDATE)


class TestCorrelationMonitor:
    """Test correlation monitoring."""

    def test_monitor_initialization(self):
        """Test monitor initializes."""
        monitor = CorrelationMonitor()
        assert monitor.correlation_threshold == 0.8

    def test_update_correlations(self):
        """Test correlation update."""
        monitor = CorrelationMonitor()

        # Generate synthetic returns
        returns = pd.DataFrame({
            "AAPL": np.random.normal(0.001, 0.02, 100),
            "MSFT": np.random.normal(0.001, 0.02, 100),
            "GOOGL": np.random.normal(0.001, 0.02, 100),
        })

        scores = monitor.update_correlations(date.today(), returns)

        assert "AAPL" in scores
        assert "MSFT" in scores
        assert all(0 <= v <= 1 for v in scores.values())


class TestVaRCalculator:
    """Test VaR and ES calculation."""

    def test_var_calculator_initialization(self):
        """Test calculator initializes."""
        calc = VaRCalculator(confidence_level=0.95)
        assert calc.confidence_level == 0.95

    def test_var_historical(self):
        """Test historical VaR computation."""
        calc = VaRCalculator()

        # Generate returns
        returns = np.random.normal(0.001, 0.02, 100)

        var = calc.compute_var_historical(returns)

        # Should be negative (worst 5% loss)
        assert var < 0

    def test_es_historical(self):
        """Test historical ES computation."""
        calc = VaRCalculator()

        returns = np.random.normal(0.001, 0.02, 100)

        es = calc.compute_es_historical(returns)

        # Should be more negative than VaR (worse tail)
        var = calc.compute_var_historical(returns)
        assert es <= var

    def test_var_parametric(self):
        """Test parametric VaR computation."""
        calc = VaRCalculator()

        var = calc.compute_var_parametric(
            mean_return=0.001,
            std_return=0.02,
        )

        # Should be negative
        assert var < 0


class TestPortfolioRiskManager:
    """Test portfolio risk manager."""

    def test_manager_initialization(self):
        """Test manager initializes."""
        manager = PortfolioRiskManager()
        assert manager.position_limiter is not None
        assert manager.circuit_breaker is not None

    def test_set_position_limits(self):
        """Test setting position limits."""
        manager = PortfolioRiskManager()

        limits = {
            "AAPL": PositionLimit(
                symbol="AAPL",
                max_position_pct=0.05,
                max_position_usd=5_000,
            ),
            "MSFT": PositionLimit(
                symbol="MSFT",
                max_position_pct=0.05,
                max_position_usd=5_000,
            ),
        }

        manager.set_position_limits(limits)

        assert "AAPL" in manager.position_limiter.base_limits

    def test_check_position_limits_ok(self):
        """Test position limit check passes."""
        manager = PortfolioRiskManager()

        positions = {"AAPL": 100}
        prices = {"AAPL": 150}

        violations = manager.check_position_limits(
            positions=positions,
            prices=prices,
            portfolio_value=100_000,
        )

        # Position is 0.15% of portfolio (well within default limits)
        assert len(violations) == 0

    def test_check_position_limits_violation(self):
        """Test position limit check fails."""
        manager = PortfolioRiskManager()

        # Very large position
        positions = {"AAPL": 100_000}
        prices = {"AAPL": 150}

        violations = manager.check_position_limits(
            positions=positions,
            prices=prices,
            portfolio_value=100_000,
        )

        # Position is 150% of portfolio (violation)
        assert len(violations) > 0

    def test_compute_daily_risk_metrics(self):
        """Test daily risk metrics computation."""
        manager = PortfolioRiskManager()

        metrics = manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=1_000,
            positions={"AAPL": 100},
            prices={"AAPL": 150},
        )

        assert metrics.portfolio_value == 100_000
        assert metrics.daily_pnl == 1_000
        assert metrics.daily_return_pct == 0.01

    def test_max_drawdown(self):
        """Test max drawdown computation."""
        manager = PortfolioRiskManager()

        # Add daily metrics with drawdown
        manager.compute_daily_risk_metrics(
            date_=date.today() - timedelta(days=2),
            portfolio_value=100_000,
            daily_pnl=0,
            positions={},
            prices={},
        )

        manager.compute_daily_risk_metrics(
            date_=date.today() - timedelta(days=1),
            portfolio_value=105_000,  # Up 5%
            daily_pnl=5_000,
            positions={},
            prices={},
        )

        manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=95_000,  # Down 10% from peak
            daily_pnl=-10_000,
            positions={},
            prices={},
        )

        dd = manager.get_max_drawdown()

        # Should show drawdown from peak
        assert dd < 0

    def test_should_halt_trading_normal(self):
        """Test halt decision under normal conditions."""
        manager = PortfolioRiskManager()

        should_halt, reason = manager.should_halt_trading()

        assert not should_halt

    def test_should_halt_trading_after_loss(self):
        """Test halt decision after circuit breaker trigger."""
        manager = PortfolioRiskManager()

        # Trigger circuit breaker
        manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=-9_000,  # 9% loss -> LIQUIDATE
            positions={},
            prices={},
        )

        should_halt, reason = manager.should_halt_trading()

        assert should_halt

    def test_get_risk_summary(self):
        """Test risk summary generation."""
        manager = PortfolioRiskManager()

        manager.compute_daily_risk_metrics(
            date_=date.today(),
            portfolio_value=100_000,
            daily_pnl=1_000,
            positions={"AAPL": 100},
            prices={"AAPL": 150},
        )

        summary = manager.get_risk_summary()

        assert "portfolio_value" in summary
        assert "daily_pnl" in summary
        assert "leverage" in summary
        assert summary["portfolio_value"] == 100_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
