"""
Live market data service using Finnhub and Yahoo Finance.
Provides real-time quotes, news, and market overview.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import httpx
from loguru import logger

from ..config import get_settings


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

    def __init__(self):
        self.settings = get_settings()
        self.finnhub_key = self.settings.finnhub_api_key
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = 30  # seconds

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get real-time quote for a symbol."""
        cache_key = f"quote_{symbol}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            async with httpx.AsyncClient() as client:
                # Try Finnhub first if we have a key
                if self.finnhub_key:
                    quote = await self._fetch_finnhub_quote(client, symbol)
                    if quote:
                        self._set_cached(cache_key, quote)
                        return quote

                # Fallback to Yahoo Finance
                quote = await self._fetch_yahoo_quote(client, symbol)
                if quote:
                    self._set_cached(cache_key, quote)
                return quote

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None

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

                if not news:
                    news = await self._fetch_yahoo_news(client)

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
            async with httpx.AsyncClient() as client:
                if self.finnhub_key:
                    news = await self._fetch_finnhub_company_news(client, symbol)

            self._set_cached(cache_key, news)
            return news[:limit]

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
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

    async def _fetch_yahoo_quote(self, client: httpx.AsyncClient, symbol: str) -> Optional[Quote]:
        """Fetch quote from Yahoo Finance."""
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = await client.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            result = data.get("chart", {}).get("result", [])
            if not result:
                return None

            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("previousClose", price)

            if price == 0:
                return None

            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            return Quote(
                symbol=symbol,
                price=price,
                change=change,
                change_percent=change_pct,
                high=meta.get("regularMarketDayHigh", price),
                low=meta.get("regularMarketDayLow", price),
                open=meta.get("regularMarketOpen", price),
                prev_close=prev_close,
                volume=meta.get("regularMarketVolume", 0),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.debug(f"Yahoo quote failed for {symbol}: {e}")
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

    async def _fetch_yahoo_news(self, client: httpx.AsyncClient) -> List[NewsItem]:
        """Fallback news from Yahoo Finance RSS."""
        # Simplified fallback - in production would parse RSS
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
