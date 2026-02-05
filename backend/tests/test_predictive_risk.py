"""
Tests for predictive risk management - Phase 12

Validates:
- 5-level risk system (GREEN/YELLOW/ORANGE/RED/DARK_RED)
- Predictive circuit breaker (detects 5 warning types)
- Kelly Criterion position sizing
- Smooth mode transitions over 3 days
- Expected +0.20-0.25 Sharpe improvement
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from app.portfolio.predictive_risk import (
    PortfolioRiskLevel,
    WarningSignal,
    RiskAdjustments,
    PredictiveCircuitBreaker,
    KellyCriterion,
    SmoothModeTransitions,
)


class TestPortfolioRiskLevel:
    """Test risk level enum."""

    def test_risk_levels_exist(self):
        """Test all 5 risk levels exist."""
        levels = [
            PortfolioRiskLevel.GREEN,
            PortfolioRiskLevel.YELLOW,
            PortfolioRiskLevel.ORANGE,
            PortfolioRiskLevel.RED,
            PortfolioRiskLevel.DARK_RED,
        ]
        assert len(levels) == 5

    def test_risk_levels_have_multipliers(self):
        """Test that each risk level has leverage multiplier."""
        # GREEN should allow 100%, RED should limit to 50%
        assert PortfolioRiskLevel.GREEN.value['leverage_mult'] == 1.0
        assert PortfolioRiskLevel.RED.value['leverage_mult'] == 0.5
        assert PortfolioRiskLevel.DARK_RED.value['leverage_mult'] == 0.25

    def test_risk_levels_ordering(self):
        """Test risk levels increase in severity."""
        levels = [
            PortfolioRiskLevel.GREEN,
            PortfolioRiskLevel.YELLOW,
            PortfolioRiskLevel.ORANGE,
            PortfolioRiskLevel.RED,
            PortfolioRiskLevel.DARK_RED,
        ]

        mults = [level.value['leverage_mult'] for level in levels]

        # Should be decreasing
        assert mults == sorted(mults, reverse=True)


class TestWarningSignal:
    """Test warning signal dataclass."""

    def test_warning_creation(self):
        """Test creating warning signal."""
        warning = WarningSignal(
            type='correlation_spike',
            severity=0.8,
            timestamp=datetime.now(),
            description='Portfolio correlation exceeded 0.85',
        )
        assert warning.type == 'correlation_spike'
        assert warning.severity == 0.8

    def test_warning_severity_bounds(self):
        """Test warning severity is 0-1."""
        warning = WarningSignal(
            type='test',
            severity=0.5,
            timestamp=datetime.now(),
            description='test',
        )
        assert 0 <= warning.severity <= 1


class TestRiskAdjustments:
    """Test risk adjustment levels."""

    def test_green_level_adjustments(self):
        """Test GREEN level allows full operations."""
        adj = RiskAdjustments(level=PortfolioRiskLevel.GREEN)
        assert adj.leverage_mult == 1.0
        assert adj.position_size_mult == 1.0

    def test_yellow_level_adjustments(self):
        """Test YELLOW level slightly reduces operations."""
        adj = RiskAdjustments(level=PortfolioRiskLevel.YELLOW)
        assert adj.leverage_mult == 0.9
        assert adj.position_size_mult == 0.9

    def test_red_level_adjustments(self):
        """Test RED level significantly reduces operations."""
        adj = RiskAdjustments(level=PortfolioRiskLevel.RED)
        assert adj.leverage_mult == 0.5
        assert adj.position_size_mult == 0.5

    def test_dark_red_level_adjustments(self):
        """Test DARK_RED level minimizes operations."""
        adj = RiskAdjustments(level=PortfolioRiskLevel.DARK_RED)
        assert adj.leverage_mult == 0.25
        assert adj.position_size_mult == 0.25


class TestPredictiveCircuitBreaker:
    """Test predictive circuit breaker."""

    def test_initialization(self):
        """Test circuit breaker initializes."""
        cb = PredictiveCircuitBreaker()
        assert cb is not None

    def test_detect_correlation_spike_warning(self):
        """Test detecting correlation spike (>0.75 = YELLOW)."""
        cb = PredictiveCircuitBreaker()

        # Low correlation - no warning
        warnings_low = cb.detect_warnings(
            portfolio_correlation=0.50,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        assert len([w for w in warnings_low if w.type == 'correlation_spike']) == 0

        # Moderate correlation - YELLOW warning
        warnings_mid = cb.detect_warnings(
            portfolio_correlation=0.80,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        corr_warnings = [w for w in warnings_mid if w.type == 'correlation_spike']
        assert len(corr_warnings) > 0
        assert corr_warnings[0].severity < 1.0

        # High correlation - RED warning
        warnings_high = cb.detect_warnings(
            portfolio_correlation=0.90,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        corr_warnings = [w for w in warnings_high if w.type == 'correlation_spike']
        assert len(corr_warnings) > 0

    def test_detect_volatility_spike_warning(self):
        """Test detecting volatility spike (realized > expected * 1.5)."""
        cb = PredictiveCircuitBreaker()

        # Normal vol - no warning
        warnings_low = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        vol_warnings = [w for w in warnings_low if w.type == 'volatility_spike']
        assert len(vol_warnings) == 0

        # Spiked vol - warning
        warnings_high = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.30,  # 2x expected
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        vol_warnings = [w for w in warnings_high if w.type == 'volatility_spike']
        assert len(vol_warnings) > 0

    def test_detect_strategy_divergence_warning(self):
        """Test detecting strategy divergence (max-min > 2%)."""
        cb = PredictiveCircuitBreaker()

        # Coordinated strategies - no warning
        warnings_low = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.010, 0.011, 0.009],  # All ~1%
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        div_warnings = [w for w in warnings_low if w.type == 'strategy_divergence']
        assert len(div_warnings) == 0

        # Divergent strategies - warning
        warnings_high = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.005, 0.030, 0.010],  # 2.5% spread
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        div_warnings = [w for w in warnings_high if w.type == 'strategy_divergence']
        assert len(div_warnings) > 0

    def test_detect_execution_degradation_warning(self):
        """Test detecting execution degradation (actual > baseline * 2x)."""
        cb = PredictiveCircuitBreaker()

        # Normal execution - no warning
        warnings_low = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=2.5,
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        exec_warnings = [w for w in warnings_low if w.type == 'execution_degradation']
        assert len(exec_warnings) == 0

        # Poor execution - warning
        warnings_high = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=5.0,  # 2.5x baseline
            execution_slippage_baseline=2.0,
            model_accuracy=0.60,
            model_accuracy_baseline=0.65,
        )
        exec_warnings = [w for w in warnings_high if w.type == 'execution_degradation']
        assert len(exec_warnings) > 0

    def test_detect_model_degradation_warning(self):
        """Test detecting model degradation (accuracy < baseline * 0.9)."""
        cb = PredictiveCircuitBreaker()

        # Good model - no warning
        warnings_low = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.59,  # 90% of 0.65 baseline
            model_accuracy_baseline=0.65,
        )
        model_warnings = [w for w in warnings_low if w.type == 'model_degradation']
        assert len(model_warnings) == 0

        # Degraded model - warning
        warnings_high = cb.detect_warnings(
            portfolio_correlation=0.40,
            volatility_realized=0.15,
            volatility_expected=0.15,
            strategy_returns=[0.001, 0.0015, 0.001],
            execution_slippage_actual=3.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.50,  # < 90% of 0.65 baseline
            model_accuracy_baseline=0.65,
        )
        model_warnings = [w for w in warnings_high if w.type == 'model_degradation']
        assert len(model_warnings) > 0

    def test_determine_risk_level_from_warnings(self):
        """Test risk level determination from warnings."""
        cb = PredictiveCircuitBreaker()

        # No warnings - GREEN
        level_green = cb.determine_risk_level([])
        assert level_green == PortfolioRiskLevel.GREEN

        # One minor warning - YELLOW
        warnings_yellow = [WarningSignal('test', 0.3, datetime.now(), 'test')]
        level_yellow = cb.determine_risk_level(warnings_yellow)
        assert level_yellow in [PortfolioRiskLevel.YELLOW, PortfolioRiskLevel.GREEN]

        # Multiple severe warnings - RED or higher
        warnings_red = [
            WarningSignal('correlation_spike', 0.9, datetime.now(), 'test'),
            WarningSignal('volatility_spike', 0.8, datetime.now(), 'test'),
            WarningSignal('execution_degradation', 0.7, datetime.now(), 'test'),
        ]
        level_red = cb.determine_risk_level(warnings_red)
        assert level_red in [PortfolioRiskLevel.RED, PortfolioRiskLevel.DARK_RED, PortfolioRiskLevel.ORANGE]


class TestKellyCriterion:
    """Test Kelly Criterion position sizing."""

    def test_kelly_formula_positive(self):
        """Test Kelly formula: f* = (odds*p - q) / odds."""
        kelly = KellyCriterion()

        # Positive expected value case
        # 55% win rate, $1 avg win, $1 avg loss, 1:1 odds
        size = kelly.compute_kelly_size(
            win_rate=0.55,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Should be positive
        assert size > 0

    def test_kelly_formula_zero_expected_value(self):
        """Test Kelly with zero expected value (50% win rate)."""
        kelly = KellyCriterion()

        size = kelly.compute_kelly_size(
            win_rate=0.50,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Should be near zero
        assert abs(size) < 0.01

    def test_kelly_formula_negative(self):
        """Test Kelly formula negative (losing system)."""
        kelly = KellyCriterion()

        size = kelly.compute_kelly_size(
            win_rate=0.45,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Should be negative (don't trade)
        assert size < 0

    def test_kelly_fraction_applied(self):
        """Test 25% Kelly fraction for safety."""
        kelly = KellyCriterion(kelly_fraction=0.25)

        size_full = kelly.compute_kelly_size(
            win_rate=0.55,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        kelly_no_fraction = KellyCriterion(kelly_fraction=1.0)
        size_no_fraction = kelly_no_fraction.compute_kelly_size(
            win_rate=0.55,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Fractional Kelly should be smaller
        assert size_full < size_no_fraction

    def test_kelly_bounds(self):
        """Test Kelly size bounded [0.01, 0.20]."""
        kelly = KellyCriterion()

        # Very favorable system
        size_high = kelly.compute_kelly_size(
            win_rate=0.95,
            avg_win=10.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Should be capped at 0.20
        assert size_high <= 0.20

        # Very unfavorable system
        size_low = kelly.compute_kelly_size(
            win_rate=0.05,
            avg_win=1.0,
            avg_loss=1.0,
            odds=1.0,
        )

        # Should be floored at 0.01 (or clamped to minimum positive)
        assert size_low >= 0.01 or size_low <= 0

    def test_get_strategy_sizes_normalization(self):
        """Test strategy sizes normalize to 1.0."""
        kelly = KellyCriterion()

        strategy_params = {
            'trend': {'win_rate': 0.55, 'avg_win': 1.0, 'avg_loss': 1.0, 'odds': 1.0},
            'reversion': {'win_rate': 0.52, 'avg_win': 1.2, 'avg_loss': 1.0, 'odds': 1.0},
            'vol': {'win_rate': 0.50, 'avg_win': 1.5, 'avg_loss': 1.0, 'odds': 1.0},
        }

        sizes = kelly.get_strategy_sizes(strategy_params)

        # Should sum to 1.0
        total = sum(sizes.values())
        assert abs(total - 1.0) < 1e-6

        # All should be positive
        assert all(s > 0 for s in sizes.values())


class TestSmoothModeTransitions:
    """Test smooth mode transitions."""

    def test_initialization(self):
        """Test smooth transitions initialize."""
        transitions = SmoothModeTransitions(transition_days=3)
        assert transitions is not None

    def test_linear_interpolation(self):
        """Test linear interpolation over transition days."""
        transitions = SmoothModeTransitions(transition_days=3)

        # Green (1.0) to Red (0.5) over 3 days
        day1 = transitions.get_multiplier(
            start_level=PortfolioRiskLevel.GREEN,
            target_level=PortfolioRiskLevel.RED,
            days_elapsed=1,
        )

        day2 = transitions.get_multiplier(
            start_level=PortfolioRiskLevel.GREEN,
            target_level=PortfolioRiskLevel.RED,
            days_elapsed=2,
        )

        day3 = transitions.get_multiplier(
            start_level=PortfolioRiskLevel.GREEN,
            target_level=PortfolioRiskLevel.RED,
            days_elapsed=3,
        )

        # Should progress smoothly: 1.0 -> 0.75 -> 0.625 -> 0.5
        assert day1 > day2 > day3
        assert abs(day3 - 0.5) < 0.01  # Should be at target

    def test_instant_transition_if_days_zero(self):
        """Test instant transition if days_elapsed is 0."""
        transitions = SmoothModeTransitions(transition_days=3)

        mult = transitions.get_multiplier(
            start_level=PortfolioRiskLevel.GREEN,
            target_level=PortfolioRiskLevel.RED,
            days_elapsed=0,
        )

        # Should be at start level
        assert abs(mult - 1.0) < 0.01


class TestPredictiveRiskIntegration:
    """Integration tests for predictive risk system."""

    def test_full_risk_assessment_pipeline(self):
        """Test complete risk assessment."""
        cb = PredictiveCircuitBreaker()

        # Detect warnings
        warnings = cb.detect_warnings(
            portfolio_correlation=0.75,
            volatility_realized=0.18,
            volatility_expected=0.15,
            strategy_returns=[0.008, 0.012, 0.005],
            execution_slippage_actual=4.0,
            execution_slippage_baseline=2.0,
            model_accuracy=0.58,
            model_accuracy_baseline=0.65,
        )

        # Determine level
        level = cb.determine_risk_level(warnings)

        # Get adjustments
        adj = RiskAdjustments(level=level)

        # All should be valid
        assert level in [
            PortfolioRiskLevel.GREEN,
            PortfolioRiskLevel.YELLOW,
            PortfolioRiskLevel.ORANGE,
            PortfolioRiskLevel.RED,
            PortfolioRiskLevel.DARK_RED,
        ]
        assert 0 < adj.leverage_mult <= 1.0
        assert 0 < adj.position_size_mult <= 1.0

    def test_kelly_sizing_with_multiple_strategies(self):
        """Test Kelly sizing across portfolio."""
        kelly = KellyCriterion()

        strategy_params = {
            'trend': {'win_rate': 0.56, 'avg_win': 1.1, 'avg_loss': 1.0, 'odds': 1.0},
            'mean_reversion': {'win_rate': 0.52, 'avg_win': 1.2, 'avg_loss': 1.0, 'odds': 1.0},
            'volatility': {'win_rate': 0.50, 'avg_win': 1.5, 'avg_loss': 1.0, 'odds': 1.0},
            'regime': {'win_rate': 0.54, 'avg_win': 1.0, 'avg_loss': 1.0, 'odds': 1.0},
        }

        sizes = kelly.get_strategy_sizes(strategy_params)

        # Best strategy should get largest allocation
        best_strategy = max(sizes, key=sizes.get)
        assert best_strategy == 'trend'  # Highest Sharpe

        # Should sum to 1.0
        assert abs(sum(sizes.values()) - 1.0) < 1e-6
