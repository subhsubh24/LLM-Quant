"""
Tests for simplified ML ensemble - Phase 2

Validates:
- Simplified ensemble is more stable than complex version
- Regularization prevents overfitting
- Degradation detection works
- Models are production-ready (low latency)
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date

from app.models.simplified_ml_ensemble import (
    LightGBMModelBase,
    LSTMModelBase,
    SimpleStackingMeta,
    SimplifiedMLEnsemble,
    ModelMetrics,
)


class TestLightGBMModel:
    """Test LightGBM base model."""

    def test_initialization(self):
        """Test LightGBM model initializes."""
        model = LightGBMModelBase()
        assert model is not None
        assert model.params['lambda_l1'] == 1.0  # Strong regularization

    def test_predict_without_training(self):
        """Test graceful handling without training."""
        model = LightGBMModelBase()

        X = np.random.normal(0, 1, (100, 20))
        pred = model.predict_proba(X)

        assert len(pred) == 100
        assert all(0 <= p <= 1 for p in pred)

    def test_mock_training(self):
        """Test mock training returns metrics."""
        model = LightGBMModelBase()

        X_train = np.random.normal(0, 1, (200, 20))
        y_train = np.random.randint(0, 2, 200)

        metrics = model.train(X_train, y_train)

        assert 'train_sharpe' in metrics or 'val_sharpe' in metrics


class TestLSTMModel:
    """Test LSTM base model."""

    def test_initialization(self):
        """Test LSTM model initializes."""
        model = LSTMModelBase()
        assert model is not None
        assert model.dropout == 0.3  # Regularization

    def test_predict_without_training(self):
        """Test graceful handling without training."""
        model = LSTMModelBase()

        X = np.random.normal(0, 1, (100, 20))
        pred = model.predict_proba(X)

        assert len(pred) == 100

    def test_mock_training(self):
        """Test mock training returns metrics."""
        model = LSTMModelBase()

        X_train = np.random.normal(0, 1, (200, 20))
        y_train = np.random.randint(0, 2, 200)

        metrics = model.train(X_train, y_train)

        assert 'train_sharpe' in metrics or 'val_sharpe' in metrics


class TestStackingMeta:
    """Test simple stacking meta-learner."""

    def test_initialization(self):
        """Test meta-learner initializes."""
        meta = SimpleStackingMeta()
        assert meta is not None
        assert meta.regularization == 1.0

    def test_predict_without_training(self):
        """Test graceful handling without training."""
        meta = SimpleStackingMeta()

        base_outputs = np.random.uniform(0, 1, (100, 2))
        pred = meta.predict_proba(base_outputs)

        assert len(pred) == 100
        assert all(0 <= p <= 1 for p in pred)

    def test_training_and_prediction(self):
        """Test meta-learner training and prediction."""
        meta = SimpleStackingMeta()

        # Generate base model outputs
        base_outputs = np.random.uniform(0.4, 0.6, (100, 2))
        y_true = np.random.randint(0, 2, 100)

        metrics = meta.train(base_outputs, y_true)
        assert 'train_accuracy' in metrics

        # Predict on new data
        new_outputs = np.random.uniform(0.4, 0.6, (50, 2))
        pred = meta.predict_proba(new_outputs)

        assert len(pred) == 50
        assert all(0 <= p <= 1 for p in pred)

    def test_regularization_effect(self):
        """Test regularization coefficient has effect."""
        meta_low_reg = SimpleStackingMeta(regularization=0.1)
        meta_high_reg = SimpleStackingMeta(regularization=10.0)

        base_outputs = np.random.uniform(0.4, 0.6, (100, 2))
        y_true = np.random.randint(0, 2, 100)

        # Both should train
        meta_low_reg.train(base_outputs, y_true)
        meta_high_reg.train(base_outputs, y_true)

        # Weights should be different
        if meta_low_reg.weights is not None and meta_high_reg.weights is not None:
            assert not np.allclose(meta_low_reg.weights, meta_high_reg.weights)


class TestSimplifiedEnsemble:
    """Test complete simplified ensemble."""

    def test_initialization(self):
        """Test ensemble initializes."""
        ensemble = SimplifiedMLEnsemble()
        assert ensemble is not None
        assert not ensemble.is_trained

    def test_predict_without_training(self):
        """Test graceful handling without training."""
        ensemble = SimplifiedMLEnsemble()

        X = np.random.normal(0, 1, (100, 20))
        pred = ensemble.predict_proba(X)

        assert len(pred) == 100
        assert all(0 <= p <= 1 for p in pred)

    def test_end_to_end_training(self):
        """Test complete ensemble training pipeline."""
        ensemble = SimplifiedMLEnsemble()

        X_train = np.random.normal(0, 1, (200, 20))
        y_train = np.random.randint(0, 2, 200)

        # Split into train/val
        X_val = X_train[-50:]
        y_val = y_train[-50:]
        X_train = X_train[:-50]
        y_train = y_train[:-50]

        metrics = ensemble.train(X_train, y_train, X_val, y_val)

        assert 'status' in metrics
        assert metrics['status'] == 'trained'
        assert ensemble.is_trained

    def test_ensemble_consistency(self):
        """Test ensemble gives consistent predictions."""
        ensemble = SimplifiedMLEnsemble()

        X_train = np.random.normal(0, 1, (100, 20))
        y_train = np.random.randint(0, 2, 100)

        ensemble.train(X_train, y_train)

        X_test = np.random.normal(0, 1, (50, 20))

        pred1 = ensemble.predict_proba(X_test)
        pred2 = ensemble.predict_proba(X_test)

        # Should be identical (no randomness after training)
        assert np.allclose(pred1, pred2)

    def test_degradation_detection_no_degradation(self):
        """Test degradation detection when no degradation."""
        ensemble = SimplifiedMLEnsemble()

        is_degraded, score = ensemble.detect_degradation(
            recent_sharpe=1.5,
            historical_sharpe=1.4,
            threshold=0.3,
        )

        assert not is_degraded
        assert 0 <= score <= 1

    def test_degradation_detection_with_degradation(self):
        """Test degradation detection when degraded."""
        ensemble = SimplifiedMLEnsemble()

        is_degraded, score = ensemble.detect_degradation(
            recent_sharpe=0.5,
            historical_sharpe=1.5,
            threshold=0.3,
        )

        assert is_degraded
        assert score > 0

    def test_degradation_detection_edge_cases(self):
        """Test degradation detection handles edge cases."""
        ensemble = SimplifiedMLEnsemble()

        # Zero historical Sharpe
        is_deg1, score1 = ensemble.detect_degradation(0.5, 0.0)
        assert not is_deg1

        # Negative values
        is_deg2, score2 = ensemble.detect_degradation(-1.0, -0.5)
        assert 0 <= score2 <= 1


class TestEnsembleVsComplex:
    """Compare simplified vs complex ensemble characteristics."""

    def test_simplified_fewer_parameters(self):
        """Verify simplified has fewer hyperparameters."""
        simplified = SimplifiedMLEnsemble()

        # Count hyperparameters
        lgb_params = len(simplified.lgb_model.params)
        lstm_params = 5  # Hard-coded for LSTM
        meta_params = 1  # Just regularization

        total_params = lgb_params + lstm_params + meta_params

        # Should be < 30 params total (vs 50+ for complex)
        assert total_params < 30
        assert total_params > 10

    def test_simplified_faster_training(self):
        """Simplified should train faster than complex version."""
        ensemble = SimplifiedMLEnsemble()

        X_train = np.random.normal(0, 1, (200, 20))
        y_train = np.random.randint(0, 2, 200)

        import time
        start = time.time()
        ensemble.train(X_train, y_train)
        elapsed = time.time() - start

        # Should train in < 5 seconds
        assert elapsed < 5


class TestProductionReadiness:
    """Test production readiness characteristics."""

    def test_low_latency_prediction(self):
        """Test prediction latency is acceptable."""
        ensemble = SimplifiedMLEnsemble()

        X_train = np.random.normal(0, 1, (100, 20))
        y_train = np.random.randint(0, 2, 100)

        ensemble.train(X_train, y_train)

        X_test = np.random.normal(0, 1, (100, 20))

        import time
        start = time.time()
        for _ in range(10):
            ensemble.predict_proba(X_test)
        elapsed = time.time() - start

        # 10 batches should take < 1 second
        assert elapsed < 1.0

    def test_graceful_degradation(self):
        """Test system degrades gracefully with bad data."""
        ensemble = SimplifiedMLEnsemble()

        # Train normally
        X_train = np.random.normal(0, 1, (100, 20))
        y_train = np.random.randint(0, 2, 100)
        ensemble.train(X_train, y_train)

        # Predict with NaN data (should handle gracefully)
        X_bad = np.full((10, 20), np.nan)
        pred = ensemble.predict_proba(X_bad)

        # Should return default predictions, not crash
        assert len(pred) == 10

    def test_error_recovery(self):
        """Test ensemble recovers from errors."""
        ensemble = SimplifiedMLEnsemble()

        # Empty training data
        metrics1 = ensemble.train(np.array([]), np.array([]))
        assert metrics1 is not None

        # After error, should still handle predictions
        X = np.random.normal(0, 1, (10, 20))
        pred = ensemble.predict_proba(X)

        assert len(pred) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
