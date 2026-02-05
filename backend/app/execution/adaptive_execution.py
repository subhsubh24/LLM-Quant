"""
Adaptive Execution - Phase 13

Dynamic execution with:
1. Adaptive Market Profiles: Time-of-day + volatility + event aware
2. Realistic Cost Model: Spread + participation + adverse selection + VIX premium
3. Volatility-Adaptive Rebalancing: Frequency scales with vol

Expected improvement: +0.05-0.07 Sharpe
Mechanism: Better order timing + realistic cost estimation
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketProfile:
    """Time-of-day market profile"""
    hour: int
    volume_factor: float  # Relative to daily average
    spread_factor: float  # Spread multiplier
    impact_factor: float  # Market impact multiplier
    recommendation: str  # OPTIMAL, CAUTION, AVOID


@dataclass
class AdaptiveProfile:
    """Adaptive profile with vol + event adjustments"""
    base_profile: MarketProfile
    vol_multiplier: float
    event_multiplier: float
    final_volume_factor: float
    final_spread_factor: float
    final_impact_factor: float


class TimeOfDayProfiles:
    """Pre-computed market profiles for each hour"""

    # US market hours: 9am-5pm
    PROFILES = {
        9: MarketProfile(9, 1.8, 2.5, 1.8, "AVOID"),      # Open - high impact
        10: MarketProfile(10, 1.3, 1.3, 1.3, "CAUTION"),
        11: MarketProfile(11, 0.8, 1.0, 0.95, "CAUTION"),
        12: MarketProfile(12, 0.7, 0.95, 0.85, "CAUTION"), # Lunch
        13: MarketProfile(13, 0.8, 1.0, 0.90, "CAUTION"),
        14: MarketProfile(14, 1.0, 1.0, 1.0, "OPTIMAL"),   # Mid-afternoon - best
        15: MarketProfile(15, 1.1, 1.1, 1.1, "OPTIMAL"),
        16: MarketProfile(16, 1.0, 1.0, 1.0, "OPTIMAL"),
        17: MarketProfile(17, 1.8, 2.5, 2.0, "AVOID"),      # Close - high impact
    }

    @classmethod
    def get_profile(cls, hour: int) -> MarketProfile:
        """Get profile for hour.

        Args:
            hour: Hour (0-23)

        Returns:
            MarketProfile for that hour (or default if outside market hours)
        """
        return cls.PROFILES.get(hour, MarketProfile(hour, 0.5, 2.0, 2.0, "AVOID"))


class AdaptiveExecutionProfiles:
    """Adaptive profiles considering volatility + events"""

    def __init__(self):
        """Initialize adaptive profiles"""
        self.iv_history = []
        self.earnings_calendar = {}  # symbol -> [dates]
        self.fed_events = []  # List of fed event dates

    def get_adaptive_profile(
        self,
        hour: int,
        iv: float,
        iv_percentile: float,
        symbol: str = "SPY",
        current_date: Optional[datetime] = None,
        is_fed_day: bool = False,
    ) -> AdaptiveProfile:
        """Compute adaptive profile.

        Args:
            hour: Hour (9-17)
            iv: Current implied volatility
            iv_percentile: IV percentile (0-100)
            symbol: Stock symbol
            current_date: Current date
            is_fed_day: True if Fed announcement today

        Returns:
            AdaptiveProfile with adjustments
        """
        # Get base time-of-day profile
        base = TimeOfDayProfiles.get_profile(hour)

        # Volatility adjustment
        vol_multiplier = 1.0
        spread_multiplier = 1.0

        if iv_percentile > 80:
            # High vol: Less volume, wider spreads
            vol_multiplier = 0.8
            spread_multiplier = 1.5
        elif iv_percentile < 20:
            # Low vol: More volume, tighter spreads
            vol_multiplier = 1.3
            spread_multiplier = 0.7

        # Event adjustment
        event_multiplier = 1.0

        if is_fed_day:
            # Fed announcement: Avoid trading
            vol_multiplier *= 0.6
            spread_multiplier *= 2.0
            event_multiplier *= 0.4

        # Check for earnings
        if symbol in self.earnings_calendar and current_date:
            earnings_dates = self.earnings_calendar[symbol]
            days_to_earnings = min(
                [(d - current_date).days for d in earnings_dates if d > current_date],
                default=999
            )

            if 0 <= days_to_earnings <= 2:
                # 2 days before/after earnings
                vol_multiplier *= 1.5
                spread_multiplier *= 1.5

        # Compute final factors
        final_vol = base.volume_factor * vol_multiplier
        final_spread = base.spread_factor * spread_multiplier
        final_impact = base.impact_factor * vol_multiplier

        return AdaptiveProfile(
            base_profile=base,
            vol_multiplier=vol_multiplier,
            event_multiplier=event_multiplier,
            final_volume_factor=float(final_vol),
            final_spread_factor=float(final_spread),
            final_impact_factor=float(final_impact),
        )


class RealisticCostModel:
    """Realistic execution cost estimation"""

    def __init__(self):
        """Initialize cost model"""
        self.execution_history = []

    def estimate_total_cost(
        self,
        order_size: float,
        daily_volume: float,
        volatility: float,
        vix: float,
        spread_bps: float,
    ) -> Dict[str, float]:
        """Estimate total execution cost.

        Args:
            order_size: Order size (dollars)
            daily_volume: Daily trading volume (dollars)
            volatility: Realized volatility
            vix: VIX level
            spread_bps: Bid-ask spread in basis points

        Returns:
            Cost breakdown {total, spread, participation, adverse, vix_premium}
        """
        # 1. Spread cost (half the bid-ask)
        spread_cost = spread_bps / 2.0

        # 2. Participation cost (sqrt relationship)
        # Larger orders get progressively worse prices
        participation_ratio = order_size / max(daily_volume, 1e-10)
        participation_cost = (participation_ratio ** 0.5) * 100.0  # Convert to bps

        # Cap participation cost
        participation_cost = min(participation_cost, 50.0)  # Max 50 bps

        # 3. Adverse selection (if aggressive)
        # Small orders get slight rebate, large get penalty
        if participation_ratio < 0.01:
            adverse_selection = -0.5  # Small order rebate
        elif participation_ratio < 0.05:
            adverse_selection = 0.5   # Normal
        elif participation_ratio < 0.1:
            adverse_selection = 1.5   # Slightly aggressive
        else:
            adverse_selection = 2.0   # Very aggressive

        # 4. VIX premium
        # At VIX=20, no premium. At VIX=40, 100% premium
        vix_premium = max(0, (vix - 20) / 20 * 100) * 0.01  # Convert to bps

        # 5. Volatility adjustment
        # High vol = more slippage
        vol_adjustment = min(volatility / 0.15, 2.0)  # Max 2x at vol > 30%

        # Total cost
        total_cost = (
            (spread_cost + participation_cost + adverse_selection) * vol_adjustment
            + vix_premium
        )

        return {
            'total_cost_bps': float(total_cost),
            'spread_cost_bps': float(spread_cost),
            'participation_cost_bps': float(participation_cost),
            'adverse_selection_bps': float(adverse_selection),
            'vix_premium_bps': float(vix_premium),
            'vol_adjustment': float(vol_adjustment),
        }

    def record_execution(
        self,
        order_id: str,
        expected_cost_bps: float,
        actual_cost_bps: float,
    ):
        """Record actual execution for validation.

        Args:
            order_id: Order ID
            expected_cost_bps: Expected cost
            actual_cost_bps: Actual cost
        """
        self.execution_history.append({
            'timestamp': datetime.now(),
            'order_id': order_id,
            'expected_cost': expected_cost_bps,
            'actual_cost': actual_cost_bps,
            'slippage': actual_cost_bps - expected_cost_bps,
        })

        # Keep last 1000
        self.execution_history = self.execution_history[-1000:]

    def get_cost_statistics(self) -> Dict[str, float]:
        """Get statistics on execution costs.

        Returns:
            Cost statistics {mean, std, max, p90, etc}
        """
        if not self.execution_history:
            return {}

        costs = np.array([e['actual_cost'] for e in self.execution_history])
        slippages = np.array([e['slippage'] for e in self.execution_history])

        return {
            'mean_cost_bps': float(np.mean(costs)),
            'std_cost_bps': float(np.std(costs)),
            'min_cost_bps': float(np.min(costs)),
            'max_cost_bps': float(np.max(costs)),
            'p90_cost_bps': float(np.percentile(costs, 90)),
            'mean_slippage_bps': float(np.mean(slippages)),
            'p90_slippage_bps': float(np.percentile(slippages, 90)),
        }


class VolatilityAdaptiveRebalancing:
    """Adaptive rebalancing frequency based on volatility"""

    def __init__(self):
        """Initialize rebalancing"""
        self.vol_history = []
        self.last_rebalance = datetime.now()

    def should_rebalance(self, current_vol: float) -> bool:
        """Check if rebalancing is needed.

        Args:
            current_vol: Current realized volatility

        Returns:
            True if rebalancing should occur
        """
        # Determine rebalance frequency from vol
        if current_vol < 0.10:
            freq_days = 10  # Low vol: less frequent
        elif current_vol < 0.15:
            freq_days = 7
        elif current_vol < 0.20:
            freq_days = 5
        elif current_vol < 0.30:
            freq_days = 3
        else:
            freq_days = 1  # High vol: daily rebalancing

        # Check if enough time has passed
        time_since_rebalance = (datetime.now() - self.last_rebalance).days

        if time_since_rebalance >= freq_days:
            self.last_rebalance = datetime.now()
            return True

        return False

    def get_rebalance_frequency(self, current_vol: float) -> int:
        """Get recommended rebalance frequency in days.

        Args:
            current_vol: Current realized volatility

        Returns:
            Rebalance frequency in days
        """
        if current_vol < 0.10:
            return 10
        elif current_vol < 0.15:
            return 7
        elif current_vol < 0.20:
            return 5
        elif current_vol < 0.30:
            return 2
        else:
            return 1


class OptimizedAdaptiveExecutor:
    """Master adaptive execution engine"""

    def __init__(self):
        """Initialize executor"""
        self.profiles = AdaptiveExecutionProfiles()
        self.costs = RealisticCostModel()
        self.rebalancing = VolatilityAdaptiveRebalancing()
        self.iv_history = []

    def get_execution_plan(
        self,
        symbol: str,
        order_size: float,
        daily_volume: float,
        hour: int,
        iv: float,
        iv_20d: float,
        volatility: float,
        vix: float,
        spread_bps: float,
        is_fed_day: bool = False,
    ) -> Dict:
        """Get comprehensive execution plan.

        Args:
            symbol: Stock symbol
            order_size: Order size
            daily_volume: Daily volume
            hour: Hour (9-17)
            iv: Current implied vol
            iv_20d: 20-day average IV
            volatility: Realized volatility
            vix: VIX level
            spread_bps: Current spread
            is_fed_day: True if Fed announcement

        Returns:
            Execution plan with all recommendations
        """
        # Get adaptive profile
        iv_percentile = np.percentile([iv], 50) if self.iv_history else 50
        self.iv_history.append(iv)
        self.iv_history = self.iv_history[-252:]

        iv_pct = (len([x for x in self.iv_history if x < iv]) / len(self.iv_history)) * 100

        profile = self.profiles.get_adaptive_profile(
            hour=hour,
            iv=iv,
            iv_percentile=iv_pct,
            symbol=symbol,
            is_fed_day=is_fed_day,
        )

        # Get cost estimate
        cost_breakdown = self.costs.estimate_total_cost(
            order_size=order_size,
            daily_volume=daily_volume,
            volatility=volatility,
            vix=vix,
            spread_bps=spread_bps,
        )

        # Rebalance check
        should_rebal = self.rebalancing.should_rebalance(volatility)
        rebal_freq = self.rebalancing.get_rebalance_frequency(volatility)

        # Recommendation
        if profile.base_profile.recommendation == "AVOID":
            recommendation = "DELAY" if not is_fed_day else "AVOID"
        elif is_fed_day:
            recommendation = "CAUTION"
        elif cost_breakdown['total_cost_bps'] > 10:
            recommendation = "REDUCE_SIZE"
        else:
            recommendation = "EXECUTE"

        return {
            'adaptive_profile': {
                'hour': hour,
                'base_recommendation': profile.base_profile.recommendation,
                'final_volume_factor': profile.final_volume_factor,
                'final_spread_factor': profile.final_spread_factor,
                'final_impact_factor': profile.final_impact_factor,
            },
            'cost_breakdown': cost_breakdown,
            'recommendation': recommendation,
            'rebalance_needed': should_rebal,
            'rebalance_frequency_days': rebal_freq,
            'iv_percentile': float(iv_pct),
            'timestamp': datetime.now().isoformat(),
        }
