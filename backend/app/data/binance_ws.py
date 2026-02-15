"""
Binance WebSocket client for real-time cryptocurrency prices.
Provides truly live data with no rate limits.
"""

import asyncio
import json
import logging
import ssl
from datetime import datetime
from typing import Dict, Optional, Callable, Set
from dataclasses import dataclass
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# CRITICAL SECURITY FIX: Enable SSL certificate verification
# Disabling verification creates MITM attack vulnerability
def _create_ssl_context():
    # Use default context which enables proper certificate validation
    ssl_context = ssl.create_default_context()
    # DO NOT disable hostname checking or certificate verification in production
    # If you have SSL issues, fix the certificates, don't disable security
    return ssl_context


@dataclass
class LivePrice:
    """Real-time price data from Binance WebSocket."""
    symbol: str  # e.g., "BTC", "ETH"
    price: float
    price_change_24h: float
    price_change_percent_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float  # Base asset volume
    quote_volume_24h: float  # Quote asset (USDT) volume
    open_price: float
    timestamp: datetime

    @property
    def is_live(self) -> bool:
        return True

    @property
    def data_source(self) -> str:
        return "binance_websocket"

    @property
    def data_age_seconds(self) -> float:
        return (datetime.now() - self.timestamp).total_seconds()


class BinanceWebSocket:
    """
    Binance WebSocket client for real-time price streaming.

    Uses the !miniTicker@arr stream which broadcasts ALL trading pairs
    every second - giving us real-time data for hundreds of coins at once.

    Tries multiple endpoints in order:
    1. Binance.US (for US users)
    2. Binance Global (for non-US)
    3. Binance Testnet (fallback)
    """

    # WebSocket endpoints to try in order
    WS_ENDPOINTS = [
        ("Binance.US", "wss://stream.binance.us:9443/ws"),
        ("Binance Global", "wss://stream.binance.com:9443/ws"),
        ("Binance Testnet", "wss://testnet.binance.vision/ws"),
    ]

    def __init__(self):
        self._prices: Dict[str, LivePrice] = {}
        self._running = False
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._reconnect_delay = 1  # Start with 1 second
        self._max_reconnect_delay = 60
        self._callbacks: Set[Callable] = set()
        self._connected = False
        self._last_update: Optional[datetime] = None
        self._update_count = 0
        self._current_endpoint: Optional[str] = None
        self._endpoint_index = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def prices(self) -> Dict[str, LivePrice]:
        return self._prices.copy()

    def get_price(self, symbol: str) -> Optional[LivePrice]:
        """Get live price for a symbol."""
        return self._prices.get(symbol.upper())

    def get_all_prices(self) -> Dict[str, LivePrice]:
        """Get all live prices."""
        return self._prices.copy()

    async def start(self):
        """Start the WebSocket connection."""
        if self._running:
            logger.warning("Binance WebSocket already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("🚀 Binance WebSocket started - real-time prices enabled")

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
        logger.info("🛑 Binance WebSocket stopped")

    async def _run(self):
        """Main WebSocket loop with reconnection logic. Tries multiple endpoints."""
        while self._running:
            # Try each endpoint in order
            connected = False
            for i, (name, base_url) in enumerate(self.WS_ENDPOINTS):
                if not self._running:
                    break

                try:
                    self._endpoint_index = i
                    await self._connect_and_stream(name, base_url)
                    connected = True
                    break  # Successfully connected and ran
                except ConnectionClosed as e:
                    logger.warning(f"{name} WebSocket connection closed: {e}")
                except Exception as e:
                    error_str = str(e)
                    if "451" in error_str:
                        logger.warning(f"{name} blocked (HTTP 451 - regulatory). Trying next endpoint...")
                        continue  # Try next endpoint immediately
                    elif "403" in error_str or "401" in error_str:
                        logger.warning(f"{name} access denied. Trying next endpoint...")
                        continue
                    else:
                        logger.error(f"{name} WebSocket error: {e}")

            if self._running and not connected:
                self._connected = False
                logger.info(f"All endpoints failed. Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                # Exponential backoff with max
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay
                )

    async def _connect_and_stream(self, name: str, base_url: str):
        """Connect to a specific WebSocket endpoint and process messages."""
        # Use the !miniTicker@arr stream for all symbols
        url = f"{base_url}/!miniTicker@arr"

        logger.info(f"Connecting to {name} WebSocket: {url}")

        # Use SSL context that handles corporate proxy/SSL inspection
        ssl_context = _create_ssl_context()

        async with websockets.connect(url, ping_interval=20, ssl=ssl_context) as ws:
            self._ws = ws
            self._connected = True
            self._current_endpoint = name
            self._reconnect_delay = 1  # Reset on successful connect
            logger.info(f"✅ {name} WebSocket connected - streaming live prices")

            async for message in ws:
                if not self._running:
                    break
                await self._process_message(message)

    async def _process_message(self, message: str):
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)

            # !miniTicker@arr returns an array of tickers
            if isinstance(data, list):
                updates = 0
                for ticker in data:
                    if self._process_ticker(ticker):
                        updates += 1

                self._last_update = datetime.now()
                self._update_count += updates

                # Log periodically (every 100 updates)
                if self._update_count % 100 == 0:
                    logger.debug(f"📊 Live prices updated: {len(self._prices)} symbols")

            # Single ticker (for individual subscriptions)
            elif isinstance(data, dict) and 'e' in data:
                self._process_ticker(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WebSocket message: {e}")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    def _process_ticker(self, ticker: Dict) -> bool:
        """
        Process a single ticker update.

        Mini ticker format:
        {
            "e": "24hrMiniTicker",  // Event type
            "E": 1672515782136,     // Event time
            "s": "BTCUSDT",         // Symbol
            "c": "16950.00",        // Close price
            "o": "16800.00",        // Open price
            "h": "17000.00",        // High price
            "l": "16700.00",        // Low price
            "v": "12345.67",        // Base asset volume
            "q": "209876543.21"     // Quote asset volume
        }
        """
        try:
            binance_symbol = ticker.get('s', '')

            # Only process USDT pairs
            if not binance_symbol.endswith('USDT'):
                return False

            # Extract our symbol (remove USDT suffix)
            symbol = binance_symbol[:-4]  # Remove "USDT"

            # Skip stablecoins and leveraged tokens
            if symbol in ('USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'FDUSD'):
                return False
            if any(x in symbol for x in ('UP', 'DOWN', 'BEAR', 'BULL')):
                return False

            close_price = float(ticker.get('c', 0))
            open_price = float(ticker.get('o', 0))
            high_price = float(ticker.get('h', 0))
            low_price = float(ticker.get('l', 0))
            volume = float(ticker.get('v', 0))
            quote_volume = float(ticker.get('q', 0))

            if close_price <= 0:
                return False

            # Calculate 24h change
            price_change = close_price - open_price
            price_change_percent = (price_change / open_price * 100) if open_price > 0 else 0

            self._prices[symbol] = LivePrice(
                symbol=symbol,
                price=close_price,
                price_change_24h=price_change,
                price_change_percent_24h=price_change_percent,
                high_24h=high_price,
                low_24h=low_price,
                volume_24h=volume,
                quote_volume_24h=quote_volume,
                open_price=open_price,
                timestamp=datetime.now(),
            )

            return True

        except (ValueError, KeyError) as e:
            logger.debug(f"Failed to process ticker: {e}")
            return False

    def add_callback(self, callback: Callable):
        """Add a callback to be called on price updates."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable):
        """Remove a callback."""
        self._callbacks.discard(callback)

    def get_status(self) -> Dict:
        """Get WebSocket connection status."""
        return {
            "connected": self._connected,
            "running": self._running,
            "endpoint": self._current_endpoint,
            "symbols_count": len(self._prices),
            "last_update": self._last_update.isoformat() if self._last_update else None,
            "total_updates": self._update_count,
            "data_source": "binance_websocket",
            "is_live": self._connected,
        }


# Singleton instance
_binance_ws: Optional[BinanceWebSocket] = None


def get_binance_ws() -> BinanceWebSocket:
    """Get singleton Binance WebSocket instance."""
    global _binance_ws
    if _binance_ws is None:
        _binance_ws = BinanceWebSocket()
    return _binance_ws


async def start_binance_ws():
    """Start the Binance WebSocket (call on app startup)."""
    ws = get_binance_ws()
    await ws.start()


async def stop_binance_ws():
    """Stop the Binance WebSocket (call on app shutdown)."""
    ws = get_binance_ws()
    await ws.stop()
