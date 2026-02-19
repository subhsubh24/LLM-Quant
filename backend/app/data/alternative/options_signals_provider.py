"""
Options-derived signals provider.

Options markets contain FORWARD-LOOKING information that stock prices
don't. When someone buys a put option, they're literally betting on
a price decline. Aggregate this across all market participants and
you get one of the most powerful predictive signals available.

KEY SIGNALS:

CBOE PUT/CALL RATIO:
  - Total puts traded / total calls traded
  - High ratio (>1.0) = excessive fear = contrarian bullish
  - Low ratio (<0.7) = complacency = contrarian bearish
  - 10-day moving average smooths noise
  - CBOE publishes this daily for free

CBOE SKEW INDEX:
  - Measures the perceived tail risk in S&P 500 options
  - Higher SKEW = market pricing in higher probability of a crash
  - Normal: 100-120, Elevated: 120-140, Extreme: >140
  - Available free from CBOE

IMPLIED VOLATILITY TERM STRUCTURE:
  - Compare near-term IV vs longer-term IV
  - Inverted (near > far) = immediate fear, hedging demand
  - Normal (near < far) = calm, carry trade profitable
  - We approximate this from VIX vs VIX3M (already in sentiment provider)

VOLATILITY RISK PREMIUM (VRP):
  - Implied vol (VIX) minus realized vol (actual S&P movement)
  - Positive VRP = options are expensive relative to reality
  - Negative VRP = rare, means realized vol exceeds expectations = crisis
  - The VRP averages +4-5 vol points and is a profitable carry trade

OPTIONS VOLUME RATIOS:
  - Single stock put/call ratios predict individual stock moves
  - Unusual options activity (big put buys) often precedes bad news
  - Equity-only P/C ratio is more predictive than index P/C
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class OptionsSignalsProvider(AlternativeDataProvider):
    """
    Computes options-derived market signals.

    Uses freely available data:
    - CBOE put/call ratio (via yfinance proxy or direct)
    - VIX vs realized vol for volatility risk premium
    - CBOE SKEW index
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "options_signals"

    def get_feature_names(self) -> List[str]:
        return [
            # Volatility risk premium
            "opt_vrp",
            "opt_vrp_zscore_21d",
            "opt_vrp_percentile_63d",
            # Realized vs implied vol spread
            "opt_realized_vol_21d",
            "opt_implied_minus_realized",
            # VIX level transformations for options context
            "opt_vix_squared",
            "opt_vix_regime",
            # SKEW proxy
            "opt_skew_proxy",
            "opt_skew_zscore_21d",
            # Gamma exposure proxy
            "opt_gamma_proxy",
            # Variance swap proxy (VIX^2 / 100)
            "opt_variance_swap",
            "opt_variance_swap_chg_5d",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch and compute options-derived signals."""
        result = pd.DataFrame()

        # Fetch VIX and SPY for VRP computation
        vix_data, spy_data = self._fetch_vix_spy(start_date, end_date)

        if vix_data is not None and spy_data is not None:
            vrp_features = self._compute_vrp(vix_data, spy_data)
            if not vrp_features.empty:
                result = pd.concat([result, vrp_features], axis=1)

        # Compute SKEW proxy from VIX behavior
        if vix_data is not None and spy_data is not None:
            skew_features = self._compute_skew_proxy(vix_data, spy_data)
            if not skew_features.empty:
                result = pd.concat([result, skew_features], axis=1)

        # Gamma exposure proxy
        if vix_data is not None:
            gamma_features = self._compute_gamma_proxy(vix_data)
            if not gamma_features.empty:
                result = pd.concat([result, gamma_features], axis=1)

        # Variance swap features
        if vix_data is not None:
            var_features = self._compute_variance_features(vix_data)
            if not var_features.empty:
                result = pd.concat([result, var_features], axis=1)

        if not result.empty:
            result = self._resample_to_daily(result)

        logger.info(
            f"Options signals: computed {len(result.columns)} features"
        )
        return result

    def _fetch_vix_spy(self, start_date, end_date):
        """Fetch VIX and SPY data for VRP computation."""
        try:
            import yfinance as yf

            extended_start = start_date - timedelta(days=365)

            vix = yf.Ticker("^VIX")
            vix_data = vix.history(start=extended_start, end=end_date + timedelta(days=1))

            spy = yf.Ticker("SPY")
            spy_data = spy.history(start=extended_start, end=end_date + timedelta(days=1))

            if vix_data.empty or spy_data.empty:
                return None, None

            vix_data.index = vix_data.index.tz_localize(None)
            spy_data.index = spy_data.index.tz_localize(None)

            return vix_data["Close"], spy_data["Close"]

        except Exception as e:
            logger.warning(f"Failed to fetch VIX/SPY: {e}")
            return None, None

    def _compute_vrp(
        self, vix: pd.Series, spy: pd.Series
    ) -> pd.DataFrame:
        """
        Volatility Risk Premium = Implied Vol - Realized Vol.

        The VRP is the market's "insurance premium" for volatility.
        When it's high, selling options is profitable (risk premium harvest).
        When it's negative, the market is in crisis (realized > expected).
        """
        result = pd.DataFrame(index=vix.index)

        # Realized vol: annualized std of SPY log returns
        spy_ret = np.log(spy / spy.shift(1))
        realized_vol_21d = spy_ret.rolling(21).std() * np.sqrt(252) * 100

        # VIX is implied vol (annualized, in percentage points)
        result["opt_realized_vol_21d"] = realized_vol_21d

        # VRP = VIX - Realized Vol
        vrp = vix - realized_vol_21d
        result["opt_vrp"] = vrp

        # Implied minus realized (same as VRP but clearer name)
        result["opt_implied_minus_realized"] = vrp

        # VRP z-score
        vrp_mean = vrp.rolling(63, min_periods=21).mean()
        vrp_std = vrp.rolling(63, min_periods=21).std()
        result["opt_vrp_zscore_21d"] = ((vrp - vrp_mean) / (vrp_std + 1e-8)).clip(-4, 4)

        # VRP percentile
        result["opt_vrp_percentile_63d"] = vrp.rolling(63, min_periods=21).apply(
            lambda x: (x.iloc[-1] > x[:-1]).mean() if len(x) > 1 else np.nan,
            raw=False,
        )

        return result

    def _compute_skew_proxy(
        self, vix: pd.Series, spy: pd.Series
    ) -> pd.DataFrame:
        """
        SKEW proxy: relationship between VIX moves and SPY moves.

        When VIX spikes much more on down days than it drops on up days,
        the market is pricing in significant tail risk (high skew).
        """
        result = pd.DataFrame(index=vix.index)

        vix_ret = vix.pct_change()
        spy_ret = np.log(spy / spy.shift(1))

        # Skew proxy: ratio of VIX change on down days vs up days
        # Rolling 21-day window
        def compute_skew_ratio(window_vix_ret, window_spy_ret):
            down_days = window_spy_ret < 0
            up_days = window_spy_ret > 0
            if down_days.sum() == 0 or up_days.sum() == 0:
                return np.nan
            avg_vix_on_down = window_vix_ret[down_days].mean()
            avg_vix_on_up = window_vix_ret[up_days].mean()
            # On down days VIX should go up, on up days VIX should go down
            # Higher ratio = more convexity = higher skew
            return avg_vix_on_down / (abs(avg_vix_on_up) + 1e-8)

        # Rolling skew computation
        skew_values = []
        for i in range(len(vix_ret)):
            if i < 21:
                skew_values.append(np.nan)
                continue
            w_vix = vix_ret.iloc[i-21:i]
            w_spy = spy_ret.iloc[i-21:i]
            skew_values.append(compute_skew_ratio(w_vix, w_spy))

        skew = pd.Series(skew_values, index=vix.index)
        result["opt_skew_proxy"] = skew

        # Skew z-score
        skew_mean = skew.rolling(63, min_periods=21).mean()
        skew_std = skew.rolling(63, min_periods=21).std()
        result["opt_skew_zscore_21d"] = (
            (skew - skew_mean) / (skew_std + 1e-8)
        ).clip(-4, 4)

        return result

    def _compute_gamma_proxy(self, vix: pd.Series) -> pd.DataFrame:
        """
        Gamma exposure proxy.

        When VIX is low and stable, market makers are long gamma
        (they dampen volatility). When VIX is high and rising,
        market makers are short gamma (they amplify volatility).

        This drives the difference between "grinding up" and "crashing."
        """
        result = pd.DataFrame(index=vix.index)

        # VIX level * VIX rate of change = gamma regime proxy
        vix_chg = vix.diff(5) / (vix.shift(5) + 1e-8)

        # Negative = long gamma (low and falling VIX, stable market)
        # Positive = short gamma (high and rising VIX, volatile market)
        result["opt_gamma_proxy"] = vix * vix_chg / 100  # Scale down

        # VIX regime (quadratic captures the convexity)
        result["opt_vix_squared"] = (vix / 100) ** 2

        # Discrete regime
        regime = pd.cut(
            vix,
            bins=[0, 12, 16, 20, 25, 30, 100],
            labels=[0, 1, 2, 3, 4, 5],
        )
        result["opt_vix_regime"] = pd.to_numeric(regime, errors='coerce').fillna(2.0)

        return result

    def _compute_variance_features(self, vix: pd.Series) -> pd.DataFrame:
        """
        Variance swap features.

        VIX^2 / 100 approximates the fair value of a 30-day variance swap.
        Changes in the variance swap level are more informative than
        changes in VIX because variance is what's actually priced.
        """
        result = pd.DataFrame(index=vix.index)

        var_swap = (vix ** 2) / 100
        result["opt_variance_swap"] = var_swap

        var_swap_chg = var_swap.diff(5) / (var_swap.shift(5) + 1e-8)
        result["opt_variance_swap_chg_5d"] = var_swap_chg.clip(-2, 2)

        return result
