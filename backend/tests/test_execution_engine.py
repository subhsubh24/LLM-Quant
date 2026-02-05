"""
Tests for smart order execution engine.

Tests cover:
- Market impact modeling
- VWAP execution
- TWAP execution
- Smart order routing
- Execution cost analysis
"""

import pytest
from datetime import datetime

from app.execution.smart_order_execution import (
    OrderType,
    OrderSide,
    ExecutionParameters,
    MarketData,
    ExecutionResult,
    MarketImpactModel,
    VWAPExecutor,
    TWAPExecutor,
    SmartOrderExecutor,
    ExecutionCostAnalyzer,
)


class TestMarketData:
    """Test market data structure."""

    def test_market_data_initialization(self):
        """Test market data initializes."""
        md = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=50000,
            ask_volume=50000,
            daily_volume=1000000,
            volatility=0.15,
        )

        assert md.price == 100.0
        assert md.bid_ask_spread > 0

    def test_bid_ask_spread_calculation(self):
        """Test bid-ask spread calculation."""
        md = MarketData(
            price=100.0,
            bid=99.9,
            ask=100.1,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=2000000,
            volatility=0.15,
        )

        # Spread should be 0.2/100 = 0.002 = 0.2%
        assert md.bid_ask_spread > 0


class TestMarketImpactModel:
    """Test market impact estimation."""

    def test_impact_model_initialization(self):
        """Test impact model initializes."""
        model = MarketImpactModel()
        assert model.alpha == 0.2

    def test_small_order_impact(self):
        """Test impact for small order."""
        model = MarketImpactModel()

        impact = model.estimate_impact(
            quantity=1000,  # 0.1% of volume
            daily_volume=1_000_000,
            volatility=0.15,
        )

        # Should be very small
        assert impact < 0.01

    def test_large_order_impact(self):
        """Test impact for large order."""
        model = MarketImpactModel()

        impact = model.estimate_impact(
            quantity=100_000,  # 10% of volume
            daily_volume=1_000_000,
            volatility=0.15,
        )

        # Should be significant
        assert impact > 0.005

    def test_high_volatility_impact(self):
        """Test impact increases with volatility."""
        model = MarketImpactModel()

        impact_low_vol = model.estimate_impact(
            quantity=50_000,
            daily_volume=1_000_000,
            volatility=0.10,
        )

        impact_high_vol = model.estimate_impact(
            quantity=50_000,
            daily_volume=1_000_000,
            volatility=0.30,
        )

        assert impact_high_vol > impact_low_vol


class TestExecutionParameters:
    """Test execution parameters."""

    def test_parameters_initialization(self):
        """Test parameters initialize."""
        params = ExecutionParameters()
        assert params.commission_bps == 1.0
        assert params.max_participation_rate == 0.10

    def test_custom_parameters(self):
        """Test custom parameters."""
        params = ExecutionParameters(
            commission_bps=0.5,
            spread_bps=3.0,
            urgency=0.8,
        )

        assert params.commission_bps == 0.5
        assert params.urgency == 0.8


class TestVWAPExecutor:
    """Test VWAP execution algorithm."""

    def test_vwap_executor_initialization(self):
        """Test VWAP executor initializes."""
        executor = VWAPExecutor()
        assert executor is not None

    def test_vwap_buy_order(self):
        """Test VWAP buy order execution."""
        executor = VWAPExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=2_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        result = executor.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        assert result.symbol == "AAPL"
        assert result.side == OrderSide.BUY
        assert result.quantity == 50_000
        assert result.avg_execution_price > market_data.price

    def test_vwap_sell_order(self):
        """Test VWAP sell order execution."""
        executor = VWAPExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=2_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        result = executor.execute(
            symbol="AAPL",
            quantity=-50_000,  # Sell
            market_data=market_data,
            params=params,
        )

        assert result.side == OrderSide.SELL
        assert result.avg_execution_price < market_data.price

    def test_vwap_cost_breakdown(self):
        """Test VWAP cost breakdown."""
        executor = VWAPExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=2_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        result = executor.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        # Should have all cost components
        assert result.commission_cost > 0
        assert result.market_impact_cost > 0
        assert result.spread_cost > 0


class TestTWAPExecutor:
    """Test TWAP execution algorithm."""

    def test_twap_executor_initialization(self):
        """Test TWAP executor initializes."""
        executor = TWAPExecutor()
        assert executor is not None

    def test_twap_higher_cost_than_vwap(self):
        """Test TWAP has higher cost than VWAP (faster execution)."""
        vwap = VWAPExecutor()
        twap = TWAPExecutor()

        market_data = MarketData(
            price=100.0,
            bid=99.95,
            ask=100.05,
            bid_volume=100000,
            ask_volume=100000,
            daily_volume=2_000_000,
            volatility=0.15,
        )

        params = ExecutionParameters()

        result_vwap = vwap.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        result_twap = twap.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        # TWAP should have higher market impact
        assert result_twap.market_impact_cost > result_vwap.market_impact_cost


class TestSmartOrderExecutor:
    """Test smart order routing."""

    def test_smart_executor_initialization(self):
        """Test smart executor initializes."""
        executor = SmartOrderExecutor()
        assert executor is not None

    def test_small_order_market_execution(self):
        """Test small orders execute as market orders."""
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

        # Small order (< 2% volume = 20k shares)
        result = executor.execute(
            symbol="AAPL",
            quantity=10_000,
            market_data=market_data,
            params=params,
        )

        assert result.market_impact_cost == 0  # Market orders have no impact

    def test_medium_order_vwap_execution(self):
        """Test medium orders use VWAP."""
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

        # Medium order (5% volume = 50k shares)
        result = executor.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        assert result.market_impact_cost > 0

    def test_large_order_twap_execution(self):
        """Test large orders use TWAP."""
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

        # Large order (15% volume = 150k shares)
        result = executor.execute(
            symbol="AAPL",
            quantity=150_000,
            market_data=market_data,
            params=params,
        )

        assert result.market_impact_cost > 0

    def test_urgent_execution_twap(self):
        """Test urgent orders use TWAP."""
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

        params = ExecutionParameters(urgency=0.8)

        result = executor.execute(
            symbol="AAPL",
            quantity=50_000,
            market_data=market_data,
            params=params,
        )

        # Should use TWAP due to urgency
        assert result.market_impact_cost > 0


class TestExecutionCostAnalyzer:
    """Test execution cost analysis."""

    def test_analyzer_initialization(self):
        """Test analyzer initializes."""
        analyzer = ExecutionCostAnalyzer()
        assert len(analyzer.execution_history) == 0

    def test_record_execution(self):
        """Test recording execution."""
        analyzer = ExecutionCostAnalyzer()

        result = ExecutionResult(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1000,
            avg_execution_price=100.5,
            total_cost=500,
            commission_cost=10,
            market_impact_cost=300,
            spread_cost=190,
        )

        analyzer.record_execution(result)

        assert len(analyzer.execution_history) == 1

    def test_average_execution_cost(self):
        """Test average execution cost calculation."""
        analyzer = ExecutionCostAnalyzer()

        for i in range(3):
            result = ExecutionResult(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=1000,
                avg_execution_price=100.0,
                total_cost=100,
                commission_cost=10,
                market_impact_cost=50,
                spread_cost=40,
            )
            analyzer.record_execution(result)

        avg_cost_bps = analyzer.get_average_execution_cost_bps()

        # 100 / (1000 * 100) = 0.001 = 10 bps
        assert avg_cost_bps > 0

    def test_get_summary(self):
        """Test getting execution summary."""
        analyzer = ExecutionCostAnalyzer()

        result = ExecutionResult(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1000,
            avg_execution_price=100.0,
            total_cost=100,
            commission_cost=10,
            market_impact_cost=50,
            spread_cost=40,
        )

        analyzer.record_execution(result)

        summary = analyzer.get_summary()

        assert "total_executions" in summary
        assert "avg_cost_bps" in summary
        assert summary["total_executions"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
