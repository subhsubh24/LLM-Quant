"""
Integration of enhanced ensemble models with existing signal engine.

Provides drop-in replacement for base estimators with:
- Modern gradient boosting (XGBoost, LightGBM)
- Deep learning (PyTorch neural networks)
- Stacking ensemble for optimal combination
- Model comparison and selection

Usage:
    # Create ensemble
    ensemble = create_production_ensemble(X, y)

    # Make predictions
    predictions = ensemble.predict(X_test)

    # Get feature importance
    importance = ensemble.get_feature_importance()
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass  # CRITICAL FIX: Missing import for @dataclass decorator
import numpy as np
import pandas as pd
import logging
import pickle  # CRITICAL FIX: Move from line 378 to here (was after use at line 350)
from datetime import datetime

from .ensemble_models import (
    BaseModel,
    XGBoostModel,
    LightGBMModel,
    NeuralNetworkModel,
    LSTMModel,
    create_enhanced_ensemble,
    HAS_XGBOOST,
    HAS_LIGHTGBM,
    HAS_TORCH,
)
from .meta_learner import StackingEnsemble, WeightedEnsemble

logger = logging.getLogger(__name__)


@dataclass
class EnsembleComparison:
    """Comparison of ensemble methods."""
    method: str  # 'stacking' | 'weighted' | 'simple'
    n_models: int
    train_score: float
    val_score: float
    inference_time_ms: float
    model_weights: Dict[str, float]


class ProductionEnsemble:
    """
    Production-grade ensemble combining modern ML techniques.

    Features:
    - Gradient boosting (XGBoost, LightGBM)
    - Deep learning (neural networks)
    - Intelligent combination (stacking or weighting)
    - Model comparison and selection
    - Feature importance tracking
    """

    def __init__(
        self,
        ensemble_method: str = "stacking",  # 'stacking' | 'weighted' | 'simple'
        use_xgboost: bool = True,
        use_lightgbm: bool = True,
        use_neural_net: bool = True,
        use_lstm: bool = False,
        device: str = "cpu",
    ):
        """
        Initialize production ensemble.

        Args:
            ensemble_method: How to combine base models
            use_xgboost: Include XGBoost
            use_lightgbm: Include LightGBM
            use_neural_net: Include neural network
            use_lstm: Include LSTM (for sequential data)
            device: PyTorch device ('cpu' or 'cuda')
        """
        self.ensemble_method = ensemble_method
        self.device = device

        # Create base models
        self.base_models = create_enhanced_ensemble(
            use_xgboost=use_xgboost and HAS_XGBOOST,
            use_lightgbm=use_lightgbm and HAS_LIGHTGBM,
            use_neural_net=use_neural_net and HAS_TORCH,
            use_lstm=use_lstm and HAS_TORCH,
            device=device,
        )

        if not self.base_models:
            raise ValueError("No models available - check dependencies")

        logger.info(f"Created ensemble with {len(self.base_models)} base models")

        # Create ensemble method
        if ensemble_method == "stacking":
            self.ensemble = StackingEnsemble(
                base_models=self.base_models,
                n_folds=5,
            )
        elif ensemble_method == "weighted":
            self.ensemble = WeightedEnsemble(
                base_models=self.base_models,
                validation_split=0.2,
            )
        else:
            raise ValueError(f"Unknown ensemble method: {ensemble_method}")

        self.fitted = False
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "ProductionEnsemble":
        """Fit ensemble."""
        logger.info(f"Fitting ensemble ({self.ensemble_method}) with {len(self.base_models)} models")

        self.feature_names = X.columns.tolist()

        # Fit ensemble
        self.ensemble.fit(X, y)
        self.fitted = True

        logger.info("Ensemble fitted successfully")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions."""
        if not self.fitted:
            raise ValueError("Ensemble not fitted")

        return self.ensemble.predict(X)

    def get_feature_importance(self) -> Dict[str, float]:
        """Get weighted feature importance."""
        if not self.fitted:
            return {}

        return self.ensemble.get_feature_importance()

    def get_model_weights(self) -> Dict[str, float]:
        """Get weights for each base model."""
        if hasattr(self.ensemble, "get_model_weights"):
            return self.ensemble.get_model_weights()
        else:
            return {name: 1.0 / len(self.base_models) for name in self.base_models}

    def get_metrics(self) -> Dict[str, Any]:
        """Get ensemble metrics."""
        return {
            "ensemble_method": self.ensemble_method,
            "n_base_models": len(self.base_models),
            "model_names": list(self.base_models.keys()),
            "model_weights": self.get_model_weights(),
            "feature_importance": self.get_feature_importance(),
        }


class EnsembleComparator:
    """
    Compare different ensemble methods to select best one.

    Evaluates:
    - Stacking ensemble
    - Weighted ensemble
    - Simple averaging
    - Individual models (for baseline)
    """

    def __init__(self, device: str = "cpu"):
        """Initialize comparator."""
        self.device = device
        self.results: List[EnsembleComparison] = []

    def compare_methods(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        test_size: float = 0.2,
    ) -> pd.DataFrame:
        """
        Compare ensemble methods.

        Args:
            X: Training features
            y: Training targets
            test_size: Fraction for test set

        Returns:
            DataFrame with comparison results
        """
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import r2_score
        import time

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )

        results = []

        # Method 1: Stacking ensemble
        try:
            logger.info("Evaluating stacking ensemble...")
            start_time = time.time()

            ensemble = ProductionEnsemble(
                ensemble_method="stacking",
                device=self.device,
            )
            ensemble.fit(X_train, y_train)

            pred = ensemble.predict(X_test)
            score = r2_score(y_test, pred)
            inference_time = (time.time() - start_time) * 1000 / len(X_test)

            results.append({
                "method": "stacking",
                "n_models": len(ensemble.base_models),
                "score": score,
                "inference_time_ms": inference_time,
                "weights": ensemble.get_model_weights(),
            })

            logger.info(f"Stacking R2: {score:.4f}")

        except Exception as e:
            logger.warning(f"Stacking failed: {e}")

        # Method 2: Weighted ensemble
        try:
            logger.info("Evaluating weighted ensemble...")
            start_time = time.time()

            ensemble = ProductionEnsemble(
                ensemble_method="weighted",
                device=self.device,
            )
            ensemble.fit(X_train, y_train)

            pred = ensemble.predict(X_test)
            score = r2_score(y_test, pred)
            inference_time = (time.time() - start_time) * 1000 / len(X_test)

            results.append({
                "method": "weighted",
                "n_models": len(ensemble.base_models),
                "score": score,
                "inference_time_ms": inference_time,
                "weights": ensemble.get_model_weights(),
            })

            logger.info(f"Weighted R2: {score:.4f}")

        except Exception as e:
            logger.warning(f"Weighted failed: {e}")

        # Convert to DataFrame
        results_df = pd.DataFrame(results)
        return results_df

    @staticmethod
    def get_best_method(comparison_df: pd.DataFrame) -> str:
        """Get best ensemble method from comparison."""
        if len(comparison_df) == 0:
            return "stacking"  # Default

        best_idx = comparison_df["score"].idxmax()
        return comparison_df.loc[best_idx, "method"]


def create_production_ensemble(
    X: pd.DataFrame,
    y: pd.Series,
    ensemble_method: str = "auto",  # 'auto' to select best
    device: str = "cpu",
) -> ProductionEnsemble:
    """
    Factory function to create and train production ensemble.

    Args:
        X: Training features
        y: Training targets
        ensemble_method: 'auto', 'stacking', or 'weighted'
        device: PyTorch device

    Returns:
        Fitted ProductionEnsemble
    """
    if ensemble_method == "auto":
        # Compare methods and select best
        logger.info("Auto-selecting best ensemble method...")
        comparator = EnsembleComparator(device=device)
        comparison = comparator.compare_methods(X, y)

        if len(comparison) == 0:
            ensemble_method = "weighted"
            logger.warning("Comparison failed, using weighted ensemble")
        else:
            ensemble_method = comparator.get_best_method(comparison)
            logger.info(f"Selected ensemble method: {ensemble_method}")

    # Create and train ensemble
    ensemble = ProductionEnsemble(
        ensemble_method=ensemble_method,
        device=device,
    )
    ensemble.fit(X, y)

    return ensemble


def compare_with_baseline(
    X: pd.DataFrame,
    y: pd.Series,
    baseline_model: BaseModel,
    test_size: float = 0.2,
) -> Dict[str, float]:
    """
    Compare ensemble with baseline model.

    Args:
        X: Features
        y: Targets
        baseline_model: Baseline model to compare against
        test_size: Fraction for test set

    Returns:
        Dict with comparison metrics
    """
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42
    )

    # Train ensemble
    ensemble = create_production_ensemble(X_train, y_train)
    ensemble_pred = ensemble.predict(X_test)

    # Train baseline
    baseline_copy = pickle.loads(pickle.dumps(baseline_model))
    baseline_copy.fit(X_train, y_train)
    baseline_pred = baseline_copy.predict(X_test)

    # Compare
    ensemble_r2 = r2_score(y_test, ensemble_pred)
    baseline_r2 = r2_score(y_test, baseline_pred)

    ensemble_rmse = np.sqrt(mean_squared_error(y_test, ensemble_pred))
    baseline_rmse = np.sqrt(mean_squared_error(y_test, baseline_pred))

    ensemble_mae = mean_absolute_error(y_test, ensemble_pred)
    baseline_mae = mean_absolute_error(y_test, baseline_pred)

    improvement_r2 = (ensemble_r2 - baseline_r2) / (abs(baseline_r2) + 1e-10)

    return {
        "ensemble_r2": ensemble_r2,
        "baseline_r2": baseline_r2,
        "r2_improvement_pct": improvement_r2 * 100,
        "ensemble_rmse": ensemble_rmse,
        "baseline_rmse": baseline_rmse,
        "rmse_improvement_pct": (1 - ensemble_rmse / (baseline_rmse + 1e-10)) * 100,
        "ensemble_mae": ensemble_mae,
        "baseline_mae": baseline_mae,
    }

