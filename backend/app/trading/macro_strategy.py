"""
Macro-Level Strategy Module for 1600h Trading

Handles:
1. Seasonal patterns (what month is it?)
2. Macro regimes (VIX, credit spreads)
3. Event calendar awareness (earnings, Fed)
4. Multi-horizon regime detection
5. Position sizing adjustments for macro events
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

class MacroStrategy:
    """Macro-aware trading strategy for 1600h predictions."""

    def __init__(self):
        self.vix_level = 20.0  # Default VIX
        self.credit_spread = 150.0  # Default OAS in bps
        self.fed_rate = 5.0  # Default Fed funds rate
        self.current_month = datetime.now().month
        self.current_quarter = (datetime.now().month - 1) // 3 + 1

        # Macro event calendar
        self.earnings_season_months = [1, 4, 7, 10]  # Q1, Q2, Q3, Q4 earnings
        self.fed_meeting_months = [1, 3, 5, 6, 7, 9, 11, 12]  # ~8 per year
        self.major_economic_data_days = {
            "nonfarm_payrolls": 1,  # First Friday of month
            "cpi": 2,  # Second week
            "gdp": 3,  # Third week
        }

    def get_seasonal_features(self, timestamp: datetime) -> Dict:
        """Extract seasonal features for given timestamp."""
        month = timestamp.month
        quarter = (month - 1) // 3 + 1
        day_of_year = timestamp.timetuple().tm_yday
        week_of_year = timestamp.isocalendar()[1]

        # Seasonal patterns (based on historical market behavior)
        seasonal_score = self._get_seasonal_score(month)

        return {
            "month": month,
            "quarter": quarter,
            "day_of_year": day_of_year,
            "week_of_year": week_of_year,
            "seasonal_score": seasonal_score,  # -1 to +1 based on historical returns
            "is_earnings_season": month in self.earnings_season_months,
            "is_fed_meeting_month": month in self.fed_meeting_months,
            "days_to_month_end": 31 - day_of_year % 31,  # Approximate
        }

    def _get_seasonal_score(self, month: int) -> float:
        """
        Historical seasonal patterns (based on SPY/stock market data).
        Positive = historically bullish months
        Negative = historically bearish months
        """
        seasonal_patterns = {
            1: 0.02,    # January: Decent (but watch Jan effect)
            2: -0.01,   # February: Slight headwind
            3: 0.01,    # March: Neutral
            4: 0.03,    # April: Bullish (post-earnings)
            5: -0.02,   # May: "Sell in May" (weaker)
            6: -0.01,   # June: Slight headwind
            7: 0.02,    # July: Summer rally
            8: -0.02,   # August: Weak (historically)
            9: -0.03,   # September: Worst month (historically)
            10: 0.01,   # October: Turnaround
            11: 0.04,   # November: Strong (pre-holiday)
            12: 0.05,   # December: Santa rally
        }
        return seasonal_patterns.get(month, 0.0)

    def get_macro_regime(self, vix_level: float = 20, credit_spread: float = 150, timestamp: Optional[datetime] = None) -> Dict:
        """
        Determine macro regime based on VIX and credit spreads.

        Regimes:
        - RISK_ON: Low VIX (<15), tight spreads (<100), risk appetite high
        - BALANCED: Moderate VIX (15-25), spreads (100-200)
        - RISK_OFF: High VIX (>25), wide spreads (>200), risk aversion
        """
        if timestamp is None:
            timestamp = datetime.now()

        vix_regime = "low" if vix_level < 15 else ("high" if vix_level > 25 else "moderate")
        spread_regime = "tight" if credit_spread < 100 else ("wide" if credit_spread > 200 else "moderate")

        # Overall regime
        if vix_level < 15 and credit_spread < 100:
            overall_regime = "RISK_ON"
            risk_score = 1.0  # High risk appetite
        elif vix_level > 25 or credit_spread > 200:
            overall_regime = "RISK_OFF"
            risk_score = 0.3  # Low risk appetite
        else:
            overall_regime = "BALANCED"
            risk_score = 0.7  # Moderate risk appetite

        # Get seasonal factor
        seasonal_score = self._get_seasonal_score(timestamp.month)
        seasonal_factor = 1.0 + seasonal_score  # Convert to multiplier (0.95 to 1.05)

        return {
            "vix_regime": vix_regime,
            "spread_regime": spread_regime,
            "overall_regime": overall_regime,
            "risk_score": risk_score,
            "vix_level": vix_level,
            "credit_spreads": credit_spread,
            "credit_spread": credit_spread,  # Both names for compatibility
            "seasonal_factor": seasonal_factor,
            "timestamp": timestamp,
        }

    def get_position_size_multiplier(self, macro_regime: Dict, prediction_confidence: float) -> float:
        """
        Adjust position size based on macro regime.

        RISK_ON: 1.2x normal (good environment)
        BALANCED: 1.0x normal
        RISK_OFF: 0.5x normal (reduce exposure)
        """
        regime_mult = {
            "RISK_ON": 1.2,
            "BALANCED": 1.0,
            "RISK_OFF": 0.5,
        }

        base_mult = regime_mult.get(macro_regime["overall_regime"], 1.0)

        # Confidence also matters
        conf_mult = 0.8 + (prediction_confidence - 0.5) * 0.4  # 0.8 to 1.2

        return base_mult * conf_mult

    def get_event_risk_adjustment(self, timestamp: datetime, days_ahead: int = 5) -> float:
        """
        Reduce position size near major economic events.

        Events: Fed meetings, CPI, Nonfarm payrolls, Earnings season
        Adjustment: -50% size within 5 days of major event
        """
        event_risk = 1.0  # No risk by default

        month = timestamp.month
        day = timestamp.day

        # Fed meeting months
        if month in self.fed_meeting_months:
            event_risk *= 0.7  # Reduce by 30% during Fed months

        # Earnings season
        if month in self.earnings_season_months:
            event_risk *= 0.75  # Reduce by 25% during earnings season

        # First Friday of month = Nonfarm Payrolls
        if day <= 7 and self._is_friday(timestamp):
            event_risk *= 0.5  # Reduce by 50% on/near NFP

        # Second week = CPI
        if 8 <= day <= 14:
            event_risk *= 0.75  # Reduce by 25% near CPI

        return event_risk

    def _is_friday(self, timestamp: datetime) -> bool:
        """Check if timestamp is Friday (4 = Friday in Python)."""
        return timestamp.weekday() == 4

    def get_multi_timeframe_regime(self, candles: List, periods: List[int] = [50, 200, 500]) -> Dict:
        """
        Detect regime at multiple timeframes.

        Useful for avoiding trades against larger timeframe trends.
        Example: Don't go short if 200-period is in strong uptrend.
        """
        if len(candles) < max(periods):
            return {"error": "Insufficient data"}

        closes = np.array([c.close for c in candles])
        regimes = {}

        for period in periods:
            if len(closes) >= period:
                recent_sma = np.mean(closes[-20:])
                long_sma = np.mean(closes[-period:])
                trend_strength = (recent_sma - long_sma) / long_sma

                if trend_strength > 0.03:
                    regime = "STRONG_UP"
                elif trend_strength > 0.01:
                    regime = "UP"
                elif trend_strength < -0.03:
                    regime = "STRONG_DOWN"
                elif trend_strength < -0.01:
                    regime = "DOWN"
                else:
                    regime = "NEUTRAL"

                regimes[f"{period}h"] = {
                    "regime": regime,
                    "trend_strength": trend_strength,
                }

        return regimes

    def should_reduce_position(self, macro_regime: Dict, multi_regimes: Dict) -> bool:
        """
        Determine if should reduce position size based on macro conditions.

        Reduce if:
        1. RISK_OFF regime + STRONG_DOWN on 200h+
        2. Approaching major event (earnings, Fed)
        3. High VIX + High credit spreads
        """
        should_reduce = False

        # Check regime alignment
        if macro_regime["overall_regime"] == "RISK_OFF":
            # Check if larger timeframes are down
            if multi_regimes.get("200h", {}).get("regime") in ["DOWN", "STRONG_DOWN"]:
                should_reduce = True

        # Check VIX level
        if macro_regime["vix_level"] > 30:  # Panic level
            should_reduce = True

        # Check credit spreads
        if macro_regime["credit_spread"] > 250:  # Stress level
            should_reduce = True

        return should_reduce

    def get_profit_taking_levels(self, entry_price: float, prediction_confidence: float, macro_regime: Dict) -> Dict:
        """
        Dynamic profit taking levels based on macro environment.

        RISK_ON: Let winners run (higher targets)
        RISK_OFF: Take profits early
        """
        base_levels = {
            0.50: entry_price * 1.05,    # 5% profit
            0.75: entry_price * 1.15,    # 15% profit
            1.00: entry_price * 1.30,    # 30% profit
        }

        if macro_regime["overall_regime"] == "RISK_ON":
            # Extend targets in risk-on environment
            multiplier = 1.3
        elif macro_regime["overall_regime"] == "RISK_OFF":
            # Tighten targets in risk-off environment
            multiplier = 0.7
        else:
            multiplier = 1.0

        return {
            level: (price - entry_price) * multiplier + entry_price
            for level, price in base_levels.items()
        }

    def get_upcoming_events(self, timestamp: datetime, days_ahead: int = 7) -> List[Dict]:
        """
        Get list of upcoming macro events that could impact trading.

        Returns list of events with:
        - type: 'fed_meeting', 'earnings', 'cpi', 'nonfarm_payrolls', 'gdp'
        - severity: 'LOW', 'MEDIUM', 'HIGH'
        - timestamp: when the event occurs
        - description: event description
        """
        events = []
        current_date = timestamp.date() if hasattr(timestamp, 'date') else timestamp
        check_until = current_date + timedelta(days=days_ahead)

        month = timestamp.month
        day = timestamp.day

        # ========== FED MEETINGS (High severity) ==========
        if month in self.fed_meeting_months:
            # Approximate: assume 8 meetings per year, roughly every 6 weeks
            # Real dates would be: Jan, Mar, May, Jun, Jul, Sep, Nov, Dec
            fed_meeting_days = {
                1: 31,  # January FOMC
                3: 20,  # March FOMC
                5: 1,   # May FOMC
                6: 19,  # June FOMC
                7: 31,  # July FOMC
                9: 18,  # September FOMC
                11: 7,  # November FOMC
                12: 18, # December FOMC
            }
            fed_date = fed_meeting_days.get(month)
            if fed_date and current_date <= datetime(timestamp.year, month, min(fed_date, 28)).date() <= check_until:
                events.append({
                    "type": "fed_meeting",
                    "severity": "HIGH",
                    "timestamp": datetime(timestamp.year, month, min(fed_date, 28)),
                    "description": f"Fed FOMC Meeting - {month}/{min(fed_date, 28)}",
                    "hours_away": (datetime(timestamp.year, month, min(fed_date, 28)) - timestamp).total_seconds() / 3600,
                })

        # ========== NONFARM PAYROLLS (High severity) ==========
        # First Friday of month
        first_day = datetime(timestamp.year, month, 1)
        first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
        if current_date <= first_friday.date() <= check_until:
            events.append({
                "type": "nonfarm_payrolls",
                "severity": "HIGH",
                "timestamp": first_friday,
                "description": f"Nonfarm Payrolls - {first_friday.strftime('%m/%d')}",
                "hours_away": (first_friday - timestamp).total_seconds() / 3600,
            })

        # ========== CPI (High severity) ==========
        # Mid-month, typically second week
        cpi_date = datetime(timestamp.year, month, 12)
        if current_date <= cpi_date.date() <= check_until:
            events.append({
                "type": "cpi",
                "severity": "HIGH",
                "timestamp": cpi_date,
                "description": f"CPI Release - {cpi_date.strftime('%m/%d')}",
                "hours_away": (cpi_date - timestamp).total_seconds() / 3600,
            })

        # ========== GDP (Medium severity) ==========
        # Usually end of month
        gdp_date = datetime(timestamp.year, month, 28)
        if current_date <= gdp_date.date() <= check_until:
            events.append({
                "type": "gdp",
                "severity": "MEDIUM",
                "timestamp": gdp_date,
                "description": f"GDP Release - {gdp_date.strftime('%m/%d')}",
                "hours_away": (gdp_date - timestamp).total_seconds() / 3600,
            })

        # ========== EARNINGS SEASON (Medium severity) ==========
        if month in self.earnings_season_months:
            earnings_dates = [
                datetime(timestamp.year, month, 15),
                datetime(timestamp.year, month, 20),
                datetime(timestamp.year, month, 25),
            ]
            for earnings_date in earnings_dates:
                if current_date <= earnings_date.date() <= check_until:
                    events.append({
                        "type": "earnings",
                        "severity": "MEDIUM",
                        "timestamp": earnings_date,
                        "description": f"Earnings Season - {earnings_date.strftime('%m/%d')}",
                        "hours_away": (earnings_date - timestamp).total_seconds() / 3600,
                    })

        # Sort by how soon they occur
        events.sort(key=lambda e: e.get("hours_away", float('inf')))

        return events


# Global macro strategy instance
_macro_strategy = MacroStrategy()

def get_macro_strategy() -> MacroStrategy:
    """Get the global macro strategy instance."""
    return _macro_strategy
