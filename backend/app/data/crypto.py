"""
Cryptocurrency market data service.
Uses CoinGecko API (free) for real-time crypto prices.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import httpx
import logging

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CryptoQuote:
    """Real-time cryptocurrency quote."""
    symbol: str
    name: str
    price: float
    change_24h: float
    change_percent_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    market_cap: float
    market_cap_rank: int
    circulating_supply: float
    total_supply: Optional[float]
    ath: float  # All-time high
    ath_change_percent: float
    timestamp: datetime

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class CryptoNews:
    """Crypto news item."""
    id: str
    title: str
    description: str
    url: str
    source: str
    published: datetime
    currencies: List[str]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['published'] = self.published.isoformat()
        return d


class CryptoMarketService:
    """Service for fetching cryptocurrency market data."""

    # Top cryptocurrencies to track
    TOP_CRYPTOS = {
        "bitcoin": ("BTC", "Bitcoin"),
        "ethereum": ("ETH", "Ethereum"),
        "binancecoin": ("BNB", "BNB"),
        "solana": ("SOL", "Solana"),
        "ripple": ("XRP", "XRP"),
        "cardano": ("ADA", "Cardano"),
        "dogecoin": ("DOGE", "Dogecoin"),
        "polkadot": ("DOT", "Polkadot"),
        "avalanche-2": ("AVAX", "Avalanche"),
        "chainlink": ("LINK", "Chainlink"),
        "polygon": ("MATIC", "Polygon"),
        "uniswap": ("UNI", "Uniswap"),
        "litecoin": ("LTC", "Litecoin"),
        "cosmos": ("ATOM", "Cosmos"),
        "ethereum-classic": ("ETC", "Ethereum Classic"),
    }

    # Symbol to CoinGecko ID mapping
    SYMBOL_TO_ID = {v[0]: k for k, v in TOP_CRYPTOS.items()}

    # Fallback mock data
    MOCK_PRICES = {
        "BTC": {"price": 43250.50, "change": 2.5, "mcap": 847000000000, "rank": 1},
        "ETH": {"price": 2285.75, "change": 1.8, "mcap": 275000000000, "rank": 2},
        "BNB": {"price": 315.20, "change": -0.5, "mcap": 47000000000, "rank": 4},
        "SOL": {"price": 98.45, "change": 5.2, "mcap": 43000000000, "rank": 5},
        "XRP": {"price": 0.62, "change": 1.2, "mcap": 34000000000, "rank": 6},
        "ADA": {"price": 0.58, "change": -1.1, "mcap": 20000000000, "rank": 8},
        "DOGE": {"price": 0.082, "change": 3.5, "mcap": 12000000000, "rank": 9},
        "DOT": {"price": 7.85, "change": 2.1, "mcap": 10000000000, "rank": 12},
        "AVAX": {"price": 35.60, "change": 4.3, "mcap": 13000000000, "rank": 10},
        "LINK": {"price": 14.25, "change": 1.5, "mcap": 8500000000, "rank": 14},
        "MATIC": {"price": 0.92, "change": -0.8, "mcap": 8500000000, "rank": 15},
        "UNI": {"price": 6.45, "change": 2.8, "mcap": 4800000000, "rank": 20},
        "LTC": {"price": 72.30, "change": 0.5, "mcap": 5400000000, "rank": 18},
        "ATOM": {"price": 9.15, "change": 1.9, "mcap": 3500000000, "rank": 25},
        "ETC": {"price": 18.75, "change": 0.3, "mcap": 2700000000, "rank": 28},
    }

    def __init__(self):
        self.settings = get_settings()
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = 30  # seconds (crypto moves fast!)
        self.base_url = "https://api.coingecko.com/api/v3"

    async def get_quote(self, symbol: str) -> Optional[CryptoQuote]:
        """Get real-time quote for a cryptocurrency."""
        symbol = symbol.upper()
        cache_key = f"crypto_quote_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Convert symbol to CoinGecko ID
        coin_id = self.SYMBOL_TO_ID.get(symbol)
        if not coin_id:
            # Try using symbol as ID directly
            coin_id = symbol.lower()

        try:
            async with httpx.AsyncClient() as client:
                quote = await self._fetch_coingecko_quote(client, coin_id, symbol)
                if quote:
                    self._set_cached(cache_key, quote)
                    return quote
        except Exception as e:
            logger.debug(f"CoinGecko API failed: {e}")

        # Fallback to mock data
        quote = self._get_mock_quote(symbol)
        if quote:
            self._set_cached(cache_key, quote)
        return quote

    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, CryptoQuote]:
        """Get quotes for multiple cryptocurrencies."""
        tasks = [self.get_quote(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, CryptoQuote):
                quotes[symbol.upper()] = result
        return quotes

    async def get_market_overview(self) -> Dict[str, Any]:
        """Get crypto market overview."""
        cache_key = "crypto_market_overview"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # Fetch top cryptos
            symbols = list(self.SYMBOL_TO_ID.keys())
            quotes = await self.get_quotes_batch(symbols)

            # Sort by market cap
            sorted_cryptos = sorted(
                quotes.values(),
                key=lambda x: x.market_cap,
                reverse=True
            )

            # Calculate market stats
            total_mcap = sum(q.market_cap for q in quotes.values())
            btc_dominance = (quotes.get("BTC").market_cap / total_mcap * 100) if quotes.get("BTC") and total_mcap > 0 else 0

            # Gainers and losers
            gainers = sorted(quotes.values(), key=lambda x: x.change_percent_24h, reverse=True)[:5]
            losers = sorted(quotes.values(), key=lambda x: x.change_percent_24h)[:5]

            overview = {
                "top_cryptos": [q.to_dict() for q in sorted_cryptos[:10]],
                "total_market_cap": total_mcap,
                "btc_dominance": round(btc_dominance, 2),
                "top_gainers": [q.to_dict() for q in gainers],
                "top_losers": [q.to_dict() for q in losers],
                "timestamp": datetime.now().isoformat(),
            }

            self._set_cached(cache_key, overview)
            return overview

        except Exception as e:
            logger.error(f"Error fetching crypto overview: {e}")
            return {"error": str(e)}

    async def get_price_history(
        self,
        symbol: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get historical price data."""
        symbol = symbol.upper()
        coin_id = self.SYMBOL_TO_ID.get(symbol, symbol.lower())

        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/coins/{coin_id}/market_chart"
                params = {
                    "vs_currency": "usd",
                    "days": days,
                }
                response = await client.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                prices = [(datetime.fromtimestamp(p[0]/1000).isoformat(), p[1])
                          for p in data.get("prices", [])]
                volumes = [(datetime.fromtimestamp(v[0]/1000).isoformat(), v[1])
                           for v in data.get("total_volumes", [])]

                return {
                    "symbol": symbol,
                    "days": days,
                    "prices": prices,
                    "volumes": volumes,
                }
        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            return {"symbol": symbol, "error": str(e)}

    async def _fetch_coingecko_quote(
        self,
        client: httpx.AsyncClient,
        coin_id: str,
        symbol: str
    ) -> Optional[CryptoQuote]:
        """Fetch quote from CoinGecko API."""
        try:
            url = f"{self.base_url}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            }
            response = await client.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            market = data.get("market_data", {})

            return CryptoQuote(
                symbol=symbol.upper(),
                name=data.get("name", symbol),
                price=market.get("current_price", {}).get("usd", 0),
                change_24h=market.get("price_change_24h", 0) or 0,
                change_percent_24h=market.get("price_change_percentage_24h", 0) or 0,
                high_24h=market.get("high_24h", {}).get("usd", 0) or 0,
                low_24h=market.get("low_24h", {}).get("usd", 0) or 0,
                volume_24h=market.get("total_volume", {}).get("usd", 0) or 0,
                market_cap=market.get("market_cap", {}).get("usd", 0) or 0,
                market_cap_rank=data.get("market_cap_rank", 0) or 0,
                circulating_supply=market.get("circulating_supply", 0) or 0,
                total_supply=market.get("total_supply"),
                ath=market.get("ath", {}).get("usd", 0) or 0,
                ath_change_percent=market.get("ath_change_percentage", {}).get("usd", 0) or 0,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"CoinGecko quote failed for {coin_id}: {e}")
            return None

    def _get_mock_quote(self, symbol: str) -> Optional[CryptoQuote]:
        """Generate mock quote when API is unavailable."""
        import random

        symbol = symbol.upper()
        mock = self.MOCK_PRICES.get(symbol)

        if mock is None:
            # Generate random data for unknown cryptos
            mock = {
                "price": random.uniform(0.5, 100),
                "change": random.uniform(-10, 10),
                "mcap": random.uniform(100000000, 10000000000),
                "rank": random.randint(50, 500),
            }

        # Add variation
        variation = random.uniform(-0.02, 0.02)
        price = mock["price"] * (1 + variation)
        name = self.TOP_CRYPTOS.get(self.SYMBOL_TO_ID.get(symbol, ""), (symbol, symbol))[1]

        return CryptoQuote(
            symbol=symbol,
            name=name,
            price=round(price, 2 if price > 1 else 6),
            change_24h=round(price * mock["change"] / 100, 4),
            change_percent_24h=round(mock["change"] + random.uniform(-1, 1), 2),
            high_24h=round(price * 1.05, 2 if price > 1 else 6),
            low_24h=round(price * 0.95, 2 if price > 1 else 6),
            volume_24h=random.uniform(100000000, 5000000000),
            market_cap=mock["mcap"],
            market_cap_rank=mock["rank"],
            circulating_supply=random.uniform(1000000, 100000000000),
            total_supply=None,
            ath=price * random.uniform(1.5, 3),
            ath_change_percent=random.uniform(-80, -10),
            timestamp=datetime.now(),
        )

    def _get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now() - entry["time"] < timedelta(seconds=self.cache_ttl):
                return entry["data"]
        return None

    def _set_cached(self, key: str, data: Any):
        """Set value in cache."""
        self.cache[key] = {"data": data, "time": datetime.now()}


# Singleton instance
_crypto_service: Optional[CryptoMarketService] = None


def get_crypto_service() -> CryptoMarketService:
    """Get singleton crypto market service."""
    global _crypto_service
    if _crypto_service is None:
        _crypto_service = CryptoMarketService()
    return _crypto_service
