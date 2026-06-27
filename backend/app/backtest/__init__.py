"""Backtesting engine module."""

from .engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
)
from .metrics import PerformanceMetrics, compute_metrics, compute_regime_metrics
from .attribution import AttributionAnalysis
from .strategy_tester import (
    StrategyBacktester,
    StrategyConfig,
    StrategyType,
    StrategyBacktestResult,
    get_strategy_backtester,
)
from .enhanced_validation import (
    ExpandingWindowValidator,
    BootstrapValidator,
    GaussianCopulaStressTester,
    FeatureEngineeringPipeline,
    ComprehensiveBacktestValidator,
)

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "PerformanceMetrics",
    "compute_metrics",
    "compute_regime_metrics",
    "AttributionAnalysis",
    "StrategyBacktester",
    "StrategyConfig",
    "StrategyType",
    "StrategyBacktestResult",
    "get_strategy_backtester",
    # Enhanced Validation - Phase 14
    "ExpandingWindowValidator",
    "BootstrapValidator",
    "GaussianCopulaStressTester",
    "FeatureEngineeringPipeline",
    "ComprehensiveBacktestValidator",
]
