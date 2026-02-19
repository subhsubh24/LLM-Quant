"""Feature engineering module."""

from .pipeline import FeaturePipeline, FeatureConfig
from .core import (
    compute_returns,
    compute_momentum,
    compute_volatility,
    compute_volume_features,
    compute_risk_features,
    compute_enhanced_technical_features,
)
from ..data.alternative import (
    AlternativeFeatureEngineer,
    AltDataConfig,
)

__all__ = [
    "FeaturePipeline",
    "FeatureConfig",
    "compute_returns",
    "compute_momentum",
    "compute_volatility",
    "compute_volume_features",
    "compute_risk_features",
    "compute_enhanced_technical_features",
    "AlternativeFeatureEngineer",
    "AltDataConfig",
]
