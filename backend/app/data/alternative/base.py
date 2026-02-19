"""
Base classes for alternative data providers.

Alternative data = any data that is NOT derived from the stock's own
price/volume history. This gives the model orthogonal information
that price-based features simply cannot capture.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict, List
import pandas as pd
import logging

logger = logging.getLogger(__name__)


@dataclass
class AltDataConfig:
    """Configuration for alternative data sources."""

    # FRED macroeconomic data
    fred_enabled: bool = True
    fred_api_key: str = ""  # Free from https://fred.stlouisfed.org/docs/api/api_key.html
    fred_series: List[str] = field(default_factory=lambda: [
        # Interest rates
        "DFF",          # Fed Funds Rate (daily)
        "DGS2",         # 2-Year Treasury Yield (daily)
        "DGS10",        # 10-Year Treasury Yield (daily)
        "DGS30",        # 30-Year Treasury Yield (daily)
        "T10Y2Y",       # 10Y-2Y Spread (yield curve, daily)
        "T10Y3M",       # 10Y-3M Spread (recession signal, daily)
        # Inflation
        "CPIAUCSL",     # CPI (monthly)
        "CPILFESL",     # Core CPI ex food & energy (monthly)
        "T5YIE",        # 5Y Breakeven Inflation (daily)
        "T10YIE",       # 10Y Breakeven Inflation (daily)
        # Employment
        "ICSA",         # Initial Jobless Claims (weekly)
        "UNRATE",       # Unemployment Rate (monthly)
        # Activity
        "INDPRO",       # Industrial Production (monthly)
        "RSAFS",        # Retail Sales (monthly)
        # Money & Credit
        "M2SL",         # M2 Money Supply (monthly)
        "BAMLH0A0HYM2", # High Yield OAS Spread (daily, credit stress)
        # Leading indicators
        "UMCSENT",      # U of Michigan Consumer Sentiment (monthly)
        "VIXCLS",       # VIX (daily, from FRED)
    ])

    # Cross-asset signals (via yfinance ETF proxies)
    cross_asset_enabled: bool = True
    cross_asset_tickers: Dict[str, str] = field(default_factory=lambda: {
        # Bonds
        "TLT": "long_treasury",       # 20+ Year Treasury
        "IEF": "mid_treasury",        # 7-10 Year Treasury
        "SHY": "short_treasury",      # 1-3 Year Treasury
        "HYG": "high_yield",          # High Yield Corporate
        "LQD": "invest_grade",        # Investment Grade Corporate
        "TIP": "tips",                # Inflation-Protected
        # Commodities
        "GLD": "gold",
        "SLV": "silver",
        "USO": "oil",
        "DBA": "agriculture",
        "DBB": "base_metals",         # Copper, aluminum, zinc
        # Currencies
        "UUP": "dollar_index",        # US Dollar Bull
        "FXY": "yen",
        "FXE": "euro",
        # Volatility
        "VXX": "vix_short",           # Short-term VIX futures
        "SVXY": "vix_inverse",        # Inverse VIX
        # International
        "EEM": "emerging_markets",
        "EFA": "developed_intl",
        # Sectors (for rotation signals)
        "XLF": "financials",
        "XLE": "energy",
        "XLU": "utilities",
        "XLP": "consumer_staples",
        "XLK": "technology",
    })

    # Sentiment proxies
    sentiment_enabled: bool = True

    # Calendar/seasonal effects (zero API cost - computed from dates)
    calendar_enabled: bool = True

    # Options-derived signals (VRP, skew, gamma from VIX/SPY)
    options_signals_enabled: bool = True

    # SEC EDGAR insider/institutional data
    edgar_enabled: bool = True

    # News sentiment (RSS feeds + NLP)
    news_sentiment_enabled: bool = True

    # Google Trends (requires pytrends, falls back to proxy)
    google_trends_enabled: bool = True

    # Weather/climate (NOAA, falls back to seasonal model)
    weather_enabled: bool = True

    # Short volume / dark pool signals
    short_volume_enabled: bool = True

    # Crypto as risk sentiment proxy (BTC/ETH)
    crypto_sentiment_enabled: bool = True

    # Congressional/political cycle signals (zero API cost - computed from dates)
    congressional_enabled: bool = True

    # Economic surprise and data release calendar (zero API cost - computed from dates)
    economic_surprise_enabled: bool = True

    # Sector rotation momentum (uses yfinance - free with internet)
    sector_rotation_enabled: bool = True

    # Bond market stress and credit risk (uses yfinance - free with internet)
    bond_stress_enabled: bool = True

    # Feature lag (minimum days to lag alternative data features)
    feature_lag_days: int = 1

    # Lookback windows for computing features from alt data
    lookback_windows: List[int] = field(default_factory=lambda: [5, 21, 63])

    def to_dict(self) -> dict:
        return {
            "fred_enabled": self.fred_enabled,
            "fred_series": self.fred_series,
            "cross_asset_enabled": self.cross_asset_enabled,
            "cross_asset_tickers": self.cross_asset_tickers,
            "sentiment_enabled": self.sentiment_enabled,
            "calendar_enabled": self.calendar_enabled,
            "options_signals_enabled": self.options_signals_enabled,
            "edgar_enabled": self.edgar_enabled,
            "news_sentiment_enabled": self.news_sentiment_enabled,
            "google_trends_enabled": self.google_trends_enabled,
            "weather_enabled": self.weather_enabled,
            "short_volume_enabled": self.short_volume_enabled,
            "crypto_sentiment_enabled": self.crypto_sentiment_enabled,
            "congressional_enabled": self.congressional_enabled,
            "economic_surprise_enabled": self.economic_surprise_enabled,
            "sector_rotation_enabled": self.sector_rotation_enabled,
            "bond_stress_enabled": self.bond_stress_enabled,
            "feature_lag_days": self.feature_lag_days,
            "lookback_windows": self.lookback_windows,
        }


class AlternativeDataProvider(ABC):
    """Base class for alternative data providers."""

    @abstractmethod
    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch alternative data for a date range.

        Returns:
            DataFrame with dates as index, data series as columns.
            Monthly/weekly data should be forward-filled to daily frequency.
        """
        pass

    @abstractmethod
    def get_feature_names(self) -> List[str]:
        """Return list of feature names this provider generates."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    def data_frequency(self) -> str:
        """Native data frequency before resampling."""
        return "mixed"

    def _resample_to_daily(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Resample mixed-frequency data to daily, forward-filling.

        CRITICAL: Forward-fill only. Never backfill, as that would
        use future data that wasn't available at the time.
        """
        if df.empty:
            return df

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Resample to business days, forward-fill
        daily_idx = pd.bdate_range(start=df.index.min(), end=df.index.max())
        df = df.reindex(daily_idx)
        df = df.ffill()  # Forward-fill only (no future leakage)

        return df
