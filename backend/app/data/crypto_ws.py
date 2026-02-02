"""
Multi-provider WebSocket client for real-time cryptocurrency prices.
Tries multiple exchanges until one connects successfully.

Providers (in order):
1. Coinbase - Most reliable in US
2. Kraken - Widely available globally
3. Binance.US - US users
4. Binance Global - International
"""

import asyncio
import json
import logging
import ssl
from datetime import datetime
from typing import Dict, Optional, List, Set
from dataclasses import dataclass
from abc import ABC, abstractmethod
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


def _create_ssl_context():
    """Create SSL context that bypasses certificate verification."""
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


@dataclass
class LivePrice:
    """Real-time price data from WebSocket."""
    symbol: str
    price: float
    price_change_24h: float
    price_change_percent_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    quote_volume_24h: float
    open_price: float
    timestamp: datetime
    source: str = "websocket"

    @property
    def is_live(self) -> bool:
        return True

    @property
    def data_source(self) -> str:
        return self.source

    @property
    def data_age_seconds(self) -> float:
        return (datetime.now() - self.timestamp).total_seconds()


class WebSocketProvider(ABC):
    """Base class for WebSocket providers."""

    name: str = "base"
    url: str = ""

    @abstractmethod
    async def connect_and_subscribe(self, ws) -> None:
        """Subscribe to price updates after connecting."""
        pass

    @abstractmethod
    def parse_message(self, message: str) -> List[LivePrice]:
        """Parse incoming message and return list of price updates."""
        pass


class CoinbaseProvider(WebSocketProvider):
    """Coinbase WebSocket provider - reliable in US."""

    name = "Coinbase"
    url = "wss://ws-feed.exchange.coinbase.com"

    # Top coins available on Coinbase
    SYMBOLS = [
        "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT",
        "MATIC", "SHIB", "LTC", "BCH", "UNI", "ATOM", "XLM", "ETC", "FIL",
        "APT", "NEAR", "OP", "INJ", "ARB", "GRT", "AAVE", "ALGO", "FTM",
        "SAND", "MANA", "AXS", "SNX", "LDO", "CRV", "MKR", "COMP", "SUSHI",
        "YFI", "BAT", "ZRX", "ENJ", "1INCH", "RNDR", "FET", "JASMY", "BLUR",
        "APE", "IMX", "SUI", "SEI", "TIA", "JUP", "BONK", "PEPE", "WIF",
    ]

    def __init__(self):
        self._last_prices: Dict[str, float] = {}
        self._open_prices: Dict[str, float] = {}

    async def connect_and_subscribe(self, ws) -> None:
        """Subscribe to ticker channel for all symbols."""
        # Build product IDs (e.g., BTC-USD)
        product_ids = [f"{s}-USD" for s in self.SYMBOLS]

        subscribe_msg = {
            "type": "subscribe",
            "product_ids": product_ids,
            "channels": ["ticker"]
        }
        await ws.send(json.dumps(subscribe_msg))
        logger.info(f"Coinbase: Subscribed to {len(product_ids)} pairs")

    def parse_message(self, message: str) -> List[LivePrice]:
        """Parse Coinbase ticker message."""
        try:
            data = json.loads(message)

            if data.get("type") != "ticker":
                return []

            product_id = data.get("product_id", "")
            if not product_id.endswith("-USD"):
                return []

            symbol = product_id.replace("-USD", "")
            price = float(data.get("price", 0))

            if price <= 0:
                return []

            # Track open price for 24h change calculation
            open_24h = float(data.get("open_24h", price))
            high_24h = float(data.get("high_24h", price))
            low_24h = float(data.get("low_24h", price))
            volume_24h = float(data.get("volume_24h", 0))

            price_change = price - open_24h
            price_change_pct = (price_change / open_24h * 100) if open_24h > 0 else 0

            return [LivePrice(
                symbol=symbol,
                price=price,
                price_change_24h=price_change,
                price_change_percent_24h=price_change_pct,
                high_24h=high_24h,
                low_24h=low_24h,
                volume_24h=volume_24h,
                quote_volume_24h=volume_24h * price,
                open_price=open_24h,
                timestamp=datetime.now(),
                source="coinbase_websocket",
            )]

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug(f"Coinbase parse error: {e}")
            return []


class KrakenProvider(WebSocketProvider):
    """Kraken WebSocket provider - widely available globally."""

    name = "Kraken"
    url = "wss://ws.kraken.com"

    # Kraken uses different symbol format
    SYMBOL_MAP = {
        "XBT/USD": "BTC", "ETH/USD": "ETH", "SOL/USD": "SOL", "XRP/USD": "XRP",
        "DOGE/USD": "DOGE", "ADA/USD": "ADA", "AVAX/USD": "AVAX", "LINK/USD": "LINK",
        "DOT/USD": "DOT", "MATIC/USD": "MATIC", "SHIB/USD": "SHIB", "LTC/USD": "LTC",
        "BCH/USD": "BCH", "UNI/USD": "UNI", "ATOM/USD": "ATOM", "XLM/USD": "XLM",
        "ETC/USD": "ETC", "FIL/USD": "FIL", "APT/USD": "APT", "NEAR/USD": "NEAR",
        "OP/USD": "OP", "INJ/USD": "INJ", "ARB/USD": "ARB", "GRT/USD": "GRT",
        "AAVE/USD": "AAVE", "ALGO/USD": "ALGO", "FTM/USD": "FTM", "SAND/USD": "SAND",
        "MANA/USD": "MANA", "AXS/USD": "AXS", "SNX/USD": "SNX", "LDO/USD": "LDO",
        "CRV/USD": "CRV", "MKR/USD": "MKR", "COMP/USD": "COMP", "SUSHI/USD": "SUSHI",
        "YFI/USD": "YFI", "BAT/USD": "BAT", "ZRX/USD": "ZRX", "ENJ/USD": "ENJ",
        "RNDR/USD": "RNDR", "FET/USD": "FET", "BLUR/USD": "BLUR", "APE/USD": "APE",
        "IMX/USD": "IMX", "SUI/USD": "SUI", "SEI/USD": "SEI", "TIA/USD": "TIA",
        "PEPE/USD": "PEPE", "BONK/USD": "BONK", "WIF/USD": "WIF",
    }

    def __init__(self):
        self._prices: Dict[str, LivePrice] = {}

    async def connect_and_subscribe(self, ws) -> None:
        """Subscribe to ticker channel."""
        pairs = list(self.SYMBOL_MAP.keys())

        subscribe_msg = {
            "event": "subscribe",
            "pair": pairs,
            "subscription": {"name": "ticker"}
        }
        await ws.send(json.dumps(subscribe_msg))
        logger.info(f"Kraken: Subscribed to {len(pairs)} pairs")

    def parse_message(self, message: str) -> List[LivePrice]:
        """Parse Kraken ticker message."""
        try:
            data = json.loads(message)

            # Kraken sends arrays for ticker data: [channelID, data, channelName, pair]
            if not isinstance(data, list) or len(data) < 4:
                return []

            if data[2] != "ticker":
                return []

            pair = data[3]
            ticker = data[1]

            symbol = self.SYMBOL_MAP.get(pair)
            if not symbol:
                return []

            # Kraken ticker format: {a: [ask], b: [bid], c: [close], v: [volume], ...}
            price = float(ticker.get("c", [0])[0])
            open_price = float(ticker.get("o", [price, price])[0])
            high = float(ticker.get("h", [price, price])[0])
            low = float(ticker.get("l", [price, price])[0])
            volume = float(ticker.get("v", [0, 0])[0])

            if price <= 0:
                return []

            price_change = price - open_price
            price_change_pct = (price_change / open_price * 100) if open_price > 0 else 0

            return [LivePrice(
                symbol=symbol,
                price=price,
                price_change_24h=price_change,
                price_change_percent_24h=price_change_pct,
                high_24h=high,
                low_24h=low,
                volume_24h=volume,
                quote_volume_24h=volume * price,
                open_price=open_price,
                timestamp=datetime.now(),
                source="kraken_websocket",
            )]

        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
            logger.debug(f"Kraken parse error: {e}")
            return []


class BinanceProvider(WebSocketProvider):
    """Binance WebSocket provider."""

    name = "Binance"
    url = "wss://stream.binance.com:9443/ws/!miniTicker@arr"

    async def connect_and_subscribe(self, ws) -> None:
        """Binance auto-subscribes via URL."""
        logger.info("Binance: Connected to miniTicker stream")

    def parse_message(self, message: str) -> List[LivePrice]:
        """Parse Binance mini ticker array."""
        try:
            data = json.loads(message)
            prices = []

            if not isinstance(data, list):
                return []

            for ticker in data:
                symbol_pair = ticker.get("s", "")
                if not symbol_pair.endswith("USDT"):
                    continue

                symbol = symbol_pair[:-4]

                # Skip stablecoins and leveraged tokens
                if symbol in ("USDC", "BUSD", "DAI", "TUSD"):
                    continue
                if any(x in symbol for x in ("UP", "DOWN", "BEAR", "BULL")):
                    continue

                price = float(ticker.get("c", 0))
                if price <= 0:
                    continue

                open_price = float(ticker.get("o", price))
                high = float(ticker.get("h", price))
                low = float(ticker.get("l", price))
                volume = float(ticker.get("v", 0))
                quote_volume = float(ticker.get("q", 0))

                price_change = price - open_price
                price_change_pct = (price_change / open_price * 100) if open_price > 0 else 0

                prices.append(LivePrice(
                    symbol=symbol,
                    price=price,
                    price_change_24h=price_change,
                    price_change_percent_24h=price_change_pct,
                    high_24h=high,
                    low_24h=low,
                    volume_24h=volume,
                    quote_volume_24h=quote_volume,
                    open_price=open_price,
                    timestamp=datetime.now(),
                    source="binance_websocket",
                ))

            return prices

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug(f"Binance parse error: {e}")
            return []


class BinanceUSProvider(BinanceProvider):
    """Binance.US WebSocket provider."""

    name = "Binance.US"
    url = "wss://stream.binance.us:9443/ws/!miniTicker@arr"


class MultiProviderWebSocket:
    """
    Binance WebSocket client for crypto price streaming.
    Uses Binance only to ensure consistent data format for derivatives trading.
    """

    def __init__(self):
        self._prices: Dict[str, LivePrice] = {}
        self._running = False
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._current_provider: Optional[str] = None
        self._last_update: Optional[datetime] = None
        self._update_count = 0
        self._reconnect_delay = 1  # Start with 1 second
        self._max_reconnect_delay = 10  # Max 10 seconds (quick reconnect)

        # Only use Binance providers for consistent derivatives data format
        self._providers: List[WebSocketProvider] = [
            BinanceUSProvider(),  # Try Binance.US first
            BinanceProvider(),    # Fallback to international Binance
        ]

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_price(self, symbol: str) -> Optional[LivePrice]:
        return self._prices.get(symbol.upper())

    def get_all_prices(self) -> Dict[str, LivePrice]:
        return self._prices.copy()

    async def start(self):
        """Start the WebSocket connection."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("🚀 Binance WebSocket started")

    async def stop(self):
        """Stop the WebSocket connection."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("🛑 WebSocket stopped")

    async def _run(self):
        """Main loop - connect to Binance with quick reconnection."""
        while self._running:
            connected = False

            for provider in self._providers:
                if not self._running:
                    break

                try:
                    logger.info(f"Connecting to {provider.name}...")
                    await self._connect_to_provider(provider)
                    connected = True
                    self._reconnect_delay = 1  # Reset delay on successful connection
                    break
                except Exception as e:
                    error_str = str(e)
                    if "451" in error_str:
                        logger.debug(f"{provider.name} blocked (HTTP 451), trying fallback...")
                    elif "403" in error_str or "401" in error_str:
                        logger.debug(f"{provider.name} access denied, trying fallback...")
                    elif "1011" in error_str or "ping timeout" in error_str.lower():
                        logger.debug(f"{provider.name} connection lost, reconnecting...")
                    else:
                        logger.debug(f"{provider.name} disconnected: {e}")
                    continue

            if self._running and not connected:
                self._connected = False
                # Quick reconnection - don't wait long
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, self._max_reconnect_delay)

    async def _connect_to_provider(self, provider: WebSocketProvider):
        """Connect to a specific provider."""
        ssl_context = _create_ssl_context()

        async with websockets.connect(
            provider.url,
            ssl=ssl_context,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._current_provider = provider.name
            self._reconnect_delay = 1
            logger.info(f"✅ {provider.name} WebSocket connected - streaming LIVE prices")

            # Subscribe to channels
            await provider.connect_and_subscribe(ws)

            # Process messages
            async for message in ws:
                if not self._running:
                    break

                prices = provider.parse_message(message)
                for price in prices:
                    self._prices[price.symbol] = price
                    self._update_count += 1

                if prices:
                    self._last_update = datetime.now()

                # Log periodically
                if self._update_count % 500 == 0:
                    logger.debug(f"📊 {provider.name}: {len(self._prices)} symbols streaming")

    def get_status(self) -> Dict:
        """Get connection status."""
        return {
            "connected": self._connected,
            "running": self._running,
            "provider": self._current_provider,
            "symbols_count": len(self._prices),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "total_updates": self._update_count,
            "is_live": self._connected,
        }


# Singleton
_crypto_ws: Optional[MultiProviderWebSocket] = None


def get_crypto_ws() -> MultiProviderWebSocket:
    """Get singleton WebSocket instance."""
    global _crypto_ws
    if _crypto_ws is None:
        _crypto_ws = MultiProviderWebSocket()
    return _crypto_ws


async def start_crypto_ws():
    """Start the WebSocket."""
    ws = get_crypto_ws()
    await ws.start()


async def stop_crypto_ws():
    """Stop the WebSocket."""
    ws = get_crypto_ws()
    await ws.stop()
