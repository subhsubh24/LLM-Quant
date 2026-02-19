"""
Alternative data providers for non-price/volume signals.

Quant firms use dozens of alternative data sources beyond market data.
This module implements 15 provider categories:

1.  Macroeconomic data (FRED) - interest rates, inflation, employment
2.  Cross-asset signals - bonds, commodities, currencies, credit spreads
3.  Sentiment proxies - VIX term structure, market breadth, fund flows
4.  Calendar/seasonal effects - FOMC drift, turn of month, OpEx
5.  Options-derived signals - VRP, skew, gamma exposure
6.  SEC EDGAR - insider trading, institutional holdings
7.  News sentiment - RSS headlines + financial NLP
8.  Google Trends - search volume as attention/fear proxy
9.  Weather/climate - NOAA data, energy demand, SAD effect
10. Short volume - FINRA dark pool and short selling signals
11. Crypto sentiment - BTC/ETH as risk appetite proxy
12. Congressional/political - election cycles, policy uncertainty
13. Economic surprise - data release calendar, surprise index proxy
14. Sector rotation - SPDR sector momentum, relative strength
15. Bond stress - credit risk, yield curve, bond-equity correlation
"""

from .base import AlternativeDataProvider, AltDataConfig
from .fred_provider import FREDProvider
from .cross_asset_provider import CrossAssetProvider
from .sentiment_provider import SentimentProvider
from .calendar_provider import CalendarEffectsProvider
from .options_signals_provider import OptionsSignalsProvider
from .edgar_provider import EDGARProvider
from .news_sentiment_provider import NewsSentimentProvider
from .google_trends_provider import GoogleTrendsProvider
from .weather_provider import WeatherProvider
from .short_volume_provider import ShortVolumeProvider
from .crypto_sentiment_provider import CryptoSentimentProvider
from .congressional_provider import CongressionalProvider
from .economic_surprise_provider import EconomicSurpriseProvider
from .sector_rotation_provider import SectorRotationProvider
from .bond_stress_provider import BondStressProvider
from .alt_feature_engineer import AlternativeFeatureEngineer

__all__ = [
    "AlternativeDataProvider",
    "AltDataConfig",
    "FREDProvider",
    "CrossAssetProvider",
    "SentimentProvider",
    "CalendarEffectsProvider",
    "OptionsSignalsProvider",
    "EDGARProvider",
    "NewsSentimentProvider",
    "GoogleTrendsProvider",
    "WeatherProvider",
    "ShortVolumeProvider",
    "CryptoSentimentProvider",
    "CongressionalProvider",
    "EconomicSurpriseProvider",
    "SectorRotationProvider",
    "BondStressProvider",
    "AlternativeFeatureEngineer",
]
