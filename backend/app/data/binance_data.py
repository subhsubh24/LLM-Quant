"""
Binance.US Market Data Fetcher for ML Model Training.

Fetches real historical data from Binance.US API to train ML models
with actual market data instead of synthetic data.

Endpoints used:
- /api/v3/klines - Candlestick data for historical prices
- /api/v3/ticker/price - Live prices
- /api/v3/ticker/24hr - 24h statistics (volume, volatility)
- /api/v3/avgPrice - Average price
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
import aiohttp
from functools import lru_cache

logger = logging.getLogger(__name__)

# Binance.US API base URL
BINANCE_US_BASE_URL = "https://api.binance.us/api/v3"

# Cache for price data (symbol -> (timestamp, data))
_price_cache: Dict[str, Tuple[datetime, np.ndarray]] = {}
_cache_duration = timedelta(minutes=5)


class BinanceDataFetcher:
    """
    Fetches real market data from Binance.US API.

    Used to provide real historical data for ML model training,
    improving prediction accuracy over synthetic data.
    """

    # Supported trading pairs on Binance.US (symbol -> USDT pair)
    SYMBOL_MAP = {
        # Major cryptos
        "BTC": "BTCUSDT",
        "ETH": "ETHUSDT",
        "SOL": "SOLUSDT",
        "BNB": "BNBUSDT",
        "XRP": "XRPUSDT",
        "DOGE": "DOGEUSDT",
        "ADA": "ADAUSDT",
        "AVAX": "AVAXUSDT",
        "LINK": "LINKUSDT",
        "DOT": "DOTUSDT",
        "MATIC": "MATICUSDT",
        "LTC": "LTCUSDT",
        "ATOM": "ATOMUSDT",
        "UNI": "UNIUSDT",
        "ETC": "ETCUSDT",
        "FIL": "FILUSDT",
        "NEAR": "NEARUSDT",
        "APT": "APTUSDT",
        "ARB": "ARBUSDT",
        "OP": "OPUSDT",
        "INJ": "INJUSDT",
        "SUI": "SUIUSDT",
        "SEI": "SEIUSDT",
        "FTM": "FTMUSDT",
        "AAVE": "AAVEUSDT",
        "MKR": "MKRUSDT",
        "LDO": "LDOUSDT",
        "CRV": "CRVUSDT",
        "SNX": "SNXUSDT",
        "COMP": "COMPUSDT",
        "GRT": "GRTUSDT",
        "FET": "FETUSDT",
        "RNDR": "RNDRUSDT",
        "AR": "ARUSDT",
        "THETA": "THETAUSDT",
        "STX": "STXUSDT",
        "PEPE": "PEPEUSDT",
        "SHIB": "SHIBUSDT",
        "FLOKI": "FLOKIUSDT",
        "BONK": "BONKUSDT",
    }

    # Perpetual symbol mapping (XXX-PERP -> XXXUSDT)
    @staticmethod
    def perp_to_spot(symbol: str) -> str:
        """Convert perpetual symbol to spot symbol."""
        base = symbol.replace("-PERP", "").replace("-perp", "")
        return BinanceDataFetcher.SYMBOL_MAP.get(base, f"{base}USDT")

    def __init__(self, use_testnet: bool = False):
        self.base_url = BINANCE_US_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        Fetch candlestick (kline) data from Binance.US.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT" or "BTC")
            interval: Kline interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            limit: Number of candles (max 1000)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds

        Returns:
            Array of shape (n, 6) with columns: [open, high, low, close, volume, close_time]
        """
        await self._ensure_session()

        # Convert symbol if needed
        if symbol in self.SYMBOL_MAP:
            trading_pair = self.SYMBOL_MAP[symbol]
        elif "-PERP" in symbol:
            trading_pair = self.perp_to_spot(symbol)
        else:
            trading_pair = symbol

        params = {
            "symbol": trading_pair,
            "interval": interval,
            "limit": min(limit, 1000),
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        try:
            async with self.session.get(
                f"{self.base_url}/klines",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    if data:
                        # Parse kline data
                        # [open_time, open, high, low, close, volume, close_time, ...]
                        klines = np.array([
                            [
                                float(k[1]),  # open
                                float(k[2]),  # high
                                float(k[3]),  # low
                                float(k[4]),  # close
                                float(k[5]),  # volume
                                k[6],         # close_time
                            ]
                            for k in data
                        ])
                        logger.debug(f"Fetched {len(klines)} klines for {trading_pair}")
                        return klines
                else:
                    logger.warning(f"Binance API error {response.status} for {trading_pair}")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching klines for {trading_pair}")
        except Exception as e:
            logger.debug(f"Error fetching klines for {trading_pair}: {e}")

        return None

    async def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Current price or None
        """
        await self._ensure_session()

        # Convert symbol if needed
        if symbol in self.SYMBOL_MAP:
            trading_pair = self.SYMBOL_MAP[symbol]
        elif "-PERP" in symbol:
            trading_pair = self.perp_to_spot(symbol)
        else:
            trading_pair = symbol

        try:
            async with self.session.get(
                f"{self.base_url}/ticker/price",
                params={"symbol": trading_pair},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get("price", 0))

        except Exception as e:
            logger.debug(f"Error fetching price for {trading_pair}: {e}")

        return None

    async def get_24hr_stats(self, symbol: str) -> Optional[Dict]:
        """
        Get 24-hour price change statistics.

        Args:
            symbol: Trading pair symbol

        Returns:
            Dict with price change stats or None
        """
        await self._ensure_session()

        # Convert symbol if needed
        if symbol in self.SYMBOL_MAP:
            trading_pair = self.SYMBOL_MAP[symbol]
        elif "-PERP" in symbol:
            trading_pair = self.perp_to_spot(symbol)
        else:
            trading_pair = symbol

        try:
            async with self.session.get(
                f"{self.base_url}/ticker/24hr",
                params={"symbol": trading_pair},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "price_change": float(data.get("priceChange", 0)),
                        "price_change_pct": float(data.get("priceChangePercent", 0)),
                        "weighted_avg_price": float(data.get("weightedAvgPrice", 0)),
                        "high": float(data.get("highPrice", 0)),
                        "low": float(data.get("lowPrice", 0)),
                        "volume": float(data.get("volume", 0)),
                        "quote_volume": float(data.get("quoteVolume", 0)),
                        "trade_count": int(data.get("count", 0)),
                    }

        except Exception as e:
            logger.debug(f"Error fetching 24hr stats for {trading_pair}: {e}")

        return None

    async def get_order_book(
        self,
        symbol: str,
        limit: int = 100
    ) -> Optional[Dict]:
        """
        Get order book depth.

        Args:
            symbol: Trading pair symbol
            limit: Number of price levels (max 5000)

        Returns:
            Dict with bids and asks or None
        """
        await self._ensure_session()

        # Convert symbol if needed
        if symbol in self.SYMBOL_MAP:
            trading_pair = self.SYMBOL_MAP[symbol]
        elif "-PERP" in symbol:
            trading_pair = self.perp_to_spot(symbol)
        else:
            trading_pair = symbol

        try:
            async with self.session.get(
                f"{self.base_url}/depth",
                params={"symbol": trading_pair, "limit": min(limit, 5000)},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "bids": [(float(b[0]), float(b[1])) for b in data.get("bids", [])],
                        "asks": [(float(a[0]), float(a[1])) for a in data.get("asks", [])],
                        "update_id": data.get("lastUpdateId"),
                    }

        except Exception as e:
            logger.debug(f"Error fetching order book for {trading_pair}: {e}")

        return None

    async def get_historical_prices(
        self,
        symbol: str,
        days: int = 252,
        interval: str = "1d"
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Get historical close prices and compute returns.

        Args:
            symbol: Trading symbol
            days: Number of days of history
            interval: Candle interval (1d recommended for ML training)

        Returns:
            Tuple of (prices array, returns array)
        """
        # Check cache first
        cache_key = f"{symbol}_{interval}_{days}"
        if cache_key in _price_cache:
            cached_time, cached_data = _price_cache[cache_key]
            if datetime.now() - cached_time < _cache_duration:
                prices = cached_data
                returns = np.diff(prices) / prices[:-1]
                return prices, returns

        # Fetch klines
        klines = await self.get_klines(symbol, interval=interval, limit=min(days, 1000))

        if klines is not None and len(klines) > 0:
            # Extract close prices
            prices = klines[:, 3]  # Close price is column 3

            # Cache the data
            _price_cache[cache_key] = (datetime.now(), prices)

            # Compute returns
            returns = np.diff(prices) / prices[:-1]

            return prices, returns

        # Return empty arrays if fetch failed
        return np.array([]), np.array([])

    async def get_multi_symbol_data(
        self,
        symbols: List[str],
        days: int = 252,
        interval: str = "1d"
    ) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
        """
        Fetch historical data for multiple symbols concurrently.

        Args:
            symbols: List of symbols
            days: Number of days
            interval: Candle interval

        Returns:
            Dict mapping symbol to (prices, returns) tuple
        """
        tasks = [
            self.get_historical_prices(symbol, days, interval)
            for symbol in symbols
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, tuple) and len(result[0]) > 0:
                data[symbol] = result
            else:
                logger.debug(f"No data for {symbol}")

        return data


# Singleton instance
_binance_fetcher: Optional[BinanceDataFetcher] = None


def get_binance_fetcher() -> BinanceDataFetcher:
    """Get singleton Binance data fetcher."""
    global _binance_fetcher
    if _binance_fetcher is None:
        _binance_fetcher = BinanceDataFetcher()
    return _binance_fetcher


async def fetch_real_crypto_data(
    symbols: List[str],
    days: int = 252
) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Convenience function to fetch real historical data for crypto symbols.

    Args:
        symbols: List of crypto symbols (e.g., ["BTC", "ETH", "SOL"])
        days: Number of days of history

    Returns:
        Dict mapping symbol to (prices, returns)
    """
    fetcher = get_binance_fetcher()
    return await fetcher.get_multi_symbol_data(symbols, days)


async def initialize_ml_with_real_data(analytics_engine, symbols: List[str]):
    """
    Initialize ML models with real historical data from Binance.

    Args:
        analytics_engine: QuantAnalyticsEngine instance
        symbols: List of symbols to fetch
    """
    logger.info(f"Fetching real historical data for {len(symbols)} symbols...")

    fetcher = get_binance_fetcher()
    data = await fetcher.get_multi_symbol_data(symbols, days=252, interval="1d")

    initialized = 0
    for symbol, (prices, returns) in data.items():
        if len(prices) >= 60:  # Need at least 60 days for ML models
            analytics_engine.update_price_history(symbol, prices)
            initialized += 1
            logger.debug(f"Initialized {symbol} with {len(prices)} days of real data")

    logger.info(f"Initialized {initialized}/{len(symbols)} symbols with real Binance data")

    return initialized
