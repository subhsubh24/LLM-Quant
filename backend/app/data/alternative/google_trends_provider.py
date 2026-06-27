"""
Google Trends data provider.

Google search volume is a direct measure of PUBLIC ATTENTION and INTENT.
When millions of people search for something, it reveals aggregate
behavior that moves markets.

KEY RESEARCH:

"Quantifying Trading Behavior in Financial Markets Using Google Trends"
(Preis, Moat & Stanley, Scientific Reports, 2013):
  - Increases in Google searches for financial terms PRECEDED market declines
  - A strategy based on "debt" search volume beat the market significantly
  - Search volume captures retail investor fear before it shows up in prices

PROVEN SEARCH TERMS:

Financial stress:
  - "stock market crash" - spikes before/during selloffs
  - "recession" - leads actual recessions by 3-6 months
  - "unemployment" - correlates with jobless claims

Consumer behavior:
  - "buy house" / "sell house" - leads housing market
  - "best savings account" - risk aversion proxy
  - "Bitcoin" - crypto retail mania gauge

Company-specific:
  - "[Company name] layoffs" - leads bad earnings
  - "[Company name] stock" - attention drives volatility

HOW TO USE:
  - The pytrends library provides free access to Google Trends
  - Weekly data updated with ~3 day lag
  - Relative scale (0-100 within the period), not absolute
  - Compare a term's current level to its own history
  - Rate of change matters more than level
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging
import time

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# Search terms that predict market movements
MARKET_SEARCH_TERMS = {
    # Fear/stress indicators
    "financial_fear": ["stock market crash", "recession", "market crash"],
    # Economic concern
    "economic_worry": ["unemployment", "layoffs", "inflation rate"],
    # Risk appetite
    "risk_appetite": ["buy stocks", "invest money", "stock tips"],
    # Safe haven
    "safe_haven": ["gold price", "treasury bonds", "savings account"],
    # Speculation
    "speculation": ["bitcoin", "crypto", "options trading"],
}


class GoogleTrendsProvider(AlternativeDataProvider):
    """
    Fetches Google Trends data for market-predictive search terms.

    Uses pytrends library (free, no API key). Rate limited by Google,
    so we batch requests and cache aggressively.

    Falls back to a proxy when pytrends is unavailable.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._cache: dict = {}

    @property
    def name(self) -> str:
        return "google_trends"

    def get_feature_names(self) -> List[str]:
        names = []
        for category in MARKET_SEARCH_TERMS:
            names.append(f"gtrends_{category}")
            names.append(f"gtrends_{category}_zscore")
            names.append(f"gtrends_{category}_momentum")
        # Composite
        names.append("gtrends_fear_index")
        names.append("gtrends_greed_index")
        names.append("gtrends_attention_index")
        return names

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch Google Trends data for all configured search terms."""
        result = pd.DataFrame()

        # Try pytrends first
        pytrends_data = self._fetch_via_pytrends(start_date, end_date)
        if pytrends_data is not None and not pytrends_data.empty:
            result = pytrends_data
        else:
            # Fall back to VIX-based proxy
            logger.info("Google Trends: using market-based proxy")
            result = self._compute_proxy(start_date, end_date)

        if not result.empty:
            # Compute composite indices
            self._compute_composites(result)
            result = self._resample_to_daily(result)

        logger.info(f"Google Trends: {len(result.columns)} features")
        return result

    def _fetch_via_pytrends(
        self,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.DataFrame]:
        """Fetch actual Google Trends data via pytrends."""
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=360)
            result = pd.DataFrame()

            for category, terms in MARKET_SEARCH_TERMS.items():
                try:
                    # Use first term in each category as primary
                    primary_term = terms[0]
                    timeframe = f"{start_date.isoformat()} {end_date.isoformat()}"

                    pytrends.build_payload(
                        [primary_term],
                        timeframe=timeframe,
                        geo="US",
                    )
                    interest = pytrends.interest_over_time()

                    if not interest.empty and primary_term in interest.columns:
                        series = interest[primary_term].astype(float)
                        result[f"gtrends_{category}"] = series

                        # Z-score (relative to own history)
                        # pytrends returns WEEKLY data, so use weekly-appropriate
                        # windows: rolling(12) ≈ 3 months, diff(4) ≈ 4 weeks
                        mean = series.rolling(12, min_periods=4).mean()
                        std = series.rolling(12, min_periods=4).std()
                        result[f"gtrends_{category}_zscore"] = (
                            (series - mean) / (std + 1e-8)
                        ).clip(-4, 4)

                        # Momentum (current vs ~4 weeks ago)
                        result[f"gtrends_{category}_momentum"] = series.diff(4)

                    # Rate limit: Google limits requests
                    time.sleep(2)

                except Exception as e:
                    logger.debug(f"pytrends failed for '{category}': {e}")
                    continue

            return result if not result.empty else None

        except ImportError:
            logger.debug("pytrends not installed (pip install pytrends)")
            return None
        except Exception as e:
            logger.debug(f"pytrends failed: {e}")
            return None

    def _compute_proxy(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Proxy Google Trends data using market signals.

        Research shows Google search volume for financial terms
        correlates strongly with:
        - VIX (fear terms)
        - Market returns (greed terms)
        - Trading volume (attention terms)
        """
        result = pd.DataFrame()

        try:
            import yfinance as yf

            extended_start = start_date - timedelta(days=180)

            spy = yf.Ticker("SPY")
            spy_data = spy.history(start=extended_start, end=end_date + timedelta(days=1))

            vix = yf.Ticker("^VIX")
            vix_data = vix.history(start=extended_start, end=end_date + timedelta(days=1))

            if spy_data.empty or vix_data.empty:
                return result

            spy_close = spy_data["Close"]
            spy_vol = spy_data["Volume"]
            vix_close = vix_data["Close"]

            spy_close.index = spy_close.index.tz_localize(None)
            spy_vol.index = spy_vol.index.tz_localize(None)
            vix_close.index = vix_close.index.tz_localize(None)

            common = spy_close.index.intersection(vix_close.index)
            result = pd.DataFrame(index=common)

            # Fear proxy: VIX level + negative returns
            spy_ret = np.log(spy_close / spy_close.shift(1)).reindex(common)
            vix_z = ((vix_close - vix_close.rolling(63).mean()) /
                     (vix_close.rolling(63).std() + 1e-8)).reindex(common)
            ret_21d = spy_ret.rolling(21).mean()

            # Financial fear ~ high VIX + negative returns
            fear = (vix_z * 0.7 + (-ret_21d * 100) * 0.3).clip(-3, 3)
            result["gtrends_financial_fear"] = fear
            result["gtrends_financial_fear_zscore"] = fear  # Already z-scored
            result["gtrends_financial_fear_momentum"] = fear.diff(21)

            # Economic worry ~ similar to fear but slower moving
            econ_worry = fear.rolling(21).mean()
            result["gtrends_economic_worry"] = econ_worry
            result["gtrends_economic_worry_zscore"] = econ_worry
            result["gtrends_economic_worry_momentum"] = econ_worry.diff(21)

            # Risk appetite ~ positive returns + falling VIX
            risk_app = (-vix_z * 0.5 + ret_21d * 100 * 0.5).clip(-3, 3)
            result["gtrends_risk_appetite"] = risk_app
            result["gtrends_risk_appetite_zscore"] = risk_app
            result["gtrends_risk_appetite_momentum"] = risk_app.diff(21)

            # Safe haven ~ VIX high + gold doing well
            result["gtrends_safe_haven"] = vix_z.clip(0, 3)
            result["gtrends_safe_haven_zscore"] = vix_z.clip(-3, 3)
            result["gtrends_safe_haven_momentum"] = vix_z.diff(21)

            # Speculation ~ volume + positive returns
            vol_z = ((spy_vol - spy_vol.rolling(63).mean()) /
                     (spy_vol.rolling(63).std() + 1e-8)).reindex(common)
            spec = (vol_z * 0.5 + ret_21d * 100 * 0.5).clip(-3, 3)
            result["gtrends_speculation"] = spec
            result["gtrends_speculation_zscore"] = spec
            result["gtrends_speculation_momentum"] = spec.diff(21)

        except Exception as e:
            logger.warning(f"Google Trends proxy failed: {e}")

        return result

    def _compute_composites(self, result: pd.DataFrame) -> None:
        """Compute composite Google Trends indices."""
        # Fear index: average of fear-related z-scores
        fear_cols = [c for c in result.columns if "fear" in c and "zscore" in c]
        worry_cols = [c for c in result.columns if "worry" in c and "zscore" in c]
        safe_cols = [c for c in result.columns if "safe" in c and "zscore" in c]

        fear_all = fear_cols + worry_cols + safe_cols
        if fear_all:
            result["gtrends_fear_index"] = result[fear_all].mean(axis=1)

        # Greed index: risk appetite + speculation
        greed_cols = [c for c in result.columns if
                      ("appetite" in c or "speculation" in c) and "zscore" in c]
        if greed_cols:
            result["gtrends_greed_index"] = result[greed_cols].mean(axis=1)

        # Attention index: absolute values of all z-scores (high attention either way)
        zscore_cols = [c for c in result.columns if "zscore" in c]
        if zscore_cols:
            result["gtrends_attention_index"] = result[zscore_cols].abs().mean(axis=1)
