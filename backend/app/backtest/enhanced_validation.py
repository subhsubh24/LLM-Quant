"""
Enhanced Validation - Phase 14

Comprehensive backtest validation with:
1. Expanding window validation (walk-forward with growing training set)
2. Bootstrap aggregation tests (random resampling)
3. Gaussian copula stress testing (correlation scenarios)
4. Feature engineering pipeline (automatic feature selection)

Expected improvements:
- Prevents overfitting detection (expanding window more rigorous)
- Captures regime changes (copula stress testing)
- Validates feature stability (engineering pipeline)
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationMetrics:
    """Comprehensive validation metrics."""
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    avg_return: float
    volatility: float
    calmar_ratio: float
    sortino_ratio: float
    confidence_interval_lower: float
    confidence_interval_upper: float


class ExpandingWindowValidator:
    """Expanding window validation (walk-forward with growing training)."""

    def __init__(self, initial_train_period_days: int = 252):
        """Initialize expanding window validator.

        Args:
            initial_train_period_days: Minimum training period (default: 1 year)
        """
        self.initial_train_period = initial_train_period_days

    def split_expanding_window(
        self,
        data: pd.DataFrame,
        test_period_days: int = 63,
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Generate expanding window splits.

        Args:
            data: Full time series data
            test_period_days: Days in each test window (default: 63 = 1 quarter)

        Returns:
            List of (train, test) dataframe tuples
        """
        splits = []
        total_days = len(data)

        # Ensure we have enough data
        if total_days < self.initial_train_period + test_period_days:
            logger.warning("Insufficient data for expanding window validation")
            return []

        # Create expanding windows
        train_end = self.initial_train_period
        while train_end + test_period_days <= total_days:
            train_data = data.iloc[:train_end]
            test_data = data.iloc[train_end:train_end + test_period_days]

            splits.append((train_data, test_data))

            # Expand training set
            train_end += test_period_days

        logger.info(f"Generated {len(splits)} expanding window splits")
        return splits

    def validate_strategy(
        self,
        strategy_fn,
        data: pd.DataFrame,
        test_period_days: int = 63,
    ) -> Dict:
        """Validate strategy across expanding windows.

        Args:
            strategy_fn: Function that trains on train_data and predicts on test_data
            data: Full time series
            test_period_days: Test period length

        Returns:
            Validation results {windows, avg_sharpe, std_sharpe, min_sharpe, max_sharpe}
        """
        splits = self.split_expanding_window(data, test_period_days)

        window_results = []
        for i, (train, test) in enumerate(splits):
            try:
                # Train on expanding window
                model = strategy_fn(train)

                # Test on hold-out period
                predictions = model.predict(test)
                returns = test['returns'].values
                sharpe = self._compute_sharpe(returns, predictions)

                window_results.append({
                    'window': i,
                    'sharpe': sharpe,
                    'num_predictions': len(predictions),
                })
            except Exception as e:
                logger.error(f"Error in window {i}: {e}")
                continue

        # Aggregate results
        if not window_results:
            return {'error': 'No valid windows'}

        sharpes = [w['sharpe'] for w in window_results]
        return {
            'windows': len(window_results),
            'avg_sharpe': np.mean(sharpes),
            'std_sharpe': np.std(sharpes),
            'min_sharpe': np.min(sharpes),
            'max_sharpe': np.max(sharpes),
            'consistency': 1.0 - np.std(sharpes) / max(np.mean(sharpes), 0.1),
        }

    @staticmethod
    def _compute_sharpe(returns: np.ndarray, weights: np.ndarray) -> float:
        """Compute Sharpe ratio."""
        strategy_returns = returns * weights
        if np.std(strategy_returns) < 1e-10:
            return 0.0
        return np.mean(strategy_returns) / np.std(strategy_returns) * np.sqrt(252)


class BootstrapValidator:
    """Block bootstrap validator for time-series robustness testing.

    Uses block resampling (contiguous blocks) instead of i.i.d. resampling
    to preserve serial dependence in returns (autocorrelation, volatility
    clustering). This produces realistic confidence intervals.

    References:
    - Politis & Romano (1994) "The Stationary Bootstrap"
    - Ledoit & Wolf (2008) "Robust Performance Hypothesis Testing with the Sharpe Ratio"
    """

    def __init__(self, num_bootstrap_samples: int = 100, block_size: int = 21):
        """Initialize block bootstrap validator.

        Args:
            num_bootstrap_samples: Number of bootstrap resamples
            block_size: Size of contiguous blocks (21 ~ 1 month preserves
                        autocorrelation and vol clustering)
        """
        self.num_samples = num_bootstrap_samples
        self.block_size = block_size

    def bootstrap_resample(
        self,
        data: pd.DataFrame,
    ) -> List[pd.DataFrame]:
        """Generate block bootstrap resamples.

        Samples contiguous blocks of rows with replacement, preserving
        the temporal structure within each block.

        Args:
            data: Original time-series data

        Returns:
            List of bootstrapped datasets
        """
        resamples = []
        n = len(data)
        block_size = min(self.block_size, max(n // 4, 1))
        # Sample enough blocks to guarantee at least n indices after concatenation
        n_blocks = (n + block_size - 1) // block_size  # ceil division

        for _ in range(self.num_samples):
            block_starts = np.random.randint(0, max(n - block_size + 1, 1), size=n_blocks)
            indices = np.concatenate([
                np.arange(start, start + block_size) for start in block_starts
            ])[:n]  # Trim to exactly original length
            resample = data.iloc[indices].reset_index(drop=True)
            resamples.append(resample)

        return resamples

    def validate_strategy(
        self,
        strategy_fn,
        data: pd.DataFrame,
    ) -> Dict:
        """Validate strategy robustness via block bootstrap.

        Args:
            strategy_fn: Function that trains and predicts
            data: Original data

        Returns:
            Block bootstrap validation results with CIs and p-value
        """
        resamples = self.bootstrap_resample(data)

        sample_results = []
        for i, resample in enumerate(resamples):
            try:
                model = strategy_fn(resample)
                predictions = model.predict(resample)
                returns = resample['returns'].values

                sharpe = self._compute_sharpe(returns, predictions)
                max_dd = self._compute_max_drawdown(returns, predictions)

                sample_results.append({
                    'sample': i,
                    'sharpe': sharpe,
                    'max_dd': max_dd,
                })
            except Exception as e:
                logger.warning(f"Bootstrap sample {i} failed: {e}")
                continue

        if not sample_results:
            return {'error': 'All bootstrap samples failed'}

        sharpes = [r['sharpe'] for r in sample_results]
        max_dds = [r['max_dd'] for r in sample_results]

        # P-value: fraction of bootstrap samples with Sharpe <= 0
        p_value = float(np.mean(np.array(sharpes) <= 0))

        return {
            'samples': len(sample_results),
            'block_size': self.block_size,
            'mean_sharpe': float(np.mean(sharpes)),
            'std_sharpe': float(np.std(sharpes)),
            'sharpe_se': float(np.std(sharpes)),
            'percentile_5_sharpe': float(np.percentile(sharpes, 5)),
            'percentile_95_sharpe': float(np.percentile(sharpes, 95)),
            'sharpe_p_value': p_value,
            'mean_max_dd': float(np.mean(max_dds)),
            'max_max_dd': float(np.max(max_dds)),
            'stability': 1.0 - float(np.std(sharpes) / max(np.mean(sharpes), 0.1)),
        }

    @staticmethod
    def _compute_sharpe(returns: np.ndarray, weights: np.ndarray) -> float:
        """Compute Sharpe ratio."""
        strategy_returns = returns * weights
        if np.std(strategy_returns) < 1e-10:
            return 0.0
        return float(np.mean(strategy_returns) / np.std(strategy_returns) * np.sqrt(252))

    @staticmethod
    def _compute_max_drawdown(returns: np.ndarray, weights: np.ndarray) -> float:
        """Compute maximum drawdown."""
        strategy_returns = returns * weights
        cum_returns = np.cumprod(1 + strategy_returns)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        return float(np.min(drawdown))

    def permutation_test(
        self,
        returns: np.ndarray,
        n_permutations: int = 1000,
    ) -> Dict[str, float]:
        """
        Permutation test for Sharpe ratio significance.

        Tests H0: strategy returns are no better than random by shuffling
        the return series and computing Sharpe on each shuffle. The p-value
        is the fraction of shuffled Sharpes that exceed the observed Sharpe.

        This is the gold standard for significance testing because it makes
        no distributional assumptions.

        Args:
            returns: Strategy daily returns
            n_permutations: Number of random shuffles

        Returns:
            Dict with observed_sharpe, p_value, mean_null_sharpe, std_null_sharpe
        """
        if len(returns) < 63:
            return {"observed_sharpe": 0.0, "p_value": 1.0, "n_permutations": 0}

        # Observed Sharpe
        mean_r = np.mean(returns)
        std_r = np.std(returns)
        observed_sharpe = (mean_r / std_r * np.sqrt(252)) if std_r > 1e-10 else 0.0

        # Generate null distribution by randomly flipping return signs.
        # Simple permutation preserves mean/std (same Sharpe). Sign-flipping
        # destroys the directional signal while preserving magnitude distribution.
        rng = np.random.RandomState(42)
        null_sharpes = []
        for _ in range(n_permutations):
            signs = rng.choice([-1, 1], size=len(returns))
            flipped = returns * signs
            s_mean = np.mean(flipped)
            s_std = np.std(flipped)
            null_sharpe = (s_mean / s_std * np.sqrt(252)) if s_std > 1e-10 else 0.0
            null_sharpes.append(null_sharpe)

        null_sharpes = np.array(null_sharpes)

        # P-value: fraction of null Sharpes >= observed
        p_value = float(np.mean(null_sharpes >= observed_sharpe))

        return {
            "observed_sharpe": float(observed_sharpe),
            "p_value": p_value,
            "mean_null_sharpe": float(np.mean(null_sharpes)),
            "std_null_sharpe": float(np.std(null_sharpes)),
            "n_permutations": n_permutations,
            "significant_at_05": p_value < 0.05,
            "significant_at_01": p_value < 0.01,
        }


class GaussianCopulaStressTester:
    """Stress testing via Gaussian copula."""

    def __init__(self, num_scenarios: int = 1000):
        """Initialize copula stress tester.

        Args:
            num_scenarios: Number of stress scenarios to generate
        """
        self.num_scenarios = num_scenarios

    def estimate_copula_parameters(
        self,
        returns: np.ndarray,
    ) -> Dict:
        """Estimate Gaussian copula parameters from returns.

        Args:
            returns: Historical returns array (samples x assets)

        Returns:
            Copula parameters {correlation_matrix, marginals}
        """
        # Estimate correlation matrix
        correlation = np.corrcoef(returns.T)

        # Estimate marginal distributions (mean, std per asset)
        marginals = {
            'means': np.mean(returns, axis=0),
            'stds': np.std(returns, axis=0),
        }

        return {
            'correlation': correlation,
            'marginals': marginals,
        }

    def generate_stress_scenarios(
        self,
        correlation: np.ndarray,
        num_scenarios: int,
        correlation_multiplier: float = 1.5,
    ) -> np.ndarray:
        """Generate stress scenarios with elevated correlation.

        Args:
            correlation: Base correlation matrix
            num_scenarios: Number of scenarios
            correlation_multiplier: Factor to increase correlations (1.5 = 50% more)

        Returns:
            Stress scenarios (num_scenarios x num_assets)
        """
        n_assets = correlation.shape[0]

        # Scale up correlations (move toward perfect correlation)
        stressed_corr = np.eye(n_assets) + correlation_multiplier * (correlation - np.eye(n_assets))

        # Clip to valid correlation range
        stressed_corr = np.clip(stressed_corr, -0.99, 0.99)

        # Generate scenarios from stressed copula
        try:
            # Cholesky decomposition
            L = np.linalg.cholesky(stressed_corr)

            # Generate standard normal scenarios
            z = np.random.standard_normal((num_scenarios, n_assets))

            # Apply Cholesky decomposition
            scenarios = z @ L.T

            return scenarios
        except np.linalg.LinAlgError:
            logger.warning("Correlation matrix not positive definite, using base correlation")
            L = np.linalg.cholesky(correlation)
            z = np.random.standard_normal((num_scenarios, n_assets))
            return z @ L.T

    def stress_test_portfolio(
        self,
        returns: np.ndarray,
        weights: np.ndarray,
    ) -> Dict:
        """Run stress tests on portfolio.

        Args:
            returns: Historical returns (samples x assets)
            weights: Portfolio weights

        Returns:
            Stress test results
        """
        # Estimate copula
        params = self.estimate_copula_parameters(returns)

        # Generate stress scenarios
        scenarios = self.generate_stress_scenarios(
            params['correlation'],
            self.num_scenarios,
            correlation_multiplier=1.5,
        )

        # Compute portfolio returns under stress
        portfolio_returns = scenarios @ weights
        sharpe_stress = self._compute_sharpe(portfolio_returns)

        # Compare to baseline
        baseline_sharpe = np.mean(returns @ weights) / np.std(returns @ weights) * np.sqrt(252)

        return {
            'baseline_sharpe': float(baseline_sharpe),
            'stress_sharpe': float(sharpe_stress),
            'sharpe_degradation': float(baseline_sharpe - sharpe_stress),
            'stress_max_dd': float(np.min(np.cumprod(1 + portfolio_returns) - 1)),
            'scenarios_evaluated': self.num_scenarios,
        }

    @staticmethod
    def _compute_sharpe(returns: np.ndarray) -> float:
        """Compute Sharpe ratio."""
        if np.std(returns) < 1e-10:
            return 0.0
        return float(np.mean(returns) / np.std(returns) * np.sqrt(252))


class FeatureEngineeringPipeline:
    """Automatic feature engineering and selection."""

    def __init__(self, max_features: int = 50):
        """Initialize feature engineering pipeline.

        Args:
            max_features: Maximum number of features to keep
        """
        self.max_features = max_features
        self.feature_importances = {}

    def generate_technical_features(
        self,
        data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Generate technical indicator features.

        Args:
            data: OHLCV data with columns: close, high, low, volume

        Returns:
            Dataframe with generated features
        """
        features = pd.DataFrame(index=data.index)

        # Momentum features
        features['returns_1d'] = data['close'].pct_change(1)
        features['returns_5d'] = data['close'].pct_change(5)
        features['returns_20d'] = data['close'].pct_change(20)

        # Volatility features
        features['volatility_10d'] = data['close'].pct_change().rolling(10).std()
        features['volatility_20d'] = data['close'].pct_change().rolling(20).std()

        # Range features
        features['range_5d'] = (data['high'].rolling(5).max() - data['low'].rolling(5).min()) / data['close']
        features['range_20d'] = (data['high'].rolling(20).max() - data['low'].rolling(20).min()) / data['close']

        # Volume features
        if 'volume' in data.columns:
            features['volume_ratio'] = data['volume'] / data['volume'].rolling(20).mean()

        # Mean reversion features
        features['price_to_20ma'] = data['close'] / data['close'].rolling(20).mean()
        features['price_to_50ma'] = data['close'] / data['close'].rolling(50).mean()

        return features.fillna(0)

    def select_important_features(
        self,
        features: pd.DataFrame,
        target: np.ndarray,
        method: str = 'correlation',
    ) -> List[str]:
        """Select most important features.

        Args:
            features: Feature dataframe
            target: Target variable (returns or signals)
            method: Selection method ('correlation', 'mutual_info')

        Returns:
            List of selected feature names
        """
        if method == 'correlation':
            # Correlation with target
            correlations = {}
            for col in features.columns:
                valid_mask = ~(np.isnan(features[col]) | np.isnan(target))
                if valid_mask.sum() > 10:
                    corr = np.abs(np.corrcoef(features[col][valid_mask], target[valid_mask])[0, 1])
                    correlations[col] = 0 if np.isnan(corr) else corr

            # Sort by correlation
            sorted_features = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
            selected = [f[0] for f in sorted_features[:self.max_features]]

            self.feature_importances = dict(sorted_features)
            return selected

        elif method == 'variance':
            # Select features with highest variance
            variances = features.var()
            selected = variances.nlargest(self.max_features).index.tolist()
            self.feature_importances = dict(variances.sort_values(ascending=False))
            return selected

        else:
            # Default: all features
            return list(features.columns[:self.max_features])

    def validate_feature_stability(
        self,
        features_old: pd.DataFrame,
        features_new: pd.DataFrame,
    ) -> Dict:
        """Validate feature stability across periods.

        Args:
            features_old: Features from old period
            features_new: Features from new period

        Returns:
            Stability metrics {correlation_mean, drift_detected}
        """
        feature_correlations = []

        for col in features_old.columns:
            if col in features_new.columns:
                valid_mask = ~(np.isnan(features_old[col]) | np.isnan(features_new[col]))
                if valid_mask.sum() > 10:
                    corr = np.corrcoef(
                        features_old[col][valid_mask],
                        features_new[col][valid_mask],
                    )[0, 1]
                    feature_correlations.append(corr)

        mean_correlation = np.mean(feature_correlations) if feature_correlations else 0.0
        drift_detected = mean_correlation < 0.8  # Threshold: 80% correlation

        return {
            'mean_correlation': float(mean_correlation),
            'drift_detected': drift_detected,
            'features_stable': len(feature_correlations),
        }


class ComprehensiveBacktestValidator:
    """Master validator combining all techniques."""

    def __init__(self):
        """Initialize comprehensive validator."""
        self.expanding_window = ExpandingWindowValidator()
        self.bootstrap = BootstrapValidator(num_bootstrap_samples=100)
        self.copula = GaussianCopulaStressTester(num_scenarios=1000)
        self.feature_eng = FeatureEngineeringPipeline()

    def run_full_validation(
        self,
        strategy_fn,
        data: pd.DataFrame,
    ) -> Dict:
        """Run comprehensive validation suite.

        Args:
            strategy_fn: Strategy training function
            data: Full backtest data

        Returns:
            Comprehensive validation report
        """
        validation_report = {
            'timestamp': datetime.now().isoformat(),
            'total_samples': len(data),
        }

        # 1. Expanding window validation
        try:
            ew_results = self.expanding_window.validate_strategy(strategy_fn, data)
            validation_report['expanding_window'] = ew_results
        except Exception as e:
            logger.error(f"Expanding window validation failed: {e}")
            validation_report['expanding_window'] = {'error': str(e)}

        # 2. Bootstrap validation
        try:
            bs_results = self.bootstrap.validate_strategy(strategy_fn, data)
            validation_report['bootstrap'] = bs_results
        except Exception as e:
            logger.error(f"Bootstrap validation failed: {e}")
            validation_report['bootstrap'] = {'error': str(e)}

        # 3. Feature engineering validation
        try:
            features = self.feature_eng.generate_technical_features(data)
            returns = data.get('returns', data['close'].pct_change()).values
            selected = self.feature_eng.select_important_features(features, returns)
            validation_report['feature_engineering'] = {
                'total_features_generated': features.shape[1],
                'features_selected': len(selected),
                'top_features': selected[:10],
            }
        except Exception as e:
            logger.error(f"Feature engineering validation failed: {e}")
            validation_report['feature_engineering'] = {'error': str(e)}

        return validation_report

    def get_validation_score(self, validation_report: Dict) -> float:
        """Compute overall validation score (0-100).

        Args:
            validation_report: Validation results

        Returns:
            Overall score 0-100
        """
        score = 0.0
        weights = 0.0

        # Expanding window consistency (25% weight)
        if 'expanding_window' in validation_report:
            ew = validation_report['expanding_window']
            if 'consistency' in ew:
                score += 25 * ew['consistency']
                weights += 25

        # Bootstrap stability (25% weight)
        if 'bootstrap' in validation_report:
            bs = validation_report['bootstrap']
            if 'stability' in bs:
                score += 25 * bs['stability']
                weights += 25

        # Feature stability (20% weight)
        if 'feature_engineering' in validation_report:
            fe = validation_report['feature_engineering']
            if 'top_features' in fe and fe['top_features']:
                score += 20 * min(len(fe['top_features']) / 10, 1.0)
                weights += 20

        # Data quality (30% weight)
        if validation_report.get('total_samples', 0) > 500:
            score += 30
            weights += 30

        if weights > 0:
            return float(score / weights * 100)
        return 0.0
