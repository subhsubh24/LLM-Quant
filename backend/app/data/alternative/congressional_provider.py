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
        """Generate political cycle features."""
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        if len(dates) == 0:
            return result

        for d in dates:
            dt = d.date() if hasattr(d, 'date') else d

            # Presidential cycle (using Jan 20 inauguration as anchor)
            # 2025 = year 1, 2026 = year 2, 2027 = year 3, 2028 = year 4
            year_in_cycle = ((dt.year - 2025) % 4) + 1
            result.loc[d, "pol_presidential_year"] = year_in_cycle / 4.0  # Normalize to 0-1

            result.loc[d, "pol_preelection_year"] = 1.0 if year_in_cycle == 3 else 0.0
            result.loc[d, "pol_election_year"] = 1.0 if year_in_cycle == 4 else 0.0
            result.loc[d, "pol_postelection_year"] = 1.0 if year_in_cycle == 1 else 0.0

            # Days to next election
            next_elections = [
                date(2024, 11, 5), date(2026, 11, 3), date(2028, 11, 3),
            ]
            days_to_election = min(
                (e - dt).days for e in next_elections if e >= dt
            ) if any(e >= dt for e in next_elections) else 365
            result.loc[d, "pol_days_to_election"] = min(days_to_election, 730) / 730.0

            # Election windows
            for e in next_elections:
                days_diff = (e - dt).days
                if 0 <= days_diff <= 30:
                    result.loc[d, "pol_election_window_30d"] = 1.0
                if 0 <= days_diff <= 90:
                    result.loc[d, "pol_election_window_90d"] = 1.0
                days_after = (dt - e).days
                if 0 <= days_after <= 30:
                    result.loc[d, "pol_post_election_30d"] = 1.0

            # Congressional session (approximate: recess in Aug, late Dec)
            in_session = 1.0
            if dt.month == 8:  # August recess
                in_session = 0.0
            elif dt.month == 12 and dt.day > 20:  # Holiday recess
                in_session = 0.0
            result.loc[d, "pol_congress_in_session"] = in_session

            # Lame duck session (Nov-Jan of election year)
            is_lame_duck = (
                (year_in_cycle == 4 and dt.month >= 11) or
                (year_in_cycle == 1 and dt.month == 1 and dt.day < 20)
            )
            result.loc[d, "pol_lame_duck_session"] = 1.0 if is_lame_duck else 0.0

            # Fiscal year end (Sept 30 - shutdown risk)
            days_to_fy = (date(dt.year, 9, 30) - dt).days
            if days_to_fy < 0:
                days_to_fy = (date(dt.year + 1, 9, 30) - dt).days
            result.loc[d, "pol_fiscal_year_end"] = 1.0 if days_to_fy <= 14 else 0.0

            # Debt ceiling window
            near_debt_event = any(
                abs((evt - dt).days) <= 30
                for evt, kind in _POLITICAL_EVENTS.items()
                if kind in ("debt_ceiling_deal", "funding_deadline")
            )
            result.loc[d, "pol_debt_ceiling_window"] = 1.0 if near_debt_event else 0.0

            # Sinusoidal encoding of 4-year presidential cycle
            # Phase: 0 at inauguration (Jan 20), full cycle over 4 years
            days_since_inauguration = (dt - date(2025, 1, 20)).days
            cycle_phase = (days_since_inauguration % (4 * 365.25)) / (4 * 365.25) * 2 * np.pi
            result.loc[d, "pol_cycle_sin"] = np.sin(cycle_phase)
            result.loc[d, "pol_cycle_cos"] = np.cos(cycle_phase)

        # Fill any NaN with 0
        result = result.fillna(0.0)

        logger.info(f"Congressional/political: {len(result.columns)} features")
        return result
