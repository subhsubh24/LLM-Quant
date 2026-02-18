"""
Aristotle Rules-Based Pipeline Strategy Adapter.

Wraps the standalone AristotleRulesStrategy (from app.strategies.rules_based_strategy)
so it can participate in the PipelineOrchestrator's scan→filter→execute cycle.

The adapter:
  1. Pulls price history from the shared FeatureStore
  2. Constructs a pandas DataFrame with OHLCV columns
  3. Delegates to AristotleRulesStrategy.generate_signal()
  4. Converts the resulting StrategySignal into pipeline Opportunity objects
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

import numpy as np
import pandas as pd

from .base import BaseStrategy

if TYPE_CHECKING:
    from ..feature_store import FeatureStore
    from ...master_bot import Opportunity

logger = logging.getLogger(__name__)

# Symbols this strategy watches — both crypto and equity.
# The adapter will scan whichever of these are present in the FeatureStore.
CRYPTO_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP",
    "AVAX", "LINK", "DOGE", "ADA", "DOT", "MATIC", "LTC", "ATOM",
    "UNI", "AAVE", "MKR", "CRV", "FET", "RNDR", "INJ", "SUI",
]

EQUITY_SYMBOLS = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "GLD", "SLV", "JPM", "BAC", "GS", "AMD", "COIN",
]

# Minimum number of price bars required by AristotleRulesStrategy (default 200).
# We use a slightly lower floor for the pipeline adapter so that symbols with
# moderate history can still be evaluated (the inner strategy handles the
# "insufficient data" case gracefully by returning a neutral signal).
MIN_BARS = 60


class AristotleRulesPipelineStrategy(BaseStrategy):
    """Pipeline adapter for the Aristotle composite rules-based strategy.

    Translates FeatureStore price arrays into the OHLCV DataFrame that
    AristotleRulesStrategy expects, runs the seven-sub-signal composite
    evaluation, and converts the StrategySignal into scored Opportunity
    objects that the PipelineOrchestrator can rank and execute.
    """

    name = "Aristotle Rules"

    def __init__(self, min_bars: int = MIN_BARS):
        self._min_bars = min_bars
        # Lazily instantiated so the heavy import only happens on first scan
        self._inner: object | None = None

    # ------------------------------------------------------------------ #
    # BaseStrategy interface
    # ------------------------------------------------------------------ #

    async def scan(self, store: "FeatureStore") -> List["Opportunity"]:
        from ...master_bot import Opportunity, AssetClass

        # Lazy-init the inner rules-based strategy
        if self._inner is None:
            self._inner = self._build_inner()

        opportunities: List[Opportunity] = []

        # Scan every symbol present in the store that we care about
        candidates = self._candidate_symbols(store)

        for symbol in candidates:
            try:
                opp = self._evaluate(symbol, store)
                if opp is not None and opp.score > 20:
                    opportunities.append(opp)
            except Exception as e:
                logger.debug(f"Aristotle Rules error {symbol}: {e}")

        return opportunities

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_inner():
        """Create the inner AristotleRulesStrategy instance."""
        from ...strategies.rules_based_strategy import AristotleRulesStrategy
        # Use default parameters; the pipeline adapter passes min_bars
        # via the DataFrame length — the inner strategy validates itself.
        return AristotleRulesStrategy()

    def _candidate_symbols(self, store: "FeatureStore") -> List[str]:
        """Return symbols that exist in the store and have enough data."""
        wanted = set(CRYPTO_SYMBOLS) | set(EQUITY_SYMBOLS)
        candidates: List[str] = []
        for sym in wanted:
            prices = store.price_history.get(sym)
            if prices is not None and len(prices) >= self._min_bars:
                candidates.append(sym)
        return sorted(candidates)

    def _evaluate(self, symbol: str, store: "FeatureStore") -> "Opportunity | None":
        """Run the inner strategy on *symbol* and convert the signal."""
        from ...master_bot import Opportunity, AssetClass, MarketRegime

        prices = store.price_history.get(symbol)
        if prices is None or len(prices) < self._min_bars:
            return None

        # Build an OHLCV DataFrame from the flat price array.
        # FeatureStore stores close prices; we synthesise OHLC from them.
        df = self._prices_to_ohlcv(prices)

        # Run the inner strategy
        signal = self._inner.generate_signal(df)

        # Extract composite score (-1..+1) and confidence (0..1)
        composite_score = signal.extra_data.get("composite_score", 0.0)
        confidence = signal.confidence

        # Skip neutral / very-weak signals
        if abs(composite_score) < 0.05 or confidence < 0.25:
            return None

        # Determine direction and strategy label
        if composite_score > 0:
            direction = "bullish"
            strategy_label = "Aristotle Rules Long"
        else:
            direction = "bearish"
            strategy_label = "Aristotle Rules Short"

        # Determine asset class
        asset_class = self._asset_class_for(symbol)

        # Score: map composite [-1, 1] and confidence [0, 1] into a 0-100 range
        # that is comparable to other pipeline strategies.
        base_score = abs(composite_score) * 60 + confidence * 40  # max = 100

        # Regime adjustment
        regime = store.market_regime
        if regime == MarketRegime.BULL_MARKET and direction == "bullish":
            base_score *= 1.15
        elif regime == MarketRegime.BEAR_MARKET and direction == "bearish":
            base_score *= 1.10
        elif regime == MarketRegime.HIGH_VOLATILITY:
            base_score *= 0.85  # Penalise in crisis

        # Risk metrics from store for additional context
        risk = store.get_risk_metrics(symbol)
        if risk.volatility_forecast > 0.5:
            base_score *= 0.85

        # Estimate expected return from composite magnitude
        expected_return = abs(composite_score) * 10  # rough %-based estimate
        max_profit = 100 * 0.10
        max_loss = 100 * 0.05

        return Opportunity(
            symbol=symbol,
            asset_class=asset_class,
            strategy=strategy_label,
            score=base_score,
            expected_return=expected_return,
            probability_of_profit=confidence,
            risk_reward_ratio=max_profit / max_loss if max_loss > 0 else 2.0,
            iv_rank=50,  # Not directly relevant for rules-based
            max_profit=max_profit,
            max_loss=max_loss,
            rationale=(
                f"Aristotle Composite={composite_score:+.3f} | "
                f"Conf={confidence:.1%} | {signal.reason}"
            ),
        )

    # ------------------------------------------------------------------ #
    # DataFrame construction
    # ------------------------------------------------------------------ #

    @staticmethod
    def _prices_to_ohlcv(prices: np.ndarray) -> pd.DataFrame:
        """Convert a 1-D close-price array into a synthetic OHLCV DataFrame.

        The FeatureStore stores close prices only.  We synthesise plausible
        open/high/low values so the inner strategy's sub-signals (which use
        OHLCV) receive structurally valid data.

        Synthetic rules:
          - open  = previous close (shift by 1, backfill first bar)
          - high  = max(open, close) * (1 + small random noise seeded on index)
          - low   = min(open, close) * (1 - small random noise seeded on index)
          - volume= constant placeholder (1_000_000); volume-based sub-signal
                    will produce a near-zero score which is acceptable.
        """
        close = np.asarray(prices, dtype=float)
        n = len(close)

        opn = np.empty(n, dtype=float)
        opn[0] = close[0]
        opn[1:] = close[:-1]

        # Deterministic "noise" based on returns so results are reproducible
        returns = np.abs(np.diff(close, prepend=close[0])) / (close + 1e-8)
        spread = np.clip(returns * 0.5, 0.001, 0.02)

        high = np.maximum(opn, close) * (1 + spread)
        low = np.minimum(opn, close) * (1 - spread)
        volume = np.full(n, 1_000_000.0)

        idx = pd.RangeIndex(n, name="bar")
        df = pd.DataFrame(
            {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )
        return df

    # ------------------------------------------------------------------ #
    # Asset-class mapping
    # ------------------------------------------------------------------ #

    @staticmethod
    def _asset_class_for(symbol: str):
        """Determine the AssetClass for a symbol."""
        from ...master_bot import AssetClass

        if symbol in EQUITY_SYMBOLS:
            # Equity symbols are routed through the options pipeline for
            # execution, but scored as stock options for asset-class tagging.
            return AssetClass.ETF_OPTIONS
        return AssetClass.CRYPTO_SPOT
