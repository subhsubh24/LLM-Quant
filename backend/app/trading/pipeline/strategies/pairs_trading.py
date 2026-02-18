"""
Pairs Trading Strategy — cointegrated-pair mean reversion.

Pipeline:
  1. find_cointegrated_pairs() via FeatureStore (Engle-Granger, 4h throttle)
  2. For each pair with active z-score signal → emit Opportunity
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)


class PairsTradingStrategy(BaseStrategy):
    name = "PairsTrading"

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass

        opportunities: List[Opportunity] = []

        try:
            coint_pairs = store.find_cointegrated_pairs(min_obs=60)
        except Exception as e:
            logger.debug(f"Pairs scan error: {e}")
            return opportunities

        for pair_info in coint_pairs:
            sym_a = pair_info["sym_a"]
            sym_b = pair_info["sym_b"]

            zscore_data = store.get_spread_zscore(sym_a, sym_b)
            if zscore_data is None:
                continue

            signal = zscore_data["signal"]
            if signal in ("hold", "exit"):
                continue

            zscore = zscore_data["zscore"]
            confidence = zscore_data["confidence"]
            half_life = zscore_data["half_life"]
            hedge_ratio = zscore_data["hedge_ratio"]

            if signal == "buy_spread":
                strategy = f"Pairs Long {sym_a} / Short {sym_b}"
                rationale = (
                    f"Cointegrated pair: z={zscore:+.2f} (entry <-1.0) | "
                    f"Half-life: {half_life:.1f} | Hedge: {hedge_ratio:.3f}"
                )
            elif signal == "sell_spread":
                strategy = f"Pairs Short {sym_a} / Long {sym_b}"
                rationale = (
                    f"Cointegrated pair: z={zscore:+.2f} (entry >+1.0) | "
                    f"Half-life: {half_life:.1f} | Hedge: {hedge_ratio:.3f}"
                )
            elif signal == "stop":
                strategy = f"Pairs STOP {sym_a}/{sym_b}"
                rationale = f"Spread blown out: z={zscore:+.2f} (>4σ) | Close immediately"
            else:
                continue

            expected_return = min(abs(zscore) * 5, 30.0)
            # Use a notional position size of 2 % capital as reference
            # (actual sizing done by the RiskGate)
            max_profit_pct = 0.08
            max_loss_pct = 0.04

            opp = Opportunity(
                symbol=f"{sym_a}/{sym_b}",
                asset_class=AssetClass.CRYPTO_SPOT,
                strategy=strategy,
                expected_return=expected_return,
                max_profit=max_profit_pct * 100,
                max_loss=max_loss_pct * 100,
                probability_of_profit=0.55 + confidence * 0.20,
                risk_reward_ratio=max_profit_pct / max_loss_pct,
                iv_rank=50.0,
                score=35.0 + confidence * 30 + min(abs(zscore), 3) * 5,
                rationale=rationale,
            )
            opportunities.append(opp)

        if coint_pairs:
            logger.info(
                f"PairsTrading: {len(coint_pairs)} cointegrated pairs, "
                f"{len(opportunities)} actionable"
            )

        return opportunities
