"""
Alpaca Historical Market Data Fetcher for ML Model Training.

Fetches real historical stock data from Alpaca API to train ML models
with actual market data instead of synthetic data.

Endpoints used:
- /v2/stocks/bars - Historical price bars (OHLCV)
- /v2/stocks/quotes - Historical quotes
- /v1beta1/news - Market news with sentiment
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
import aiohttp

from ..config import get_settings

logger = logging.getLogger(__name__)

# Alpaca Data API base URL
ALPACA_DATA_URL = "https://data.alpaca.markets"

# Cache for price data (symbol -> (timestamp, data))
_stock_price_cache: Dict[str, Tuple[datetime, np.ndarray]] = {}
_cache_duration = timedelta(minutes=15)


class AlpacaDataFetcher:
    """
    Fetches real historical market data from Alpaca API.

    Requires Alpaca API keys configured in environment:
    - ALPACA_API_KEY
    - ALPACA_API_SECRET
    """

    # Stock symbols to fetch
    STOCK_SYMBOLS = [
        # Major tech stocks
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
        # ETFs
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",
        # Commodities ETFs
        "GLD", "SLV", "USO", "UNG",
        # Sector ETFs
        "XLF", "XLE", "XLK", "XLV", "XLI", "XLU",
        # High volatility stocks
        "GME", "AMC", "COIN", "MARA", "RIOT",
        # Blue chips
        "JPM", "BAC", "WFC", "GS", "V", "MA",
        "JNJ", "PFE", "UNH", "MRK",
        "XOM", "CVX", "COP",
        "WMT", "HD", "TGT", "COST",
    ]

    def __init__(self):
        self.settings = get_settings()
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    @property
    def has_keys(self) -> bool:
        """Check if Alpaca API keys are configured."""
        return self.settings.has_alpaca_keys

    def _get_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        return {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": self.settings.alpaca_api_secret,
        }

    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self._get_headers())

    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 252,
        start: Optional[str] = None,
        end: Optional[str] = None,
        feed: str = "iex",  # Use iex for free tier, "sip" for paid
    ) -> Optional[np.ndarray]:
        """
        Fetch historical price bars from Alpaca.

        Args:
            symbol: Stock symbol (e.g., "AAPL", "SPY")
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day)
            limit: Number of bars (max 10000)
            start: Start date (YYYY-MM-DD)
            end: End date (YYYY-MM-DD)
            feed: Data feed ("iex" free, "sip" paid)

        Returns:
            Array of shape (n, 6) with columns: [open, high, low, close, volume, timestamp]
        """
        if not self.has_keys:
            logger.debug("Alpaca API keys not configured")
            return None

        await self._ensure_session()

        # Default to last year of data
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")
        if not start:
            start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        params = {
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "limit": min(limit, 10000),
            "feed": feed,
            "adjustment": "split",  # Adjust for stock splits
        }

        try:
            url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/bars"
            async with self.session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    bars = data.get("bars", [])
                    if bars:
                        # Parse bar data
                        result = np.array([
                            [
                                float(bar["o"]),  # open
                                float(bar["h"]),  # high
                                float(bar["l"]),  # low
                                float(bar["c"]),  # close
                                float(bar["v"]),  # volume
                                0,  # timestamp placeholder
                            ]
                            for bar in bars
                        ])
                        logger.debug(f"Fetched {len(result)} bars for {symbol}")
                        return result
                elif response.status == 403:
                    logger.debug(f"Alpaca API access forbidden for {symbol} - check subscription")
                else:
                    text = await response.text()
                    logger.debug(f"Alpaca API error {response.status} for {symbol}: {text[:100]}")

        except asyncio.TimeoutError:
            logger.debug(f"Timeout fetching bars for {symbol}")
        except Exception as e:
            logger.debug(f"Error fetching bars for {symbol}: {e}")

        return None

    async def get_latest_quote(self, symbol: str) -> Optional[float]:
        """
        Get latest quote for a symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Latest price or None
        """
        if not self.has_keys:
            return None

        await self._ensure_session()

        try:
            url = f"{ALPACA_DATA_URL}/v2/stocks/{symbol}/quotes/latest"
            async with self.session.get(
                url,
                params={"feed": "iex"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    quote = data.get("quote", {})
                    # Use midpoint of bid/ask
                    bid = float(quote.get("bp", 0))
                    ask = float(quote.get("ap", 0))
                    if bid > 0 and ask > 0:
                        return (bid + ask) / 2
                    return float(quote.get("ap", 0)) or float(quote.get("bp", 0))

        except Exception as e:
            logger.debug(f"Error fetching quote for {symbol}: {e}")

        return None

    async def get_historical_prices(
        self,
        symbol: str,
        days: int = 252,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get historical close prices and compute returns.

        Args:
            symbol: Stock symbol
            days: Number of trading days of history

        Returns:
            Tuple of (prices array, returns array)
        """
        # Check cache first
        cache_key = f"{symbol}_{days}"
        if cache_key in _stock_price_cache:
            cached_time, cached_data = _stock_price_cache[cache_key]
            if datetime.now() - cached_time < _cache_duration:
                prices = cached_data
                returns = np.diff(prices) / prices[:-1]
                return prices, returns

        # Fetch bars
        bars = await self.get_bars(symbol, timeframe="1Day", limit=days)

        if bars is not None and len(bars) > 0:
            # Extract close prices
            prices = bars[:, 3]  # Close price is column 3

            # Cache the data
            _stock_price_cache[cache_key] = (datetime.now(), prices)

            # Compute returns
            returns = np.diff(prices) / prices[:-1]

            return prices, returns

        # Return empty arrays if fetch failed
        return np.array([]), np.array([])

    async def get_multi_symbol_data(
        self,
        symbols: List[str],
        days: int = 252,
    ) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
        """
        Fetch historical data for multiple symbols concurrently.

        Args:
            symbols: List of symbols
            days: Number of days

        Returns:
            Dict mapping symbol to (prices, returns) tuple
        """
        if not self.has_keys:
            logger.info("Alpaca API keys not configured - skipping stock data fetch")
            return {}

        # Batch requests to avoid rate limits (200 req/min for free tier)
        batch_size = 10
        data = {}

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tasks = [
                self.get_historical_prices(symbol, days)
                for symbol in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for symbol, result in zip(batch, results):
                if isinstance(result, tuple) and len(result[0]) > 0:
                    data[symbol] = result
                else:
                    logger.debug(f"No data for {symbol}")

            # Small delay between batches to respect rate limits
            if i + batch_size < len(symbols):
                await asyncio.sleep(0.5)

        return data

    async def get_news(
        self,
        symbols: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """
        Fetch recent news for symbols.

        Args:
            symbols: List of symbols (None for all)
            limit: Number of articles

        Returns:
            List of news articles
        """
        if not self.has_keys:
            return []

        await self._ensure_session()

        params = {
            "limit": min(limit, 50),
            "include_content": False,
        }
        if symbols:
            params["symbols"] = ",".join(symbols[:10])  # Max 10 symbols

        try:
            url = f"{ALPACA_DATA_URL}/v1beta1/news"
            async with self.session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("news", [])

        except Exception as e:
            logger.debug(f"Error fetching news: {e}")

        return []


# Singleton instance
_alpaca_fetcher: Optional[AlpacaDataFetcher] = None


def get_alpaca_fetcher() -> AlpacaDataFetcher:
    """Get singleton Alpaca data fetcher."""
    global _alpaca_fetcher
    if _alpaca_fetcher is None:
        _alpaca_fetcher = AlpacaDataFetcher()
    return _alpaca_fetcher


async def fetch_real_stock_data(
    symbols: Optional[List[str]] = None,
    days: int = 252
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Convenience function to fetch real historical data for stock symbols.

    Args:
        symbols: List of stock symbols (uses defaults if None)
        days: Number of days of history

    Returns:
        Dict mapping symbol to (prices, returns)
    """
    fetcher = get_alpaca_fetcher()
    if symbols is None:
        symbols = fetcher.STOCK_SYMBOLS
    return await fetcher.get_multi_symbol_data(symbols, days)


async def initialize_ml_with_stock_data(analytics_engine, symbols: Optional[List[str]] = None):
    """
    Initialize ML models with real historical stock data from Alpaca.

    Args:
        analytics_engine: QuantAnalyticsEngine instance
        symbols: List of symbols to fetch (uses defaults if None)
    """
    fetcher = get_alpaca_fetcher()

    if not fetcher.has_keys:
        logger.info("Alpaca API keys not configured - using synthetic stock data")
        return 0

    if symbols is None:
        symbols = fetcher.STOCK_SYMBOLS

    logger.info(f"Fetching real historical data for {len(symbols)} stock symbols from Alpaca...")

    data = await fetcher.get_multi_symbol_data(symbols, days=252)

    initialized = 0
    for symbol, (prices, returns) in data.items():
        if len(prices) >= 60:  # Need at least 60 days for ML models
            analytics_engine.update_price_history(symbol, prices)
            initialized += 1
            logger.debug(f"Initialized {symbol} with {len(prices)} days of real Alpaca data")

    logger.info(f"Initialized {initialized}/{len(symbols)} stocks with real Alpaca data")

    return initialized
