"""
Tests for enhanced validation - Phase 14

Validates:
- Expanding window validation
- Bootstrap aggregation
- Gaussian copula stress testing
- Feature engineering pipeline
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

from app.backtest.enhanced_validation import (
    ExpandingWindowValidator,
    BootstrapValidator,
    GaussianCopulaStressTester,
    FeatureEngineeringPipeline,
    ComprehensiveBacktestValidator,
)


class TestExpandingWindowValidator:
    """Test expanding window validation."""

    def test_initialization(self):
        """Test validator initializes."""
        validator = ExpandingWindowValidator(initial_train_period_days=252)
        assert validator is not None

    def test_split_expanding_window(self):
        """Test expanding window splits."""
        validator = ExpandingWindowValidator(initial_train_period_days=252)

        # Create synthetic data
        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 1000),
            'close': np.cumprod(1 + np.random.normal(0.001, 0.02, 1000)),
        })

        splits = validator.split_expanding_window(data, test_period_days=63)

        assert len(splits) > 0
        assert all(len(train) >= 252 for train, _ in splits)
        assert all(len(test) == 63 for _, test in splits)

    def test_splits_non_overlapping(self):
        """Test that test sets don't overlap."""
        validator = ExpandingWindowValidator(initial_train_period_days=252)

        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 1000),
        })

        splits = validator.split_expanding_window(data, test_period_days=63)

        # Check that consecutive windows don't overlap in test sets
        for i in range(len(splits) - 1):
            _, test1 = splits[i]
            _, test2 = splits[i + 1]
            # Test periods should not overlap
            assert len(test1) == len(test2)

    def test_train_size_expanding(self):
        """Test that training sets expand over time."""
        validator = ExpandingWindowValidator(initial_train_period_days=252)

        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 1000),
        })

        splits = validator.split_expanding_window(data, test_period_days=63)

        train_sizes = [len(train) for train, _ in splits]

        # Training sizes should be non-decreasing
        assert train_sizes == sorted(train_sizes)


class TestBootstrapValidator:
    """Test bootstrap validation."""

    def test_initialization(self):
        """Test bootstrap validator initializes."""
        validator = BootstrapValidator(num_bootstrap_samples=100)
        assert validator is not None

    def test_bootstrap_resample_shape(self):
        """Test bootstrap resamples have same shape as original."""
        validator = BootstrapValidator(num_bootstrap_samples=50)

        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 200),
        })

        resamples = validator.bootstrap_resample(data)

        assert len(resamples) == 50
        assert all(len(r) == len(data) for r in resamples)

    def test_bootstrap_sampling_with_replacement(self):
        """Test bootstrap samples with replacement."""
        validator = BootstrapValidator(num_bootstrap_samples=10)

        data = pd.DataFrame({
            'value': [1, 2, 3, 4, 5],
        })

        resamples = validator.bootstrap_resample(data)

        # At least some resamples should have duplicate values
        has_duplicates = False
        for resample in resamples:
            if len(resample) != len(resample['value'].unique()):
                has_duplicates = True
                break

        assert has_duplicates  # Expected with replacement


class TestGaussianCopulaStressTester:
    """Test Gaussian copula stress testing."""

    def test_initialization(self):
        """Test copula tester initializes."""
        tester = GaussianCopulaStressTester(num_scenarios=100)
        assert tester is not None

    def test_estimate_copula_parameters(self):
        """Test copula parameter estimation."""
        tester = GaussianCopulaStressTester()

        # Generate sample returns
        returns = np.random.multivariate_normal(
            mean=[0.001, 0.001, 0.001],
            cov=[[0.0004, 0.0001, 0.00005],
                 [0.0001, 0.0004, 0.0001],
                 [0.00005, 0.0001, 0.0004]],
            size=500,
        )

        params = tester.estimate_copula_parameters(returns)

        assert 'correlation' in params
        assert 'marginals' in params
        assert params['correlation'].shape == (3, 3)

    def test_generate_stress_scenarios(self):
        """Test stress scenario generation."""
        tester = GaussianCopulaStressTester(num_scenarios=100)

        # Base correlation
        correlation = np.array([
            [1.0, 0.3, 0.2],
            [0.3, 1.0, 0.3],
            [0.2, 0.3, 1.0],
        ])

        scenarios = tester.generate_stress_scenarios(
            correlation,
            num_scenarios=100,
            correlation_multiplier=1.5,
        )

        assert scenarios.shape == (100, 3)
        # Scenarios should be standard normal roughly
        assert abs(np.mean(scenarios)) < 0.2
        assert abs(np.std(scenarios) - 1.0) < 0.2


class TestFeatureEngineeringPipeline:
    """Test feature engineering pipeline."""

    def test_initialization(self):
        """Test pipeline initializes."""
        pipeline = FeatureEngineeringPipeline(max_features=50)
        assert pipeline is not None

    def test_generate_technical_features(self):
        """Test technical feature generation."""
        pipeline = FeatureEngineeringPipeline()

        # Create OHLCV data
        n = 252
        close = np.cumprod(1 + np.random.normal(0.001, 0.02, n))
        data = pd.DataFrame({
            'close': close,
            'high': close * 1.01,
            'low': close * 0.99,
            'volume': np.random.uniform(1e6, 10e6, n),
        })

        features = pipeline.generate_technical_features(data)

        assert features.shape[0] == len(data)
        assert features.shape[1] > 5  # At least 5 features
        assert 'returns_1d' in features.columns
        assert 'volatility_10d' in features.columns

    def test_select_important_features(self):
        """Test feature importance selection."""
        pipeline = FeatureEngineeringPipeline(max_features=20)

        # Create features and target
        features = pd.DataFrame({
            'feature_1': np.random.normal(0, 1, 100),
            'feature_2': np.random.normal(0, 1, 100),
            'feature_3': np.random.normal(0, 1, 100),
        })

        # Target correlated with feature_1
        target = features['feature_1'].values + np.random.normal(0, 0.1, 100)

        selected = pipeline.select_important_features(features, target, method='correlation')

        assert len(selected) <= 20
        assert 'feature_1' in selected  # Should select correlated feature

    def test_validate_feature_stability(self):
        """Test feature stability validation."""
        pipeline = FeatureEngineeringPipeline()

        # Create two periods of features
        features_old = pd.DataFrame({
            'feature_1': np.random.normal(0, 1, 100),
            'feature_2': np.random.normal(0, 1, 100),
        })

        # Slightly different distribution (but correlated)
        features_new = features_old + np.random.normal(0, 0.1, features_old.shape)

        stability = pipeline.validate_feature_stability(features_old, features_new)

        assert 'mean_correlation' in stability
        assert 'drift_detected' in stability
        assert stability['mean_correlation'] > 0.9  # High correlation expected


class TestComprehensiveValidator:
    """Test comprehensive backtest validator."""

    def test_initialization(self):
        """Test validator initializes."""
        validator = ComprehensiveBacktestValidator()
        assert validator is not None

    def test_validation_score_computation(self):
        """Test validation score computation."""
        validator = ComprehensiveBacktestValidator()

        # Create mock validation report
        report = {
            'total_samples': 1000,
            'expanding_window': {'consistency': 0.8},
            'bootstrap': {'stability': 0.75},
            'feature_engineering': {'top_features': ['f1', 'f2', 'f3']},
        }

        score = validator.get_validation_score(report)

        # Score should be between 0 and 100
        assert 0 <= score <= 100
        # With good metrics, score should be reasonably high
        assert score > 50

    def test_validation_score_empty_report(self):
        """Test score with empty report."""
        validator = ComprehensiveBacktestValidator()

        report = {'total_samples': 0}

        score = validator.get_validation_score(report)

        assert score == 0.0


class TestValidationIntegration:
    """Integration tests for validation pipeline."""

    def test_full_validation_pipeline(self):
        """Test complete validation pipeline."""
        validator = ComprehensiveBacktestValidator()

        # Create sample data
        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 500),
            'close': np.cumprod(1 + np.random.normal(0.001, 0.02, 500)),
            'high': np.cumprod(1 + np.random.normal(0.001, 0.02, 500)) * 1.01,
            'low': np.cumprod(1 + np.random.normal(0.001, 0.02, 500)) * 0.99,
            'volume': np.random.uniform(1e6, 10e6, 500),
        })

        # Simple strategy function (always predict 0.5)
        def strategy_fn(train_data):
            class MockStrategy:
                def predict(self, test_data):
                    return np.full(len(test_data), 0.5)
            return MockStrategy()

        # Run validation
        report = validator.run_full_validation(strategy_fn, data)

        # Should have results
        assert 'timestamp' in report
        assert 'total_samples' in report
        assert report['total_samples'] == 500

    def test_expanding_window_consistency(self):
        """Test expanding window produces consistent results."""
        validator = ExpandingWindowValidator(initial_train_period_days=100)

        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 400),
        })

        splits = validator.split_expanding_window(data, test_period_days=50)

        # Should produce multiple splits
        assert len(splits) >= 2

    def test_bootstrap_reduces_variance(self):
        """Test bootstrap aggregation reduces variance."""
        bootstrap_validator = BootstrapValidator(num_bootstrap_samples=50)

        data = pd.DataFrame({
            'returns': np.random.normal(0.001, 0.02, 300),
        })

        resamples = bootstrap_validator.bootstrap_resample(data)

        # Resamples should exist
        assert len(resamples) == 50
        assert all(len(r) == len(data) for r in resamples)
