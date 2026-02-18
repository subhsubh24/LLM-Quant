"""
Integration layer for enhanced signal engine with existing engine.

This module patches the existing SignalEngine with enhanced features:
- Decorrelation
- Adaptive weighting
- Sector rotation

Usage:
    from app.signals.engine import SignalEngine
    from app.signals.enhanced_integration import enhance_signal_engine

    engine = SignalEngine()
    enhanced = enhance_signal_engine(engine)
    signals = enhanced.generate_signals(...)
"""

from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import logging

from .engine import SignalEngine, StockSignal, PortfolioSignals
from .enhanced_engine import (
    EnhancedSignalEngine,
    FactorDecorrelator,
    AdaptiveWeightingSystem,
    SectorRotationManager,
)

logger = logging.getLogger(__name__)


class EnhancedSignalEngineWrapper:
    """
    Wraps existing SignalEngine with enhanced features.

    This allows gradual adoption of enhancements without breaking existing code.
    """

    def __init__(
        self,
        base_engine: SignalEngine,
        use_pca: bool = True,
        use_adaptive_weights: bool = True,
        use_sector_rotation: bool = True,
        adaptive_weight_lookback: int = 60,
        decorrelation_lookback: int = 252,
    ):
        """Initialize enhanced wrapper."""
        self.base_engine = base_engine
        self.enhanced = EnhancedSignalEngine(
            use_pca=use_pca,
            use_adaptive_weights=use_adaptive_weights,
            use_sector_rotation=use_sector_rotation,
            decorrelation_lookback=decorrelation_lookback,
        )

        # State for adaptive weighting
        self.adaptive_weight_lookback = adaptive_weight_lookback
        self.factor_returns_history: Dict[str, pd.Series] = {}
        self.portfolio_returns_history: pd.Series = pd.Series()
        self.adaptive_weights_cache: Optional[Dict[str, float]] = None
        self.last_weight_update: Optional[datetime] = None

    def generate_signals(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        fundamentals: Optional[Dict] = None,
        force_recompute_weights: bool = False,
    ) -> PortfolioSignals:
        """
        Generate signals with enhanced features.

        Args:
            prices: Price data (dates x tickers)
            volumes: Volume data (optional)
            fundamentals: Fundamental data (optional)
            force_recompute_weights: Force recalculation of adaptive weights

        Returns:
            Enhanced PortfolioSignals with better factor composition
        """
        logger.info("Generating enhanced signals")

        # Get base factor scores
        momentum_scores = self.base_engine._compute_momentum_scores(prices)
        value_scores = self.base_engine._compute_value_scores(prices, fundamentals)
        quality_scores = self.base_engine._compute_quality_scores(fundamentals)
        volatility_scores = self.base_engine._compute_volatility_scores(prices)
        technical_scores = self.base_engine._compute_technical_scores(prices, volumes)

        # Detect market regime
        market_regime, regime_conf = self.base_engine._detect_regime(prices)

        # Step 1: Decorrelate factors if enabled
        if self.enhanced.use_pca:
            decorrelated_df, loadings = self.enhanced.compute_decorrelated_factors(
                momentum_scores,
                value_scores,
                quality_scores,
                volatility_scores,
                technical_scores,
            )
            logger.info(f"Factors decorrelated: {loadings}")
        else:
            decorrelated_df = None

        # Step 2: Compute adaptive weights if enabled
        adaptive_weights = None
        if self.enhanced.use_adaptive_weights:
            adaptive_weights = self._compute_adaptive_weights(
                momentum_scores,
                value_scores,
                quality_scores,
                volatility_scores,
                technical_scores,
                market_regime,
                force_recompute=force_recompute_weights,
            )
            logger.info(f"Adaptive weights computed: {adaptive_weights.to_dict()}")

        # Step 3: Generate signals with enhanced composition
        signals = []
        for ticker in prices.columns:
            try:
                # Get factor scores for this ticker
                momentum = momentum_scores.get(ticker, 0)
                value = value_scores.get(ticker, 0)
                quality = quality_scores.get(ticker, 0)
                volatility = volatility_scores.get(ticker, 0)
                technical = technical_scores.get(ticker, 0)

                # Use adaptive weights if available
                ticker_weights = None
                if adaptive_weights:
                    ticker_weights = {
                        'momentum': adaptive_weights.momentum,
                        'value': adaptive_weights.value,
                        'quality': adaptive_weights.quality,
                        'volatility': adaptive_weights.volatility,
                        'technical': adaptive_weights.technical,
                    }
                    # Apply regime scaling
                    regime_scale = self.base_engine._adjust_weights_for_regime(market_regime)
                    for factor in ticker_weights:
                        if factor in regime_scale:
                            ticker_weights[factor] *= regime_scale[factor]
                    # Renormalize
                    total = sum(ticker_weights.values())
                    if total > 0:
                        ticker_weights = {k: v / total for k, v in ticker_weights.items()}

                # Create signal with enhanced composition
                signal = self.base_engine._create_stock_signal(
                    ticker=ticker,
                    prices=prices[ticker],
                    momentum=momentum,
                    value=value,
                    quality=quality,
                    volatility=volatility,
                    technical=technical,
                    weights=ticker_weights,
                )
                signals.append(signal)

            except Exception as e:
                logger.warning(f"Failed to generate signal for {ticker}: {e}")

        # Sort by composite score
        signals.sort(key=lambda x: x.composite_score, reverse=True)

        # Step 4: Apply sector rotation if enabled
        if self.enhanced.use_sector_rotation:
            signals = self._apply_sector_rotation(signals, prices)

        # Identify buys and sells
        buy_signals = [s for s in signals if s.action == "BUY"]
        sell_signals = [s for s in signals if s.action == "SELL"]

        # Generate recommended weights
        recommended_weights = self.base_engine._compute_optimal_weights(signals, prices)

        # Apply sector rotation to weights if enabled
        if self.enhanced.use_sector_rotation:
            # CRITICAL FIX: sector_map should map ticker -> sector NAME (string), not weights (dict)
            sector_map = {
                ticker.split("-")[0]: self.base_engine.SYMBOL_SECTOR.get(ticker.split("-")[0], "other")
                for ticker in prices.columns
            }
            recommended_weights = self.enhanced.sector_manager.check_sector_concentration(
                recommended_weights, sector_map
            )

        # Calculate expected portfolio metrics
        exp_ret, exp_vol, exp_sharpe = self.base_engine._estimate_portfolio_metrics(
            recommended_weights, prices
        )

        return PortfolioSignals(
            timestamp=datetime.now(),
            signals=signals,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            market_regime=market_regime,
            regime_confidence=regime_conf,
            recommended_weights=recommended_weights,
            expected_portfolio_return=exp_ret,
            expected_portfolio_vol=exp_vol,
            expected_sharpe=exp_sharpe,
        )

    def _compute_adaptive_weights(
        self,
        momentum_scores: Dict[str, float],
        value_scores: Dict[str, float],
        quality_scores: Dict[str, float],
        volatility_scores: Dict[str, float],
        technical_scores: Dict[str, float],
        market_regime: str,
        force_recompute: bool = False,
    ):
        """Compute adaptive weights based on historical performance."""
        # Check if we need to recompute (daily)
        now = datetime.now()
        if not force_recompute and self.last_weight_update:
            if (now - self.last_weight_update).days < 1:
                if self.adaptive_weights_cache:
                    return self.adaptive_weights_cache

        if not self.enhanced.weighting_system:
            self.enhanced.weighting_system = AdaptiveWeightingSystem()

        # Aggregate factor returns
        factor_returns = {
            'momentum': pd.Series(momentum_scores),
            'value': pd.Series(value_scores),
            'quality': pd.Series(quality_scores),
            'volatility': pd.Series(volatility_scores),
            'technical': pd.Series(technical_scores),
        }

        # Use cached returns or estimate
        portfolio_returns = self.portfolio_returns_history
        if len(portfolio_returns) == 0:
            portfolio_returns = pd.Series([0.0])

        # Compute adaptive weights
        adaptive_weights = self.enhanced.weighting_system.compute_adaptive_weights(
            factor_returns, portfolio_returns, market_regime
        )

        self.adaptive_weights_cache = adaptive_weights
        self.last_weight_update = now

        return adaptive_weights

    def _apply_sector_rotation(
        self,
        signals: List[StockSignal],
        prices: pd.DataFrame
    ) -> List[StockSignal]:
        """Apply sector rotation to filter/reweight signals."""
        if not self.enhanced.sector_manager:
            return signals

        # Get sector momentum
        # CRITICAL FIX: sector_map should map ticker -> sector NAME (string), not weights (dict)
        sector_map = {
            ticker.split("-")[0]: self.base_engine.SYMBOL_SECTOR.get(ticker.split("-")[0], "other")
            for ticker in prices.columns
        }

        sector_momentum = self.enhanced.sector_manager.get_sector_momentum(
            prices, sector_map
        )

        # Adjust signal scores based on sector momentum
        for signal in signals:
            sector = sector_map.get(signal.symbol.split("-")[0])
            if sector and sector in sector_momentum:
                # Boost signals in positive momentum sectors
                sector_boost = sector_momentum[sector] * 0.1
                signal.composite_score += sector_boost
                signal.confidence *= (1 + sector_momentum[sector] * 0.2)

        # Re-sort after adjustment
        signals.sort(key=lambda x: x.composite_score, reverse=True)

        return signals

    def update_returns_history(
        self,
        factor_returns: Dict[str, float],
        portfolio_return: float
    ) -> None:
        """
        Update historical returns for adaptive weighting.

        Call this daily with realized returns to enable adaptive weighting.

        Args:
            factor_returns: Dict of factor -> daily return
            portfolio_return: Actual portfolio daily return
        """
        timestamp = datetime.now()

        for factor, ret in factor_returns.items():
            if factor not in self.factor_returns_history:
                self.factor_returns_history[factor] = pd.Series(dtype=float)

            self.factor_returns_history[factor][timestamp] = ret

        self.portfolio_returns_history[timestamp] = portfolio_return

        # Invalidate weight cache to force recomputation
        self.last_weight_update = None

    def get_metrics(self) -> Dict:
        """Get engine metrics and state."""
        return {
            "use_pca": self.enhanced.use_pca,
            "use_adaptive_weights": self.enhanced.use_adaptive_weights,
            "use_sector_rotation": self.enhanced.use_sector_rotation,
            "adaptive_weights": (
                self.adaptive_weights_cache.to_dict()
                if self.adaptive_weights_cache
                else None
            ),
            "factor_returns_history_length": {
                k: len(v) for k, v in self.factor_returns_history.items()
            },
            "portfolio_returns_history_length": len(self.portfolio_returns_history),
        }


def enhance_signal_engine(
    base_engine: SignalEngine,
    use_pca: bool = True,
    use_adaptive_weights: bool = True,
    use_sector_rotation: bool = True,
) -> EnhancedSignalEngineWrapper:
    """
    Factory function to enhance existing signal engine.

    Example:
        engine = SignalEngine()
        enhanced = enhance_signal_engine(engine)
        signals = enhanced.generate_signals(prices, volumes, fundamentals)
    """
    return EnhancedSignalEngineWrapper(
        base_engine=base_engine,
        use_pca=use_pca,
        use_adaptive_weights=use_adaptive_weights,
        use_sector_rotation=use_sector_rotation,
    )
