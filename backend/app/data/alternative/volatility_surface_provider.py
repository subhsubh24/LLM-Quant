"""
Volatility surface and term structure signals provider.

WHY THE VOL SURFACE MATTERS:

1. TERM STRUCTURE SLOPE:
   - Compare VIX (30d) vs VIX3M (90d) vs VIX6M (180d)
   - Flat/inverted = fear is HERE, not just expected
   - Steep contango = complacency, great for vol selling
   - Term structure is the #1 predictor of VIX futures returns

2. REALIZED VS IMPLIED DECOMPOSITION:
   - Separate VIX into realized vol + risk premium + jump component
   - Jump risk premium spikes before actual crashes
   - Mean-reverting risk premium = profitable carry trade

3. VARIANCE RISK PREMIUM:
   - VIX^2 (implied variance) vs realized variance
   - Systematically positive (insurance premium)
   - When it goes negative = extreme stress
   - Hedge fund strategy: harvest VRP in normal times

4. VOL-OF-VOL (VVIX):
   - Volatility of VIX itself = uncertainty about uncertainty
   - High VVIX = options on VIX are expensive = tail risk demand
   - VVIX/VIX ratio captures "fear of fear"

5. CROSS-ASSET VOL SIGNALS:
   - Bond vol (MOVE) vs equity vol (VIX) ratio
   - When MOVE leads VIX higher = rates driving the selloff
   - Currency vol (CVIX) spike = global macro stress

IMPLEMENTATION:
   Uses VIX, VIX3M, VIX9D, VVIX from CBOE via yfinance (free).
   Computes term structure, risk premium decomposition, and vol regime.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class VolatilitySurfaceProvider(AlternativeDataProvider):
    """
    Volatility surface and term structure signals.

    Extracts forward-looking information from the volatility curve
    that simple VIX level misses. The SHAPE of the vol surface
    is more predictive than its level.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "vol_surface"

    def get_feature_names(self) -> List[str]:
        return [
            # Term structure
            "vol_term_slope_30_90",       # VIX / VIX3M ratio
            "vol_term_slope_chg_5d",      # 5d change in term structure
            "vol_term_contango",          # Binary: contango (1) or backwardation (0)
            "vol_term_curvature",         # Convexity of the term structure
            # Risk premium
            "vol_risk_premium",           # Implied - realized (annualized)
            "vol_risk_premium_zscore",    # Z-score of risk premium
            "vol_risk_premium_regime",    # Regime: positive (normal), negative (stress)
            # Vol-of-vol
            "vol_vvix_level",             # VVIX (vol of VIX)
            "vol_vvix_zscore",            # VVIX z-score
            "vol_vvix_vix_ratio",         # VVIX/VIX = fear intensity per unit vol
            # Realized vol components
            "vol_realized_5d",            # 5-day realized vol (fast)
            "vol_realized_21d",           # 21-day realized vol (slow)
            "vol_realized_ratio",         # Fast/slow vol ratio (acceleration)
            # Vol regime
            "vol_regime_compressed",      # Vol below 5th percentile of 1yr range
            "vol_regime_exploding",       # Vol above 95th percentile of 1yr range
            "vol_mean_reversion_signal",  # Distance from long-term mean (mean-reversion)
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch vol surface data and compute features."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - vol surface unavailable")
            return pd.DataFrame()

        extended_start = start_date - timedelta(days=365)
        result = pd.DataFrame()

        try:
            # Fetch VIX family
            tickers = {"^VIX": "vix", "^VIX3M": "vix3m", "^VIX9D": "vix9d", "^VVIX": "vvix"}
            data = {}

            for ticker, name in tickers.items():
                try:
                    t = yf.Ticker(ticker)
                    hist = t.history(start=extended_start, end=end_date + timedelta(days=1))
                    if not hist.empty:
                        close = hist["Close"]
                        close.index = self._make_tz_naive(close.index)
                        data[name] = close
                except Exception:
                    continue

            if "vix" not in data:
                logger.warning("VIX data unavailable - vol surface skipped")
                return pd.DataFrame()

            # Fetch SPY for realized vol
            spy = yf.Ticker("SPY")
            spy_data = spy.history(start=extended_start, end=end_date + timedelta(days=1))
            if not spy_data.empty:
                spy_close = spy_data["Close"]
                spy_close.index = self._make_tz_naive(spy_close.index)
                data["spy"] = spy_close

            result = self._compute_features(data)

        except Exception as e:
            logger.warning(f"Vol surface provider failed: {e}")

        if not result.empty:
            result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
            result = result.ffill().fillna(0.0)

        logger.info(f"Vol surface: {len(result.columns)} features")
        return result

    def _compute_features(self, data: dict) -> pd.DataFrame:
        """Compute vol surface features from VIX family data."""
        vix = data["vix"]
        result = pd.DataFrame(index=vix.index)
        eps = 1e-8

        # === TERM STRUCTURE ===
        if "vix3m" in data:
            vix3m = data["vix3m"]
            common = vix.index.intersection(vix3m.index)
            if len(common) > 0:
                v = vix.loc[common]
                v3m = vix3m.loc[common]

                # Slope: VIX / VIX3M (< 1 = contango, > 1 = backwardation)
                slope = v / (v3m + eps)
                result["vol_term_slope_30_90"] = slope
                result["vol_term_slope_chg_5d"] = slope.diff(5)
                result["vol_term_contango"] = (slope < 1.0).astype(float)

                # Curvature (if 9-day VIX available)
                if "vix9d" in data:
                    vix9d = data["vix9d"]
                    common3 = common.intersection(vix9d.index)
                    if len(common3) > 20:
                        v9 = vix9d.loc[common3]
                        v30 = vix.loc[common3]
                        v90 = vix3m.loc[common3]
                        # Curvature = 2*VIX30 - VIX9 - VIX90 (butterfly)
                        curvature = (2 * v30 - v9 - v90) / (v30 + eps)
                        result["vol_term_curvature"] = curvature.reindex(vix.index)
                    else:
                        result["vol_term_curvature"] = 0.0
                else:
                    result["vol_term_curvature"] = 0.0
        else:
            # Fallback: estimate term structure from VIX dynamics
            result["vol_term_slope_30_90"] = 0.95  # Assume normal contango
            result["vol_term_slope_chg_5d"] = 0.0
            result["vol_term_contango"] = 1.0
            result["vol_term_curvature"] = 0.0

        # === RISK PREMIUM ===
        if "spy" in data:
            spy = data["spy"]
            common = vix.index.intersection(spy.index)
            if len(common) > 0:
                spy_aligned = spy.loc[common]
                spy_ret = np.log(spy_aligned / spy_aligned.shift(1))
                realized_21d = spy_ret.rolling(21, min_periods=10).std() * np.sqrt(252) * 100

                vix_aligned = vix.loc[common]
                risk_premium = vix_aligned - realized_21d
                result["vol_risk_premium"] = risk_premium.reindex(vix.index)

                rp_mean = risk_premium.rolling(63, min_periods=21).mean()
                rp_std = risk_premium.rolling(63, min_periods=21).std()
                result["vol_risk_premium_zscore"] = (
                    (risk_premium - rp_mean) / (rp_std + eps)
                ).clip(-4, 4).reindex(vix.index)

                # Regime: negative risk premium = crisis
                result["vol_risk_premium_regime"] = (risk_premium < 0).astype(float).reindex(vix.index)
        else:
            result["vol_risk_premium"] = 0.0
            result["vol_risk_premium_zscore"] = 0.0
            result["vol_risk_premium_regime"] = 0.0

        # === VOL-OF-VOL (VVIX) ===
        if "vvix" in data:
            vvix = data["vvix"]
            common = vix.index.intersection(vvix.index)
            if len(common) > 0:
                vv = vvix.loc[common]
                result["vol_vvix_level"] = vv.reindex(vix.index)

                vv_mean = vv.rolling(63, min_periods=21).mean()
                vv_std = vv.rolling(63, min_periods=21).std()
                result["vol_vvix_zscore"] = (
                    (vv - vv_mean) / (vv_std + eps)
                ).clip(-4, 4).reindex(vix.index)

                # VVIX/VIX ratio = fear intensity per unit vol
                v_common = vix.loc[common]
                result["vol_vvix_vix_ratio"] = (vv / (v_common + eps)).reindex(vix.index)
            else:
                result["vol_vvix_level"] = 0.0
                result["vol_vvix_zscore"] = 0.0
                result["vol_vvix_vix_ratio"] = 0.0
        else:
            # Approximate VVIX from VIX dynamics
            vix_ret = vix.pct_change()
            vix_vol = vix_ret.rolling(21, min_periods=10).std() * np.sqrt(252) * 100
            result["vol_vvix_level"] = vix_vol
            vv_mean = vix_vol.rolling(63, min_periods=21).mean()
            vv_std = vix_vol.rolling(63, min_periods=21).std()
            result["vol_vvix_zscore"] = ((vix_vol - vv_mean) / (vv_std + eps)).clip(-4, 4)
            result["vol_vvix_vix_ratio"] = vix_vol / (vix + eps)

        # === REALIZED VOL COMPONENTS ===
        if "spy" in data:
            spy = data["spy"]
            common = vix.index.intersection(spy.index)
            spy_ret = np.log(spy.loc[common] / spy.loc[common].shift(1))

            vol_5d = spy_ret.rolling(5, min_periods=3).std() * np.sqrt(252) * 100
            vol_21d = spy_ret.rolling(21, min_periods=10).std() * np.sqrt(252) * 100

            result["vol_realized_5d"] = vol_5d.reindex(vix.index)
            result["vol_realized_21d"] = vol_21d.reindex(vix.index)
            result["vol_realized_ratio"] = (vol_5d / (vol_21d + eps)).reindex(vix.index)
        else:
            result["vol_realized_5d"] = 0.0
            result["vol_realized_21d"] = 0.0
            result["vol_realized_ratio"] = 1.0

        # === VOL REGIME ===
        # Percentile-based regime detection
        vix_pctile_low = vix.rolling(252, min_periods=63).quantile(0.05)
        vix_pctile_high = vix.rolling(252, min_periods=63).quantile(0.95)
        result["vol_regime_compressed"] = (vix < vix_pctile_low).astype(float)
        result["vol_regime_exploding"] = (vix > vix_pctile_high).astype(float)

        # Mean reversion signal: distance from long-term mean
        vix_lt_mean = vix.rolling(252, min_periods=63).mean()
        vix_lt_std = vix.rolling(252, min_periods=63).std()
        result["vol_mean_reversion_signal"] = (
            (vix - vix_lt_mean) / (vix_lt_std + eps)
        ).clip(-4, 4)

        return result
