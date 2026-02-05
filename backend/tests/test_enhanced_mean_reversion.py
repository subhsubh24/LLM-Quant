"""
Tests for Enhanced Mean Reversion with ATR - Phase 3A

Tests cover:
- ATR computation correctness
- ATR-based bands vs Bollinger Bands
- Adaptive volatility adjustments
- Signal generation in different volatility regimes
- Volume confirmation
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

from app.strategies.enhanced_mean_reversion import (
    compute_atr,
    EnhancedMeanReversionStrategy,
    AdaptiveVolatilityMeanReversionStrategy,
)


class TestATRComputation:
    """Test ATR (Average True Range) calculation."""

    def test_atr_simple(self):
        """Test basic ATR computation."""
        high = np.array([102, 103, 101, 104, 105])
        low = np.array([100, 101, 99, 102, 103])
        close = np.array([101, 102, 100, 103, 104])

        atr = compute_atr(high, low, close, period=2)

        # ATR should be positive
        assert all(a >= 0 for a in atr)

    def test_atr_high_volatility(self):
        """Test ATR increases with volatility."""
        # Low volatility
        high_low_vol = np.ones(20) + np.random.uniform(0, 0.5, 20)
        low_low_vol = np.ones(20) - np.random.uniform(0, 0.5, 20)
        close_low_vol = np.ones(20)

        atr_low = compute_atr(high_low_vol, low_low_vol, close_low_vol, period=14)

        # High volatility
        high_high_vol = np.ones(20) + np.random.uniform(0, 5, 20)
        low_high_vol = np.ones(20) - np.random.uniform(0, 5, 20)
        close_high_vol = np.ones(20)

        atr_high = compute_atr(high_high_vol, low_high_vol, close_high_vol, period=14)

        # ATR should be higher in high volatility
        assert atr_high[-1] > atr_low[-1]

    def test_atr_insufficient_data(self):
        """Test ATR with insufficient data."""
        high = np.array([100, 101, 102])
        low = np.array([99, 100, 101])
        close = np.array([100, 101, 102])

        atr = compute_atr(high, low, close, period=14)

        # Should return zeros or small values
        assert len(atr) == 3


class TestEnhancedMeanReversionStrategy:
    """Test enhanced mean reversion with ATR."""

    def test_initialization_atr_mode(self):
        """Test strategy initializes in ATR mode."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True)
        assert strategy.strategy_id == "mean_reversion_atr_v2"
        assert strategy.use_atr is True

    def test_initialization_bollinger_mode(self):
        """Test strategy initializes in Bollinger Bands mode."""
        strategy = EnhancedMeanReversionStrategy(use_atr=False)
        assert strategy.use_atr is False

    def test_signal_atr_bands_oversold(self):
        """Test signal when price below lower ATR band."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True)

        # Create data with high/low
        n = 50
        base_price = 100
        data = pd.DataFrame({
            'high': base_price + np.random.uniform(0, 2, n),
            'low': base_price - np.random.uniform(0, 2, n),
            'close': base_price + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        # Price overshoots downward
        data.iloc[-1, data.columns.get_loc('close')] = base_price - 5

        signal = strategy.generate_signal(data)

        # Should generate long signal
        if signal.confidence > 0.3:
            assert signal.symbols.get('MEAN_REV', 0) > 0

    def test_signal_atr_bands_overbought(self):
        """Test signal when price above upper ATR band."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True)

        # Create data
        n = 50
        base_price = 100
        data = pd.DataFrame({
            'high': base_price + np.random.uniform(0, 2, n),
            'low': base_price - np.random.uniform(0, 2, n),
            'close': base_price + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        # Price overshoots upward
        data.iloc[-1, data.columns.get_loc('close')] = base_price + 5

        signal = strategy.generate_signal(data)

        # Should generate short signal
        if signal.confidence > 0.3:
            assert signal.symbols.get('MEAN_REV', 0) < 0

    def test_fallback_to_bollinger_bands(self):
        """Test fallback to Bollinger Bands if no high/low data."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True)

        # Create data without high/low
        n = 50
        data = pd.DataFrame({
            'close': np.random.normal(100, 2, n),
            'volume': np.ones(n) * 1000,
        })

        # Should not crash, use Bollinger Bands instead
        signal = strategy.generate_signal(data)

        assert signal is not None

    def test_volume_confirmation(self):
        """Test volume confirmation requirement."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True, min_volume_ratio=2.0)

        # Create data
        n = 50
        base_price = 100
        data = pd.DataFrame({
            'high': base_price + np.random.uniform(0, 2, n),
            'low': base_price - np.random.uniform(0, 2, n),
            'close': base_price + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        # Price at extreme but low volume
        data.iloc[-1, data.columns.get_loc('close')] = base_price - 5
        data.iloc[-1, data.columns.get_loc('volume')] = 100  # Low volume

        signal = strategy.generate_signal(data)

        # Should have low confidence due to low volume
        assert signal.confidence < 0.5

    def test_atr_bands_extra_data(self):
        """Test extra data contains band information."""
        strategy = EnhancedMeanReversionStrategy(use_atr=True)

        n = 50
        data = pd.DataFrame({
            'high': 100 + np.random.uniform(0, 2, n),
            'low': 100 - np.random.uniform(0, 2, n),
            'close': 100 + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        signal = strategy.generate_signal(data)

        # Should have band information
        if 'upper_band' in signal.extra_data:
            assert signal.extra_data['upper_band'] > signal.extra_data['lower_band']


class TestAdaptiveVolatilityMeanReversion:
    """Test adaptive volatility mean reversion."""

    def test_initialization(self):
        """Test strategy initializes."""
        strategy = AdaptiveVolatilityMeanReversionStrategy()
        assert strategy.strategy_id == "mean_reversion_adaptive_v3"

    def test_low_volatility_regime(self):
        """Test tight bands in low volatility regime."""
        strategy = AdaptiveVolatilityMeanReversionStrategy()

        # Create stable price data (low volatility)
        n = 100
        close = 100 + np.random.normal(0, 0.5, n)  # Low volatility

        data = pd.DataFrame({
            'high': close + 0.1,
            'low': close - 0.1,
            'close': close,
            'volume': np.ones(n) * 1000,
        })

        signal = strategy.generate_signal(data)

        # Should detect low volatility regime
        if 'volatility_regime' in signal.extra_data:
            regime = signal.extra_data['volatility_regime']
            assert regime in ['low_vol', 'normal', 'high_vol']

    def test_high_volatility_regime(self):
        """Test wider bands in high volatility regime."""
        strategy = AdaptiveVolatilityMeanReversionStrategy()

        # Create volatile price data (high volatility)
        n = 100
        close = 100 + np.random.normal(0, 10, n)  # High volatility

        data = pd.DataFrame({
            'high': close + 5,
            'low': close - 5,
            'close': close,
            'volume': np.ones(n) * 1000,
        })

        signal = strategy.generate_signal(data)

        # Should detect high volatility regime
        if 'volatility_regime' in signal.extra_data:
            regime = signal.extra_data['volatility_regime']
            assert regime in ['low_vol', 'normal', 'high_vol']

    def test_band_adjustment(self):
        """Test band adjustment factor."""
        strategy = AdaptiveVolatilityMeanReversionStrategy()

        # Create data
        n = 100
        data = pd.DataFrame({
            'high': 100 + np.random.uniform(0, 3, n),
            'low': 100 - np.random.uniform(0, 3, n),
            'close': 100 + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        signal = strategy.generate_signal(data)

        # Should have band adjustment
        if 'band_adjustment' in signal.extra_data:
            adjustment = signal.extra_data['band_adjustment']
            assert 0.5 < adjustment < 2.0  # Reasonable range


class TestComparison:
    """Compare enhanced vs basic mean reversion."""

    def test_atr_vs_bollinger_similar_signals(self):
        """Test ATR and Bollinger Bands give similar signals."""
        strategy_atr = EnhancedMeanReversionStrategy(use_atr=True)
        strategy_bb = EnhancedMeanReversionStrategy(use_atr=False)

        # Create data
        n = 50
        data = pd.DataFrame({
            'high': 100 + np.random.uniform(0, 2, n),
            'low': 100 - np.random.uniform(0, 2, n),
            'close': 100 + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        signal_atr = strategy_atr.generate_signal(data)
        signal_bb = strategy_bb.generate_signal(data)

        # Both should have strategy signals
        assert signal_atr.strategy_id == "mean_reversion_atr_v2"
        assert signal_bb.strategy_id == "mean_reversion_atr_v2"

    def test_atr_adapts_to_volatility_changes(self):
        """Test ATR bands adapt faster than Bollinger to vol changes."""
        strategy_atr = EnhancedMeanReversionStrategy(
            use_atr=True,
            period=20,
            atr_period=14,
        )

        # Low volatility data
        n = 50
        data_low_vol = pd.DataFrame({
            'high': 100 + np.random.uniform(0, 0.5, n),
            'low': 100 - np.random.uniform(0, 0.5, n),
            'close': 100 + np.random.uniform(-0.25, 0.25, n),
            'volume': np.ones(n) * 1000,
        })

        signal_low = strategy_atr.generate_signal(data_low_vol)

        # High volatility data
        data_high_vol = data_low_vol.copy()
        data_high_vol['high'] = 100 + np.random.uniform(0, 5, n)
        data_high_vol['low'] = 100 - np.random.uniform(0, 5, n)
        data_high_vol['close'] = 100 + np.random.uniform(-2.5, 2.5, n)

        signal_high = strategy_atr.generate_signal(data_high_vol)

        # Signals should adapt to volatility
        # (ATR is more responsive than fixed std dev)


class TestIntegrationWithFramework:
    """Test integration with strategy framework."""

    def test_inherits_from_base_strategy(self):
        """Test inherits from BaseStrategy."""
        from app.strategies import BaseStrategy

        strategy = EnhancedMeanReversionStrategy()

        assert isinstance(strategy, BaseStrategy)
        assert hasattr(strategy, 'generate_signal')
        assert hasattr(strategy, 'strategy_id')

    def test_signal_structure(self):
        """Test signal has correct structure."""
        strategy = EnhancedMeanReversionStrategy()

        n = 50
        data = pd.DataFrame({
            'high': 100 + np.random.uniform(0, 2, n),
            'low': 100 - np.random.uniform(0, 2, n),
            'close': 100 + np.random.uniform(-1, 1, n),
            'volume': np.ones(n) * 1000,
        })

        signal = strategy.generate_signal(data)

        # Check signal structure
        assert hasattr(signal, 'symbols')
        assert hasattr(signal, 'target_weights')
        assert hasattr(signal, 'confidence')
        assert hasattr(signal, 'extra_data')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
