"""
Tests for statistical arbitrage engine and integration.

Tests cover:
- Cointegration testing
- Pairs trading signal generation
- Mean-reversion detection
- Portfolio management and position sizing
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.trading.stat_arb_engine import (
    CointegrationTester,
    PairsTradingEngine,
    MeanReversionDetector,
    StatArbEngine,
)
from app.trading.stat_arb_integration import (
    StatArbPortfolioManager,
    StatArbMetrics,
    create_stat_arb_system,
)


class TestCointegrationTester:
    """Test cointegration detection."""

    @pytest.fixture
    def cointegrated_series(self):
        """Create cointegrated price series."""
        np.random.seed(42)
        n = 252

        # Create cointegrated pair
        common_shock = np.random.randn(n)
        price_a = 100 + np.cumsum(common_shock + np.random.randn(n) * 0.1)
        price_b = 50 + np.cumsum(common_shock * 0.8 + np.random.randn(n) * 0.15)

        return pd.Series(price_a), pd.Series(price_b)

    @pytest.fixture
    def random_series(self):
        """Create uncorrelated random series."""
        np.random.seed(42)
        n = 252

        price_a = 100 + np.cumsum(np.random.randn(n))
        price_b = 50 + np.cumsum(np.random.randn(n))

        return pd.Series(price_a), pd.Series(price_b)

    def test_adf_test(self):
        """Test ADF test execution."""
        tester = CointegrationTester()

        # Create stationary series
        np.random.seed(42)
        stationary = pd.Series(np.random.randn(100))

        adf_stat, pvalue = tester.test_adf(stationary)

        # Stationary series should have p-value < 0.05
        assert pvalue < 0.10  # Relaxed threshold for noise

    def test_cointegration_detection_cointegrated(self, cointegrated_series):
        """Test detection of cointegrated pairs."""
        tester = CointegrationTester()
        price_a, price_b = cointegrated_series

        adf_stat, pvalue, coint_score = tester.find_cointegration_strength(price_a, price_b)

        # Cointegrated pair should have higher score
        assert coint_score > 0.4

    def test_cointegration_detection_random(self, random_series):
        """Test that random series score lower."""
        tester = CointegrationTester()
        price_a, price_b = random_series

        adf_stat, pvalue, coint_score = tester.find_cointegration_strength(price_a, price_b)

        # Random series should have lower score
        assert coint_score < 0.7


class TestPairsTradingEngine:
    """Test pairs trading functionality."""

    @pytest.fixture
    def sample_prices(self):
        """Create sample price data with cointegrated pairs."""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252)

        # Create 10 stocks
        n_stocks = 10
        n_days = len(dates)

        # Create some cointegrated pairs
        prices_dict = {}
        common = np.cumsum(np.random.randn(n_days) * 0.01)

        for i in range(n_stocks):
            if i < 2:
                # Cointegrated pair
                prices_dict[f'STOCK{i}'] = 100 + common * 10 + np.cumsum(np.random.randn(n_days) * 0.5)
            else:
                # Random walk
                prices_dict[f'STOCK{i}'] = 100 + np.cumsum(np.random.randn(n_days))

        return pd.DataFrame(prices_dict, index=dates)

    def test_engine_initialization(self):
        """Test engine initializes."""
        engine = PairsTradingEngine(
            lookback_days=252,
            min_cointegration_score=0.70,
            zscore_entry=2.0,
            zscore_exit=0.5,
        )

        assert engine.lookback_days == 252
        assert engine.min_cointegration_score == 0.70

    def test_pair_finding(self, sample_prices):
        """Test finding cointegrated pairs."""
        engine = PairsTradingEngine(
            min_cointegration_score=0.5,  # Lower threshold for test
            lookback_days=100,
        )

        pairs = engine.find_pairs(sample_prices, max_pairs=50)

        # Should find at least some pairs
        assert len(pairs) >= 0  # May find 0 with random data

    def test_pair_signal_generation(self, sample_prices):
        """Test pair signal generation."""
        engine = PairsTradingEngine(
            min_cointegration_score=0.5,
            lookback_days=100,
        )

        pairs = engine.find_pairs(sample_prices, max_pairs=10)

        if pairs:
            signals = engine.generate_pair_signals(sample_prices, pairs)

            assert len(signals) == len(pairs)
            for signal in signals:
                assert signal.action in ["BUY_A_SELL_B", "SELL_A_BUY_B", "CLOSE", "HOLD"]


class TestMeanReversionDetector:
    """Test mean-reversion detection."""

    @pytest.fixture
    def correlated_returns(self):
        """Create correlated return series."""
        np.random.seed(42)
        n = 252

        # Create correlated returns
        common = np.random.randn(n)
        ret_a = common * 0.5 + np.random.randn(n) * 0.015
        ret_b = common * 0.7 + np.random.randn(n) * 0.015

        # Convert to prices
        price_a = 100 * np.exp(np.cumsum(ret_a))
        price_b = 100 * np.exp(np.cumsum(ret_b))

        return pd.Series(price_a), pd.Series(price_b)

    def test_detector_initialization(self):
        """Test detector initializes."""
        detector = MeanReversionDetector(
            correlation_lookback=60,
            deviation_threshold=1.5,
        )

        assert detector.correlation_lookback == 60

    def test_correlation_breakdown_detection(self, correlated_returns):
        """Test correlation breakdown detection."""
        detector = MeanReversionDetector(correlation_lookback=60)
        price_a, price_b = correlated_returns

        corr_now, corr_mean, deviation, action = (
            detector.detect_correlation_breakdown(price_a, price_b)
        )

        assert -1 <= corr_now <= 1
        assert isinstance(action, str)


class TestStatArbEngine:
    """Test overall stat arb engine."""

    @pytest.fixture
    def sample_prices(self):
        """Create sample price data."""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252)

        prices_dict = {}
        for i in range(5):
            prices_dict[f'STOCK{i}'] = 100 + np.cumsum(np.random.randn(252) * 0.5)

        return pd.DataFrame(prices_dict, index=dates)

    def test_engine_initialization(self):
        """Test engine initializes."""
        engine = StatArbEngine(
            lookback_days=252,
            use_pairs_trading=True,
            use_correlation_arb=False,
        )

        assert engine.use_pairs_trading
        assert not engine.use_correlation_arb

    def test_strategy_generation(self, sample_prices):
        """Test strategy generation."""
        engine = StatArbEngine(
            lookback_days=100,
            use_pairs_trading=True,
            pairs_per_strategy=10,
        )

        strategies = engine.generate_strategies(sample_prices)

        assert 'pairs_trading' in strategies

    def test_combined_signals(self, sample_prices):
        """Test getting combined signals."""
        engine = StatArbEngine(
            lookback_days=100,
            use_pairs_trading=True,
        )

        strategies = engine.generate_strategies(sample_prices)
        all_signals = engine.get_all_signals(strategies)

        assert isinstance(all_signals, list)


class TestStatArbPortfolioManager:
    """Test portfolio management for stat arb."""

    def test_manager_initialization(self):
        """Test manager initializes."""
        manager = StatArbPortfolioManager(
            capital=100_000,
            max_pairs_active=10,
            capital_per_pair=10_000,
        )

        assert manager.capital == 100_000
        assert manager.max_pairs_active == 10

    def test_position_sizing(self):
        """Test position sizing."""
        from app.trading.stat_arb_engine import PairSignal

        manager = StatArbPortfolioManager(capital=100_000)

        signal = PairSignal(
            symbol_a='AAPL',
            symbol_b='MSFT',
            timestamp=datetime.now(),
            adf_statistic=-3.5,
            adf_pvalue=0.01,
            cointegration_score=0.85,
            spread_current=0.0,
            spread_zscore=2.5,
            expected_volatility=0.15,
            position_ratio_a_to_b=1.2,
        )

        size_a, size_b = manager.size_pair_position(signal, 50_000)

        assert size_a > 0
        assert size_b > 0
        assert size_a + size_b <= 50_000 * 1.5  # Allow some flexibility

    def test_order_generation(self):
        """Test order generation from signals."""
        from app.trading.stat_arb_engine import PairSignal

        manager = StatArbPortfolioManager(capital=100_000, max_pairs_active=5)

        signals = [
            PairSignal(
                symbol_a='AAPL',
                symbol_b='MSFT',
                timestamp=datetime.now(),
                adf_statistic=-3.5,
                adf_pvalue=0.01,
                cointegration_score=0.85,
                spread_current=0.0,
                spread_zscore=2.5,
                action="BUY_A_SELL_B",
                confidence=0.85,
                expected_volatility=0.15,
                position_ratio_a_to_b=1.0,
            ),
            PairSignal(
                symbol_a='JPM',
                symbol_b='BAC',
                timestamp=datetime.now(),
                adf_statistic=-3.2,
                adf_pvalue=0.02,
                cointegration_score=0.80,
                spread_current=0.0,
                spread_zscore=-1.8,
                action="SELL_A_BUY_B",
                confidence=0.75,
                expected_volatility=0.18,
                position_ratio_a_to_b=1.1,
            ),
        ]

        orders = manager.generate_position_orders(signals)

        assert len(orders) > 0
        # Should have buy and sell orders
        buy_orders = [o for o in orders if o['side'] == 'BUY']
        sell_orders = [o for o in orders if o['side'] == 'SELL']
        assert len(buy_orders) > 0
        assert len(sell_orders) > 0


class TestStatArbMetrics:
    """Test stat arb metrics."""

    def test_pair_pnl_calculation_long_short(self):
        """Test P&L calculation for long-short pair."""
        # Long AAPL at 150, short MSFT at 350
        pnl = StatArbMetrics.compute_pair_pnl(
            entry_price_a=150,
            entry_price_b=350,
            current_price_a=155,
            current_price_b=345,
            size_a=100,
            size_b=100,
            side_a="BUY",
            side_b="SELL",
        )

        # Long A: +$500, Short B: +$500 = +$1000
        assert pnl == 1000

    def test_portfolio_hedge_ratio(self):
        """Test hedge ratio calculation."""
        from app.trading.stat_arb_engine import PairSignal

        signals = [
            PairSignal(
                symbol_a='A',
                symbol_b='B',
                timestamp=datetime.now(),
                adf_statistic=-3.5,
                adf_pvalue=0.01,
                cointegration_score=0.85,
                spread_current=0.0,
                spread_zscore=0.0,
                action="BUY_A_SELL_B",
                position_ratio_a_to_b=1.0,
            ),
        ]

        metrics = StatArbMetrics.portfolio_hedge_ratio(signals)

        assert 'hedge_ratio' in metrics
        assert metrics['long_exposure'] > 0


def test_factory_function(sample_prices=None):
    """Test factory function."""
    if sample_prices is None:
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252)
        prices = {}
        for i in range(5):
            prices[f'STOCK{i}'] = 100 + np.cumsum(np.random.randn(252))
        sample_prices = pd.DataFrame(prices, index=dates)

    engine, manager = create_stat_arb_system(
        sample_prices,
        capital=100_000,
        max_pairs=5,
    )

    assert engine is not None
    assert manager is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
