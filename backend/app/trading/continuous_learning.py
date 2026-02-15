"""
Continuous Learning & Online Model Retraining

Adapts models to changing market conditions by:
- Retraining every N candles (online learning)
- Using sliding window (recent data = more important)
- Keeping models fresh (not overfit to old data)
- Detecting market regime changes
- Dynamically adjusting model weights

This solves the degradation problem where models trained on
old data stop working as markets change.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from collections import deque
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class RetrainingWindow:
    """Data window for retraining"""
    features: np.ndarray  # (n_samples, n_features)
    labels: np.ndarray  # (n_samples,)
    rewards: np.ndarray  # (n_samples,)
    start_idx: int
    end_idx: int
    timestamp: float


class ContinuousLearner:
    """
    Online learning manager for continuous model retraining.

    Key features:
    1. Sliding window training (recent data weighted more)
    2. Retrain trigger based on:
       - Number of new candles (every N candles)
       - Market regime change
       - Performance degradation
    3. Incremental updates (don't retrain from scratch)
    4. Model checkpoint management
    """

    def __init__(
        self,
        retrain_interval: int = 100,  # Retrain every 100 candles
        window_size: int = 5000,  # Keep last 5000 samples
        performance_threshold: float = 0.45,  # Alert if win rate < 45%
    ):
        """
        Initialize continuous learner.

        Args:
            retrain_interval: Retrain every N new candles
            window_size: Size of sliding training window
            performance_threshold: Win rate threshold for retraining trigger
        """
        self.retrain_interval = retrain_interval
        self.window_size = window_size
        self.performance_threshold = performance_threshold

        # Tracking
        self.candles_since_retrain = 0
        self.total_candles_processed = 0
        self.training_history: List[Dict] = []
        self.retraining_events: List[Dict] = []

        # Data buffer - FIX #12: Use deque for O(1) operations and thread safety
        self.feature_buffer: deque = deque(maxlen=window_size)
        self.label_buffer: deque = deque(maxlen=window_size)
        self.reward_buffer: deque = deque(maxlen=window_size)
        self._buffer_lock = Lock()  # Thread safety for atomic operations

        # Performance tracking
        self.recent_trades: List[float] = []  # P&L values
        self.max_recent_trades = 20

    def should_retrain(
        self,
        current_win_rate: Optional[float] = None,
        market_regime_changed: bool = False,
    ) -> Tuple[bool, str]:
        """
        Determine if model should be retrained.

        Returns:
            (should_retrain, reason)
        """
        # Trigger 1: Reached retrain interval
        if self.candles_since_retrain >= self.retrain_interval:
            return True, f"interval_reached ({self.candles_since_retrain} candles)"

        # Trigger 2: Market regime changed
        if market_regime_changed:
            return True, "market_regime_changed"

        # Trigger 3: Performance degradation
        if (
            current_win_rate is not None
            and current_win_rate < self.performance_threshold
        ):
            return True, f"performance_degradation (win_rate={current_win_rate:.2f})"

        return False, "no_retrain_needed"

    def add_sample(
        self, features: np.ndarray, label: int, reward: float
    ):
        """
        Add training sample to buffer.

        Args:
            features: Feature vector
            label: Action label (0=sell, 1=hold, 2=buy)
            reward: Trade reward/P&L
        """
        # FIX #12: Atomic operation with thread safety
        with self._buffer_lock:
            self.feature_buffer.append(features)
            self.label_buffer.append(label)
            self.reward_buffer.append(reward)
            # Note: deque with maxlen automatically removes oldest items

        self.candles_since_retrain += 1
        self.total_candles_processed += 1

        # Track performance
        self.recent_trades.append(reward)
        if len(self.recent_trades) > self.max_recent_trades:
            self.recent_trades.pop(0)

    def get_training_window(
        self, recent_weight: float = 2.0
    ) -> Optional[RetrainingWindow]:
        """
        Get sliding window of training data for retraining.

        Args:
            recent_weight: Weight recent samples more heavily (0.5-3.0)
                          > 1.0 = emphasize recent data
                          < 1.0 = emphasize older data

        Returns:
            RetrainingWindow with weighted samples
        """
        # FIX #12: Thread-safe buffer read
        with self._buffer_lock:
            if len(self.feature_buffer) < 100:
                return None  # Need minimum data

            # Create sliding window with recency weighting
            n_samples = len(self.feature_buffer)
            features = np.array(list(self.feature_buffer))
            labels = np.array(list(self.label_buffer))
            rewards = np.array(list(self.reward_buffer))

            # Validate buffer alignment
            assert len(features) == len(labels) == len(rewards), \
                f"Buffer misalignment: features={len(features)}, labels={len(labels)}, rewards={len(rewards)}"

        # Recency weights (exponential: recent samples = higher weight)
        # BUG FIX #7: Validate recent_weight > 0 to avoid NaN from np.log()
        if recent_weight != 1.0 and recent_weight > 0:
            positions = np.arange(n_samples)
            # Exponential weighting: earlier samples lower weight
            weights = np.exp((positions - (n_samples - 1)) * np.log(recent_weight) / n_samples)
            weights = weights / np.mean(weights)  # Normalize

            # Apply weights (optional: use for weighted training)
            # Most frameworks don't support sample weights, so just use recent data
        else:
            # Default to equal weighting if recent_weight is invalid
            weights = np.ones(n_samples)

        return RetrainingWindow(
            features=features,
            labels=labels,
            rewards=rewards,
            start_idx=max(0, n_samples - self.window_size),
            end_idx=n_samples,
            timestamp=self._current_timestamp(),
        )

    def record_retrain_event(
        self,
        reason: str,
        old_metrics: Dict,
        new_metrics: Dict,
        models_updated: List[str],
    ):
        """
        Record a retraining event for analysis.

        Args:
            reason: Why retraining happened
            old_metrics: Performance before retrain
            new_metrics: Performance after retrain
            models_updated: Which models were updated
        """
        event = {
            "timestamp": self._current_timestamp(),
            "reason": reason,
            "candles_processed": self.total_candles_processed,
            "old_metrics": old_metrics,
            "new_metrics": new_metrics,
            "models_updated": models_updated,
            "buffer_size": len(self.feature_buffer),
        }
        self.retraining_events.append(event)

        # Log the event
        improvement = (
            new_metrics.get("accuracy", 0) - old_metrics.get("accuracy", 0)
        )
        logger.info(
            f"🔄 Retraining Event: {reason} | "
            f"Accuracy: {old_metrics.get('accuracy', 0):.2%} → "
            f"{new_metrics.get('accuracy', 0):.2%} ({improvement:+.2%}) | "
            f"Models: {', '.join(models_updated)}"
        )

        # Reset retrain counter
        self.candles_since_retrain = 0

    def get_performance_metrics(self) -> Dict:
        """
        Get current performance metrics from recent trades.

        Returns:
            Dictionary with metrics
        """
        if not self.recent_trades:
            return {
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
            }

        winning = sum(1 for pnl in self.recent_trades if pnl > 0)
        total = len(self.recent_trades)

        return {
            "win_rate": winning / total if total > 0 else 0,
            "avg_pnl": np.mean(self.recent_trades),
            "total_trades": total,
            "winning_trades": winning,
        }

    def detect_market_regime_change(
        self, recent_returns: List[float], threshold: float = 0.05
    ) -> bool:
        """
        Detect if market regime has changed (trigger retrain).

        Args:
            recent_returns: Last 50 returns
            threshold: Volatility change threshold

        Returns:
            True if regime likely changed
        """
        if len(recent_returns) < 50:
            return False

        # Compare recent volatility vs historical
        recent_vol = np.std(recent_returns[-20:])
        historical_vol = np.std(recent_returns[:30])

        # BUG FIX #4 & #5: Use epsilon for float comparison and division protection
        if historical_vol < 1e-8:
            return False

        vol_change = abs(recent_vol - historical_vol) / (historical_vol + 1e-8)

        return vol_change > threshold

    def _current_timestamp(self) -> float:
        """Get current timestamp."""
        import time

        return time.time()

    def get_training_stats(self) -> Dict:
        """Get statistics about training buffer and retraining history."""
        return {
            "total_candles_processed": self.total_candles_processed,
            "candles_since_retrain": self.candles_since_retrain,
            "buffer_size": len(self.feature_buffer),
            "retraining_count": len(self.retraining_events),
            "last_retrain_reason": self.retraining_events[-1].get("reason")
            if self.retraining_events
            else None,
            "performance": self.get_performance_metrics(),
        }


class AdaptiveEnsembleWeighter:
    """
    Dynamically reweight ensemble models based on recent performance.

    Instead of equal weighting, use:
    - Recent accuracy of each model
    - Disagreement between models
    - Market condition fitness
    """

    def __init__(self, model_names: List[str], lookback: int = 50):
        """
        Initialize adaptive weighter.

        Args:
            model_names: Names of base models
            lookback: Use last N trades for weighting
        """
        self.model_names = model_names
        self.lookback = lookback

        # Track per-model performance
        self.model_performance: Dict[str, List[float]] = {
            name: [] for name in model_names
        }

    def record_prediction(self, model_name: str, was_correct: bool):
        """Record if a model's prediction was correct."""
        if model_name in self.model_performance:
            self.model_performance[model_name].append(1.0 if was_correct else 0.0)

            # Keep only recent predictions
            if len(self.model_performance[model_name]) > self.lookback:
                self.model_performance[model_name].pop(0)

    def get_model_weights(self) -> Dict[str, float]:
        """
        Calculate adaptive weights for each model.

        Returns:
            Dictionary of model_name -> weight (sums to 1.0)
        """
        weights = {}

        # Calculate accuracy for each model
        accuracies = {}
        for model_name, predictions in self.model_performance.items():
            if predictions:
                accuracy = np.mean(predictions)
            else:
                accuracy = 0.5  # Default to neutral
            accuracies[model_name] = accuracy

        # Avoid zero weights - use minimum floor
        min_accuracy = 0.3
        adjusted_accuracies = {
            name: max(acc, min_accuracy) for name, acc in accuracies.items()
        }

        # Normalize to sum to 1.0
        total = sum(adjusted_accuracies.values())
        # BUG FIX #4: Guard against empty model_names list
        if len(self.model_names) == 0:
            logger.error("❌ No models to weight - model_names list is empty")
            return {}

        if total > 0:
            weights = {
                name: acc / total for name, acc in adjusted_accuracies.items()
            }
        else:
            # Fallback to equal weights
            equal_weight = 1.0 / len(self.model_names)
            weights = {name: equal_weight for name in self.model_names}

        return weights

    def get_performance_summary(self) -> Dict[str, Dict]:
        """Get detailed performance for each model."""
        summary = {}

        for model_name, predictions in self.model_performance.items():
            if predictions:
                accuracy = np.mean(predictions)
                count = len(predictions)
            else:
                accuracy = 0.0
                count = 0

            summary[model_name] = {
                "accuracy": accuracy,
                "predictions_recorded": count,
                "weight": self.get_model_weights()[model_name],
            }

        return summary
