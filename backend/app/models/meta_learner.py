"""
Meta-Learner for Ensemble Stacking

Implements stacking ensemble that:
1. Trains individual models on training data
2. Generates meta-features from model predictions on validation data
3. Trains meta-learner to combine predictions optimally
4. Uses meta-learner for final predictions

This is more sophisticated than simple averaging - it learns
which models work best in which situations.

References:
- Wolpert (1992) "Stacked Generalization"
- Breiman (1996) "Stacked Regressions"
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import logging
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold

logger = logging.getLogger(__name__)


@dataclass
class StackingMetrics:
    """Metrics for stacking ensemble."""
    n_models: int
    n_folds: int
    train_r2: float
    val_r2: float
    model_weights: Dict[str, float] = field(default_factory=dict)
    model_train_scores: Dict[str, float] = field(default_factory=dict)
    model_val_scores: Dict[str, float] = field(default_factory=dict)


class StackingEnsemble:
    """
    Stacking ensemble that learns to combine model predictions.

    Process:
    1. Split data into K folds
    2. For each fold:
       a. Train all models on fold training data
       b. Predict on fold validation data (generate meta-features)
    3. Train meta-learner on meta-features to predict targets
    4. For final predictions:
       a. All models predict → meta-features
       b. Meta-learner combines predictions
    """

    def __init__(
        self,
        base_models: Dict[str, Any],
        meta_model: Optional[Any] = None,
        n_folds: int = 5,
        random_seed: int = 42,
    ):
        """
        Initialize stacking ensemble.

        Args:
            base_models: Dict of model_name -> model_instance
            meta_model: Model for combining predictions (default: Ridge regression)
            n_folds: Number of folds for cross-validation
            random_seed: Random seed for reproducibility
        """
        self.base_models = base_models
        self.meta_model = meta_model or Ridge(alpha=1.0)
        self.n_folds = n_folds
        self.random_seed = random_seed

        # Track trained models
        self.trained_models: Dict[str, List[Any]] = {}  # model_name -> [fold_models]
        self.meta_learner: Optional[Any] = None
        self.fitted = False
        self.feature_names: List[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "StackingEnsemble":
        """
        Fit stacking ensemble using cross-validation.

        Args:
            X: Training features
            y: Training targets

        Returns:
            self
        """
        logger.info(f"Fitting stacking ensemble with {len(self.base_models)} base models")

        self.feature_names = X.columns.tolist()

        # Initialize fold models storage
        for model_name in self.base_models:
            self.trained_models[model_name] = []

        # Generate meta-features using K-fold cross-validation
        meta_features = np.zeros((len(X), len(self.base_models)))
        meta_features_df = pd.DataFrame(
            meta_features, columns=list(self.base_models.keys()), index=X.index
        )

        kfold = KFold(n_splits=self.n_folds, shuffle=True, random_state=self.random_seed)

        fold_idx = 0
        for train_idx, val_idx in kfold.split(X):
            fold_idx += 1
            logger.debug(f"Processing fold {fold_idx}/{self.n_folds}")

            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            # Train each base model on this fold
            for model_name, base_model in self.base_models.items():
                try:
                    # Train model on fold
                    fold_model = self._clone_model(base_model)
                    fold_model.fit(X_train, y_train)

                    # Store trained model
                    self.trained_models[model_name].append(fold_model)

                    # Generate meta-feature (prediction on validation set)
                    meta_pred = fold_model.predict(X_val)
                    meta_features_df.loc[X_val.index, model_name] = meta_pred.values

                except Exception as e:
                    logger.warning(f"Error training {model_name} on fold {fold_idx}: {e}")

        # Train meta-learner on meta-features
        try:
            self.meta_learner = Ridge(alpha=1.0)
            self.meta_learner.fit(meta_features_df.fillna(0), y)
            logger.info("Meta-learner fitted")
        except Exception as e:
            logger.error(f"Error training meta-learner: {e}")
            self.meta_learner = None

        self.fitted = True
        logger.info("Stacking ensemble fitted successfully")

        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """
        Make predictions using stacking ensemble.

        Args:
            X: Features to predict

        Returns:
            Predictions
        """
        if not self.fitted or not self.meta_learner:
            raise ValueError("Ensemble not fitted")

        # Generate meta-features (predictions from all base models)
        meta_features = []

        for model_name in self.base_models:
            if model_name not in self.trained_models or not self.trained_models[model_name]:
                logger.warning(f"No trained models for {model_name}")
                meta_features.append(np.zeros(len(X)))
                continue

            # Average predictions from all folds
            fold_predictions = []
            for fold_model in self.trained_models[model_name]:
                try:
                    pred = fold_model.predict(X)
                    fold_predictions.append(pred.values)
                except Exception as e:
                    logger.warning(f"Error predicting with {model_name}: {e}")

            if fold_predictions:
                avg_pred = np.mean(fold_predictions, axis=0)
                meta_features.append(avg_pred)
            else:
                meta_features.append(np.zeros(len(X)))

        # Combine meta-features
        meta_df = pd.DataFrame(
            np.column_stack(meta_features),
            columns=list(self.base_models.keys()),
            index=X.index,
        )

        # Use meta-learner for final prediction
        final_predictions = self.meta_learner.predict(meta_df.fillna(0))

        return pd.Series(final_predictions, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        """
        Get feature importance from base models weighted by meta-learner.

        Returns:
            Dict of feature -> importance score
        """
        if not self.fitted:
            return {}

        total_importance = {}

        # Get meta-learner weights
        if self.meta_learner and hasattr(self.meta_learner, "coef_"):
            meta_weights = np.abs(self.meta_learner.coef_)
            meta_weights = meta_weights / np.sum(meta_weights)
        else:
            meta_weights = np.ones(len(self.base_models)) / len(self.base_models)

        # For each base model
        for idx, (model_name, meta_weight) in enumerate(
            zip(self.base_models.keys(), meta_weights)
        ):
            if model_name not in self.trained_models or not self.trained_models[model_name]:
                continue

            # Average importance from fold models
            fold_importances = []
            for fold_model in self.trained_models[model_name]:
                try:
                    imp = fold_model.get_feature_importance()
                    if imp:
                        fold_importances.append(imp)
                except Exception:
                    pass

            if fold_importances:
                # Average importance across folds
                avg_importance = {}
                for feature in fold_importances[0].keys():
                    values = [imp.get(feature, 0) for imp in fold_importances]
                    avg_importance[feature] = np.mean(values)

                # Weight by meta-learner coefficient
                for feature, imp in avg_importance.items():
                    if feature not in total_importance:
                        total_importance[feature] = 0
                    total_importance[feature] += imp * meta_weight

        # Normalize
        if total_importance:
            total = sum(total_importance.values())
            if total > 0:
                total_importance = {k: v / total for k, v in total_importance.items()}

        return total_importance

    def get_model_weights(self) -> Dict[str, float]:
        """
        Get meta-learner weights for each base model.

        These weights indicate how much each model contributes to final prediction.
        """
        if not self.meta_learner or not hasattr(self.meta_learner, "coef_"):
            weights = {name: 1.0 / len(self.base_models) for name in self.base_models}
        else:
            raw_weights = np.abs(self.meta_learner.coef_)
            total = np.sum(raw_weights)
            # FIX #6: Add zero-division guard - if all weights are 0, use equal weighting
            if total <= 0:
                weights = {name: 1.0 / len(self.base_models) for name in self.base_models}
            else:
                weights = {
                    name: w / total for name, w in zip(self.base_models.keys(), raw_weights)
                }

        return weights

    def get_metrics(self) -> StackingMetrics:
        """Get ensemble performance metrics."""
        return StackingMetrics(
            n_models=len(self.base_models),
            n_folds=self.n_folds,
            train_r2=0.0,  # Can be computed if needed
            val_r2=0.0,
            model_weights=self.get_model_weights(),
        )

    @staticmethod
    def _clone_model(model: Any) -> Any:
        """Clone a model (create new instance with same parameters)."""
        import copy

        try:
            # Try sklearn clone
            from sklearn.base import clone

            return clone(model)
        except (TypeError, AttributeError):  # BUG FIX #30: Catch specific exceptions only
            # Fall back to deep copy if sklearn clone fails
            return copy.deepcopy(model)


class WeightedEnsemble:
    """
    Simpler weighted ensemble (alternative to stacking).

    Uses model performance on validation set to determine weights.
    """

    def __init__(
        self,
        base_models: Dict[str, Any],
        validation_split: float = 0.2,
        random_seed: int = 42,
    ):
        """Initialize weighted ensemble."""
        self.base_models = base_models
        self.validation_split = validation_split
        self.random_seed = random_seed

        self.trained_models: Dict[str, Any] = {}
        self.model_weights: Dict[str, float] = {}
        self.fitted = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "WeightedEnsemble":
        """Fit weighted ensemble."""
        from sklearn.model_selection import train_test_split

        logger.info(f"Fitting weighted ensemble with {len(self.base_models)} models")

        # Split data
        X_train, X_val, y_train, y_val = train_test_split(
            X,
            y,
            test_size=self.validation_split,
            random_state=self.random_seed,
        )

        # Train each model and compute validation score
        scores = {}

        for model_name, base_model in self.base_models.items():
            try:
                # Train
                import copy

                model = copy.deepcopy(base_model)
                model.fit(X_train, y_train)
                self.trained_models[model_name] = model

                # Score on validation set
                pred = model.predict(X_val)
                mse = np.mean((pred.values - y_val.values) ** 2)
                rmse = np.sqrt(mse)
                r2 = 1 - (np.sum((y_val.values - pred.values) ** 2) /
                          np.sum((y_val.values - np.mean(y_val.values)) ** 2))

                scores[model_name] = r2  # Use R2 for weighting
                logger.info(f"{model_name}: R2={r2:.4f}, RMSE={rmse:.4f}")

            except Exception as e:
                logger.warning(f"Error training {model_name}: {e}")
                scores[model_name] = 0.0

        # Convert scores to weights (softmax)
        scores_array = np.array(list(scores.values()))
        # CRITICAL FIX #10: Replace NaN with 0 BEFORE clipping (NaN persists through np.clip)
        scores_array = np.nan_to_num(scores_array, nan=0.0)
        scores_array = np.clip(scores_array, 0, 1)  # Clip to [0, 1]
        weights_raw = np.exp(scores_array * 10)  # Amplify differences
        weights = weights_raw / np.sum(weights_raw)

        self.model_weights = dict(zip(self.base_models.keys(), weights))
        self.fitted = True

        logger.info(f"Ensemble weights: {self.model_weights}")
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Make predictions using weighted ensemble."""
        if not self.fitted:
            raise ValueError("Ensemble not fitted")

        predictions = []

        for model_name, model in self.trained_models.items():
            try:
                pred = model.predict(X)
                weight = self.model_weights.get(model_name, 0)
                # Handle both Series and numpy array returns
                pred_values = pred.values if hasattr(pred, 'values') else pred
                predictions.append(pred_values * weight)
            except Exception as e:
                logger.warning(f"Error predicting with {model_name}: {e}")

        if not predictions:
            raise ValueError("No valid predictions")

        combined = np.sum(predictions, axis=0)
        return pd.Series(combined, index=X.index)

    def get_feature_importance(self) -> Dict[str, float]:
        """Get weighted feature importance."""
        if not self.fitted:
            return {}

        total_importance = {}

        for model_name, model in self.trained_models.items():
            try:
                imp = model.get_feature_importance()
                weight = self.model_weights.get(model_name, 0)

                for feature, score in imp.items():
                    if feature not in total_importance:
                        total_importance[feature] = 0
                    total_importance[feature] += score * weight

            except Exception:
                pass

        return total_importance
