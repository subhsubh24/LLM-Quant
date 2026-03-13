"""
Polymarket API Client.

Wraps the three Polymarket APIs:
- Gamma API: Market discovery (events, markets, metadata) — no auth
- CLOB API: Read-only pricing (no auth), order placement (auth required)
- Data API: Trades, positions, holders, activity — no auth

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
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            logger.error(f"Polymarket API error: {e} (status={status}, url={url})")
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
            logger.warning(f"[POLYMARKET] Gamma API returned empty/null for markets (params={params})")
            return []

        if isinstance(data, dict):
            # Gamma API v2 may wrap results in a dict with "data" key
            if "data" in data:
                logger.info(f"[POLYMARKET] Gamma API returned dict with 'data' key, unwrapping")
                data = data["data"]
            else:
                logger.warning(f"[POLYMARKET] Gamma API returned dict with keys: {list(data.keys())[:10]}")
                return []

        if not isinstance(data, list):
            logger.warning(f"[POLYMARKET] Gamma API returned unexpected type: {type(data).__name__} (expected list)")
            return []

        markets = []
        parse_errors = 0
        for m in data:
            try:
                markets.append(self._parse_market(m))
            except Exception as e:
                parse_errors += 1
                if parse_errors <= 3:
                    logger.warning(f"[POLYMARKET] Market parse error: {e} | raw keys: {list(m.keys()) if isinstance(m, dict) else type(m)}")
        if parse_errors > 3:
            logger.warning(f"[POLYMARKET] {parse_errors} total parse errors")
        logger.info(f"[POLYMARKET] Fetched {len(markets)} markets (offset={offset}, raw={len(data)}, errors={parse_errors})")

        # Diagnostic: warn if most markets have zero volume/liquidity (likely API schema change)
        if markets:
            zero_vol = sum(1 for m in markets if m.total_volume == 0)
            zero_liq = sum(1 for m in markets if m.liquidity == 0)
            if zero_vol > len(markets) * 0.8:
                sample_keys = list(data[0].keys()) if data and isinstance(data[0], dict) else []
                logger.warning(
                    f"[POLYMARKET] {zero_vol}/{len(markets)} markets have volume=0 — "
                    f"API field names may have changed. Raw keys: {sample_keys}"
                )
            if zero_liq > len(markets) * 0.8:
                logger.warning(f"[POLYMARKET] {zero_liq}/{len(markets)} markets have liquidity=0")
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

    def enrich_markets_with_clob(
        self,
        markets: List[Market],
        max_markets: int = 40,
        fetch_books: bool = False,
    ) -> Dict[str, OrderBook]:
        """
        Enrich markets in-place with live CLOB prices.

        Updates each outcome's price and midpoint fields from the CLOB API.
        Rate budget: ~2 requests per binary market (1 midpoint per outcome).
        With max_markets=40 and 80 req/min limit, this takes ~60s worst case.

        Args:
            markets: Markets to enrich (modified in place).
            max_markets: Max markets to price (rate limit budget).
            fetch_books: Also fetch full order books (2x request budget).

        Returns:
            Dict of order books keyed by token_id (only if fetch_books=True).
        """
        order_books: Dict[str, OrderBook] = {}
        enriched = 0
        errors = 0

        for market in markets[:max_markets]:
            for outcome in market.outcomes:
                if not outcome.token_id:
                    continue
                try:
                    mid = self.get_midpoint(outcome.token_id)
                    if mid is not None:
                        outcome.price = mid
                        outcome.midpoint = mid
                        enriched += 1

                    if fetch_books:
                        book = self.get_order_book(outcome.token_id)
                        if book:
                            order_books[outcome.token_id] = book
                            # Update price to best bid (what you'd actually get)
                            if book.best_bid > 0:
                                outcome.price = book.best_bid
                except Exception as e:
                    errors += 1
                    if errors <= 3:
                        logger.warning(f"[CLOB] Enrichment error for {outcome.token_id}: {e}")

        if enriched > 0:
            logger.info(
                f"[CLOB] Enriched {enriched} outcomes across {min(len(markets), max_markets)} markets"
                + (f" ({len(order_books)} order books)" if fetch_books else "")
                + (f" ({errors} errors)" if errors else "")
            )
        return order_books

    # ================================================================
    # Data API (public, no auth required)
    # ================================================================

    def get_trades(
        self,
        market: Optional[str] = None,
        user: Optional[str] = None,
        side: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """
        Fetch trades from Data API.

        Args:
            market: Condition ID to filter by (optional).
            user: Wallet address to filter by (optional).
            side: "BUY" or "SELL" (optional).
            limit: Max results (up to 500).
            offset: Pagination offset.

        Returns list of trade dicts with keys: side, asset, conditionId,
        size, price, timestamp, transactionHash, trader, etc.
        """
        params: dict = {"limit": min(limit, 500), "offset": offset}
        if market:
            params["market"] = market
        if user:
            params["user"] = user
        if side:
            params["side"] = side
        data = self._get(f"{DATA_API}/trades", params)
        return data if isinstance(data, list) else []

    def get_positions(
        self,
        user: str,
        market: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "CASHPNL",
    ) -> List[dict]:
        """
        Fetch current positions for a wallet address.

        Returns list of position dicts with keys: asset, conditionId,
        size, avgPrice, currentValue, initialValue, cashPnl, percentPnl,
        title, outcome, etc.
        """
        params: dict = {"user": user, "limit": min(limit, 500), "offset": offset, "sortBy": sort_by}
        if market:
            params["market"] = market
        data = self._get(f"{DATA_API}/positions", params)
        return data if isinstance(data, list) else []

    def get_holders(
        self,
        market: str,
        limit: int = 100,
    ) -> List[dict]:
        """
        Get top holders for a market (condition ID).

        Returns list of dicts, each containing tokenId and holders array.
        Each holder has: proxyWallet, amount, outcomeIndex, pseudonym.
        """
        params: dict = {"market": market, "limit": limit}
        data = self._get(f"{DATA_API}/holders", params)
        return data if isinstance(data, list) else []

    def get_activity(
        self,
        user: str,
        activity_type: Optional[str] = None,
        market: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """
        Fetch on-chain activity for a wallet.

        Args:
            user: Wallet address.
            activity_type: TRADE, SPLIT, MERGE, REDEEM, REWARD, or CONVERSION.
            market: Condition ID filter.
            start: Unix timestamp (seconds).
            end: Unix timestamp (seconds).
        """
        params: dict = {"user": user, "limit": min(limit, 500), "offset": offset}
        if activity_type:
            params["type"] = activity_type
        if market:
            params["market"] = market
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        data = self._get(f"{DATA_API}/activity", params)
        return data if isinstance(data, list) else []

    def get_portfolio_value(self, user: str) -> Optional[float]:
        """Get total USD position value for a wallet."""
        data = self._get(f"{DATA_API}/value", params={"user": user})
        if isinstance(data, list) and data:
            return float(data[0].get("value", 0))
        return None

    def get_open_interest(self, market: Optional[str] = None) -> List[dict]:
        """
        Get open interest for a market.

        Returns list of dicts: [{"market": conditionId, "value": float}].
        """
        params: dict = {}
        if market:
            params["market"] = market
        data = self._get(f"{DATA_API}/oi", params)
        return data if isinstance(data, list) else []

    def get_leaderboard(
        self,
        period: str = "all",
        order_by: str = "pnl",
        limit: int = 50,
    ) -> List[dict]:
        """
        Get trader leaderboard ranked by PnL or volume.

        Args:
            period: "1d", "7d", "30d", or "all".
            order_by: "pnl" or "volume".
            limit: Max results (up to 100).

        Returns list of trader dicts with address, pnl, volume, etc.
        """
        params: dict = {"period": period, "orderBy": order_by, "limit": min(limit, 100)}
        data = self._get(f"{DATA_API}/leaderboard", params)
        return data if isinstance(data, list) else []

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_market(self, raw: dict) -> Market:
        """Parse raw Gamma API market into Market dataclass."""
        import json as _json

        # Parse outcomes from parallel arrays
        # Gamma API returns these as JSON-encoded strings: '["Yes","No"]' or CSV: "Yes,No"
        outcome_labels = raw.get("outcomes", "Yes,No")
        if isinstance(outcome_labels, str):
            try:
                parsed = _json.loads(outcome_labels)
                if isinstance(parsed, list):
                    outcome_labels = parsed
                else:
                    outcome_labels = outcome_labels.split(",")
            except (ValueError, TypeError):
                outcome_labels = outcome_labels.split(",")

        outcome_prices = raw.get("outcomePrices", "0.5,0.5")
        if isinstance(outcome_prices, str):
            try:
                parsed = _json.loads(outcome_prices)
                if isinstance(parsed, list):
                    outcome_prices = [float(p) for p in parsed]
                else:
                    outcome_prices = [float(p) for p in outcome_prices.split(",") if p]
            except (ValueError, TypeError):
                outcome_prices = [float(p) for p in outcome_prices.split(",") if p]
        elif isinstance(outcome_prices, list):
            outcome_prices = [float(p) for p in outcome_prices]

        token_ids = raw.get("clobTokenIds", [])
        if isinstance(token_ids, str):
            try:
                parsed = _json.loads(token_ids)
                if isinstance(parsed, list):
                    token_ids = [str(t) for t in parsed]
                else:
                    token_ids = [t.strip() for t in token_ids.split(",") if t.strip()]
            except (ValueError, TypeError):
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

        # Volume: try multiple field names (API schema changes over time)
        volume = 0.0
        for vol_key in ("volume", "volumeNum", "totalVolume", "total_volume", "volume_usd"):
            v = raw.get(vol_key)
            if v is not None:
                try:
                    volume = float(v)
                    if volume > 0:
                        break
                except (ValueError, TypeError):
                    pass

        # Liquidity: try multiple field names
        liquidity = 0.0
        for liq_key in ("liquidity", "liquidityNum", "totalLiquidity", "liquidityClob"):
            v = raw.get(liq_key)
            if v is not None:
                try:
                    liquidity = float(v)
                    if liquidity > 0:
                        break
                except (ValueError, TypeError):
                    pass

        return Market(
            id=raw.get("id", ""),
            condition_id=raw.get("conditionId", ""),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            description=raw.get("description", ""),
            category=raw.get("category", ""),
            end_date=end_date,
            outcomes=outcomes,
            total_volume=volume,
            liquidity=liquidity,
            active=raw.get("active", False),
            closed=raw.get("closed", False),
            resolved=raw.get("resolved", False) if "resolved" in raw else False,
            resolution_source=raw.get("resolutionSource", ""),
            tags=tags,
            neg_risk=raw.get("negRisk", False),
        )
