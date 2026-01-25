"""Trading system with order management, automation, and options."""

from .orders import (
    Order, OrderType, OrderSide, OrderStatus, TimeInForce,
    BracketOrder, OrderManager, get_order_manager
)
from .auto_trader import (
    AutoTrader, Portfolio, Position, TradeLog,
    RebalanceFrequency, get_auto_trader
)
from .options import (
    OptionType, OptionStyle, Greeks, OptionContract, OptionsStrategy,
    BlackScholes, OptionsManager, get_options_manager
)

__all__ = [
    "Order", "OrderType", "OrderSide", "OrderStatus", "TimeInForce",
    "BracketOrder", "OrderManager", "get_order_manager",
    "AutoTrader", "Portfolio", "Position", "TradeLog",
    "RebalanceFrequency", "get_auto_trader",
    "OptionType", "OptionStyle", "Greeks", "OptionContract", "OptionsStrategy",
    "BlackScholes", "OptionsManager", "get_options_manager",
]
