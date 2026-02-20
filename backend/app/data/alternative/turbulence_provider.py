"""
Market Turbulence Index provider.

WHY TURBULENCE MATTERS:

1. MAHALANOBIS DISTANCE (Kritzman & Li, 2010):
   - Measures how "unusual" today's multi-asset returns are relative to history
   - Accounts for correlations between assets (not just individual moves)
   - A 2% equity drop ALONE is not unusual. A 2% equity drop + 1% bond drop
     + 3% gold drop simultaneously IS unusual — that's a turbulence spike
   - Turbulence > 2 sigma predicts next-month drawdowns with 70% accuracy

2. ABSORPTION RATIO (Kritzman et al., 2011):
   - Already implemented in correlation_regime_provider
   - Turbulence is complementary: absorption = systemic risk LEVEL,
     turbulence = systemic risk REALIZATION

3. REGIME DETECTION:
   - Low turbulence (< 1 sigma): Normal market, trend-following works
   - Medium turbulence (1-2 sigma): Transition, reduce position size
   - High turbulence (> 2 sigma): Crisis, risk-off or mean-reversion

4. MEAN REVERSION OF TURBULENCE:
   - Turbulence is strongly mean-reverting (AR(1) coefficient ~0.85)
   - After extreme turbulence, markets tend to calm → recovery trade
   - But turbulence can cluster (GARCH-like behavior)

IMPLEMENTATION:
   Uses yfinance for multi-asset returns (SPY, TLT, GLD, UUP, HYG, EEM).
   Computes rolling covariance matrix and Mahalanobis distance daily.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# Asset classes for turbulence computation
_TURB_TICKERS = ["SPY", "TLT", "GLD", "UUP", "HYG", "EEM", "USO", "VNQ"]


class TurbulenceProvider(AlternativeDataProvider):
    """
    Market turbulence index based on Mahalanobis distance.

    Measures how statistically unusual today's multi-asset returns are
    relative to the recent historical distribution. Accounts for both
    individual asset moves AND their correlations.

    Features:
    - Raw turbulence index (Mahalanobis distance)
    - Turbulence z-score (how unusual is current turbulence)
    - Turbulence regime (low/medium/high/crisis)
    - Turbulence momentum (is turbulence rising or falling)
    - Turbulence mean-reversion signal
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "turbulence"

    def get_feature_names(self) -> List[str]:
        return [
            # Core turbulence measures
            "turb_index",                # Raw Mahalanobis distance
            "turb_index_log",            # Log turbulence (reduces skew)
            "turb_zscore",               # Z-score of turbulence
            "turb_percentile",           # Percentile rank (63d)
            # Dynamics
            "turb_momentum_5d",          # 5-day change in turbulence
            "turb_momentum_21d",         # 21-day change in turbulence
            "turb_ewma_ratio",           # Fast EWMA / slow EWMA (trend)
            # Regime indicators
            "turb_regime_calm",          # Turbulence < 25th percentile
            "turb_regime_elevated",      # Turbulence > 75th percentile
            "turb_regime_crisis",        # Turbulence > 95th percentile
            # Mean-reversion signal
            "turb_mean_reversion",       # High turb → expect decline (contrarian)
            # Conditional measures
            "turb_equity_contribution",  # How much SPY drives turbulence
            "turb_credit_contribution",  # How much HYG drives turbulence
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch multi-asset data and compute turbulence index."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - turbulence unavailable")
            return pd.DataFrame()

        # Need extended history for covariance estimation
        extended_start = start_date - timedelta(days=400)

        try:
            data = yf.download(
                _TURB_TICKERS,
                start=str(extended_start),
                end=str(end_date + timedelta(days=1)),
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"Failed to download turbulence data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        try:
            prices = data["Close"].copy()
        except KeyError:
            return pd.DataFrame()

        prices.index = self._make_tz_naive(pd.to_datetime(prices.index))
        prices = prices.ffill()

        # Need at least SPY + 2 other assets
        available = [t for t in _TURB_TICKERS if t in prices.columns]
        if len(available) < 3 or "SPY" not in available:
            logger.warning(f"Only {len(available)} assets for turbulence (need 3+)")
            return pd.DataFrame()

        # Compute daily log returns
        returns = np.log(prices[available] / prices[available].shift(1))
        returns = returns.dropna()

        result = pd.DataFrame(index=prices.index)

        # === COMPUTE ROLLING TURBULENCE INDEX ===
        turb_values = self._compute_turbulence(returns, window=252)
        result["turb_index"] = turb_values

        # Log turbulence (reduces right skew, more normally distributed)
        result["turb_index_log"] = np.log1p(turb_values)

        # Z-score of turbulence
        turb_mean = turb_values.rolling(252, min_periods=63).mean()
        turb_std = turb_values.rolling(252, min_periods=63).std()
        result["turb_zscore"] = (
            (turb_values - turb_mean) / (turb_std + 1e-8)
        ).clip(-4, 4)

        # Percentile rank
        result["turb_percentile"] = turb_values.rolling(
            63, min_periods=21
        ).apply(
            lambda x: (x.iloc[-1] >= x).sum() / len(x) if len(x) > 0 else np.nan,
            raw=False,
        )

        # === DYNAMICS ===
        turb_smooth = turb_values.rolling(5, min_periods=3).mean()
        result["turb_momentum_5d"] = turb_smooth.diff(5)
        result["turb_momentum_21d"] = turb_smooth.diff(21)

        # EWMA ratio: fast/slow (> 1 means turbulence rising)
        ewma_fast = turb_values.ewm(span=5, min_periods=3).mean()
        ewma_slow = turb_values.ewm(span=21, min_periods=10).mean()
        result["turb_ewma_ratio"] = (
            (ewma_fast / (ewma_slow + 1e-8)) - 1
        ).clip(-2, 2)

        # === REGIME INDICATORS ===
        pctile = result["turb_percentile"]
        result["turb_regime_calm"] = (pctile < 0.25).astype(float)
        result["turb_regime_elevated"] = (pctile > 0.75).astype(float)
        result["turb_regime_crisis"] = (pctile > 0.95).astype(float)

        # === MEAN-REVERSION SIGNAL ===
        # When turbulence is extremely high, expect it to decline
        # When turbulence is extremely low, expect it to rise
        result["turb_mean_reversion"] = -result["turb_zscore"].clip(-3, 3) / 3

        # === CONDITIONAL CONTRIBUTIONS ===
        # Decompose: which asset class is driving turbulence?
        self._compute_contributions(returns, result, available)

        # Filter to requested range
        result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        result = result.ffill().fillna(0.0)

        logger.info(f"Turbulence: {len(result.columns)} features")
        return result

    def _compute_turbulence(
        self,
        returns: pd.DataFrame,
        window: int = 252,
    ) -> pd.Series:
        """
        Compute rolling Mahalanobis distance (turbulence index).

        For each day t:
        1. Estimate covariance matrix from [t-window, t-1]
        2. Compute Mahalanobis distance of today's returns from the mean
        3. Turbulence = sqrt(Mahalanobis distance)

        Higher = more unusual market behavior.
        """
        n_assets = returns.shape[1]
        min_periods = max(n_assets * 3, 63)  # Need enough data for stable covariance
        turb = pd.Series(np.nan, index=returns.index)

        for i in range(min_periods, len(returns)):
            start_idx = max(0, i - window)
            hist = returns.iloc[start_idx:i]  # Exclude today (no look-ahead)
            today = returns.iloc[i].values

            if len(hist) < min_periods:
                continue

            mu = hist.mean().values
            try:
                cov = hist.cov().values

                # Regularize covariance matrix for numerical stability
                cov += np.eye(n_assets) * 1e-6

                cov_inv = np.linalg.inv(cov)
                diff = today - mu
                mahal = diff @ cov_inv @ diff

                # Turbulence = sqrt of Mahalanobis distance, normalized by n_assets
                turb.iloc[i] = np.sqrt(max(mahal, 0)) / np.sqrt(n_assets)

            except np.linalg.LinAlgError:
                continue

        return turb

    def _compute_contributions(
        self,
        returns: pd.DataFrame,
        result: pd.DataFrame,
        available: List[str],
    ) -> None:
        """
        Compute asset-class contribution to turbulence.

        Uses marginal contribution: how much does each asset's
        squared deviation contribute to the total Mahalanobis distance?
        Approximated by the squared z-score of each asset's return.
        """
        window = 63

        if "SPY" in available:
            spy_ret = returns["SPY"]
            spy_mean = spy_ret.rolling(window, min_periods=21).mean()
            spy_std = spy_ret.rolling(window, min_periods=21).std()
            spy_z = ((spy_ret - spy_mean) / (spy_std + 1e-8)) ** 2
            # Normalize: what fraction of total squared deviation is from SPY?
            total_z2 = pd.DataFrame()
            for t in available:
                r = returns[t]
                m = r.rolling(window, min_periods=21).mean()
                s = r.rolling(window, min_periods=21).std()
                total_z2[t] = ((r - m) / (s + 1e-8)) ** 2
            total = total_z2.sum(axis=1) + 1e-8
            result["turb_equity_contribution"] = (spy_z / total).reindex(result.index)

        if "HYG" in available:
            hyg_ret = returns["HYG"]
            hyg_mean = hyg_ret.rolling(window, min_periods=21).mean()
            hyg_std = hyg_ret.rolling(window, min_periods=21).std()
            hyg_z = ((hyg_ret - hyg_mean) / (hyg_std + 1e-8)) ** 2
            total_z2 = pd.DataFrame()
            for t in available:
                r = returns[t]
                m = r.rolling(window, min_periods=21).mean()
                s = r.rolling(window, min_periods=21).std()
                total_z2[t] = ((r - m) / (s + 1e-8)) ** 2
            total = total_z2.sum(axis=1) + 1e-8
            result["turb_credit_contribution"] = (hyg_z / total).reindex(result.index)
