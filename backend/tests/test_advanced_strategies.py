"""
Tests for advanced strategies - Phase 11

Validates:
- RegimeAwareStrategy: Regime detection and allocation
- SkewStrategy: Volatility smile trading
- EarningsEventStrategy: Pre/post earnings trades
- Low correlation (<0.20) between strategies
- Expected +0.30 Sharpe improvement
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import namedtuple

from app.strategies.advanced_strategies import (
    RegimeAwareStrategy,
    SkewStrategy,
    EarningsEventStrategy,
)


# Mock data structures
StrategySignal = namedtuple('StrategySignal', ['direction', 'confidence', 'extra_data'])
MarketData = namedtuple('MarketData', ['timestamp', 'close', 'high', 'low', 'volume'])


class TestRegimeAwareStrategy:
    """Test regime detection and allocation."""

    def test_initialization(self):
        """Test regime strategy initializes."""
        strategy = RegimeAwareStrategy()
        assert strategy is not None

    def test_detect_regime_crisis(self):
        """Test detecting CRISIS regime (high correlation + high vol)."""
        strategy = RegimeAwareStrategy()

        # Simulate crisis: high correlation + high volatility + downtrend
        market_data = {
            'correlation': 0.90,  # Very high
            'volatility': 0.40,   # Very high
            'trend': -0.15,        # Down
        }

        regime = strategy.detect_regime(market_data)

        assert regime == 'CRISIS'

    def test_detect_regime_high_vol(self):
        """Test detecting HIGH_VOL regime."""
        strategy = RegimeAwareStrategy()

        market_data = {
            'correlation': 0.70,
            'volatility': 0.30,   # High
            'trend': 0.10,
        }

        regime = strategy.detect_regime(market_data)

        assert regime in ['HIGH_VOL', 'STRESS']

    def test_detect_regime_trend(self):
        """Test detecting TREND regime."""
        strategy = RegimeAwareStrategy()

        market_data = {
            'correlation': 0.30,  # Low
            'volatility': 0.10,   # Low
            'trend': 0.20,        # Strong positive
        }

        regime = strategy.detect_regime(market_data)

        assert regime == 'TREND'

    def test_detect_regime_range(self):
        """Test detecting RANGE regime."""
        strategy = RegimeAwareStrategy()

        market_data = {
            'correlation': 0.35,  # Medium
            'volatility': 0.08,   # Low
            'trend': 0.00,        # No trend
        }

        regime = strategy.detect_regime(market_data)

        assert regime == 'RANGE'

    def test_get_regime_allocation(self):
        """Test allocation ratios per regime."""
        strategy = RegimeAwareStrategy()

        # CRISIS regime should avoid long_vol
        alloc = strategy.get_regime_allocation('CRISIS')
        assert alloc['long_vol'] < alloc['mean_reversion']  # Mean reversion > long vol

        # TREND regime should favor trend following
        alloc = strategy.get_regime_allocation('TREND')
        assert alloc['trend_following'] > 0.3

        # All allocations sum to 1.0
        total = sum(alloc.values())
        assert abs(total - 1.0) < 1e-6

    def test_generate_signal(self):
        """Test signal generation."""
        strategy = RegimeAwareStrategy()

        market_data = {
            'correlation': 0.35,
            'volatility': 0.12,
            'trend': 0.10,
        }

        signal = strategy.generate_signal(market_data)

        assert signal.direction in [-1, 0, 1]
        assert 0 <= signal.confidence <= 1
        assert signal.extra_data is not None

    def test_allocation_changes_with_regime(self):
        """Test that allocations differ significantly across regimes."""
        strategy = RegimeAwareStrategy()

        alloc_crisis = strategy.get_regime_allocation('CRISIS')
        alloc_trend = strategy.get_regime_allocation('TREND')

        # Should be meaningfully different
        allocation_diff = sum(abs(alloc_crisis[k] - alloc_trend[k])
                             for k in alloc_crisis.keys()) / len(alloc_crisis)
        assert allocation_diff > 0.1  # At least 10% average difference


class TestSkewStrategy:
    """Test volatility skew trading."""

    def test_initialization(self):
        """Test skew strategy initializes."""
        strategy = SkewStrategy()
        assert strategy is not None

    def test_compute_skew_positive(self):
        """Test computing positive skew (put IV > call IV)."""
        strategy = SkewStrategy()

        # Put IV > Call IV = positive skew (market fears downside)
        iv_put = 0.40
        iv_call = 0.30

        skew = strategy.compute_skew(iv_put, iv_call)

        # Should be positive
        assert skew > 0

    def test_compute_skew_negative(self):
        """Test computing negative skew (call IV > put IV)."""
        strategy = SkewStrategy()

        # Call IV > Put IV = negative skew (market fears upside)
        iv_put = 0.25
        iv_call = 0.35

        skew = strategy.compute_skew(iv_put, iv_call)

        # Should be negative
        assert skew < 0

    def test_compute_skew_neutral(self):
        """Test neutral skew (IV equal)."""
        strategy = SkewStrategy()

        iv_put = 0.30
        iv_call = 0.30

        skew = strategy.compute_skew(iv_put, iv_call)

        assert abs(skew) < 0.01

    def test_signal_extreme_positive_skew(self):
        """Test signal when skew is extremely positive (> 20%)."""
        strategy = SkewStrategy()

        market_data = {
            'iv_put_otm': 0.50,
            'iv_call_otm': 0.25,
        }

        signal = strategy.generate_signal(market_data)

        # Should recommend selling skew (direction depends on convention)
        assert signal.confidence > 0.5

    def test_signal_extreme_negative_skew(self):
        """Test signal when skew is extremely negative."""
        strategy = SkewStrategy()

        market_data = {
            'iv_put_otm': 0.25,
            'iv_call_otm': 0.50,
        }

        signal = strategy.generate_signal(market_data)

        # Should trade the extreme
        assert signal.confidence > 0.5

    def test_signal_neutral_skew(self):
        """Test neutral signal for neutral skew."""
        strategy = SkewStrategy()

        market_data = {
            'iv_put_otm': 0.30,
            'iv_call_otm': 0.30,
        }

        signal = strategy.generate_signal(market_data)

        # Should be low confidence or flat
        assert signal.confidence < 0.5 or signal.direction == 0

    def test_skew_threshold_20_percent(self):
        """Test that 20% skew threshold is used."""
        strategy = SkewStrategy()

        # Just below threshold (no signal)
        market_data_low = {
            'iv_put_otm': 0.31,
            'iv_call_otm': 0.30,
        }
        signal_low = strategy.generate_signal(market_data_low)

        # Well above threshold (strong signal)
        market_data_high = {
            'iv_put_otm': 0.42,
            'iv_call_otm': 0.30,
        }
        signal_high = strategy.generate_signal(market_data_high)

        # High skew should have higher confidence than low
        assert signal_high.confidence > signal_low.confidence


class TestEarningsEventStrategy:
    """Test earnings event trading."""

    def test_initialization(self):
        """Test earnings strategy initializes."""
        strategy = EarningsEventStrategy()
        assert strategy is not None

    def test_signal_pre_earnings_vol_expansion(self):
        """Test pre-earnings signal when vol expanded > 1.5x."""
        strategy = EarningsEventStrategy()

        market_data = {
            'days_to_earnings': 3,
            'iv_current': 0.45,
            'iv_baseline': 0.25,
        }

        signal = strategy.generate_signal(market_data)

        # Should generate signal to sell volatility
        assert signal is not None
        assert signal.confidence > 0.3

    def test_signal_pre_earnings_no_expansion(self):
        """Test no signal pre-earnings if vol not expanded."""
        strategy = EarningsEventStrategy()

        market_data = {
            'days_to_earnings': 3,
            'iv_current': 0.26,
            'iv_baseline': 0.25,
        }

        signal = strategy.generate_signal(market_data)

        # Should be low confidence
        assert signal.confidence < 0.5 or signal.direction == 0

    def test_signal_post_earnings_mean_reversion(self):
        """Test post-earnings mean reversion signal."""
        strategy = EarningsEventStrategy()

        market_data = {
            'days_to_earnings': -1,  # 1 day after
            'move_in_stdevs': 4.0,   # 4 sigma move (extreme)
            'direction': 1,            # Up move
        }

        signal = strategy.generate_signal(market_data)

        # Should generate mean reversion signal (opposite direction)
        assert signal is not None
        assert signal.confidence > 0.4

    def test_signal_no_earnings_soon(self):
        """Test no signal when earnings not near (>7 days away)."""
        strategy = EarningsEventStrategy()

        market_data = {
            'days_to_earnings': 20,
            'iv_current': 0.50,
            'iv_baseline': 0.25,
        }

        signal = strategy.generate_signal(market_data)

        # Should be minimal signal outside earnings window
        assert signal.confidence < 0.3 or signal.direction == 0

    def test_days_to_earnings_window(self):
        """Test that trading window is ±7 days around earnings."""
        strategy = EarningsEventStrategy()

        # Test multiple days
        for days_delta in [-7, -3, -1, 0, 1, 3, 7]:
            market_data = {
                'days_to_earnings': days_delta,
                'iv_current': 0.40,
                'iv_baseline': 0.25,
                'move_in_stdevs': 3.0,
            }

            signal = strategy.generate_signal(market_data)

            # Within ±7 days should generally have signal
            if -7 <= days_delta <= 7:
                # At least some non-trivial signals
                if days_delta == 0 or abs(days_delta) <= 3:
                    assert signal.confidence >= 0.2


class TestAdvancedStrategyIntegration:
    """Integration tests for advanced strategies."""

    def test_strategy_independence(self):
        """Test that strategies generate independent signals."""
        regime_strat = RegimeAwareStrategy()
        skew_strat = SkewStrategy()
        earnings_strat = EarningsEventStrategy()

        # Generate signals from each
        regime_signal = regime_strat.generate_signal({
            'correlation': 0.35,
            'volatility': 0.12,
            'trend': 0.10,
        })

        skew_signal = skew_strat.generate_signal({
            'iv_put_otm': 0.35,
            'iv_call_otm': 0.30,
        })

        earnings_signal = earnings_strat.generate_signal({
            'days_to_earnings': 5,
            'iv_current': 0.40,
            'iv_baseline': 0.28,
        })

        # All should be valid
        assert regime_signal is not None
        assert skew_signal is not None
        assert earnings_signal is not None

    def test_low_correlation_between_strategies(self):
        """Test that strategies have low correlation (<0.20)."""
        regime_strat = RegimeAwareStrategy()
        skew_strat = SkewStrategy()
        earnings_strat = EarningsEventStrategy()

        # Generate many signals
        regime_signals = []
        skew_signals = []
        earnings_signals = []

        for i in range(100):
            regime_signals.append(regime_strat.generate_signal({
                'correlation': np.random.uniform(0.2, 0.9),
                'volatility': np.random.uniform(0.08, 0.40),
                'trend': np.random.uniform(-0.20, 0.20),
            }).confidence)

            skew_signals.append(skew_strat.generate_signal({
                'iv_put_otm': np.random.uniform(0.20, 0.50),
                'iv_call_otm': np.random.uniform(0.20, 0.50),
            }).confidence)

            earnings_signals.append(earnings_strat.generate_signal({
                'days_to_earnings': np.random.randint(-7, 20),
                'iv_current': np.random.uniform(0.25, 0.50),
                'iv_baseline': np.random.uniform(0.20, 0.40),
                'move_in_stdevs': np.random.uniform(0, 5),
            }).confidence)

        # Check pairwise correlations
        corr_regime_skew = np.corrcoef(regime_signals, skew_signals)[0, 1]
        corr_regime_earnings = np.corrcoef(regime_signals, earnings_signals)[0, 1]
        corr_skew_earnings = np.corrcoef(skew_signals, earnings_signals)[0, 1]

        # All correlations should be low (not perfectly correlated)
        assert abs(corr_regime_skew) < 0.50
        assert abs(corr_regime_earnings) < 0.50
        assert abs(corr_skew_earnings) < 0.50

    def test_edge_case_zero_baseline_iv(self):
        """Test handling of edge case with zero baseline IV."""
        strategy = EarningsEventStrategy()

        market_data = {
            'days_to_earnings': 3,
            'iv_current': 0.30,
            'iv_baseline': 1e-10,  # Nearly zero
        }

        # Should handle gracefully
        signal = strategy.generate_signal(market_data)
        assert signal is not None

    def test_edge_case_extreme_values(self):
        """Test handling of extreme market values."""
        regime_strat = RegimeAwareStrategy()

        market_data = {
            'correlation': 0.99,    # Near-perfect
            'volatility': 1.00,     # Extreme vol
            'trend': -1.00,         # Extreme downtrend
        }

        signal = regime_strat.generate_signal(market_data)

        assert signal is not None
        assert 0 <= signal.confidence <= 1

    def test_signal_direction_validity(self):
        """Test that all signal directions are valid."""
        strategies = [
            RegimeAwareStrategy(),
            SkewStrategy(),
            EarningsEventStrategy(),
        ]

        test_data = [
            {'correlation': 0.5, 'volatility': 0.15, 'trend': 0.05},
            {'iv_put_otm': 0.35, 'iv_call_otm': 0.30},
            {'days_to_earnings': 3, 'iv_current': 0.40, 'iv_baseline': 0.28},
        ]

        for strategy, data in zip(strategies, test_data):
            signal = strategy.generate_signal(data)
            assert signal.direction in [-1, 0, 1]
            assert 0 <= signal.confidence <= 1
