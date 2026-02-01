"""
Data providers for fetching stock market data.
Implements a clean interface with multiple backends.

Note on data quality:
- Free data sources have limitations (survivorship bias, delayed data, missing corporate actions)
- For production research, consider premium data sources
- This implementation documents known limitations
"""

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List
import pandas as pd
import numpy as np
import logging

from ..config import get_settings

logger = logging.getLogger(__name__)


class DataProvider(ABC):
    """Abstract base class for data providers."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: date,
        end_date: date
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV data for a single ticker.

        Returns DataFrame with columns: date, open, high, low, close, volume, adjusted_close
        Returns None if data unavailable.
        """
        pass

    @abstractmethod
    def fetch_multiple(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV data for multiple tickers.

        Returns dict mapping ticker -> DataFrame.
        Missing tickers are omitted from result.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and attribution."""
        pass

    @property
    def limitations(self) -> List[str]:
        """Document known data limitations."""
        return [
            "Free data sources subject to survivorship bias",
            "Corporate actions may not be fully adjusted",
            "Data may have delays or gaps",
        ]


class StooqProvider(DataProvider):
    """
    Stooq data provider - free, no API key required.

    Limitations:
    - US stocks only via .US suffix
    - May have gaps in historical data
    - Rate limited (be respectful)
    """

    BASE_URL = "https://stooq.com/q/d/l/"

    @property
    def name(self) -> str:
        return "stooq"

    @property
    def limitations(self) -> List[str]:
        return super().limitations + [
            "Stooq data may lag by 1 day",
            "Some tickers may not be available",
            "Volume data may be incomplete for some stocks",
        ]

    def _format_ticker(self, ticker: str) -> str:
        """Format ticker for Stooq API."""
        # Stooq uses .US suffix for US stocks
        ticker = ticker.upper().replace(".", "-")
        if not ticker.endswith(".US"):
            ticker = f"{ticker}.US"
        return ticker

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: date,
        end_date: date
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV from Stooq."""
        import requests

        stooq_ticker = self._format_ticker(ticker)
        url = f"{self.BASE_URL}?s={stooq_ticker}&d1={start_date.strftime('%Y%m%d')}&d2={end_date.strftime('%Y%m%d')}"

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Parse CSV
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))

            if df.empty or len(df) < 2:
                logger.warning(f"No data from Stooq for {ticker}")
                return None

            # Standardize columns
            df.columns = df.columns.str.lower()
            df = df.rename(columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume"
            })

            # Parse dates
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            # Add adjusted close (Stooq provides adjusted data by default)
            df["adjusted_close"] = df["close"]
            df["ticker"] = ticker.upper().replace(".US", "")

            # Basic validation
            df = self._validate_data(df)

            return df

        except Exception as e:
            logger.error(f"Error fetching {ticker} from Stooq: {e}")
            return None

    def fetch_multiple(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date
    ) -> Dict[str, pd.DataFrame]:
        """Fetch multiple tickers (sequentially to respect rate limits)."""
        import time

        results = {}
        for i, ticker in enumerate(tickers):
            df = self.fetch_ohlcv(ticker, start_date, end_date)
            if df is not None:
                results[ticker] = df

            # Rate limiting: small delay between requests
            if i < len(tickers) - 1:
                time.sleep(0.5)

        return results

    def _validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Basic data validation and cleaning."""
        # Remove rows with invalid prices
        df = df[df["close"] > 0]
        df = df[df["open"] > 0]
        df = df[df["high"] >= df["low"]]

        # Handle missing volume (set to 0, flag for caution)
        df["volume"] = df["volume"].fillna(0)

        return df


class YFinanceProvider(DataProvider):
    """
    Yahoo Finance data provider via yfinance library.

    Limitations:
    - Subject to Yahoo's terms of service
    - Data quality varies
    - May have rate limits
    """

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def limitations(self) -> List[str]:
        return super().limitations + [
            "Yahoo Finance data subject to their ToS",
            "Adjusted prices may have calculation differences",
            "Some historical data may be missing",
        ]

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: date,
        end_date: date
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV from Yahoo Finance."""
        import yfinance as yf

        try:
            stock = yf.Ticker(ticker)
            df = stock.history(
                start=start_date,
                end=end_date + timedelta(days=1),  # yfinance end is exclusive
                auto_adjust=False
            )

            if df.empty:
                logger.warning(f"No data from yfinance for {ticker}")
                return None

            # Standardize
            df = df.reset_index()
            df.columns = df.columns.str.lower()
            df = df.rename(columns={
                "adj close": "adjusted_close",
                "stock splits": "splits",
                "dividends": "dividends"
            })

            # Keep only needed columns
            df = df[["date", "open", "high", "low", "close", "volume", "adjusted_close"]]
            df["ticker"] = ticker.upper()
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

            # Validate
            df = self._validate_data(df)

            return df

        except Exception as e:
            logger.error(f"Error fetching {ticker} from yfinance: {e}")
            return None

    def fetch_multiple(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date
    ) -> Dict[str, pd.DataFrame]:
        """Fetch multiple tickers using yfinance batch download."""
        import yfinance as yf

        try:
            # yfinance supports batch downloads
            data = yf.download(
                tickers,
                start=start_date,
                end=end_date + timedelta(days=1),
                auto_adjust=False,
                group_by="ticker",
                threads=True
            )

            results = {}
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = data.copy()
                    else:
                        df = data[ticker].copy()

                    df = df.reset_index()
                    df.columns = df.columns.str.lower()
                    df = df.rename(columns={"adj close": "adjusted_close"})
                    df = df[["date", "open", "high", "low", "close", "volume", "adjusted_close"]]
                    df["ticker"] = ticker.upper()
                    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
                    df = self._validate_data(df)

                    if not df.empty:
                        results[ticker] = df

                except Exception as e:
                    logger.warning(f"Error processing {ticker}: {e}")
                    continue

            return results

        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            # Fallback to sequential
            return {
                t: df for t in tickers
                if (df := self.fetch_ohlcv(t, start_date, end_date)) is not None
            }

    def _validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Basic data validation."""
        df = df.dropna(subset=["close"])
        df = df[df["close"] > 0]
        df["volume"] = df["volume"].fillna(0)
        return df


def get_data_provider() -> DataProvider:
    """Factory function to get configured data provider."""
    settings = get_settings()

    if settings.data_provider == "stooq":
        return StooqProvider()
    elif settings.data_provider == "yfinance":
        return YFinanceProvider()
    else:
        logger.warning(f"Unknown provider {settings.data_provider}, defaulting to Stooq")
        return StooqProvider()
