"""
Tests for core trading strategies.

Tests cover:
- Signal generation
- Trend following
- Mean reversion
- Volatility trading
- Sector rotation
- Carry trading
- Technical patterns
- Sentiment analysis
- Factor rotation
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, date

from app.strategies.core_strategies import (
    TrendFollowingStrategy,
    MeanReversionStrategy,
    VolatilityTradingStrategy,
    SectorRotationStrategy,
    CarryTradingStrategy,
    TechnicalPatternsStrategy,
    SentimentAnalysisStrategy,
    FactorRotationStrategy,
)


class TestTrendFollowingStrategy:
    """Test trend following strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = TrendFollowingStrategy()
        assert strategy.strategy_id == "trend_following_v1"
        assert strategy.fast_period == 20
        assert strategy.slow_period == 50

    def test_signal_generation_insufficient_data(self):
        """Test signal with insufficient data."""
        strategy = TrendFollowingStrategy()

        data = pd.DataFrame({
            'close': [100, 101, 102],
            'volume': [1000, 1100, 1200],
        })

        signal = strategy.generate_signal(data)
        assert signal.confidence == 0

    def test_signal_generation_uptrend(self):
        """Test signal generation in uptrend."""
        strategy = TrendFollowingStrategy()

        # Generate uptrending data
        close_prices = list(range(100, 150)) + [150 + i * 0.5 for i in range(51)]
        data = pd.DataFrame({
            'close': close_prices,
            'volume': [1000] * len(close_prices),
        })

        signal = strategy.generate_signal(data)
        assert signal.confidence > 0.5

    def test_signal_generation_downtrend(self):
        """Test signal generation in downtrend."""
        strategy = TrendFollowingStrategy()

        # Generate downtrending data
        close_prices = list(range(150, 100, -1)) + [100 - i * 0.5 for i in range(51)]
        data = pd.DataFrame({
            'close': close_prices,
            'volume': [1000] * len(close_prices),
        })

        signal = strategy.generate_signal(data)
        # Should have low confidence in downtrend


class TestMeanReversionStrategy:
    """Test mean reversion strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = MeanReversionStrategy()
        assert strategy.strategy_id == "mean_reversion_v1"
        assert strategy.period == 20

    def test_signal_generation(self):
        """Test signal generation."""
        strategy = MeanReversionStrategy()

        # Generate mean-reverting data (price oscillates around mean)
        mean_price = 100
        close_prices = [mean_price + np.sin(i * 0.1) * 5 for i in range(50)]
        data = pd.DataFrame({
            'close': close_prices,
            'volume': [1000] * len(close_prices),
        })

        signal = strategy.generate_signal(data)
        assert signal is not None


class TestVolatilityTradingStrategy:
    """Test volatility trading strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = VolatilityTradingStrategy()
        assert strategy.strategy_id == "volatility_v1"

    def test_signal_generation_low_volatility(self):
        """Test signal generation with low volatility."""
        strategy = VolatilityTradingStrategy()

        # Generate low volatility data
        close_prices = [100 + np.random.normal(0, 0.1) for _ in range(50)]
        data = pd.DataFrame({
            'close': close_prices,
        })

        signal = strategy.generate_signal(data)
        assert signal is not None

    def test_signal_generation_high_volatility(self):
        """Test signal generation with high volatility."""
        strategy = VolatilityTradingStrategy()

        # Generate high volatility data
        close_prices = [100 + np.random.normal(0, 5) for _ in range(50)]
        data = pd.DataFrame({
            'close': close_prices,
        })

        signal = strategy.generate_signal(data)
        assert signal is not None


class TestSectorRotationStrategy:
    """Test sector rotation strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = SectorRotationStrategy()
        assert strategy.strategy_id == "sector_rotation_v1"

    def test_signal_generation(self):
        """Test signal generation."""
        strategy = SectorRotationStrategy()

        data = pd.DataFrame({
            'close': range(100, 150),
        })

        signal = strategy.generate_signal(data)
        assert signal.confidence > 0


class TestCarryTradingStrategy:
    """Test carry trading strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = CarryTradingStrategy()
        assert strategy.strategy_id == "carry_v1"

    def test_signal_generation_risk_on(self):
        """Test signal generation in risk-on regime."""
        strategy = CarryTradingStrategy()

        context = {'risk_sentiment': 0.5}  # Risk-on
        signal = strategy.generate_signal(None, context)

        assert signal.confidence > 0

    def test_signal_generation_risk_off(self):
        """Test signal generation in risk-off regime."""
        strategy = CarryTradingStrategy()

        context = {'risk_sentiment': -0.5}  # Risk-off
        signal = strategy.generate_signal(None, context)

        assert signal.confidence > 0


class TestTechnicalPatternsStrategy:
    """Test technical patterns strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = TechnicalPatternsStrategy()
        assert strategy.strategy_id == "technical_v1"

    def test_signal_generation_overbought(self):
        """Test signal generation in overbought condition."""
        strategy = TechnicalPatternsStrategy()

        # Generate consistently increasing prices (overbought)
        close_prices = [100 + i for i in range(50)]
        data = pd.DataFrame({
            'close': close_prices,
        })

        signal = strategy.generate_signal(data)
        assert signal is not None

    def test_signal_generation_oversold(self):
        """Test signal generation in oversold condition."""
        strategy = TechnicalPatternsStrategy()

        # Generate consistently decreasing prices (oversold)
        close_prices = [150 - i for i in range(50)]
        data = pd.DataFrame({
            'close': close_prices,
        })

        signal = strategy.generate_signal(data)
        assert signal is not None


class TestSentimentAnalysisStrategy:
    """Test sentiment analysis strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = SentimentAnalysisStrategy()
        assert strategy.strategy_id == "sentiment_v1"

    def test_signal_generation_positive_sentiment(self):
        """Test signal generation with positive sentiment."""
        strategy = SentimentAnalysisStrategy()

        context = {'sentiment_score': 0.8}  # Positive
        signal = strategy.generate_signal(None, context)

        assert signal.confidence > 0

    def test_signal_generation_negative_sentiment(self):
        """Test signal generation with negative sentiment."""
        strategy = SentimentAnalysisStrategy()

        context = {'sentiment_score': 0.2}  # Negative
        signal = strategy.generate_signal(None, context)

        assert signal.confidence > 0


class TestFactorRotationStrategy:
    """Test factor rotation strategy."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = FactorRotationStrategy()
        assert strategy.strategy_id == "factor_rotation_v1"

    def test_signal_generation(self):
        """Test signal generation."""
        strategy = FactorRotationStrategy()

        context = {
            'value_return': 0.02,
            'growth_return': 0.015,
            'momentum_return': 0.025,
        }
        signal = strategy.generate_signal(None, context)

        assert signal.confidence > 0


class TestStrategyIntegration:
    """Test strategies working together."""

    def test_multiple_strategies(self):
        """Test multiple strategies generating signals."""
        strategies = [
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            VolatilityTradingStrategy(),
            SectorRotationStrategy(),
        ]

        data = pd.DataFrame({
            'close': np.random.normal(100, 10, 100),
            'volume': np.random.normal(1000, 100, 100),
        })

        signals = []
        for strategy in strategies:
            signal = strategy.generate_signal(data)
            signals.append(signal)
            assert signal is not None

        # All signals should be generated
        assert len(signals) == len(strategies)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
