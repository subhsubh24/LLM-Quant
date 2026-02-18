"""
RiskGate — unified risk filter applied after all strategies produce Opportunities.

Consolidates:
  - Portfolio drawdown circuit breaker (soft 10 %, hard 20 %)
  - Cross-asset correlation / sector concentration limits
  - Dynamic score + confidence thresholds (regime-adjusted)
  - Allocation limits per asset class
  - Duplicate-position guard
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set

from ..master_bot import AssetClass, MarketRegime, Opportunity

logger = logging.getLogger(__name__)

# Sector classification (correlation proxy)
SYMBOL_SECTOR: Dict[str, str] = {
    # Crypto — BTC & majors
    "BTC": "crypto_major", "ETH": "crypto_major",
    "BNB": "crypto_major", "SOL": "crypto_major", "XRP": "crypto_major",
    # Crypto — DeFi
    "AAVE": "crypto_defi", "UNI": "crypto_defi", "MKR": "crypto_defi",
    "CRV": "crypto_defi", "COMP": "crypto_defi", "SNX": "crypto_defi",
    "DYDX": "crypto_defi", "GMX": "crypto_defi", "LDO": "crypto_defi",
    # Crypto — Memes
    "DOGE": "crypto_meme", "SHIB": "crypto_meme", "PEPE": "crypto_meme",
    "FLOKI": "crypto_meme", "BONK": "crypto_meme", "WIF": "crypto_meme",
    # Crypto — L1/L2
    "ADA": "crypto_l1", "AVAX": "crypto_l1", "DOT": "crypto_l1",
    "ATOM": "crypto_l1", "NEAR": "crypto_l1", "APT": "crypto_l1",
    "SUI": "crypto_l1", "SEI": "crypto_l1", "ARB": "crypto_l2",
    "OP": "crypto_l2", "MATIC": "crypto_l2", "STX": "crypto_l2",
    # Crypto — AI
    "FET": "crypto_ai", "RNDR": "crypto_ai", "AR": "crypto_ai",
    "THETA": "crypto_ai",
    # Equities — Tech
    "AAPL": "equity_tech", "MSFT": "equity_tech", "GOOGL": "equity_tech",
    "AMZN": "equity_tech", "NVDA": "equity_tech", "META": "equity_tech",
    "TSLA": "equity_tech", "AMD": "equity_tech", "NFLX": "equity_tech",
    "CRM": "equity_tech", "INTC": "equity_tech",
    # Equities — Financial
    "JPM": "equity_financial", "BAC": "equity_financial",
    "V": "equity_financial", "MA": "equity_financial",
    "PYPL": "equity_financial", "SQ": "equity_financial",
    "COIN": "equity_financial", "GS": "equity_financial",
    # ETFs
    "SPY": "etf_broad", "QQQ": "etf_broad", "IWM": "etf_broad",
    "DIA": "etf_broad",
    "XLK": "etf_sector", "XLF": "etf_sector", "XLE": "etf_sector",
    "XLV": "etf_sector", "XLU": "etf_sector", "XLI": "etf_sector",
    # Commodities
    "GLD": "commodity", "SLV": "commodity", "GDX": "commodity",
    "USO": "commodity", "UNG": "commodity", "WEAT": "commodity",
    "CORN": "commodity",
}


def _get_sector(symbol: str) -> str:
    """Return sector for *symbol* (strip -PERP, -CALL, etc.)."""
    base = symbol.split("-")[0].split("/")[0]
    return SYMBOL_SECTOR.get(base, "other")


class RiskGate:
    """
    Stateless filter: given portfolio context + opportunities,
    return the subset that pass all risk checks.
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        drawdown_soft: float = 0.10,
        drawdown_hard: float = 0.20,
        max_sector_same_dir: int = 3,
    ):
        self.initial_capital = initial_capital
        self.drawdown_soft = drawdown_soft
        self.drawdown_hard = drawdown_hard
        self.max_sector_same_dir = max_sector_same_dir

        self.allocation_limits: Dict[AssetClass, float] = {
            AssetClass.STOCK_OPTIONS: 0.25,
            AssetClass.ETF_OPTIONS: 0.25,
            AssetClass.COMMODITY_OPTIONS: 0.10,
            AssetClass.CRYPTO_PERPETUAL: 0.15,
            AssetClass.CRYPTO_OPTIONS: 0.10,
            AssetClass.CRYPTO_SPOT: 0.15,
        }

    # ------------------------------------------------------------------ #
    # Dynamic thresholds
    # ------------------------------------------------------------------ #

    @staticmethod
    def score_threshold(regime: MarketRegime) -> float:
        return {
            MarketRegime.HIGH_VOLATILITY: 50,
            MarketRegime.BEAR_MARKET: 45,
            MarketRegime.RANGE_BOUND: 35,
            MarketRegime.BULL_MARKET: 30,
            MarketRegime.LOW_VOLATILITY: 28,
        }.get(regime, 35)

    @staticmethod
    def confidence_threshold(regime: MarketRegime) -> float:
        return {
            MarketRegime.HIGH_VOLATILITY: 0.75,
            MarketRegime.BEAR_MARKET: 0.70,
            MarketRegime.RANGE_BOUND: 0.60,
            MarketRegime.BULL_MARKET: 0.55,
            MarketRegime.LOW_VOLATILITY: 0.50,
        }.get(regime, 0.60)

    # ------------------------------------------------------------------ #
    # Regime alignment
    # ------------------------------------------------------------------ #

    @staticmethod
    def regime_alignment(opp: Opportunity, regime: MarketRegime) -> float:
        """How well does the opportunity match the current regime?"""
        # Stat-arb / market-neutral strategies
        if "Pairs" in opp.strategy or "Funding Arb" in opp.strategy:
            if regime == MarketRegime.RANGE_BOUND:
                return 0.95
            if regime == MarketRegime.HIGH_VOLATILITY:
                return 0.85
            return 0.75

        if regime == MarketRegime.HIGH_VOLATILITY:
            if "Iron Condor" in opp.strategy or "Sell" in opp.strategy:
                return 0.9
            if "Straddle" in opp.strategy and "Long" not in opp.strategy:
                return 0.8
        elif regime == MarketRegime.LOW_VOLATILITY:
            if "Long" in opp.strategy or "Buy" in opp.strategy:
                return 0.85
        elif regime == MarketRegime.BULL_MARKET:
            if "Long" in opp.strategy or "Call" in opp.strategy:
                return 0.9
        elif regime == MarketRegime.BEAR_MARKET:
            if "Short" in opp.strategy or "Put" in opp.strategy:
                return 0.9

        return 0.5

    # ------------------------------------------------------------------ #
    # Correlation / sector concentration
    # ------------------------------------------------------------------ #

    def _check_sector_concentration(
        self,
        symbol: str,
        side: str,
        existing_positions: Dict[str, str],
    ) -> bool:
        """Return True if adding (symbol, side) stays within concentration limit."""
        sector = _get_sector(symbol)
        count = 0
        for pos_sym, pos_side in existing_positions.items():
            if _get_sector(pos_sym) == sector and pos_side == side:
                count += 1
        return count < self.max_sector_same_dir

    # ------------------------------------------------------------------ #
    # Main filter
    # ------------------------------------------------------------------ #

    def filter(
        self,
        opportunities: List[Opportunity],
        *,
        total_pnl: float,
        regime: MarketRegime,
        current_allocations: Dict[AssetClass, float],
        held_symbols: Set[str],
        existing_positions: Dict[str, str],
        max_new: int = 3,
        peak_value: float = 0,
    ) -> List[Opportunity]:
        """
        Return the opportunities that pass all risk checks.

        Parameters
        ----------
        total_pnl :            current portfolio P&L (negative = loss)
        regime :               current MarketRegime
        current_allocations :  fraction allocated per AssetClass
        held_symbols :         symbols we already hold
        existing_positions :   {symbol: side} for sector-concentration check
        max_new :              maximum new positions per cycle
        peak_value :           peak portfolio value for drawdown calc
        """
        # ── Drawdown circuit breaker (peak-to-trough) ─────────
        current_value = self.initial_capital + total_pnl
        if peak_value > 0 and peak_value > current_value:
            drawdown = (peak_value - current_value) / peak_value
        else:
            drawdown = 0.0

        if drawdown >= self.drawdown_hard:
            logger.warning(
                f"CIRCUIT BREAKER: drawdown {drawdown:.1%} >= {self.drawdown_hard:.0%} — halting"
            )
            return []

        if drawdown >= self.drawdown_soft:
            max_new = 1
            logger.info(
                f"Drawdown {drawdown:.1%} >= {self.drawdown_soft:.0%} — "
                f"reducing max new positions to {max_new}"
            )

        # ── Per-opportunity checks ────────────────────────────
        score_thresh = self.score_threshold(regime)
        conf_thresh = self.confidence_threshold(regime)

        passed: List[Opportunity] = []

        for opp in opportunities:
            if len(passed) >= max_new:
                break

            # Allocation limit
            alloc = current_allocations.get(opp.asset_class, 0)
            limit = self.allocation_limits.get(opp.asset_class, 0.20)
            if alloc >= limit:
                continue

            # Duplicate position
            if opp.symbol in held_symbols:
                continue

            # Score threshold
            if opp.score < score_thresh:
                continue

            # ML confidence (if available)
            if opp.ml_prediction and opp.ml_prediction.confidence < conf_thresh:
                continue

            # Sector concentration
            side = "long" if "Long" in opp.strategy or "Buy" in opp.strategy else "short"
            if not self._check_sector_concentration(opp.symbol, side, existing_positions):
                continue

            # Attach regime alignment
            opp.regime_alignment = self.regime_alignment(opp, regime)

            passed.append(opp)

        return passed
