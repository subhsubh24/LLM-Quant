"""
Hybrid Signal Engine - Combines ML Ensemble Predictions with Rules-Based Strategy Signals

This engine merges two independent signal sources:
1. ML Ensemble (SimplifiedMLEnsemble) - data-driven probabilistic predictions
2. Rules-Based Strategy (BaseStrategy subclass) - domain-knowledge-driven signals

The combination uses:
- Configurable weighted averaging of both signal sources
- Agreement bonus: when both sources agree on direction, confidence is boosted
- Disagreement penalty: when sources conflict, position size is reduced by 50%
- Dynamic weighting: shifts weight toward whichever source has been more accurate recently
- Optional agreement filter: only trade when both sources agree

References:
- Bates & Granger (1969) - Combination of Forecasts
- Timmermann (2006) - Forecast Combinations
- Rapach et al. (2010) - Out-of-Sample Equity Premium Prediction
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from enum import Enum
from collections import defaultdict
import numpy as np
import pandas as pd
import logging

from .engine import (
    SignalEngine,
    StockSignal,
    PortfolioSignals,
    SignalStrength,
)
from ..models.simplified_ml_ensemble import SimplifiedMLEnsemble
from ..strategies.framework import BaseStrategy, StrategySignal
from ..config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Configuration
# ---------------------------------------------------------------------------

class SignalSource(Enum):
    """Origin of a trading signal."""
    ML_ENSEMBLE = "ml_ensemble"
    RULES_BASED = "rules_based"
    HYBRID = "hybrid"


@dataclass
class HybridSignalConfig:
    """
    Configuration for the hybrid signal engine.

    Weights must satisfy: ml_weight + rules_weight + agreement_bonus == 1.0
    (the agreement_bonus is only applied when both sources agree; otherwise the
    ml_weight and rules_weight are re-normalised to sum to 1.0).
    """
    # Core weighting
    ml_weight: float = 0.45
    rules_weight: float = 0.45
    agreement_bonus: float = 0.10

    # Filtering thresholds
    min_confidence: float = 0.55
    agreement_required: bool = False

    # Dynamic weight adaptation
    dynamic_weighting: bool = True
    lookback_for_weighting: int = 63  # trading days (~3 months)

    def validate(self) -> None:
        """Raise if configuration is inconsistent."""
        total = self.ml_weight + self.rules_weight + self.agreement_bonus
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Weights must sum to 1.0, got ml={self.ml_weight} + "
                f"rules={self.rules_weight} + bonus={self.agreement_bonus} = {total}"
            )
        if not (0.0 <= self.min_confidence <= 1.0):
            raise ValueError(f"min_confidence must be in [0, 1], got {self.min_confidence}")
        if self.lookback_for_weighting < 1:
            raise ValueError(f"lookback_for_weighting must be >= 1, got {self.lookback_for_weighting}")


# ---------------------------------------------------------------------------
# Performance Tracker - tracks recent accuracy of each signal source
# ---------------------------------------------------------------------------

@dataclass
class _PredictionRecord:
    """Single prediction record for performance tracking."""
    source: SignalSource
    ticker: str
    predicted_direction: float  # positive = bullish, negative = bearish
    actual_return: float
    timestamp: datetime = field(default_factory=datetime.now)


class PerformanceTracker:
    """
    Track prediction accuracy for ML and rules-based signal sources.

    Used to compute dynamic weights: whichever source has been more accurate
    over the recent lookback window receives a larger share of the total weight.
    """

    def __init__(self) -> None:
        self._records: List[_PredictionRecord] = []

    # -- public API ----------------------------------------------------------

    def record_prediction(
        self,
        source: SignalSource,
        ticker: str,
        predicted_direction: float,
        actual_return: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Record one prediction / actual pair.

        Args:
            source: Which signal source produced this prediction.
            ticker: Symbol this prediction was for.
            predicted_direction: Positive means bullish, negative means bearish.
            actual_return: Realised return over the prediction horizon.
            timestamp: When the prediction was made (defaults to now).
        """
        self._records.append(
            _PredictionRecord(
                source=source,
                ticker=ticker,
                predicted_direction=predicted_direction,
                actual_return=actual_return,
                timestamp=timestamp or datetime.now(),
            )
        )

    def get_accuracy(
        self,
        source: SignalSource,
        lookback_days: int = 63,
    ) -> float:
        """
        Compute directional accuracy for *source* over the last *lookback_days*.

        Returns a float in [0, 1].  Returns 0.5 (no edge) if there are fewer
        than 5 records in the window.
        """
        cutoff = datetime.now() - timedelta(days=lookback_days)
        relevant = [
            r for r in self._records
            if r.source == source and r.timestamp >= cutoff
        ]

        if len(relevant) < 5:
            return 0.5  # not enough data -- assume coin-flip

        correct = sum(
            1 for r in relevant
            if (r.predicted_direction > 0 and r.actual_return > 0)
            or (r.predicted_direction < 0 and r.actual_return < 0)
            or (r.predicted_direction == 0 and abs(r.actual_return) < 1e-8)
        )
        return correct / len(relevant)

    def get_dynamic_weights(
        self,
        lookback_days: int = 63,
        base_ml_weight: float = 0.50,
        base_rules_weight: float = 0.50,
    ) -> Dict[str, float]:
        """
        Compute dynamic weights that shift toward the more accurate source.

        The approach:
        1. Compute accuracy_ml and accuracy_rules over the lookback window.
        2. Take accuracy-weighted combination, normalised to sum to 1.0.
        3. Blend 50/50 with the base weights for stability (shrinkage toward prior).

        Returns:
            {"ml": <float>, "rules": <float>}  summing to 1.0
        """
        acc_ml = self.get_accuracy(SignalSource.ML_ENSEMBLE, lookback_days)
        acc_rules = self.get_accuracy(SignalSource.RULES_BASED, lookback_days)

        total_acc = acc_ml + acc_rules
        if total_acc < 1e-8:
            # Both are zero (should never happen with the 0.5 floor, but guard)
            return {"ml": base_ml_weight, "rules": base_rules_weight}

        # Accuracy-implied weights
        implied_ml = acc_ml / total_acc
        implied_rules = acc_rules / total_acc

        # Shrinkage blend: 50% base prior, 50% data-driven
        shrinkage = 0.5
        blended_ml = shrinkage * base_ml_weight + (1 - shrinkage) * implied_ml
        blended_rules = shrinkage * base_rules_weight + (1 - shrinkage) * implied_rules

        # Renormalise (should be close to 1.0 already, but be safe)
        total = blended_ml + blended_rules
        return {
            "ml": blended_ml / total,
            "rules": blended_rules / total,
        }

    def get_record_count(self, source: Optional[SignalSource] = None) -> int:
        """Return the number of stored records, optionally filtered by source."""
        if source is None:
            return len(self._records)
        return sum(1 for r in self._records if r.source == source)

    def clear(self) -> None:
        """Remove all stored records."""
        self._records.clear()


# ---------------------------------------------------------------------------
# Hybrid Signal Engine
# ---------------------------------------------------------------------------

class HybridSignalEngine:
    """
    Combines ML ensemble predictions with rules-based strategy signals into
    unified PortfolioSignals.

    Usage::

        ml_ensemble = SimplifiedMLEnsemble()
        rules_strategy = MyRulesStrategy(...)  # BaseStrategy subclass
        engine = HybridSignalEngine(ml_ensemble, rules_strategy)

        portfolio_signals = engine.generate_hybrid_signals(
            prices=price_df,
            volumes=volume_df,
            features=feature_array,
        )
    """

    def __init__(
        self,
        ml_ensemble: SimplifiedMLEnsemble,
        rules_strategy: BaseStrategy,
        config: Optional[HybridSignalConfig] = None,
    ) -> None:
        self.ml_ensemble = ml_ensemble
        self.rules_strategy = rules_strategy
        self.config = config or HybridSignalConfig()
        self.config.validate()

        self.settings = get_settings()
        self.signal_engine = SignalEngine()  # for regime detection & helpers
        self.tracker = PerformanceTracker()

        logger.info(
            "HybridSignalEngine initialised  "
            f"(ml_weight={self.config.ml_weight}, "
            f"rules_weight={self.config.rules_weight}, "
            f"agreement_bonus={self.config.agreement_bonus}, "
            f"dynamic_weighting={self.config.dynamic_weighting})"
        )

    # -- main entry point ----------------------------------------------------

    def generate_hybrid_signals(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        features: Optional[np.ndarray] = None,
        fundamentals: Optional[Dict[str, Dict]] = None,
        **strategy_kwargs: Any,
    ) -> PortfolioSignals:
        """
        Generate hybrid portfolio signals.

        Args:
            prices: DataFrame with DatetimeIndex rows, ticker columns.
            volumes: Optional volume DataFrame (same shape as prices).
            features: Optional feature matrix for the ML ensemble.
                      Shape (n_tickers, n_features) -- one row per ticker in
                      the *same order* as ``prices.columns``.
            fundamentals: Optional dict ticker -> fundamental metrics (passed
                          through to the base SignalEngine for quality/value).
            **strategy_kwargs: Extra keyword arguments forwarded to the
                               rules-based strategy's ``generate_signal``.

        Returns:
            PortfolioSignals with hybrid-combined signals.
        """
        tickers = list(prices.columns)
        n_tickers = len(tickers)

        logger.info(f"Generating hybrid signals for {n_tickers} tickers")

        # 1. ML predictions  ------------------------------------------------
        ml_scores = self._get_ml_scores(tickers, features)

        # 2. Rules-based scores  ---------------------------------------------
        rules_scores = self._get_rules_scores(prices, volumes, **strategy_kwargs)

        # 3. Market regime (re-use SignalEngine logic)  ----------------------
        market_regime, regime_confidence = self.signal_engine._detect_regime(prices)

        # 4. Determine effective weights  ------------------------------------
        ml_w, rules_w = self._effective_weights()

        # 5. Combine per-ticker  ---------------------------------------------
        signals: List[StockSignal] = []
        for idx, ticker in enumerate(tickers):
            try:
                ml_score = ml_scores.get(ticker, 0.0)
                rules_score = rules_scores.get(ticker, 0.0)

                combined_score, confidence, source_label = self._combine_scores(
                    ml_score=ml_score,
                    rules_score=rules_score,
                    ml_weight=ml_w,
                    rules_weight=rules_w,
                )

                # Apply regime-aware adjustment
                combined_score = self._apply_regime_adjustment(
                    combined_score, market_regime, regime_confidence
                )

                # Filter by minimum confidence
                if confidence < self.config.min_confidence:
                    combined_score = 0.0

                # Build the StockSignal
                stock_signal = self._build_stock_signal(
                    ticker=ticker,
                    prices=prices[ticker],
                    combined_score=combined_score,
                    confidence=confidence,
                    ml_score=ml_score,
                    rules_score=rules_score,
                    source=source_label,
                )
                signals.append(stock_signal)

            except Exception as exc:
                logger.warning(f"Failed to generate hybrid signal for {ticker}: {exc}")

        # 6. Sort and partition  ---------------------------------------------
        signals.sort(key=lambda s: s.composite_score, reverse=True)
        buy_signals = [s for s in signals if s.action == "BUY"]
        sell_signals = [s for s in signals if s.action == "SELL"]

        # 7. Optimal weights (delegate to base SignalEngine)  ----------------
        recommended_weights = self.signal_engine._compute_optimal_weights(signals, prices)
        exp_ret, exp_vol, exp_sharpe = self.signal_engine._estimate_portfolio_metrics(
            recommended_weights, prices,
        )

        portfolio = PortfolioSignals(
            timestamp=datetime.now(),
            signals=signals,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            market_regime=market_regime,
            regime_confidence=regime_confidence,
            recommended_weights=recommended_weights,
            expected_portfolio_return=exp_ret,
            expected_portfolio_vol=exp_vol,
            expected_sharpe=exp_sharpe,
        )

        logger.info(
            f"Hybrid signals generated: {len(buy_signals)} buys, "
            f"{len(sell_signals)} sells, regime={market_regime}"
        )
        return portfolio

    # -- internal helpers ----------------------------------------------------

    def _get_ml_scores(
        self,
        tickers: List[str],
        features: Optional[np.ndarray],
    ) -> Dict[str, float]:
        """
        Obtain ML ensemble predictions and normalise from probability [0, 1]
        to a directional score in [-1, +1].

        Mapping: score = 2 * probability - 1
                 prob 0.0 -> score -1 (strong bearish)
                 prob 0.5 -> score  0 (neutral)
                 prob 1.0 -> score +1 (strong bullish)
        """
        if features is None:
            logger.debug("No features supplied; ML scores default to 0.0")
            return {t: 0.0 for t in tickers}

        try:
            probas = self.ml_ensemble.predict_proba(features)  # shape (n_tickers,)
            scores: Dict[str, float] = {}
            for i, ticker in enumerate(tickers):
                prob = float(probas[i]) if i < len(probas) else 0.5
                # Normalise to [-1, +1]
                scores[ticker] = float(np.clip(2.0 * prob - 1.0, -1.0, 1.0))
            return scores

        except Exception as exc:
            logger.error(f"ML ensemble prediction failed: {exc}")
            return {t: 0.0 for t in tickers}

    def _get_rules_scores(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame],
        **kwargs: Any,
    ) -> Dict[str, float]:
        """
        Run the rules-based strategy and normalise its per-ticker scores
        to [-1, +1].

        The BaseStrategy.generate_signal returns a StrategySignal whose
        ``symbols`` dict maps ticker -> score (already in [-1, 1]).
        """
        try:
            strat_signal: StrategySignal = self.rules_strategy.generate_signal(
                prices, volumes, **kwargs,
            )
            # ``symbols`` is Dict[str, float] with scores in [-1, 1]
            scores = dict(strat_signal.symbols)

            # Ensure all tickers are present (default to 0 if strategy did not
            # produce a score for a given ticker)
            for ticker in prices.columns:
                if ticker not in scores:
                    scores[ticker] = 0.0

            # Clip to safety
            return {t: float(np.clip(v, -1.0, 1.0)) for t, v in scores.items()}

        except Exception as exc:
            logger.error(f"Rules-based strategy failed: {exc}")
            return {t: 0.0 for t in prices.columns}

    def _effective_weights(self) -> Tuple[float, float]:
        """
        Return the (ml_weight, rules_weight) to use for this run.

        If dynamic weighting is enabled and the tracker has enough data,
        the weights are adapted toward the better-performing source.
        Otherwise the static config weights are used (re-normalised to
        exclude the agreement bonus, which is handled separately).
        """
        base_ml = self.config.ml_weight
        base_rules = self.config.rules_weight

        if self.config.dynamic_weighting:
            dynamic = self.tracker.get_dynamic_weights(
                lookback_days=self.config.lookback_for_weighting,
                base_ml_weight=base_ml / (base_ml + base_rules),
                base_rules_weight=base_rules / (base_ml + base_rules),
            )
            ml_w = dynamic["ml"]
            rules_w = dynamic["rules"]
        else:
            total = base_ml + base_rules
            ml_w = base_ml / total
            rules_w = base_rules / total

        return ml_w, rules_w

    def _combine_scores(
        self,
        ml_score: float,
        rules_score: float,
        ml_weight: float,
        rules_weight: float,
    ) -> Tuple[float, float, SignalSource]:
        """
        Combine ML and rules-based scores into a single hybrid score.

        Returns:
            (combined_score, confidence, dominant_source)

        Logic:
        - Base score is the weighted average of the two inputs.
        - If both agree on direction, an *agreement bonus* is added
          (signed to match the direction) and confidence is boosted.
        - If they disagree, the combined score is dampened by 50%
          (position-size reduction) and confidence is lowered.
        - If agreement_required is True and they disagree, the combined
          score is forced to 0 (no trade).
        """
        # Weighted base combination
        base_score = ml_weight * ml_score + rules_weight * rules_score

        ml_direction = np.sign(ml_score)
        rules_direction = np.sign(rules_score)

        sources_agree = (
            (ml_direction == rules_direction)
            and ml_direction != 0
        )

        if sources_agree:
            # Both sources point the same way -- boost
            bonus = self.config.agreement_bonus * np.sign(base_score)
            combined_score = base_score + bonus

            # Confidence: high when both strong and agreeing
            raw_confidence = 0.5 * (abs(ml_score) + abs(rules_score))
            confidence = min(raw_confidence + 0.15, 1.0)
            source_label = SignalSource.HYBRID

        elif ml_direction != 0 and rules_direction != 0:
            # Active disagreement -- dampen by 50%
            if self.config.agreement_required:
                combined_score = 0.0
                confidence = 0.0
            else:
                combined_score = base_score * 0.5
                confidence = max(
                    0.5 * (abs(ml_score) + abs(rules_score)) - 0.20,
                    0.0,
                )
            # Label by the dominant contributor
            source_label = (
                SignalSource.ML_ENSEMBLE
                if abs(ml_score) >= abs(rules_score)
                else SignalSource.RULES_BASED
            )
        else:
            # One or both are neutral -- no bonus/penalty
            combined_score = base_score
            confidence = 0.5 * (abs(ml_score) + abs(rules_score))
            if abs(ml_score) > abs(rules_score):
                source_label = SignalSource.ML_ENSEMBLE
            elif abs(rules_score) > abs(ml_score):
                source_label = SignalSource.RULES_BASED
            else:
                source_label = SignalSource.HYBRID

        # Clip final score to [-1, 1]
        combined_score = float(np.clip(combined_score, -1.0, 1.0))
        confidence = float(np.clip(confidence, 0.0, 1.0))

        return combined_score, confidence, source_label

    @staticmethod
    def _apply_regime_adjustment(
        score: float,
        regime: str,
        regime_confidence: float,
    ) -> float:
        """
        Dampen or amplify a signal based on the detected market regime.

        - high_vol: reduce aggressive signals (scale toward 0)
        - bear: penalise long signals, boost short signals
        - bull: mild boost to long signals
        - normal: no adjustment
        """
        if regime == "high_vol":
            # Scale down proportionally to regime confidence
            dampening = 1.0 - 0.3 * regime_confidence
            return score * dampening

        if regime == "bear":
            # Penalise longs, favour shorts
            adjustment = -0.10 * regime_confidence
            return float(np.clip(score + adjustment, -1.0, 1.0))

        if regime == "bull":
            # Mild boost to longs
            adjustment = 0.05 * regime_confidence
            return float(np.clip(score + adjustment, -1.0, 1.0))

        # "normal" or unknown
        return score

    def _build_stock_signal(
        self,
        ticker: str,
        prices: pd.Series,
        combined_score: float,
        confidence: float,
        ml_score: float,
        rules_score: float,
        source: SignalSource,
    ) -> StockSignal:
        """
        Construct a fully-populated StockSignal from the hybrid combination.
        """
        # Determine signal strength / action
        if combined_score > 0.5:
            strength = SignalStrength.STRONG_BUY
            action = "BUY"
        elif combined_score > 0.2:
            strength = SignalStrength.BUY
            action = "BUY"
        elif combined_score < -0.5:
            strength = SignalStrength.STRONG_SELL
            action = "SELL"
        elif combined_score < -0.2:
            strength = SignalStrength.SELL
            action = "SELL"
        else:
            strength = SignalStrength.HOLD
            action = "HOLD"

        # Risk estimates from recent price history
        returns = prices.pct_change().dropna()
        if len(returns) >= 63:
            vol = float(returns.iloc[-63:].std() * np.sqrt(252))
        else:
            vol = 0.25  # fallback

        expected_ret = combined_score * 0.15  # heuristic scaling
        sharpe_est = expected_ret / (vol + 1e-10)

        # Position sizing via vol-target
        target_vol = self.settings.target_volatility
        max_position = min(target_vol / (vol + 1e-10) * 0.1, self.settings.max_position_weight)

        if action == "BUY":
            target_weight = max_position * (0.5 + 0.5 * abs(combined_score))
        else:
            target_weight = 0.0

        # Stop-loss / take-profit
        stop_loss = max(vol * 2, 0.08)
        take_profit = max(expected_ret * 2, 0.15)

        return StockSignal(
            symbol=ticker,
            timestamp=datetime.now(),
            composite_score=combined_score,
            signal_strength=strength,
            confidence=confidence,
            # Factor breakdown: store hybrid sources in the factor slots
            momentum_score=ml_score,     # ML prediction as "momentum" proxy
            value_score=rules_score,     # rules score as "value" proxy
            quality_score=0.0,
            volatility_score=0.0,
            technical_score=0.0,
            factor_details={
                "ml_score": round(ml_score, 4),
                "rules_score": round(rules_score, 4),
                "signal_source": source.value,
            },
            expected_return=expected_ret,
            expected_volatility=vol,
            sharpe_estimate=sharpe_est,
            max_position_size=max_position,
            action=action,
            target_weight=target_weight,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
        )

    # -- convenience methods -------------------------------------------------

    def record_outcome(
        self,
        ticker: str,
        ml_prediction: float,
        rules_prediction: float,
        actual_return: float,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Record the actual outcome for a previous prediction so that the
        PerformanceTracker can update dynamic weights.

        Should be called once the prediction horizon has elapsed and the
        realised return is known.
        """
        self.tracker.record_prediction(
            source=SignalSource.ML_ENSEMBLE,
            ticker=ticker,
            predicted_direction=ml_prediction,
            actual_return=actual_return,
            timestamp=timestamp,
        )
        self.tracker.record_prediction(
            source=SignalSource.RULES_BASED,
            ticker=ticker,
            predicted_direction=rules_prediction,
            actual_return=actual_return,
            timestamp=timestamp,
        )

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Return a diagnostic summary of the engine state, useful for
        dashboards and monitoring.
        """
        ml_acc = self.tracker.get_accuracy(
            SignalSource.ML_ENSEMBLE, self.config.lookback_for_weighting,
        )
        rules_acc = self.tracker.get_accuracy(
            SignalSource.RULES_BASED, self.config.lookback_for_weighting,
        )
        dynamic_w = self.tracker.get_dynamic_weights(
            lookback_days=self.config.lookback_for_weighting,
            base_ml_weight=self.config.ml_weight / (self.config.ml_weight + self.config.rules_weight),
            base_rules_weight=self.config.rules_weight / (self.config.ml_weight + self.config.rules_weight),
        )

        return {
            "config": {
                "ml_weight": self.config.ml_weight,
                "rules_weight": self.config.rules_weight,
                "agreement_bonus": self.config.agreement_bonus,
                "min_confidence": self.config.min_confidence,
                "agreement_required": self.config.agreement_required,
                "dynamic_weighting": self.config.dynamic_weighting,
                "lookback_for_weighting": self.config.lookback_for_weighting,
            },
            "performance": {
                "ml_accuracy": round(ml_acc, 4),
                "rules_accuracy": round(rules_acc, 4),
                "ml_records": self.tracker.get_record_count(SignalSource.ML_ENSEMBLE),
                "rules_records": self.tracker.get_record_count(SignalSource.RULES_BASED),
            },
            "effective_weights": {
                "ml": round(dynamic_w["ml"], 4),
                "rules": round(dynamic_w["rules"], 4),
            },
            "ml_ensemble_trained": self.ml_ensemble.is_trained,
            "rules_strategy": {
                "name": self.rules_strategy.name,
                "id": self.rules_strategy.strategy_id,
                "healthy": self.rules_strategy.is_healthy(),
            },
        }


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------

_hybrid_engine: Optional[HybridSignalEngine] = None


def get_hybrid_signal_engine(
    ml_ensemble: Optional[SimplifiedMLEnsemble] = None,
    rules_strategy: Optional[BaseStrategy] = None,
    config: Optional[HybridSignalConfig] = None,
) -> Optional[HybridSignalEngine]:
    """
    Get or create the singleton HybridSignalEngine.

    Both ``ml_ensemble`` and ``rules_strategy`` must be provided on first
    call.  Subsequent calls return the cached instance (arguments are
    ignored after initial creation).

    Returns None if the required dependencies are not supplied on the first
    call.
    """
    global _hybrid_engine

    if _hybrid_engine is not None:
        return _hybrid_engine

    if ml_ensemble is None or rules_strategy is None:
        logger.warning(
            "Cannot create HybridSignalEngine without both ml_ensemble "
            "and rules_strategy."
        )
        return None

    _hybrid_engine = HybridSignalEngine(
        ml_ensemble=ml_ensemble,
        rules_strategy=rules_strategy,
        config=config,
    )
    return _hybrid_engine
