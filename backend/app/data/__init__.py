"""Data ingestion and management module."""

from .providers import DataProvider, StooqProvider, YFinanceProvider, get_data_provider
from .universe import UniverseManager, DEFAULT_UNIVERSE
from .cache import DataCache
from .live import LiveMarketService, get_live_market_service, Quote
from .crypto import CryptoMarketService, get_crypto_service, CryptoQuote
from .options_data_provider import (
    OptionsDataProvider, RealOptionsChain, get_options_data_provider
)
from .alternative import (
    AlternativeFeatureEngineer,
    AltDataConfig,
    FREDProvider,
    CrossAssetProvider,
    SentimentProvider,
    CalendarEffectsProvider,
    OptionsSignalsProvider,
    EDGARProvider,
    NewsSentimentProvider,
    GoogleTrendsProvider,
    WeatherProvider,
    ShortVolumeProvider,
)

__all__ = [
    "DataProvider",
    "StooqProvider",
    "YFinanceProvider",
    "get_data_provider",
    "UniverseManager",
    "DEFAULT_UNIVERSE",
    "DataCache",
    "LiveMarketService",
    "get_live_market_service",
    "Quote",
    "CryptoMarketService",
    "get_crypto_service",
    "CryptoQuote",
    "OptionsDataProvider",
    "RealOptionsChain",
    "get_options_data_provider",
    "AlternativeFeatureEngineer",
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
]
