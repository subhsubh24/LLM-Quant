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
from .options_bot import (
    OptionsQuantBot, OptionsMode, OptionsPosition, OptionsTrade,
    IVAnalysis, OptionsRiskManager, get_options_bot, create_options_bot,
    CryptoDerivativePosition,
)
from .master_bot import (
    MasterQuantBot, MarketRegime, Opportunity,
    get_master_bot, create_master_bot,
    QuantAnalyticsEngine, MLPrediction, RiskMetrics,
)
from .ml_models import (
    DQN, PPOAgent, LSTM, TransformerPredictor, MarketRegimeVAE,
    EnsemblePredictor, Experience,
    create_dqn_agent, create_ppo_agent, create_ensemble,
)
from .quant_analytics import (
    BayesianEstimator, GaussianHMM, GARCH,
    GaussianCopula, StudentTCopula, ExtremeValueAnalyzer,
    FactorModel, PortfolioOptimizer, SignalGenerator,
    WalkForwardOptimizer, create_analytics_suite,
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
    # Options Bot
    "OptionsQuantBot", "OptionsMode", "OptionsPosition", "OptionsTrade",
    "IVAnalysis", "OptionsRiskManager", "get_options_bot", "create_options_bot",
    "CryptoDerivativePosition",
    # Master Bot (unified)
    "MasterQuantBot", "MarketRegime", "Opportunity",
    "get_master_bot", "create_master_bot",
    "QuantAnalyticsEngine", "MLPrediction", "RiskMetrics",
    # ML Models
    "DQN", "PPOAgent", "LSTM", "TransformerPredictor", "MarketRegimeVAE",
    "EnsemblePredictor", "Experience",
    "create_dqn_agent", "create_ppo_agent", "create_ensemble",
    # Quant Analytics
    "BayesianEstimator", "GaussianHMM", "GARCH",
    "GaussianCopula", "StudentTCopula", "ExtremeValueAnalyzer",
    "FactorModel", "PortfolioOptimizer", "SignalGenerator",
    "WalkForwardOptimizer", "create_analytics_suite",
]
