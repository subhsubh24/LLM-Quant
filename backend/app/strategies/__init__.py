"""Trading strategies subsystem."""

from .framework import (
    BaseStrategy,
    StrategySignal,
    StrategyMetrics,
    StrategyStatus,
    StrategyRegistry,
    StrategyExecutor,
)
from .core_strategies import (
    TrendFollowingStrategy,
    MeanReversionStrategy,
    VolatilityTradingStrategy,
    SectorRotationStrategy,
    CarryTradingStrategy,
    TechnicalPatternsStrategy,
    SentimentAnalysisStrategy,
    FactorRotationStrategy,
)
from .counter_cyclical_strategies import (
    LongVolatilityStrategy,
    IntradayMeanReversionStrategy,
    EnhancedFactorRotationStrategy,
    KalmanFilterStatArbStrategy,
)
from .enhanced_mean_reversion import (
    EnhancedMeanReversionStrategy,
    AdaptiveVolatilityMeanReversionStrategy,
)
from .sentiment_strategy import (
    SentimentAnalysisStrategy as SentimentTradingStrategy,
    MultiSourceSentimentStrategy,
)

__all__ = [
    # Framework
    "BaseStrategy",
    "StrategySignal",
    "StrategyMetrics",
    "StrategyStatus",
    "StrategyRegistry",
    "StrategyExecutor",
    # Core Strategies (8)
    "TrendFollowingStrategy",
    "MeanReversionStrategy",
    "VolatilityTradingStrategy",
    "SectorRotationStrategy",
    "CarryTradingStrategy",
    "TechnicalPatternsStrategy",
    "SentimentAnalysisStrategy",
    "FactorRotationStrategy",
    # Counter-Cyclical & Enhanced (4)
    "LongVolatilityStrategy",
    "IntradayMeanReversionStrategy",
    "EnhancedFactorRotationStrategy",
    "KalmanFilterStatArbStrategy",
    # Enhanced Mean Reversion (2)
    "EnhancedMeanReversionStrategy",
    "AdaptiveVolatilityMeanReversionStrategy",
    # Sentiment Trading (2)
    "SentimentTradingStrategy",
    "MultiSourceSentimentStrategy",
]
