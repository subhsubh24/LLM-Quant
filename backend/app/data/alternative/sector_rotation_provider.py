"""
Sector rotation momentum signals.

WHY THIS MATTERS:

1. SECTOR ROTATION:
   - Money flows between sectors in predictable patterns
   - Early cycle: Consumer Discretionary, Financials lead
   - Mid cycle: Technology, Industrials lead
   - Late cycle: Energy, Materials lead
   - Recession: Utilities, Healthcare, Consumer Staples lead
   - Tracking which sectors are winning/losing reveals economic regime

2. RELATIVE STRENGTH:
   - Sectors outperforming SPY = institutional conviction
   - Sector breadth (how many sectors up) = market health
   - Concentration (few sectors leading) = fragile rally

3. DEFENSIVE vs CYCLICAL ROTATION:
   - Money flowing to Utilities/Staples/Healthcare = risk-off
   - Money flowing to Tech/Discretionary/Financials = risk-on
   - The RATIO between these groups is a leading indicator

IMPLEMENTATION:
   Uses SPDR sector ETFs via yfinance (free, no API key):
   XLK (Tech), XLF (Financials), XLE (Energy), XLV (Healthcare),
   XLY (Consumer Disc), XLP (Consumer Staples), XLI (Industrials),
   XLB (Materials), XLU (Utilities), XLRE (Real Estate), XLC (Comm)
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# SPDR Sector ETFs
SECTOR_ETFS = {
    "XLK": "technology",
    "XLF": "financials",
    "XLE": "energy",
    "XLV": "healthcare",
    "XLY": "consumer_disc",
    "XLP": "consumer_staples",
    "XLI": "industrials",
    "XLB": "materials",
    "XLU": "utilities",
    "XLRE": "real_estate",
    "XLC": "communication",
}

# Classification for rotation analysis
CYCLICAL_SECTORS = ["XLK", "XLF", "XLY", "XLI", "XLB", "XLE"]
DEFENSIVE_SECTORS = ["XLV", "XLP", "XLU", "XLRE"]


class SectorRotationProvider(AlternativeDataProvider):
    """
    Sector rotation momentum and relative strength signals.

    Tracks institutional money flow between sectors to detect:
    - Economic cycle phase (early/mid/late/recession)
    - Risk-on vs risk-off rotation
    - Market breadth at the sector level
    - Leadership concentration (fragile vs broad rally)
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "sector_rotation"

    def get_feature_names(self) -> List[str]:
        return [
            # Sector relative strength (each sector vs SPY)
            "sector_tech_rs",
            "sector_fin_rs",
            "sector_energy_rs",
            "sector_health_rs",
            "sector_disc_rs",
            "sector_staples_rs",
            "sector_industrial_rs",
            "sector_materials_rs",
            "sector_utility_rs",
            # Rotation indicators
            "sector_cyclical_vs_defensive",   # Cyclical outperformance = risk-on
            "sector_breadth",                  # % of sectors outperforming SPY
            "sector_dispersion",               # Cross-sector return dispersion
            "sector_concentration",            # HHI of returns (top-heavy?)
            "sector_momentum_leader",          # Strongest sector ID (normalized)
            "sector_momentum_laggard",         # Weakest sector ID (normalized)
            # Rotation velocity
            "sector_rotation_speed",           # How fast leadership is changing
            "sector_risk_appetite",            # Composite risk-on score
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch sector ETF data and compute rotation signals."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed - sector rotation unavailable")
            return pd.DataFrame()

        # Fetch all sector ETFs + SPY benchmark
        tickers = list(SECTOR_ETFS.keys()) + ["SPY"]
        fetch_start = start_date - timedelta(days=90)  # Extra for rolling calcs

        try:
            data = yf.download(
                tickers, start=str(fetch_start), end=str(end_date),
                progress=False, auto_adjust=True
            )
        except Exception as e:
            logger.warning(f"Failed to download sector data: {e}")
            return pd.DataFrame()

        if data.empty:
            return pd.DataFrame()

        # Extract close prices
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"]
        else:
            closes = data

        # Need SPY as benchmark
        if "SPY" not in closes.columns:
            logger.warning("SPY not available for sector rotation")
            return pd.DataFrame()

        spy = closes["SPY"]
        result = pd.DataFrame(index=closes.index)

        # 1. Relative Strength: 21-day sector return minus SPY return
        spy_ret_21 = spy.pct_change(21)

        sector_rets = {}
        rs_columns = {
            "XLK": "sector_tech_rs",
            "XLF": "sector_fin_rs",
            "XLE": "sector_energy_rs",
            "XLV": "sector_health_rs",
            "XLY": "sector_disc_rs",
            "XLP": "sector_staples_rs",
            "XLI": "sector_industrial_rs",
            "XLB": "sector_materials_rs",
            "XLU": "sector_utility_rs",
        }

        for ticker, col_name in rs_columns.items():
            if ticker in closes.columns:
                sec_ret = closes[ticker].pct_change(21)
                rs = sec_ret - spy_ret_21
                result[col_name] = rs.clip(-0.2, 0.2)  # Cap at ±20%
                sector_rets[ticker] = sec_ret

        # 2. Cyclical vs Defensive
        cyclical_rets = []
        defensive_rets = []
        for ticker in CYCLICAL_SECTORS:
            if ticker in closes.columns:
                cyclical_rets.append(closes[ticker].pct_change(21))
        for ticker in DEFENSIVE_SECTORS:
            if ticker in closes.columns:
                defensive_rets.append(closes[ticker].pct_change(21))

        if cyclical_rets and defensive_rets:
            avg_cyclical = pd.concat(cyclical_rets, axis=1).mean(axis=1)
            avg_defensive = pd.concat(defensive_rets, axis=1).mean(axis=1)
            result["sector_cyclical_vs_defensive"] = (avg_cyclical - avg_defensive).clip(-0.15, 0.15)
        else:
            result["sector_cyclical_vs_defensive"] = 0.0

        # 3. Sector breadth: % of sectors outperforming SPY
        if sector_rets:
            outperformers = pd.DataFrame(sector_rets)
            breadth = outperformers.gt(spy_ret_21, axis=0).sum(axis=1) / len(sector_rets)
            result["sector_breadth"] = breadth * 2 - 1  # Scale to -1 to 1
        else:
            result["sector_breadth"] = 0.0

        # 4. Return dispersion (cross-sectional volatility)
        if sector_rets:
            ret_df = pd.DataFrame(sector_rets)
            result["sector_dispersion"] = ret_df.std(axis=1).clip(0, 0.1) / 0.1
        else:
            result["sector_dispersion"] = 0.0

        # 5. Concentration (HHI of absolute returns)
        if sector_rets:
            abs_rets = pd.DataFrame(sector_rets).abs()
            total = abs_rets.sum(axis=1) + 1e-8
            shares = abs_rets.div(total, axis=0)
            hhi = (shares ** 2).sum(axis=1)
            # Normalize: 1/N = perfect dispersion, 1 = total concentration
            n_sectors = len(sector_rets)
            result["sector_concentration"] = (hhi - 1/n_sectors) / (1 - 1/n_sectors + 1e-8)
        else:
            result["sector_concentration"] = 0.0

        # 6. Leader/Laggard (which sector is strongest/weakest)
        if sector_rets:
            ret_df = pd.DataFrame(sector_rets)
            n_sectors = len(sector_rets)
            # Vectorized: argmax/argmin across columns, normalized to [0, 1]
            valid_mask = ~ret_df.isna().all(axis=1)
            # Initialize defaults (neutral)
            result["sector_momentum_leader"] = 0.5
            result["sector_momentum_laggard"] = 0.5
            if valid_mask.any() and n_sectors > 1:
                result.loc[valid_mask, "sector_momentum_leader"] = (
                    np.nanargmax(ret_df.loc[valid_mask].values, axis=1) / (n_sectors - 1)
                )
                result.loc[valid_mask, "sector_momentum_laggard"] = (
                    np.nanargmin(ret_df.loc[valid_mask].values, axis=1) / (n_sectors - 1)
                )

        # 7. Rotation speed: how much has leadership changed in 5 days?
        if "sector_momentum_leader" in result.columns:
            result["sector_rotation_speed"] = result["sector_momentum_leader"].diff(5).abs()
        else:
            result["sector_rotation_speed"] = 0.0

        # 8. Risk appetite composite
        risk_signals = []
        if "sector_cyclical_vs_defensive" in result.columns:
            risk_signals.append(result["sector_cyclical_vs_defensive"] / 0.15)
        if "sector_breadth" in result.columns:
            risk_signals.append(result["sector_breadth"])
        if risk_signals:
            result["sector_risk_appetite"] = pd.concat(risk_signals, axis=1).mean(axis=1).clip(-1, 1)
        else:
            result["sector_risk_appetite"] = 0.0

        # Normalize timezone before filtering
        if result.index.tz is not None:
            result.index = result.index.tz_localize(None)

        # Filter to requested date range using proper Timestamp slicing
        result = result.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        result = result.ffill().fillna(0.0)

        logger.info(f"Sector rotation: {len(result.columns)} features")
        return result
