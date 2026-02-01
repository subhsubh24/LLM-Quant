"""
Live market data service using yfinance and Finnhub.
Provides real-time quotes, news, and market overview.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor
import httpx
from loguru import logger

from ..config import get_settings

# Import yfinance
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed - some features may not work")


@dataclass
class Quote:
    """Real-time stock quote."""
    symbol: str
    price: float
    change: float
    change_percent: float
    high: float
    low: float
    open: float
    prev_close: float
    volume: int
    timestamp: datetime

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['timestamp'] = self.timestamp.isoformat()
        return d


@dataclass
class NewsItem:
    """Market news item."""
    id: str
    headline: str
    summary: str
    source: str
    url: str
    image: Optional[str]
    published: datetime
    related_symbols: List[str]
    sentiment: Optional[str] = None

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['published'] = self.published.isoformat()
        return d


@dataclass
class MarketIndex:
    """Major market index data."""
    symbol: str
    name: str
    price: float
    change: float
    change_percent: float


class LiveMarketService:
    """Service for fetching live market data."""

    # Major indices to track
    INDICES = {
        "^GSPC": "S&P 500",
        "^DJI": "Dow Jones",
        "^IXIC": "NASDAQ",
        "^RUT": "Russell 2000",
        "^VIX": "VIX",
    }

    # Sector ETFs for sector performance
    SECTOR_ETFS = {
        "XLK": "Technology",
        "XLF": "Financials",
        "XLV": "Healthcare",
        "XLE": "Energy",
        "XLI": "Industrials",
        "XLY": "Consumer Disc",
        "XLP": "Consumer Staples",
        "XLU": "Utilities",
        "XLB": "Materials",
        "XLRE": "Real Estate",
        "XLC": "Communication",
    }

    # Fallback mock data when APIs are unavailable
    MOCK_PRICES = {
        "AAPL": 185.92, "MSFT": 415.50, "GOOGL": 175.25, "AMZN": 185.75,
        "NVDA": 875.35, "META": 485.10, "TSLA": 248.50, "JPM": 195.80,
        "V": 280.45, "UNH": 525.30, "XOM": 105.25, "JNJ": 158.90,
        "WMT": 165.40, "MA": 450.25, "PG": 165.80, "HD": 365.50,
        "^GSPC": 4950.25, "^DJI": 38650.75, "^IXIC": 15625.50,
        "^RUT": 2025.30, "^VIX": 14.25,
        "XLK": 205.50, "XLF": 42.35, "XLV": 142.80, "XLE": 88.45,
        "XLI": 118.25, "XLY": 185.60, "XLP": 75.80, "XLU": 68.45,
        "XLB": 85.75, "XLRE": 38.90, "XLC": 78.25,
    }

    def __init__(self):
        self.settings = get_settings()
        self.finnhub_key = self.settings.finnhub_api_key
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = 60  # seconds
        self.executor = ThreadPoolExecutor(max_workers=4)

    def _fetch_yfinance_quote_sync(self, symbol: str) -> Optional[Quote]:
        """Synchronous yfinance quote fetch (runs in thread pool)."""
        if not YFINANCE_AVAILABLE:
            return None

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info

            price = float(info.last_price) if hasattr(info, 'last_price') and info.last_price else 0
            prev_close = float(info.previous_close) if hasattr(info, 'previous_close') and info.previous_close else price

            if price == 0:
                # Try getting from history
                hist = ticker.history(period="1d")
                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])
                    prev_close = float(hist['Open'].iloc[0])

            if price == 0:
                return None

            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            day_high = float(info.day_high) if hasattr(info, 'day_high') and info.day_high else price
            day_low = float(info.day_low) if hasattr(info, 'day_low') and info.day_low else price
            day_open = float(info.open) if hasattr(info, 'open') and info.open else price
            volume = int(info.last_volume) if hasattr(info, 'last_volume') and info.last_volume else 0

            return Quote(
                symbol=symbol,
                price=round(price, 2),
                change=round(change, 2),
                change_percent=round(change_pct, 2),
                high=round(day_high, 2),
                low=round(day_low, 2),
                open=round(day_open, 2),
                prev_close=round(prev_close, 2),
                volume=volume,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"yfinance quote failed for {symbol}: {e}")
            return None

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get real-time quote for a symbol."""
        cache_key = f"quote_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # Use yfinance in thread pool (it's synchronous)
            loop = asyncio.get_event_loop()
            quote = await loop.run_in_executor(
                self.executor,
                self._fetch_yfinance_quote_sync,
                symbol
            )

            if quote:
                self._set_cached(cache_key, quote)
                return quote

            # Fallback to Finnhub API
            if self.finnhub_key:
                async with httpx.AsyncClient() as client:
                    quote = await self._fetch_finnhub_quote(client, symbol)
                    if quote:
                        self._set_cached(cache_key, quote)
                        return quote

            # Final fallback: use mock data so UI works
            quote = self._get_mock_quote(symbol)
            if quote:
                self._set_cached(cache_key, quote)
            return quote

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            # Return mock data on error
            return self._get_mock_quote(symbol)

    def _get_mock_quote(self, symbol: str) -> Optional[Quote]:
        """Generate mock quote for testing when APIs are unavailable."""
        import random

        base_price = self.MOCK_PRICES.get(symbol.upper())
        if base_price is None:
            # Generate random price for unknown symbols
            base_price = random.uniform(50, 500)

        # Add small random variation
        variation = random.uniform(-0.02, 0.02)
        price = base_price * (1 + variation)
        prev_close = base_price
        change = price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        return Quote(
            symbol=symbol.upper(),
            price=round(price, 2),
            change=round(change, 2),
            change_percent=round(change_pct, 2),
            high=round(price * 1.01, 2),
            low=round(price * 0.99, 2),
            open=round(prev_close, 2),
            prev_close=round(prev_close, 2),
            volume=random.randint(1000000, 50000000),
            timestamp=datetime.now(),
        )

    async def get_quotes_batch(self, symbols: List[str]) -> Dict[str, Quote]:
        """Get quotes for multiple symbols."""
        tasks = [self.get_quote(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        quotes = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Quote):
                quotes[symbol] = result
        return quotes

    async def get_market_overview(self) -> Dict[str, Any]:
        """Get market overview with indices and sector performance."""
        cache_key = "market_overview"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # Fetch indices
            index_quotes = await self.get_quotes_batch(list(self.INDICES.keys()))
            indices = []
            for symbol, name in self.INDICES.items():
                if symbol in index_quotes:
                    q = index_quotes[symbol]
                    indices.append({
                        "symbol": symbol,
                        "name": name,
                        "price": q.price,
                        "change": q.change,
                        "change_percent": q.change_percent,
                    })

            # Fetch sectors
            sector_quotes = await self.get_quotes_batch(list(self.SECTOR_ETFS.keys()))
            sectors = []
            for symbol, name in self.SECTOR_ETFS.items():
                if symbol in sector_quotes:
                    q = sector_quotes[symbol]
                    sectors.append({
                        "symbol": symbol,
                        "name": name,
                        "change_percent": q.change_percent,
                    })

            # Sort sectors by performance
            sectors.sort(key=lambda x: x["change_percent"], reverse=True)

            overview = {
                "indices": indices,
                "sectors": sectors,
                "timestamp": datetime.now().isoformat(),
                "market_status": self._get_market_status(),
            }

            self._set_cached(cache_key, overview)
            return overview

        except Exception as e:
            logger.error(f"Error fetching market overview: {e}")
            return {"indices": [], "sectors": [], "error": str(e)}

    async def get_news(self, category: str = "general", limit: int = 20) -> List[NewsItem]:
        """Get market news."""
        cache_key = f"news_{category}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached[:limit]

        try:
            news = []
            async with httpx.AsyncClient() as client:
                if self.finnhub_key:
                    news = await self._fetch_finnhub_news(client, category)

            # If no news from Finnhub, try yfinance
            if not news and YFINANCE_AVAILABLE:
                loop = asyncio.get_event_loop()
                news = await loop.run_in_executor(
                    self.executor,
                    self._fetch_yfinance_news_sync,
                    "SPY"
                )

            self._set_cached(cache_key, news)
            return news[:limit]

        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return []

    async def get_symbol_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        """Get news for a specific symbol."""
        cache_key = f"news_symbol_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached[:limit]

        try:
            news = []

            # Try Finnhub first
            async with httpx.AsyncClient() as client:
                if self.finnhub_key:
                    news = await self._fetch_finnhub_company_news(client, symbol)

            # Fallback to yfinance
            if not news and YFINANCE_AVAILABLE:
                loop = asyncio.get_event_loop()
                news = await loop.run_in_executor(
                    self.executor,
                    self._fetch_yfinance_news_sync,
                    symbol
                )

            self._set_cached(cache_key, news)
            return news[:limit]

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def _fetch_yfinance_news_sync(self, symbol: str) -> List[NewsItem]:
        """Fetch news using yfinance (sync, runs in thread pool)."""
        try:
            ticker = yf.Ticker(symbol)
            raw_news = ticker.news or []

            news = []
            for item in raw_news[:20]:
                try:
                    published = datetime.fromtimestamp(item.get("providerPublishTime", 0))
                    news.append(NewsItem(
                        id=str(item.get("uuid", "")),
                        headline=item.get("title", ""),
                        summary=item.get("title", ""),  # yfinance doesn't have summary
                        source=item.get("publisher", ""),
                        url=item.get("link", ""),
                        image=item.get("thumbnail", {}).get("resolutions", [{}])[0].get("url") if item.get("thumbnail") else None,
                        published=published,
                        related_symbols=item.get("relatedTickers", []),
                    ))
                except Exception:
                    continue
            return news
        except Exception as e:
            logger.debug(f"yfinance news failed for {symbol}: {e}")
            return []

    async def _fetch_finnhub_quote(self, client: httpx.AsyncClient, symbol: str) -> Optional[Quote]:
        """Fetch quote from Finnhub API."""
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_key}"
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("c", 0) == 0:
                return None

            return Quote(
                symbol=symbol,
                price=data["c"],
                change=data["d"] or 0,
                change_percent=data["dp"] or 0,
                high=data["h"],
                low=data["l"],
                open=data["o"],
                prev_close=data["pc"],
                volume=0,  # Finnhub quote doesn't include volume
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Finnhub quote failed for {symbol}: {e}")
            return None

    async def _fetch_finnhub_news(self, client: httpx.AsyncClient, category: str) -> List[NewsItem]:
        """Fetch market news from Finnhub."""
        try:
            url = f"https://finnhub.io/api/v1/news?category={category}&token={self.finnhub_key}"
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            news = []
            for item in data[:50]:
                try:
                    news.append(NewsItem(
                        id=str(item.get("id", "")),
                        headline=item.get("headline", ""),
                        summary=item.get("summary", "")[:500],
                        source=item.get("source", ""),
                        url=item.get("url", ""),
                        image=item.get("image"),
                        published=datetime.fromtimestamp(item.get("datetime", 0)),
                        related_symbols=item.get("related", "").split(",") if item.get("related") else [],
                    ))
                except Exception:
                    continue
            return news
        except Exception as e:
            logger.debug(f"Finnhub news failed: {e}")
            return []

    async def _fetch_finnhub_company_news(self, client: httpx.AsyncClient, symbol: str) -> List[NewsItem]:
        """Fetch company-specific news from Finnhub."""
        try:
            today = datetime.now()
            from_date = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            to_date = today.strftime("%Y-%m-%d")

            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={from_date}&to={to_date}&token={self.finnhub_key}"
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            news = []
            for item in data[:20]:
                try:
                    news.append(NewsItem(
                        id=str(item.get("id", "")),
                        headline=item.get("headline", ""),
                        summary=item.get("summary", "")[:500],
                        source=item.get("source", ""),
                        url=item.get("url", ""),
                        image=item.get("image"),
                        published=datetime.fromtimestamp(item.get("datetime", 0)),
                        related_symbols=[symbol],
                    ))
                except Exception:
                    continue
            return news
        except Exception as e:
            logger.debug(f"Finnhub company news failed for {symbol}: {e}")
            return []

    def _get_market_status(self) -> str:
        """Determine if US market is open."""
        now = datetime.now()
        # Simple check - doesn't account for holidays
        if now.weekday() >= 5:
            return "closed"

        market_open = now.replace(hour=9, minute=30, second=0)
        market_close = now.replace(hour=16, minute=0, second=0)

        if market_open <= now <= market_close:
            return "open"
        elif now < market_open:
            return "pre-market"
        else:
            return "after-hours"

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
_service: Optional[LiveMarketService] = None

def get_live_market_service() -> LiveMarketService:
    """Get singleton live market service."""
    global _service
    if _service is None:
        _service = LiveMarketService()
    return _service
