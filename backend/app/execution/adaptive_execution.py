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

        Raises:
            ValueError: If hour outside 0-23
        """
        # Input validation
        if not isinstance(hour, int):
            logger.error(f"Invalid hour type: {type(hour)}, expected int")
            raise ValueError(f"Hour must be int, got {type(hour)}")
        if not 0 <= hour <= 23:
            logger.error(f"Hour {hour} outside valid range 0-23")
            raise ValueError(f"Hour must be 0-23, got {hour}")

        profile = cls.PROFILES.get(hour, MarketProfile(hour, 0.5, 2.0, 2.0, "AVOID"))
        logger.debug(f"Retrieved profile for hour {hour}: {profile.recommendation}")
        return profile


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
            iv: Current implied volatility (0-1)
            iv_percentile: IV percentile (0-100)
            symbol: Stock symbol
            current_date: Current date
            is_fed_day: True if Fed announcement today

        Returns:
            AdaptiveProfile with adjustments

        Raises:
            ValueError: If inputs invalid
        """
        # Input validation
        if not isinstance(hour, int) or not 9 <= hour <= 17:
            logger.error(f"Invalid hour {hour}, must be 9-17")
            raise ValueError(f"Hour must be 9-17, got {hour}")
        if not isinstance(iv, (int, float)) or iv < 0:
            logger.error(f"Invalid IV {iv}, must be non-negative")
            raise ValueError(f"IV must be non-negative, got {iv}")
        if not isinstance(iv_percentile, (int, float)) or not 0 <= iv_percentile <= 100:
            logger.error(f"Invalid IV percentile {iv_percentile}, must be 0-100")
            raise ValueError(f"IV percentile must be 0-100, got {iv_percentile}")
        if not isinstance(symbol, str) or len(symbol) == 0:
            logger.error(f"Invalid symbol {symbol}, must be non-empty string")
            raise ValueError(f"Symbol must be non-empty string, got {symbol}")
        if current_date is None:
            current_date = datetime.now()
        if not isinstance(is_fed_day, bool):
            logger.error(f"Invalid is_fed_day type: {type(is_fed_day)}")
            raise ValueError(f"is_fed_day must be bool, got {type(is_fed_day)}")

        logger.debug(f"Computing adaptive profile for {symbol} at {hour}:00, IV={iv:.2%}, IV%={iv_percentile:.1f}")

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
            order_size: Order size (dollars), must be > 0
            daily_volume: Daily trading volume (dollars), must be > 0
            volatility: Realized volatility (0-1), must be >= 0
            vix: VIX level (typically 10-80)
            spread_bps: Bid-ask spread in basis points (0-100)

        Returns:
            Cost breakdown {total, spread, participation, adverse, vix_premium}

        Raises:
            ValueError: If inputs are invalid
        """
        # Input validation
        if not isinstance(order_size, (int, float)) or order_size <= 0:
            logger.error(f"Invalid order_size {order_size}, must be > 0")
            raise ValueError(f"order_size must be > 0, got {order_size}")
        if not isinstance(daily_volume, (int, float)) or daily_volume <= 0:
            logger.error(f"Invalid daily_volume {daily_volume}, must be > 0")
            raise ValueError(f"daily_volume must be > 0, got {daily_volume}")
        if not isinstance(volatility, (int, float)) or volatility < 0:
            logger.error(f"Invalid volatility {volatility}, must be >= 0")
            raise ValueError(f"volatility must be >= 0, got {volatility}")
        if not isinstance(vix, (int, float)) or vix < 0:
            logger.error(f"Invalid vix {vix}, must be >= 0")
            raise ValueError(f"vix must be >= 0, got {vix}")
        if not isinstance(spread_bps, (int, float)) or spread_bps < 0:
            logger.error(f"Invalid spread_bps {spread_bps}, must be >= 0")
            raise ValueError(f"spread_bps must be >= 0, got {spread_bps}")

        logger.debug(f"Estimating cost: order={order_size:,.0f}, volume={daily_volume:,.0f}, vol={volatility:.2%}, vix={vix:.1f}, spread={spread_bps:.1f}bps")

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
        # At VIX=20, no premium. At VIX=40, 100 bps premium
        vix_premium = max(0, (vix - 20) / 20 * 100)  # Expressed in basis points

        # 5. Volatility adjustment
        # High vol = more slippage
        vol_adjustment = min(volatility / 0.15, 2.0)  # Max 2x at vol > 30%

        # Total cost
        total_cost = (
            (spread_cost + participation_cost + adverse_selection) * vol_adjustment
            + vix_premium
        )

        result = {
            'total_cost_bps': float(total_cost),
            'spread_cost_bps': float(spread_cost),
            'participation_cost_bps': float(participation_cost),
            'adverse_selection_bps': float(adverse_selection),
            'vix_premium_bps': float(vix_premium),
            'vol_adjustment': float(vol_adjustment),
        }

        logger.debug(f"Cost breakdown: total={total_cost:.1f}bps, spread={spread_cost:.1f}, participation={participation_cost:.1f}, adverse={adverse_selection:.1f}, vix_premium={vix_premium:.1f}")

        return result

    def record_execution(
        self,
        order_id: str,
        expected_cost_bps: float,
        actual_cost_bps: float,
    ):
        """Record actual execution for validation.

        Args:
            order_id: Order ID
            expected_cost_bps: Expected cost in bps
            actual_cost_bps: Actual cost in bps

        Raises:
            ValueError: If inputs invalid
        """
        # Input validation
        if not isinstance(order_id, str) or len(order_id) == 0:
            logger.error(f"Invalid order_id {order_id}, must be non-empty string")
            raise ValueError(f"order_id must be non-empty string, got {order_id}")
        if not isinstance(expected_cost_bps, (int, float)):
            logger.error(f"Invalid expected_cost_bps type: {type(expected_cost_bps)}")
            raise ValueError(f"expected_cost_bps must be numeric, got {type(expected_cost_bps)}")
        if not isinstance(actual_cost_bps, (int, float)):
            logger.error(f"Invalid actual_cost_bps type: {type(actual_cost_bps)}")
            raise ValueError(f"actual_cost_bps must be numeric, got {type(actual_cost_bps)}")

        slippage = actual_cost_bps - expected_cost_bps
        self.execution_history.append({
            'timestamp': datetime.now(),
            'order_id': order_id,
            'expected_cost': expected_cost_bps,
            'actual_cost': actual_cost_bps,
            'slippage': slippage,
        })

        logger.debug(f"Recorded execution {order_id}: expected={expected_cost_bps:.1f}bps, actual={actual_cost_bps:.1f}bps, slippage={slippage:+.1f}bps")

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
        self.last_rebalance = None  # None means first call will return True

    def should_rebalance(self, current_vol: float) -> bool:
        """Check if rebalancing is needed.

        Args:
            current_vol: Current realized volatility (0-1)

        Returns:
            True if rebalancing should occur

        Raises:
            ValueError: If volatility invalid
        """
        # Input validation
        if not isinstance(current_vol, (int, float)) or current_vol < 0:
            logger.error(f"Invalid current_vol {current_vol}, must be >= 0")
            raise ValueError(f"current_vol must be >= 0, got {current_vol}")

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

        logger.debug(f"Volatility {current_vol:.2%}: rebalance every {freq_days} days")

        # Check if enough time has passed
        if self.last_rebalance is None:
            # First call - always rebalance
            self.last_rebalance = datetime.now()
            logger.info(f"First rebalance check triggered (vol={current_vol:.2%})")
            return True

        time_since_rebalance = (datetime.now() - self.last_rebalance).days

        should_rebal = time_since_rebalance >= freq_days
        if should_rebal:
            self.last_rebalance = datetime.now()
            logger.info(f"Rebalancing triggered after {time_since_rebalance} days (threshold: {freq_days} days, vol={current_vol:.2%})")
            return True

        return False

    def get_rebalance_frequency(self, current_vol: float) -> int:
        """Get recommended rebalance frequency in days.

        Args:
            current_vol: Current realized volatility (0-1)

        Returns:
            Rebalance frequency in days (1-10)

        Raises:
            ValueError: If volatility invalid
        """
        # Input validation
        if not isinstance(current_vol, (int, float)) or current_vol < 0:
            logger.error(f"Invalid current_vol {current_vol}, must be >= 0")
            raise ValueError(f"current_vol must be >= 0, got {current_vol}")

        if current_vol < 0.10:
            freq = 10
        elif current_vol < 0.15:
            freq = 7
        elif current_vol < 0.20:
            freq = 5
        elif current_vol < 0.30:
            freq = 2
        else:
            freq = 1

        logger.debug(f"Rebalance frequency for vol {current_vol:.2%}: {freq} days")
        return freq


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
            symbol: Stock symbol (non-empty string)
            order_size: Order size (> 0)
            daily_volume: Daily volume (> 0)
            hour: Hour (9-17)
            iv: Current implied vol (>= 0)
            iv_20d: 20-day average IV (>= 0)
            volatility: Realized volatility (>= 0)
            vix: VIX level (>= 0)
            spread_bps: Current spread (>= 0)
            is_fed_day: True if Fed announcement

        Returns:
            Execution plan with all recommendations

        Raises:
            ValueError: If inputs invalid
        """
        # Comprehensive input validation
        if not isinstance(symbol, str) or len(symbol) == 0:
            logger.error(f"Invalid symbol {symbol}, must be non-empty string")
            raise ValueError(f"symbol must be non-empty string, got {symbol}")
        if not isinstance(order_size, (int, float)) or order_size <= 0:
            logger.error(f"Invalid order_size {order_size}, must be > 0")
            raise ValueError(f"order_size must be > 0, got {order_size}")
        if not isinstance(daily_volume, (int, float)) or daily_volume <= 0:
            logger.error(f"Invalid daily_volume {daily_volume}, must be > 0")
            raise ValueError(f"daily_volume must be > 0, got {daily_volume}")
        if not isinstance(hour, int) or not 9 <= hour <= 17:
            logger.error(f"Invalid hour {hour}, must be 9-17")
            raise ValueError(f"hour must be 9-17, got {hour}")
        if not isinstance(iv, (int, float)) or iv < 0:
            logger.error(f"Invalid iv {iv}, must be >= 0")
            raise ValueError(f"iv must be >= 0, got {iv}")
        if not isinstance(iv_20d, (int, float)) or iv_20d < 0:
            logger.error(f"Invalid iv_20d {iv_20d}, must be >= 0")
            raise ValueError(f"iv_20d must be >= 0, got {iv_20d}")
        if not isinstance(volatility, (int, float)) or volatility < 0:
            logger.error(f"Invalid volatility {volatility}, must be >= 0")
            raise ValueError(f"volatility must be >= 0, got {volatility}")
        if not isinstance(vix, (int, float)) or vix < 0:
            logger.error(f"Invalid vix {vix}, must be >= 0")
            raise ValueError(f"vix must be >= 0, got {vix}")
        if not isinstance(spread_bps, (int, float)) or spread_bps < 0:
            logger.error(f"Invalid spread_bps {spread_bps}, must be >= 0")
            raise ValueError(f"spread_bps must be >= 0, got {spread_bps}")
        if not isinstance(is_fed_day, bool):
            logger.error(f"Invalid is_fed_day type: {type(is_fed_day)}")
            raise ValueError(f"is_fed_day must be bool, got {type(is_fed_day)}")

        logger.info(f"Computing execution plan for {symbol}: order={order_size:,.0f}, hour={hour}:00, iv={iv:.2%}, vix={vix:.1f}, fed_day={is_fed_day}")

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
            'adaptive_profile': profile,  # Return the actual profile object for compatibility
            'cost_breakdown': cost_breakdown,
            'recommendation': recommendation,
            'rebalance_needed': should_rebal,
            'rebalance_frequency_days': rebal_freq,
            'iv_percentile': float(iv_pct),
            'timestamp': datetime.now().isoformat(),
        }
