"""
Live Broker Integrations for Real Trading.

Supports:
- Alpaca: US Stocks, ETFs, Options (paper + live)
- Binance: Crypto Spot, Perpetual Futures

IMPORTANT: Start with paper trading to verify the system works correctly
before switching to live trading with real money.
"""

import os
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import json

from .activity_logger import get_activity_logger, EventSubtype

logger = logging.getLogger(__name__)


class BrokerType(Enum):
    """Supported brokers."""
    ALPACA = "alpaca"
    BINANCE = "binance"
    PAPER = "paper"  # Simulated


class TradingMode(Enum):
    """Trading mode."""
    PAPER = "paper"
    LIVE = "live"


@dataclass
class BrokerCredentials:
    """API credentials for a broker."""
    broker: BrokerType
    api_key: str
    api_secret: str
    is_paper: bool = True
    additional_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LivePosition:
    """A real position from a broker."""
    symbol: str
    quantity: float
    side: str  # "long" or "short"
    entry_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float
    broker: BrokerType


@dataclass
class LiveOrder:
    """A real order submitted to a broker."""
    id: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str  # "market", "limit", "stop"
    limit_price: Optional[float]
    stop_price: Optional[float]
    status: str  # "pending", "filled", "cancelled", "rejected"
    filled_quantity: float
    filled_price: float
    broker: BrokerType
    timestamp: datetime


# =============================================================================
# ALPACA BROKER (US Stocks, ETFs, Options)
# =============================================================================

class AlpacaBroker:
    """
    Alpaca Trading API Integration.

    Supports:
    - US Stocks and ETFs
    - Options (beta)
    - Paper and Live trading
    - Real-time market data

    Documentation: https://alpaca.markets/docs/
    """

    PAPER_BASE_URL = "https://paper-api.alpaca.markets"
    LIVE_BASE_URL = "https://api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        self.base_url = self.PAPER_BASE_URL if paper else self.LIVE_BASE_URL

        self._session = None
        self._connected = False

        logger.info(f"AlpacaBroker initialized: {'PAPER' if paper else 'LIVE'} mode")

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.api_secret,
                }
            )
        return self._session

    async def connect(self) -> bool:
        """Connect and verify credentials."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/v2/account") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._connected = True
                    logger.info(f"Alpaca connected: Account {data.get('account_number')}")
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Alpaca connection failed: {error}")
                    return False
        except Exception as e:
            logger.error(f"Alpaca connection error: {e}")
            return False

    async def disconnect(self):
        """Close connection."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    async def get_account(self) -> Dict:
        """Get account information."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/v2/account") as resp:
            if resp.status == 200:
                return await resp.json()
            raise Exception(f"Failed to get account: {await resp.text()}")

    async def get_positions(self) -> List[LivePosition]:
        """Get all open positions."""
        session = await self._get_session()
        async with session.get(f"{self.base_url}/v2/positions") as resp:
            if resp.status == 200:
                data = await resp.json()
                positions = []
                for pos in data:
                    positions.append(LivePosition(
                        symbol=pos["symbol"],
                        quantity=float(pos["qty"]),
                        side="long" if float(pos["qty"]) > 0 else "short",
                        entry_price=float(pos["avg_entry_price"]),
                        current_price=float(pos["current_price"]),
                        unrealized_pnl=float(pos["unrealized_pl"]),
                        market_value=float(pos["market_value"]),
                        broker=BrokerType.ALPACA,
                    ))
                return positions
            raise Exception(f"Failed to get positions: {await resp.text()}")

    async def get_quote(self, symbol: str) -> Dict:
        """Get real-time quote for a symbol."""
        session = await self._get_session()
        async with session.get(
            f"{self.DATA_URL}/v2/stocks/{symbol}/quotes/latest",
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                quote = data.get("quote", {})
                return {
                    "symbol": symbol,
                    "bid": float(quote.get("bp", 0)),
                    "ask": float(quote.get("ap", 0)),
                    "mid": (float(quote.get("bp", 0)) + float(quote.get("ap", 0))) / 2,
                    "timestamp": quote.get("t"),
                }
            return {"symbol": symbol, "bid": 0, "ask": 0, "mid": 0}

    async def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 100,
    ) -> List[Dict]:
        """Get historical bars."""
        session = await self._get_session()
        params = {
            "timeframe": timeframe,
            "limit": limit,
        }
        async with session.get(
            f"{self.DATA_URL}/v2/stocks/{symbol}/bars",
            params=params,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("bars", [])
            return []

    async def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,  # "buy" or "sell"
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> LiveOrder:
        """Submit an order."""
        session = await self._get_session()

        order_data = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }

        if limit_price:
            order_data["limit_price"] = str(limit_price)
        if stop_price:
            order_data["stop_price"] = str(stop_price)

        async with session.post(
            f"{self.base_url}/v2/orders",
            json=order_data,
        ) as resp:
            if resp.status in [200, 201]:
                data = await resp.json()
                return LiveOrder(
                    id=data["id"],
                    symbol=data["symbol"],
                    side=data["side"],
                    quantity=float(data["qty"]),
                    order_type=data["type"],
                    limit_price=float(data.get("limit_price") or 0),
                    stop_price=float(data.get("stop_price") or 0),
                    status=data["status"],
                    filled_quantity=float(data.get("filled_qty") or 0),
                    filled_price=float(data.get("filled_avg_price") or 0),
                    broker=BrokerType.ALPACA,
                    timestamp=datetime.now(),
                )
            error = await resp.text()
            raise Exception(f"Order failed: {error}")

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        session = await self._get_session()
        async with session.delete(f"{self.base_url}/v2/orders/{order_id}") as resp:
            return resp.status in [200, 204]

    async def close_position(self, symbol: str) -> bool:
        """Close all shares of a position."""
        session = await self._get_session()
        async with session.delete(f"{self.base_url}/v2/positions/{symbol}") as resp:
            return resp.status in [200, 204]


# =============================================================================
# BINANCE BROKER (Crypto Spot & Futures)
# =============================================================================

class BinanceBroker:
    """
    Binance Trading API Integration.

    Supports:
    - Spot trading (BTC, ETH, etc.)
    - USDT-M Perpetual Futures (Binance Global only, limited on Binance.US)
    - Real-time WebSocket data

    Documentation:
    - Binance Global: https://binance-docs.github.io/apidocs/
    - Binance.US: https://docs.binance.us/
    """

    # Binance Global URLs
    SPOT_BASE_URL = "https://api.binance.com"
    FUTURES_BASE_URL = "https://fapi.binance.com"
    TESTNET_SPOT_URL = "https://testnet.binance.vision"
    TESTNET_FUTURES_URL = "https://testnet.binancefuture.com"

    # Binance.US URLs (no futures, spot only)
    US_SPOT_URL = "https://api.binance.us"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        us_mode: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.us_mode = us_mode

        if us_mode:
            # Binance.US - spot only, no futures
            self.spot_url = self.US_SPOT_URL
            self.futures_url = None  # Binance.US doesn't have futures
            mode_str = "US"
        elif testnet:
            self.spot_url = self.TESTNET_SPOT_URL
            self.futures_url = self.TESTNET_FUTURES_URL
            mode_str = "TESTNET"
        else:
            self.spot_url = self.SPOT_BASE_URL
            self.futures_url = self.FUTURES_BASE_URL
            mode_str = "LIVE"

        self._session = None
        self._connected = False

        logger.info(f"BinanceBroker initialized: {mode_str} mode")

    def _sign(self, params: Dict) -> str:
        """Sign request parameters."""
        import hmac
        import hashlib

        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self.api_key}
            )
        return self._session

    async def connect(self) -> bool:
        """Connect and verify credentials."""
        try:
            session = await self._get_session()

            params = {"timestamp": int(datetime.now().timestamp() * 1000)}
            params["signature"] = self._sign(params)

            async with session.get(
                f"{self.spot_url}/api/v3/account",
                params=params,
            ) as resp:
                if resp.status == 200:
                    self._connected = True
                    logger.info("Binance connected successfully")
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Binance connection failed: {error}")
                    return False
        except Exception as e:
            logger.error(f"Binance connection error: {e}")
            return False

    async def disconnect(self):
        """Close connection."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False

    async def get_account(self) -> Dict:
        """Get account information."""
        session = await self._get_session()

        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        params["signature"] = self._sign(params)

        async with session.get(
            f"{self.spot_url}/api/v3/account",
            params=params,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            raise Exception(f"Failed to get account: {await resp.text()}")

    async def get_futures_account(self) -> Dict:
        """Get futures account information."""
        session = await self._get_session()

        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        params["signature"] = self._sign(params)

        async with session.get(
            f"{self.futures_url}/fapi/v2/account",
            params=params,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            raise Exception(f"Failed to get futures account: {await resp.text()}")

    async def get_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        session = await self._get_session()

        async with session.get(
            f"{self.spot_url}/api/v3/ticker/price",
            params={"symbol": symbol},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("price", 0))
            return 0

    async def get_futures_price(self, symbol: str) -> float:
        """Get current futures price."""
        session = await self._get_session()

        async with session.get(
            f"{self.futures_url}/fapi/v1/ticker/price",
            params={"symbol": symbol},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return float(data.get("price", 0))
            return 0

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 100,
    ) -> List[Dict]:
        """Get historical klines/candlesticks."""
        session = await self._get_session()

        async with session.get(
            f"{self.spot_url}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [
                    {
                        "open_time": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    }
                    for k in data
                ]
            return []

    async def get_positions(self) -> List[LivePosition]:
        """Get all open positions (futures)."""
        session = await self._get_session()

        params = {"timestamp": int(datetime.now().timestamp() * 1000)}
        params["signature"] = self._sign(params)

        async with session.get(
            f"{self.futures_url}/fapi/v2/positionRisk",
            params=params,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                positions = []
                for pos in data:
                    qty = float(pos.get("positionAmt", 0))
                    if qty != 0:
                        positions.append(LivePosition(
                            symbol=pos["symbol"],
                            quantity=abs(qty),
                            side="long" if qty > 0 else "short",
                            entry_price=float(pos.get("entryPrice", 0)),
                            current_price=float(pos.get("markPrice", 0)),
                            unrealized_pnl=float(pos.get("unRealizedProfit", 0)),
                            market_value=abs(qty) * float(pos.get("markPrice", 0)),
                            broker=BrokerType.BINANCE,
                        ))
                return positions
            return []

    async def submit_spot_order(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
    ) -> LiveOrder:
        """Submit a spot order."""
        session = await self._get_session()

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": str(quantity),
            "timestamp": int(datetime.now().timestamp() * 1000),
        }

        if price and order_type == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        params["signature"] = self._sign(params)

        async with session.post(
            f"{self.spot_url}/api/v3/order",
            params=params,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return LiveOrder(
                    id=str(data["orderId"]),
                    symbol=data["symbol"],
                    side=data["side"].lower(),
                    quantity=float(data["origQty"]),
                    order_type=data["type"].lower(),
                    limit_price=float(data.get("price") or 0),
                    stop_price=0,
                    status=data["status"].lower(),
                    filled_quantity=float(data.get("executedQty") or 0),
                    filled_price=float(data.get("price") or 0),
                    broker=BrokerType.BINANCE,
                    timestamp=datetime.now(),
                )
            error = await resp.text()
            raise Exception(f"Order failed: {error}")

    async def submit_futures_order(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> LiveOrder:
        """Submit a futures order."""
        session = await self._get_session()

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": str(quantity),
            "timestamp": int(datetime.now().timestamp() * 1000),
        }

        if reduce_only:
            params["reduceOnly"] = "true"

        if price and order_type == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        params["signature"] = self._sign(params)

        async with session.post(
            f"{self.futures_url}/fapi/v1/order",
            params=params,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return LiveOrder(
                    id=str(data["orderId"]),
                    symbol=data["symbol"],
                    side=data["side"].lower(),
                    quantity=float(data["origQty"]),
                    order_type=data["type"].lower(),
                    limit_price=float(data.get("price") or 0),
                    stop_price=float(data.get("stopPrice") or 0),
                    status=data["status"].lower(),
                    filled_quantity=float(data.get("executedQty") or 0),
                    filled_price=float(data.get("avgPrice") or 0),
                    broker=BrokerType.BINANCE,
                    timestamp=datetime.now(),
                )
            error = await resp.text()
            raise Exception(f"Futures order failed: {error}")

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a futures symbol."""
        session = await self._get_session()

        params = {
            "symbol": symbol,
            "leverage": leverage,
            "timestamp": int(datetime.now().timestamp() * 1000),
        }
        params["signature"] = self._sign(params)

        async with session.post(
            f"{self.futures_url}/fapi/v1/leverage",
            params=params,
        ) as resp:
            return resp.status == 200

    async def close_futures_position(self, symbol: str) -> bool:
        """Close a futures position."""
        positions = await self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                side = "SELL" if pos.side == "long" else "BUY"
                try:
                    await self.submit_futures_order(
                        symbol=symbol,
                        side=side,
                        quantity=pos.quantity,
                        reduce_only=True,
                    )
                    return True
                except Exception as e:
                    logger.error(f"Failed to close position: {e}")
                    return False
        return False


# =============================================================================
# UNIFIED BROKER MANAGER
# =============================================================================

class BrokerManager:
    """
    Unified broker manager for multi-exchange trading.

    Manages:
    - API credentials (stored securely)
    - Broker connections
    - Order routing
    - Position aggregation
    """

    def __init__(self):
        self.alpaca: Optional[AlpacaBroker] = None
        self.binance: Optional[BinanceBroker] = None
        self.credentials: Dict[BrokerType, BrokerCredentials] = {}
        self.is_live = False

        logger.info("BrokerManager initialized")

    def set_credentials(
        self,
        broker: BrokerType,
        api_key: str,
        api_secret: str,
        is_paper: bool = True,
        additional_config: Optional[Dict[str, Any]] = None,
    ):
        """Set credentials for a broker."""
        self.credentials[broker] = BrokerCredentials(
            broker=broker,
            api_key=api_key,
            api_secret=api_secret,
            is_paper=is_paper,
            additional_config=additional_config or {},
        )
        # Debug: show masked key values
        key_masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
        secret_masked = f"{api_secret[:4]}...{api_secret[-4:]}" if len(api_secret) > 8 else "***"
        logger.info(f"Credentials set for {broker.value}: {'PAPER' if is_paper else 'LIVE'}")
        print(f"[BROKER] {broker.value} key={key_masked}, secret={secret_masked}")

    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all configured brokers."""
        results = {}

        if BrokerType.ALPACA in self.credentials:
            creds = self.credentials[BrokerType.ALPACA]
            self.alpaca = AlpacaBroker(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                paper=creds.is_paper,
            )
            results["alpaca"] = await self.alpaca.connect()

        if BrokerType.BINANCE in self.credentials:
            creds = self.credentials[BrokerType.BINANCE]
            us_mode = creds.additional_config.get("us_mode", False)
            self.binance = BinanceBroker(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                testnet=creds.is_paper,
                us_mode=us_mode,
            )
            results["binance"] = await self.binance.connect()

        self.is_live = any(
            not creds.is_paper for creds in self.credentials.values()
        )

        return results

    async def disconnect_all(self):
        """Disconnect from all brokers."""
        if self.alpaca:
            await self.alpaca.disconnect()
        if self.binance:
            await self.binance.disconnect()

    async def get_all_positions(self) -> List[LivePosition]:
        """Get positions from all connected brokers."""
        positions = []

        if self.alpaca and self.alpaca._connected:
            positions.extend(await self.alpaca.get_positions())

        if self.binance and self.binance._connected:
            positions.extend(await self.binance.get_positions())

        return positions

    async def get_live_price(self, symbol: str, asset_type: str = "stock") -> float:
        """Get live price for a symbol."""
        if asset_type == "stock" and self.alpaca and self.alpaca._connected:
            quote = await self.alpaca.get_quote(symbol)
            return quote.get("mid", 0)
        elif asset_type == "crypto" and self.binance and self.binance._connected:
            # Convert symbol format (e.g., "BTC" -> "BTCUSDT")
            binance_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
            return await self.binance.get_price(binance_symbol)
        elif asset_type == "crypto_futures" and self.binance and self.binance._connected:
            binance_symbol = f"{symbol.replace('-PERP', '')}USDT"
            return await self.binance.get_futures_price(binance_symbol)
        return 0

    async def submit_stock_order(
        self,
        symbol: str,
        quantity: float,
        side: str,
        order_type: str = "market",
    ) -> Optional[LiveOrder]:
        """Submit a stock order via Alpaca."""
        if not self.alpaca or not self.alpaca._connected:
            raise Exception("Alpaca not connected")

        return await self.alpaca.submit_order(
            symbol=symbol,
            qty=quantity,
            side=side,
            order_type=order_type,
        )

    async def submit_crypto_order(
        self,
        symbol: str,
        quantity: float,
        side: str,
        is_futures: bool = False,
    ) -> Optional[LiveOrder]:
        """Submit a crypto order via Binance."""
        if not self.binance or not self.binance._connected:
            raise Exception("Binance not connected")

        binance_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        if is_futures:
            return await self.binance.submit_futures_order(
                symbol=binance_symbol,
                side=side.upper(),
                quantity=quantity,
            )
        else:
            return await self.binance.submit_spot_order(
                symbol=binance_symbol,
                side=side.upper(),
                quantity=quantity,
            )

    def get_status(self) -> Dict:
        """Get broker connection status."""
        return {
            "alpaca": {
                "configured": BrokerType.ALPACA in self.credentials,
                "connected": self.alpaca._connected if self.alpaca else False,
                "mode": "paper" if self.credentials.get(BrokerType.ALPACA, BrokerCredentials(BrokerType.ALPACA, "", "", True)).is_paper else "live",
            },
            "binance": {
                "configured": BrokerType.BINANCE in self.credentials,
                "connected": self.binance._connected if self.binance else False,
                "mode": "testnet" if self.credentials.get(BrokerType.BINANCE, BrokerCredentials(BrokerType.BINANCE, "", "", True)).is_paper else "live",
            },
            "is_live_trading": self.is_live,
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_broker_manager: Optional[BrokerManager] = None


def get_broker_manager() -> BrokerManager:
    """Get or create the broker manager singleton."""
    global _broker_manager
    if _broker_manager is None:
        _broker_manager = BrokerManager()
    return _broker_manager


async def auto_initialize_brokers() -> Dict[str, Any]:
    """
    Auto-initialize brokers from environment config.

    Called on app startup if AUTO_CONNECT_BROKERS=true.
    Uses paper/testnet mode by default for safety.
    """
    from ..config import get_settings

    settings = get_settings()
    manager = get_broker_manager()
    activity_logger = get_activity_logger()
    results = {"alpaca": None, "binance": None, "errors": []}

    # Setup Alpaca if keys are configured
    if settings.has_alpaca_keys:
        try:
            manager.set_credentials(
                broker=BrokerType.ALPACA,
                api_key=settings.alpaca_api_key,
                api_secret=settings.alpaca_api_secret,
                is_paper=settings.alpaca_paper_mode,
            )
            logger.info(f"Alpaca credentials configured (paper={settings.alpaca_paper_mode})")
            results["alpaca"] = "configured"
        except Exception as e:
            logger.error(f"Failed to configure Alpaca: {e}")
            results["errors"].append(f"Alpaca config error: {e}")

    # Setup Binance if keys are configured
    if settings.has_binance_keys:
        try:
            us_mode = getattr(settings, 'binance_us_mode', True)  # Default to US mode
            manager.set_credentials(
                broker=BrokerType.BINANCE,
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
                is_paper=settings.binance_testnet_mode,
                additional_config={"us_mode": us_mode},
            )
            mode_str = "US" if us_mode else ("testnet" if settings.binance_testnet_mode else "global")
            logger.info(f"Binance credentials configured ({mode_str})")
            results["binance"] = "configured"
        except Exception as e:
            logger.error(f"Failed to configure Binance: {e}")
            results["errors"].append(f"Binance config error: {e}")

    # Auto-connect if configured
    if settings.auto_connect_brokers and manager.credentials:
        try:
            connect_results = await manager.connect_all()
            results["connection"] = connect_results
            logger.info(f"Broker auto-connect results: {connect_results}")

            # Log broker connection results to activity logger
            for broker_name, success in connect_results.items():
                await activity_logger.log_broker(
                    subtype=EventSubtype.CONNECT if success else EventSubtype.AUTH_FAILURE,
                    broker=broker_name,
                    message=f"{broker_name.capitalize()} connection {'successful' if success else 'failed'}",
                    success=success,
                    details={
                        "mode": "paper" if broker_name == "alpaca" and settings.alpaca_paper_mode else
                               "testnet" if broker_name == "binance" and settings.binance_testnet_mode else "live",
                        "us_mode": True if broker_name == "binance" and getattr(settings, 'binance_us_mode', True) else None,
                    }
                )

        except Exception as e:
            logger.error(f"Broker auto-connect failed: {e}")
            results["errors"].append(f"Auto-connect error: {e}")

            # Log connection error
            await activity_logger.log_error(
                subtype=EventSubtype.EXCEPTION,
                message=f"Broker auto-connect failed: {str(e)[:200]}",
                details={"error": str(e)}
            )

    return results
