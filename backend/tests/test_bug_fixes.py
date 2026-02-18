"""
Tests for critical bug fixes - Phase 1

Ensures all identified bugs are fixed:
1. Division by zero protection
2. NaN handling
3. Cost calculation correctness
4. Circuit breaker resettability
5. Data validation
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta

from app.portfolio.bug_fixes import (
    safe_compute_adjusted_limit,
    safe_compute_participation_rate,
    compute_execution_cost_safely,
    safe_normalize_weights,
    ResettableCircuitBreaker,
    validate_fold_data,
)


class TestPositionLimiterBugFix:
    """Test division by zero fix in position limiter."""

    def test_zero_daily_volume(self):
        """Test handles zero daily volume safely."""
        result = safe_compute_adjusted_limit(
            base_max_pct=0.05,
            current_volatility=0.15,
            volatility_threshold=0.20,
            daily_volume=0,  # BUG: Zero volume
            position_size=10_000,
            liquidity_requirement=0.10,
            portfolio_value=100_000,
        )

        # Should apply conservative 50% reduction
        assert 0 < result < 0.05

    def test_zero_position_size(self):
        """Test handles zero position size safely."""
        result = safe_compute_adjusted_limit(
            base_max_pct=0.05,
            current_volatility=0.15,
            volatility_threshold=0.20,
            daily_volume=1_000_000,
            position_size=0,  # No position yet
            liquidity_requirement=0.10,
            portfolio_value=100_000,
        )

        # Should not crash, return reasonable value
        assert 0 < result <= 0.05

    def test_poor_liquidity(self):
        """Test applies liquidity adjustment correctly."""
        result = safe_compute_adjusted_limit(
            base_max_pct=0.05,
            current_volatility=0.15,
            volatility_threshold=0.20,
            daily_volume=50_000,  # Poor liquidity
            position_size=50_000,  # Large relative position
            liquidity_requirement=0.10,
            portfolio_value=100_000,
        )

        # Should be reduced due to poor liquidity
        assert 0 < result < 0.05


class TestExecutionRoutingBugFix:
    """Test division by zero fix in execution routing."""

    def test_zero_daily_volume_participation(self):
        """Test handles zero daily volume in participation rate."""
        result = safe_compute_participation_rate(
            quantity=10_000,
            daily_volume=0,  # BUG: Zero volume
        )

        # Should return max participation (1.0), not crash
        assert result == 1.0

    def test_zero_quantity(self):
        """Test handles zero quantity."""
        result = safe_compute_participation_rate(
            quantity=0,
            daily_volume=1_000_000,
        )

        assert result == 0.0

    def test_normal_participation(self):
        """Test normal participation rate calculation."""
        result = safe_compute_participation_rate(
            quantity=50_000,
            daily_volume=1_000_000,
        )

        # 5% participation
        assert abs(result - 0.05) < 0.001


class TestCostCalculationBugFix:
    """Test cost sign correction for buy/sell orders."""

    def test_buy_order_costs_positive(self):
        """Test buy order costs are positive."""
        total, comm, impact, spread = compute_execution_cost_safely(
            quantity=10_000,  # Buy
            avg_execution_price=100.5,
            market_price=100.0,
            spread_cost=0.025,
            market_impact_cost=0.01,
            commission_bps=1.0,
        )

        # All costs should be positive for buy
        assert total > 0
        assert comm > 0
        assert impact > 0
        assert spread > 0

    def test_sell_order_costs_negative(self):
        """Test sell order costs are negative."""
        total, comm, impact, spread = compute_execution_cost_safely(
            quantity=-10_000,  # Sell
            avg_execution_price=99.5,
            market_price=100.0,
            spread_cost=0.025,
            market_impact_cost=0.01,
            commission_bps=1.0,
        )

        # All costs should be negative for sell
        assert total < 0
        assert comm < 0
        assert impact < 0
        assert spread < 0

    def test_zero_quantity_zero_cost(self):
        """Test zero quantity gives zero costs."""
        total, comm, impact, spread = compute_execution_cost_safely(
            quantity=0,
            avg_execution_price=100.0,
            market_price=100.0,
            spread_cost=0.025,
            market_impact_cost=0.01,
            commission_bps=1.0,
        )

        assert total == 0
        assert comm == 0
        assert impact == 0
        assert spread == 0


class TestNaNHandlingBugFix:
    """Test NaN propagation fix in weighting."""

    def test_nan_weights_filtered(self):
        """Test NaN weights are removed."""
        weights = {
            "s1": 0.4,
            "s2": np.nan,  # BUG: NaN value
            "s3": 0.3,
        }

        result = safe_normalize_weights(weights)

        # NaN should be filtered out
        assert "s2" not in result or result["s2"] > 0.05
        assert all(np.isfinite(w) for w in result.values())

    def test_infinite_weights_filtered(self):
        """Test infinite weights are removed."""
        weights = {
            "s1": 0.4,
            "s2": np.inf,  # BUG: Infinite value
            "s3": 0.3,
        }

        result = safe_normalize_weights(weights)

        # Infinite should be filtered out
        assert all(np.isfinite(w) for w in result.values())

    def test_all_invalid_weights_fallback(self):
        """Test fallback to equal weighting if all invalid."""
        weights = {
            "s1": np.nan,
            "s2": np.inf,
            "s3": -0.5,  # Negative
        }

        result = safe_normalize_weights(weights)

        # Should fallback to equal weighting
        assert len(result) == 3
        assert all(w > 0 for w in result.values())

    def test_normalize_sums_to_one(self):
        """Test normalized weights sum to 1."""
        weights = {
            "s1": 0.4,
            "s2": 0.3,
            "s3": 0.2,
        }

        result = safe_normalize_weights(weights)

        assert abs(sum(result.values()) - 1.0) < 0.001


class TestCircuitBreakerBugFix:
    """Test circuit breaker resettability."""

    def test_circuit_breaker_reset_daily(self):
        """Test circuit breaker resets daily."""
        cb = ResettableCircuitBreaker(
            type('Thresholds', (), {
                'daily_loss_pct': 5.0,
                'daily_loss_halt_pct': 8.0,
            })()
        )

        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Record loss today
        cb.reset_if_needed(today)
        assert cb.last_reset_date == today

        # Reset tomorrow
        assert cb.reset_if_needed(tomorrow)
        assert cb.last_reset_date == tomorrow

    def test_circuit_breaker_records_loss(self):
        """Test circuit breaker records loss safely."""
        cb = ResettableCircuitBreaker(
            type('Thresholds', (), {
                'daily_loss_pct': 5.0,
                'daily_loss_halt_pct': 8.0,
            })()
        )

        cb.record_loss(date.today(), -3.0)

        assert len(cb.daily_losses) == 1

    def test_circuit_breaker_invalid_loss_handling(self):
        """Test circuit breaker handles invalid loss values."""
        cb = ResettableCircuitBreaker(
            type('Thresholds', (), {
                'daily_loss_pct': 5.0,
                'daily_loss_halt_pct': 8.0,
            })()
        )

        # Should not crash with invalid value
        level, reason, recoverable = cb.check_circuit_breaker(
            date.today(),
            np.nan,  # Invalid
        )

        assert level == "NONE"


class TestWalkForwardValidation:
    """Test walk-forward data validation bug fix."""

    def test_sufficient_data_passes(self):
        """Test sufficient data passes validation."""
        train = pd.DataFrame({'returns': np.random.normal(0, 0.02, 300)})
        test = pd.DataFrame({'returns': np.random.normal(0, 0.02, 50)})

        is_valid, reason = validate_fold_data(train, test)

        assert is_valid

    def test_insufficient_train_data_fails(self):
        """Test insufficient train data fails."""
        train = pd.DataFrame({'returns': np.random.normal(0, 0.02, 50)})  # Too few
        test = pd.DataFrame({'returns': np.random.normal(0, 0.02, 50)})

        is_valid, reason = validate_fold_data(train, test)

        assert not is_valid
        assert "train" in reason.lower()

    def test_insufficient_test_data_fails(self):
        """Test insufficient test data fails."""
        train = pd.DataFrame({'returns': np.random.normal(0, 0.02, 300)})
        test = pd.DataFrame({'returns': np.random.normal(0, 0.02, 5)})  # Too few

        is_valid, reason = validate_fold_data(train, test)

        assert not is_valid
        assert "test" in reason.lower()

    def test_empty_train_data_fails(self):
        """Test empty train data fails."""
        train = pd.DataFrame({'returns': []})
        test = pd.DataFrame({'returns': np.random.normal(0, 0.02, 50)})

        is_valid, reason = validate_fold_data(train, test)

        assert not is_valid

    def test_nan_data_detected(self):
        """Test NaN in data is detected."""
        train = pd.DataFrame({
            'returns': [np.nan] + list(np.random.normal(0, 0.02, 299))
        })
        test = pd.DataFrame({'returns': np.random.normal(0, 0.02, 50)})

        is_valid, reason = validate_fold_data(train, test)

        assert not is_valid
        assert "NaN" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
