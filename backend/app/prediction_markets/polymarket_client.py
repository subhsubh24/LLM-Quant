"""
Polymarket API Client.

Wraps the three Polymarket APIs:
- Gamma API: Market discovery (events, markets, metadata) — no auth
- CLOB API: Trading (prices, order books, order placement) — auth required
- Data API: Portfolio (positions, trade history) — auth required

Uses py-clob-client for authenticated operations, raw HTTP for read-only scanning.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 80  # Conservative (limit is ~100)
REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE


class MarketStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"


@dataclass
class Outcome:
    """A single outcome in a prediction market (e.g., YES or NO)."""
    token_id: str
    label: str          # "Yes", "No", "42-45°F", etc.
    price: float        # Current best price (0.00 to 1.00)
    midpoint: float     # Midpoint price
    volume: float       # Total volume traded


@dataclass
class Market:
    """A prediction market with its outcomes."""
    id: str
    condition_id: str
    question: str
    slug: str
    description: str
    category: str
    end_date: Optional[datetime]
    outcomes: List[Outcome]
    total_volume: float
    liquidity: float
    active: bool
    closed: bool
    resolved: bool
    resolution_source: str = ""
    tags: List[str] = field(default_factory=list)
    neg_risk: bool = False  # Negative risk market (multi-outcome)

    @property
    def status(self) -> MarketStatus:
        if self.resolved:
            return MarketStatus.RESOLVED
        if self.closed:
            return MarketStatus.CLOSED
        return MarketStatus.ACTIVE

    @property
    def spread(self) -> float:
        """Price spread between YES and NO (should be ~0 for efficient markets)."""
        if len(self.outcomes) == 2:
            return abs(1.0 - sum(o.price for o in self.outcomes))
        return 0.0

    @property
    def is_binary(self) -> bool:
        return len(self.outcomes) == 2

    @property
    def is_multi(self) -> bool:
        return len(self.outcomes) > 2


@dataclass
class OrderBook:
    """Order book for a single outcome token."""
    token_id: str
    bids: List[Dict[str, float]]  # [{"price": 0.45, "size": 1000}, ...]
    asks: List[Dict[str, float]]
    best_bid: float
    best_ask: float
    spread: float
    tick_size: float
    min_order_size: float


@dataclass
class ScanResult:
    """Result from a market scan identifying an opportunity."""
    market: Market
    strategy: str           # "weather_arb", "near_certainty", "cross_market_arb", "same_market_arb"
    outcome_idx: int        # Which outcome to trade
    side: str               # "BUY" or "SELL"
    entry_price: float      # Price to enter at
    expected_value: float   # Expected payout
    edge: float             # Expected profit as decimal (e.g., 0.15 = 15%)
    confidence: float       # Signal confidence (0-1)
    reason: str             # Human-readable explanation
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PolymarketClient:
    """
    Read-only Polymarket scanner for market discovery and pricing.

    For order placement, use py-clob-client with wallet authentication.
    This client focuses on the scanning/analysis side which doesn't require auth.
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

    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """Rate-limited GET request."""
        self._rate_limit()
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            self._request_count += 1
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Polymarket API error: {e}")
            return None

    # ================================================================
    # Market Discovery (Gamma API)
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
        Fetch markets from Gamma API.

        Args:
            limit: Max markets to return (max 100 per page)
            offset: Pagination offset
            active: Only active markets
            closed: Include closed markets
            tag: Filter by category tag (e.g., "weather", "politics", "crypto")
        """
        params = {"limit": limit, "offset": offset}
        if active:
            params["active"] = "true"
        if closed:
            params["closed"] = "true"
        if tag:
            params["tag"] = tag

        data = self._get(f"{GAMMA_API}/markets", params)
        if not data:
            return []

        markets = []
        for m in data:
            try:
                markets.append(self._parse_market(m))
            except Exception as e:
                logger.debug(f"Skipping malformed market: {e}")
        return markets

    def get_market_by_slug(self, slug: str) -> Optional[Market]:
        """Fetch a single market by its URL slug."""
        data = self._get(f"{GAMMA_API}/markets", params={"slug": slug})
        if data and len(data) > 0:
            return self._parse_market(data[0])
        return None

    def get_events(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """Fetch events (each event contains 1+ markets)."""
        data = self._get(f"{GAMMA_API}/events", params={"limit": limit, "offset": offset})
        return data or []

    def search_markets(self, query: str, limit: int = 20) -> List[Market]:
        """Search markets by keyword."""
        # Gamma API doesn't have a search endpoint, so we fetch and filter
        all_markets = []
        for offset in range(0, 200, 100):
            batch = self.get_markets(limit=100, offset=offset)
            all_markets.extend(batch)
            if len(batch) < 100:
                break

        query_lower = query.lower()
        return [
            m for m in all_markets
            if query_lower in m.question.lower()
            or query_lower in m.description.lower()
            or any(query_lower in t.lower() for t in m.tags)
        ][:limit]

    # ================================================================
    # Pricing (CLOB API)
    # ================================================================

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get best price for a token."""
        data = self._get(f"{CLOB_API}/price", params={"token_id": token_id, "side": side})
        if data and "price" in data:
            return float(data["price"])
        return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        data = self._get(f"{CLOB_API}/midpoint", params={"token_id": token_id})
        if data and "mid" in data:
            return float(data["mid"])
        return None

    def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        """Get full order book for a token."""
        data = self._get(f"{CLOB_API}/book", params={"token_id": token_id})
        if not data:
            return None

        bids = [{"price": float(b["price"]), "size": float(b["size"])}
                for b in data.get("bids", [])]
        asks = [{"price": float(a["price"]), "size": float(a["size"])}
                for a in data.get("asks", [])]

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 1.0

        return OrderBook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=best_ask - best_bid,
            tick_size=float(data.get("tick_size", 0.01)),
            min_order_size=float(data.get("min_order_size", 5)),
        )

    def get_spread(self, token_id: str) -> Optional[float]:
        """Get bid-ask spread for a token."""
        data = self._get(f"{CLOB_API}/spread", params={"token_id": token_id})
        if data and "spread" in data:
            return float(data["spread"])
        return None

    # ================================================================
    # Batch Operations
    # ================================================================

    def get_live_prices(self, markets: List[Market]) -> Dict[str, Dict[str, float]]:
        """
        Fetch live prices for all outcomes in a list of markets.

        Returns: {market_id: {outcome_label: price}}
        """
        prices = {}
        for market in markets:
            market_prices = {}
            for outcome in market.outcomes:
                if outcome.token_id:
                    price = self.get_midpoint(outcome.token_id)
                    if price is not None:
                        market_prices[outcome.label] = price
            if market_prices:
                prices[market.id] = market_prices
        return prices

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_market(self, raw: dict) -> Market:
        """Parse raw Gamma API market into Market dataclass."""
        # Parse outcomes from parallel arrays
        outcome_labels = raw.get("outcomes", "Yes,No")
        if isinstance(outcome_labels, str):
            outcome_labels = outcome_labels.split(",")

        outcome_prices = raw.get("outcomePrices", "0.5,0.5")
        if isinstance(outcome_prices, str):
            outcome_prices = [float(p) for p in outcome_prices.split(",") if p]
        elif isinstance(outcome_prices, list):
            outcome_prices = [float(p) for p in outcome_prices]

        token_ids = raw.get("clobTokenIds", [])
        if isinstance(token_ids, str):
            token_ids = [t.strip() for t in token_ids.split(",") if t.strip()]

        outcomes = []
        for i, label in enumerate(outcome_labels):
            outcomes.append(Outcome(
                token_id=token_ids[i] if i < len(token_ids) else "",
                label=label.strip(),
                price=outcome_prices[i] if i < len(outcome_prices) else 0.5,
                midpoint=outcome_prices[i] if i < len(outcome_prices) else 0.5,
                volume=0.0,
            ))

        # Parse end date
        end_date = None
        if raw.get("endDate"):
            try:
                end_date = datetime.fromisoformat(raw["endDate"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        # Parse tags
        tags = raw.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        return Market(
            id=raw.get("id", ""),
            condition_id=raw.get("conditionId", ""),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            end_date=end_date,
            outcomes=outcomes,
            total_volume=float(raw.get("volume", 0)),
            liquidity=float(raw.get("liquidity", 0)),
            active=raw.get("active", False),
            closed=raw.get("closed", False),
            resolved=raw.get("resolved", False) if "resolved" in raw else False,
            resolution_source=raw.get("resolutionSource", ""),
            tags=tags,
            neg_risk=raw.get("negRisk", False),
        )
