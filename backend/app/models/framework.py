"""
Model training and validation framework.

Implements rigorous time-series cross-validation with:
- Walk-forward validation (expanding or rolling window)
- Purging and embargo to prevent leakage
- Multiple performance metrics
- Stability analysis over time
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Iterator
from datetime import date, timedelta
import numpy as np
import pandas as pd
import logging
import json

logger = logging.getLogger(__name__)
from hashlib import sha256

from .estimators import BaseRanker, EnsembleRanker


@dataclass
class ModelConfig:
    """Configuration for model training."""

    model_type: str = "ensemble"  # ridge, elasticnet, rf, gbm, ensemble

    # Model hyperparameters (depend on model_type)
    model_params: Dict[str, Any] = field(default_factory=dict)

    # Validation settings
    validation_method: str = "walk_forward"  # walk_forward, expanding
    train_window_days: int = 756  # 3 years
    validation_window_days: int = 63  # ~3 months
    step_days: int = 21  # ~1 month between folds
    embargo_days: int = 5  # Gap between train and validation

    # Target settings
    prediction_horizon: int = 5  # Days ahead to predict
    target_type: str = "return"  # return, rank

    # Sample weighting
    # Exponential decay: weight = exp(-decay_rate * (T - t) / T)
    # 0.0 = equal weights, 1.0 = strong recency bias
    sample_weight_decay: float = 0.5

    # Random seed
    random_state: int = 42

    def to_dict(self) -> dict:
        return {
            "model_type": self.model_type,
            "model_params": self.model_params,
            "validation_method": self.validation_method,
            "train_window_days": self.train_window_days,
            "validation_window_days": self.validation_window_days,
            "step_days": self.step_days,
            "embargo_days": self.embargo_days,
            "prediction_horizon": self.prediction_horizon,
            "target_type": self.target_type,
            "sample_weight_decay": self.sample_weight_decay,
            "random_state": self.random_state,
        }

    def compute_hash(self) -> str:
        config_str = json.dumps(self.to_dict(), sort_keys=True)
        return sha256(config_str.encode()).hexdigest()[:16]


@dataclass
class CVFold:
    """Single cross-validation fold."""
    fold_id: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    train_indices: np.ndarray
    validation_indices: np.ndarray


class TimeSeriesCV:
    """
    Time-series cross-validation with purging and embargo.

    Key concepts:
    - Purging: Remove samples near the train/validation boundary
      whose labels overlap with validation data (e.g., if prediction_horizon=5,
      the last 5 training samples have forward returns that peek into
      the validation period)
    - Embargo: Add a gap between training and validation periods
      to account for serial correlation in returns
    """

    def __init__(
        self,
        train_window: int,
        validation_window: int,
        step: int,
        embargo: int = 5,
        purge: int = 0,
        expanding: bool = False
    ):
        """
        Args:
            train_window: Training window size in samples
            validation_window: Validation window size in samples
            step: Step size between folds
            embargo: Number of samples to skip between train and validation
            purge: Number of samples to remove from end of training set
                   (should equal prediction_horizon to prevent label leakage)
            expanding: If True, use expanding window; if False, use rolling
        """
        self.train_window = train_window
        self.validation_window = validation_window
        self.step = step
        self.embargo = embargo
        self.purge = purge
        self.expanding = expanding

    def split(
        self,
        X: pd.DataFrame,
        y: Optional[pd.Series] = None
    ) -> Iterator[CVFold]:
        """
        Generate train/validation splits with purging and embargo.

        Yields CVFold objects with indices for each fold.

        Layout for each fold:
        |--- Training (purged) ---|-- Purge --|-- Embargo --|--- Validation ---|
                                  ^           ^
                            labels overlap   serial correlation gap
        """
        n_samples = len(X)
        dates = X.index.tolist()

        fold_id = 0
        current_pos = self.train_window

        while current_pos + self.embargo + self.validation_window <= n_samples:
            # Training indices
            if self.expanding:
                train_start_idx = 0
            else:
                train_start_idx = current_pos - self.train_window

            # Purge: remove last `purge` samples from training to prevent
            # label leakage (their forward return labels extend into the gap)
            train_end_idx = current_pos - self.purge

            # Validation indices (after embargo)
            val_start_idx = current_pos + self.embargo
            val_end_idx = val_start_idx + self.validation_window

            # Ensure we don't exceed data
            if val_end_idx > n_samples:
                break

            # Ensure training set is non-empty after purging
            if train_end_idx <= train_start_idx:
                current_pos += self.step
                continue

            train_indices = np.arange(train_start_idx, train_end_idx)
            val_indices = np.arange(val_start_idx, val_end_idx)

            yield CVFold(
                fold_id=fold_id,
                train_start=dates[train_start_idx],
                train_end=dates[train_end_idx - 1],
                validation_start=dates[val_start_idx],
                validation_end=dates[val_end_idx - 1],
                train_indices=train_indices,
                validation_indices=val_indices
            )

            fold_id += 1
            current_pos += self.step

    def get_n_splits(self, X: pd.DataFrame) -> int:
        """Count number of splits."""
        return sum(1 for _ in self.split(X))


@dataclass
class FoldResult:
    """Results from a single CV fold."""
    fold_id: int
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    train_score: float
    validation_score: float
    predictions: pd.Series
    feature_importance: Dict[str, float]


@dataclass
class ValidationResult:
    """Complete validation results."""
    config: ModelConfig
    fold_results: List[FoldResult]
    mean_train_score: float
    mean_validation_score: float
    std_validation_score: float
    feature_importance: Dict[str, float]
    stability_metrics: Dict[str, float]


class WalkForwardValidator:
    """
    Walk-forward validation for time-series models.

    This is the gold standard for backtesting ML models in finance:
    1. Train on historical data
    2. Predict on future data
    3. Move forward in time
    4. Repeat
    """

    def __init__(self, config: ModelConfig):
        self.config = config

    def validate(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model: BaseRanker
    ) -> ValidationResult:
        """
        Run walk-forward validation.

        Args:
            X: Feature DataFrame
            y: Target Series
            model: Model to validate

        Returns:
            ValidationResult with all fold metrics
        """
        # Create CV splitter with purging to prevent label leakage
        # Purge removes training samples whose forward-return labels
        # overlap with the validation period
        cv = TimeSeriesCV(
            train_window=self.config.train_window_days,
            validation_window=self.config.validation_window_days,
            step=self.config.step_days,
            embargo=self.config.embargo_days,
            purge=self.config.prediction_horizon,
            expanding=(self.config.validation_method == "expanding")
        )

        fold_results = []

        for fold in cv.split(X):
            logger.debug(
                f"Fold {fold.fold_id}: train {fold.train_start} to {fold.train_end}, "
                f"val {fold.validation_start} to {fold.validation_end}"
            )

            # Get data for this fold
            X_train = X.iloc[fold.train_indices]
            y_train = y.iloc[fold.train_indices]
            X_val = X.iloc[fold.validation_indices]
            y_val = y.iloc[fold.validation_indices]

            # Handle NaN
            train_mask = X_train.notna().all(axis=1) & y_train.notna()
            val_mask = X_val.notna().all(axis=1) & y_val.notna()

            X_train = X_train[train_mask]
            y_train = y_train[train_mask]
            X_val = X_val[val_mask]
            y_val = y_val[val_mask]

            if len(X_train) < 100 or len(X_val) < 10:
                logger.warning(f"Skipping fold {fold.fold_id}: insufficient data")
                continue

            # Apply temporal decay sample weighting if configured
            # More recent samples get higher weight so the model adapts to
            # regime changes faster
            sample_weight = None
            if self.config.sample_weight_decay > 0:
                n = len(X_train)
                # Exponential decay: weight increases towards the end of training
                t = np.arange(n, dtype=float)
                sample_weight = np.exp(self.config.sample_weight_decay * (t - n) / n)
                # Normalize so weights sum to n (preserves effective sample size interpretation)
                sample_weight = sample_weight * n / sample_weight.sum()

            # Train (pass sample_weight if model supports it)
            if sample_weight is not None and hasattr(model, 'fit'):
                try:
                    model.fit(X_train, y_train, sample_weight=sample_weight)
                except TypeError:
                    # Model doesn't accept sample_weight — train without it
                    model.fit(X_train, y_train)
            else:
                model.fit(X_train, y_train)

            # Predict
            train_pred = model.predict(X_train)
            val_pred = model.predict(X_val)

            # Score using rank correlation (Spearman)
            train_score = self._rank_correlation(y_train, train_pred)
            val_score = self._rank_correlation(y_val, val_pred)

            fold_results.append(FoldResult(
                fold_id=fold.fold_id,
                train_start=fold.train_start,
                train_end=fold.train_end,
                validation_start=fold.validation_start,
                validation_end=fold.validation_end,
                train_score=train_score,
                validation_score=val_score,
                predictions=val_pred,
                feature_importance=model.get_feature_importance()
            ))

        if not fold_results:
            raise ValueError("No valid folds - check data quality")

        # Aggregate results
        train_scores = [f.train_score for f in fold_results]
        val_scores = [f.validation_score for f in fold_results]

        # Average feature importance
        all_imp = {}
        for fold in fold_results:
            for feat, imp in fold.feature_importance.items():
                if feat not in all_imp:
                    all_imp[feat] = []
                all_imp[feat].append(abs(imp))
        avg_importance = {k: np.mean(v) for k, v in all_imp.items()}

        # Stability metrics
        stability = self._compute_stability(fold_results)

        return ValidationResult(
            config=self.config,
            fold_results=fold_results,
            mean_train_score=np.mean(train_scores),
            mean_validation_score=np.mean(val_scores),
            std_validation_score=np.std(val_scores),
            feature_importance=avg_importance,
            stability_metrics=stability
        )

    def _rank_correlation(self, y_true: pd.Series, y_pred: pd.Series) -> float:
        """Compute Spearman rank correlation."""
        from scipy.stats import spearmanr
        corr, _ = spearmanr(y_true, y_pred)
        return corr if not np.isnan(corr) else 0.0

    def _compute_stability(self, fold_results: List[FoldResult]) -> Dict[str, float]:
        """Compute stability metrics across folds."""
        val_scores = [f.validation_score for f in fold_results]

        # Score stability
        score_stability = 1.0 - (np.std(val_scores) / (np.mean(np.abs(val_scores)) + 1e-6))

        # Feature importance stability (how consistent are top features)
        top_k = 10
        top_features_per_fold = []
        for fold in fold_results:
            sorted_imp = sorted(
                fold.feature_importance.items(),
                key=lambda x: abs(x[1]),
                reverse=True
            )
            top_features_per_fold.append(set([f[0] for f in sorted_imp[:top_k]]))

        # Jaccard similarity between consecutive folds
        jaccard_scores = []
        for i in range(1, len(top_features_per_fold)):
            intersection = len(top_features_per_fold[i] & top_features_per_fold[i-1])
            union = len(top_features_per_fold[i] | top_features_per_fold[i-1])
            if union > 0:
                jaccard_scores.append(intersection / union)

        feature_stability = np.mean(jaccard_scores) if jaccard_scores else 0.0

        return {
            "score_stability": score_stability,
            "feature_stability": feature_stability,
            "n_positive_folds": sum(1 for s in val_scores if s > 0),
            "n_total_folds": len(val_scores),
        }


class ModelTrainer:
    """
    High-level model training interface.

    Handles:
    - Model creation based on config
    - Validation
    - Final model training
    - Artifact storage
    """

    def __init__(self, config: ModelConfig):
        self.config = config

    def create_model(self) -> BaseRanker:
        """Create model based on config."""
        from .estimators import (
            RidgeRanker,
            ElasticNetRanker,
            RandomForestRanker,
            GradientBoostingRanker,
            LightGBMRanker,
            EnsembleRanker
        )

        model_map = {
            "ridge": RidgeRanker,
            "elasticnet": ElasticNetRanker,
            "rf": RandomForestRanker,
            "gbm": GradientBoostingRanker,
            "lgbm": LightGBMRanker,
            "ensemble": EnsembleRanker,
        }

        model_class = model_map.get(self.config.model_type)
        if model_class is None:
            raise ValueError(f"Unknown model type: {self.config.model_type}")

        return model_class(**self.config.model_params)

    def train_and_validate(
        self,
        X: pd.DataFrame,
        y: pd.Series
    ) -> Tuple[BaseRanker, ValidationResult]:
        """
        Train model with validation.

        Returns:
            Tuple of (trained_model, validation_result)
        """
        model = self.create_model()
        validator = WalkForwardValidator(self.config)

        # Run validation
        result = validator.validate(X, y, model)

        # Train final model on all data
        mask = X.notna().all(axis=1) & y.notna()
        X_final = X[mask]
        y_final = y[mask]

        final_model = self.create_model()
        final_model.fit(X_final, y_final)

        logger.info(
            f"Training complete. Mean val score: {result.mean_validation_score:.4f} "
            f"(+/- {result.std_validation_score:.4f})"
        )

        return final_model, result

    def generate_diagnostics(
        self,
        result: ValidationResult
    ) -> Dict[str, Any]:
        """Generate diagnostic report from validation."""
        # Sort features by importance
        sorted_imp = sorted(
            result.feature_importance.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )

        # Identify concerning patterns
        warnings = []

        # Large train/val gap suggests overfitting
        overfit_gap = result.mean_train_score - result.mean_validation_score
        if overfit_gap > 0.1:
            warnings.append(
                f"Potential overfitting: train score {result.mean_train_score:.3f} "
                f"much higher than validation {result.mean_validation_score:.3f}"
            )

        # High variance suggests instability
        if result.std_validation_score > 0.05:
            warnings.append(
                f"High validation variance ({result.std_validation_score:.3f}) "
                "suggests model instability across time"
            )

        # Low positive fold rate
        pos_rate = result.stability_metrics["n_positive_folds"] / result.stability_metrics["n_total_folds"]
        if pos_rate < 0.6:
            warnings.append(
                f"Only {pos_rate:.0%} of folds have positive correlation - "
                "model may not generalize"
            )

        return {
            "summary": {
                "mean_train_score": result.mean_train_score,
                "mean_validation_score": result.mean_validation_score,
                "std_validation_score": result.std_validation_score,
                "n_folds": len(result.fold_results),
            },
            "stability": result.stability_metrics,
            "top_features": sorted_imp[:20],
            "warnings": warnings,
            "interpretation": self._interpret_results(result),
        }

    def _interpret_results(self, result: ValidationResult) -> str:
        """Generate human-readable interpretation."""
        score = result.mean_validation_score

        if score < 0:
            quality = "negative (model predictions inversely correlated with returns)"
        elif score < 0.02:
            quality = "weak (barely above random)"
        elif score < 0.05:
            quality = "modest (typical for equity factors)"
        elif score < 0.10:
            quality = "good (strong signal)"
        else:
            quality = "very strong (verify this isn't overfitting or leakage)"

        interpretation = f"""
Model Performance Analysis:
- Rank correlation: {score:.4f} ({quality})
- Consistency: {result.stability_metrics['n_positive_folds']}/{result.stability_metrics['n_total_folds']} folds positive
- Feature stability: {result.stability_metrics['feature_stability']:.2f} (1.0 = perfectly stable)

Note: In equity markets, even small positive correlations (0.02-0.05) can be
economically significant after portfolio construction and risk management.
Very high correlations (>0.10) should be scrutinized for data issues.
"""
        return interpretation.strip()
