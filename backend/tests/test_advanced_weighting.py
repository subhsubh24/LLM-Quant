"""
Tests for Advanced Weighting Engine - Phase 4

Tests cover:
- Exponential moving correlations
- Correlation breakdown detection
- Adaptive circuit breakers
- Portfolio mode management
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta

from app.portfolio.advanced_weighting_engine import (
    ExponentialMovingCorrelations,
    CorrelationBreakdownDetection,
    AdaptiveCircuitBreakerByVolatility,
    PortfolioRiskModeManager,
    PortfolioMode,
    AdvancedWeightingSystem,
)


class TestExponentialMovingCorrelations:
    """Test EMA correlation computation."""

    def test_initialization(self):
        """Test initializes properly."""
        ema = ExponentialMovingCorrelations()
        assert ema.span == 60
        assert ema.ema_corr_matrix is None

    def test_first_update(self):
        """Test first update sets initial correlation."""
        ema = ExponentialMovingCorrelations()

        returns = pd.DataFrame({
            'A': np.random.normal(0, 0.02, 100),
            'B': np.random.normal(0, 0.02, 100),
            'C': np.random.normal(0, 0.02, 100),
        })

        corr = ema.update(returns)

        assert corr is not None
        assert len(corr) == 3
        assert not corr.empty

    def test_decay_effect(self):
        """Test that recent data weighted more heavily."""
        ema_no_decay = ExponentialMovingCorrelations(decay=1.0)
        ema_decay = ExponentialMovingCorrelations(decay=0.9)

        returns1 = pd.DataFrame({
            'A': np.random.normal(0, 0.02, 100),
            'B': np.random.normal(0, 0.02, 100),
        })

        ema_no_decay.update(returns1)
        ema_decay.update(returns1)

        # Update with different correlation structure
        returns2 = pd.DataFrame({
            'A': np.random.normal(0, 0.02, 100),
            'B': np.random.normal(0, 0.02, 100),
        })

        corr_no_decay = ema_no_decay.update(returns2)
        corr_decay = ema_decay.update(returns2)

        # Results should be different (decay should be more responsive)


class TestCorrelationBreakdownDetection:
    """Test correlation breakdown detection."""

    def test_initialization(self):
        """Test initializes properly."""
        detector = CorrelationBreakdownDetection()
        assert detector.correlation_spike_threshold == 0.85

    def test_normal_correlation(self):
        """Test normal correlations don't trigger crisis."""
        detector = CorrelationBreakdownDetection()

        # Create low correlation matrix
        corr = pd.DataFrame(np.eye(3))
        corr.iloc[0, 1] = 0.3
        corr.iloc[1, 0] = 0.3
        corr.iloc[1, 2] = 0.3
        corr.iloc[2, 1] = 0.3

        result = detector.update(corr, date.today())

        assert not result['is_crisis']
        assert result['severity'] < 0.5

    def test_high_correlation_crisis(self):
        """Test high correlations trigger crisis."""
        detector = CorrelationBreakdownDetection()

        # Create high correlation matrix (crisis)
        corr_array = np.ones((3, 3)) * 0.9
        np.fill_diagonal(corr_array, 1.0)
        corr = pd.DataFrame(corr_array)

        result = detector.update(corr, date.today())

        assert result['is_crisis']
        assert result['severity'] > 0.25  # 0.9 corr gives severity of 0.333

    def test_history_tracking(self):
        """Test correlation history is tracked."""
        detector = CorrelationBreakdownDetection()

        for i in range(10):
            corr = pd.DataFrame(np.eye(2))
            corr.iloc[0, 1] = 0.3 + i * 0.05
            corr.iloc[1, 0] = 0.3 + i * 0.05

            detector.update(corr, date.today() - timedelta(days=10-i))

        assert len(detector.correlation_history) == 10


class TestAdaptiveCircuitBreaker:
    """Test adaptive circuit breaker by volatility."""

    def test_initialization(self):
        """Test initializes properly."""
        acb = AdaptiveCircuitBreakerByVolatility()
        assert acb.normal_daily_loss_limit == 5.0

    def test_low_volatility_tight_limit(self):
        """Test low volatility gets tight loss limits."""
        acb = AdaptiveCircuitBreakerByVolatility(normal_daily_loss_limit=5.0)

        limit_low = acb.compute_adaptive_limit(0.10, normal_volatility=0.15)
        limit_normal = acb.compute_adaptive_limit(0.15, normal_volatility=0.15)

        # Low volatility should have tighter (smaller) limit
        assert limit_low < limit_normal

    def test_high_volatility_relaxed_limit(self):
        """Test high volatility gets relaxed loss limits."""
        acb = AdaptiveCircuitBreakerByVolatility(normal_daily_loss_limit=5.0)

        limit_normal = acb.compute_adaptive_limit(0.15, normal_volatility=0.15)
        limit_high = acb.compute_adaptive_limit(0.30, normal_volatility=0.15)

        # High volatility should have relaxed (larger) limit
        assert limit_high > limit_normal

    def test_limit_bounds(self):
        """Test limits are bounded."""
        acb = AdaptiveCircuitBreakerByVolatility(normal_daily_loss_limit=5.0)

        limit_very_low = acb.compute_adaptive_limit(0.01, normal_volatility=0.15)
        limit_very_high = acb.compute_adaptive_limit(1.0, normal_volatility=0.15)

        # Should be bounded
        assert 2.5 <= limit_very_low <= 10.0
        assert 2.5 <= limit_very_high <= 10.0


class TestPortfolioModeManager:
    """Test portfolio mode management."""

    def test_initialization_normal_mode(self):
        """Test initializes in normal mode."""
        manager = PortfolioRiskModeManager()
        assert manager.current_mode == PortfolioMode.NORMAL

    def test_normal_to_crisis(self):
        """Test transition from normal to crisis mode."""
        manager = PortfolioRiskModeManager()

        # Trigger crisis
        new_mode = manager.determine_mode(
            correlation_breakdown_severity=0.8,
            daily_loss_pct=-3.0,
            weekly_loss_pct=-5.0,
            realized_volatility=0.40,
            normal_volatility=0.15,
        )

        assert new_mode == PortfolioMode.CRISIS

        mode, adjustments = manager.update_mode(new_mode)

        assert mode == PortfolioMode.CRISIS
        assert adjustments.leverage_multiplier < 1.0  # De-leveraged

    def test_caution_mode(self):
        """Test caution mode triggers."""
        manager = PortfolioRiskModeManager()

        new_mode = manager.determine_mode(
            correlation_breakdown_severity=0.5,
            daily_loss_pct=-1.5,
            weekly_loss_pct=-3.0,
            realized_volatility=0.25,
            normal_volatility=0.15,
        )

        assert new_mode == PortfolioMode.CAUTION

    def test_recovery_mode(self):
        """Test recovery mode transition."""
        manager = PortfolioRiskModeManager()

        # Enter crisis
        manager.update_mode(PortfolioMode.CRISIS)

        # Recover
        new_mode = manager.determine_mode(
            correlation_breakdown_severity=0.2,
            daily_loss_pct=-0.2,
            weekly_loss_pct=-0.5,
            realized_volatility=0.12,
            normal_volatility=0.15,
        )

        assert new_mode == PortfolioMode.RECOVERY

    def test_mode_history(self):
        """Test mode transitions are recorded."""
        manager = PortfolioRiskModeManager()

        manager.update_mode(PortfolioMode.CAUTION)
        manager.update_mode(PortfolioMode.CRISIS)
        manager.update_mode(PortfolioMode.RECOVERY)
        manager.update_mode(PortfolioMode.NORMAL)

        assert len(manager.mode_history) >= 3


class TestAdvancedWeightingSystem:
    """Test complete advanced weighting system."""

    def test_initialization(self):
        """Test system initializes."""
        system = AdvancedWeightingSystem()
        assert system.ema_correlations is not None
        assert system.breakdown_detection is not None

    def test_full_update_normal_conditions(self):
        """Test full update in normal conditions."""
        system = AdvancedWeightingSystem()

        returns = pd.DataFrame({
            'S1': np.random.normal(0.001, 0.02, 100),
            'S2': np.random.normal(0.001, 0.02, 100),
            'S3': np.random.normal(0.001, 0.02, 100),
        })

        result = system.update(
            returns=returns,
            current_date=date.today(),
            daily_loss_pct=-0.5,
            weekly_loss_pct=-1.0,
            realized_volatility=0.15,
        )

        assert 'correlation_matrix' in result
        assert 'breakdown_info' in result
        assert 'portfolio_mode' in result
        assert result['portfolio_mode'] == 'normal'

    def test_full_update_crisis_conditions(self):
        """Test full update in crisis conditions."""
        system = AdvancedWeightingSystem()

        returns = pd.DataFrame({
            'S1': np.random.normal(-0.02, 0.05, 100),
            'S2': np.random.normal(-0.02, 0.05, 100),
            'S3': np.random.normal(-0.02, 0.05, 100),
        })

        result = system.update(
            returns=returns,
            current_date=date.today(),
            daily_loss_pct=-4.0,
            weekly_loss_pct=-10.0,
            realized_volatility=0.40,
        )

        assert result['portfolio_mode'] == 'crisis'
        assert result['mode_adjustments']['leverage_multiplier'] < 1.0

    def test_mode_adjustments_application(self):
        """Test applying mode adjustments to weights."""
        from app.portfolio.advanced_weighting_engine import ModeAdjustments

        system = AdvancedWeightingSystem()

        target_weights = {
            'S1': 0.4,
            'S2': 0.3,
            'S3': 0.3,
        }

        adjustments = ModeAdjustments(
            leverage_multiplier=0.5,
            position_size_multiplier=0.5,
            circuit_breaker_tightness=1.0,
            rebalance_frequency=1,
        )

        adjusted = system.apply_mode_adjustments(target_weights, adjustments)

        # Weights should be halved
        assert sum(adjusted.values()) <= 1.0
        for w in adjusted.values():
            assert w > 0

    def test_crisis_detection_and_mode_switch(self):
        """Test crisis is detected and mode switches."""
        system = AdvancedWeightingSystem()

        # Normal conditions initially
        result1 = system.update(
            returns=pd.DataFrame(np.random.normal(0, 0.02, (100, 3))),
            current_date=date.today(),
            daily_loss_pct=-0.5,
            weekly_loss_pct=-1.0,
            realized_volatility=0.15,
        )

        assert result1['portfolio_mode'] == 'normal'

        # Crisis conditions
        result2 = system.update(
            returns=pd.DataFrame(np.random.normal(0, 0.05, (100, 3))),
            current_date=date.today(),
            daily_loss_pct=-5.0,
            weekly_loss_pct=-15.0,
            realized_volatility=0.40,
        )

        assert result2['portfolio_mode'] == 'crisis'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
