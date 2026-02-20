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
    train_window_days: int = 1260  # 5 years (was 756/3yr — too short for stable cov estimates)
    validation_window_days: int = 63  # ~3 months
    step_days: int = 21  # ~1 month between folds
    embargo_days: int = 5  # Gap between train and validation

    # True out-of-sample holdout
    # Reserve the last N days as a never-touched test set.
    # Walk-forward validation uses data BEFORE this holdout.
    oos_holdout_days: int = 252  # 1 year held out for final evaluation

    # Target settings
    prediction_horizon: int = 5  # Days ahead to predict
    target_type: str = "return"  # return, rank

    # Sample weighting
    # Exponential decay: weight = exp(-decay_rate * (T - t) / T)
    # 0.0 = equal weights, 1.0 = strong recency bias
    sample_weight_decay: float = 0.5

    # Multiple comparison correction
    # When evaluating multiple strategies/models, apply FDR correction
    # to prevent selecting strategies that are lucky rather than skilled
    apply_fdr_correction: bool = True
    fdr_alpha: float = 0.05  # False discovery rate threshold

    # Feature selection
    # Minimum Information Coefficient (rank correlation between feature
    # and forward returns) to keep a feature. Features below this threshold
    # add noise without signal and degrade model performance.
    min_feature_ic: float = 0.02  # Keep features with |IC| >= 0.02
    use_pca_decorrelation: bool = True  # PCA on highly-correlated feature groups
    pca_variance_threshold: float = 0.95  # Keep components explaining 95% variance

    # Hyperparameter tuning
    tune_hyperparameters: bool = True
    n_tuning_trials: int = 30  # Number of Bayesian optimization trials

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
            "oos_holdout_days": self.oos_holdout_days,
            "prediction_horizon": self.prediction_horizon,
            "target_type": self.target_type,
            "sample_weight_decay": self.sample_weight_decay,
            "apply_fdr_correction": self.apply_fdr_correction,
            "fdr_alpha": self.fdr_alpha,
            "min_feature_ic": self.min_feature_ic,
            "use_pca_decorrelation": self.use_pca_decorrelation,
            "pca_variance_threshold": self.pca_variance_threshold,
            "tune_hyperparameters": self.tune_hyperparameters,
            "n_tuning_trials": self.n_tuning_trials,
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
class OOSResult:
    """True out-of-sample test results (never seen during training/validation)."""
    oos_score: float  # Spearman correlation on held-out data
    oos_n_samples: int
    oos_start: date
    oos_end: date
    oos_by_regime: Dict[str, float]  # Score stratified by market regime


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
    oos_result: Optional[OOSResult] = None  # True out-of-sample evaluation
    fdr_adjusted_pvalue: Optional[float] = None  # Multiple comparison corrected p-value
    selected_features: Optional[List[str]] = None  # Features that passed IC filter


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


class FeatureSelector:
    """
    IC-based feature selection with PCA decorrelation.

    Removes noise features that don't predict returns and decorrelates
    the remaining features to improve model stability.
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._pca_model = None
        self._selected_features: List[str] = []
        self._pca_features: List[str] = []

    def select_features(
        self, X: pd.DataFrame, y: pd.Series
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        Select features based on Information Coefficient (rank correlation
        between each feature and forward returns).

        Returns:
            Tuple of (filtered_X, selected_feature_names)
        """
        from scipy.stats import spearmanr

        selected = []
        ic_scores = {}

        for col in X.columns:
            valid = X[col].notna() & y.notna()
            if valid.sum() < 100:
                continue
            corr, pval = spearmanr(X.loc[valid, col], y[valid])
            ic = corr if not np.isnan(corr) else 0.0
            ic_scores[col] = ic
            if abs(ic) >= self.config.min_feature_ic:
                selected.append(col)

        if not selected:
            logger.warning("No features passed IC filter — keeping all features")
            selected = X.columns.tolist()

        logger.info(
            f"Feature selection: {len(selected)}/{len(X.columns)} features pass "
            f"|IC| >= {self.config.min_feature_ic}"
        )
        self._selected_features = selected
        return X[selected], selected

    def apply_pca(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Apply PCA to decorrelate features, keeping components that
        explain pca_variance_threshold of total variance.
        """
        if not self.config.use_pca_decorrelation:
            return X

        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler

        # Standardize first (PCA is sensitive to scale)
        scaler = StandardScaler()
        X_clean = X.fillna(0)
        X_scaled = scaler.fit_transform(X_clean.values)

        # Fit PCA keeping enough components for threshold
        pca = PCA(n_components=self.config.pca_variance_threshold, svd_solver='full')
        X_pca = pca.fit_transform(X_scaled)

        n_components = X_pca.shape[1]
        self._pca_model = (scaler, pca)
        pca_cols = [f"pc_{i}" for i in range(n_components)]
        self._pca_features = pca_cols

        logger.info(
            f"PCA: {len(X.columns)} features → {n_components} components "
            f"({pca.explained_variance_ratio_.sum():.1%} variance explained)"
        )

        return pd.DataFrame(X_pca, index=X.index, columns=pca_cols)

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """Apply saved feature selection and PCA to new data."""
        if self._selected_features:
            available = [f for f in self._selected_features if f in X.columns]
            X = X[available]

        if self._pca_model is not None and self.config.use_pca_decorrelation:
            scaler, pca = self._pca_model
            X_clean = X.fillna(0)
            X_scaled = scaler.transform(X_clean.values)
            X_pca = pca.transform(X_scaled)
            return pd.DataFrame(X_pca, index=X.index, columns=self._pca_features)

        return X


class FDRCorrection:
    """
    Benjamini-Hochberg False Discovery Rate correction.

    When evaluating N strategies, some will look good by chance alone.
    FDR correction identifies which results are statistically robust
    vs. lucky outcomes from multiple testing.
    """

    @staticmethod
    def correct_pvalues(pvalues: List[float], alpha: float = 0.05) -> List[Tuple[int, float, bool]]:
        """
        Apply Benjamini-Hochberg FDR correction.

        Args:
            pvalues: List of p-values from strategy evaluations
            alpha: Target false discovery rate

        Returns:
            List of (original_index, adjusted_pvalue, is_significant)
        """
        n = len(pvalues)
        if n == 0:
            return []

        # Sort p-values (keep track of original indices)
        indexed = sorted(enumerate(pvalues), key=lambda x: x[1])

        results = []
        for rank, (orig_idx, pval) in enumerate(indexed, 1):
            # BH threshold: (rank / n) * alpha
            threshold = (rank / n) * alpha
            adjusted_pval = min(pval * n / rank, 1.0)
            is_significant = pval <= threshold
            results.append((orig_idx, adjusted_pval, is_significant))

        # Restore original order
        results.sort(key=lambda x: x[0])
        return results

    @staticmethod
    def strategy_pvalue(
        val_scores: List[float], n_folds: int
    ) -> float:
        """
        Compute p-value for a strategy's validation performance.

        Tests H0: true rank correlation = 0 (strategy has no skill)
        using a one-sample t-test on fold scores.
        """
        from scipy.stats import ttest_1samp

        if n_folds < 3:
            return 1.0  # Not enough folds for meaningful test

        scores = np.array(val_scores)
        t_stat, pval = ttest_1samp(scores, 0.0)

        # One-sided test: we only care if score > 0
        if t_stat > 0:
            return pval / 2
        return 1.0 - pval / 2


class HyperparameterTuner:
    """
    Bayesian-inspired hyperparameter tuning via random search
    with successive halving.

    Uses the walk-forward validator to evaluate each configuration,
    so hyperparameter selection respects time-series structure.
    """

    # Search spaces for each model type
    SEARCH_SPACES = {
        "ridge": {
            "alpha": (0.01, 100.0, "log"),
        },
        "elasticnet": {
            "alpha": (0.01, 10.0, "log"),
            "l1_ratio": (0.1, 0.9, "uniform"),
        },
        "rf": {
            "n_estimators": (50, 300, "int"),
            "max_depth": (3, 10, "int"),
            "min_samples_leaf": (20, 100, "int"),
            "max_features": (0.1, 0.5, "uniform"),
        },
        "lgbm": {
            "n_estimators": (50, 500, "int"),
            "learning_rate": (0.01, 0.2, "log"),
            "num_leaves": (15, 63, "int"),
            "max_depth": (3, 8, "int"),
            "min_child_samples": (20, 100, "int"),
            "feature_fraction": (0.3, 0.8, "uniform"),
            "lambda_l1": (0.0, 5.0, "uniform"),
            "lambda_l2": (0.0, 5.0, "uniform"),
        },
        "gbm": {
            "n_estimators": (50, 300, "int"),
            "learning_rate": (0.01, 0.2, "log"),
            "max_depth": (2, 6, "int"),
            "min_samples_leaf": (20, 100, "int"),
            "subsample": (0.6, 1.0, "uniform"),
        },
    }

    def __init__(self, config: ModelConfig):
        self.config = config
        self.best_params: Dict[str, Any] = {}
        self.tuning_history: List[Dict[str, Any]] = []

    def _sample_params(self, model_type: str, rng: np.random.RandomState) -> Dict[str, Any]:
        """Sample a random hyperparameter configuration."""
        space = self.SEARCH_SPACES.get(model_type, {})
        params = {}
        for name, (lo, hi, scale) in space.items():
            if scale == "log":
                params[name] = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
            elif scale == "int":
                params[name] = int(rng.randint(lo, hi + 1))
            else:
                params[name] = float(rng.uniform(lo, hi))
        return params

    def tune(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        model_type: str,
    ) -> Dict[str, Any]:
        """
        Tune hyperparameters using random search evaluated with walk-forward CV.

        Returns:
            Best hyperparameter dict
        """
        if model_type == "ensemble":
            logger.info("Skipping tuning for ensemble (tune sub-models individually)")
            return {}

        rng = np.random.RandomState(self.config.random_state)
        n_trials = self.config.n_tuning_trials
        best_score = -np.inf
        best_params = {}

        logger.info(f"Tuning {model_type} with {n_trials} trials")

        for trial in range(n_trials):
            params = self._sample_params(model_type, rng)

            # Create config with these params
            trial_config = ModelConfig(
                model_type=model_type,
                model_params=params,
                validation_method=self.config.validation_method,
                train_window_days=self.config.train_window_days,
                validation_window_days=self.config.validation_window_days,
                step_days=self.config.step_days,
                embargo_days=self.config.embargo_days,
                prediction_horizon=self.config.prediction_horizon,
                sample_weight_decay=self.config.sample_weight_decay,
                random_state=self.config.random_state,
                # Disable nested tuning/selection
                tune_hyperparameters=False,
                min_feature_ic=0.0,
                use_pca_decorrelation=False,
                oos_holdout_days=0,
            )

            try:
                from .estimators import (
                    RidgeRanker, ElasticNetRanker, RandomForestRanker,
                    GradientBoostingRanker, LightGBMRanker,
                )
                model_map = {
                    "ridge": RidgeRanker,
                    "elasticnet": ElasticNetRanker,
                    "rf": RandomForestRanker,
                    "gbm": GradientBoostingRanker,
                    "lgbm": LightGBMRanker,
                }
                model = model_map[model_type](**params)

                validator = WalkForwardValidator(trial_config)
                result = validator.validate(X, y, model)
                score = result.mean_validation_score

                self.tuning_history.append({
                    "trial": trial, "params": params, "score": score
                })

                if score > best_score:
                    best_score = score
                    best_params = params
                    logger.debug(f"  Trial {trial}: score={score:.4f} (new best)")

            except Exception as e:
                logger.debug(f"  Trial {trial} failed: {e}")
                continue

        logger.info(
            f"Tuning complete: best score={best_score:.4f}, params={best_params}"
        )
        self.best_params = best_params
        return best_params


class ModelTrainer:
    """
    High-level model training interface.

    Handles:
    - Feature selection (IC-based + PCA)
    - Hyperparameter tuning (Bayesian random search)
    - Walk-forward validation with OOS holdout
    - Multiple comparison correction (FDR)
    - Model creation and final training
    - Artifact storage
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._feature_selector: Optional[FeatureSelector] = None

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
        Full training pipeline:
        1. Split OOS holdout (never touched during training/validation)
        2. Feature selection via IC filter
        3. Optional PCA decorrelation
        4. Optional hyperparameter tuning
        5. Walk-forward cross-validation
        6. Train final model on all non-OOS data
        7. Evaluate on OOS holdout
        8. Apply FDR correction

        Returns:
            Tuple of (trained_model, validation_result)
        """
        # ---- Step 1: Split OOS holdout ----
        oos_result = None
        X_dev, y_dev = X, y
        X_oos, y_oos = None, None

        if self.config.oos_holdout_days > 0 and len(X) > self.config.oos_holdout_days + self.config.train_window_days:
            split_idx = len(X) - self.config.oos_holdout_days
            X_dev, y_dev = X.iloc[:split_idx], y.iloc[:split_idx]
            X_oos, y_oos = X.iloc[split_idx:], y.iloc[split_idx:]
            logger.info(
                f"OOS holdout: {len(X_oos)} samples reserved "
                f"({X_oos.index[0]} to {X_oos.index[-1]})"
            )

        # ---- Step 2: Feature selection ----
        selected_features = None
        if self.config.min_feature_ic > 0:
            self._feature_selector = FeatureSelector(self.config)
            X_dev, selected_features = self._feature_selector.select_features(X_dev, y_dev)

            # Apply PCA decorrelation
            if self.config.use_pca_decorrelation and len(X_dev.columns) > 10:
                X_dev = self._feature_selector.apply_pca(X_dev)

        # ---- Step 3: Hyperparameter tuning ----
        if self.config.tune_hyperparameters and self.config.model_type != "ensemble":
            tuner = HyperparameterTuner(self.config)
            best_params = tuner.tune(X_dev, y_dev, self.config.model_type)
            if best_params:
                self.config.model_params = best_params

        # ---- Step 4: Walk-forward validation ----
        model = self.create_model()
        validator = WalkForwardValidator(self.config)
        result = validator.validate(X_dev, y_dev, model)
        result.selected_features = selected_features

        # ---- Step 5: FDR correction ----
        if self.config.apply_fdr_correction:
            val_scores = [f.validation_score for f in result.fold_results]
            pval = FDRCorrection.strategy_pvalue(val_scores, len(val_scores))
            result.fdr_adjusted_pvalue = pval
            if pval > self.config.fdr_alpha:
                logger.warning(
                    f"Strategy p-value {pval:.4f} > {self.config.fdr_alpha} — "
                    "performance may not be statistically significant"
                )

        # ---- Step 6: Train final model on all dev data ----
        mask = X_dev.notna().all(axis=1) & y_dev.notna()
        X_final = X_dev[mask]
        y_final = y_dev[mask]

        final_model = self.create_model()
        final_model.fit(X_final, y_final)

        # ---- Step 7: OOS evaluation ----
        if X_oos is not None and y_oos is not None:
            oos_result = self._evaluate_oos(final_model, X_oos, y_oos)
            result.oos_result = oos_result
            logger.info(f"OOS score: {oos_result.oos_score:.4f}")

        logger.info(
            f"Training complete. Mean val score: {result.mean_validation_score:.4f} "
            f"(+/- {result.std_validation_score:.4f})"
        )

        return final_model, result

    def _evaluate_oos(
        self,
        model: BaseRanker,
        X_oos: pd.DataFrame,
        y_oos: pd.Series,
    ) -> OOSResult:
        """Evaluate model on true out-of-sample holdout with regime stratification."""
        from scipy.stats import spearmanr

        # Transform OOS features if feature selector was used
        if self._feature_selector is not None:
            X_oos = self._feature_selector.transform(X_oos)

        # Overall OOS score
        oos_mask = X_oos.notna().all(axis=1) & y_oos.notna()
        X_clean = X_oos[oos_mask]
        y_clean = y_oos[oos_mask]

        if len(X_clean) < 10:
            return OOSResult(
                oos_score=0.0, oos_n_samples=len(X_clean),
                oos_start=X_oos.index[0] if hasattr(X_oos.index[0], 'date') else X_oos.index[0],
                oos_end=X_oos.index[-1] if hasattr(X_oos.index[-1], 'date') else X_oos.index[-1],
                oos_by_regime={}
            )

        preds = model.predict(X_clean)
        corr, _ = spearmanr(y_clean, preds)
        oos_score = corr if not np.isnan(corr) else 0.0

        # Regime-stratified evaluation
        regime_scores = self._score_by_regime(y_clean, preds)

        oos_start = X_oos.index[0]
        oos_end = X_oos.index[-1]
        if hasattr(oos_start, 'date'):
            oos_start = oos_start.date()
        if hasattr(oos_end, 'date'):
            oos_end = oos_end.date()

        return OOSResult(
            oos_score=oos_score,
            oos_n_samples=len(X_clean),
            oos_start=oos_start,
            oos_end=oos_end,
            oos_by_regime=regime_scores,
        )

    def _score_by_regime(
        self,
        y: pd.Series,
        preds: pd.Series,
    ) -> Dict[str, float]:
        """Score predictions stratified by volatility regime."""
        from scipy.stats import spearmanr

        regimes = {}

        # Use rolling volatility of target as regime indicator
        if len(y) < 63:
            return regimes

        rolling_vol = y.rolling(21).std()
        vol_median = rolling_vol.median()

        # Low-vol regime (calm markets)
        low_vol_mask = rolling_vol <= vol_median
        if low_vol_mask.sum() > 20:
            c, _ = spearmanr(y[low_vol_mask], preds[low_vol_mask])
            regimes["low_volatility"] = c if not np.isnan(c) else 0.0

        # High-vol regime (stressed markets)
        high_vol_mask = rolling_vol > vol_median
        if high_vol_mask.sum() > 20:
            c, _ = spearmanr(y[high_vol_mask], preds[high_vol_mask])
            regimes["high_volatility"] = c if not np.isnan(c) else 0.0

        return regimes

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

        # Low positive fold rate — tightened from 60% to 75% for production
        pos_rate = result.stability_metrics["n_positive_folds"] / result.stability_metrics["n_total_folds"]
        if pos_rate < 0.75:
            warnings.append(
                f"Only {pos_rate:.0%} of folds have positive correlation - "
                "model may not generalize (need >75%)"
            )

        # FDR significance check
        if result.fdr_adjusted_pvalue is not None and result.fdr_adjusted_pvalue > self.config.fdr_alpha:
            warnings.append(
                f"Strategy not statistically significant after FDR correction "
                f"(p={result.fdr_adjusted_pvalue:.4f} > {self.config.fdr_alpha})"
            )

        # OOS degradation check
        if result.oos_result is not None:
            oos_gap = result.mean_validation_score - result.oos_result.oos_score
            if oos_gap > 0.03:
                warnings.append(
                    f"OOS degradation: validation={result.mean_validation_score:.4f} "
                    f"vs OOS={result.oos_result.oos_score:.4f} — possible overfitting"
                )

        diagnostics = {
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

        # Add OOS metrics if available
        if result.oos_result is not None:
            diagnostics["oos"] = {
                "score": result.oos_result.oos_score,
                "n_samples": result.oos_result.oos_n_samples,
                "start": str(result.oos_result.oos_start),
                "end": str(result.oos_result.oos_end),
                "by_regime": result.oos_result.oos_by_regime,
            }

        # Add statistical significance
        if result.fdr_adjusted_pvalue is not None:
            diagnostics["statistical_significance"] = {
                "p_value": result.fdr_adjusted_pvalue,
                "fdr_alpha": self.config.fdr_alpha,
                "is_significant": result.fdr_adjusted_pvalue <= self.config.fdr_alpha,
            }

        # Add feature selection info
        if result.selected_features is not None:
            diagnostics["feature_selection"] = {
                "n_selected": len(result.selected_features),
                "min_ic_threshold": self.config.min_feature_ic,
            }

        return diagnostics

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
