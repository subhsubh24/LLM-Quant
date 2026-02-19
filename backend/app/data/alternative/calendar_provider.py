"""
Calendar and seasonal effects provider.

This costs NOTHING - it's computed from the date alone. Yet calendar
effects are among the most robust and well-documented anomalies:

TURN OF MONTH EFFECT:
  - Last 3 days + first 3 days of each month account for almost ALL
    of the market's long-term gains
  - Documented since the 1980s, still persists
  - Driven by institutional cash flows (pension funds, 401k contributions)

FOMC DRIFT:
  - The S&P 500 returns ~80% of its gains in the 24 hours BEFORE
    Fed announcements (Lucca & Moench, NY Fed, 2015)
  - One of the most profitable anomalies ever documented
  - Still works because it's driven by position unwinding ahead of uncertainty

DAY OF WEEK:
  - Monday effect (negative), Friday effect (positive)
  - Weakened in recent years but still statistically significant
  - Driven by news release timing and settlement patterns

HOLIDAY EFFECT:
  - Trading days before market holidays show abnormally positive returns
  - Pre-holiday returns are 9-14x normal daily average
  - Works because short-sellers cover before holidays

MONTHLY SEASONALITY:
  - "Sell in May" (May-Oct underperforms Nov-Apr)
  - January effect (small caps outperform)
  - September effect (historically worst month)
  - Tax-loss selling in December

OPTIONS EXPIRATION:
  - Quad witching (3rd Friday of Mar, Jun, Sep, Dec) = high volume, mean reversion
  - Monthly OpEx creates pin risk around popular strikes
  - Gamma exposure drives spot toward max pain

QUARTER END:
  - Window dressing by institutional managers
  - Rebalancing flows from pension funds and target-date funds
  - Tends to push recent winners higher and losers lower
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)

# FOMC meeting dates (historical + scheduled)
# These are publicly announced well in advance
FOMC_DATES_2023_2026 = [
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
]

# Major US market holidays (market closed)
US_HOLIDAYS_NAMES = [
    "New Year", "MLK Day", "Presidents Day", "Good Friday",
    "Memorial Day", "Juneteenth", "Independence Day", "Labor Day",
    "Thanksgiving", "Christmas",
]


class CalendarEffectsProvider(AlternativeDataProvider):
    """
    Computes calendar-based and seasonal features from dates alone.

    Zero API cost. Proven anomalies. No look-ahead bias since all
    features are derived from the date itself (known in advance).
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()
        self._fomc_dates = pd.to_datetime(FOMC_DATES_2023_2026)

    @property
    def name(self) -> str:
        return "calendar"

    def get_feature_names(self) -> List[str]:
        return [
            # Day of week
            "cal_day_monday",
            "cal_day_friday",
            # Month seasonality
            "cal_month_jan",
            "cal_month_sep",
            "cal_month_oct",
            "cal_month_nov",
            "cal_month_dec",
            "cal_sell_in_may",
            # Turn of month
            "cal_turn_of_month",
            "cal_month_start",
            "cal_month_end",
            # Quarter effects
            "cal_quarter_end",
            "cal_quarter_start",
            "cal_quarter_end_window",
            # FOMC
            "cal_fomc_minus2",
            "cal_fomc_minus1",
            "cal_fomc_day",
            "cal_fomc_plus1",
            "cal_fomc_window",
            # Options expiration
            "cal_opex_week",
            "cal_opex_day",
            "cal_quad_witching",
            # Holiday effects
            "cal_pre_holiday",
            "cal_post_holiday",
            # Year effects
            "cal_year_start",
            "cal_year_end",
            # Day of month (cyclical encoding)
            "cal_dom_sin",
            "cal_dom_cos",
            # Week of year (cyclical encoding)
            "cal_woy_sin",
            "cal_woy_cos",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Compute all calendar features for the date range."""
        # Generate business day index
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        self._compute_day_of_week(result)
        self._compute_month_seasonality(result)
        self._compute_turn_of_month(result)
        self._compute_quarter_effects(result)
        self._compute_fomc_effects(result)
        self._compute_opex_effects(result)
        self._compute_holiday_effects(result)
        self._compute_year_effects(result)
        self._compute_cyclical_encoding(result)

        logger.info(
            f"Calendar: computed {len(result.columns)} features, "
            f"{len(result)} days"
        )

        return result

    def _compute_day_of_week(self, result: pd.DataFrame) -> None:
        """Monday and Friday effects."""
        dow = result.index.dayofweek
        result["cal_day_monday"] = (dow == 0).astype(float)
        result["cal_day_friday"] = (dow == 4).astype(float)

    def _compute_month_seasonality(self, result: pd.DataFrame) -> None:
        """Monthly seasonality indicators."""
        month = result.index.month
        result["cal_month_jan"] = (month == 1).astype(float)
        result["cal_month_sep"] = (month == 9).astype(float)
        result["cal_month_oct"] = (month == 10).astype(float)
        result["cal_month_nov"] = (month == 11).astype(float)
        result["cal_month_dec"] = (month == 12).astype(float)

        # Sell in May (May through October = historically weaker)
        result["cal_sell_in_may"] = ((month >= 5) & (month <= 10)).astype(float)

    def _compute_turn_of_month(self, result: pd.DataFrame) -> None:
        """Turn of month effect (last 3 + first 3 business days)."""
        dom = result.index.day
        days_in_month = result.index.to_series().apply(
            lambda x: pd.Timestamp(x.year, x.month, 1) + pd.offsets.MonthEnd(0)
        ).dt.day

        # First 3 business days
        result["cal_month_start"] = (dom <= 3).astype(float)

        # Last 3 business days (approximate)
        result["cal_month_end"] = (dom >= days_in_month - 3).astype(float)

        # Combined turn of month
        result["cal_turn_of_month"] = (
            (result["cal_month_start"] == 1) | (result["cal_month_end"] == 1)
        ).astype(float)

    def _compute_quarter_effects(self, result: pd.DataFrame) -> None:
        """Quarter-end window dressing effects."""
        month = result.index.month
        dom = result.index.day

        # Quarter-end months (March, June, September, December)
        is_quarter_end_month = month.isin([3, 6, 9, 12])
        is_quarter_start_month = month.isin([1, 4, 7, 10])

        # Quarter end: last 5 days of quarter
        days_in_month = result.index.to_series().apply(
            lambda x: pd.Timestamp(x.year, x.month, 1) + pd.offsets.MonthEnd(0)
        ).dt.day
        result["cal_quarter_end"] = (
            is_quarter_end_month & (dom >= days_in_month - 5)
        ).astype(float)

        # Quarter start: first 5 days
        result["cal_quarter_start"] = (
            is_quarter_start_month & (dom <= 5)
        ).astype(float)

        # Extended quarter-end window (last 10 days of quarter)
        result["cal_quarter_end_window"] = (
            is_quarter_end_month & (dom >= days_in_month - 10)
        ).astype(float)

    def _compute_fomc_effects(self, result: pd.DataFrame) -> None:
        """
        FOMC meeting drift effects.

        The pre-FOMC drift is one of the most profitable anomalies:
        stocks drift up in the 2 days before FOMC announcements.
        """
        dates = result.index

        # Create indicators for days relative to FOMC
        fomc_m2 = pd.Series(0.0, index=dates)
        fomc_m1 = pd.Series(0.0, index=dates)
        fomc_day = pd.Series(0.0, index=dates)
        fomc_p1 = pd.Series(0.0, index=dates)
        fomc_window = pd.Series(0.0, index=dates)

        for fomc_date in self._fomc_dates:
            # Find the business days around this FOMC date
            for i, d in enumerate(dates):
                diff = (d - fomc_date).days
                if diff == -2 or diff == -3:  # Account for weekends
                    fomc_m2.iloc[i] = 1.0
                elif diff == -1:
                    fomc_m1.iloc[i] = 1.0
                elif diff == 0:
                    fomc_day.iloc[i] = 1.0
                elif diff == 1:
                    fomc_p1.iloc[i] = 1.0

                # FOMC window: day-2 through day+1
                if -3 <= diff <= 1:
                    fomc_window.iloc[i] = 1.0

        result["cal_fomc_minus2"] = fomc_m2
        result["cal_fomc_minus1"] = fomc_m1
        result["cal_fomc_day"] = fomc_day
        result["cal_fomc_plus1"] = fomc_p1
        result["cal_fomc_window"] = fomc_window

    def _compute_opex_effects(self, result: pd.DataFrame) -> None:
        """
        Options expiration effects.

        Monthly OpEx: 3rd Friday of each month
        Quad witching: 3rd Friday of Mar, Jun, Sep, Dec
        """
        dates = result.index

        opex_day = pd.Series(0.0, index=dates)
        opex_week = pd.Series(0.0, index=dates)
        quad_witch = pd.Series(0.0, index=dates)

        for d in dates:
            # 3rd Friday: day 15-21 and Friday (weekday=4)
            if d.weekday() == 4 and 15 <= d.day <= 21:
                opex_day.loc[d] = 1.0

                # Quad witching months
                if d.month in [3, 6, 9, 12]:
                    quad_witch.loc[d] = 1.0

            # OpEx week: the week containing the 3rd Friday
            # Find 3rd Friday of this month
            first_day = pd.Timestamp(d.year, d.month, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)

            # Within 5 business days of OpEx
            days_to_opex = abs((d - third_friday).days)
            if days_to_opex <= 5:
                opex_week.loc[d] = 1.0

        result["cal_opex_day"] = opex_day
        result["cal_opex_week"] = opex_week
        result["cal_quad_witching"] = quad_witch

    def _compute_holiday_effects(self, result: pd.DataFrame) -> None:
        """
        Pre-holiday and post-holiday effects.

        Uses business day gaps to detect holidays (market closures).
        """
        dates = result.index

        # Detect holidays by gaps in business days
        day_diff = pd.Series(dates, index=dates).diff().dt.days
        post_holiday = (day_diff > 1).astype(float)  # Gap > 1 day = holiday before

        # Pre-holiday: the day before a gap
        pre_holiday = post_holiday.shift(-1).fillna(0)

        result["cal_pre_holiday"] = pre_holiday
        result["cal_post_holiday"] = post_holiday

    def _compute_year_effects(self, result: pd.DataFrame) -> None:
        """Year-start and year-end effects (tax, rebalancing)."""
        month = result.index.month
        dom = result.index.day

        # First 2 weeks of January (January effect)
        result["cal_year_start"] = ((month == 1) & (dom <= 15)).astype(float)

        # Last 2 weeks of December (tax-loss selling, Santa rally)
        result["cal_year_end"] = ((month == 12) & (dom >= 15)).astype(float)

    def _compute_cyclical_encoding(self, result: pd.DataFrame) -> None:
        """
        Cyclical encoding of day-of-month and week-of-year.

        Sin/cos encoding preserves the circular nature of time
        (December 31 is close to January 1, not far from it).
        """
        # Day of month (1-31) -> cyclical
        dom = result.index.day
        result["cal_dom_sin"] = np.sin(2 * np.pi * dom / 31)
        result["cal_dom_cos"] = np.cos(2 * np.pi * dom / 31)

        # Week of year (1-52) -> cyclical
        woy = result.index.isocalendar().week.values.astype(float)
        result["cal_woy_sin"] = np.sin(2 * np.pi * woy / 52)
        result["cal_woy_cos"] = np.cos(2 * np.pi * woy / 52)
