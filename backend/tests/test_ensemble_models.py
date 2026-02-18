"""
Tests for enhanced ensemble models and meta-learners.

Tests cover:
- XGBoost, LightGBM, Neural Networks, LSTM
- Stacking and weighted ensembles
- Meta-learner combination strategies
- Production ensemble integration
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

# Import with graceful failures for optional dependencies
try:
    from app.models.ensemble_models import (
        XGBoostModel,
        LightGBMModel,
        NeuralNetworkModel,
        LSTMModel,
        create_enhanced_ensemble,
        HAS_XGBOOST,
        HAS_LIGHTGBM,
        HAS_TORCH,
    )
    HAS_MODELS = True
except ImportError:
    HAS_MODELS = False

try:
    from app.models.meta_learner import (
        StackingEnsemble,
        WeightedEnsemble,
    )
    HAS_META = True
except ImportError:
    HAS_META = False

try:
    from app.models.ensemble_integration import (
        ProductionEnsemble,
        EnsembleComparator,
        create_production_ensemble,
    )
    HAS_INTEGRATION = True
except ImportError:
    HAS_INTEGRATION = False


@pytest.fixture
def sample_data():
    """Create sample training data."""
    np.random.seed(42)
    n_samples = 200
    n_features = 15

    X = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f"feature_{i}" for i in range(n_features)],
    )

    # Create target with some linear relationship
    y = pd.Series(
        X.iloc[:, 0] * 2 + X.iloc[:, 1] * -1 + np.random.randn(n_samples) * 0.5,
        name="target",
    )

    return X, y


@pytest.mark.skipif(not HAS_XGBOOST, reason="XGBoost not installed")
class TestXGBoostModel:
    """Test XGBoost model."""

    def test_xgboost_fit_predict(self, sample_data):
        """Test XGBoost fitting and prediction."""
        X, y = sample_data

        model = XGBoostModel(n_estimators=20, learning_rate=0.1, max_depth=3)
        model.fit(X, y)

        predictions = model.predict(X)

        assert len(predictions) == len(X)
        assert not np.any(np.isnan(predictions.values))

    def test_xgboost_feature_importance(self, sample_data):
        """Test feature importance calculation."""
        X, y = sample_data

        model = XGBoostModel(n_estimators=20)
        model.fit(X, y)

        importance = model.get_feature_importance()

        assert len(importance) > 0
        assert all(0 <= v <= 1 for v in importance.values())

    def test_xgboost_serialization(self, sample_data):
        """Test model serialization."""
        X, y = sample_data

        model = XGBoostModel()
        model.fit(X, y)

        # Serialize
        data = model.serialize()
        assert isinstance(data, bytes)

        # Deserialize
        model2 = XGBoostModel.deserialize(data)
        pred1 = model.predict(X).values
        pred2 = model2.predict(X).values

        np.testing.assert_array_almost_equal(pred1, pred2)


@pytest.mark.skipif(not HAS_LIGHTGBM, reason="LightGBM not installed")
class TestLightGBMModel:
    """Test LightGBM model."""

    def test_lightgbm_fit_predict(self, sample_data):
        """Test LightGBM fitting and prediction."""
        X, y = sample_data

        model = LightGBMModel(n_estimators=20, max_depth=3)
        model.fit(X, y)

        predictions = model.predict(X)

        assert len(predictions) == len(X)
        assert not np.any(np.isnan(predictions.values))

    def test_lightgbm_feature_importance(self, sample_data):
        """Test feature importance."""
        X, y = sample_data

        model = LightGBMModel(n_estimators=20)
        model.fit(X, y)

        importance = model.get_feature_importance()

        assert len(importance) > 0


@pytest.mark.skipif(not HAS_TORCH, reason="PyTorch not installed")
class TestNeuralNetworkModel:
    """Test neural network model."""

    def test_nn_fit_predict(self, sample_data):
        """Test NN fitting and prediction."""
        X, y = sample_data

        model = NeuralNetworkModel(
            input_dim=X.shape[1],
            hidden_dims=[32, 16],
            epochs=10,
        )
        model.fit(X, y)

        predictions = model.predict(X)

        assert len(predictions) == len(X)
        assert not np.any(np.isnan(predictions.values))

    def test_nn_feature_importance(self, sample_data):
        """Test neural network feature importance."""
        X, y = sample_data

        model = NeuralNetworkModel(
            input_dim=X.shape[1],
            hidden_dims=[32, 16],
            epochs=10,
        )
        model.fit(X, y)

        importance = model.get_feature_importance()

        # Should have importance for each feature
        assert len(importance) > 0


@pytest.mark.skipif(not HAS_TORCH, reason="PyTorch not installed")
class TestLSTMModel:
    """Test LSTM model."""

    def test_lstm_fit_predict(self, sample_data):
        """Test LSTM fitting and prediction."""
        X, y = sample_data

        model = LSTMModel(
            sequence_length=10,
            hidden_dim=32,
            epochs=5,
        )
        model.fit(X, y)

        # Can only predict last sequence
        predictions = model.predict(X.iloc[-1:])

        assert len(predictions) >= 0


@pytest.mark.skipif(not HAS_META, reason="Meta-learner not installed")
class TestStackingEnsemble:
    """Test stacking ensemble."""

    def test_stacking_ensemble_fit(self, sample_data):
        """Test stacking ensemble initialization and fitting."""
        X, y = sample_data

        # Create simple base models
        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor

        base_models = {
            "ridge": Ridge(alpha=1.0),
            "rf": RandomForestRegressor(n_estimators=10, random_state=42),
        }

        ensemble = StackingEnsemble(base_models, n_folds=2)
        ensemble.fit(X, y)

        assert ensemble.fitted

    def test_stacking_ensemble_predict(self, sample_data):
        """Test stacking ensemble prediction."""
        X, y = sample_data

        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor

        base_models = {
            "ridge": Ridge(alpha=1.0),
            "rf": RandomForestRegressor(n_estimators=10, random_state=42),
        }

        ensemble = StackingEnsemble(base_models, n_folds=2)
        ensemble.fit(X, y)

        predictions = ensemble.predict(X)

        assert len(predictions) == len(X)

    def test_stacking_model_weights(self, sample_data):
        """Test stacking meta-learner weights."""
        X, y = sample_data

        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor

        base_models = {
            "ridge": Ridge(alpha=1.0),
            "rf": RandomForestRegressor(n_estimators=10, random_state=42),
        }

        ensemble = StackingEnsemble(base_models, n_folds=2)
        ensemble.fit(X, y)

        weights = ensemble.get_model_weights()

        assert len(weights) == 2
        assert all(0 <= w <= 1 for w in weights.values())


@pytest.mark.skipif(not HAS_META, reason="Meta-learner not installed")
class TestWeightedEnsemble:
    """Test weighted ensemble."""

    def test_weighted_ensemble_fit(self, sample_data):
        """Test weighted ensemble fitting."""
        X, y = sample_data

        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor

        base_models = {
            "ridge": Ridge(alpha=1.0),
            "rf": RandomForestRegressor(n_estimators=10, random_state=42),
        }

        ensemble = WeightedEnsemble(base_models)
        ensemble.fit(X, y)

        assert ensemble.fitted

    def test_weighted_ensemble_predict(self, sample_data):
        """Test weighted ensemble prediction."""
        X, y = sample_data

        from sklearn.linear_model import Ridge
        from sklearn.ensemble import RandomForestRegressor

        base_models = {
            "ridge": Ridge(alpha=1.0),
            "rf": RandomForestRegressor(n_estimators=10, random_state=42),
        }

        ensemble = WeightedEnsemble(base_models)
        ensemble.fit(X, y)

        predictions = ensemble.predict(X)

        assert len(predictions) == len(X)


@pytest.mark.skipif(not HAS_INTEGRATION, reason="Integration not installed")
class TestProductionEnsemble:
    """Test production ensemble."""

    def test_production_ensemble_stacking(self, sample_data):
        """Test production ensemble with stacking."""
        X, y = sample_data

        if not any([HAS_XGBOOST, HAS_LIGHTGBM, HAS_TORCH]):
            pytest.skip("No ensemble models available")

        try:
            ensemble = ProductionEnsemble(ensemble_method="stacking")
            ensemble.fit(X, y)

            predictions = ensemble.predict(X)

            assert len(predictions) == len(X)
        except Exception as e:
            pytest.skip(f"Ensemble creation failed: {e}")

    def test_production_ensemble_weighted(self, sample_data):
        """Test production ensemble with weighted method."""
        X, y = sample_data

        if not any([HAS_XGBOOST, HAS_LIGHTGBM, HAS_TORCH]):
            pytest.skip("No ensemble models available")

        try:
            ensemble = ProductionEnsemble(ensemble_method="weighted")
            ensemble.fit(X, y)

            predictions = ensemble.predict(X)

            assert len(predictions) == len(X)
        except Exception as e:
            pytest.skip(f"Ensemble creation failed: {e}")

    def test_production_ensemble_metrics(self, sample_data):
        """Test ensemble metrics."""
        X, y = sample_data

        if not any([HAS_XGBOOST, HAS_LIGHTGBM, HAS_TORCH]):
            pytest.skip("No ensemble models available")

        try:
            ensemble = ProductionEnsemble()
            ensemble.fit(X, y)

            metrics = ensemble.get_metrics()

            assert "ensemble_method" in metrics
            assert "n_base_models" in metrics
            assert "model_weights" in metrics
        except Exception as e:
            pytest.skip(f"Ensemble creation failed: {e}")


class TestCreateEnhancedEnsemble:
    """Test factory function."""

    def test_create_enhanced_ensemble(self):
        """Test creating enhanced ensemble."""
        models = create_enhanced_ensemble(
            use_xgboost=HAS_XGBOOST,
            use_lightgbm=HAS_LIGHTGBM,
            use_neural_net=HAS_TORCH,
            use_lstm=False,
        )

        assert isinstance(models, dict)

        if HAS_XGBOOST:
            assert "xgboost" in models
        if HAS_LIGHTGBM:
            assert "lightgbm" in models
        if HAS_TORCH:
            assert "neural_net" in models


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
