"""Data ingestion and management module."""

from .providers import DataProvider, StooqProvider, YFinanceProvider, get_data_provider
from .universe import UniverseManager, DEFAULT_UNIVERSE
from .cache import DataCache

__all__ = [
    "DataProvider",
    "StooqProvider",
    "YFinanceProvider",
    "get_data_provider",
    "UniverseManager",
    "DEFAULT_UNIVERSE",
    "DataCache",
]
