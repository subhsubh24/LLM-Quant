"""
Tests for enhanced signal engine components.

Tests cover:
- Factor decorrelation
- Adaptive weighting
- Sector rotation
- Integration with base engine
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from app.signals.enhanced_engine import (
    FactorDecorrelator,
    AdaptiveWeightingSystem,
    SectorRotationManager,
    EnhancedSignalEngine,
)


class TestFactorDecorrelator:
    """Test PCA-based factor decorrelation."""

    @pytest.fixture
    def sample_factors(self):
        """Create sample correlated factor scores."""
        np.random.seed(42)
        n_stocks = 100

        # Create highly correlated factors
        momentum = np.random.randn(n_stocks)
        value = momentum * 0.8 + np.random.randn(n_stocks) * 0.2  # 80% correlated
        quality = (momentum + value) * 0.5 + np.random.randn(n_stocks) * 0.3
        volatility = -momentum * 0.6 + np.random.randn(n_stocks) * 0.4
        technical = momentum * 0.5 + np.random.randn(n_stocks) * 0.5

        return pd.DataFrame({
            'momentum': momentum,
            'value': value,
            'quality': quality,
            'volatility': volatility,
            'technical': technical,
        })

    def test_decorrelator_fit(self, sample_factors):
        """Test that decorrelator fits properly."""
        decorrelator = FactorDecorrelator(n_components=4)
        decorrelator.fit(sample_factors)

        assert decorrelator.fitted
        assert decorrelator.pca is not None
        assert decorrelator.scaler is not None

    def test_decorrelator_reduces_correlation(self, sample_factors):
        """Test that decorrelated factors have lower correlation."""
        decorrelator = FactorDecorrelator(n_components=4)
        decorrelator.fit(sample_factors)

        # Original correlation
        orig_corr = sample_factors.corr().values
        orig_avg_corr = np.abs(orig_corr[np.triu_indices_from(orig_corr, k=1)]).mean()

        # Decorrelated correlation
        decorrelated = decorrelator.transform(sample_factors)
        dec_corr = decorrelated.corr().values
        dec_avg_corr = np.abs(dec_corr[np.triu_indices_from(dec_corr, k=1)]).mean()

        # Decorrelated should have much lower correlation
        assert dec_avg_corr < orig_avg_corr

    def test_decorrelator_variance_preserved(self, sample_factors):
        """Test that decorrelator preserves total variance."""
        decorrelator = FactorDecorrelator(variance_explained=0.90)
        decorrelator.fit(sample_factors)

        explained_var = decorrelator.pca.explained_variance_ratio_.sum()
        assert explained_var >= 0.85  # Should preserve ~90%


class TestAdaptiveWeightingSystem:
    """Test adaptive weighting based on performance."""

    @pytest.fixture
    def sample_returns(self):
        """Create sample factor and portfolio returns."""
        np.random.seed(42)
        dates = pd.date_range('2023-01-01', periods=252)

        # Create factor returns with different Sharpes
        momentum_ret = np.random.randn(252) * 0.02 + 0.0005  # Good Sharpe
        value_ret = np.random.randn(252) * 0.03 - 0.0001  # Bad Sharpe
        quality_ret = np.random.randn(252) * 0.025  # Medium Sharpe
        volatility_ret = np.random.randn(252) * 0.015 + 0.0003  # Good Sharpe
        technical_ret = np.random.randn(252) * 0.035  # Bad Sharpe

        factor_returns = {
            'momentum': pd.Series(momentum_ret, index=dates),
            'value': pd.Series(value_ret, index=dates),
            'quality': pd.Series(quality_ret, index=dates),
            'volatility': pd.Series(volatility_ret, index=dates),
            'technical': pd.Series(technical_ret, index=dates),
        }

        # Portfolio returns mix of factors
        portfolio_ret = (momentum_ret * 0.3 + quality_ret * 0.3 +
                        volatility_ret * 0.2 + value_ret * 0.1 + technical_ret * 0.1)

        return factor_returns, pd.Series(portfolio_ret, index=dates)

    def test_adaptive_weights_initialization(self):
        """Test that adaptive system initializes."""
        system = AdaptiveWeightingSystem(lookback_days=60)
        assert system.lookback_days == 60

    def test_adaptive_weights_computation(self, sample_returns):
        """Test that adaptive weights are computed."""
        factor_ret, portfolio_ret = sample_returns
        system = AdaptiveWeightingSystem(lookback_days=60)

        weights = system.compute_adaptive_weights(factor_ret, portfolio_ret)

        assert weights.momentum >= 0
        assert weights.value >= 0
        assert weights.quality >= 0
        assert weights.volatility >= 0
        assert weights.technical >= 0

        # Should sum to approximately 1
        total = (weights.momentum + weights.value + weights.quality +
                weights.volatility + weights.technical)
        assert 0.95 < total < 1.05

    def test_regime_adjustment(self):
        """Test that regime adjustments work."""
        system = AdaptiveWeightingSystem()

        # Test bull regime
        bull_adj = system._get_regime_adjustment("bull")
        assert bull_adj["momentum"] > bull_adj["value"]  # Momentum > value in bull

        # Test bear regime
        bear_adj = system._get_regime_adjustment("bear")
        assert bear_adj["value"] > bear_adj["momentum"]  # Value > momentum in bear

        # Test high vol regime
        hvol_adj = system._get_regime_adjustment("high_vol")
        assert hvol_adj["quality"] > hvol_adj["momentum"]  # Quality > momentum in high vol


class TestSectorRotationManager:
    """Test sector rotation management."""

    def test_initialization(self):
        """Test sector manager initializes."""
        manager = SectorRotationManager(sector_max_pct=0.25)
        assert manager.sector_max_pct == 0.25

    def test_sector_concentration_check(self):
        """Test sector concentration limiting."""
        manager = SectorRotationManager(sector_max_pct=0.20)

        weights = {
            'AAPL': 0.15,  # Tech
            'MSFT': 0.15,  # Tech
            'JPM': 0.10,   # Finance
            'BAC': 0.10,   # Finance
            'PG': 0.10,    # Staples
            'KO': 0.10,    # Staples
            'XLE': 0.15,   # Energy
        }

        sector_map = {
            'AAPL': 'tech',
            'MSFT': 'tech',
            'JPM': 'finance',
            'BAC': 'finance',
            'PG': 'staples',
            'KO': 'staples',
            'XLE': 'energy',
        }

        adjusted = manager.check_sector_concentration(weights, sector_map)

        # Check no sector exceeds limit
        sector_totals = {}
        for ticker, weight in adjusted.items():
            sector = sector_map[ticker]
            sector_totals[sector] = sector_totals.get(sector, 0) + weight

        for sector, total in sector_totals.items():
            assert total <= 0.21  # Allow slight numerical rounding

    def test_sector_momentum_calculation(self):
        """Test sector momentum calculation."""
        manager = SectorRotationManager()

        # Create simple price data
        dates = pd.date_range('2023-01-01', periods=100)
        prices = pd.DataFrame({
            'AAPL': 100 + np.arange(100),  # Uptrend
            'MSFT': 100 + np.arange(100),  # Uptrend
            'JPM': 100 - np.arange(100) * 0.5,  # Downtrend
            'BAC': 100 - np.arange(100) * 0.5,  # Downtrend
        }, index=dates)

        sector_map = {
            'AAPL': 'tech',
            'MSFT': 'tech',
            'JPM': 'finance',
            'BAC': 'finance',
        }

        momentum = manager.get_sector_momentum(prices, sector_map, lookback=50)

        assert 'tech' in momentum
        assert 'finance' in momentum
        assert momentum['tech'] > 0  # Tech sector up
        assert momentum['finance'] < 0  # Finance sector down


class TestEnhancedSignalEngine:
    """Test enhanced signal engine integration."""

    def test_engine_initialization(self):
        """Test engine initializes with features."""
        engine = EnhancedSignalEngine(
            use_pca=True,
            use_adaptive_weights=True,
            use_sector_rotation=True
        )

        assert engine.use_pca
        assert engine.use_adaptive_weights
        assert engine.use_sector_rotation

    def test_engine_with_disabled_features(self):
        """Test engine works with features disabled."""
        engine = EnhancedSignalEngine(
            use_pca=False,
            use_adaptive_weights=False,
            use_sector_rotation=False
        )

        assert not engine.use_pca
        assert not engine.use_adaptive_weights
        assert not engine.use_sector_rotation

    def test_decorrelated_factors_computation(self):
        """Test factor decorrelation in engine."""
        engine = EnhancedSignalEngine(use_pca=True)

        # Create sample factors
        np.random.seed(42)
        momentum = np.random.randn(100) * 0.5
        value = momentum * 0.8 + np.random.randn(100) * 0.2
        quality = np.random.randn(100) * 0.5
        volatility = -momentum * 0.6 + np.random.randn(100) * 0.4
        technical = np.random.randn(100) * 0.5

        decorrelated, loadings = engine.compute_decorrelated_factors(
            dict(enumerate(momentum)),
            dict(enumerate(value)),
            dict(enumerate(quality)),
            dict(enumerate(volatility)),
            dict(enumerate(technical)),
        )

        assert decorrelated is not None
        assert len(loadings) >= 0

    def test_composite_score_composition(self):
        """Test composite score composition."""
        engine = EnhancedSignalEngine()

        momentum = 0.5
        value = -0.3
        quality = 0.2
        volatility = -0.1
        technical = 0.4

        weights = {
            'momentum': 0.25,
            'value': 0.20,
            'quality': 0.20,
            'volatility': 0.15,
            'technical': 0.20,
        }

        composite = engine.compose_composite_score(
            momentum, value, quality, volatility, technical, weights
        )

        # Should be between -1 and 1
        assert -1 <= composite <= 1

        # Weights should be reflected in composition
        expected = (0.25 * 0.5 + 0.20 * -0.3 + 0.20 * 0.2 +
                   0.15 * -0.1 + 0.20 * 0.4)
        assert abs(composite - expected) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
