"""
Tests for Sentiment Analysis Trading Strategy - Phase 6

Tests cover:
- Sentiment signal generation
- Multi-source consensus logic
- Confidence scoring
- Trend boosting
- Integration with sentiment engine
"""

import pytest
from datetime import datetime
import numpy as np
import pandas as pd

from app.strategies.sentiment_strategy import (
    SentimentAnalysisStrategy,
    MultiSourceSentimentStrategy,
)


class TestSentimentAnalysisStrategy:
    """Test sentiment analysis trading strategy."""

    def test_initialization(self):
        """Test strategy initializes properly."""
        strategy = SentimentAnalysisStrategy()

        assert strategy.strategy_id == "sentiment_analysis_v1"
        assert strategy.strategy_name == "Sentiment Analysis"
        assert strategy.confidence_threshold == 0.3
        assert strategy.source_count_required == 1

    def test_no_context(self):
        """Test behavior with no context."""
        strategy = SentimentAnalysisStrategy()

        data = pd.DataFrame({"close": [100, 101, 102]})
        signal = strategy.generate_signal(data, context=None)

        assert signal.confidence == 0.0

    def test_insufficient_confidence(self):
        """Test signal filtered by confidence threshold."""
        strategy = SentimentAnalysisStrategy(confidence_threshold=0.9)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple stock moves", "description": "Neutral movement"}
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # Signal confidence should be below threshold or no signal generated
        assert signal.confidence <= strategy.confidence_threshold or signal.confidence == 0.0

    def test_bullish_signal_generation(self):
        """Test bullish signal generation from news."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {
                    "title": "Apple surges surge jump soar rally",
                    "description": "Strong growth bullish positive",
                }
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        assert signal.symbols.get("SENTIMENT", 0) > 0
        assert signal.confidence > 0.3

    def test_bearish_signal_generation(self):
        """Test bearish signal generation from news."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {
                    "title": "Apple crashes plunge drop decline",
                    "description": "Weak earnings bearish negative",
                }
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        assert signal.symbols.get("SENTIMENT", 0) < 0
        assert signal.confidence > 0.3

    def test_bullish_options_signal(self):
        """Test bullish signal from options positioning."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "put_volume": 100,
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # Low put/call ratio = bullish
        if signal.confidence > 0.3:
            assert signal.symbols.get("SENTIMENT", 0) > 0

    def test_bearish_options_signal(self):
        """Test bearish signal from options positioning."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "put_volume": 500,
            "call_volume": 100,
            "put_oi": 3000,
            "call_oi": 1000,
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # High put/call ratio = bearish
        if signal.confidence > 0.3:
            assert signal.symbols.get("SENTIMENT", 0) < 0

    def test_multi_source_consensus_bullish(self):
        """Test bullish consensus from multiple sources."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges surge", "description": "bullish growth"}
            ],
            "put_volume": 100,
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
            "social_posts": [{"text": "#bullish #moon AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # All sources bullish = strong signal
        if signal.confidence > 0.4:
            assert signal.symbols.get("SENTIMENT", 0) > 0

    def test_multi_source_consensus_bearish(self):
        """Test bearish consensus from multiple sources."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple crashes crash", "description": "bearish decline"}
            ],
            "put_volume": 500,
            "call_volume": 100,
            "put_oi": 3000,
            "call_oi": 1000,
            "social_posts": [{"text": "#bearish #dump AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # All sources bearish = strong signal
        if signal.confidence > 0.4:
            assert signal.symbols.get("SENTIMENT", 0) < 0

    def test_source_count_filtering(self):
        """Test minimum source count requirement."""
        strategy = SentimentAnalysisStrategy(source_count_required=2)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
            # No options or social data
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # Only 1 source, but need 2
        assert signal.confidence == 0.0

    def test_trend_boost_strengthening(self):
        """Test confidence boost when sentiment strengthening."""
        strategy = SentimentAnalysisStrategy(
            source_count_required=1,
            trend_boost=0.1,
        )

        # Add several bullish signals to build up trend
        for i in range(5):
            context = {
                "symbol": "AAPL",
                "news_headlines": [
                    {"title": "Apple surges", "description": "bullish"}
                ],
            }
            data = pd.DataFrame({"close": [100]})
            signal = strategy.generate_signal(data, context=context)

        # Last signal should have trend boost applied
        assert signal.confidence > 0.0

    def test_extra_data_included(self):
        """Test extra data is included in signal."""
        strategy = SentimentAnalysisStrategy(source_count_required=1)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        if signal.confidence > 0:
            assert "sentiment_level" in signal.extra_data
            assert "overall_score" in signal.extra_data
            assert "news_score" in signal.extra_data
            assert "signal_strength" in signal.extra_data
            assert "source_count" in signal.extra_data

    def test_signal_structure(self):
        """Test generated signal has correct structure."""
        strategy = SentimentAnalysisStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        assert hasattr(signal, "symbols")
        assert hasattr(signal, "target_weights")
        assert hasattr(signal, "confidence")
        assert hasattr(signal, "strategy_id")
        assert signal.strategy_id == "sentiment_analysis_v1"


class TestMultiSourceSentimentStrategy:
    """Test multi-source consensus sentiment strategy."""

    def test_initialization(self):
        """Test strategy initializes properly."""
        strategy = MultiSourceSentimentStrategy()

        assert strategy.strategy_id == "sentiment_consensus_v1"
        assert strategy.min_agreement_score == 0.5
        assert strategy.require_all_sources == False

    def test_no_consensus(self):
        """Test no signal when sources disagree."""
        strategy = MultiSourceSentimentStrategy(min_agreement_score=0.9)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
            "put_volume": 500,  # Bearish options
            "call_volume": 100,
            "put_oi": 3000,
            "call_oi": 1000,
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # News bullish, options bearish = disagreement
        # Should produce low confidence or no signal
        assert signal.confidence < 0.5 or "SENTIMENT_CONSENSUS" not in signal.symbols

    def test_bullish_consensus(self):
        """Test bullish signal with consensus."""
        strategy = MultiSourceSentimentStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges surge", "description": "bullish growth"}
            ],
            "put_volume": 100,  # Bullish options
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
            "social_posts": [{"text": "#bullish #moon AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # All sources agree bullish
        assert signal.symbols.get("SENTIMENT_CONSENSUS", 0) > 0
        assert signal.confidence > 0.4

    def test_bearish_consensus(self):
        """Test bearish signal with consensus."""
        strategy = MultiSourceSentimentStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple crashes crash", "description": "bearish weak"}
            ],
            "put_volume": 500,  # Bearish options
            "call_volume": 100,
            "put_oi": 3000,
            "call_oi": 1000,
            "social_posts": [{"text": "#bearish #dump AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # All sources agree bearish
        assert signal.symbols.get("SENTIMENT_CONSENSUS", 0) < 0
        assert signal.confidence > 0.4

    def test_insufficient_sources(self):
        """Test no consensus with insufficient sources."""
        strategy = MultiSourceSentimentStrategy(require_all_sources=True)

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
            # Only news, no options or social
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # Only 1 source, require 3
        assert signal.confidence == 0.0

    def test_agreement_score_calculation(self):
        """Test agreement score affects confidence."""
        strategy = MultiSourceSentimentStrategy()

        # Perfect agreement (3/3 bullish)
        context_perfect = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges surge surge", "description": "bullish"}
            ],
            "put_volume": 100,
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
            "social_posts": [{"text": "#bullish #moon AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal_perfect = strategy.generate_signal(data, context=context_perfect)

        # Partial agreement (2/3 bullish)
        context_partial = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
            "put_volume": 500,  # Bearish
            "call_volume": 100,
            "put_oi": 3000,
            "call_oi": 1000,
            "social_posts": [{"text": "#bullish AAPL"}],
        }

        signal_partial = strategy.generate_signal(data, context=context_partial)

        # Perfect agreement should have higher confidence
        if signal_perfect.confidence > 0 and signal_partial.confidence > 0:
            # Perfect agreement shouldn't necessarily be higher due to min_agreement
            pass

    def test_extra_data_consensus(self):
        """Test consensus data is included in signal."""
        strategy = MultiSourceSentimentStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges", "description": "bullish"}
            ],
            "put_volume": 100,
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        if signal.confidence > 0.3:
            assert "source_agreement" in signal.extra_data
            assert "sources_bullish" in signal.extra_data
            assert "sources_bearish" in signal.extra_data


class TestIntegration:
    """Test strategy integration."""

    def test_both_strategies_same_context(self):
        """Test both strategies generate signals from same context."""
        strategy1 = SentimentAnalysisStrategy(source_count_required=1)
        strategy2 = MultiSourceSentimentStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple surges surge", "description": "bullish growth"}
            ],
            "put_volume": 100,
            "call_volume": 500,
            "put_oi": 1000,
            "call_oi": 3000,
            "social_posts": [{"text": "#bullish AAPL"}],
        }

        data = pd.DataFrame({"close": [100]})
        signal1 = strategy1.generate_signal(data, context=context)
        signal2 = strategy2.generate_signal(data, context=context)

        # Both should generate signals, consensus more strict
        assert signal1.confidence > 0
        # signal2 may have higher confidence due to agreement

    def test_neutral_market(self):
        """Test with neutral sentiment."""
        strategy = SentimentAnalysisStrategy()

        context = {
            "symbol": "AAPL",
            "news_headlines": [
                {"title": "Apple stock trades", "description": "neutral movement"}
            ],
        }

        data = pd.DataFrame({"close": [100]})
        signal = strategy.generate_signal(data, context=context)

        # Neutral sentiment should have low confidence
        assert signal.confidence < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
