"""
Aristotle Rules-Based Trading Strategy - Discretionary Technical Analysis

A composite rules-based strategy that emulates the decision-making process of an
experienced discretionary trader. Named after Aristotle's systematic approach to
classifying and reasoning about the natural world, this strategy combines multiple
independent technical rules into a weighted composite signal.

Sub-signals:
1. RSI Pullback in Trend      (weight: 0.20) - Pullbacks within established trends
2. Fibonacci Support           (weight: 0.15) - Key retracement levels as support/resistance
3. Moving Average Alignment    (weight: 0.20) - Multi-timeframe trend confirmation
4. MACD Histogram Divergence   (weight: 0.15) - Momentum shift detection
5. Volume Confirmation         (weight: 0.10) - Participation validation
6. Bollinger Band Squeeze      (weight: 0.10) - Volatility compression breakouts
7. Candlestick Patterns        (weight: 0.10) - Price action pattern recognition

References:
- Wilder (1978) "New Concepts in Technical Trading Systems" - RSI
- Bollinger (2001) "Bollinger on Bollinger Bands" - Band squeeze
- Nison (1991) "Japanese Candlestick Charting Techniques" - Candlestick patterns
- Murphy (1999) "Technical Analysis of the Financial Markets" - Fibonacci, MA alignment
- Appel (2005) "Technical Analysis: Power Tools for Active Investors" - MACD
"""

from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
import logging

from .framework import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default sub-signal weights (must sum to 1.0)
DEFAULT_WEIGHTS: Dict[str, float] = {
    "rsi_pullback": 0.20,
    "fibonacci": 0.15,
    "ma_alignment": 0.20,
    "macd": 0.15,
    "volume": 0.10,
    "bollinger": 0.10,
    "candlestick": 0.10,
}

# Fibonacci retracement ratios
FIBONACCI_RATIOS: List[float] = [0.236, 0.382, 0.500, 0.618, 0.786]


# ---------------------------------------------------------------------------
# Data classes for sub-signal results
# ---------------------------------------------------------------------------

@dataclass
class SubSignal:
    """Result from a single sub-signal rule evaluation."""
    name: str
    score: float  # -1.0 to +1.0
    weight: float
    confidence: float  # 0.0 to 1.0, how reliable this particular sub-signal is
    reason: str = ""

    @property
    def weighted_score(self) -> float:
        return self.score * self.weight


# ---------------------------------------------------------------------------
# FibonacciLevelCalculator
# ---------------------------------------------------------------------------

class FibonacciLevelCalculator:
    """
    Computes Fibonacci retracement and extension levels from price data.

    Identifies the most recent significant swing high and swing low within
    a lookback window, then derives standard Fibonacci retracement levels
    (23.6%, 38.2%, 50%, 61.8%, 78.6%) between those extremes.

    Usage:
        calc = FibonacciLevelCalculator(lookback=120, swing_threshold=5)
        levels = calc.compute_levels(prices)
        proximity = calc.proximity_to_level(current_price, levels)
    """

    def __init__(
        self,
        lookback: int = 120,
        swing_threshold: int = 5,
        proximity_pct: float = 0.015,
    ):
        """
        Initialize Fibonacci calculator.

        Args:
            lookback: Number of bars to search for swing high/low.
            swing_threshold: Minimum bars on each side to confirm a swing point.
            proximity_pct: How close price must be to a level to count as
                           "at support/resistance", expressed as a fraction (e.g. 0.015 = 1.5%).
        """
        self.lookback = lookback
        self.swing_threshold = swing_threshold
        self.proximity_pct = proximity_pct

    def find_swing_high(self, highs: np.ndarray, threshold: int) -> Optional[int]:
        """
        Find the most recent swing high index.

        A swing high is a bar whose high is greater than or equal to the highs
        of the surrounding `threshold` bars on each side.

        Args:
            highs: Array of high prices.
            threshold: Number of bars on each side required.

        Returns:
            Index of the swing high, or None if not found.
        """
        if len(highs) < 2 * threshold + 1:
            return None

        for i in range(len(highs) - 1 - threshold, threshold - 1, -1):
            left = highs[max(0, i - threshold):i]
            right = highs[i + 1:i + 1 + threshold]
            if len(left) == 0 or len(right) == 0:
                continue
            if highs[i] >= np.max(left) and highs[i] >= np.max(right):
                return i
        return None

    def find_swing_low(self, lows: np.ndarray, threshold: int) -> Optional[int]:
        """
        Find the most recent swing low index.

        A swing low is a bar whose low is less than or equal to the lows
        of the surrounding `threshold` bars on each side.

        Args:
            lows: Array of low prices.
            threshold: Number of bars on each side required.

        Returns:
            Index of the swing low, or None if not found.
        """
        if len(lows) < 2 * threshold + 1:
            return None

        for i in range(len(lows) - 1 - threshold, threshold - 1, -1):
            left = lows[max(0, i - threshold):i]
            right = lows[i + 1:i + 1 + threshold]
            if len(left) == 0 or len(right) == 0:
                continue
            if lows[i] <= np.min(left) and lows[i] <= np.min(right):
                return i
        return None

    def compute_levels(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> Optional[Dict[str, float]]:
        """
        Compute Fibonacci retracement levels from recent swing points.

        Args:
            highs: Array of high prices (full lookback window).
            lows: Array of low prices (full lookback window).

        Returns:
            Dictionary with keys like 'swing_high', 'swing_low', '0.382', '0.500', etc.
            Returns None if swing points cannot be identified.
        """
        swing_high_idx = self.find_swing_high(highs, self.swing_threshold)
        swing_low_idx = self.find_swing_low(lows, self.swing_threshold)

        if swing_high_idx is None or swing_low_idx is None:
            return None

        swing_high = float(highs[swing_high_idx])
        swing_low = float(lows[swing_low_idx])

        if swing_high <= swing_low:
            return None

        swing_range = swing_high - swing_low

        levels: Dict[str, float] = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "swing_high_idx": float(swing_high_idx),
            "swing_low_idx": float(swing_low_idx),
        }

        # Determine direction: if swing high is more recent, we are in a downswing
        # and retracements are measured from the high downward.
        # If swing low is more recent, we are in an upswing and retracements
        # are measured from the low upward.
        upswing = swing_low_idx < swing_high_idx  # low came first -> up move

        for ratio in FIBONACCI_RATIOS:
            if upswing:
                # Retracement of an up-move: potential support below current price
                level = swing_high - ratio * swing_range
            else:
                # Retracement of a down-move: potential resistance above current price
                level = swing_low + ratio * swing_range
            levels[f"{ratio:.3f}"] = level

        levels["direction"] = 1.0 if upswing else -1.0

        return levels

    def proximity_to_level(
        self,
        current_price: float,
        levels: Dict[str, float],
    ) -> Tuple[Optional[str], float]:
        """
        Determine if current price is near a Fibonacci level.

        Args:
            current_price: The current price.
            levels: Fibonacci levels from compute_levels().

        Returns:
            Tuple of (level_name, distance_pct) for the closest Fibonacci level.
            level_name is None if no level is within proximity_pct.
        """
        closest_name: Optional[str] = None
        closest_dist: float = float("inf")

        for ratio in FIBONACCI_RATIOS:
            key = f"{ratio:.3f}"
            if key not in levels:
                continue
            level_price = levels[key]
            if level_price <= 0:
                continue
            dist_pct = abs(current_price - level_price) / level_price
            if dist_pct < closest_dist:
                closest_dist = dist_pct
                closest_name = key

        if closest_dist <= self.proximity_pct:
            return closest_name, closest_dist
        return None, closest_dist


# ---------------------------------------------------------------------------
# AristotleRulesStrategy
# ---------------------------------------------------------------------------

class AristotleRulesStrategy(BaseStrategy):
    """
    Aristotle Rules-Based Composite Strategy.

    Combines seven independent technical sub-signals into a single weighted
    composite score that mimics the thought process of a discretionary trader.
    Each sub-signal evaluates a different dimension of market structure (trend,
    momentum, volatility, volume, price-action) and produces a score from -1
    (strong sell) to +1 (strong buy).

    The composite score is the weighted average of all sub-signal scores.
    Confidence is derived from the agreement among sub-signals: when many
    sub-signals point the same direction, confidence is high.
    """

    def __init__(
        self,
        # RSI parameters
        rsi_period: int = 14,
        rsi_pullback_buy: float = 40.0,
        rsi_overbought_sell: float = 60.0,
        # Moving average parameters
        ma_fast: int = 20,
        ma_mid: int = 50,
        ma_slow: int = 200,
        # MACD parameters
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        # Bollinger parameters
        bb_period: int = 20,
        bb_std: float = 2.0,
        bb_squeeze_threshold: float = 0.04,
        # Volume parameters
        volume_lookback: int = 20,
        volume_multiplier: float = 1.5,
        # Fibonacci parameters
        fib_lookback: int = 120,
        fib_swing_threshold: int = 5,
        fib_proximity_pct: float = 0.015,
        # Sub-signal weights
        weights: Optional[Dict[str, float]] = None,
        # Minimum data requirements
        min_bars: int = 200,
    ):
        """
        Initialize the Aristotle rules-based strategy.

        Args:
            rsi_period: Period for RSI calculation.
            rsi_pullback_buy: RSI threshold for pullback buy (below this in uptrend).
            rsi_overbought_sell: RSI threshold for overbought sell (above this in downtrend).
            ma_fast: Fast moving average period.
            ma_mid: Medium moving average period.
            ma_slow: Slow moving average period.
            macd_fast: MACD fast EMA period.
            macd_slow: MACD slow EMA period.
            macd_signal: MACD signal line period.
            bb_period: Bollinger Band period.
            bb_std: Bollinger Band standard deviation multiplier.
            bb_squeeze_threshold: Bandwidth below this is considered a squeeze.
            volume_lookback: Volume moving average lookback.
            volume_multiplier: Volume must exceed this multiple of average.
            fib_lookback: Bars to look back for Fibonacci swing points.
            fib_swing_threshold: Bars on each side to confirm swing.
            fib_proximity_pct: How close price must be to Fibonacci level.
            weights: Override default sub-signal weights.
            min_bars: Minimum number of bars required for signal generation.
        """
        super().__init__(
            name="Aristotle Rules-Based (Composite Technical)",
            description=(
                "Discretionary-style composite strategy combining RSI pullbacks, "
                "Fibonacci levels, MA alignment, MACD momentum, volume confirmation, "
                "Bollinger squeeze breakouts, and candlestick patterns"
            ),
        )
        self.strategy_id = "aristotle_rules_v1"

        # RSI
        self.rsi_period = rsi_period
        self.rsi_pullback_buy = rsi_pullback_buy
        self.rsi_overbought_sell = rsi_overbought_sell

        # Moving averages
        self.ma_fast = ma_fast
        self.ma_mid = ma_mid
        self.ma_slow = ma_slow

        # MACD
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal

        # Bollinger Bands
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.bb_squeeze_threshold = bb_squeeze_threshold

        # Volume
        self.volume_lookback = volume_lookback
        self.volume_multiplier = volume_multiplier

        # Fibonacci
        self.fib_calculator = FibonacciLevelCalculator(
            lookback=fib_lookback,
            swing_threshold=fib_swing_threshold,
            proximity_pct=fib_proximity_pct,
        )

        # Weights
        self.weights = weights if weights is not None else DEFAULT_WEIGHTS.copy()
        self._validate_weights()

        # Minimum bars
        self.min_bars = min_bars

    def _validate_weights(self) -> None:
        """Ensure weights sum to 1.0; normalize if necessary."""
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            logger.warning(
                f"Sub-signal weights sum to {total:.4f}, normalizing to 1.0"
            )
            self.weights = {k: v / total for k, v in self.weights.items()}

    # ------------------------------------------------------------------
    # Main signal generation
    # ------------------------------------------------------------------

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """
        Generate a composite trading signal from multiple technical rules.

        Args:
            data: DataFrame with columns: open, high, low, close, volume.
                  Index should be datetime-like.
            context: Optional context dict (risk limits, regime info, etc.).

        Returns:
            StrategySignal with composite score and confidence.
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
            confidence=0.0,
        )

        # --- Validate input data ---
        required_cols = {"open", "high", "low", "close", "volume"}
        if not required_cols.issubset(set(data.columns)):
            missing = required_cols - set(data.columns)
            logger.warning(
                f"Aristotle strategy: missing columns {missing}, "
                f"returning neutral signal"
            )
            signal.reason = f"Missing columns: {missing}"
            return signal

        if len(data) < self.min_bars:
            logger.debug(
                f"Aristotle strategy: insufficient data ({len(data)} bars, "
                f"need {self.min_bars}), returning neutral signal"
            )
            signal.reason = f"Insufficient data: {len(data)}/{self.min_bars} bars"
            return signal

        try:
            close = data["close"].values.astype(float)
            high = data["high"].values.astype(float)
            low = data["low"].values.astype(float)
            opn = data["open"].values.astype(float)
            volume = data["volume"].values.astype(float)

            # --- Compute all sub-signals ---
            sub_signals: List[SubSignal] = []

            sub_signals.append(self._rsi_pullback_signal(close))
            sub_signals.append(self._fibonacci_signal(high, low, close[-1]))
            sub_signals.append(self._ma_alignment_signal(close))
            sub_signals.append(self._macd_signal(close))
            sub_signals.append(self._volume_signal(volume))
            sub_signals.append(self._bollinger_signal(close))
            sub_signals.append(self._candlestick_signal(opn, high, low, close))

            # --- Composite score ---
            composite_score = sum(ss.weighted_score for ss in sub_signals)
            composite_score = float(np.clip(composite_score, -1.0, 1.0))

            # --- Confidence: based on agreement among sub-signals ---
            # If all sub-signals agree on direction, confidence is high.
            non_zero = [ss for ss in sub_signals if abs(ss.score) > 0.05]
            if len(non_zero) > 0:
                direction_agreement = abs(
                    sum(1 if ss.score > 0 else -1 for ss in non_zero)
                ) / len(non_zero)
                avg_sub_confidence = np.mean([ss.confidence for ss in non_zero])
                confidence = 0.3 + 0.4 * direction_agreement + 0.3 * avg_sub_confidence
            else:
                confidence = 0.2  # No strong views

            confidence = float(np.clip(confidence, 0.0, 1.0))

            # --- Populate signal ---
            if composite_score > 0.05:
                signal.symbols["RULES_BASED"] = composite_score
                signal.target_weights["RULES_BASED"] = 0.8
            elif composite_score < -0.05:
                signal.symbols["RULES_BASED"] = composite_score
                signal.target_weights["RULES_BASED"] = 0.8
            else:
                signal.symbols["RULES_BASED"] = 0.0
                signal.target_weights["RULES_BASED"] = 0.2  # Minimal exposure
                confidence = min(confidence, 0.35)

            signal.confidence = confidence
            signal.conviction = abs(composite_score)

            # Build reason string
            dominant = sorted(sub_signals, key=lambda s: abs(s.score), reverse=True)
            top_reasons = [
                f"{ss.name}={ss.score:+.2f}" for ss in dominant[:3] if abs(ss.score) > 0.05
            ]
            signal.reason = (
                f"Composite={composite_score:+.3f} | "
                f"Top drivers: {', '.join(top_reasons) if top_reasons else 'none'}"
            )

            # Store sub-signal details in extra_data for transparency
            signal.extra_data = {
                "composite_score": round(composite_score, 4),
                "sub_signals": {
                    ss.name: {
                        "score": round(ss.score, 4),
                        "weight": round(ss.weight, 4),
                        "weighted": round(ss.weighted_score, 4),
                        "confidence": round(ss.confidence, 4),
                        "reason": ss.reason,
                    }
                    for ss in sub_signals
                },
            }

            self.last_signal_time = datetime.now()
            logger.debug(
                f"Aristotle signal: score={composite_score:+.3f}, "
                f"confidence={confidence:.3f}, "
                f"direction={'LONG' if composite_score > 0 else 'SHORT' if composite_score < 0 else 'FLAT'}"
            )

        except Exception as e:
            logger.error(f"Aristotle strategy signal generation failed: {e}", exc_info=True)
            signal.confidence = 0.0
            signal.reason = f"Error: {str(e)}"
            self.record_error()

        return signal

    # ------------------------------------------------------------------
    # Sub-signal 1: RSI Pullback in Trend
    # ------------------------------------------------------------------

    def _compute_rsi(self, close: np.ndarray, period: int) -> float:
        """
        Compute the Relative Strength Index (Wilder's smoothing).

        Args:
            close: Array of closing prices.
            period: RSI lookback period.

        Returns:
            RSI value between 0 and 100.
        """
        if len(close) < period + 1:
            return 50.0  # Neutral default

        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # Wilder's exponential smoothing
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss < 1e-10:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return float(rsi)

    def _rsi_pullback_signal(self, close: np.ndarray) -> SubSignal:
        """
        RSI Pullback in Trend sub-signal.

        Logic:
        - RSI < 40 with price above 50-day MA -> buy (pullback in uptrend)
        - RSI > 60 with price below 50-day MA -> sell (overbought in downtrend)
        - Otherwise neutral.
        """
        weight = self.weights.get("rsi_pullback", 0.20)

        try:
            rsi = self._compute_rsi(close, self.rsi_period)
            ma_50 = float(np.mean(close[-self.ma_mid:]))
            current_price = float(close[-1])

            score = 0.0
            reason = f"RSI={rsi:.1f}, price vs MA50={'above' if current_price > ma_50 else 'below'}"

            if rsi < self.rsi_pullback_buy and current_price > ma_50:
                # Pullback in uptrend - strong buy
                # Score scales: RSI=40 -> mild, RSI=20 -> strong
                intensity = (self.rsi_pullback_buy - rsi) / self.rsi_pullback_buy
                score = 0.5 + 0.5 * intensity
                reason += " -> BUY pullback in uptrend"

            elif rsi > self.rsi_overbought_sell and current_price < ma_50:
                # Overbought in downtrend - strong sell
                intensity = (rsi - self.rsi_overbought_sell) / (100.0 - self.rsi_overbought_sell)
                score = -(0.5 + 0.5 * intensity)
                reason += " -> SELL overbought in downtrend"

            elif rsi < 30 and current_price < ma_50:
                # Deeply oversold in downtrend - mild contrarian buy
                score = 0.2
                reason += " -> mild contrarian buy (deeply oversold)"

            confidence = 0.6 if abs(score) > 0.3 else 0.3
            return SubSignal(
                name="rsi_pullback", score=score, weight=weight,
                confidence=confidence, reason=reason,
            )

        except Exception as e:
            logger.warning(f"RSI pullback sub-signal failed: {e}")
            return SubSignal(
                name="rsi_pullback", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 2: Fibonacci Support / Resistance
    # ------------------------------------------------------------------

    def _fibonacci_signal(
        self,
        high: np.ndarray,
        low: np.ndarray,
        current_price: float,
    ) -> SubSignal:
        """
        Fibonacci retracement sub-signal.

        Logic:
        - If price is near a key Fibonacci retracement level (38.2%, 50%, 61.8%)
          during an upswing retracement, treat as support (buy).
        - If price is near a Fibonacci level during a downswing retracement,
          treat as resistance (sell).
        """
        weight = self.weights.get("fibonacci", 0.15)

        try:
            lookback = min(self.fib_calculator.lookback, len(high))
            levels = self.fib_calculator.compute_levels(
                high[-lookback:], low[-lookback:]
            )

            if levels is None:
                return SubSignal(
                    name="fibonacci", score=0.0, weight=weight,
                    confidence=0.1, reason="No swing points found",
                )

            level_name, distance = self.fib_calculator.proximity_to_level(
                current_price, levels
            )

            if level_name is None:
                return SubSignal(
                    name="fibonacci", score=0.0, weight=weight,
                    confidence=0.2,
                    reason=f"Price not near any Fib level (closest dist={distance:.4f})",
                )

            direction = levels.get("direction", 0.0)
            # Stronger signal for key levels (0.382, 0.500, 0.618)
            level_value = float(level_name)
            key_levels = {0.382, 0.500, 0.618}
            is_key_level = any(abs(level_value - kl) < 0.01 for kl in key_levels)
            strength = 0.8 if is_key_level else 0.5

            # Proximity boost: closer to level -> stronger signal
            proximity_boost = 1.0 - (distance / self.fib_calculator.proximity_pct)
            strength *= max(proximity_boost, 0.3)

            if direction > 0:
                # Upswing retracement -> these levels are support -> buy
                score = strength
                reason = f"At Fib {level_name} support (upswing retrace, dist={distance:.4f})"
            else:
                # Downswing retracement -> these levels are resistance -> sell
                score = -strength
                reason = f"At Fib {level_name} resistance (downswing retrace, dist={distance:.4f})"

            confidence = 0.55 if is_key_level else 0.35
            return SubSignal(
                name="fibonacci", score=score, weight=weight,
                confidence=confidence, reason=reason,
            )

        except Exception as e:
            logger.warning(f"Fibonacci sub-signal failed: {e}")
            return SubSignal(
                name="fibonacci", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 3: Moving Average Alignment
    # ------------------------------------------------------------------

    def _ma_alignment_signal(self, close: np.ndarray) -> SubSignal:
        """
        Moving average alignment sub-signal.

        Logic:
        - All MAs aligned bullish (20 > 50 > 200): strong buy
        - All MAs aligned bearish (20 < 50 < 200): strong sell
        - Partial alignment: scaled signal
        - Golden cross / death cross detection for recent crossovers
        """
        weight = self.weights.get("ma_alignment", 0.20)

        try:
            ma_fast = float(np.mean(close[-self.ma_fast:]))
            ma_mid = float(np.mean(close[-self.ma_mid:]))
            ma_slow = float(np.mean(close[-self.ma_slow:]))
            current_price = float(close[-1])

            # Check alignment
            bullish_alignment = (ma_fast > ma_mid > ma_slow)
            bearish_alignment = (ma_fast < ma_mid < ma_slow)

            # Compute slope of the 50-day MA (trend direction confirmation)
            if len(close) > self.ma_mid + 5:
                ma_mid_prev = float(np.mean(close[-(self.ma_mid + 5):-5]))
                ma_slope = (ma_mid - ma_mid_prev) / (ma_mid_prev + 1e-10)
            else:
                ma_slope = 0.0

            # Price position relative to MAs
            above_all = current_price > ma_fast > ma_mid > ma_slow
            below_all = current_price < ma_fast < ma_mid < ma_slow

            score = 0.0
            reasons = []

            if bullish_alignment:
                score += 0.5
                reasons.append("MAs aligned bullish (20>50>200)")
                if above_all:
                    score += 0.3
                    reasons.append("price above all MAs")
                if ma_slope > 0.005:
                    score += 0.2
                    reasons.append(f"MA50 trending up (slope={ma_slope:.4f})")

            elif bearish_alignment:
                score -= 0.5
                reasons.append("MAs aligned bearish (20<50<200)")
                if below_all:
                    score -= 0.3
                    reasons.append("price below all MAs")
                if ma_slope < -0.005:
                    score -= 0.2
                    reasons.append(f"MA50 trending down (slope={ma_slope:.4f})")

            else:
                # Partial alignment - check for golden/death cross
                if ma_fast > ma_mid:
                    score += 0.2
                    reasons.append("fast MA above mid MA")
                elif ma_fast < ma_mid:
                    score -= 0.2
                    reasons.append("fast MA below mid MA")

                if current_price > ma_slow:
                    score += 0.1
                    reasons.append("price above 200-MA")
                elif current_price < ma_slow:
                    score -= 0.1
                    reasons.append("price below 200-MA")

            score = float(np.clip(score, -1.0, 1.0))
            confidence = 0.7 if (bullish_alignment or bearish_alignment) else 0.4
            reason = "; ".join(reasons) if reasons else "No clear MA alignment"

            return SubSignal(
                name="ma_alignment", score=score, weight=weight,
                confidence=confidence, reason=reason,
            )

        except Exception as e:
            logger.warning(f"MA alignment sub-signal failed: {e}")
            return SubSignal(
                name="ma_alignment", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 4: MACD Histogram Divergence
    # ------------------------------------------------------------------

    def _compute_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """
        Compute exponential moving average.

        Args:
            data: Input price array.
            period: EMA period.

        Returns:
            Array of EMA values (same length as input, with initial values
            using SMA seed).
        """
        if len(data) < period:
            return np.full_like(data, np.nan, dtype=float)

        ema = np.zeros_like(data, dtype=float)
        multiplier = 2.0 / (period + 1.0)

        # Seed with SMA
        ema[period - 1] = np.mean(data[:period])

        for i in range(period, len(data)):
            ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1]

        # Fill initial values with NaN
        ema[:period - 1] = np.nan
        return ema

    def _macd_signal(self, close: np.ndarray) -> SubSignal:
        """
        MACD histogram divergence sub-signal.

        Logic:
        - MACD histogram turning positive after being negative = bullish momentum shift
        - MACD histogram turning negative after being positive = bearish momentum shift
        - Magnitude of histogram indicates strength
        """
        weight = self.weights.get("macd", 0.15)

        try:
            ema_fast = self._compute_ema(close, self.macd_fast)
            ema_slow = self._compute_ema(close, self.macd_slow)

            macd_line = ema_fast - ema_slow

            # Remove NaN values for signal line calculation
            valid_start = self.macd_slow - 1
            if len(macd_line) < valid_start + self.macd_signal_period:
                return SubSignal(
                    name="macd", score=0.0, weight=weight,
                    confidence=0.1, reason="Insufficient data for MACD",
                )

            signal_line = self._compute_ema(
                macd_line[valid_start:], self.macd_signal_period
            )

            # Histogram
            hist_len = min(len(macd_line) - valid_start, len(signal_line))
            histogram = macd_line[-hist_len:] - signal_line[-hist_len:]

            if len(histogram) < 3:
                return SubSignal(
                    name="macd", score=0.0, weight=weight,
                    confidence=0.1, reason="Insufficient histogram data",
                )

            current_hist = float(histogram[-1])
            prev_hist = float(histogram[-2])
            prev_prev_hist = float(histogram[-3])

            score = 0.0
            reasons = []

            # Detect histogram zero-line crossover
            if current_hist > 0 and prev_hist <= 0:
                score = 0.7
                reasons.append("MACD histogram crossed above zero (bullish)")
            elif current_hist < 0 and prev_hist >= 0:
                score = -0.7
                reasons.append("MACD histogram crossed below zero (bearish)")
            # Detect increasing/decreasing histogram (momentum building)
            elif current_hist > 0 and current_hist > prev_hist:
                score = 0.3
                reasons.append("MACD histogram increasing (bullish momentum building)")
            elif current_hist < 0 and current_hist < prev_hist:
                score = -0.3
                reasons.append("MACD histogram decreasing (bearish momentum building)")
            # Detect histogram divergence from trend (weakening)
            elif current_hist > 0 and current_hist < prev_hist < prev_prev_hist:
                score = -0.2
                reasons.append("MACD histogram declining from positive (momentum fading)")
            elif current_hist < 0 and current_hist > prev_hist > prev_prev_hist:
                score = 0.2
                reasons.append("MACD histogram rising from negative (selling pressure easing)")

            confidence = 0.6 if abs(score) > 0.5 else 0.4
            reason = "; ".join(reasons) if reasons else f"MACD hist={current_hist:.4f}, neutral"

            return SubSignal(
                name="macd", score=score, weight=weight,
                confidence=confidence, reason=reason,
            )

        except Exception as e:
            logger.warning(f"MACD sub-signal failed: {e}")
            return SubSignal(
                name="macd", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 5: Volume Confirmation
    # ------------------------------------------------------------------

    def _volume_signal(self, volume: np.ndarray) -> SubSignal:
        """
        Volume confirmation sub-signal.

        Logic:
        - Volume above 1.5x 20-day average = confirmation of current move
        - Very high volume (2x+) = strong confirmation
        - Below-average volume = lack of conviction
        - This signal amplifies the direction of other signals rather than
          providing direction on its own. We approximate direction from
          recent volume trend.
        """
        weight = self.weights.get("volume", 0.10)

        try:
            if len(volume) < self.volume_lookback + 1:
                return SubSignal(
                    name="volume", score=0.0, weight=weight,
                    confidence=0.1, reason="Insufficient volume data",
                )

            avg_volume = float(np.mean(volume[-self.volume_lookback - 1:-1]))
            current_volume = float(volume[-1])

            if avg_volume < 1e-10:
                return SubSignal(
                    name="volume", score=0.0, weight=weight,
                    confidence=0.1, reason="Zero average volume",
                )

            volume_ratio = current_volume / avg_volume

            # Volume trend over last 5 bars
            recent_vol = volume[-5:]
            vol_trend = float(np.mean(recent_vol[-3:])) / (float(np.mean(recent_vol[:2])) + 1e-10)

            score = 0.0
            reasons = []

            if volume_ratio >= 2.0:
                # Very high volume: strong confirmation
                score = 0.8
                reasons.append(f"Very high volume ({volume_ratio:.1f}x avg)")
                confidence = 0.7
            elif volume_ratio >= self.volume_multiplier:
                # Above-average volume: confirmation
                score = 0.5
                reasons.append(f"Above-avg volume ({volume_ratio:.1f}x avg)")
                confidence = 0.5
            elif volume_ratio < 0.5:
                # Very low volume: lack of conviction, slightly negative
                score = -0.3
                reasons.append(f"Very low volume ({volume_ratio:.1f}x avg)")
                confidence = 0.3
            else:
                # Normal volume
                score = 0.0
                reasons.append(f"Normal volume ({volume_ratio:.1f}x avg)")
                confidence = 0.2

            # Volume trend adjustment
            if vol_trend > 1.3:
                score = min(score + 0.2, 1.0)
                reasons.append("volume trending up")
            elif vol_trend < 0.7:
                score = max(score - 0.2, -1.0)
                reasons.append("volume trending down")

            return SubSignal(
                name="volume", score=score, weight=weight,
                confidence=confidence, reason="; ".join(reasons),
            )

        except Exception as e:
            logger.warning(f"Volume sub-signal failed: {e}")
            return SubSignal(
                name="volume", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 6: Bollinger Band Squeeze + Breakout
    # ------------------------------------------------------------------

    def _bollinger_signal(self, close: np.ndarray) -> SubSignal:
        """
        Bollinger Band squeeze and breakout sub-signal.

        Logic:
        - Squeeze: bandwidth < threshold (volatility compression)
        - Breakout above upper band after squeeze = bullish
        - Breakout below lower band after squeeze = bearish
        - Price walking the upper band = bullish trend
        - Price walking the lower band = bearish trend
        """
        weight = self.weights.get("bollinger", 0.10)

        try:
            if len(close) < self.bb_period + 5:
                return SubSignal(
                    name="bollinger", score=0.0, weight=weight,
                    confidence=0.1, reason="Insufficient data for Bollinger Bands",
                )

            # Current Bollinger Bands
            sma = float(np.mean(close[-self.bb_period:]))
            std = float(np.std(close[-self.bb_period:], ddof=1))
            upper = sma + self.bb_std * std
            lower = sma - self.bb_std * std
            bandwidth = (upper - lower) / (sma + 1e-10)

            # Previous Bollinger Bands (5 bars ago) for squeeze detection
            sma_prev = float(np.mean(close[-(self.bb_period + 5):-5]))
            std_prev = float(np.std(close[-(self.bb_period + 5):-5], ddof=1))
            upper_prev = sma_prev + self.bb_std * std_prev
            lower_prev = sma_prev - self.bb_std * std_prev
            bandwidth_prev = (upper_prev - lower_prev) / (sma_prev + 1e-10)

            current_price = float(close[-1])
            prev_price = float(close[-2])

            score = 0.0
            reasons = []

            # Check for squeeze (low bandwidth)
            is_squeeze = bandwidth_prev < self.bb_squeeze_threshold
            expanding = bandwidth > bandwidth_prev * 1.2

            if is_squeeze and expanding:
                # Squeeze breakout
                if current_price > upper:
                    score = 0.9
                    reasons.append(
                        f"Bollinger squeeze breakout UP "
                        f"(bw: {bandwidth_prev:.4f}->{bandwidth:.4f})"
                    )
                elif current_price < lower:
                    score = -0.9
                    reasons.append(
                        f"Bollinger squeeze breakout DOWN "
                        f"(bw: {bandwidth_prev:.4f}->{bandwidth:.4f})"
                    )
                else:
                    score = 0.1 if current_price > sma else -0.1
                    reasons.append(
                        f"Bollinger squeeze expanding, price near middle "
                        f"(bw: {bandwidth_prev:.4f}->{bandwidth:.4f})"
                    )
            elif current_price > upper and prev_price > sma:
                # Walking the upper band
                score = 0.4
                reasons.append("Price walking upper Bollinger Band (bullish)")
            elif current_price < lower and prev_price < sma:
                # Walking the lower band
                score = -0.4
                reasons.append("Price walking lower Bollinger Band (bearish)")
            elif current_price > upper:
                # Breakout without squeeze - weaker signal
                score = 0.2
                reasons.append("Price above upper band (mild bullish)")
            elif current_price < lower:
                score = -0.2
                reasons.append("Price below lower band (mild bearish)")
            else:
                # Inside bands
                pct_b = (current_price - lower) / (upper - lower + 1e-10)
                if pct_b > 0.8:
                    score = 0.15
                    reasons.append(f"%B={pct_b:.2f}, near upper band")
                elif pct_b < 0.2:
                    score = -0.15
                    reasons.append(f"%B={pct_b:.2f}, near lower band")
                else:
                    reasons.append(f"%B={pct_b:.2f}, mid-band range")

            if is_squeeze and not expanding:
                reasons.append(f"SQUEEZE active (bw={bandwidth:.4f})")

            confidence = 0.65 if (is_squeeze and expanding) else 0.35
            return SubSignal(
                name="bollinger", score=score, weight=weight,
                confidence=confidence, reason="; ".join(reasons),
            )

        except Exception as e:
            logger.warning(f"Bollinger sub-signal failed: {e}")
            return SubSignal(
                name="bollinger", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )

    # ------------------------------------------------------------------
    # Sub-signal 7: Candlestick Patterns
    # ------------------------------------------------------------------

    def _candlestick_signal(
        self,
        opn: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
    ) -> SubSignal:
        """
        Candlestick pattern recognition sub-signal.

        Detects:
        - Hammer / Inverted Hammer (bullish reversal)
        - Bullish / Bearish Engulfing
        - Doji (indecision, potential reversal)

        We look at the last 2-3 bars to identify these patterns.
        """
        weight = self.weights.get("candlestick", 0.10)

        try:
            if len(close) < 3:
                return SubSignal(
                    name="candlestick", score=0.0, weight=weight,
                    confidence=0.1, reason="Insufficient bars for candlestick analysis",
                )

            patterns_found: List[Tuple[str, float]] = []

            # Current and previous bar values
            o1, h1, l1, c1 = float(opn[-1]), float(high[-1]), float(low[-1]), float(close[-1])
            o2, h2, l2, c2 = float(opn[-2]), float(high[-2]), float(low[-2]), float(close[-2])

            body1 = abs(c1 - o1)
            body2 = abs(c2 - o2)
            range1 = h1 - l1
            range2 = h2 - l2

            # Avoid division by zero
            if range1 < 1e-10:
                range1 = 1e-10
            if range2 < 1e-10:
                range2 = 1e-10

            upper_shadow1 = h1 - max(o1, c1)
            lower_shadow1 = min(o1, c1) - l1

            # --- Doji ---
            # Body is very small relative to range
            body_ratio = body1 / range1
            if body_ratio < 0.1 and range1 > 0:
                # Doji: indecision, mild reversal signal
                # Direction depends on prior trend
                if c2 > o2:
                    # Prior was bullish -> doji may signal reversal down
                    patterns_found.append(("doji_after_bull", -0.3))
                elif c2 < o2:
                    # Prior was bearish -> doji may signal reversal up
                    patterns_found.append(("doji_after_bear", 0.3))
                else:
                    patterns_found.append(("doji_neutral", 0.0))

            # --- Hammer (bullish) ---
            # Small body at top, long lower shadow (>= 2x body), small upper shadow
            if (
                lower_shadow1 >= 2.0 * body1
                and upper_shadow1 <= body1 * 0.5
                and body1 > 0
                and c1 >= o1  # Bullish body preferred, but not required
            ):
                patterns_found.append(("hammer", 0.6))

            # --- Inverted Hammer (bullish after downtrend) ---
            # Small body at bottom, long upper shadow (>= 2x body), small lower shadow
            if (
                upper_shadow1 >= 2.0 * body1
                and lower_shadow1 <= body1 * 0.5
                and body1 > 0
                and c2 < o2  # Prior bar was bearish (downtrend context)
            ):
                patterns_found.append(("inverted_hammer", 0.5))

            # --- Bullish Engulfing ---
            # Current bar is bullish (close > open) and its body completely engulfs
            # the prior bearish bar's body
            if (
                c1 > o1  # Current is bullish
                and c2 < o2  # Prior was bearish
                and o1 <= c2  # Current open at or below prior close
                and c1 >= o2  # Current close at or above prior open
                and body1 > body2  # Current body larger
            ):
                patterns_found.append(("bullish_engulfing", 0.7))

            # --- Bearish Engulfing ---
            # Current bar is bearish and its body engulfs the prior bullish bar
            if (
                c1 < o1  # Current is bearish
                and c2 > o2  # Prior was bullish
                and o1 >= c2  # Current open at or above prior close
                and c1 <= o2  # Current close at or below prior open
                and body1 > body2  # Current body larger
            ):
                patterns_found.append(("bearish_engulfing", -0.7))

            if not patterns_found:
                return SubSignal(
                    name="candlestick", score=0.0, weight=weight,
                    confidence=0.15, reason="No candlestick patterns detected",
                )

            # Combine pattern scores (take the strongest pattern)
            strongest = max(patterns_found, key=lambda p: abs(p[1]))
            all_names = [p[0] for p in patterns_found]
            score = float(np.clip(strongest[1], -1.0, 1.0))

            confidence = 0.5 if abs(score) > 0.5 else 0.3
            reason = f"Patterns: {', '.join(all_names)} (strongest: {strongest[0]}={strongest[1]:+.1f})"

            return SubSignal(
                name="candlestick", score=score, weight=weight,
                confidence=confidence, reason=reason,
            )

        except Exception as e:
            logger.warning(f"Candlestick sub-signal failed: {e}")
            return SubSignal(
                name="candlestick", score=0.0, weight=weight,
                confidence=0.0, reason=f"Error: {e}",
            )
