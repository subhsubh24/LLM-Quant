"""
Factor momentum and cross-sectional signals provider.

WHY FACTOR MOMENTUM MATTERS:

1. FACTOR TIMING:
   - Value, momentum, quality factors go through regimes
   - Factor momentum (recent winner factors continue winning) works
   - Arnott et al. (2019): "Factor momentum is pervasive"
   - Factor crowding precedes factor crashes

2. CROSS-SECTIONAL MOMENTUM:
   - Sector momentum: winning sectors continue winning (Moskowitz & Grinblatt 1999)
   - Reversal at 1-week: short-term reversal is profitable
   - 12-1 month momentum: the classic Jegadeesh & Titman factor
   - We proxy this from sector ETFs (free via yfinance)

3. DISPERSION SIGNALS:
   - Cross-sectional return dispersion = stock-picking opportunity
   - High dispersion = alpha opportunity for active managers
   - Low dispersion = index-hugging, macro-driven markets
   - Dispersion falling = correlation rising = systemic risk

4. FACTOR VALUATIONS:
   - When growth outperforms value by too much: mean reversion
   - Small-cap vs large-cap spread signals risk appetite
   - Proxy from style ETFs: IWF/IWD (growth/value), IWM/SPY (small/large)

IMPLEMENTATION:
   Uses sector ETFs from yfinance (free) to compute factor proxies.
   Falls back to synthetic signals when internet is unavailable.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# Style/factor ETFs
_FACTOR_TICKERS = {
    "IWF": "growth",       # Russell 1000 Growth
    "IWD": "value",        # Russell 1000 Value
    "IWM": "small_cap",    # Russell 2000 (small cap)
    "SPY": "large_cap",    # S&P 500 (large cap)
    "MTUM": "momentum",    # MSCI USA Momentum Factor
    "QUAL": "quality",     # MSCI USA Quality Factor
    "USMV": "low_vol",     # MSCI USA Min Volatility
}

# Sector ETFs for dispersion
_SECTOR_TICKERS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]


class FactorMomentumProvider(AlternativeDataProvider):
    """
    Factor momentum and cross-sectional signals.

    Computes:
    - Factor momentum (which factors are winning)
    - Growth vs value spread
    - Small vs large spread
    - Cross-sector return dispersion
    - Sector momentum breadth
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "factor_momentum"

    def get_feature_names(self) -> List[str]:
        return [
            # Factor spreads
            "factor_growth_value_21d",     # Growth minus value return (21d)
            "factor_growth_value_63d",     # Growth minus value return (63d)
            "factor_small_large_21d",      # Small cap minus large cap (21d)
            "factor_small_large_63d",      # Small cap minus large cap (63d)
            # Factor momentum
            "factor_momentum_ret_21d",     # Momentum factor ETF return
            "factor_quality_ret_21d",      # Quality factor ETF return
            "factor_low_vol_ret_21d",      # Low vol factor ETF return
            # Factor momentum composite
            "factor_winner_spread",        # Best factor - worst factor (21d)
            "factor_momentum_persistence", # Autocorrelation of factor winner
            # Cross-sectional dispersion
            "factor_sector_dispersion",    # Cross-sector return std (21d)
            "factor_sector_disp_chg",      # Change in dispersion (tightening/widening)
            "factor_sector_disp_zscore",   # Dispersion z-score
            # Sector momentum breadth
            "factor_sector_breadth",       # Fraction of sectors with positive 21d momentum
            "factor_sector_breadth_chg",   # Change in breadth
            # Risk parity signal
            "factor_risk_parity_signal",   # Low-vol outperformance = risk-off
            # Mean reversion signals
            "factor_gv_mean_reversion",    # Growth-value spread z-score (mean reversion)
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch factor ETF data and compute signals."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - factor momentum unavailable")
            return pd.DataFrame()

        extended_start = start_date - timedelta(days=365)
        all_tickers = list(_FACTOR_TICKERS.keys()) + _SECTOR_TICKERS

        try:
            data = yf.download(
                all_tickers,
                start=str(extended_start),
                end=str(end_date + timedelta(days=1)),
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"Failed to download factor data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        # Extract close prices
        if len(all_tickers) == 1:
            prices = data[["Close"]].copy()
            prices.columns = all_tickers
        else:
            try:
                prices = data["Close"].copy()
            except KeyError:
                return pd.DataFrame()

        prices.index = self._make_tz_naive(pd.to_datetime(prices.index))
        prices = prices.apply(pd.to_numeric, errors='coerce')
        prices = prices.ffill()

        result = pd.DataFrame(index=prices.index)

        # === FACTOR SPREADS ===
        self._compute_factor_spreads(prices, result)

        # === FACTOR MOMENTUM ===
        self._compute_factor_momentum(prices, result)

        # === CROSS-SECTIONAL DISPERSION ===
        self._compute_dispersion(prices, result)

        # === SECTOR BREADTH ===
        self._compute_sector_breadth(prices, result)

        # Filter to date range
        result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        result = result.ffill().fillna(0.0)

        logger.info(f"Factor momentum: {len(result.columns)} features")
        return result

    def _compute_factor_spreads(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Compute growth-value, small-large factor spreads."""
        # Growth vs Value
        if "IWF" in prices.columns and "IWD" in prices.columns:
            gv_21 = (
                np.log(prices["IWF"] / prices["IWF"].shift(21))
                - np.log(prices["IWD"] / prices["IWD"].shift(21))
            ).clip(-1, 1)
            gv_63 = (
                np.log(prices["IWF"] / prices["IWF"].shift(63))
                - np.log(prices["IWD"] / prices["IWD"].shift(63))
            ).clip(-1, 1)
            result["factor_growth_value_21d"] = gv_21
            result["factor_growth_value_63d"] = gv_63

            # Mean reversion signal: extreme growth-value spread tends to revert
            gv_mean = gv_63.rolling(252, min_periods=63).mean()
            gv_std = gv_63.rolling(252, min_periods=63).std()
            result["factor_gv_mean_reversion"] = (
                (gv_63 - gv_mean) / (gv_std + 1e-8)
            ).clip(-4, 4)

        # Small vs Large
        if "IWM" in prices.columns and "SPY" in prices.columns:
            sl_21 = (
                np.log(prices["IWM"] / prices["IWM"].shift(21))
                - np.log(prices["SPY"] / prices["SPY"].shift(21))
            ).clip(-1, 1)
            sl_63 = (
                np.log(prices["IWM"] / prices["IWM"].shift(63))
                - np.log(prices["SPY"] / prices["SPY"].shift(63))
            ).clip(-1, 1)
            result["factor_small_large_21d"] = sl_21
            result["factor_small_large_63d"] = sl_63

    def _compute_factor_momentum(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Compute factor momentum signals."""
        factor_rets = {}

        for ticker, name in _FACTOR_TICKERS.items():
            if ticker in prices.columns:
                ret_21d = np.log(prices[ticker] / prices[ticker].shift(21)).clip(-1, 1)
                factor_rets[name] = ret_21d

                if name in ("momentum", "quality", "low_vol"):
                    result[f"factor_{name}_ret_21d"] = ret_21d

        if len(factor_rets) >= 3:
            factor_df = pd.DataFrame(factor_rets)

            # Winner-loser spread: best factor minus worst factor
            result["factor_winner_spread"] = (
                factor_df.max(axis=1) - factor_df.min(axis=1)
            )

            # Factor momentum persistence: which factor won last month?
            # Encode winner as numeric (idxmax returns strings, can't roll over strings)
            factor_names = list(factor_df.columns)
            name_to_int = {n: i for i, n in enumerate(factor_names)}
            winner = factor_df.dropna(how='all').idxmax(axis=1)
            winner_numeric = winner.map(name_to_int).reindex(factor_df.index)
            # Persistence = fraction of last 21 days where the same factor won
            persistence = winner_numeric.rolling(21, min_periods=10).apply(
                lambda x: (x == x.iloc[-1]).mean() if len(x) > 0 else 0.5,
                raw=False,
            )
            result["factor_momentum_persistence"] = persistence

        # Risk parity signal: low-vol outperforming = risk-off environment
        if "USMV" in prices.columns and "SPY" in prices.columns:
            result["factor_risk_parity_signal"] = (
                np.log(prices["USMV"] / prices["USMV"].shift(21))
                - np.log(prices["SPY"] / prices["SPY"].shift(21))
            ).clip(-1, 1)

    def _compute_dispersion(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Compute cross-sector return dispersion."""
        sector_rets = {}
        for ticker in _SECTOR_TICKERS:
            if ticker in prices.columns:
                sector_rets[ticker] = np.log(
                    prices[ticker] / prices[ticker].shift(1)
                )

        if len(sector_rets) >= 5:
            ret_df = pd.DataFrame(sector_rets)

            # Cross-sectional dispersion: rolling std of sector returns
            dispersion = ret_df.std(axis=1).rolling(21, min_periods=10).mean()
            result["factor_sector_dispersion"] = dispersion

            # Change in dispersion
            result["factor_sector_disp_chg"] = dispersion.diff(21)

            # Z-score of dispersion
            disp_mean = dispersion.rolling(252, min_periods=63).mean()
            disp_std = dispersion.rolling(252, min_periods=63).std()
            result["factor_sector_disp_zscore"] = (
                (dispersion - disp_mean) / (disp_std + 1e-8)
            ).clip(-4, 4)

    def _compute_sector_breadth(
        self, prices: pd.DataFrame, result: pd.DataFrame
    ) -> None:
        """Compute sector momentum breadth."""
        sector_mom = {}
        for ticker in _SECTOR_TICKERS:
            if ticker in prices.columns:
                sector_mom[ticker] = np.log(
                    prices[ticker] / prices[ticker].shift(21)
                )

        if len(sector_mom) >= 5:
            mom_df = pd.DataFrame(sector_mom)

            # Fraction of sectors with positive 21d momentum (NaN-aware denominator)
            breadth = (mom_df > 0).sum(axis=1) / mom_df.notna().sum(axis=1).clip(lower=1)
            result["factor_sector_breadth"] = breadth

            # Breadth change
            result["factor_sector_breadth_chg"] = breadth.diff(5)
