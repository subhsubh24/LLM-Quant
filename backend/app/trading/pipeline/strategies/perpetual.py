"""
Perpetual Strategy — ML-directed crypto perpetual futures.

Uses the FeatureStore ML ensemble to score long/short perp opportunities
on the full Binance Futures universe.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)

CRYPTO_PERPETUALS = [
    # Tier 1
    "BTC-PERP", "ETH-PERP", "BNB-PERP", "SOL-PERP", "XRP-PERP",
    # Tier 2
    "DOGE-PERP", "ADA-PERP", "AVAX-PERP", "LINK-PERP", "DOT-PERP",
    "MATIC-PERP", "LTC-PERP", "ATOM-PERP", "UNI-PERP", "ETC-PERP",
    "FIL-PERP", "NEAR-PERP", "APT-PERP", "ARB-PERP", "OP-PERP",
    # Tier 3 — DeFi & L2
    "INJ-PERP", "SUI-PERP", "SEI-PERP", "TIA-PERP", "FTM-PERP",
    "AAVE-PERP", "MKR-PERP", "LDO-PERP", "CRV-PERP", "SNX-PERP",
    "COMP-PERP", "DYDX-PERP", "GMX-PERP", "GRT-PERP", "IMX-PERP",
    # Tier 4 — AI & Storage
    "FET-PERP", "RNDR-PERP", "AR-PERP", "THETA-PERP", "STX-PERP",
    # Tier 5 — Memes
    "PEPE-PERP", "SHIB-PERP", "FLOKI-PERP", "BONK-PERP", "WIF-PERP",
    "MEME-PERP", "ORDI-PERP",
    # Tier 6 — Recent
    "JTO-PERP", "PYTH-PERP", "JUP-PERP", "STRK-PERP", "W-PERP",
    "ENA-PERP", "ONDO-PERP", "PENDLE-PERP", "NOT-PERP", "WLD-PERP",
]


class PerpetualStrategy(BaseStrategy):
    name = "Perpetual"

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass

        opportunities: List[Opportunity] = []

        for symbol in CRYPTO_PERPETUALS:
            try:
                opp = self._score(symbol, store)
                if opp and opp.score > 30:
                    opportunities.append(opp)
            except Exception as e:
                logger.debug(f"Perpetual error {symbol}: {e}")

        return opportunities

    # ------------------------------------------------------------------ #

    @staticmethod
    def _score(symbol: str, store: "FeatureStore") -> "Opportunity | None":
        from ...master_bot import Opportunity, AssetClass

        ml = store.get_ml_prediction(symbol)

        if ml.action == 0:
            strategy = "Short Perpetual"
            expected_return = 40 * ml.confidence
            probability = 0.55 + ml.ensemble_agreement * 0.15
            rationale = (
                f"ML Sell (conf {ml.confidence:.0%}) | "
                f"Regime: {ml.regime}"
            )
        elif ml.action == 2:
            strategy = "Long Perpetual"
            expected_return = 40 * ml.confidence
            probability = 0.55 + ml.ensemble_agreement * 0.15
            rationale = (
                f"ML Buy (conf {ml.confidence:.0%}) | "
                f"Regime: {ml.regime}"
            )
        else:
            strategy = "Long Perpetual"
            expected_return = 15
            probability = 0.50
            rationale = f"Neutral ML | {symbol}"

        max_profit = 100 * 0.10
        max_loss = 100 * 0.05
        rr = max_profit / max_loss if max_loss > 0 else 2.0

        score = (
            expected_return * 0.30
            + probability * 100 * 0.25
            + ml.confidence * 50 * 0.25
            + rr * 15 * 0.20
        )

        return Opportunity(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO_PERPETUAL,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=rr,
            iv_rank=65,
            score=score,
            rationale=rationale,
        )
