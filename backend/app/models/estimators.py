"""
Model estimators for stock ranking.

These models predict expected returns or rank stocks by attractiveness.
All models are designed for cross-sectional prediction (ranking stocks
within each time period).

Key design principles:
1. Models should be robust to outliers and noise
2. Regularization is essential to prevent overfitting
3. Feature importance should be interpretable
4. Models should degrade gracefully with limited data
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
import pickle
from sklearn.linear_model import Ridge, ElasticNet
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import logging

logger = logging.getLogger(__name__)


class BaseRanker(ABC):
    """Abstract base class for ranking models."""

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseRanker":
        """Fit the model."""
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Predict scores (higher = more attractive)."""
        pass

    @abstractmethod
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        pass

    def rank(self, X: pd.DataFrame) -> pd.Series:
        """Rank stocks by predicted score (1 = best)."""
        scores = self.predict(X)
        return scores.rank(ascending=False)

    def serialize(self) -> bytes:
        """Serialize model for storage."""
        return pickle.dumps(self)

    @classmethod
    def deserialize(cls, data: bytes) -> "BaseRanker":
        """Deserialize model from storage."""
        return pickle.loads(data)


class RidgeRanker(BaseRanker):
    """
    Ridge regression for stock ranking.

    Pros:
    - Highly interpretable
    - Stable coefficients
    - Fast training
    - Works well with many correlated features

    Cons:
    - Assumes linear relationships
    - May underfit complex patterns
    """

    def __init__(self, alpha: float = 1.0, normalize: bool = True):
        self.alpha = alpha
        self.normalize = normalize
        self.model: Optional[Pipeline] = None
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RidgeRanker":
        self.feature_names = X.columns.tolist()

        # Build pipeline with optional scaling
        steps = []
        if self.normalize:
            steps.append(("scaler", StandardScaler()))
        steps.append(("ridge", Ridge(alpha=self.alpha)))

        self.model = Pipeline(steps)
        self.model.fit(X.values, y.values)

        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise ValueError("Model not fitted")

        preds = self.model.predict(X.values)
        return pd.Series(preds, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}

        ridge = self.model.named_steps["ridge"]
        coefs = ridge.coef_

        return dict(zip(self.feature_names, coefs))


class ElasticNetRanker(BaseRanker):
    """
    ElasticNet regression for stock ranking.

    Combines L1 (Lasso) and L2 (Ridge) regularization.

    Pros:
    - Feature selection via L1
    - Stability via L2
    - Interpretable

    Cons:
    - Still linear
    - Requires tuning l1_ratio
    """

    def __init__(
        self,
        alpha: float = 1.0,
        l1_ratio: float = 0.5,
        normalize: bool = True
    ):
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.normalize = normalize
        self.model: Optional[Pipeline] = None
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "ElasticNetRanker":
        self.feature_names = X.columns.tolist()

        steps = []
        if self.normalize:
            steps.append(("scaler", StandardScaler()))
        steps.append(("elasticnet", ElasticNet(
            alpha=self.alpha,
            l1_ratio=self.l1_ratio,
            max_iter=5000
        )))

        self.model = Pipeline(steps)
        self.model.fit(X.values, y.values)

        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise ValueError("Model not fitted")

        preds = self.model.predict(X.values)
        return pd.Series(preds, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}

        enet = self.model.named_steps["elasticnet"]
        return dict(zip(self.feature_names, enet.coef_))


class RandomForestRanker(BaseRanker):
    """
    Random Forest for stock ranking.

    Pros:
    - Captures nonlinear relationships
    - Handles interactions automatically
    - Robust to outliers
    - Built-in feature importance

    Cons:
    - Less interpretable
    - Can overfit if not regularized
    - Slower training
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        min_samples_leaf: int = 50,
        max_features: float = 0.3,
        random_state: int = 42
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.random_state = random_state
        self.model: Optional[RandomForestRegressor] = None
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "RandomForestRanker":
        self.feature_names = X.columns.tolist()

        self.model = RandomForestRegressor(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            max_features=self.max_features,
            random_state=self.random_state,
            n_jobs=-1
        )
        self.model.fit(X.values, y.values)

        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise ValueError("Model not fitted")

        preds = self.model.predict(X.values)
        return pd.Series(preds, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}

        return dict(zip(self.feature_names, self.model.feature_importances_))


class GradientBoostingRanker(BaseRanker):
    """
    Gradient Boosting for stock ranking.

    Pros:
    - Often best predictive performance
    - Handles nonlinearity
    - Sequential error correction

    Cons:
    - Prone to overfitting without care
    - Slower training
    - Less interpretable
    - Sensitive to hyperparameters
    """

    def __init__(
        self,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        max_depth: int = 3,
        min_samples_leaf: int = 50,
        subsample: float = 0.8,
        random_state: int = 42
    ):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.subsample = subsample
        self.random_state = random_state
        self.model: Optional[GradientBoostingRegressor] = None
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "GradientBoostingRanker":
        self.feature_names = X.columns.tolist()

        self.model = GradientBoostingRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            subsample=self.subsample,
            random_state=self.random_state
        )
        self.model.fit(X.values, y.values)

        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise ValueError("Model not fitted")

        preds = self.model.predict(X.values)
        return pd.Series(preds, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        if self.model is None:
            return {}

        return dict(zip(self.feature_names, self.model.feature_importances_))


class EnsembleRanker(BaseRanker):
    """
    Ensemble of multiple ranking models.

    Combines predictions from multiple models using simple averaging
    or weighted averaging based on validation performance.

    This is often more robust than any single model.
    """

    def __init__(
        self,
        models: Optional[List[BaseRanker]] = None,
        weights: Optional[List[float]] = None
    ):
        if models is None:
            # Default ensemble
            models = [
                RidgeRanker(alpha=1.0),
                ElasticNetRanker(alpha=0.5, l1_ratio=0.5),
                RandomForestRanker(n_estimators=100, max_depth=5),
            ]
        self.models = models
        self.weights = weights or [1.0 / len(models)] * len(models)
        self.fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "EnsembleRanker":
        for model in self.models:
            model.fit(X, y)
        self.fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if not self.fitted:
            raise ValueError("Model not fitted")

        predictions = []
        for model, weight in zip(self.models, self.weights):
            pred = model.predict(X)
            predictions.append(pred * weight)

        combined = sum(predictions)
        return combined

    def get_feature_importance(self) -> Dict[str, float]:
        """Get averaged feature importance across models."""
        all_importance: Dict[str, List[float]] = {}

        for model, weight in zip(self.models, self.weights):
            imp = model.get_feature_importance()
            for feature, value in imp.items():
                if feature not in all_importance:
                    all_importance[feature] = []
                all_importance[feature].append(abs(value) * weight)

        # Average importance
        return {k: np.mean(v) for k, v in all_importance.items()}

    def get_model_diagnostics(self) -> List[Dict[str, Any]]:
        """Get diagnostics for each model in ensemble."""
        diagnostics = []
        for i, model in enumerate(self.models):
            diagnostics.append({
                "model_index": i,
                "model_type": type(model).__name__,
                "weight": self.weights[i],
                "n_features": len(model.get_feature_importance()),
            })
        return diagnostics
