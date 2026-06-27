"""
WebSocket feeds for real-time prediction market prices.

Connects to:
1. Polymarket CLOB WebSocket — real-time order book updates

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
    exchange: str           # "polymarket"
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
# Unified Feed Manager
# ============================================================

class PredictionMarketFeedManager:
    """
    Manages WebSocket feeds for Polymarket.

    Provides a single interface for:
    - Subscribing to markets
    - Getting real-time prices
    - Registering callbacks for price changes
    - Periodic price sampling to DB
    """

    def __init__(self):
        self.polymarket = PolymarketWSFeed()
        self._sample_task: Optional[asyncio.Task] = None
        self._sample_interval_sec: int = 60
        self._on_price_callbacks: List[Callable] = []

    async def start(self):
        """Start all WebSocket feeds."""
        await self.polymarket.start()
        self._sample_task = asyncio.create_task(self._periodic_sample())
        logger.info("Prediction market WebSocket feeds started")

    async def stop(self):
        """Stop all WebSocket feeds."""
        await self.polymarket.stop()
        if self._sample_task:
            self._sample_task.cancel()
            try:
                await self._sample_task
            except asyncio.CancelledError:
                pass
        logger.info("Prediction market WebSocket feeds stopped")

    async def subscribe_polymarket(self, token_ids: List[str]):
        await self.polymarket.subscribe(token_ids)

    def get_price(self, exchange: str, identifier: str) -> Optional[PredictionPrice]:
        """Get price by exchange and token_id."""
        if exchange == "polymarket":
            return self.polymarket.get_price(identifier)
        return None

    def get_all_prices(self) -> Dict[str, PredictionPrice]:
        """Get all prices."""
        prices = {}
        for token_id, price in self.polymarket.get_all_prices().items():
            prices[f"poly:{token_id}"] = price
        return prices

    def on_price_update(self, callback: Callable):
        """Register a callback for price updates."""
        self._on_price_callbacks.append(callback)
        self.polymarket.on_price_update(callback)

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
            "total_active_prices": len(self.polymarket.get_all_prices()),
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
