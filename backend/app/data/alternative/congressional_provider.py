"""
Congressional trading and political event signals.

WHY THIS MATTERS FOR EQUITY TRADING:

1. CONGRESSIONAL TRADING:
   - US lawmakers have historically outperformed the market by 6-12%/year
   - They have access to non-public policy information (committee briefings,
     regulatory actions, military intelligence)
   - STOCK Act (2012) requires disclosure within 45 days
   - Clustered buying by multiple congress members = strong signal
   - Academic research: Ziobrowski et al. (2004) "Abnormal Returns from
     the Common Stock Investments of the US Senate"

2. POLITICAL CYCLE:
   - Presidential cycle: Year 3 (pre-election) is historically strongest
   - Midterm cycle: stocks rally after midterms
   - Policy uncertainty around elections depresses multiples
   - Government shutdowns create temporary dislocations

3. POLICY SURPRISE:
   - Fed policy surprises move markets immediately
   - Fiscal policy (tax/spending) affects sector rotation
   - Regulatory changes create sector-specific alpha

IMPLEMENTATION:
   Without live Congressional trading data APIs (which are paid),
   we use policy/political cycle features as proxies. These capture
   the same underlying dynamics (political uncertainty, election cycles,
   fiscal policy phase) without needing real-time disclosure data.
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


# Key political dates (elections, inaugurations, debt ceiling deadlines)
_POLITICAL_EVENTS = {
    # US Presidential Elections (first Tuesday after first Monday in November)
    date(2024, 11, 5): "presidential_election",
    date(2022, 11, 8): "midterm_election",
    date(2026, 11, 3): "midterm_election",
    # Inaugurations
    date(2025, 1, 20): "inauguration",
    # Notable debt ceiling / shutdown events
    date(2023, 6, 3): "debt_ceiling_deal",
    date(2024, 3, 22): "funding_deadline",
    date(2025, 3, 14): "funding_deadline",
}


class CongressionalProvider(AlternativeDataProvider):
    """
    Political cycle and policy signal features.

    Captures presidential cycle, election proximity, policy uncertainty,
    and government event effects on markets.
    """

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "congressional"

    def get_feature_names(self) -> List[str]:
        return [
            # Presidential cycle (4-year)
            "pol_presidential_year",      # 1-4 (year in presidential term)
            "pol_preelection_year",       # Binary: year 3 of cycle (historically strongest)
            "pol_election_year",          # Binary: year 4 of cycle
            "pol_postelection_year",      # Binary: year 1 of cycle
            # Election proximity
            "pol_days_to_election",       # Days to next election (normalized)
            "pol_election_window_30d",    # Within 30 days of election
            "pol_election_window_90d",    # Within 90 days of election
            "pol_post_election_30d",      # 30 days after election (resolution rally)
            # Congressional session
            "pol_congress_in_session",    # Approximation: not August/late-Dec recess
            "pol_lame_duck_session",      # Nov-Jan of election year (unpredictable)
            # Policy uncertainty proxy
            "pol_fiscal_year_end",        # Sept 30 (shutdown risk)
            "pol_debt_ceiling_window",    # Near known debt ceiling deadlines
            # Seasonal political patterns
            "pol_cycle_sin",             # Sinusoidal encoding of 4-year cycle
            "pol_cycle_cos",             # Cosine encoding of 4-year cycle
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Generate political cycle features (vectorized)."""
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        if len(dates) == 0:
            return result

        # Convert to python date array once
        date_objs = np.array([d.date() for d in dates])
        years = np.array([dt.year for dt in date_objs])
        months = np.array([dt.month for dt in date_objs])
        days = np.array([dt.day for dt in date_objs])

        # --- Presidential cycle (vectorized) ---
        year_in_cycle = ((years - 2025) % 4) + 1
        result["pol_presidential_year"] = year_in_cycle / 4.0
        result["pol_preelection_year"] = (year_in_cycle == 3).astype(float)
        result["pol_election_year"] = (year_in_cycle == 4).astype(float)
        result["pol_postelection_year"] = (year_in_cycle == 1).astype(float)

        # --- Days to next election (vectorized) ---
        next_elections = [date(2024, 11, 5), date(2026, 11, 3), date(2028, 11, 3)]
        dte = np.full(len(date_objs), 365.0)
        win_30 = np.zeros(len(date_objs))
        win_90 = np.zeros(len(date_objs))
        post_30 = np.zeros(len(date_objs))

        for e in next_elections:
            for i, dt in enumerate(date_objs):
                days_diff = (e - dt).days
                if days_diff >= 0:
                    dte[i] = min(dte[i], days_diff)
                if 0 <= days_diff <= 30:
                    win_30[i] = 1.0
                if 0 <= days_diff <= 90:
                    win_90[i] = 1.0
                days_after = (dt - e).days
                if 0 <= days_after <= 30:
                    post_30[i] = 1.0

        result["pol_days_to_election"] = np.minimum(dte, 730) / 730.0
        result["pol_election_window_30d"] = win_30
        result["pol_election_window_90d"] = win_90
        result["pol_post_election_30d"] = post_30

        # --- Congressional session (vectorized) ---
        in_session = np.ones(len(date_objs))
        in_session[months == 8] = 0.0
        in_session[(months == 12) & (days > 20)] = 0.0
        result["pol_congress_in_session"] = in_session

        # --- Lame duck session (vectorized) ---
        is_lame_duck = (
            ((year_in_cycle == 4) & (months >= 11)) |
            ((year_in_cycle == 1) & (months == 1) & (days < 20))
        )
        result["pol_lame_duck_session"] = is_lame_duck.astype(float)

        # --- Fiscal year end (vectorized) ---
        fiscal_end = np.zeros(len(date_objs))
        for i, dt in enumerate(date_objs):
            fy = date(dt.year, 9, 30)
            days_to_fy = (fy - dt).days
            if days_to_fy < 0:
                days_to_fy = (date(dt.year + 1, 9, 30) - dt).days
            if days_to_fy <= 14:
                fiscal_end[i] = 1.0
        result["pol_fiscal_year_end"] = fiscal_end

        # --- Debt ceiling window (vectorized) ---
        debt_events = [
            evt for evt, kind in _POLITICAL_EVENTS.items()
            if kind in ("debt_ceiling_deal", "funding_deadline")
        ]
        debt_window = np.zeros(len(date_objs))
        for evt in debt_events:
            for i, dt in enumerate(date_objs):
                if abs((evt - dt).days) <= 30:
                    debt_window[i] = 1.0
        result["pol_debt_ceiling_window"] = debt_window

        # --- Sinusoidal encoding (fully vectorized) ---
        inauguration = date(2025, 1, 20)
        days_since = np.array([(dt - inauguration).days for dt in date_objs], dtype=float)
        cycle_phase = (days_since % (4 * 365.25)) / (4 * 365.25) * 2 * np.pi
        result["pol_cycle_sin"] = np.sin(cycle_phase)
        result["pol_cycle_cos"] = np.cos(cycle_phase)

        result = result.fillna(0.0)
        logger.info(f"Congressional/political: {len(result.columns)} features")
        return result
