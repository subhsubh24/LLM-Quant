"""
Bond market stress and credit risk signals.

WHY THIS MATTERS:

1. BONDS LEAD EQUITIES:
   - Credit markets are smarter than equity markets
   - Bond traders are institutional (banks, pensions, insurance)
   - When credit stress rises, equities follow 2-6 weeks later
   - The 2008, 2020, and 2022 selloffs all showed credit leading

2. YIELD CURVE:
   - Inverted yield curve → recession (12-18 month lead)
   - Steepening from inversion → recovery beginning
   - 2s10s spread is the gold standard, but also use 3m10y

3. CREDIT SPREADS:
   - Investment grade spreads (LQD vs Treasury) = corporate health
   - High yield spreads (HYG vs LQD) = distress signal
   - When HY spreads blow out, equities crash follows

4. TREASURY VOLATILITY:
   - MOVE index equivalent (bond vol)
   - High bond vol = uncertainty = equity selloff risk
   - Bond-equity correlation changes signal regime shifts

IMPLEMENTATION:
   Uses bond ETFs via yfinance (free):
   TLT (20yr), IEF (7-10yr), SHY (1-3yr), HYG (High Yield),
   LQD (Investment Grade), TIP (TIPS), AGG (Aggregate Bond)
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class BondStressProvider(AlternativeDataProvider):
    """
    Bond market stress and credit risk indicators.

    Monitors:
    - Yield curve shape and dynamics
    - Credit spreads (HY vs IG vs Treasury)
    - Bond-equity correlation regime
    - Treasury volatility as uncertainty proxy
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "bond_stress"

    def get_feature_names(self) -> List[str]:
        return [
            # Yield curve signals
            "bond_curve_slope",           # TLT vs SHY (long vs short duration)
            "bond_curve_slope_chg_5d",    # 5-day change in slope
            "bond_curve_slope_chg_21d",   # 21-day change in slope
            "bond_curve_curvature",       # IEF relative to TLT+SHY average (belly)
            # Credit spread signals
            "bond_hy_spread",             # HYG vs LQD return difference
            "bond_hy_spread_zscore",      # Z-score of HY spread (21d)
            "bond_hy_momentum",           # HYG 21-day momentum
            "bond_ig_momentum",           # LQD 21-day momentum
            "bond_credit_stress",         # Composite credit stress score
            # Duration/rate risk
            "bond_duration_momentum",     # TLT momentum (rate expectations)
            "bond_tips_breakeven_chg",    # TIP vs IEF (inflation expectation proxy)
            "bond_vol_21d",               # Bond market volatility (TLT realized vol)
            "bond_vol_zscore",            # Bond vol z-score
            # Bond-equity relationship
            "bond_equity_corr_21d",       # Bond-SPY correlation (regime indicator)
            "bond_equity_corr_63d",       # Longer-term correlation
            "bond_equity_decorrelation",  # Deviation from normal correlation
            # Composite
            "bond_stress_score",          # Overall bond market stress composite
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch bond ETF data and compute stress signals."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - bond stress unavailable")
            return pd.DataFrame()

        tickers = ["TLT", "IEF", "SHY", "HYG", "LQD", "TIP", "SPY"]
        fetch_start = start_date - timedelta(days=120)

        try:
            data = yf.download(
                tickers, start=str(fetch_start), end=str(end_date),
                progress=False, auto_adjust=True
            )
        except Exception as e:
            logger.warning(f"Failed to download bond data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        # Extract close prices
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"]
        else:
            closes = data

        result = pd.DataFrame(index=closes.index)

        tlt = closes.get("TLT")
        ief = closes.get("IEF")
        shy = closes.get("SHY")
        hyg = closes.get("HYG")
        lqd = closes.get("LQD")
        tip = closes.get("TIP")
        spy = closes.get("SPY")

        # --- Yield Curve Signals ---
        if tlt is not None and shy is not None:
            # Slope: normalized price ratio (TLT/SHY - 1)
            # When TLT outperforms SHY → rates falling → slope steepening
            tlt_ret = tlt.pct_change(21)
            shy_ret = shy.pct_change(21)
            curve_slope = tlt_ret - shy_ret
            result["bond_curve_slope"] = curve_slope.clip(-0.1, 0.1)
            result["bond_curve_slope_chg_5d"] = curve_slope.diff(5).clip(-0.05, 0.05)
            result["bond_curve_slope_chg_21d"] = curve_slope.diff(21).clip(-0.1, 0.1)

        # Curvature: IEF relative to average of TLT and SHY
        if ief is not None and tlt is not None and shy is not None:
            ief_ret = ief.pct_change(21)
            avg_ends = (tlt.pct_change(21) + shy.pct_change(21)) / 2
            result["bond_curve_curvature"] = (ief_ret - avg_ends).clip(-0.05, 0.05)

        # --- Credit Spread Signals ---
        if hyg is not None and lqd is not None:
            hyg_ret = hyg.pct_change(1)
            lqd_ret = lqd.pct_change(1)
            # HY spread: when HYG underperforms LQD → credit stress rising
            spread = (hyg_ret - lqd_ret).rolling(5).mean()
            result["bond_hy_spread"] = spread.clip(-0.02, 0.02)

            # Z-score of spread
            spread_mean = spread.rolling(63, min_periods=21).mean()
            spread_std = spread.rolling(63, min_periods=21).std()
            result["bond_hy_spread_zscore"] = ((spread - spread_mean) / (spread_std + 1e-8)).clip(-3, 3)

        if hyg is not None:
            result["bond_hy_momentum"] = hyg.pct_change(21).clip(-0.1, 0.1)

        if lqd is not None:
            result["bond_ig_momentum"] = lqd.pct_change(21).clip(-0.1, 0.1)

        # Credit stress composite
        stress_signals = []
        if "bond_hy_spread_zscore" in result.columns:
            stress_signals.append(-result["bond_hy_spread_zscore"])  # Negative = stress
        if "bond_hy_momentum" in result.columns:
            stress_signals.append(-result["bond_hy_momentum"] * 10)  # Scale up
        if stress_signals:
            result["bond_credit_stress"] = pd.concat(stress_signals, axis=1).mean(axis=1).clip(-1, 1)
        else:
            result["bond_credit_stress"] = 0.0

        # --- Duration/Rate Risk ---
        if tlt is not None:
            result["bond_duration_momentum"] = tlt.pct_change(21).clip(-0.15, 0.15)

            # Bond volatility
            tlt_ret_daily = tlt.pct_change(1)
            result["bond_vol_21d"] = tlt_ret_daily.rolling(21).std() * np.sqrt(252)
            vol_mean = result["bond_vol_21d"].rolling(63, min_periods=21).mean()
            vol_std = result["bond_vol_21d"].rolling(63, min_periods=21).std()
            result["bond_vol_zscore"] = ((result["bond_vol_21d"] - vol_mean) / (vol_std + 1e-8)).clip(-3, 3)

        # TIPS breakeven proxy
        if tip is not None and ief is not None:
            tip_ret = tip.pct_change(21)
            ief_ret = ief.pct_change(21)
            # TIP outperforming IEF → inflation expectations rising
            result["bond_tips_breakeven_chg"] = (tip_ret - ief_ret).clip(-0.05, 0.05)

        # --- Bond-Equity Relationship ---
        if tlt is not None and spy is not None:
            tlt_ret_daily = tlt.pct_change(1)
            spy_ret_daily = spy.pct_change(1)

            # Rolling correlation
            corr_21 = tlt_ret_daily.rolling(21, min_periods=10).corr(spy_ret_daily)
            corr_63 = tlt_ret_daily.rolling(63, min_periods=21).corr(spy_ret_daily)
            result["bond_equity_corr_21d"] = corr_21.clip(-1, 1)
            result["bond_equity_corr_63d"] = corr_63.clip(-1, 1)

            # Normal correlation is negative (bonds hedge equities)
            # When it goes positive → regime shift (both selling off = liquidity crisis)
            normal_corr = -0.3  # Historical average
            result["bond_equity_decorrelation"] = (corr_21 - normal_corr).clip(-1, 1)

        # --- Composite Stress Score ---
        stress_components = []
        if "bond_credit_stress" in result.columns:
            stress_components.append(result["bond_credit_stress"])
        if "bond_vol_zscore" in result.columns:
            stress_components.append(result["bond_vol_zscore"] / 3)  # Normalize
        if "bond_equity_decorrelation" in result.columns:
            stress_components.append(result["bond_equity_decorrelation"])
        if stress_components:
            result["bond_stress_score"] = pd.concat(stress_components, axis=1).mean(axis=1).clip(-1, 1)
        else:
            result["bond_stress_score"] = 0.0

        # Filter to requested date range
        result = result.loc[str(start_date):str(end_date)]
        result = result.fillna(method='ffill').fillna(0.0)

        logger.info(f"Bond stress: {len(result.columns)} features")
        return result
