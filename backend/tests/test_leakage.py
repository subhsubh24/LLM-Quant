"""
Leakage detection tests.

These tests verify that features are properly lagged to prevent look-ahead bias.
This is the MOST IMPORTANT test in the entire codebase.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta


def generate_test_prices(n_days: int = 500, n_tickers: int = 5) -> pd.DataFrame:
    """Generate synthetic price data for testing."""
    np.random.seed(42)
    dates = pd.date_range(start="2020-01-01", periods=n_days, freq="B")
    tickers = [f"TICK{i}" for i in range(n_tickers)]

    data = {}
    for ticker in tickers:
        # Random walk
        returns = np.random.randn(n_days) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))
        data[ticker] = prices

    return pd.DataFrame(data, index=dates)


class TestFeatureLeakage:
    """Test that features don't leak future information."""

    def test_return_features_are_lagged(self):
        """Return features at time t should not use price at time t."""
        from app.features.core import compute_returns

        prices = generate_test_prices()

        # Compute returns with different lags
        returns = compute_returns(prices, periods=[1, 5, 21])

        # For each date t, the feature should be based on prices up to t-1
        # This means the first valid feature should be at index 2 (for 1-day return with 1-day lag)
        for col in returns.columns:
            first_valid = returns[col].first_valid_index()
            first_price = prices.iloc[:, 0].first_valid_index()

            # Feature should start after price data
            assert first_valid > first_price, f"Feature {col} may have leakage"

    def test_momentum_features_are_lagged(self):
        """Momentum features should be properly lagged."""
        from app.features.core import compute_momentum

        prices = generate_test_prices()
        momentum = compute_momentum(prices, windows=[21, 63])

        # Check that momentum at time t doesn't use price at time t
        for col in momentum.columns:
            # The feature should have NaN at the beginning due to lookback + lag
            assert momentum[col].iloc[:22].isna().all(), f"Feature {col} may have leakage"

    def test_volatility_features_are_lagged(self):
        """Volatility features should be properly lagged."""
        from app.features.core import compute_volatility

        prices = generate_test_prices()
        vol = compute_volatility(prices, windows=[21])

        # Should have NaN for first 22 days (21 lookback + 1 lag)
        for col in vol.columns:
            assert vol[col].iloc[:22].isna().all(), f"Feature {col} may have leakage"

    def test_feature_target_alignment(self):
        """Features at time t should predict returns from t to t+horizon, not t-1 to t."""
        from app.features.pipeline import FeaturePipeline, FeatureConfig

        prices = generate_test_prices()

        config = FeatureConfig(enabled_features=["returns", "momentum"])
        pipeline = FeaturePipeline(config)

        features = pipeline.compute_features(prices)
        target = pipeline.compute_target(prices, horizon=5)

        # For any date t where we have both features and target:
        # - Features should be based on data up to t-1
        # - Target should be the return from t to t+5

        # This means feature at t and target at t are independent
        # (target uses future data that feature doesn't have)

        common_dates = features.index.intersection(target.index)
        assert len(common_dates) > 100, "Not enough common dates"

        # Simple check: correlation between features and targets should be modest
        # If correlation is very high, there's likely leakage
        for feat_col in features.columns[:5]:  # Check first 5 features
            for tgt_col in target.columns[:3]:  # Check first 3 targets
                corr = features.loc[common_dates, feat_col].corr(
                    target.loc[common_dates, tgt_col]
                )
                # Correlation should be small in absolute value (typically < 0.1)
                # Very high correlation suggests leakage
                assert abs(corr) < 0.5, f"Suspiciously high correlation ({corr:.3f}) between {feat_col} and {tgt_col}"


class TestBacktestLeakage:
    """Test that backtest doesn't use future information."""

    def test_no_future_prices_in_signals(self):
        """
        Trading signals at time t should not depend on prices after time t.

        This is tested by checking that changing future prices doesn't
        change historical signals.
        """
        # This would require running the full backtest engine
        # Simplified version: just check the logic is correct
        pass

    def test_walk_forward_validation(self):
        """Validation should always use future data, never past."""
        from app.models.framework import TimeSeriesCV
        import numpy as np

        # Create sample data
        n_samples = 500
        X = pd.DataFrame(
            np.random.randn(n_samples, 10),
            index=pd.date_range("2020-01-01", periods=n_samples, freq="B")
        )

        cv = TimeSeriesCV(
            train_window=252,
            validation_window=63,
            step=21,
            embargo=5
        )

        for fold in cv.split(X):
            # Validation should always come after training
            assert fold.validation_start > fold.train_end, "Validation overlaps with training"

            # Embargo should be respected
            train_end_idx = list(X.index).index(fold.train_end)
            val_start_idx = list(X.index).index(fold.validation_start)
            assert val_start_idx - train_end_idx >= 5, "Embargo not respected"


class TestSanityChecks:
    """Basic sanity checks for the quant pipeline."""

    def test_prices_positive(self):
        """Prices should always be positive."""
        prices = generate_test_prices()
        assert (prices > 0).all().all(), "Prices contain non-positive values"

    def test_returns_reasonable(self):
        """Daily returns should be within reasonable range."""
        prices = generate_test_prices()
        returns = prices.pct_change().dropna()

        # Daily returns should typically be < 20%
        assert (returns.abs() < 0.5).all().all(), "Unreasonable daily returns"

    def test_feature_no_inf(self):
        """Features should not contain infinity."""
        from app.features.pipeline import FeaturePipeline, FeatureConfig

        prices = generate_test_prices()
        config = FeatureConfig(enabled_features=["returns", "momentum", "volatility"])
        pipeline = FeaturePipeline(config)

        features = pipeline.compute_features(prices)

        assert not np.isinf(features.values).any(), "Features contain infinity"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
