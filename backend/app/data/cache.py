"""
Data caching layer for efficient data access.

Handles:
- SQLite storage of fetched price data
- Cache invalidation and refresh
- Data quality checks
"""

from datetime import date, datetime, timedelta
from typing import Optional, List, Dict
import pandas as pd
from sqlmodel import Session, select, and_
import logging

from ..db.models import StockPrice

logger = logging.getLogger(__name__)
from ..config import get_settings
from .providers import DataProvider, get_data_provider


class DataCache:
    """
    Caches stock price data in SQLite.

    This provides:
    - Faster repeated access to historical data
    - Reduced load on external APIs
    - Consistent data for reproducible research
    """

    def __init__(self, session: Session, provider: Optional[DataProvider] = None):
        self.session = session
        self.provider = provider or get_data_provider()
        self.settings = get_settings()

    def get_prices(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
        refresh: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Get price data for a ticker, fetching if needed.

        Args:
            ticker: Stock ticker symbol
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            refresh: Force refresh from provider

        Returns:
            DataFrame with OHLCV data or None if unavailable
        """
        ticker = ticker.upper()

        if not refresh:
            # Check cache
            cached = self._get_from_cache(ticker, start_date, end_date)
            if cached is not None and len(cached) > 0:
                # Check if cache is fresh enough
                if self._is_cache_valid(ticker, end_date):
                    return cached

        # Fetch from provider
        logger.info(f"Fetching {ticker} from {self.provider.name}")
        df = self.provider.fetch_ohlcv(ticker, start_date, end_date)

        if df is not None and not df.empty:
            self._save_to_cache(ticker, df)
            return df

        # Return cached data even if stale
        cached = self._get_from_cache(ticker, start_date, end_date)
        if cached is not None:
            logger.warning(f"Using stale cache for {ticker}")
            return cached

        return None

    def get_multiple(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        refresh: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """
        Get price data for multiple tickers.

        Returns dict mapping ticker -> DataFrame.
        """
        results = {}
        missing = []

        # Check cache first
        for ticker in tickers:
            ticker = ticker.upper()
            if not refresh:
                cached = self._get_from_cache(ticker, start_date, end_date)
                if cached is not None and len(cached) > 0:
                    if self._is_cache_valid(ticker, end_date):
                        results[ticker] = cached
                        continue
            missing.append(ticker)

        # Fetch missing from provider
        if missing:
            logger.info(f"Fetching {len(missing)} tickers from {self.provider.name}")
            fetched = self.provider.fetch_multiple(missing, start_date, end_date)

            for ticker, df in fetched.items():
                if df is not None and not df.empty:
                    self._save_to_cache(ticker, df)
                    results[ticker] = df

        return results

    def get_price_matrix(
        self,
        tickers: List[str],
        start_date: date,
        end_date: date,
        price_col: str = "adjusted_close"
    ) -> pd.DataFrame:
        """
        Get price matrix with tickers as columns.

        Returns DataFrame with dates as index, tickers as columns.
        Missing data is forward-filled then backward-filled.
        """
        data = self.get_multiple(tickers, start_date, end_date)

        if not data:
            return pd.DataFrame()

        # Build matrix
        dfs = []
        for ticker, df in data.items():
            series = df.set_index("date")[price_col].rename(ticker)
            dfs.append(series)

        if not dfs:
            return pd.DataFrame()

        matrix = pd.concat(dfs, axis=1)
        matrix.index = pd.to_datetime(matrix.index)
        matrix = matrix.sort_index()

        # Handle missing data (document this limitation)
        # Forward fill then backward fill
        matrix = matrix.ffill().bfill()

        return matrix

    def _get_from_cache(
        self,
        ticker: str,
        start_date: date,
        end_date: date
    ) -> Optional[pd.DataFrame]:
        """Retrieve data from SQLite cache."""
        statement = select(StockPrice).where(
            and_(
                StockPrice.ticker == ticker,
                StockPrice.date >= start_date,
                StockPrice.date <= end_date,
                StockPrice.is_valid == True
            )
        ).order_by(StockPrice.date)

        results = self.session.exec(statement).all()

        if not results:
            return None

        df = pd.DataFrame([
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "adjusted_close": r.adjusted_close or r.close,
                "ticker": r.ticker
            }
            for r in results
        ])

        df["date"] = pd.to_datetime(df["date"])
        return df

    def _save_to_cache(self, ticker: str, df: pd.DataFrame):
        """Save data to SQLite cache."""
        ticker = ticker.upper()

        # Remove existing data for this ticker in date range
        min_date = df["date"].min()
        max_date = df["date"].max()

        if isinstance(min_date, pd.Timestamp):
            min_date = min_date.date()
        if isinstance(max_date, pd.Timestamp):
            max_date = max_date.date()

        # Delete existing
        statement = select(StockPrice).where(
            and_(
                StockPrice.ticker == ticker,
                StockPrice.date >= min_date,
                StockPrice.date <= max_date
            )
        )
        existing = self.session.exec(statement).all()
        for record in existing:
            self.session.delete(record)

        # Insert new
        for _, row in df.iterrows():
            row_date = row["date"]
            if isinstance(row_date, pd.Timestamp):
                row_date = row_date.date()

            price = StockPrice(
                ticker=ticker,
                date=row_date,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                adjusted_close=float(row.get("adjusted_close", row["close"])),
                is_valid=True,
                data_source=self.provider.name
            )
            self.session.add(price)

        self.session.commit()

    def _is_cache_valid(self, ticker: str, end_date: date) -> bool:
        """Check if cache is still valid (not stale)."""
        # Get most recent cached date
        statement = select(StockPrice).where(
            StockPrice.ticker == ticker
        ).order_by(StockPrice.date.desc()).limit(1)

        latest = self.session.exec(statement).first()

        if latest is None:
            return False

        # If we're looking for recent data, check freshness
        today = date.today()
        if end_date >= today - timedelta(days=self.settings.data_cache_days):
            # Cache should be refreshed periodically
            cache_age = (datetime.utcnow() - latest.created_at).days
            if cache_age > self.settings.data_cache_days:
                return False

        return True

    def get_data_quality_report(self, ticker: str) -> Dict:
        """Generate data quality report for a ticker."""
        statement = select(StockPrice).where(
            StockPrice.ticker == ticker
        ).order_by(StockPrice.date)

        records = self.session.exec(statement).all()

        if not records:
            return {"status": "no_data", "ticker": ticker}

        dates = [r.date for r in records]
        closes = [r.close for r in records]
        volumes = [r.volume for r in records]

        # Check for gaps
        date_diffs = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        gap_days = [d for d in date_diffs if d > 5]  # More than 5 days = suspicious gap

        # Check for zero/negative values
        zero_closes = sum(1 for c in closes if c <= 0)
        zero_volumes = sum(1 for v in volumes if v <= 0)

        return {
            "ticker": ticker,
            "status": "ok" if len(gap_days) == 0 else "has_gaps",
            "start_date": str(dates[0]),
            "end_date": str(dates[-1]),
            "trading_days": len(records),
            "gaps_detected": len(gap_days),
            "zero_closes": zero_closes,
            "zero_volumes": zero_volumes,
            "data_source": records[0].data_source if records else None
        }
