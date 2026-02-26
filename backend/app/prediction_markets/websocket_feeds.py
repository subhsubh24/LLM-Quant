"""
WebSocket feeds for real-time prediction market prices.

Connects to:
1. Polymarket CLOB WebSocket — real-time order book updates
2. Kalshi WebSocket — live market data feed

Follows the same singleton + async pattern as crypto_ws.py.
Price updates are stored in-memory and optionally persisted to DB.
"""

import asyncio
import json
import logging
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


def _create_ssl_context():
    """Create SSL context with certificate verification."""
    ssl_context = ssl.create_default_context()
    return ssl_context


@dataclass
class PredictionPrice:
    """Real-time prediction market price."""
    exchange: str           # "polymarket" or "kalshi"
    market_id: str
    token_id: str
    outcome_label: str
    price: float            # 0.00-1.00
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    volume_24h: float = 0.0
    last_trade_price: float = 0.0
    last_trade_size: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_live(self) -> bool:
        return True

    @property
    def data_age_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.timestamp).total_seconds()

    @property
    def midpoint(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.price


# ============================================================
# Polymarket WebSocket Provider
# ============================================================

class PolymarketWSFeed:
    """
    WebSocket feed for Polymarket CLOB price updates.

    Connects to: wss://ws-subscriptions-clob.polymarket.com/ws/market
    Protocol: Subscribe to asset_ids (token_ids) for live book updates.
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

    def __init__(self):
        self._ws = None
        self._connected = False
        self._prices: Dict[str, PredictionPrice] = {}  # token_id -> PredictionPrice
        self._subscribed_tokens: Set[str] = set()
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._callbacks: List[Callable] = []
        self._task: Optional[asyncio.Task] = None
        # Sequence gap detection: track message sequence to detect missed updates
        self._last_sequence: Dict[str, int] = {}  # token_id -> last seq number
        self._gap_count: int = 0
        self._total_messages: int = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_price(self, token_id: str) -> Optional[PredictionPrice]:
        return self._prices.get(token_id)

    def get_all_prices(self) -> Dict[str, PredictionPrice]:
        return dict(self._prices)

    def on_price_update(self, callback: Callable):
        """Register a callback for price updates."""
        self._callbacks.append(callback)

    async def subscribe(self, token_ids: List[str]):
        """Subscribe to price updates for a list of token IDs."""
        new_tokens = set(token_ids) - self._subscribed_tokens
        if not new_tokens:
            return

        self._subscribed_tokens.update(new_tokens)

        if self._ws and self._connected:
            for token_id in new_tokens:
                msg = json.dumps({
                    "type": "subscribe",
                    "channel": "market",
                    "assets_ids": [token_id],
                })
                try:
                    await self._ws.send(msg)
                except Exception as e:
                    logger.warning(f"Polymarket WS subscribe failed: {e}")

    async def start(self):
        """Start the WebSocket connection."""
        self._task = asyncio.create_task(self._connect_loop())

    async def stop(self):
        """Stop the WebSocket connection."""
        self._connected = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _connect_loop(self):
        """Connection loop with reconnection."""
        while True:
            try:
                ssl_ctx = _create_ssl_context()
                async with websockets.connect(
                    self.WS_URL,
                    ssl=ssl_ctx,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = 1.0
                    logger.info("Polymarket WebSocket connected")

                    # Resubscribe to all tokens
                    if self._subscribed_tokens:
                        for token_id in self._subscribed_tokens:
                            msg = json.dumps({
                                "type": "subscribe",
                                "channel": "market",
                                "assets_ids": [token_id],
                            })
                            await ws.send(msg)

                    async for message in ws:
                        try:
                            self._handle_message(message)
                        except Exception as e:
                            logger.debug(f"Polymarket WS message parse error: {e}")

            except (ConnectionClosed, ConnectionError, OSError) as e:
                self._connected = False
                logger.warning(
                    f"Polymarket WS disconnected: {e}. "
                    f"Reconnecting in {self._reconnect_delay:.0f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                logger.error(f"Polymarket WS unexpected error: {e}")
                await asyncio.sleep(self._reconnect_delay)

    def _handle_message(self, raw: str):
        """Parse incoming Polymarket WebSocket message with sequence validation."""
        data = json.loads(raw)
        msg_type = data.get("type", "")
        self._total_messages += 1

        # Sequence gap detection: if messages include a sequence number,
        # verify continuity. A gap means our local state diverged from
        # the exchange — stale quotes will get adversely selected.
        seq = data.get("sequence") or data.get("seq")
        token_id_for_seq = data.get("asset_id", "")
        if seq is not None and token_id_for_seq:
            seq = int(seq)
            last = self._last_sequence.get(token_id_for_seq)
            if last is not None and seq > last + 1:
                gap = seq - last - 1
                self._gap_count += gap
                logger.warning(
                    f"[WS GAP] Polymarket sequence gap for {token_id_for_seq}: "
                    f"expected {last + 1}, got {seq} (missed {gap} messages)"
                )
            self._last_sequence[token_id_for_seq] = seq

        if msg_type == "price_change":
            # Book-level update
            for change in data.get("changes", []):
                token_id = change.get("asset_id", "")
                if not token_id:
                    continue

                price = self._prices.get(token_id, PredictionPrice(
                    exchange="polymarket",
                    market_id="",
                    token_id=token_id,
                    outcome_label="",
                    price=0.0,
                ))

                if "price" in change:
                    price.price = float(change["price"])
                if "bid" in change:
                    price.bid = float(change["bid"])
                if "ask" in change:
                    price.ask = float(change["ask"])
                if "spread" in change:
                    price.spread = float(change["spread"])

                price.timestamp = datetime.now(timezone.utc)
                self._prices[token_id] = price

                for cb in self._callbacks:
                    try:
                        cb(price)
                    except Exception:
                        pass

        elif msg_type == "last_trade_price":
            token_id = data.get("asset_id", "")
            if token_id and token_id in self._prices:
                self._prices[token_id].last_trade_price = float(data.get("price", 0))
                self._prices[token_id].last_trade_size = float(data.get("size", 0))
                self._prices[token_id].timestamp = datetime.now(timezone.utc)

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "subscribed_tokens": len(self._subscribed_tokens),
            "active_prices": len(self._prices),
            "provider": "polymarket",
            "total_messages": self._total_messages,
            "sequence_gaps": self._gap_count,
        }


# ============================================================
# Kalshi WebSocket Provider
# ============================================================

class KalshiWSFeed:
    """
    WebSocket feed for Kalshi live data.

    Connects to: wss://trading-api.kalshi.com/trade-api/ws/v2
    Protocol: Subscribe to tickers for orderbook + trade updates.
    """

    WS_URL = "wss://trading-api.kalshi.com/trade-api/ws/v2"

    def __init__(self, api_key_id: str = "", private_key_pem: str = ""):
        self.api_key_id = api_key_id
        self.private_key_pem = private_key_pem
        self._ws = None
        self._connected = False
        self._prices: Dict[str, PredictionPrice] = {}
        self._subscribed_tickers: Set[str] = set()
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._callbacks: List[Callable] = []
        self._task: Optional[asyncio.Task] = None
        self._seq = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_price(self, ticker: str) -> Optional[PredictionPrice]:
        return self._prices.get(ticker)

    def get_all_prices(self) -> Dict[str, PredictionPrice]:
        return dict(self._prices)

    def on_price_update(self, callback: Callable):
        self._callbacks.append(callback)

    async def subscribe(self, tickers: List[str]):
        """Subscribe to price updates for Kalshi tickers."""
        new_tickers = set(tickers) - self._subscribed_tickers
        if not new_tickers:
            return

        self._subscribed_tickers.update(new_tickers)

        if self._ws and self._connected:
            self._seq += 1
            msg = json.dumps({
                "id": self._seq,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta", "ticker"],
                    "market_tickers": list(new_tickers),
                },
            })
            try:
                await self._ws.send(msg)
            except Exception as e:
                logger.warning(f"Kalshi WS subscribe failed: {e}")

    async def start(self):
        self._task = asyncio.create_task(self._connect_loop())

    async def stop(self):
        self._connected = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _connect_loop(self):
        while True:
            try:
                ssl_ctx = _create_ssl_context()
                async with websockets.connect(
                    self.WS_URL,
                    ssl=ssl_ctx,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = 1.0
                    logger.info("Kalshi WebSocket connected")

                    # Resubscribe
                    if self._subscribed_tickers:
                        self._seq += 1
                        msg = json.dumps({
                            "id": self._seq,
                            "cmd": "subscribe",
                            "params": {
                                "channels": ["orderbook_delta", "ticker"],
                                "market_tickers": list(self._subscribed_tickers),
                            },
                        })
                        await ws.send(msg)

                    async for message in ws:
                        try:
                            self._handle_message(message)
                        except Exception as e:
                            logger.debug(f"Kalshi WS message parse error: {e}")

            except (ConnectionClosed, ConnectionError, OSError) as e:
                self._connected = False
                logger.warning(
                    f"Kalshi WS disconnected: {e}. "
                    f"Reconnecting in {self._reconnect_delay:.0f}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                logger.error(f"Kalshi WS unexpected error: {e}")
                await asyncio.sleep(self._reconnect_delay)

    def _handle_message(self, raw: str):
        """Parse Kalshi WebSocket messages."""
        data = json.loads(raw)
        msg_type = data.get("type", "")

        if msg_type == "orderbook_snapshot" or msg_type == "orderbook_delta":
            ticker = data.get("msg", {}).get("market_ticker", "")
            if not ticker:
                return

            msg = data.get("msg", {})
            yes_bids = msg.get("yes", [])

            best_bid = float(yes_bids[0][0]) / 100 if yes_bids else 0.0
            best_ask = 1.0 - best_bid if best_bid > 0 else 1.0

            price = PredictionPrice(
                exchange="kalshi",
                market_id=ticker,
                token_id=ticker,
                outcome_label="Yes",
                price=(best_bid + best_ask) / 2 if best_bid > 0 else 0.5,
                bid=best_bid,
                ask=best_ask,
                spread=best_ask - best_bid if best_bid > 0 else 0.0,
            )
            self._prices[ticker] = price

            for cb in self._callbacks:
                try:
                    cb(price)
                except Exception:
                    pass

        elif msg_type == "ticker":
            ticker = data.get("msg", {}).get("market_ticker", "")
            if not ticker:
                return

            msg = data.get("msg", {})
            yes_price = float(msg.get("yes_price", 50)) / 100

            if ticker in self._prices:
                self._prices[ticker].price = yes_price
                self._prices[ticker].timestamp = datetime.now(timezone.utc)
                if "volume" in msg:
                    self._prices[ticker].volume_24h = float(msg["volume"])
            else:
                self._prices[ticker] = PredictionPrice(
                    exchange="kalshi",
                    market_id=ticker,
                    token_id=ticker,
                    outcome_label="Yes",
                    price=yes_price,
                )

        elif msg_type == "trade":
            ticker = data.get("msg", {}).get("market_ticker", "")
            if ticker and ticker in self._prices:
                msg = data.get("msg", {})
                self._prices[ticker].last_trade_price = float(msg.get("yes_price", 0)) / 100
                self._prices[ticker].last_trade_size = float(msg.get("count", 0))
                self._prices[ticker].timestamp = datetime.now(timezone.utc)

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "subscribed_tickers": len(self._subscribed_tickers),
            "active_prices": len(self._prices),
            "provider": "kalshi",
        }


# ============================================================
# Unified Feed Manager
# ============================================================

class PredictionMarketFeedManager:
    """
    Manages WebSocket feeds across Polymarket and Kalshi.

    Provides a single interface for:
    - Subscribing to markets by exchange
    - Getting real-time prices
    - Registering callbacks for price changes
    - Periodic price sampling to DB
    """

    def __init__(self):
        self.polymarket = PolymarketWSFeed()
        self.kalshi = KalshiWSFeed()
        self._sample_task: Optional[asyncio.Task] = None
        self._sample_interval_sec: int = 60
        self._on_price_callbacks: List[Callable] = []

    async def start(self):
        """Start all WebSocket feeds."""
        await self.polymarket.start()
        await self.kalshi.start()
        self._sample_task = asyncio.create_task(self._periodic_sample())
        logger.info("Prediction market WebSocket feeds started")

    async def stop(self):
        """Stop all WebSocket feeds."""
        await self.polymarket.stop()
        await self.kalshi.stop()
        if self._sample_task:
            self._sample_task.cancel()
            try:
                await self._sample_task
            except asyncio.CancelledError:
                pass
        logger.info("Prediction market WebSocket feeds stopped")

    async def subscribe_polymarket(self, token_ids: List[str]):
        await self.polymarket.subscribe(token_ids)

    async def subscribe_kalshi(self, tickers: List[str]):
        await self.kalshi.subscribe(tickers)

    def get_price(self, exchange: str, identifier: str) -> Optional[PredictionPrice]:
        """Get price by exchange and token_id/ticker."""
        if exchange == "polymarket":
            return self.polymarket.get_price(identifier)
        elif exchange == "kalshi":
            return self.kalshi.get_price(identifier)
        return None

    def get_all_prices(self) -> Dict[str, PredictionPrice]:
        """Get all prices across both exchanges."""
        prices = {}
        for token_id, price in self.polymarket.get_all_prices().items():
            prices[f"poly:{token_id}"] = price
        for ticker, price in self.kalshi.get_all_prices().items():
            prices[f"kalshi:{ticker}"] = price
        return prices

    def on_price_update(self, callback: Callable):
        """Register a callback for any price update across all exchanges."""
        self._on_price_callbacks.append(callback)
        self.polymarket.on_price_update(callback)
        self.kalshi.on_price_update(callback)

    async def _periodic_sample(self):
        """Periodically sample prices to database."""
        while True:
            try:
                await asyncio.sleep(self._sample_interval_sec)
                await self._save_price_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Price sampling error: {e}")

    async def _save_price_snapshot(self):
        """Save current prices to PredictionPriceHistory table."""
        try:
            from ..db.database import get_session
            from .models import PredictionPriceHistory

            all_prices = self.get_all_prices()
            if not all_prices:
                return

            with get_session() as session:
                for key, price in all_prices.items():
                    if price.data_age_seconds > 300:
                        continue  # Skip stale prices

                    record = PredictionPriceHistory(
                        exchange=price.exchange,
                        market_id=price.market_id,
                        token_id=price.token_id,
                        outcome_label=price.outcome_label,
                        price=price.price,
                        bid=price.bid,
                        ask=price.ask,
                        spread=price.spread,
                        volume_24h=price.volume_24h,
                    )
                    session.add(record)

            logger.debug(f"Saved {len(all_prices)} prediction market price samples")
        except Exception as e:
            logger.error(f"Failed to save price snapshot: {e}")

    def get_status(self) -> dict:
        return {
            "polymarket": self.polymarket.get_status(),
            "kalshi": self.kalshi.get_status(),
            "total_active_prices": (
                len(self.polymarket.get_all_prices()) +
                len(self.kalshi.get_all_prices())
            ),
            "sample_interval_sec": self._sample_interval_sec,
        }


# ============================================================
# Singleton
# ============================================================

_feed_manager: Optional[PredictionMarketFeedManager] = None


def get_feed_manager() -> PredictionMarketFeedManager:
    """Get or create the global feed manager."""
    global _feed_manager
    if _feed_manager is None:
        _feed_manager = PredictionMarketFeedManager()
    return _feed_manager


async def start_prediction_feeds():
    """Start prediction market WebSocket feeds (called from app lifespan)."""
    manager = get_feed_manager()
    await manager.start()


async def stop_prediction_feeds():
    """Stop prediction market WebSocket feeds."""
    global _feed_manager
    if _feed_manager:
        await _feed_manager.stop()
