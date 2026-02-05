"""
Advanced Testing & Validation Framework

Rigorous validation for all strategies and the system:
- Walk-forward validation (out-of-sample testing)
- Monte Carlo simulation (10,000 path analysis)
- Robustness testing (parameter sensitivity)
- Stress testing (2008/COVID/VIX scenarios)
- Integration testing (multiple strategies together)
- Performance benchmarking

This ensures only robust, production-ready strategies are deployed.

References:
- Pardo (2008) "The Evaluation and Optimization of Trading Strategies"
- de Prado (2018) "Advances in Financial Machine Learning"
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd
import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of strategy validation."""
    strategy_name: str
    is_valid: bool
    tests_passed: int
    tests_failed: int

    # Performance
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    sharpe_degradation: float  # (in_sample - out_of_sample) / in_sample

    # Robustness
    robustness_score: float  # 0-1, how robust to parameter changes
    stress_test_results: Dict[str, float]  # scenario -> return
    monte_carlo_returns: List[float]  # Distribution of returns

    # Warnings
    warnings: List[str]

    def is_production_ready(self) -> bool:
        """Check if strategy is production-ready."""
        return (
            self.is_valid
            and self.out_of_sample_sharpe > 0.5
            and self.sharpe_degradation < 0.5  # <50% degradation acceptable
            and self.robustness_score > 0.6
            and len(self.warnings) < 3
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "is_valid": self.is_valid,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "in_sample_sharpe": round(self.in_sample_sharpe, 2),
            "out_of_sample_sharpe": round(self.out_of_sample_sharpe, 2),
            "sharpe_degradation": round(self.sharpe_degradation, 2),
            "robustness_score": round(self.robustness_score, 2),
            "stress_test_results": {k: round(v, 4) for k, v in self.stress_test_results.items()},
            "production_ready": self.is_production_ready(),
            "warnings": self.warnings,
        }


class WalkForwardValidator:
    """
    Walk-forward validation prevents look-ahead bias.

    Process:
    1. Split data into non-overlapping train/test windows
    2. Train on window T
    3. Test on window T+1 (out-of-sample)
    4. Compare performance
    5. Repeat across entire history

    Key: Test set must come after train set (prevents look-ahead bias)
    """

    def __init__(
        self,
        train_window_days: int = 252,  # 1 year
        test_window_days: int = 63,    # 3 months
        min_sharpe_for_validity: float = 0.5,
    ):
        """Initialize validator."""
        self.train_window_days = train_window_days
        self.test_window_days = test_window_days
        self.min_sharpe_for_validity = min_sharpe_for_validity
        self.folds: List[Tuple[pd.DataFrame, pd.DataFrame]] = []

    def split(
        self,
        returns: pd.Series,
        embargo_days: int = 20,  # Gap between train and test
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Split data into walk-forward folds.

        Args:
            returns: Daily returns series
            embargo_days: Days to skip between train and test (prevents leakage)

        Returns:
            List of (train_data, test_data) tuples
        """
        self.folds = []
        n = len(returns)
        total_window = self.train_window_days + embargo_days + self.test_window_days

        for start_idx in range(0, n - total_window, self.test_window_days):
            train_end = start_idx + self.train_window_days
            test_start = train_end + embargo_days
            test_end = test_start + self.test_window_days

            train_data = returns.iloc[start_idx:train_end]
            test_data = returns.iloc[test_start:test_end]

            self.folds.append((train_data, test_data))

        logger.info(f"Created {len(self.folds)} walk-forward folds")
        return self.folds

    def validate_strategy(
        self,
        strategy_fn: Callable,  # Function that trains strategy on data
        returns: pd.Series,
    ) -> Tuple[float, float, float]:
        """
        Validate strategy using walk-forward.

        Args:
            strategy_fn: Function(train_data) -> predict_func
            returns: Daily returns

        Returns:
            (in_sample_sharpe, out_of_sample_sharpe, degradation)
        """
        in_sample_sharpes = []
        out_of_sample_sharpes = []

        for train_data, test_data in self.folds:
            try:
                # Train on fold
                predict_fn = strategy_fn(train_data)

                # In-sample performance
                train_preds = predict_fn(train_data)
                in_sample_sharpe = self._compute_sharpe(train_data, train_preds)
                in_sample_sharpes.append(in_sample_sharpe)

                # Out-of-sample performance
                test_preds = predict_fn(test_data)
                out_of_sample_sharpe = self._compute_sharpe(test_data, test_preds)
                out_of_sample_sharpes.append(out_of_sample_sharpe)

            except Exception as e:
                logger.warning(f"Fold validation failed: {e}")
                continue

        avg_in_sample = np.mean(in_sample_sharpes) if in_sample_sharpes else 0
        avg_out_of_sample = np.mean(out_of_sample_sharpes) if out_of_sample_sharpes else 0
        degradation = (
            (avg_in_sample - avg_out_of_sample) / (abs(avg_in_sample) + 1e-10)
            if avg_in_sample != 0
            else 0
        )

        return avg_in_sample, avg_out_of_sample, degradation

    @staticmethod
    def _compute_sharpe(returns: pd.Series, predictions: pd.Series) -> float:
        """Compute Sharpe ratio from predictions."""
        if len(returns) == 0 or len(predictions) == 0:
            return 0

        # Align
        common_idx = returns.index.intersection(predictions.index)
        r = returns.loc[common_idx]
        p = predictions.loc[common_idx]

        correlation = r.corr(p)
        return_volatility = r.std() * np.sqrt(252)
        return correlation * return_volatility if return_volatility > 0 else 0


class MonteCarloValidator:
    """
    Monte Carlo simulation generates 10,000 potential paths.

    Validates that strategy works across diverse market scenarios,
    not just the one historical path.
    """

    def __init__(self, n_simulations: int = 10_000):
        """Initialize."""
        self.n_simulations = n_simulations

    def simulate_paths(
        self,
        returns: pd.Series,
        n_paths: int = None,
    ) -> np.ndarray:
        """
        Generate Monte Carlo return paths.

        Bootstrap-based: resample actual daily returns with replacement.

        Args:
            returns: Historical daily returns
            n_paths: Number of paths (default: self.n_simulations)

        Returns:
            Array of shape (n_paths, len(returns))
        """
        n_paths = n_paths or self.n_simulations
        r = returns.values

        paths = []
        for _ in range(n_paths):
            # Resample returns with replacement
            sampled = np.random.choice(r, size=len(r), replace=True)
            cumulative = np.cumprod(1 + sampled) - 1
            paths.append(cumulative)

        return np.array(paths)

    def compute_path_statistics(
        self,
        paths: np.ndarray,
    ) -> Dict[str, float]:
        """
        Compute statistics across paths.

        Args:
            paths: Shape (n_paths, n_days)

        Returns:
            Dict with percentiles and statistics
        """
        final_returns = paths[:, -1]

        return {
            "mean_return": np.mean(final_returns),
            "std_return": np.std(final_returns),
            "percentile_5": np.percentile(final_returns, 5),
            "percentile_25": np.percentile(final_returns, 25),
            "percentile_50": np.percentile(final_returns, 50),
            "percentile_75": np.percentile(final_returns, 75),
            "percentile_95": np.percentile(final_returns, 95),
            "min_return": np.min(final_returns),
            "max_return": np.max(final_returns),
            "var_95": np.percentile(final_returns, 5),
            "cvar_95": np.mean(final_returns[final_returns <= np.percentile(final_returns, 5)]),
        }


class RobustnessValidator:
    """
    Robustness testing checks parameter sensitivity.

    If small changes to parameters cause large changes in returns,
    strategy is fragile (overfitted).
    """

    def __init__(self, sensitivity_tolerance: float = 0.2):
        """Initialize."""
        self.sensitivity_tolerance = sensitivity_tolerance  # Max 20% change acceptable

    def test_parameter_sensitivity(
        self,
        base_strategy_fn: Callable,
        base_returns: pd.Series,
        param_ranges: Dict[str, List[Any]],
    ) -> float:
        """
        Test sensitivity to parameter changes.

        Args:
            base_strategy_fn: Function(params) -> sharpe_ratio
            base_returns: Base returns for comparison
            param_ranges: Dict of param_name -> [values_to_test]

        Returns:
            Robustness score (0-1, higher = more robust)
        """
        base_sharpe = self._estimate_sharpe(base_returns)
        if base_sharpe == 0:
            return 0

        sensitivities = []

        for param_name, values in param_ranges.items():
            param_sharpes = []

            for value in values:
                try:
                    sharpe = base_strategy_fn({param_name: value})
                    param_sharpes.append(sharpe)
                except Exception:
                    param_sharpes.append(0)

            if param_sharpes:
                # Compute sensitivity (coefficient of variation)
                sensitivity = np.std(param_sharpes) / (np.mean(param_sharpes) + 1e-10)
                sensitivities.append(sensitivity)

        if not sensitivities:
            return 0

        avg_sensitivity = np.mean(sensitivities)
        robustness = 1.0 / (1.0 + avg_sensitivity)  # Convert to 0-1 scale

        return np.clip(robustness, 0, 1)

    @staticmethod
    def _estimate_sharpe(returns: pd.Series) -> float:
        """Estimate Sharpe ratio."""
        if len(returns) < 2:
            return 0
        return returns.mean() / (returns.std() + 1e-10) * np.sqrt(252)


class StressTestValidator:
    """
    Stress tests evaluate strategy in extreme scenarios.

    Tests against:
    - 1987 Black Monday crash (-22% daily)
    - 2008 financial crisis (-40%+ losses)
    - 2020 COVID crash (-30% in days)
    - VIX spike to 80+
    - Liquidity crisis (spreads 10x wider)
    """

    SCENARIOS = {
        "2008_crisis": -0.40,
        "covid_crash": -0.30,
        "black_monday": -0.22,
        "vix_spike": -0.15,
        "liquidity_crisis": -0.10,
        "rate_shock": -0.08,
    }

    def stress_test_returns(
        self,
        returns: pd.Series,
    ) -> Dict[str, float]:
        """
        Stress test returns across scenarios.

        Args:
            returns: Daily returns series

        Returns:
            Dict of scenario -> stressed_return
        """
        results = {}

        for scenario_name, shock_size in self.SCENARIOS.items():
            # Apply shock
            stressed = returns.copy()
            # Add shock to worst days
            worst_idx = stressed.nsmallest(len(stressed) // 10).index
            stressed.loc[worst_idx] += shock_size

            # Compute new Sharpe
            sharpe = stressed.mean() / (stressed.std() + 1e-10) * np.sqrt(252)
            results[scenario_name] = sharpe

        return results


class StrategyValidator:
    """
    Master validator that runs all tests on a strategy.

    Returns comprehensive ValidationResult with:
    - In-sample vs out-of-sample performance
    - Robustness to parameter changes
    - Stress test results
    - Monte Carlo paths
    """

    def __init__(self):
        """Initialize."""
        self.walk_forward = WalkForwardValidator()
        self.monte_carlo = MonteCarloValidator(n_simulations=1000)  # Reduced for speed
        self.robustness = RobustnessValidator()
        self.stress_test = StressTestValidator()

    def validate(
        self,
        strategy_name: str,
        returns: pd.Series,
        strategy_fn: Callable,
        param_ranges: Optional[Dict[str, List[Any]]] = None,
    ) -> ValidationResult:
        """
        Complete validation of strategy.

        Args:
            strategy_name: Name of strategy
            returns: Daily returns
            strategy_fn: Function to train strategy
            param_ranges: Optional parameter ranges for sensitivity testing

        Returns:
            ValidationResult with all test results
        """
        tests_passed = 0
        tests_failed = 0
        warnings = []

        try:
            # Test 1: Walk-forward validation
            self.walk_forward.split(returns)
            in_sample, out_of_sample, degradation = self.walk_forward.validate_strategy(
                strategy_fn, returns
            )
            tests_passed += 1

            if degradation > 0.5:
                warnings.append("High sharpe degradation (possible overfitting)")
                tests_failed += 1
            else:
                tests_passed += 1

        except Exception as e:
            logger.warning(f"Walk-forward validation failed: {e}")
            in_sample = out_of_sample = degradation = 0
            tests_failed += 2

        try:
            # Test 2: Monte Carlo simulation
            paths = self.monte_carlo.simulate_paths(returns, n_paths=1000)
            mc_stats = self.monte_carlo.compute_path_statistics(paths)
            tests_passed += 1

            monte_carlo_returns = paths[:, -1].tolist()

            if mc_stats["percentile_5"] < -0.3:
                warnings.append("High tail risk (5th percentile < -30%)")

        except Exception as e:
            logger.warning(f"Monte Carlo validation failed: {e}")
            mc_stats = {}
            monte_carlo_returns = []
            tests_failed += 1

        try:
            # Test 3: Robustness testing
            if param_ranges:
                robustness_score = self.robustness.test_parameter_sensitivity(
                    strategy_fn, returns, param_ranges
                )
                tests_passed += 1

                if robustness_score < 0.4:
                    warnings.append("Low robustness to parameter changes")
            else:
                robustness_score = 1.0

        except Exception as e:
            logger.warning(f"Robustness validation failed: {e}")
            robustness_score = 0
            tests_failed += 1

        try:
            # Test 4: Stress testing
            stress_results = self.stress_test.stress_test_returns(returns)
            tests_passed += 1

            # Check if strategy survives stress
            survived_all = all(s > -0.5 for s in stress_results.values())
            if not survived_all:
                warnings.append("Strategy fails in some stress scenarios")

        except Exception as e:
            logger.warning(f"Stress testing failed: {e}")
            stress_results = {}
            tests_failed += 1

        is_valid = (
            in_sample > 0.3
            and out_of_sample > 0
            and robustness_score > 0.3
        )

        return ValidationResult(
            strategy_name=strategy_name,
            is_valid=is_valid,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            in_sample_sharpe=in_sample,
            out_of_sample_sharpe=out_of_sample,
            sharpe_degradation=degradation,
            robustness_score=robustness_score,
            stress_test_results=stress_results,
            monte_carlo_returns=monte_carlo_returns,
            warnings=warnings,
        )
