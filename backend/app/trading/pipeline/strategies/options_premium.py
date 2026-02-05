"""
Options Premium Strategy — IV-rank driven premium selling / buying.

Covers stock options, ETF options, commodity options, and crypto options.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

import numpy as np

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)

STOCK_OPTIONS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD",
    "NFLX", "CRM", "INTC", "PYPL", "SQ", "COIN", "V", "MA", "JPM", "BAC",
]
ETF_OPTIONS = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLU", "XLI",
]
COMMODITY_OPTIONS = [
    "GLD", "SLV", "GDX", "USO", "UNG", "WEAT", "CORN",
]
CRYPTO_OPTIONS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "LINK", "DOGE",
    "ADA", "DOT", "MATIC", "LTC",
]


def _build_iv_analysis(store: "FeatureStore", symbol: str):
    """Synthetic IV analysis from realised vol when no live IV feed."""
    risk = store.get_risk_metrics(symbol)
    vol = risk.volatility_forecast
    # Simulate IV rank: high realised vol → high IV rank
    iv_rank = min(100, max(0, vol * 200))
    return type("IVAnalysis", (), {"iv_rank": iv_rank, "current_iv": vol})()


class OptionsPremiumStrategy(BaseStrategy):
    name = "OptionsPremium"

    def __init__(self, require_market_open: bool = True):
        self.require_market_open = require_market_open

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass, MarketRegime

        opportunities: List[Opportunity] = []

        # Stock / ETF / Commodity options only when market is open
        if self.require_market_open:
            try:
                from ...trading.quant_bot import is_market_open
                market_open = is_market_open()
            except Exception:
                market_open = False
        else:
            market_open = True

        if market_open:
            for sym in STOCK_OPTIONS:
                opp = self._score_option(sym, AssetClass.STOCK_OPTIONS, store)
                if opp and opp.score > 35:
                    opportunities.append(opp)

            for sym in ETF_OPTIONS:
                opp = self._score_option(sym, AssetClass.ETF_OPTIONS, store)
                if opp and opp.score > 35:
                    opportunities.append(opp)

            for sym in COMMODITY_OPTIONS:
                opp = self._score_option(sym, AssetClass.COMMODITY_OPTIONS, store)
                if opp and opp.score > 35:
                    opportunities.append(opp)

        # Crypto options are 24/7
        for base in CRYPTO_OPTIONS:
            for opt_type in ("call", "put"):
                opp = self._score_crypto_option(base, opt_type, store)
                if opp and opp.score > 35:
                    opportunities.append(opp)

        return opportunities

    # ------------------------------------------------------------------ #

    @staticmethod
    def _score_option(
        symbol: str,
        asset_class: "AssetClass",
        store: "FeatureStore",
    ) -> "Opportunity | None":
        from ...master_bot import Opportunity, MarketRegime

        iv = _build_iv_analysis(store, symbol)

        if iv.iv_rank > 50 or store.market_regime == MarketRegime.HIGH_VOLATILITY:
            strategy = "Iron Condor"
            expected_return = 25 + iv.iv_rank * 0.3
            probability = 0.70 + (iv.iv_rank - 50) * 0.002
            max_profit, max_loss = 200 + iv.iv_rank * 3, 500
            rationale = f"High IV Rank ({iv.iv_rank:.0f}%) — premium selling"
        elif iv.iv_rank < 25:
            strategy = "Long Straddle"
            expected_return = 15 + (25 - iv.iv_rank) * 0.5
            probability = 0.45
            max_profit, max_loss = 1000, 300
            rationale = f"Low IV Rank ({iv.iv_rank:.0f}%) — cheap premium"
        else:
            strategy = "Vertical Spread"
            expected_return = 20
            probability = 0.55
            max_profit, max_loss = 300, 200
            rationale = f"Moderate IV ({iv.iv_rank:.0f}%) — directional"

        rr = max_profit / max_loss if max_loss > 0 else 0
        score = (
            expected_return * 0.3
            + probability * 100 * 0.25
            + iv.iv_rank * 0.2
            + rr * 10 * 0.15
            + 20 * 0.1
        )

        return Opportunity(
            symbol=symbol,
            asset_class=asset_class,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=rr,
            iv_rank=iv.iv_rank,
            score=score,
            rationale=rationale,
        )

    @staticmethod
    def _score_crypto_option(
        base_asset: str,
        option_type: str,
        store: "FeatureStore",
    ) -> "Opportunity | None":
        from ...master_bot import Opportunity, AssetClass

        risk = store.get_risk_metrics(base_asset)
        iv = min(1.0, max(0.3, risk.volatility_forecast + np.random.uniform(-0.1, 0.2)))

        if iv > 0.70:
            strategy = f"Sell {base_asset} {option_type.title()}"
            expected_return, probability = 35, 0.65
            max_profit = 100 * 0.05
            max_loss = 100 * 0.15
            rationale = f"High crypto IV ({iv*100:.0f}%) — selling premium"
        else:
            strategy = f"Buy {base_asset} {option_type.title()}"
            expected_return, probability = 25, 0.40
            max_profit = 100 * 0.20
            max_loss = 100 * 0.03
            rationale = f"Lower crypto IV ({iv*100:.0f}%) — directional"

        rr = max_profit / max_loss if max_loss > 0 else 0
        score = (
            expected_return * 0.3
            + probability * 100 * 0.25
            + iv * 100 * 0.2
            + rr * 10 * 0.15
            + 15 * 0.1
        )

        return Opportunity(
            symbol=f"{base_asset}-{option_type.upper()}",
            asset_class=AssetClass.CRYPTO_OPTIONS,
            strategy=strategy,
            expected_return=expected_return,
            max_profit=max_profit,
            max_loss=max_loss,
            probability_of_profit=probability,
            risk_reward_ratio=rr,
            iv_rank=iv * 100,
            score=score,
            rationale=rationale,
        )
