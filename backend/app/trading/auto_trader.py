"""
Automated Trading System

This is the core automation engine that:
1. Generates signals from the multi-factor engine
2. Translates signals into orders
3. Manages position sizing and risk
4. Executes rebalancing
5. Monitors and adjusts positions

Designed to teach hedge fund-level systematic trading.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from enum import Enum
import numpy as np
import pandas as pd
from loguru import logger

from ..signals.engine import SignalEngine, PortfolioSignals, StockSignal, get_signal_engine
from .orders import OrderManager, Order, OrderSide, OrderType, BracketOrder, get_order_manager
from ..config import get_settings


class RebalanceFrequency(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class Position:
    """Current position in a stock."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    weight: float
    entry_date: datetime
    last_signal: Optional[StockSignal] = None

    # Risk management
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 2),
            "current_price": round(self.current_price, 2),
            "market_value": round(self.market_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 4),
            "weight": round(self.weight, 4),
            "entry_date": self.entry_date.isoformat(),
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
        }


@dataclass
class Portfolio:
    """Portfolio state."""
    cash: float
    positions: Dict[str, Position]
    total_value: float
    total_pnl: float
    total_pnl_pct: float

    # Performance tracking
    daily_returns: List[float] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "cash": round(self.cash, 2),
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "total_value": round(self.total_value, 2),
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(self.total_pnl_pct, 4),
            "n_positions": len(self.positions),
        }


@dataclass
class TradeLog:
    """Record of a trade."""
    id: str
    timestamp: datetime
    symbol: str
    side: str
    quantity: float
    price: float
    value: float
    commission: float
    signal_score: Optional[float]
    order_type: str
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": round(self.price, 2),
            "value": round(self.value, 2),
            "commission": round(self.commission, 2),
            "signal_score": round(self.signal_score, 4) if self.signal_score else None,
            "order_type": self.order_type,
            "notes": self.notes,
        }


class AutoTrader:
    """
    Automated trading system implementing systematic strategies.

    Key features:
    - Signal-based position management
    - Risk-controlled position sizing
    - Automated rebalancing
    - Stop-loss and take-profit management
    - Performance tracking
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        max_positions: int = 20,
        max_position_weight: float = 0.10,
        rebalance_frequency: RebalanceFrequency = RebalanceFrequency.WEEKLY,
        stop_loss_pct: float = 0.08,
        take_profit_pct: float = 0.20,
        use_trailing_stops: bool = True,
        trailing_stop_pct: float = 0.10,
    ):
        self.settings = get_settings()
        self.signal_engine = get_signal_engine()
        self.order_manager = get_order_manager()

        # Portfolio settings
        self.initial_cash = initial_cash
        self.max_positions = max_positions
        self.max_position_weight = max_position_weight
        self.rebalance_frequency = rebalance_frequency

        # Risk settings
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.use_trailing_stops = use_trailing_stops
        self.trailing_stop_pct = trailing_stop_pct

        # State
        self.portfolio = Portfolio(
            cash=initial_cash,
            positions={},
            total_value=initial_cash,
            total_pnl=0,
            total_pnl_pct=0,
        )
        self.trade_history: List[TradeLog] = []
        self.last_signals: Optional[PortfolioSignals] = None
        self.last_rebalance: Optional[datetime] = None

        # Automation state
        self.auto_trading_enabled = False
        self.paper_mode = True  # Always true - no real trading

    def enable_auto_trading(self):
        """Enable automated trading."""
        self.auto_trading_enabled = True
        logger.info("Auto-trading ENABLED")

    def disable_auto_trading(self):
        """Disable automated trading."""
        self.auto_trading_enabled = False
        logger.info("Auto-trading DISABLED")

    def generate_signals(self, prices: pd.DataFrame) -> PortfolioSignals:
        """Generate signals for the universe."""
        self.last_signals = self.signal_engine.generate_signals(prices)
        return self.last_signals

    def update_prices(self, current_prices: Dict[str, float]):
        """Update portfolio with current prices."""
        total_position_value = 0

        for symbol, position in self.portfolio.positions.items():
            if symbol in current_prices:
                position.current_price = current_prices[symbol]
                position.market_value = position.quantity * position.current_price
                position.unrealized_pnl = position.market_value - (position.quantity * position.avg_cost)
                position.unrealized_pnl_pct = position.unrealized_pnl / (position.quantity * position.avg_cost)
                total_position_value += position.market_value

        # Update portfolio totals
        self.portfolio.total_value = self.portfolio.cash + total_position_value
        self.portfolio.total_pnl = self.portfolio.total_value - self.initial_cash
        self.portfolio.total_pnl_pct = self.portfolio.total_pnl / self.initial_cash

        # Update weights
        for position in self.portfolio.positions.values():
            position.weight = position.market_value / self.portfolio.total_value if self.portfolio.total_value > 0 else 0

        # Record equity
        self.portfolio.equity_curve.append((datetime.now(), self.portfolio.total_value))

        # Process open orders
        filled = self.order_manager.process_orders(current_prices)
        for order in filled:
            self._process_filled_order(order)

        # Check stop losses and take profits
        self._check_risk_limits(current_prices)

    def should_rebalance(self) -> bool:
        """Check if it's time to rebalance."""
        if self.last_rebalance is None:
            return True

        now = datetime.now()
        if self.rebalance_frequency == RebalanceFrequency.DAILY:
            return (now - self.last_rebalance).days >= 1
        elif self.rebalance_frequency == RebalanceFrequency.WEEKLY:
            return (now - self.last_rebalance).days >= 7
        elif self.rebalance_frequency == RebalanceFrequency.MONTHLY:
            return (now - self.last_rebalance).days >= 30

        return False

    def rebalance(
        self,
        signals: Optional[PortfolioSignals] = None,
        current_prices: Optional[Dict[str, float]] = None,
    ) -> List[Order]:
        """
        Rebalance portfolio based on signals.
        Returns list of orders created.
        """
        if signals is None:
            signals = self.last_signals
        if signals is None:
            logger.warning("No signals available for rebalancing")
            return []

        logger.info("Starting portfolio rebalance...")

        orders = []

        # Get target weights from signals
        target_weights = signals.recommended_weights

        # Current weights
        current_weights = {
            symbol: pos.weight
            for symbol, pos in self.portfolio.positions.items()
        }

        # Calculate required trades
        trades_needed = self._calculate_rebalance_trades(
            current_weights, target_weights, current_prices or {}
        )

        # Execute sells first (to free up cash)
        for symbol, (action, shares, price) in trades_needed.items():
            if action == "SELL":
                signal = next((s for s in signals.signals if s.symbol == symbol), None)
                order = self.order_manager.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=abs(shares),
                    signal_score=signal.composite_score if signal else None,
                    notes="Rebalance sell",
                )
                orders.append(order)

        # Execute buys
        for symbol, (action, shares, price) in trades_needed.items():
            if action == "BUY":
                signal = next((s for s in signals.signals if s.symbol == symbol), None)

                # Use bracket orders for new positions
                if symbol not in self.portfolio.positions:
                    bracket = self.order_manager.create_bracket_order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=shares,
                        stop_loss_pct=signal.stop_loss_pct if signal else self.stop_loss_pct,
                        take_profit_pct=signal.take_profit_pct if signal else self.take_profit_pct,
                    )
                    orders.append(bracket.entry_order)
                else:
                    # Adding to existing position
                    order = self.order_manager.create_market_order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=shares,
                        signal_score=signal.composite_score if signal else None,
                        notes="Rebalance buy",
                    )
                    orders.append(order)

        self.last_rebalance = datetime.now()
        logger.info(f"Rebalance complete: {len(orders)} orders created")

        return orders

    def _calculate_rebalance_trades(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        current_prices: Dict[str, float],
    ) -> Dict[str, Tuple[str, float, float]]:
        """
        Calculate trades needed to move from current to target weights.
        Returns dict of symbol -> (action, shares, price)
        """
        trades = {}
        portfolio_value = self.portfolio.total_value

        # All symbols we need to consider
        all_symbols = set(current_weights.keys()) | set(target_weights.keys())

        for symbol in all_symbols:
            current_weight = current_weights.get(symbol, 0)
            target_weight = target_weights.get(symbol, 0)
            weight_diff = target_weight - current_weight

            # Only trade if difference is significant (>1%)
            if abs(weight_diff) < 0.01:
                continue

            price = current_prices.get(symbol, 0)
            if price <= 0:
                continue

            # Calculate shares
            value_diff = weight_diff * portfolio_value
            shares = abs(value_diff / price)

            if weight_diff > 0:
                trades[symbol] = ("BUY", shares, price)
            else:
                trades[symbol] = ("SELL", shares, price)

        return trades

    def _process_filled_order(self, order: Order):
        """Process a filled order and update portfolio."""
        symbol = order.symbol
        quantity = order.filled_quantity
        price = order.filled_price
        commission = order.commission

        if order.side == OrderSide.BUY:
            # Buying
            cost = quantity * price + commission

            if symbol in self.portfolio.positions:
                # Add to existing position
                pos = self.portfolio.positions[symbol]
                total_cost = (pos.quantity * pos.avg_cost) + cost
                pos.quantity += quantity
                pos.avg_cost = total_cost / pos.quantity
            else:
                # New position
                self.portfolio.positions[symbol] = Position(
                    symbol=symbol,
                    quantity=quantity,
                    avg_cost=price + (commission / quantity),
                    current_price=price,
                    market_value=quantity * price,
                    unrealized_pnl=0,
                    unrealized_pnl_pct=0,
                    weight=0,
                    entry_date=datetime.now(),
                    stop_loss_price=price * (1 - self.stop_loss_pct),
                    take_profit_price=price * (1 + self.take_profit_pct),
                )

            self.portfolio.cash -= cost

        else:
            # Selling
            proceeds = quantity * price - commission

            if symbol in self.portfolio.positions:
                pos = self.portfolio.positions[symbol]
                pos.quantity -= quantity

                if pos.quantity <= 0.001:
                    # Position closed
                    del self.portfolio.positions[symbol]

            self.portfolio.cash += proceeds

        # Log trade
        trade = TradeLog(
            id=order.id,
            timestamp=datetime.now(),
            symbol=symbol,
            side=order.side.value,
            quantity=quantity,
            price=price,
            value=quantity * price,
            commission=commission,
            signal_score=order.signal_score,
            order_type=order.order_type.value,
            notes=order.notes,
        )
        self.trade_history.append(trade)

    def _check_risk_limits(self, current_prices: Dict[str, float]):
        """Check and enforce stop losses and take profits."""
        for symbol, position in list(self.portfolio.positions.items()):
            price = current_prices.get(symbol, position.current_price)

            # Check stop loss
            if position.stop_loss_price and price <= position.stop_loss_price:
                logger.warning(f"Stop loss triggered for {symbol} at {price:.2f}")
                self.order_manager.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    notes="Stop loss triggered",
                )

            # Check take profit
            elif position.take_profit_price and price >= position.take_profit_price:
                logger.info(f"Take profit triggered for {symbol} at {price:.2f}")
                self.order_manager.create_market_order(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=position.quantity,
                    notes="Take profit triggered",
                )

            # Update trailing stop
            elif self.use_trailing_stops and position.stop_loss_price:
                new_stop = price * (1 - self.trailing_stop_pct)
                if new_stop > position.stop_loss_price:
                    position.stop_loss_price = new_stop
                    logger.debug(f"Trailing stop updated for {symbol}: {new_stop:.2f}")

    def execute_signal(self, signal: StockSignal, current_price: float) -> Optional[Order]:
        """Execute a single signal manually."""
        if signal.action == "BUY":
            # Calculate position size
            target_value = self.portfolio.total_value * signal.target_weight
            shares = target_value / current_price

            if shares < 1:
                return None

            bracket = self.order_manager.create_bracket_order(
                symbol=signal.symbol,
                side=OrderSide.BUY,
                quantity=shares,
                stop_loss_pct=signal.stop_loss_pct,
                take_profit_pct=signal.take_profit_pct,
            )
            return bracket.entry_order

        elif signal.action == "SELL":
            if signal.symbol not in self.portfolio.positions:
                return None

            position = self.portfolio.positions[signal.symbol]
            return self.order_manager.create_market_order(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                quantity=position.quantity,
                signal_score=signal.composite_score,
                notes="Signal sell",
            )

        return None

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Calculate comprehensive performance metrics."""
        if len(self.portfolio.equity_curve) < 2:
            return {"error": "Insufficient data"}

        values = [v for _, v in self.portfolio.equity_curve]
        returns = np.diff(values) / np.array(values[:-1])

        # Basic metrics
        total_return = (values[-1] - self.initial_cash) / self.initial_cash
        n_days = max(len(returns), 1)
        cagr = (1 + total_return) ** (252 / n_days) - 1 if n_days > 0 else 0

        # Risk metrics
        vol = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0
        sharpe = (cagr - 0.02) / vol if vol > 0 else 0  # Assume 2% risk-free

        # Drawdown
        peak = np.maximum.accumulate(values)
        drawdown = (np.array(values) - peak) / peak
        max_drawdown = np.min(drawdown)

        # Trade metrics
        n_trades = len(self.trade_history)
        winning_trades = sum(1 for t in self.trade_history if t.side == "sell")  # Simplified

        return {
            "total_return": round(total_return, 4),
            "cagr": round(cagr, 4),
            "volatility": round(vol, 4),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_drawdown, 4),
            "n_trades": n_trades,
            "current_positions": len(self.portfolio.positions),
            "portfolio_value": round(self.portfolio.total_value, 2),
            "cash": round(self.portfolio.cash, 2),
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current auto-trader status."""
        return {
            "auto_trading_enabled": self.auto_trading_enabled,
            "paper_mode": self.paper_mode,
            "rebalance_frequency": self.rebalance_frequency.value,
            "last_rebalance": self.last_rebalance.isoformat() if self.last_rebalance else None,
            "portfolio": self.portfolio.to_dict(),
            "open_orders": len(self.order_manager.get_open_orders()),
            "performance": self.get_performance_metrics(),
            "market_regime": self.last_signals.market_regime if self.last_signals else "unknown",
        }


# Singleton
_trader: Optional[AutoTrader] = None

def get_auto_trader() -> AutoTrader:
    global _trader
    if _trader is None:
        settings = get_settings()
        _trader = AutoTrader(initial_cash=settings.initial_cash)
    return _trader
