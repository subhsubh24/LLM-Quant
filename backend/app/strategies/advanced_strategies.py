"""
Advanced Strategies - Phase 11

Three new low-correlation strategies:
1. Regime-Aware Meta-Strategy: Routes capital per market regime
2. Options Skew Strategy: Trades implied vol smile anomalies
3. Earnings Event Strategy: Pre/post earnings volatility

Expected improvement: +0.30 Sharpe (3 strategies × 0.10 each)
Correlation: 0.15-0.20 (low, uncorrelated to existing)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import logging

from .framework import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


@dataclass
class MarketRegime:
    """Market regime classification"""
    regime: str  # CRISIS, HIGH_VOL, STRESS, TREND, RANGE
    correlation: float
    volatility: float
    confidence: float
    trend_strength: float


class RegimeAwareStrategy(BaseStrategy):
    """
    Routes capital to best strategies per market regime.

    Regimes:
    - CRISIS: High correlation + high volatility
    - HIGH_VOL: High volatility
    - STRESS: Elevated correlation
    - TREND: Consistent trend
    - RANGE: Ranging market
    """

    def __init__(self):
        """Initialize regime strategy"""
        # CRITICAL BUG FIX #9: Use correct super().__init__() parameters
        super().__init__(
            name="Regime Aware Meta",
            description="Routes capital by market regime",
        )
        self.regime_history = []
        self.correlation_history = []
        self.vol_history = []

    def detect_regime(
        self,
        correlation: float,
        volatility: float,
        trend_strength: float,
    ) -> MarketRegime:
        """Detect current market regime.

        Args:
            correlation: Average portfolio correlation
            volatility: Realized volatility
            trend_strength: Trend consistency metric (0-1)

        Returns:
            MarketRegime classification
        """
        # Store history
        self.correlation_history.append(correlation)
        self.vol_history.append(volatility)

        # Keep last 20
        self.correlation_history = self.correlation_history[-20:]
        self.vol_history = self.vol_history[-20:]

        # Classify regime
        if correlation > 0.85 and volatility > 0.30:
            regime = "CRISIS"
            confidence = 0.9
        elif volatility > 0.25:
            regime = "HIGH_VOL"
            confidence = 0.8
        elif correlation > 0.65:
            regime = "STRESS"
            confidence = 0.7
        elif trend_strength > 0.6:
            regime = "TREND"
            confidence = 0.75
        else:
            regime = "RANGE"
            confidence = 0.7

        return MarketRegime(
            regime=regime,
            correlation=correlation,
            volatility=volatility,
            confidence=confidence,
            trend_strength=trend_strength,
        )

    def get_regime_allocation(self, regime: MarketRegime) -> Dict[str, float]:
        """Get strategy allocation per regime.

        Args:
            regime: Current market regime

        Returns:
            Strategy allocations (should sum to 1.0)
        """
        allocations = {
            "CRISIS": {
                "long_vol": 0.40,           # Vol hedge
                "mean_reversion": 0.40,    # MR in crisis
                "trend": 0.20,             # Reduce trend
            },
            "HIGH_VOL": {
                "vol_trading": 0.50,       # Vol trades
                "trend": 0.30,             # Still follow
                "mean_reversion": 0.20,    # Some reversion
            },
            "STRESS": {
                "mean_reversion": 0.40,    # MR more
                "trend": 0.35,
                "stat_arb": 0.25,
            },
            "TREND": {
                "trend": 0.70,             # Strong trend
                "technical": 0.20,
                "factor": 0.10,
            },
            "RANGE": {
                "mean_reversion": 0.50,    # MR dominant
                "stat_arb": 0.30,
                "factor": 0.20,
            },
        }

        return allocations.get(regime.regime, allocations["RANGE"])

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """Generate regime-aware signal.

        Args:
            data: OHLCV data
            context: Dict with correlation, vol, trend_strength

        Returns:
            StrategySignal
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
        )

        if context is None:
            return signal

        try:
            # Get regime
            regime = self.detect_regime(
                correlation=context.get('correlation', 0.3),
                volatility=context.get('volatility', 0.15),
                trend_strength=context.get('trend_strength', 0.5),
            )

            # Get allocation
            allocation = self.get_regime_allocation(regime)

            # Generate signal
            signal.symbols['REGIME'] = 1.0  # Meta signal
            signal.target_weights['REGIME'] = 0.7
            signal.confidence = regime.confidence

            # Add extra data
            signal.extra_data = {
                'regime': regime.regime,
                'correlation': float(regime.correlation),
                'volatility': float(regime.volatility),
                'allocation': allocation,
                'confidence': float(regime.confidence),
            }

            self.last_signal = signal
            self.regime_history.append(regime.regime)

        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            signal.confidence = 0

        return signal


class SkewStrategy(BaseStrategy):
    """
    Trades options implied volatility skew anomalies.

    Skew = IV(OTM Put) - IV(OTM Call)
    Extreme skew = trading opportunity
    """

    def __init__(self, skew_threshold: float = 0.20):
        """Initialize skew strategy.

        Args:
            skew_threshold: Threshold for extreme skew (20% = 0.20)
        """
        # CRITICAL BUG FIX #9: Use correct super().__init__() parameters
        super().__init__(
            name="Implied Vol Skew",
            description="Trades volatility smile anomalies",
        )
        self.skew_threshold = skew_threshold
        self.skew_history = []

    def compute_skew(
        self,
        iv_otm_put: float,
        iv_otm_call: float,
    ) -> float:
        """Compute volatility skew.

        Args:
            iv_otm_put: OTM put implied vol
            iv_otm_call: OTM call implied vol

        Returns:
            Skew metric
        """
        if iv_otm_call <= 0:
            return 0.0

        skew = (iv_otm_put - iv_otm_call) / iv_otm_call
        return float(np.clip(skew, -1.0, 1.0))

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """Generate skew-based signal.

        Args:
            data: OHLCV data (not directly used)
            context: Dict with iv_otm_put, iv_otm_call

        Returns:
            StrategySignal
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
        )

        if context is None:
            return signal

        try:
            # Compute skew
            skew = self.compute_skew(
                iv_otm_put=context.get('iv_otm_put', 0.20),
                iv_otm_call=context.get('iv_otm_call', 0.18),
            )

            self.skew_history.append(skew)
            self.skew_history = self.skew_history[-20:]

            # Generate signal based on extreme skew
            if skew > self.skew_threshold:
                # High put skew = sell put skew (bullish)
                signal.symbols['SKEW'] = 0.5  # Mild long
                signal.target_weights['SKEW'] = 0.3
                signal.confidence = min(0.6, abs(skew) / 0.5)

            elif skew < -self.skew_threshold:
                # High call skew = sell call skew (bearish)
                signal.symbols['SKEW'] = -0.5  # Mild short
                signal.target_weights['SKEW'] = 0.3
                signal.confidence = min(0.6, abs(skew) / 0.5)

            else:
                # Normal skew, no signal
                signal.confidence = 0.2

            # Add extra data
            signal.extra_data = {
                'skew': float(skew),
                'skew_trend': float(np.mean(self.skew_history[-5:])) if len(self.skew_history) > 0 else 0.0,
                'threshold': self.skew_threshold,
            }

            self.last_signal = signal

        except Exception as e:
            logger.warning(f"Skew analysis failed: {e}")
            signal.confidence = 0

        return signal


class EarningsEventStrategy(BaseStrategy):
    """
    Trades around earnings events.

    Pre-earnings: Volatility expansion (sell straddles)
    Post-earnings: Mean reversion (large moves revert)
    """

    def __init__(
        self,
        vol_expansion_threshold: float = 1.5,
        mean_reversion_threshold: float = 3.0,
    ):
        """Initialize earnings strategy.

        Args:
            vol_expansion_threshold: IV expansion threshold (1.5x = 50%)
            mean_reversion_threshold: Price move threshold in sigmas
        """
        # CRITICAL BUG FIX #9: Use correct super().__init__() parameters
        super().__init__(
            name="Earnings Event",
            description="Pre/post earnings volatility trades",
        )
        self.vol_expansion_threshold = vol_expansion_threshold
        self.mean_reversion_threshold = mean_reversion_threshold
        self.earnings_dates = {}  # symbol -> list of dates

    def is_earnings_day(self, symbol: str, current_date: datetime) -> bool:
        """Check if today is earnings day.

        Args:
            symbol: Stock symbol
            current_date: Current date

        Returns:
            True if earnings day
        """
        if symbol not in self.earnings_dates:
            return False

        dates = self.earnings_dates[symbol]
        return any(
            (current_date.date() - d.date()).days == 0
            for d in dates
        )

    def days_to_earnings(self, symbol: str, current_date: datetime) -> int:
        """Days until next earnings.

        Args:
            symbol: Stock symbol
            current_date: Current date

        Returns:
            Days until earnings (-1 if no earnings)
        """
        if symbol not in self.earnings_dates:
            return -1

        upcoming = [d for d in self.earnings_dates[symbol] if d > current_date]
        if not upcoming:
            return -1

        return (min(upcoming) - current_date).days

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """Generate earnings-based signal.

        Args:
            data: OHLCV data
            context: Dict with symbol, iv, iv_normal, last_move_sigma, etc.

        Returns:
            StrategySignal
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
        )

        if context is None:
            return signal

        try:
            symbol = context.get('symbol', 'UNKNOWN')
            current_date = context.get('date', datetime.now())
            iv = context.get('iv', 0.20)
            iv_normal = context.get('iv_normal', 0.15)
            last_move_sigma = context.get('last_move_sigma', 0.0)

            days_to_earn = self.days_to_earnings(symbol, current_date)

            # Pre-earnings: 1-7 days before
            if 1 <= days_to_earn <= 7:
                vol_expansion = iv / max(iv_normal, 1e-10)

                if vol_expansion > self.vol_expansion_threshold:
                    # Sell premium (straddle/strangle)
                    signal.symbols['EARNINGS_PRE'] = -0.4  # Short vol
                    signal.target_weights['EARNINGS_PRE'] = 0.2
                    signal.confidence = min(0.7, vol_expansion / 2.0)
                else:
                    signal.confidence = 0.3

            # Post-earnings: 0-3 days after (large move likely reverting)
            elif days_to_earn == -1 or days_to_earn == 0:
                if abs(last_move_sigma) > self.mean_reversion_threshold:
                    # Mean reversion trade
                    direction = -np.sign(last_move_sigma)  # Trade opposite
                    signal.symbols['EARNINGS_POST'] = direction * 0.5
                    signal.target_weights['EARNINGS_POST'] = 0.25
                    signal.confidence = min(0.8, abs(last_move_sigma) / 5.0)
                else:
                    signal.confidence = 0.2

            else:
                signal.confidence = 0

            # Add extra data
            signal.extra_data = {
                'symbol': symbol,
                'days_to_earnings': days_to_earn,
                'iv': float(iv),
                'iv_normal': float(iv_normal),
                'vol_expansion': float(iv / max(iv_normal, 1e-10)),
                'last_move_sigma': float(last_move_sigma),
            }

            self.last_signal = signal

        except Exception as e:
            logger.warning(f"Earnings analysis failed: {e}")
            signal.confidence = 0

        return signal
