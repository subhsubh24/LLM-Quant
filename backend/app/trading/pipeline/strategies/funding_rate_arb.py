"""
Funding Rate Arbitrage Strategy.

Detects abnormally high / low funding rates on crypto perpetuals
and creates market-neutral carry-trade Opportunities.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)

# Top-20 liquid perps to scan for funding rate arb
LIQUID_PERPS = [
    "BTC-PERP", "ETH-PERP", "BNB-PERP", "SOL-PERP", "XRP-PERP",
    "DOGE-PERP", "ADA-PERP", "AVAX-PERP", "LINK-PERP", "DOT-PERP",
    "MATIC-PERP", "LTC-PERP", "ATOM-PERP", "UNI-PERP", "ETC-PERP",
    "FIL-PERP", "NEAR-PERP", "APT-PERP", "ARB-PERP", "OP-PERP",
]


class FundingRateArbStrategy(BaseStrategy):
    name = "FundingRateArb"

    def __init__(self, get_price_fn=None):
        """
        Parameters
        ----------
        get_price_fn : async callable(symbol) -> float
            Function to fetch the live price for a symbol.
            Injected by the orchestrator (wraps engine._get_crypto_price).
        """
        self._get_price = get_price_fn

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass

        opportunities: List[Opportunity] = []

        for symbol in LIQUID_PERPS:
            try:
                base = symbol.split("-")[0]
                funding_rate = await store.fetch_funding_rate(symbol)

                # Fetch spot and perp prices through injected helper
                spot_price = perp_price = 0.0
                if self._get_price is not None:
                    spot_price = await self._get_price(base)
                    perp_price = await self._get_price(symbol)
                if spot_price <= 0 or perp_price <= 0:
                    continue

                arb = store.get_funding_rate_arb_signal(
                    symbol, funding_rate, spot_price, perp_price,
                )

                if arb["signal"] == "neutral" or arb["confidence"] < 0.3:
                    continue

                annual_carry = arb["annualized_carry"]

                if arb["signal"] == "short_perp_long_spot":
                    strategy = f"Funding Arb: Short {symbol} + Long {base}"
                    rationale = (
                        f"High funding {funding_rate*100:.4f}% / 8 h "
                        f"({annual_carry:.1f}% ann.) | "
                        f"Basis: {arb['basis']*100:.3f}%"
                    )
                else:
                    strategy = f"Funding Arb: Long {symbol} + Short {base}"
                    rationale = (
                        f"Neg funding {funding_rate*100:.4f}% / 8 h "
                        f"({annual_carry:.1f}% ann.) | "
                        f"Basis: {arb['basis']*100:.3f}%"
                    )

                expected_return = min(annual_carry / 12, 10.0)
                # Notional sizing (actual sizing by RiskGate)
                max_profit = expected_return
                max_loss = 2.0  # 2 % stop on basis blow-out

                opp = Opportunity(
                    symbol=f"{base}-FUNDING",
                    asset_class=AssetClass.CRYPTO_PERPETUAL,
                    strategy=strategy,
                    expected_return=expected_return,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    probability_of_profit=0.70 + arb["confidence"] * 0.15,
                    risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 3.0,
                    iv_rank=40.0,
                    score=40.0 + arb["confidence"] * 25 + min(annual_carry, 100) * 0.2,
                    rationale=rationale,
                )
                opportunities.append(opp)

            except Exception as e:
                logger.debug(f"FundingArb error {symbol}: {e}")

        if opportunities:
            logger.info(f"FundingRateArb: {len(opportunities)} opportunities")

        return opportunities
