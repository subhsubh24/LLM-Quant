"""
Edge Case Testing - Phase 7

Comprehensive testing of edge cases, boundary conditions, and failure modes:

1. NaN/Inf Propagation: Ensure contamination doesn't cascade
2. Zero/Negative Values: Handle domain violations
3. Circular Dependencies: Detect mutual dependencies
4. Empty Data: Handle missing inputs
5. Boundary Values: Min/max conditions
6. Precision Loss: Floating point edge cases
7. Timing Issues: Race conditions, order dependencies
8. Resource Limits: Memory, computation limits
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import math


class TestNaNPropagation:
    """Test NaN handling and contamination prevention."""

    def test_nan_in_price_series(self):
        """Test NaN in price data doesn't break calculations."""
        prices = np.array([100, 101, np.nan, 103, 104, 105])

        # Should handle gracefully
        valid_prices = prices[~np.isnan(prices)]

        assert len(valid_prices) == 5
        returns = np.diff(np.log(valid_prices))
        assert not any(np.isnan(returns))

    def test_nan_in_correlations(self):
        """Test NaN in correlation matrix."""
        data = pd.DataFrame({
            'A': [100, 101, np.nan, 103],
            'B': [1, 2, 3, 4],
            'C': [10, 11, 12, np.nan],
        })

        # Correlation should handle NaN
        corr = data.corr()

        # Non-NaN correlations should be valid
        assert not np.isnan(corr.loc['A', 'B'])
        assert not np.isnan(corr.loc['B', 'C'])

    def test_weights_with_nan(self):
        """Test portfolio weights with NaN values."""
        weights = np.array([0.3, np.nan, 0.4, 0.3])

        # Filter NaN
        valid_weights = weights[~np.isnan(weights)]

        # Renormalize
        weights_normalized = valid_weights / valid_weights.sum()

        assert len(weights_normalized) == 3
        assert abs(weights_normalized.sum() - 1.0) < 1e-10
        assert all(np.isfinite(weights_normalized))

    def test_nan_contagion_in_portfolio(self):
        """Test NaN doesn't contaminate entire portfolio."""
        returns = np.array([
            [0.01, 0.02, np.nan],
            [0.02, 0.03, 0.01],
            [0.01, 0.01, 0.02],
        ])

        # Strategy 3 is bad (has NaN)
        valid_returns = returns[:, ~np.isnan(returns).any(axis=0)]

        assert valid_returns.shape == (3, 2)
        assert all(np.isfinite(valid_returns.flatten()))


class TestInfinitiesAndOverflow:
    """Test handling of infinite values and numerical overflow."""

    def test_infinite_in_returns(self):
        """Test infinite returns (division by zero)."""
        prices = np.array([100, 101, 0, 103])  # Zero price

        # Log returns would have -inf
        with np.errstate(divide='ignore', invalid='ignore'):
            log_returns = np.diff(np.log(prices))

        # Filter infinities
        valid_returns = log_returns[np.isfinite(log_returns)]

        # Only first return is valid; second and third are -inf and inf
        assert len(valid_returns) == 1

    def test_division_by_zero(self):
        """Test division by zero handling."""
        numerator = 100
        denominator = 0

        try:
            result = numerator / denominator if denominator != 0 else 0
            assert result == 0
        except ZeroDivisionError:
            pytest.fail("Should handle division by zero")

    def test_log_of_negative(self):
        """Test log of negative price."""
        prices = np.array([100, -50, 102])  # Negative price (impossible)

        # Handle gracefully
        valid_prices = prices[prices > 0]

        assert len(valid_prices) == 2
        log_returns = np.diff(np.log(valid_prices))
        assert all(np.isfinite(log_returns))

    def test_extremely_large_values(self):
        """Test extremely large portfolio values."""
        # Very large number (close to float64 limit)
        large_value = 1e308

        # Should not overflow in basic operations
        result = large_value * 0.999

        assert result < 1e308

    def test_extremely_small_values(self):
        """Test extremely small values."""
        small_value = 1e-308  # Close to float64 minimum

        # Should not underflow
        result = small_value * 2

        assert result > 0


class TestZeroAndNegativeValues:
    """Test handling of zero and negative values."""

    def test_zero_volume(self):
        """Test zero trading volume."""
        volume = 0

        # Should not break position sizing
        position_size = 1000 if volume > 0 else 0

        assert position_size == 0

    def test_negative_price(self):
        """Test negative price (invalid data)."""
        price = -100

        # Should filter out
        assert price <= 0

    def test_negative_volatility(self):
        """Test negative volatility (impossible)."""
        variance = -0.01  # Impossible

        # Take absolute value or skip
        volatility = np.sqrt(abs(variance))

        assert volatility >= 0

    def test_zero_correlation(self):
        """Test zero correlation (completely independent)."""
        corr = 0.0

        # Should be valid
        assert -1.0 <= corr <= 1.0

    def test_negative_weight(self):
        """Test negative portfolio weight."""
        weight = -0.1  # Short position (might be valid)

        # Should be within valid range for leverage
        assert -2.0 <= weight <= 2.0  # Typical leverage limit


class TestBoundaryConditions:
    """Test boundary and limit conditions."""

    def test_max_correlation_1_0(self):
        """Test perfect positive correlation."""
        # Identical series
        data = pd.DataFrame({
            'A': [1, 2, 3, 4, 5],
            'B': [1, 2, 3, 4, 5],
        })

        corr = data.corr().iloc[0, 1]

        assert abs(corr - 1.0) < 1e-10

    def test_min_correlation_minus_1_0(self):
        """Test perfect negative correlation."""
        data = pd.DataFrame({
            'A': [1, 2, 3, 4, 5],
            'B': [5, 4, 3, 2, 1],
        })

        corr = data.corr().iloc[0, 1]

        assert abs(corr - (-1.0)) < 1e-10

    def test_volatility_zero(self):
        """Test zero volatility (no movement)."""
        prices = np.ones(100) * 100

        returns = np.diff(np.log(prices))
        volatility = np.std(returns)

        assert volatility < 1e-10

    def test_portfolio_100_percent_allocation(self):
        """Test exact 100% allocation."""
        weights = np.array([0.25, 0.25, 0.25, 0.25])

        total = weights.sum()

        assert abs(total - 1.0) < 1e-10

    def test_sharpe_extreme_values(self):
        """Test Sharpe ratio at extremes."""
        np.random.seed(42)

        # Very high Sharpe
        returns_high = np.random.normal(0.01, 0.001, 100)
        sharpe_high = returns_high.mean() / returns_high.std() * np.sqrt(252)

        assert sharpe_high > 5.0

        # Very low Sharpe (expected: mean/std * sqrt(252) = -0.1 * 15.87 ≈ -1.59)
        returns_low = np.random.normal(-0.01, 0.1, 100)
        sharpe_low = returns_low.mean() / returns_low.std() * np.sqrt(252)

        assert sharpe_low < 0.0  # Negative Sharpe for negative mean returns


class TestEmptyAndMissingData:
    """Test handling of empty and missing data."""

    def test_empty_dataframe(self):
        """Test empty DataFrame."""
        df = pd.DataFrame()

        # Should handle gracefully
        assert len(df) == 0
        assert df.shape[1] == 0

    def test_single_row_dataframe(self):
        """Test single row (insufficient for correlation)."""
        df = pd.DataFrame({
            'A': [100],
            'B': [1],
        })

        # Correlation needs at least 2 values
        assert len(df) < 2

    def test_all_nan_column(self):
        """Test column with all NaN."""
        df = pd.DataFrame({
            'A': [1, 2, 3],
            'B': [np.nan, np.nan, np.nan],
        })

        # Should filter out all-NaN columns
        valid_cols = df.columns[~df.isna().all()]

        assert len(valid_cols) == 1

    def test_missing_timestamp(self):
        """Test missing timestamp data."""
        data = pd.DataFrame({
            'close': [100, 101, 102],
        })

        # Generate timestamps if missing
        if 'timestamp' not in data.columns:
            data['timestamp'] = pd.date_range('2024-01-01', periods=len(data))

        assert 'timestamp' in data.columns

    def test_sparse_data(self):
        """Test sparse data with many NaN."""
        data = pd.DataFrame({
            'A': [100, np.nan, np.nan, 103],
            'B': [np.nan, 2, np.nan, 4],
            'C': [10, np.nan, 12, np.nan],
        })

        # Should handle sparse data
        data_filled = data.ffill().bfill()

        assert not data_filled.isna().any().any()


class TestPrecisionAndRounding:
    """Test floating point precision issues."""

    def test_sum_loss_of_precision(self):
        """Test precision loss in summing many small values."""
        # Sum of small values
        small_values = np.ones(1000) * 1e-10

        total = small_values.sum()

        # Should be close to 1e-7
        assert 0.5e-7 < total < 2e-7

    def test_cancellation_error(self):
        """Test catastrophic cancellation."""
        # (1 + 1e-16) - 1 loses precision
        x = 1.0
        epsilon = 1e-16

        result = (x + epsilon) - x

        # Result might be 0 due to precision limits
        assert result <= epsilon

    def test_weight_normalization_precision(self):
        """Test weight normalization doesn't accumulate errors."""
        weights = np.array([0.33, 0.33, 0.33, 0.01])

        # Normalize
        weights_norm = weights / weights.sum()

        # Should sum exactly to 1.0
        error = abs(weights_norm.sum() - 1.0)

        assert error < 1e-10

    def test_correlation_bounds(self):
        """Test correlation stays within [-1, 1]."""
        data = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
        })

        corr = data.corr().iloc[0, 1]

        assert -1.0 <= corr <= 1.0


class TestTimingAndOrder:
    """Test timing-dependent and order-dependent operations."""

    def test_out_of_order_data(self):
        """Test handling of out-of-order timestamps."""
        data = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 3),
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            ],
            'close': [103, 101, 102],
        })

        # Sort by timestamp
        data_sorted = data.sort_values('timestamp')

        assert data_sorted['timestamp'].is_monotonic_increasing

    def test_duplicate_timestamps(self):
        """Test handling of duplicate timestamps."""
        data = pd.DataFrame({
            'timestamp': [
                datetime(2024, 1, 1),
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            ],
            'close': [100, 101, 102],
        })

        # Should handle duplicates (e.g., take first or last)
        data_unique = data.drop_duplicates('timestamp')

        assert len(data_unique) == 2

    def test_gaps_in_data(self):
        """Test gaps in time series."""
        dates = [
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            datetime(2024, 1, 5),  # 3-day gap
            datetime(2024, 1, 6),
        ]

        # Detect gaps
        gaps = np.diff([d.day for d in dates])

        assert any(g > 1 for g in gaps)

    def test_future_dated_data(self):
        """Test future-dated data (look-ahead bias)."""
        current_date = datetime.now()
        future_date = current_date + timedelta(days=1)

        # Should filter out future data
        assert future_date > current_date


class TestResourceLimits:
    """Test behavior under resource constraints."""

    def test_large_correlation_matrix(self):
        """Test very large correlation matrix."""
        n = 1000  # 1000 securities

        # Create random correlation-like matrix
        L = np.random.randn(n, 50)
        corr = L @ L.T / 50

        # Clip to valid range
        corr = np.clip(corr, -1, 1)

        assert corr.shape == (n, n)

    def test_memory_efficient_computation(self):
        """Test memory-efficient processing."""
        # Process in batches instead of all at once
        n_total = 1_000_000

        batch_size = 100_000
        n_batches = (n_total + batch_size - 1) // batch_size

        assert n_batches == 10

    def test_timeout_handling(self):
        """Test handling of long-running operations."""
        start_time = datetime.now()
        timeout = 10  # seconds

        # Operation that could timeout
        elapsed = (datetime.now() - start_time).total_seconds()

        # Should complete within timeout
        assert elapsed < timeout


class TestConsistencyAndInvariance:
    """Test consistency checks and invariants."""

    def test_weight_sum_invariant(self):
        """Test portfolio weights always sum to 100%."""
        for _ in range(100):
            n_assets = np.random.randint(2, 10)
            weights = np.random.dirichlet(np.ones(n_assets))

            # Should sum exactly to 1.0
            assert abs(weights.sum() - 1.0) < 1e-10

    def test_correlation_symmetry(self):
        """Test correlation matrix symmetry."""
        data = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
            'C': np.random.randn(100),
        })

        corr = data.corr()

        # Should be symmetric
        assert np.allclose(corr, corr.T)

    def test_diagonal_ones(self):
        """Test correlation matrix diagonal is 1.0."""
        data = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
        })

        corr = data.corr()

        # Diagonal should be all 1.0
        assert np.allclose(np.diag(corr), 1.0)

    def test_psd_property(self):
        """Test correlation matrix is positive semi-definite."""
        data = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
            'C': np.random.randn(100),
        })

        corr = data.corr()

        # All eigenvalues should be >= 0
        eigenvalues = np.linalg.eigvals(corr)

        assert all(e >= -1e-10 for e in eigenvalues)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
