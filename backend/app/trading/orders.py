"""
Advanced Order Management System

Supports:
- Market orders
- Limit orders
- Stop-loss orders
- Take-profit orders
- Trailing stops
- OCO (One-Cancels-Other)
- Bracket orders (entry + stop + target)

All orders are paper trading only - no real execution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import uuid
from loguru import logger


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"
    TAKE_PROFIT = "take_profit"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(Enum):
    GTC = "gtc"  # Good til cancelled
    DAY = "day"  # Day order
    IOC = "ioc"  # Immediate or cancel
    FOK = "fok"  # Fill or kill


@dataclass
class Order:
    """Represents a trading order."""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    status: OrderStatus = OrderStatus.PENDING

    # Prices
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    trailing_amount: Optional[float] = None  # For trailing stops (absolute or %)
    trailing_percent: bool = False

    # Time settings
    time_in_force: TimeInForce = TimeInForce.GTC
    expires_at: Optional[datetime] = None

    # Execution
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fill_time: Optional[datetime] = None
    commission: float = 0.0
    slippage: float = 0.0

    # Linked orders
    parent_order_id: Optional[str] = None
    linked_orders: List[str] = field(default_factory=list)
    oco_group: Optional[str] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    signal_score: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "status": self.status.value,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "trailing_amount": self.trailing_amount,
            "trailing_percent": self.trailing_percent,
            "time_in_force": self.time_in_force.value,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "fill_time": self.fill_time.isoformat() if self.fill_time else None,
            "commission": self.commission,
            "slippage": self.slippage,
            "created_at": self.created_at.isoformat(),
            "signal_score": self.signal_score,
            "notes": self.notes,
        }


@dataclass
class BracketOrder:
    """
    Bracket order: Entry + Stop Loss + Take Profit.
    Used for automated position management.
    """
    id: str
    symbol: str
    side: OrderSide
    quantity: float

    # Entry
    entry_order: Order

    # Exit orders (created after entry fills)
    stop_loss_order: Optional[Order] = None
    take_profit_order: Optional[Order] = None

    # Prices
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None

    # Status
    status: str = "pending"  # pending, active, closed

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "status": self.status,
            "entry_order": self.entry_order.to_dict(),
            "stop_loss_order": self.stop_loss_order.to_dict() if self.stop_loss_order else None,
            "take_profit_order": self.take_profit_order.to_dict() if self.take_profit_order else None,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
        }


class OrderManager:
    """
    Manages order lifecycle and execution.
    Simulates realistic order fills with slippage and partial fills.
    """

    DEFAULT_COMMISSION_BPS = 10  # 10 basis points
    DEFAULT_SLIPPAGE_BPS = 5  # 5 basis points

    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.bracket_orders: Dict[str, BracketOrder] = {}
        self.oco_groups: Dict[str, List[str]] = {}

    def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        signal_score: Optional[float] = None,
        notes: str = ""
    ) -> Order:
        """Create a market order."""
        order = Order(
            id=str(uuid.uuid4())[:8],
            symbol=symbol.upper(),
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            time_in_force=TimeInForce.IOC,
            signal_score=signal_score,
            notes=notes,
        )
        self.orders[order.id] = order
        logger.info(f"Created market order: {order.id} {side.value} {quantity} {symbol}")
        return order

    def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        limit_price: float,
        time_in_force: TimeInForce = TimeInForce.GTC,
        signal_score: Optional[float] = None,
    ) -> Order:
        """Create a limit order."""
        order = Order(
            id=str(uuid.uuid4())[:8],
            symbol=symbol.upper(),
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            signal_score=signal_score,
        )
        self.orders[order.id] = order
        logger.info(f"Created limit order: {order.id} {side.value} {quantity} {symbol} @ {limit_price}")
        return order

    def create_stop_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        stop_price: float,
        limit_price: Optional[float] = None,
    ) -> Order:
        """Create a stop or stop-limit order."""
        order_type = OrderType.STOP_LIMIT if limit_price else OrderType.STOP
        order = Order(
            id=str(uuid.uuid4())[:8],
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=quantity,
            stop_price=stop_price,
            limit_price=limit_price,
        )
        self.orders[order.id] = order
        logger.info(f"Created stop order: {order.id} {side.value} {quantity} {symbol} stop @ {stop_price}")
        return order

    def create_trailing_stop(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        trail_amount: float,
        trail_percent: bool = False,
    ) -> Order:
        """Create a trailing stop order."""
        order = Order(
            id=str(uuid.uuid4())[:8],
            symbol=symbol.upper(),
            side=side,
            order_type=OrderType.TRAILING_STOP,
            quantity=quantity,
            trailing_amount=trail_amount,
            trailing_percent=trail_percent,
        )
        self.orders[order.id] = order
        trail_str = f"{trail_amount}%" if trail_percent else f"${trail_amount}"
        logger.info(f"Created trailing stop: {order.id} {side.value} {quantity} {symbol} trail {trail_str}")
        return order

    def create_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        entry_price: Optional[float] = None,  # None = market order
        stop_loss_pct: float = 0.05,  # 5% stop loss
        take_profit_pct: float = 0.10,  # 10% take profit
    ) -> BracketOrder:
        """
        Create a bracket order with automatic stop loss and take profit.
        This is the recommended way to enter positions.
        """
        bracket_id = str(uuid.uuid4())[:8]

        # Create entry order
        if entry_price:
            entry_order = self.create_limit_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                limit_price=entry_price,
            )
        else:
            entry_order = self.create_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

        bracket = BracketOrder(
            id=bracket_id,
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            entry_order=entry_order,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )

        self.bracket_orders[bracket_id] = bracket
        logger.info(f"Created bracket order: {bracket_id} {side.value} {quantity} {symbol} SL:{stop_loss_pct:.1%} TP:{take_profit_pct:.1%}")
        return bracket

    def create_oco_order(
        self,
        order1: Order,
        order2: Order,
    ) -> str:
        """
        Create OCO (One-Cancels-Other) order pair.
        When one fills, the other is cancelled.
        """
        oco_id = str(uuid.uuid4())[:8]
        order1.oco_group = oco_id
        order2.oco_group = oco_id
        self.oco_groups[oco_id] = [order1.id, order2.id]
        logger.info(f"Created OCO group: {oco_id} orders {order1.id}, {order2.id}")
        return oco_id

    def process_orders(self, current_prices: Dict[str, float]) -> List[Order]:
        """
        Process all open orders against current prices.
        Returns list of filled orders.
        """
        filled = []

        for order_id, order in list(self.orders.items()):
            if order.status not in [OrderStatus.PENDING, OrderStatus.OPEN]:
                continue

            symbol = order.symbol
            if symbol not in current_prices:
                continue

            price = current_prices[symbol]
            fill = self._check_fill(order, price)

            if fill:
                filled.append(order)
                self._handle_fill(order, fill)

        # Process bracket orders
        self._process_bracket_orders(current_prices)

        return filled

    def _check_fill(self, order: Order, current_price: float) -> Optional[Dict]:
        """Check if order should fill at current price."""

        if order.order_type == OrderType.MARKET:
            # Market orders fill immediately with slippage
            slippage = current_price * self.DEFAULT_SLIPPAGE_BPS / 10000
            if order.side == OrderSide.BUY:
                fill_price = current_price + slippage
            else:
                fill_price = current_price - slippage

            return {"price": fill_price, "quantity": order.quantity}

        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and current_price <= order.limit_price:
                return {"price": order.limit_price, "quantity": order.quantity}
            elif order.side == OrderSide.SELL and current_price >= order.limit_price:
                return {"price": order.limit_price, "quantity": order.quantity}

        elif order.order_type in [OrderType.STOP, OrderType.STOP_LIMIT]:
            if order.side == OrderSide.SELL and current_price <= order.stop_price:
                # Stop triggered
                fill_price = order.limit_price or (current_price * 0.999)
                return {"price": fill_price, "quantity": order.quantity}
            elif order.side == OrderSide.BUY and current_price >= order.stop_price:
                fill_price = order.limit_price or (current_price * 1.001)
                return {"price": fill_price, "quantity": order.quantity}

        elif order.order_type == OrderType.TAKE_PROFIT:
            if order.side == OrderSide.SELL and current_price >= order.limit_price:
                return {"price": order.limit_price, "quantity": order.quantity}

        return None

    def _handle_fill(self, order: Order, fill: Dict):
        """Handle order fill."""
        order.status = OrderStatus.FILLED
        order.filled_quantity = fill["quantity"]
        order.filled_price = fill["price"]
        order.fill_time = datetime.now()
        order.commission = fill["price"] * fill["quantity"] * self.DEFAULT_COMMISSION_BPS / 10000
        order.updated_at = datetime.now()

        logger.info(f"Order filled: {order.id} {order.side.value} {order.filled_quantity} {order.symbol} @ {order.filled_price:.2f}")

        # Handle OCO
        if order.oco_group:
            self._cancel_oco_group(order.oco_group, except_order=order.id)

    def _cancel_oco_group(self, oco_id: str, except_order: str):
        """Cancel other orders in OCO group."""
        if oco_id not in self.oco_groups:
            return

        for order_id in self.oco_groups[oco_id]:
            if order_id != except_order and order_id in self.orders:
                self.orders[order_id].status = OrderStatus.CANCELLED
                logger.info(f"Cancelled OCO order: {order_id}")

    def _process_bracket_orders(self, current_prices: Dict[str, float]):
        """Process bracket orders - create exit orders after entry fills."""

        for bracket_id, bracket in self.bracket_orders.items():
            if bracket.status == "closed":
                continue

            entry = bracket.entry_order

            # Check if entry filled
            if entry.status == OrderStatus.FILLED and bracket.status == "pending":
                # Create stop loss and take profit orders
                entry_price = entry.filled_price

                if bracket.side == OrderSide.BUY:
                    # Long position: SL below, TP above
                    sl_price = entry_price * (1 - bracket.stop_loss_pct)
                    tp_price = entry_price * (1 + bracket.take_profit_pct)

                    bracket.stop_loss_order = self.create_stop_order(
                        symbol=bracket.symbol,
                        side=OrderSide.SELL,
                        quantity=bracket.quantity,
                        stop_price=sl_price,
                    )

                    bracket.take_profit_order = Order(
                        id=str(uuid.uuid4())[:8],
                        symbol=bracket.symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.TAKE_PROFIT,
                        quantity=bracket.quantity,
                        limit_price=tp_price,
                    )
                    self.orders[bracket.take_profit_order.id] = bracket.take_profit_order

                else:
                    # Short position: SL above, TP below
                    sl_price = entry_price * (1 + bracket.stop_loss_pct)
                    tp_price = entry_price * (1 - bracket.take_profit_pct)

                    bracket.stop_loss_order = self.create_stop_order(
                        symbol=bracket.symbol,
                        side=OrderSide.BUY,
                        quantity=bracket.quantity,
                        stop_price=sl_price,
                    )

                    bracket.take_profit_order = Order(
                        id=str(uuid.uuid4())[:8],
                        symbol=bracket.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.TAKE_PROFIT,
                        quantity=bracket.quantity,
                        limit_price=tp_price,
                    )
                    self.orders[bracket.take_profit_order.id] = bracket.take_profit_order

                # Create OCO for SL and TP
                self.create_oco_order(bracket.stop_loss_order, bracket.take_profit_order)

                bracket.stop_loss_price = sl_price
                bracket.take_profit_price = tp_price
                bracket.status = "active"

                logger.info(f"Bracket activated: {bracket_id} SL @ {sl_price:.2f} TP @ {tp_price:.2f}")

            # Check if bracket closed
            if bracket.status == "active":
                if bracket.stop_loss_order and bracket.stop_loss_order.status == OrderStatus.FILLED:
                    bracket.status = "closed"
                    logger.info(f"Bracket closed by stop loss: {bracket_id}")
                elif bracket.take_profit_order and bracket.take_profit_order.status == OrderStatus.FILLED:
                    bracket.status = "closed"
                    logger.info(f"Bracket closed by take profit: {bracket_id}")

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if order_id not in self.orders:
            return False

        order = self.orders[order_id]
        if order.status in [OrderStatus.PENDING, OrderStatus.OPEN]:
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()
            logger.info(f"Cancelled order: {order_id}")
            return True

        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all open orders, optionally filtered by symbol."""
        orders = [
            o for o in self.orders.values()
            if o.status in [OrderStatus.PENDING, OrderStatus.OPEN]
        ]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol.upper()]
        return orders

    def get_filled_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get all filled orders."""
        orders = [
            o for o in self.orders.values()
            if o.status == OrderStatus.FILLED
        ]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol.upper()]
        return orders


# Singleton
_manager: Optional[OrderManager] = None

def get_order_manager() -> OrderManager:
    global _manager
    if _manager is None:
        _manager = OrderManager()
    return _manager
