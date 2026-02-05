"""
Momentum / Spot Directional Strategy.

Uses ML ensemble + technical indicators to generate directional
buy/sell opportunities on crypto spot and equity markets.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)

# Symbols this strategy watches
CRYPTO_SPOT = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "AVAX", "LINK", "DOGE", "ADA", "DOT", "MATIC", "LTC", "ATOM",
    "UNI", "AAVE", "MKR", "CRV", "FET", "RNDR", "INJ", "SUI",
]


class MomentumStrategy(BaseStrategy):
    name = "Momentum"

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass, MarketRegime

        opportunities: List[Opportunity] = []

        for symbol in CRYPTO_SPOT:
            try:
                opp = self._score(symbol, store)
                if opp and opp.score > 30:
                    opportunities.append(opp)
            except Exception as e:
                logger.debug(f"Momentum error {symbol}: {e}")

        return opportunities

    # ------------------------------------------------------------------ #

    @staticmethod
    def _score(symbol: str, store: "FeatureStore") -> "Opportunity | None":
        from ...master_bot import Opportunity, AssetClass, MarketRegime

        ml_pred = store.get_ml_prediction(symbol)
        risk = store.get_risk_metrics(symbol)
        indicators = store.get_indicators(symbol)

        if ml_pred.action == 2:
            strategy, direction = "Spot Long", "bullish"
        elif ml_pred.action == 0:
            strategy, direction = "Spot Short", "bearish"
        else:
            strategy, direction = "Spot Long", "neutral"

        base_score = ml_pred.confidence * 100

        # Regime adjustment
        regime = store.market_regime
        if regime == MarketRegime.BULL_MARKET and direction == "bullish":
            base_score *= 1.2
        elif regime == MarketRegime.BEAR_MARKET and direction == "bearish":
            base_score *= 1.1

        # Penalise high vol for spot (prefer stable entries)
        if risk.volatility_forecast > 0.5:
            base_score *= 0.8

        # Technical confirmation bonus
        rsi = indicators.get("rsi", 50)
        if direction == "bullish" and rsi < 35:
            base_score *= 1.1  # Oversold confirmation
        elif direction == "bearish" and rsi > 65:
            base_score *= 1.1  # Overbought confirmation

        max_profit = 100 * 0.10
        max_loss = 100 * 0.05
        expected_return = ml_pred.lstm_pred * 100 if ml_pred.lstm_pred else 5

        return Opportunity(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO_SPOT,
            strategy=strategy,
            score=base_score,
            expected_return=expected_return,
            probability_of_profit=ml_pred.confidence,
            risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 2.0,
            iv_rank=50,
            max_profit=max_profit,
            max_loss=max_loss,
            rationale=(
                f"ML: {ml_pred.action_name} (conf {ml_pred.confidence:.1%}) | "
                f"Regime: {ml_pred.regime} | "
                f"RSI: {rsi:.0f} | Vol: {risk.volatility_forecast:.0%}"
            ),
        )
