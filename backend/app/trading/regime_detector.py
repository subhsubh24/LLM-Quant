"""
Market Regime Detection Module

Extracted from WalkForwardBacktester: detects market regime (bull/bear/sideways)
using SMA crossover with hysteresis, and provides regime-aware stop adjustments.
"""

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)


def detect_market_regime(
    candles,
    window: int = 50,
    prev_regime: str = 'sideways',
    switch_threshold: float = 1.0,
    base_threshold: float = 0.02,
    vol_threshold: float = 0.01,
) -> str:
    """
    Detect current market regime (bull, bear, or sideways) with hysteresis to prevent whipsaw.

    Args:
        candles: Recent OHLCV candles to analyze (must have .close attribute)
        window: Look-back window
        prev_regime: Previous regime (for hysteresis/stickiness)
        switch_threshold: Multiplier for trend needed to switch regime (>1.0 = hysteresis)
                         1.0 = no hysteresis (original behavior)
                         1.3 = require 30% larger trend change to switch
        base_threshold: Minimum trend strength (SMA divergence) to detect a regime (default: 2%)
                       Lower = more sensitive to regime changes
                       Higher = less sensitive (misses some but more stable)
        vol_threshold: Minimum volatility to confirm a regime change (default: 1%)
                      Prevents false regime detection in flat/quiet markets

    Returns:
        'bull', 'bear', or 'sideways'
    """
    if len(candles) < window:
        return 'sideways'

    recent = candles[-window:]
    closes = np.array([c.close for c in recent])

    # Calculate trend
    sma_short = np.mean(closes[-20:])
    sma_long = np.mean(closes)
    # BUG FIX #24: Add epsilon protection for division by zero
    trend = (sma_short - sma_long) / (sma_long + 1e-8)

    # Calculate volatility
    # BUG FIX #17: Add epsilon protection for division by zero
    returns = np.diff(closes) / (closes[:-1] + 1e-8)
    volatility = np.std(returns)

    # If already in a regime, require stronger signal to leave it (hysteresis)
    if prev_regime == 'bull':
        if trend < -base_threshold * switch_threshold and volatility > vol_threshold:
            return 'bear'
        elif trend > base_threshold and volatility > vol_threshold:
            return 'bull'  # Stay in bull if still positive
        else:
            return 'sideways'
    elif prev_regime == 'bear':
        if trend > base_threshold * switch_threshold and volatility > vol_threshold:
            return 'bull'
        elif trend < -base_threshold and volatility > vol_threshold:
            return 'bear'  # Stay in bear if still negative
        else:
            return 'sideways'
    else:  # prev_regime == 'sideways'
        if trend > base_threshold * switch_threshold and volatility > vol_threshold:
            return 'bull'
        elif trend < -base_threshold * switch_threshold and volatility > vol_threshold:
            return 'bear'
        else:
            return 'sideways'


def adjust_stop_for_regime(base_stop: float, regime: str, side: str) -> float:
    """
    Apply regime-aware stop adjustments.

    With-trend trades get more room (trend supports the position).
    Counter-trend trades get tighter stops (cut fast if wrong).

    Args:
        base_stop: Base stop loss percentage
        regime: Current market regime ('bull', 'bear', 'sideways')
        side: Position side ('long' or 'short')

    Returns:
        Adjusted stop loss percentage
    """
    if regime == 'bull':
        if side == "long":
            return base_stop * 1.15  # With trend: +15% room
        else:
            return base_stop * 0.85  # Against trend: -15%
    elif regime == 'bear':
        if side == "short":
            return base_stop * 1.15  # With trend: +15% room
        else:
            return base_stop * 0.85  # Against trend: -15%
    # Neutral: no adjustment
    return base_stop
