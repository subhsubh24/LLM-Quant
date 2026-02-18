"""
Pluggable strategy modules for the trading pipeline.

Each strategy:
  1. Declares which symbols / asset classes it watches
  2. Receives features from the shared FeatureStore
  3. Emits Opportunity objects
"""

from .base import BaseStrategy
from .pairs_trading import PairsTradingStrategy
from .momentum import MomentumStrategy
from .options_premium import OptionsPremiumStrategy
from .perpetual import PerpetualStrategy
from .funding_rate_arb import FundingRateArbStrategy
from .aristotle_rules import AristotleRulesPipelineStrategy

__all__ = [
    "BaseStrategy",
    "PairsTradingStrategy",
    "MomentumStrategy",
    "OptionsPremiumStrategy",
    "PerpetualStrategy",
    "FundingRateArbStrategy",
    "AristotleRulesPipelineStrategy",
]
