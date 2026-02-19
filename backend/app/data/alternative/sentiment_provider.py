"""
Market sentiment and positioning data provider.

Sentiment data captures the BEHAVIORAL dimension of markets that
price data alone cannot. This is crucial because:

1. Markets are driven by humans (and their algorithms)
2. Extreme sentiment readings mean-revert
3. Positioning data reveals crowding and potential squeezes

KEY SENTIMENT SIGNALS:

VIX Term Structure:
  - The single most predictive volatility signal
  - Contango (VIX < VX2) = normal, carry trade works
  - Backwardation (VIX > VX2) = panic, equity drawdown imminent
  - 5-day change in term structure predicts 1-month equity returns

Put/Call Ratio:
  - High P/C = excessive hedging = contrarian bullish
  - Low P/C = complacency = contrarian bearish
  - Works best at extremes (>1.2 or <0.6)

Market Breadth (Advance/Decline):
  - Divergence from price = weakening trend
  - When indices rise but breadth narrows = distribution
  - Breadth thrust (>90% advancing) = strong buy signal

New Highs vs New Lows:
  - Leading indicator of trend health
  - Divergence warns of reversals

Margin Debt:
  - Leverage proxy
  - Rising margin debt = confidence (but potential fragility)
  - Sharp declines = forced liquidation risk
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class SentimentProvider(AlternativeDataProvider):
    """
    Fetches and computes market sentiment indicators.

    Uses free data sources:
    - yfinance for VIX, VIX futures proxies
    - Market breadth from ETF proxies
    - Computed sentiment composites
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "sentiment"

    def get_feature_names(self) -> List[str]:
        return [
            # VIX features
            "sent_vix_level",
            "sent_vix_percentile_63d",
            "sent_vix_zscore_21d",
            "sent_vix_chg_5d",
            "sent_vix_term_structure",
            "sent_vix_contango",
            # Market breadth proxies
            "sent_breadth_advance_pct",
            "sent_breadth_mcclellan",
            "sent_breadth_thrust",
            # Risk regime
            "sent_risk_regime_score",
            "sent_fear_greed_proxy",
            # Equity put/call proxy
            "sent_skew_proxy",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch and compute sentiment indicators."""
        result = pd.DataFrame()

        # 1. VIX-based sentiment
        vix_features = self._compute_vix_features(start_date, end_date)
        if not vix_features.empty:
            result = pd.concat([result, vix_features], axis=1)

        # 2. Market breadth (from sector ETFs)
        breadth_features = self._compute_breadth_features(start_date, end_date)
        if not breadth_features.empty:
            result = pd.concat([result, breadth_features], axis=1)

        # 3. Composite risk/sentiment scores
        if not result.empty:
            self._compute_composites(result)

        if not result.empty:
            result = self._resample_to_daily(result)

        logger.info(
            f"Sentiment: computed {len(result.columns)} features, "
            f"{len(result)} days"
        )

        return result

    def _compute_vix_features(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Compute VIX-derived features.

        The VIX is the market's real-time fear gauge. But the RAW level
        is less useful than its CONTEXT: percentile, rate of change,
        and term structure.
        """
        result = pd.DataFrame()

        try:
            import yfinance as yf

            extended_start = start_date - timedelta(days=365)

            # VIX spot
            vix = yf.Ticker("^VIX")
            vix_data = vix.history(
                start=extended_start,
                end=end_date + timedelta(days=1),
            )

            if vix_data.empty:
                return result

            vix_close = vix_data["Close"]
            vix_close.index = vix_close.index.tz_localize(None)

            # VIX level (raw)
            result["sent_vix_level"] = vix_close

            # VIX percentile over trailing 63 days (quarterly context)
            result["sent_vix_percentile_63d"] = vix_close.rolling(63).apply(
                lambda x: (x.iloc[-1] > x[:-1]).mean() if len(x) > 1 else np.nan,
                raw=False,
            )

            # VIX z-score (21-day)
            vix_mean = vix_close.rolling(21).mean()
            vix_std = vix_close.rolling(21).std()
            result["sent_vix_zscore_21d"] = (vix_close - vix_mean) / (vix_std + 1e-8)

            # VIX 5-day change (rate of fear increase)
            result["sent_vix_chg_5d"] = vix_close.diff(5) / (vix_close.shift(5) + 1e-8)

            # VIX term structure (using VXX as short-term proxy)
            vix_ts = self._compute_vix_term_structure(extended_start, end_date)
            if vix_ts is not None:
                result["sent_vix_term_structure"] = vix_ts["term_structure"]
                result["sent_vix_contango"] = vix_ts["contango"]

        except Exception as e:
            logger.warning(f"Failed to compute VIX features: {e}")

        return result

    def _compute_vix_term_structure(
        self,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.DataFrame]:
        """
        VIX term structure: compare short-term vs medium-term VIX.

        Uses VIX (spot) vs VIX3M or approximated from VXX behavior.
        Contango (front < back) = normal market
        Backwardation (front > back) = stress
        """
        try:
            import yfinance as yf

            # Try VIX3M (3-month VIX) for term structure
            vix3m = yf.Ticker("^VIX3M")
            vix3m_data = vix3m.history(
                start=start_date,
                end=end_date + timedelta(days=1),
            )

            vix = yf.Ticker("^VIX")
            vix_data = vix.history(
                start=start_date,
                end=end_date + timedelta(days=1),
            )

            if vix3m_data.empty or vix_data.empty:
                return None

            vix_close = vix_data["Close"]
            vix3m_close = vix3m_data["Close"]

            vix_close.index = vix_close.index.tz_localize(None)
            vix3m_close.index = vix3m_close.index.tz_localize(None)

            # Align indices
            common = vix_close.index.intersection(vix3m_close.index)
            if len(common) == 0:
                return None

            vix_aligned = vix_close.loc[common]
            vix3m_aligned = vix3m_close.loc[common]

            result = pd.DataFrame(index=common)

            # Term structure ratio: VIX / VIX3M
            # < 1 = contango (normal), > 1 = backwardation (stress)
            result["term_structure"] = vix_aligned / (vix3m_aligned + 1e-8)

            # Binary contango indicator
            result["contango"] = (result["term_structure"] < 1.0).astype(float)

            return result

        except Exception as e:
            logger.debug(f"VIX term structure failed: {e}")
            return None

    def _compute_breadth_features(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Market breadth approximation using sector ETF returns.

        True breadth (advance/decline data) requires paid data.
        We approximate using sector ETF agreement as a proxy.
        If most sectors are up, breadth is strong; if only a few, it's weak.
        """
        result = pd.DataFrame()

        # Use sector ETFs to approximate breadth
        sector_tickers = [
            "XLF", "XLE", "XLU", "XLP", "XLK", "XLV",
            "XLI", "XLB", "XLY", "XLRE", "XLC",
        ]

        try:
            import yfinance as yf

            extended_start = start_date - timedelta(days=90)

            data = yf.download(
                sector_tickers,
                start=extended_start,
                end=end_date + timedelta(days=1),
                auto_adjust=True,
                threads=True,
            )

            if data.empty:
                return result

            prices = data["Close"]
            prices.index = pd.to_datetime(prices.index).tz_localize(None)

            # Daily returns for each sector
            returns = prices.pct_change()

            # Breadth: % of sectors with positive daily return
            result["sent_breadth_advance_pct"] = (returns > 0).mean(axis=1)

            # McClellan-style oscillator (19-day EMA - 39-day EMA of breadth)
            breadth = (returns > 0).mean(axis=1) - 0.5  # Center around 0
            ema_19 = breadth.ewm(span=19, min_periods=10).mean()
            ema_39 = breadth.ewm(span=39, min_periods=20).mean()
            result["sent_breadth_mcclellan"] = ema_19 - ema_39

            # Breadth thrust: 10-day sum of advancing % > 0.6
            result["sent_breadth_thrust"] = (
                (returns > 0).mean(axis=1).rolling(10).mean()
            )

        except Exception as e:
            logger.warning(f"Failed to compute breadth features: {e}")

        return result

    def _compute_composites(self, result: pd.DataFrame) -> None:
        """
        Compute composite sentiment scores from individual indicators.

        These combine multiple signals into single risk/sentiment measures.
        """
        # Risk regime score (combines VIX and breadth)
        components = []

        if "sent_vix_zscore_21d" in result.columns:
            # Invert VIX z-score (high VIX = low risk appetite)
            components.append(-result["sent_vix_zscore_21d"])

        if "sent_breadth_advance_pct" in result.columns:
            # Breadth: rescale to [-1, 1]
            components.append(2 * result["sent_breadth_advance_pct"] - 1)

        if "sent_vix_contango" in result.columns:
            # Contango = risk-on (1), backwardation = risk-off (0)
            components.append(2 * result["sent_vix_contango"] - 1)

        if components:
            result["sent_risk_regime_score"] = (
                pd.concat(components, axis=1).mean(axis=1)
            )

        # Fear & Greed proxy (simplified CNN-style)
        # Scale: -1 (extreme fear) to +1 (extreme greed)
        fg_components = []

        if "sent_vix_percentile_63d" in result.columns:
            # Low VIX percentile = greed, high = fear
            fg_components.append(1 - 2 * result["sent_vix_percentile_63d"])

        if "sent_breadth_thrust" in result.columns:
            fg_components.append(2 * result["sent_breadth_thrust"] - 1)

        if fg_components:
            result["sent_fear_greed_proxy"] = (
                pd.concat(fg_components, axis=1).mean(axis=1)
            )

        # Skew proxy (VIX level relative to recent realized vol of SPY)
        if "sent_vix_level" in result.columns:
            # When implied vol (VIX) >> realized vol, put buying is extreme
            result["sent_skew_proxy"] = result["sent_vix_zscore_21d"].clip(-3, 3) if "sent_vix_zscore_21d" in result.columns else np.nan
