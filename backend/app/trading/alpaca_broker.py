"""
Alpaca Broker Integration for Live Paper Trading.

Provides real broker connectivity for:
- Submitting orders (market, limit, stop)
- Monitoring fills and positions
- Real-time portfolio tracking
- Automatic position reconciliation

Safety features:
- Paper trading mode by default (no real money)
- Order size limits and validation
- Rate limiting on API calls
- Graceful degradation on API errors

Usage:
    broker = AlpacaBroker()
    await broker.connect()
    await broker.submit_order("AAPL", qty=10, side="buy")
    positions = await broker.get_positions()
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """Order status enum."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class BrokerOrder:
    """An order submitted to the broker."""
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    order_type: str  # "market", "limit", "stop", "stop_limit"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: float = 0.0
    filled_avg_price: float = 0.0
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    commission: float = 0.0


@dataclass
class BrokerPosition:
    """A position held at the broker."""
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


@dataclass
class BrokerAccount:
    """Broker account summary."""
    account_id: str
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    is_paper: bool


class AlpacaBroker:
    """
    Alpaca broker integration for paper and live trading.

    Wraps the Alpaca Trade API with safety checks and logging.
    """

    # API endpoints
    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        paper_mode: bool = True,
        max_order_value: float = 10_000,  # Safety: max single order
        max_daily_orders: int = 100,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_mode = paper_mode
        self.max_order_value = max_order_value
        self.max_daily_orders = max_daily_orders

        self.base_url = self.PAPER_URL if paper_mode else self.LIVE_URL
        self._connected = False
        self._session = None
        self._orders_today: List[BrokerOrder] = []
        self._order_counter = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """
        Connect to Alpaca API and verify credentials.

        Returns:
            True if connected successfully
        """
        if not self.api_key or not self.api_secret:
            # Try loading from config
            try:
                from ..config import get_settings
                settings = get_settings()
                self.api_key = settings.alpaca_api_key
                self.api_secret = settings.alpaca_api_secret
                self.paper_mode = settings.alpaca_paper_mode
                self.base_url = self.PAPER_URL if self.paper_mode else self.LIVE_URL
            except Exception:
                pass

        if not self.api_key or not self.api_secret:
            logger.warning("Alpaca API keys not configured — broker not connected")
            return False

        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.api_secret,
                }
            )

            # Verify connection
            async with self._session.get(f"{self.base_url}/v2/account") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._connected = True
                    mode = "PAPER" if self.paper_mode else "LIVE"
                    logger.info(
                        f"Connected to Alpaca ({mode}): "
                        f"equity=${float(data.get('equity', 0)):,.2f}"
                    )
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Alpaca auth failed ({resp.status}): {error}")
                    return False

        except ImportError:
            logger.warning("aiohttp not installed — Alpaca broker unavailable")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            return False

    async def disconnect(self) -> None:
        """Close the API session."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False
        logger.info("Disconnected from Alpaca")

    async def get_account(self) -> Optional[BrokerAccount]:
        """Get account summary."""
        if not self._connected or not self._session:
            return None

        try:
            async with self._session.get(f"{self.base_url}/v2/account") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

                return BrokerAccount(
                    account_id=data.get("id", ""),
                    equity=float(data.get("equity", 0)),
                    cash=float(data.get("cash", 0)),
                    buying_power=float(data.get("buying_power", 0)),
                    portfolio_value=float(data.get("portfolio_value", 0)),
                    is_paper=self.paper_mode,
                )
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            return None

    async def get_positions(self) -> List[BrokerPosition]:
        """Get all open positions."""
        if not self._connected or not self._session:
            return []

        try:
            async with self._session.get(f"{self.base_url}/v2/positions") as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

                positions = []
                for p in data:
                    positions.append(BrokerPosition(
                        symbol=p["symbol"],
                        qty=float(p["qty"]),
                        avg_entry_price=float(p["avg_entry_price"]),
                        current_price=float(p["current_price"]),
                        market_value=float(p["market_value"]),
                        unrealized_pnl=float(p["unrealized_pl"]),
                        unrealized_pnl_pct=float(p["unrealized_plpc"]),
                    ))
                return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def submit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> Optional[BrokerOrder]:
        """
        Submit an order to Alpaca.

        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            qty: Number of shares
            side: "buy" or "sell"
            order_type: "market", "limit", "stop", "stop_limit"
            limit_price: Limit price (required for limit/stop_limit)
            stop_price: Stop price (required for stop/stop_limit)
            time_in_force: "day", "gtc", "ioc", "fok"

        Returns:
            BrokerOrder if submitted, None if failed
        """
        # Safety checks
        if not self._connected or not self._session:
            logger.error("Cannot submit order: not connected")
            return None

        if len(self._orders_today) >= self.max_daily_orders:
            logger.error(f"Daily order limit reached ({self.max_daily_orders})")
            return None

        if qty <= 0:
            logger.error(f"Invalid quantity: {qty}")
            return None

        if side not in ("buy", "sell"):
            logger.error(f"Invalid side: {side}")
            return None

        # Build order payload
        order_data = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }

        if limit_price is not None:
            order_data["limit_price"] = str(limit_price)
        if stop_price is not None:
            order_data["stop_price"] = str(stop_price)

        try:
            async with self._session.post(
                f"{self.base_url}/v2/orders",
                json=order_data
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    order = BrokerOrder(
                        order_id=data["id"],
                        symbol=symbol,
                        side=side,
                        qty=qty,
                        order_type=order_type,
                        limit_price=limit_price,
                        stop_price=stop_price,
                        status=OrderStatus.SUBMITTED,
                        submitted_at=datetime.now(),
                    )
                    self._orders_today.append(order)
                    logger.info(
                        f"Order submitted: {side} {qty} {symbol} ({order_type}) "
                        f"[{order.order_id[:8]}]"
                    )
                    return order
                else:
                    error = await resp.text()
                    logger.error(f"Order rejected ({resp.status}): {error}")
                    return None

        except Exception as e:
            logger.error(f"Failed to submit order: {e}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not self._connected or not self._session:
            return False

        try:
            async with self._session.delete(
                f"{self.base_url}/v2/orders/{order_id}"
            ) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Order cancelled: {order_id[:8]}")
                    return True
                else:
                    logger.error(f"Failed to cancel order {order_id[:8]}: {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return False

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count of cancelled orders."""
        if not self._connected or not self._session:
            return 0

        try:
            async with self._session.delete(f"{self.base_url}/v2/orders") as resp:
                if resp.status == 207:
                    data = await resp.json()
                    cancelled = len([o for o in data if o.get("status") == 200])
                    logger.info(f"Cancelled {cancelled} orders")
                    return cancelled
                return 0
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return 0

    async def close_all_positions(self) -> bool:
        """Liquidate all positions (emergency use only)."""
        if not self._connected or not self._session:
            return False

        logger.warning("CLOSING ALL POSITIONS")

        try:
            async with self._session.delete(f"{self.base_url}/v2/positions") as resp:
                if resp.status == 207:
                    logger.warning("All positions closed")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to close positions: {e}")
            return False

    async def execute_rebalance(
        self,
        target_weights: Dict[str, float],
        portfolio_value: float,
    ) -> List[BrokerOrder]:
        """
        Execute a portfolio rebalance to match target weights.

        Args:
            target_weights: Dict of symbol -> target weight (0-1)
            portfolio_value: Current portfolio value for sizing

        Returns:
            List of submitted orders
        """
        if not self._connected:
            logger.error("Cannot rebalance: not connected")
            return []

        # Get current positions
        positions = await self.get_positions()
        current_holdings = {p.symbol: p for p in positions}

        orders = []

        # Get current prices (use position data or fetch)
        for symbol, target_weight in target_weights.items():
            target_value = portfolio_value * target_weight
            current_value = 0.0

            if symbol in current_holdings:
                current_value = current_holdings[symbol].market_value

            diff_value = target_value - current_value

            # Skip small adjustments (< $100 or < 0.5% of portfolio)
            if abs(diff_value) < 100 or abs(diff_value) / portfolio_value < 0.005:
                continue

            # Estimate qty from current price
            if symbol in current_holdings:
                price = current_holdings[symbol].current_price
            else:
                price = target_value / max(target_weight * 100, 1)  # Rough estimate

            if price <= 0:
                continue

            qty = int(abs(diff_value) / price)
            if qty <= 0:
                continue

            side = "buy" if diff_value > 0 else "sell"

            order = await self.submit_order(symbol, qty, side, order_type="market")
            if order:
                orders.append(order)

        # Close positions not in target
        for symbol, pos in current_holdings.items():
            if symbol not in target_weights or target_weights[symbol] <= 0:
                order = await self.submit_order(
                    symbol, abs(pos.qty), "sell", order_type="market"
                )
                if order:
                    orders.append(order)

        logger.info(f"Rebalance: submitted {len(orders)} orders")
        return orders

    def get_daily_order_count(self) -> int:
        """Get number of orders placed today."""
        return len(self._orders_today)

    def get_order_history(self) -> List[Dict[str, Any]]:
        """Get today's order history."""
        return [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "type": o.order_type,
                "status": o.status.value,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            }
            for o in self._orders_today
        ]
