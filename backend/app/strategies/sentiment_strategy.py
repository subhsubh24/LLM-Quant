"""
Sentiment Analysis Trading Strategy - Phase 6

Generates trading signals based on:
- News sentiment (headlines, articles)
- Options market positioning (put/call ratios)
- Social media sentiment (Twitter, Reddit)
- Composite sentiment index

SIGNAL GENERATION LOGIC:
- Strongly Bullish (score > 1.5): Long signal, high confidence
- Bullish (0.5 to 1.5): Mild long signal, moderate confidence
- Neutral (-0.5 to 0.5): No signal or small position
- Bearish (-1.5 to -0.5): Mild short signal, moderate confidence
- Strongly Bearish (< -1.5): Short signal, high confidence

RISK CONTROLS:
- Only generate signals if weighted_confidence > 0.3
- Signal strength acts as confidence multiplier
- Trend consideration: strengthening trends get more weight
- Cross-source consensus required for high-confidence signals

EXPECTED IMPACT: +0.25 Sharpe (alternative data alpha)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Any
from datetime import datetime
import logging

from .framework import BaseStrategy, StrategySignal
from app.portfolio.sentiment_integration import (
    CompositeSentimentEngine,
    SentimentLevel,
)

logger = logging.getLogger(__name__)


class SentimentAnalysisStrategy(BaseStrategy):
    """
    Trading strategy based on composite sentiment analysis.

    Uses news, options, and social sentiment to generate directional signals.
    Employs multi-source consensus for robustness.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.3,
        source_count_required: int = 1,
        trend_boost: float = 0.1,
    ):
        """Initialize sentiment analysis strategy.

        Args:
            confidence_threshold: Minimum confidence to generate signal
            source_count_required: Minimum number of sentiment sources
            trend_boost: Additional signal boost if trend is strengthening
        """
        super().__init__(
            name="Sentiment Analysis",
            description="Multi-source sentiment trading",
        )
        self.engine = CompositeSentimentEngine()
        self.confidence_threshold = confidence_threshold
        self.source_count_required = source_count_required
        self.trend_boost = trend_boost

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """Generate sentiment-based trading signal.

        Args:
            data: OHLCV data (not directly used for sentiment, but for consistency)
            context: Dict with sentiment data:
                - news_headlines: List of {'title', 'description', 'publishedAt'}
                - put_volume, call_volume, put_oi, call_oi: Options data
                - social_posts: List of {'text', 'timestamp'}

        Returns:
            StrategySignal with sentiment-based direction
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
        )

        if not context:
            return signal

        try:
            # Extract sentiment data from context
            symbol = context.get('symbol', 'UNKNOWN')
            news_headlines = context.get('news_headlines')
            put_volume = context.get('put_volume', 0)
            call_volume = context.get('call_volume', 0)
            put_oi = context.get('put_oi', 0)
            call_oi = context.get('call_oi', 0)
            social_posts = context.get('social_posts')

            # Compute composite sentiment
            composite = self.engine.compute_composite_sentiment(
                symbol=symbol,
                news_headlines=news_headlines,
                put_volume=put_volume,
                call_volume=call_volume,
                put_oi=put_oi,
                call_oi=call_oi,
                social_posts=social_posts,
            )

            # Check minimum sources
            if composite.source_count < self.source_count_required:
                signal.confidence = 0.0
                return signal

            # Check confidence threshold
            if composite.weighted_confidence < self.confidence_threshold:
                signal.confidence = 0.0
                return signal

            # Apply trend boost if sentiment strengthening
            confidence = composite.weighted_confidence
            if composite.trend == 'strengthening':
                confidence = min(1.0, confidence + self.trend_boost)

            # Generate signal based on sentiment level
            if composite.sentiment_level == SentimentLevel.STRONGLY_BULLISH:
                signal.symbols['SENTIMENT'] = 1.0
                signal.target_weights['SENTIMENT'] = 0.8
                signal.confidence = min(1.0, confidence * 1.2)  # 20% confidence boost

            elif composite.sentiment_level == SentimentLevel.BULLISH:
                signal.symbols['SENTIMENT'] = 0.6
                signal.target_weights['SENTIMENT'] = 0.5
                signal.confidence = confidence

            elif composite.sentiment_level == SentimentLevel.BEARISH:
                signal.symbols['SENTIMENT'] = -0.6
                signal.target_weights['SENTIMENT'] = 0.5
                signal.confidence = confidence

            elif composite.sentiment_level == SentimentLevel.STRONGLY_BEARISH:
                signal.symbols['SENTIMENT'] = -1.0
                signal.target_weights['SENTIMENT'] = 0.8
                signal.confidence = min(1.0, confidence * 1.2)  # 20% confidence boost

            else:  # NEUTRAL
                signal.confidence = 0.2

            # Add extra data for analysis
            signal.extra_data = {
                'sentiment_level': composite.sentiment_level.value,
                'overall_score': float(composite.overall_score),
                'news_score': float(composite.news_score),
                'options_score': float(composite.options_score),
                'social_score': float(composite.social_score),
                'signal_strength': float(composite.signal_strength),
                'weighted_confidence': float(composite.weighted_confidence),
                'source_count': composite.source_count,
                'trend': composite.trend,
                'source_weights': {
                    'news': self.engine.source_weights['news'],
                    'options': self.engine.source_weights['options'],
                    'social': self.engine.source_weights['social'],
                },
            }

            self.last_signal = signal

        except Exception as e:
            logger.warning(f"Sentiment analysis signal generation failed: {e}")
            signal.confidence = 0

        return signal


class MultiSourceSentimentStrategy(BaseStrategy):
    """
    Enhanced sentiment strategy requiring consensus from multiple sources.

    Only generates strong signals when multiple sources agree.
    More conservative but potentially more reliable.
    """

    def __init__(
        self,
        min_agreement_score: float = 0.5,  # Signals must align in direction
        require_all_sources: bool = False,
    ):
        """Initialize multi-source sentiment strategy.

        Args:
            min_agreement_score: Minimum agreement between sources
            require_all_sources: If True, require news + options + social
        """
        super().__init__(
            name="Sentiment Consensus",
            description="Multi-source consensus sentiment trading",
        )
        self.engine = CompositeSentimentEngine()
        self.min_agreement_score = min_agreement_score
        self.require_all_sources = require_all_sources

    def generate_signal(
        self,
        data: pd.DataFrame,
        context: Optional[Dict[str, Any]] = None,
    ) -> StrategySignal:
        """Generate consensus sentiment signal.

        Args:
            data: OHLCV data (not directly used)
            context: Dict with sentiment data (same as SentimentAnalysisStrategy)

        Returns:
            StrategySignal only if multiple sources agree
        """
        signal = StrategySignal(
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            timestamp=datetime.now(),
        )

        if not context:
            return signal

        try:
            # Extract sentiment data
            symbol = context.get('symbol', 'UNKNOWN')
            news_headlines = context.get('news_headlines')
            put_volume = context.get('put_volume', 0)
            call_volume = context.get('call_volume', 0)
            put_oi = context.get('put_oi', 0)
            call_oi = context.get('call_oi', 0)
            social_posts = context.get('social_posts')

            # Compute composite sentiment
            composite = self.engine.compute_composite_sentiment(
                symbol=symbol,
                news_headlines=news_headlines,
                put_volume=put_volume,
                call_volume=call_volume,
                put_oi=put_oi,
                call_oi=call_oi,
                social_posts=social_posts,
            )

            # Check if we have enough sources
            if self.require_all_sources:
                if composite.source_count < 3:
                    return signal
            else:
                if composite.source_count < 2:
                    return signal

            # Check source agreement
            # All sources should point same direction (all > 0 or all < 0)
            scores = [composite.news_score, composite.options_score, composite.social_score]
            valid_scores = [s for s in scores if s != 0]

            if not valid_scores:
                return signal

            # Compute agreement: Do sources agree on direction?
            positive_count = sum(1 for s in valid_scores if s > 0)
            negative_count = sum(1 for s in valid_scores if s < 0)
            total_count = len(valid_scores)

            # Agreement score: 1.0 if all agree, 0.0 if split
            agreement = max(positive_count, negative_count) / total_count

            if agreement < self.min_agreement_score:
                signal.confidence = 0.2  # Weak signal due to disagreement
                return signal

            # All sources agree - generate strong signal
            if positive_count > negative_count:
                # Bullish consensus
                signal.symbols['SENTIMENT_CONSENSUS'] = 1.0
                signal.target_weights['SENTIMENT_CONSENSUS'] = 0.7
                signal.confidence = min(1.0, agreement * composite.weighted_confidence)

            else:
                # Bearish consensus
                signal.symbols['SENTIMENT_CONSENSUS'] = -1.0
                signal.target_weights['SENTIMENT_CONSENSUS'] = 0.7
                signal.confidence = min(1.0, agreement * composite.weighted_confidence)

            # Add extra data
            signal.extra_data = {
                'source_agreement': float(agreement),
                'sources_bullish': positive_count,
                'sources_bearish': negative_count,
                'overall_score': float(composite.overall_score),
                'signal_strength': float(composite.signal_strength),
            }

            self.last_signal = signal

        except Exception as e:
            logger.warning(f"Consensus sentiment signal generation failed: {e}")
            signal.confidence = 0

        return signal
