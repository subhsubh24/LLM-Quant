"""Backtesting engine module."""

from .engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
)
from .metrics import PerformanceMetrics, compute_metrics, compute_regime_metrics
from .attribution import AttributionAnalysis
# NOTE: strategy_tester.py (yfinance-based equity/crypto technical-indicator backtester)
# was removed 2026-07-01 as stock-era dead residue (ROADMAP A1) — it was imported nowhere
# in the prediction-markets app. PM backtesting lives in prediction_markets/walk_forward.py.
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
    # Enhanced Validation - Phase 14
    "ExpandingWindowValidator",
    "BootstrapValidator",
    "GaussianCopulaStressTester",
    "FeatureEngineeringPipeline",
    "ComprehensiveBacktestValidator",
]
