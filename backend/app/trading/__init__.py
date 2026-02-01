"""Trading system with order management, automation, options, and autonomous bot."""

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
from .quant_bot import (
    QuantBot, TradingMode, AssetClass, BotTrade, BotPosition,
    TradeRationale, get_quant_bot, run_bot
)

__all__ = [
    "Order", "OrderType", "OrderSide", "OrderStatus", "TimeInForce",
    "BracketOrder", "OrderManager", "get_order_manager",
    "AutoTrader", "Portfolio", "Position", "TradeLog",
    "RebalanceFrequency", "get_auto_trader",
    "OptionType", "OptionStyle", "Greeks", "OptionContract", "OptionsStrategy",
    "BlackScholes", "OptionsManager", "get_options_manager",
    "QuantBot", "TradingMode", "AssetClass", "BotTrade", "BotPosition",
    "TradeRationale", "get_quant_bot", "run_bot",
]
