"""
Intermarket correlation regime provider.

WHY CORRELATION REGIMES MATTER:

1. STOCK-BOND CORRELATION REGIME:
   - Normal: Negative correlation (bonds hedge equities)
   - Crisis: Positive correlation (everything sells off = liquidity crisis)
   - Goldilocks: Zero correlation (each driven by own fundamentals)
   - REGIME CHANGES predict 80% of the worst equity drawdowns
   - Pollet & Wilson (2010): "Average correlation predicts market returns"

2. CROSS-ASSET CORRELATION CLUSTERING:
   - When all assets correlate → systemic risk rising
   - When assets decorrelate → idiosyncratic opportunities
   - "Correlations go to 1 in a crisis" (but the SPEED matters)
   - Kritzman et al. (2011): Absorption ratio predicts crises

3. DISPERSION-CORRELATION TRADEOFF:
   - High cross-sector correlation + low dispersion = macro-driven
   - Low correlation + high dispersion = stock-picking environment
   - The TRANSITION between these regimes is tradeable

4. REALIZED CORRELATION DYNAMICS:
   - Rolling correlations are mean-reverting
   - Extreme correlation readings predict reversals
   - Rate of change in correlation > absolute level for timing

IMPLEMENTATION:
   Uses yfinance for major ETF classes (equity, bond, commodity, currency).
   Computes pairwise rolling correlations and regime indicators.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# Core asset class representatives
_ASSET_TICKERS = {
    "SPY": "equity",
    "TLT": "bond_long",
    "SHY": "bond_short",
    "GLD": "gold",
    "UUP": "dollar",
    "HYG": "credit",
    "EEM": "em_equity",
    "VNQ": "real_estate",
}


class CorrelationRegimeProvider(AlternativeDataProvider):
    """
    Intermarket correlation regime detection.

    Computes:
    - Pairwise rolling correlations between major asset classes
    - Absorption ratio (systemic risk measure)
    - Correlation regime indicators (crisis/normal/goldilocks)
    - Rate of change in correlation structure
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "correlation_regime"

    def get_feature_names(self) -> List[str]:
        return [
            # Key pairwise correlations
            "corr_equity_bond",          # SPY-TLT correlation (THE key relationship)
            "corr_equity_gold",          # SPY-GLD (risk-off hedge effectiveness)
            "corr_equity_credit",        # SPY-HYG (credit-equity linkage)
            "corr_equity_dollar",        # SPY-UUP (dollar impact on equities)
            "corr_equity_em",            # SPY-EEM (global risk appetite)
            "corr_bond_gold",            # TLT-GLD (real rate proxy)
            # Correlation dynamics
            "corr_equity_bond_chg_21d",  # How fast stock-bond corr is changing
            "corr_equity_bond_zscore",   # Is stock-bond corr abnormal?
            # Systemic risk measures
            "corr_absorption_ratio",     # Kritzman absorption ratio
            "corr_avg_pairwise",         # Average pairwise correlation
            "corr_avg_pairwise_chg",     # Change in avg correlation
            "corr_avg_pairwise_zscore",  # Z-score of avg correlation
            # Regime indicators
            "corr_crisis_regime",        # Stock-bond corr > 0.3 (liquidity crisis)
            "corr_hedging_regime",       # Stock-bond corr < -0.3 (normal hedging)
            "corr_regime_transition",    # Rate of regime change
            # Diversification effectiveness
            "corr_diversification_ratio", # How much diversification benefit exists
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch asset prices and compute correlation regime features."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - correlation regime unavailable")
            return pd.DataFrame()

        extended_start = start_date - timedelta(days=400)
        tickers = list(_ASSET_TICKERS.keys())

        try:
            data = yf.download(
                tickers,
                start=str(extended_start),
                end=str(end_date + timedelta(days=1)),
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"Failed to download correlation data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        try:
            prices = data["Close"].copy()
        except KeyError:
            return pd.DataFrame()

        prices.index = self._make_tz_naive(pd.to_datetime(prices.index))
        prices = prices.ffill()

        # Need at least SPY and TLT
        if "SPY" not in prices.columns or "TLT" not in prices.columns:
            logger.warning("SPY or TLT not available for correlation regime")
            return pd.DataFrame()

        # Compute daily log returns
        returns = {}
        for ticker in tickers:
            if ticker in prices.columns:
                returns[ticker] = np.log(prices[ticker] / prices[ticker].shift(1))
        ret_df = pd.DataFrame(returns)

        result = pd.DataFrame(index=prices.index)

        # === KEY PAIRWISE CORRELATIONS ===
        self._compute_pairwise_correlations(ret_df, result)

        # === CORRELATION DYNAMICS ===
        self._compute_correlation_dynamics(ret_df, result)

        # === SYSTEMIC RISK MEASURES ===
        self._compute_systemic_risk(ret_df, result)

        # === REGIME INDICATORS ===
        self._compute_regime_indicators(result)

        # Filter to date range
        result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        result = result.ffill().fillna(0.0)

        logger.info(f"Correlation regime: {len(result.columns)} features")
        return result

    def _compute_pairwise_correlations(
        self, ret_df: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Compute rolling pairwise correlations between asset classes."""
        pairs = [
            ("SPY", "TLT", "corr_equity_bond"),
            ("SPY", "GLD", "corr_equity_gold"),
            ("SPY", "HYG", "corr_equity_credit"),
            ("SPY", "UUP", "corr_equity_dollar"),
            ("SPY", "EEM", "corr_equity_em"),
            ("TLT", "GLD", "corr_bond_gold"),
        ]

        for t1, t2, col_name in pairs:
            if t1 in ret_df.columns and t2 in ret_df.columns:
                corr = ret_df[t1].rolling(63, min_periods=21).corr(ret_df[t2])
                result[col_name] = corr.clip(-1, 1)

    def _compute_correlation_dynamics(
        self, ret_df: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Track how correlations are changing over time."""
        if "SPY" not in ret_df.columns or "TLT" not in ret_df.columns:
            return

        # Short-term vs long-term stock-bond correlation
        corr_short = ret_df["SPY"].rolling(21, min_periods=10).corr(ret_df["TLT"])
        corr_long = ret_df["SPY"].rolling(126, min_periods=42).corr(ret_df["TLT"])

        # Rate of change: how fast is correlation shifting?
        result["corr_equity_bond_chg_21d"] = corr_short.diff(21)

        # Z-score: is current correlation abnormal?
        corr_mean = corr_long.rolling(252, min_periods=63).mean()
        corr_std = corr_long.rolling(252, min_periods=63).std()
        result["corr_equity_bond_zscore"] = (
            (corr_short - corr_mean) / (corr_std + 1e-8)
        ).clip(-4, 4)

    def _compute_systemic_risk(
        self, ret_df: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """
        Compute systemic risk measures from correlation structure.

        Absorption ratio (Kritzman et al., 2011):
        Fraction of total variance explained by top N principal components.
        Higher = more systemic risk (assets moving together).
        """
        available = [t for t in _ASSET_TICKERS if t in ret_df.columns]
        if len(available) < 4:
            return

        subset = ret_df[available].dropna()

        # Rolling absorption ratio (63-day window)
        window = 63
        min_periods = 30
        absorption = []
        avg_corr = []
        indices = []

        for i in range(min_periods, len(subset)):
            start_idx = max(0, i - window)
            window_data = subset.iloc[start_idx:i]

            if len(window_data) < min_periods:
                continue

            # Correlation matrix
            corr_matrix = window_data.corr()

            # Average pairwise correlation (exclude diagonal)
            n = len(corr_matrix)
            mask = ~np.eye(n, dtype=bool)
            avg_c = corr_matrix.values[mask].mean()
            avg_corr.append(avg_c)

            # Absorption ratio: variance explained by top 1 eigenvalue
            try:
                eigenvalues = np.linalg.eigvalsh(corr_matrix.values)
                eigenvalues = np.sort(eigenvalues)[::-1]
                total_var = eigenvalues.sum()
                if total_var > 0:
                    # Top 1 component's share of total variance
                    absorption.append(eigenvalues[0] / total_var)
                else:
                    absorption.append(np.nan)
            except np.linalg.LinAlgError:
                absorption.append(np.nan)

            indices.append(subset.index[i - 1])

        if indices:
            abs_series = pd.Series(absorption, index=indices)
            corr_series = pd.Series(avg_corr, index=indices)

            result["corr_absorption_ratio"] = abs_series.reindex(result.index)
            result["corr_avg_pairwise"] = corr_series.reindex(result.index)

            # Change in average pairwise correlation
            avg_corr_filled = result["corr_avg_pairwise"].ffill()
            result["corr_avg_pairwise_chg"] = avg_corr_filled.diff(21)

            # Z-score of average correlation
            mean_corr = avg_corr_filled.rolling(252, min_periods=63).mean()
            std_corr = avg_corr_filled.rolling(252, min_periods=63).std()
            result["corr_avg_pairwise_zscore"] = (
                (avg_corr_filled - mean_corr) / (std_corr + 1e-8)
            ).clip(-4, 4)

    def _compute_regime_indicators(self, result: pd.DataFrame) -> None:
        """Compute correlation regime indicators."""
        if "corr_equity_bond" not in result.columns:
            return

        corr_eb = result["corr_equity_bond"]

        # Crisis regime: stock-bond correlation positive (both selling off)
        result["corr_crisis_regime"] = (corr_eb > 0.3).astype(float)

        # Normal hedging regime: stock-bond correlation negative
        result["corr_hedging_regime"] = (corr_eb < -0.3).astype(float)

        # Regime transition speed: abs rate of change
        result["corr_regime_transition"] = corr_eb.diff(10).abs()

        # Diversification ratio: 1 - avg_pairwise_corr (higher = more diversified)
        if "corr_avg_pairwise" in result.columns:
            result["corr_diversification_ratio"] = (
                1 - result["corr_avg_pairwise"].clip(0, 1)
            )
        else:
            result["corr_diversification_ratio"] = 0.5
