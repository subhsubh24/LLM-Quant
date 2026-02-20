"""
Earnings seasonality and reporting calendar signals provider.

WHY EARNINGS SEASONALITY MATTERS:

1. PRE-EARNINGS ANNOUNCEMENT DRIFT:
   - Stocks tend to drift UP in the 10 days before earnings
   - This effect has been documented for 40+ years
   - Lucca & Moench (2015) showed similar drift before FOMC
   - The drift is stronger for stocks with positive recent momentum

2. POST-EARNINGS ANNOUNCEMENT DRIFT (PEAD):
   - One of the most robust anomalies in finance
   - Stocks that beat estimates continue to outperform for 60 days
   - Stocks that miss continue to underperform
   - We capture the CALENDAR of when earnings cluster

3. EARNINGS SEASON PATTERNS:
   - Earnings season starts ~2 weeks after quarter end
   - Week 2-3 of Jan/Apr/Jul/Oct = peak earnings density
   - Market volatility rises during earnings season
   - Cross-stock correlations drop (idiosyncratic news dominates)

4. DAY-OF-WEEK EFFECTS:
   - Monday earnings tend to be worse (bad news Friday dump)
   - Tuesday/Wednesday are most common for large-caps
   - Thursday after-close is popular for "bad news burial"

IMPLEMENTATION:
   Zero API cost - computed entirely from calendar dates.
   Works perfectly offline.
"""

from datetime import date
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class EarningsSeasonalityProvider(AlternativeDataProvider):
    """
    Earnings calendar and seasonality features.

    Computes:
    - Earnings season indicator (peak reporting periods)
    - Pre/post earnings drift windows
    - Quarter-end rebalancing effects
    - Day-of-week seasonal patterns
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "earnings_seasonality"

    def get_feature_names(self) -> List[str]:
        return [
            # Earnings season phases
            "earn_season_peak",           # Peak earnings reporting week
            "earn_season_early",          # Early earnings (week 1-2 after Q end)
            "earn_season_late",           # Late earnings (week 5-6 after Q end)
            "earn_pre_drift_window",      # 10 days before typical earnings cluster
            # Quarter-end effects
            "earn_quarter_end_5d",        # Within 5 bdays of quarter end (rebalancing)
            "earn_quarter_start_5d",      # First 5 bdays of new quarter
            "earn_window_dressing",       # Last 3 bdays of quarter (fund window dressing)
            # Day-of-week effects
            "earn_day_monday",            # Monday (historically weaker)
            "earn_day_friday",            # Friday (pre-weekend risk)
            # Seasonal patterns
            "earn_january_effect",        # January small-cap outperformance
            "earn_halloween_indicator",   # Nov-Apr historically stronger
            "earn_sell_in_may",           # May-Oct historically weaker
            # Volatility seasonality
            "earn_vol_season_high",       # High-vol months (Sep, Oct)
            "earn_vol_season_low",        # Low-vol months (Dec, Apr)
            # Week-of-month effects
            "earn_week_1",               # First week of month
            "earn_week_3",               # OpEx week (options expiration)
            # Sinusoidal quarter encoding
            "earn_quarter_sin",          # Smooth quarter-cycle encoding
            "earn_quarter_cos",          # Cosine quarter encoding
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Generate earnings seasonality features (all computed from dates)."""
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        if len(dates) == 0:
            return result

        date_objs = np.array([d.date() for d in dates])
        months = np.array([dt.month for dt in date_objs])
        days = np.array([dt.day for dt in date_objs])
        dow = np.array([dt.weekday() for dt in date_objs])  # 0=Monday

        # --- Earnings season phases ---
        # Peak earnings: weeks 2-4 after quarter end (Jan 15-31, Apr 15-30, Jul 15-31, Oct 15-31)
        peak_months = np.isin(months, [1, 4, 7, 10])
        result["earn_season_peak"] = (peak_months & (days >= 15)).astype(float)

        # Early earnings: first 2 weeks after quarter end
        result["earn_season_early"] = (peak_months & (days < 15)).astype(float)

        # Late earnings: weeks 5-6 (Feb 1-15, May 1-15, Aug 1-15, Nov 1-15)
        late_months = np.isin(months, [2, 5, 8, 11])
        result["earn_season_late"] = (late_months & (days <= 15)).astype(float)

        # Pre-earnings drift window: 10 bdays before peak earnings
        # Approximate: last 10 bdays of quarter-end month (Mar, Jun, Sep, Dec)
        q_end_months = np.isin(months, [3, 6, 9, 12])
        result["earn_pre_drift_window"] = (q_end_months & (days >= 18)).astype(float)

        # --- Quarter-end effects ---
        # Quarter ends: Mar 31, Jun 30, Sep 30, Dec 31
        # Use business day proximity
        date_series = pd.Series(dates, index=dates)
        ym = date_series.dt.to_period('Q')
        bday_rank = ym.groupby(ym).cumcount() + 1
        bday_reverse_rank = ym.groupby(ym).cumcount(ascending=False) + 1

        result["earn_quarter_end_5d"] = (bday_reverse_rank <= 5).astype(float)
        result["earn_quarter_start_5d"] = (bday_rank <= 5).astype(float)
        result["earn_window_dressing"] = (bday_reverse_rank <= 3).astype(float)

        # --- Day-of-week effects ---
        result["earn_day_monday"] = (dow == 0).astype(float)
        result["earn_day_friday"] = (dow == 4).astype(float)

        # --- Seasonal patterns ---
        result["earn_january_effect"] = (months == 1).astype(float)

        # Halloween indicator: Nov through April = strong period
        result["earn_halloween_indicator"] = (
            np.isin(months, [11, 12, 1, 2, 3, 4])
        ).astype(float)

        # Sell in May: May through October = weak period
        result["earn_sell_in_may"] = (
            np.isin(months, [5, 6, 7, 8, 9, 10])
        ).astype(float)

        # --- Volatility seasonality ---
        result["earn_vol_season_high"] = np.isin(months, [9, 10]).astype(float)
        result["earn_vol_season_low"] = np.isin(months, [4, 12]).astype(float)

        # --- Week-of-month effects ---
        result["earn_week_1"] = (days <= 7).astype(float)
        result["earn_week_3"] = ((days >= 15) & (days <= 21)).astype(float)

        # --- Sinusoidal quarter encoding ---
        # Smooth encoding of position within the quarter cycle
        day_of_year = np.array([dt.timetuple().tm_yday for dt in date_objs], dtype=float)
        quarter_phase = (day_of_year % 91.25) / 91.25 * 2 * np.pi
        result["earn_quarter_sin"] = np.sin(quarter_phase)
        result["earn_quarter_cos"] = np.cos(quarter_phase)

        result = result.fillna(0.0)
        logger.info(f"Earnings seasonality: {len(result.columns)} features")
        return result
