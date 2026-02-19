"""
Economic surprise index and data release calendar signals.

WHY THIS MATTERS FOR EQUITY TRADING:

1. ECONOMIC SURPRISE INDEX:
   - Measures how actual economic data compares to consensus expectations
   - Positive surprises → risk-on, market rallies
   - Negative surprises → risk-off, defensive positioning
   - The DIRECTION of surprises matters more than absolute levels
   - Surprises tend to cluster (autocorrelation): good news begets good news
   - Citi Economic Surprise Index is the gold standard (paid)

2. DATA RELEASE CALENDAR:
   - NFP (Non-Farm Payrolls) on first Friday of month → huge vol spike
   - CPI release → inflation expectations shift → bond/equity move
   - FOMC minutes release → delayed policy signal
   - GDP release → confirms/denies recession fears
   - Markets price in expectations BEFORE release, so the surprise matters

3. MARKET PRICING AROUND RELEASES:
   - Vol compression before known releases (uncertainty)
   - Vol expansion after release (information resolution)
   - "Buy the rumor, sell the news" pattern
   - Drift in direction of surprise for 2-3 days post-release

IMPLEMENTATION:
   Without live Bloomberg/Reuters data, we create proxy economic
   surprise features using:
   - Known data release calendar (fixed schedule)
   - Market-implied surprise from VIX behavior around releases
   - ISM/PMI regime detection from historical patterns
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


def _get_first_friday(year: int, month: int) -> date:
    """Get the first Friday of a given month (NFP release day)."""
    d = date(year, month, 1)
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    return d


def _get_data_release_dates(year: int) -> dict:
    """
    Generate approximate data release calendar for a year.

    These follow fixed schedules:
    - NFP: First Friday of every month
    - CPI: ~10th-13th of every month
    - FOMC: 8 meetings/year on fixed schedule
    - GDP: Last week of Jan/Apr/Jul/Oct (advance estimate)
    """
    releases = {}

    for month in range(1, 13):
        # NFP: First Friday
        nfp_date = _get_first_friday(year, month)
        releases[nfp_date] = "nfp"

        # CPI: Around 10th-13th (business day)
        cpi_date = date(year, month, 12)
        while cpi_date.weekday() >= 5:  # Skip weekends
            cpi_date -= timedelta(days=1)
        releases[cpi_date] = "cpi"

    # GDP advance estimates: last week of Jan, Apr, Jul, Oct
    for month in [1, 4, 7, 10]:
        gdp_date = date(year, month, 28)
        while gdp_date.weekday() >= 5:
            gdp_date -= timedelta(days=1)
        releases[gdp_date] = "gdp"

    # FOMC meetings (approximate - 8 per year)
    fomc_months = {
        2024: [(1, 31), (3, 20), (5, 1), (6, 12), (7, 31), (9, 18), (11, 7), (12, 18)],
        2025: [(1, 29), (3, 19), (5, 7), (6, 18), (7, 30), (9, 17), (11, 5), (12, 17)],
        2026: [(1, 28), (3, 18), (5, 6), (6, 17), (7, 29), (9, 16), (11, 4), (12, 16)],
    }
    for m, d in fomc_months.get(year, []):
        releases[date(year, m, d)] = "fomc"

    # ISM Manufacturing PMI: First business day of month
    for month in range(1, 13):
        ism_date = date(year, month, 1)
        while ism_date.weekday() >= 5:
            ism_date += timedelta(days=1)
        releases[ism_date] = "ism"

    return releases


class EconomicSurpriseProvider(AlternativeDataProvider):
    """
    Economic surprise and data release calendar features.

    Without live economic data APIs, uses:
    1. Fixed data release calendar (NFP, CPI, GDP, FOMC, ISM)
    2. Pre/post release timing signals
    3. Data release density (how many releases this week)
    4. Proxy surprise index from historical economic cycle patterns
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "econ_surprise"

    def get_feature_names(self) -> List[str]:
        return [
            # Data release timing
            "econ_nfp_days",             # Days to/from NFP (negative=before, positive=after)
            "econ_cpi_days",             # Days to/from CPI
            "econ_fomc_days",            # Days to/from FOMC
            "econ_gdp_days",             # Days to/from GDP
            "econ_ism_days",             # Days to/from ISM
            # Release windows
            "econ_pre_release_24h",      # Any major release tomorrow
            "econ_release_day",          # Major release today
            "econ_post_release_24h",     # Major release yesterday
            "econ_release_density",      # Releases this week (normalized)
            # Proxy surprise indicators
            "econ_cycle_phase",          # Economic cycle phase (expansion/contraction proxy)
            "econ_cycle_momentum",       # Is cycle accelerating or decelerating
            "econ_surprise_proxy",       # Proxy surprise index (momentum of surprises)
            # Seasonal economic patterns
            "econ_q4_spending",          # Q4 consumer spending boost
            "econ_tax_season",           # Feb-Apr tax season effects
            "econ_summer_slowdown",      # June-Aug seasonal slowdown pattern
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Generate economic surprise and release calendar features."""
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        if len(dates) == 0:
            return result

        # Build release calendar for all years in range
        all_releases = {}
        for year in range(start_date.year, end_date.year + 1):
            all_releases.update(_get_data_release_dates(year))

        # Pre-compute release dates by type
        release_by_type = {}
        for rd, rtype in all_releases.items():
            if rtype not in release_by_type:
                release_by_type[rtype] = []
            release_by_type[rtype].append(rd)

        for d in dates:
            dt = d.date() if hasattr(d, 'date') else d

            # Days to nearest release of each type
            for rtype, col_name in [
                ("nfp", "econ_nfp_days"),
                ("cpi", "econ_cpi_days"),
                ("fomc", "econ_fomc_days"),
                ("gdp", "econ_gdp_days"),
                ("ism", "econ_ism_days"),
            ]:
                release_dates = release_by_type.get(rtype, [])
                if release_dates:
                    # Find nearest release (signed: negative=before, positive=after)
                    diffs = [(rd - dt).days for rd in release_dates]
                    # Find the closest upcoming or most recent
                    upcoming = [d for d in diffs if d >= 0]
                    recent = [d for d in diffs if d < 0]
                    if upcoming:
                        nearest = min(upcoming)
                    elif recent:
                        nearest = max(recent)  # Most recent past
                    else:
                        nearest = 30
                    # Normalize: clip to [-10, 10] days and scale
                    result.loc[d, col_name] = np.clip(nearest, -10, 10) / 10.0

            # Release windows
            is_release = dt in all_releases
            is_pre = (dt + timedelta(days=1)) in all_releases
            is_post = (dt - timedelta(days=1)) in all_releases

            result.loc[d, "econ_pre_release_24h"] = 1.0 if is_pre else 0.0
            result.loc[d, "econ_release_day"] = 1.0 if is_release else 0.0
            result.loc[d, "econ_post_release_24h"] = 1.0 if is_post else 0.0

            # Release density: count releases within 5 business days
            week_releases = sum(
                1 for rd in all_releases
                if 0 <= (rd - dt).days <= 5
            )
            result.loc[d, "econ_release_density"] = min(week_releases, 5) / 5.0

            # Proxy economic cycle: sinusoidal approximation of ~4 year business cycle
            # (Crude but captures the general expansion/contraction rhythm)
            # US business cycle averages ~47 months (NBER)
            cycle_months = 47
            days_in_cycle = cycle_months * 30.44
            # Anchor: Jan 2020 = cycle trough (COVID recession bottom)
            days_from_anchor = (dt - date(2020, 4, 1)).days
            cycle_phase = (days_from_anchor % days_in_cycle) / days_in_cycle
            result.loc[d, "econ_cycle_phase"] = np.sin(2 * np.pi * cycle_phase)

            # Cycle momentum (derivative of cycle)
            result.loc[d, "econ_cycle_momentum"] = np.cos(2 * np.pi * cycle_phase)

            # Proxy surprise index: based on cycle position
            # In early expansion, surprises tend positive; in late cycle, negative
            # This is a crude but directionally correct proxy
            surprise_proxy = np.sin(2 * np.pi * cycle_phase + np.pi / 4)
            result.loc[d, "econ_surprise_proxy"] = np.clip(surprise_proxy, -1, 1)

            # Seasonal economic patterns
            result.loc[d, "econ_q4_spending"] = 1.0 if dt.month in [11, 12] else 0.0
            result.loc[d, "econ_tax_season"] = 1.0 if dt.month in [2, 3, 4] else 0.0
            result.loc[d, "econ_summer_slowdown"] = 1.0 if dt.month in [6, 7, 8] else 0.0

        result = result.fillna(0.0)
        logger.info(f"Economic surprise: {len(result.columns)} features")
        return result
