"""
Alternative data providers for non-price/volume signals.

Quant firms use dozens of alternative data sources beyond market data.
This module implements the most accessible and proven ones:

1. Macroeconomic data (FRED) - interest rates, inflation, employment
2. Cross-asset signals - bonds, commodities, currencies, credit spreads
3. Sentiment proxies - VIX term structure, market breadth, fund flows
"""

from .base import AlternativeDataProvider, AltDataConfig
from .fred_provider import FREDProvider
from .cross_asset_provider import CrossAssetProvider
from .sentiment_provider import SentimentProvider
from .alt_feature_engineer import AlternativeFeatureEngineer

__all__ = [
    "AlternativeDataProvider",
    "AltDataConfig",
    "FREDProvider",
    "CrossAssetProvider",
    "SentimentProvider",
    "AlternativeFeatureEngineer",
]
