"""
Kalshi API Client.

Kalshi is a CFTC-regulated prediction market exchange.

Public endpoints (no auth required):
- GET /trade-api/v2/markets           — list/filter markets
- GET /trade-api/v2/markets/{ticker}  — single market
- GET /trade-api/v2/markets/{ticker}/orderbook — orderbook
- GET /trade-api/v2/events            — list events (groups of markets)
- GET /trade-api/v2/events/{ticker}   — single event with nested markets

Auth (API key + signature) required for: orders, portfolio, positions.
This client focuses on the read-only scanning side.

Base URL: https://api.elections.kalshi.com  (covers ALL markets, not just elections)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .polymarket_client import Market, OrderBook, Outcome, ScanResult  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

# Rate limiting — Kalshi doesn't publish exact limits; be conservative
MAX_REQUESTS_PER_MINUTE = 60
REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE


class KalshiClient:
    """
    Read-only Kalshi scanner for market discovery and pricing.

    Returns the same Market/Outcome/OrderBook dataclasses as PolymarketClient
    so strategies work with either exchange.
    """

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "LLM-Quant/1.0",
            "Accept": "application/json",
        })
        self._last_request_time = 0.0
        self._request_count = 0

    def _rate_limit(self):
        """Enforce rate limiting."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """Rate-limited GET request."""
        self._rate_limit()
        url = f"{KALSHI_API}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            self._request_count += 1
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Kalshi API error: {e}")
            return None

    # ================================================================
    # Market Discovery
    # ================================================================

    def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        tag: Optional[str] = None,
    ) -> List[Market]:
        """
        Fetch markets from Kalshi.

        Args:
            limit: Max markets to return (max 1000)
            offset: Not used by Kalshi (cursor-based), kept for API compat
            active: Only active (open) markets
            closed: Include closed/settled markets
            tag: Filter by series_ticker (e.g., "HIGHNY", "KXBTC")
        """
        params: Dict[str, Any] = {"limit": min(limit, 200)}

        if active and not closed:
            params["status"] = "open"
        elif closed and not active:
            params["status"] = "settled"
        # else: no filter — return all

        if tag:
            params["series_ticker"] = tag

        data = self._get("/markets", params)
        if not data or "markets" not in data:
            return []

        markets = []
        for m in data["markets"]:
            try:
                markets.append(self._parse_market(m))
            except Exception as e:
                logger.debug(f"Skipping malformed Kalshi market: {e}")

        return markets[:limit]

    def get_market_by_ticker(self, ticker: str) -> Optional[Market]:
        """Fetch a single market by ticker."""
        data = self._get(f"/markets/{ticker}")
        if data and "market" in data:
            return self._parse_market(data["market"])
        return None

    def get_events(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        with_nested_markets: bool = True,
    ) -> List[dict]:
        """
        Fetch events (each event groups related markets).

        Args:
            limit: Max events to return
            status: Filter by "open", "closed", or "settled"
            with_nested_markets: Include market objects in response
        """
        params: Dict[str, Any] = {"limit": min(limit, 200)}
        if status:
            params["status"] = status
        if with_nested_markets:
            params["with_nested_markets"] = "true"

        data = self._get("/events", params)
        if data and "events" in data:
            return data["events"]
        return []

    def search_markets(self, query: str, limit: int = 20) -> List[Market]:
        """Search markets by keyword (client-side filter)."""
        all_markets = self.get_markets(limit=200)
        query_lower = query.lower()
        return [
            m for m in all_markets
            if query_lower in m.question.lower()
            or query_lower in m.description.lower()
            or query_lower in m.category.lower()
        ][:limit]

    # ================================================================
    # Pricing
    # ================================================================

    def get_order_book(self, ticker: str) -> Optional[OrderBook]:
        """Get orderbook for a market ticker."""
        data = self._get(f"/markets/{ticker}/orderbook")
        if not data or "orderbook" not in data:
            return None

        ob = data["orderbook"]
        # Kalshi returns yes/no bids and asks
        # Convert cents to dollars (0-1 range)
        yes_bids = ob.get("yes", [])
        no_bids = ob.get("no", [])

        bids = [{"price": float(b[0]) / 100, "size": float(b[1])}
                for b in yes_bids] if yes_bids else []
        asks = [{"price": float(a[0]) / 100, "size": float(a[1])}
                for a in no_bids] if no_bids else []

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = 1.0 - asks[0]["price"] if asks else 1.0

        return OrderBook(
            token_id=ticker,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=best_ask - best_bid,
            tick_size=0.01,
            min_order_size=1,
        )

    def get_midpoint(self, ticker: str) -> Optional[float]:
        """Get midpoint price for a market (from orderbook)."""
        ob = self.get_order_book(ticker)
        if ob:
            return (ob.best_bid + ob.best_ask) / 2
        return None

    def get_price(self, ticker: str, side: str = "BUY") -> Optional[float]:
        """Get best price for a market."""
        ob = self.get_order_book(ticker)
        if not ob:
            return None
        return ob.best_ask if side == "BUY" else ob.best_bid

    def get_spread(self, ticker: str) -> Optional[float]:
        """Get bid-ask spread."""
        ob = self.get_order_book(ticker)
        if ob:
            return ob.spread
        return None

    def get_live_prices(self, markets: List[Market]) -> Dict[str, Dict[str, float]]:
        """Fetch live prices for markets. Returns {market_id: {outcome_label: price}}."""
        prices = {}
        for market in markets:
            # Kalshi markets use the ticker as ID
            yes_price = None
            for outcome in market.outcomes:
                if outcome.label == "Yes":
                    yes_price = outcome.price
                    break

            if yes_price is not None:
                prices[market.id] = {
                    "Yes": yes_price,
                    "No": 1.0 - yes_price,
                }
        return prices

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_market(self, raw: dict) -> Market:
        """Parse Kalshi API market into shared Market dataclass."""
        ticker = raw.get("ticker", "")

        # Prices — prefer _dollars fields, fall back to cents
        yes_price = 0.5
        if raw.get("yes_bid_dollars"):
            yes_bid = float(raw["yes_bid_dollars"])
            yes_ask = float(raw.get("yes_ask_dollars", raw["yes_bid_dollars"]))
            yes_price = (yes_bid + yes_ask) / 2
        elif raw.get("yes_bid") is not None:
            yes_bid = raw["yes_bid"] / 100
            yes_ask = raw.get("yes_ask", raw["yes_bid"]) / 100
            yes_price = (yes_bid + yes_ask) / 2
        elif raw.get("last_price") is not None:
            yes_price = raw["last_price"] / 100
        elif raw.get("last_price_dollars"):
            yes_price = float(raw["last_price_dollars"])

        no_price = 1.0 - yes_price

        # Build binary Yes/No outcomes
        outcomes = [
            Outcome(
                token_id=ticker,
                label="Yes",
                price=yes_price,
                midpoint=yes_price,
                volume=float(raw.get("volume", 0)),
            ),
            Outcome(
                token_id=f"{ticker}_NO",
                label="No",
                price=no_price,
                midpoint=no_price,
                volume=0.0,
            ),
        ]

        # Subtitle gives range info for multi-outcome events (e.g., "51° to 52°")
        title = raw.get("title", ticker)
        subtitle = raw.get("subtitle", "")
        question = f"{title} — {subtitle}" if subtitle else title

        # Parse close time
        end_date = None
        close_time = raw.get("close_time") or raw.get("expiration_time")
        if close_time:
            try:
                end_date = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Status mapping
        status = raw.get("status", "")
        is_active = status in ("open", "active")
        is_closed = status in ("closed",)
        is_resolved = status in ("settled",)

        # Category from event ticker prefix (e.g., HIGHNY → Weather, KXBTC → Crypto)
        event_ticker = raw.get("event_ticker", "")
        category = self._infer_category(event_ticker, title)

        return Market(
            id=ticker,
            condition_id=raw.get("event_ticker", ""),
            question=question,
            slug=ticker.lower(),
            description=subtitle,
            category=category,
            end_date=end_date,
            outcomes=outcomes,
            total_volume=float(raw.get("volume", 0)),
            liquidity=0.0,  # Kalshi deprecated liquidity field
            active=is_active,
            closed=is_closed,
            resolved=is_resolved,
            resolution_source="kalshi",
            tags=[event_ticker] if event_ticker else [],
            neg_risk=False,
        )

    @staticmethod
    def _infer_category(event_ticker: str, title: str) -> str:
        """Infer market category from event ticker prefix and title."""
        et = event_ticker.upper()
        tl = title.lower()

        if any(k in et for k in ("HIGH", "LOW", "TEMP", "RAIN", "SNOW", "WIND")):
            return "Weather"
        if any(k in et for k in ("KXBTC", "KXETH", "KXSOL", "CRYPTO")):
            return "Crypto"
        if any(k in et for k in ("INX", "SPY", "NASDAQ", "SP500")):
            return "Stocks"
        if any(k in et for k in ("FED", "CPI", "GDP", "ECON", "JOBS", "NFP")):
            return "Economics"
        if any(k in tl for k in ("election", "president", "senate", "congress")):
            return "Politics"
        if any(k in tl for k in ("oscar", "grammy", "super bowl", "nfl", "nba")):
            return "Entertainment"
        return "General"
