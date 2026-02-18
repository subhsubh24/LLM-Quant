"""
Tests for risk controls and backtester.

Tests cover:
- Circuit breakers (daily, weekly, drawdown)
- Stress testing scenarios
- Position limits enforcement
- Execution cost modeling
- Backtest accuracy and attribution
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta

from app.portfolio.risk_controls import (
    CircuitBreakerManager,
    StressTestManager,
    PositionLimits,
    RiskControlSystem,
    RiskEvent,
)
from app.backtest.advanced_backtester import (
    AdvancedBacktester,
    ExecutionModel,
    ExecutionCost,
    Trade,
)


class TestCircuitBreakerManager:
    """Test circuit breaker functionality."""

    def test_circuit_breaker_initialization(self):
        """Test circuit breaker manager initializes."""
        manager = CircuitBreakerManager()
        assert len(manager.circuit_breakers) == 0

    def test_add_circuit_breaker(self):
        """Test adding circuit breaker."""
        manager = CircuitBreakerManager()
        breaker = manager.add_circuit_breaker(
            "test_breaker",
            loss_limit_pct=5.0,
            lookback_days=1,
            action="pause",
        )

        assert breaker.name == "test_breaker"
        assert breaker.loss_limit_pct == 5.0
        assert "test_breaker" in manager.circuit_breakers

    def test_circuit_breaker_trigger_daily_loss(self):
        """Test circuit breaker triggers on daily loss."""
        manager = CircuitBreakerManager()
        manager.add_circuit_breaker(
            "daily_loss",
            loss_limit_pct=5.0,
            lookback_days=1,
            action="pause",
        )

        # Create returns that exceed loss limit (last day must exceed -5%)
        returns = pd.Series([0.01, 0.02, -0.06])

        triggered = manager.check_circuit_breakers(returns, 100_000)

        assert len(triggered) > 0
        assert triggered[0][1] == RiskEvent.DAILY_LOSS_LIMIT

    def test_circuit_breaker_cooldown(self):
        """Test circuit breaker cooldown."""
        manager = CircuitBreakerManager()
        breaker = manager.add_circuit_breaker(
            "test",
            loss_limit_pct=5.0,
            action="pause",
        )

        # Manually trigger
        breaker.triggered = True
        breaker.triggered_at = datetime.now()

        # Should be on cooldown
        assert not breaker.is_cooldown_expired()


class TestStressTestManager:
    """Test stress testing."""

    def test_stress_test_initialization(self):
        """Test stress test manager initializes."""
        manager = StressTestManager()
        assert len(manager.scenarios) > 0

    def test_scenario_2008(self):
        """Test 2008 crisis scenario."""
        manager = StressTestManager()

        positions = {"SPY": 50_000, "IWM": 30_000, "AGG": 20_000}
        asset_class_map = {"SPY": "equities", "IWM": "equities", "AGG": "credit"}

        stressed = manager.scenarios["2008_crisis"].apply_to_positions(
            positions, asset_class_map
        )

        # Equities should be down 40%, credit down 50%
        assert stressed["SPY"] < positions["SPY"]
        assert stressed["AGG"] < positions["AGG"]

    def test_run_all_stress_tests(self):
        """Test running all stress tests."""
        manager = StressTestManager()

        positions = {"SPY": 50_000, "AAPL": 30_000}
        asset_class_map = {"SPY": "equities", "AAPL": "equities"}

        results = manager.run_stress_test(
            positions, asset_class_map, portfolio_value=100_000
        )

        assert len(results) > 0
        assert "2008_crisis" in results
        assert "covid_crash" in results


class TestPositionLimits:
    """Test position limits."""

    def test_position_limits_initialization(self):
        """Test position limits initializes."""
        limits = PositionLimits(
            max_position_pct=0.05,
            max_sector_pct=0.25,
        )

        assert limits.max_position_pct == 0.05

    def test_position_limit_violation(self):
        """Test detecting position limit violations."""
        limits = PositionLimits(max_position_pct=0.10)

        # 15% of portfolio in one position
        positions = {"AAPL": 15_000}
        violations = limits.check_position_limits(positions, 100_000)

        assert len(violations) > 0

    def test_leverage_limit_violation(self):
        """Test detecting leverage violations."""
        limits = PositionLimits(max_leverage=1.5)

        # 200% gross exposure
        positions = {"AAPL": 100_000, "MSFT": -100_000}
        violations = limits.check_position_limits(positions, 100_000)

        assert any("leverage" in v[1].lower() for v in violations)


class TestRiskControlSystem:
    """Test overall risk control system."""

    def test_risk_control_initialization(self):
        """Test risk control system initializes."""
        system = RiskControlSystem(
            initial_capital=100_000,
            daily_loss_limit_pct=5.0,
        )

        assert system.initial_capital == 100_000
        assert len(system.circuit_breaker_manager.circuit_breakers) > 0

    def test_check_all_controls(self):
        """Test checking all controls."""
        system = RiskControlSystem(initial_capital=100_000)

        returns = pd.Series([-0.06, 0.01, 0.02])
        positions = {"AAPL": 50_000}

        results = system.check_all_controls(
            positions=positions,
            returns=returns,
            portfolio_value=100_000,
        )

        assert "circuit_breakers_triggered" in results
        assert "position_violations" in results
        assert "stress_test_results" in results


class TestExecutionModel:
    """Test execution cost modeling."""

    def test_execution_model_initialization(self):
        """Test execution model initializes."""
        model = ExecutionModel(
            commission_bps=1.0,
            base_spread_bps=5.0,
        )

        assert model.commission_bps == 1.0

    def test_execute_order_buy(self):
        """Test buy order execution."""
        model = ExecutionModel(commission_bps=1.0, slippage_bps=2.0)

        executed_price, cost = model.execute_order(
            ticker="AAPL",
            side="BUY",
            quantity=100,
            reference_price=150,
            daily_volume=50_000_000,
            volatility=0.20,
        )

        # Executed price should be higher (cost of buying)
        assert executed_price > 150
        assert cost.total_cost_bps > 0

    def test_execute_order_sell(self):
        """Test sell order execution."""
        model = ExecutionModel(commission_bps=1.0, slippage_bps=2.0)

        executed_price, cost = model.execute_order(
            ticker="AAPL",
            side="SELL",
            quantity=100,
            reference_price=150,
            daily_volume=50_000_000,
            volatility=0.20,
        )

        # Executed price should be lower (cost of selling)
        assert executed_price < 150
        assert cost.total_cost_bps > 0


class TestAdvancedBacktester:
    """Test backtesting functionality."""

    @pytest.fixture
    def sample_backtest_data(self):
        """Create sample data for backtesting."""
        dates = pd.date_range("2023-01-01", periods=252)
        n_stocks = 5

        prices = {}
        volumes = {}

        for i in range(n_stocks):
            ticker = f"STOCK{i}"
            # Create random walk price
            returns = np.random.randn(252) * 0.02
            prices[ticker] = 100 * np.exp(np.cumsum(returns))
            volumes[ticker] = np.random.uniform(1e6, 10e6, 252)

        prices_df = pd.DataFrame(prices, index=dates)
        volumes_df = pd.DataFrame(volumes, index=dates)

        return prices_df, volumes_df, dates

    def test_backtester_initialization(self):
        """Test backtester initializes."""
        backtester = AdvancedBacktester(initial_capital=100_000)

        assert backtester.initial_capital == 100_000

    def test_backtest_simple_strategy(self, sample_backtest_data):
        """Test running a simple backtest."""
        prices_df, volumes_df, dates = sample_backtest_data

        backtester = AdvancedBacktester(
            initial_capital=100_000,
            commission_bps=1.0,
        )

        # Simple equal-weight signals
        signals = {}

        for date in dates:
            signals[date] = {f"STOCK{i}": 1.0 for i in range(5)}

        # Equal-weight portfolio
        def portfolio_weights(day_signals):
            n = len(day_signals)
            return {ticker: 1.0 / n for ticker in day_signals}

        result = backtester.backtest(
            prices=prices_df,
            signals=signals,
            portfolio_weights_fn=portfolio_weights,
            volumes=volumes_df,
        )

        # Check result attributes
        assert hasattr(result, "total_return_pct")
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert len(result.trades) > 0

    def test_backtest_metrics_computed(self, sample_backtest_data):
        """Test that backtest computes all metrics."""
        prices_df, volumes_df, dates = sample_backtest_data

        backtester = AdvancedBacktester(initial_capital=100_000)

        signals = {date: {f"STOCK{i}": 1.0 for i in range(5)} for date in dates}

        def portfolio_weights(day_signals):
            n = len(day_signals)
            return {ticker: 1.0 / n for ticker in day_signals}

        result = backtester.backtest(
            prices=prices_df,
            signals=signals,
            portfolio_weights_fn=portfolio_weights,
            volumes=volumes_df,
        )

        # All metrics should be computed
        assert result.total_return_pct is not None
        assert result.annualized_return is not None
        assert result.volatility is not None
        assert result.sharpe_ratio is not None
        assert result.max_drawdown is not None
        assert result.win_rate is not None

    def test_backtest_summary(self, sample_backtest_data):
        """Test backtest summary generation."""
        prices_df, volumes_df, dates = sample_backtest_data

        backtester = AdvancedBacktester(initial_capital=100_000)

        signals = {date: {f"STOCK{i}": 1.0 for i in range(5)} for date in dates}

        def portfolio_weights(day_signals):
            n = len(day_signals)
            return {ticker: 1.0 / n for ticker in day_signals}

        result = backtester.backtest(
            prices=prices_df,
            signals=signals,
            portfolio_weights_fn=portfolio_weights,
            volumes=volumes_df,
        )

        summary = result.summary()

        assert "initial_capital" in summary
        assert "total_return" in summary
        assert "sharpe_ratio" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
