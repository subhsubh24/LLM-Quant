"""
Tests for Real Sentiment & Alternative Data Integration - Phase 6

Tests cover:
- News sentiment analysis (keyword counting)
- Options sentiment analysis (put/call ratios)
- Social sentiment analysis (post aggregation)
- Composite sentiment engine
- Trend detection
- Signal confidence scoring
"""

import pytest
from datetime import datetime, timedelta
import numpy as np

from app.portfolio.sentiment_integration import (
    NewsSentimentAnalyzer,
    OptionsSentimentAnalyzer,
    SocialSentimentAnalyzer,
    CompositeSentimentEngine,
    SentimentLevel,
    SentimentScore,
    CompositeSentiment,
)


class TestNewsSentimentAnalyzer:
    """Test news sentiment analysis."""

    def test_initialization(self):
        """Test initializes properly."""
        analyzer = NewsSentimentAnalyzer(lookback_days=7)
        assert analyzer.lookback_days == 7
        assert len(analyzer.news_history) == 0

    def test_empty_headlines(self):
        """Test with no headlines."""
        analyzer = NewsSentimentAnalyzer()
        score = analyzer.analyze_headlines("AAPL", [])

        assert score.symbol == "AAPL"
        assert score.source == "news"
        assert score.score == 0.0
        assert score.confidence == 0.0
        assert score.data_points == 0

    def test_bullish_headlines(self):
        """Test with bullish news."""
        analyzer = NewsSentimentAnalyzer()

        headlines = [
            {
                "title": "Apple surges on strong growth",
                "description": "Record profits drive rally",
            },
            {
                "title": "Tech sector innovation leads market",
                "description": "Apple expansion opportunity",
            },
        ]

        score = analyzer.analyze_headlines("AAPL", headlines)

        assert score.symbol == "AAPL"
        assert score.score > 0.5  # Bullish
        assert score.confidence > 0.0
        assert score.data_points == 2

    def test_bearish_headlines(self):
        """Test with bearish news."""
        analyzer = NewsSentimentAnalyzer()

        headlines = [
            {
                "title": "Apple stock plunges on weak earnings",
                "description": "Risk of declining sales",
            },
            {
                "title": "Tech sector faces challenges",
                "description": "Apple downgrade warning",
            },
        ]

        score = analyzer.analyze_headlines("AAPL", headlines)

        assert score.symbol == "AAPL"
        assert score.score < -0.5  # Bearish
        assert score.confidence > 0.0
        assert score.data_points == 2

    def test_mixed_headlines(self):
        """Test with mixed sentiment."""
        analyzer = NewsSentimentAnalyzer()

        headlines = [
            {"title": "Apple surges on growth", "description": "Positive outlook"},
            {"title": "Apple faces challenges", "description": "Risk warning"},
        ]

        score = analyzer.analyze_headlines("AAPL", headlines)

        assert score.symbol == "AAPL"
        assert -0.5 < score.score < 0.5  # Near neutral
        assert score.data_points == 2

    def test_sentiment_history_tracking(self):
        """Test sentiment history is tracked."""
        analyzer = NewsSentimentAnalyzer()

        # Add first batch
        headlines1 = [
            {"title": "Apple surges", "description": "Growth"}
        ]
        score1 = analyzer.analyze_headlines("AAPL", headlines1)

        # Add second batch
        headlines2 = [
            {"title": "Apple declines", "description": "Weakness"}
        ]
        score2 = analyzer.analyze_headlines("AAPL", headlines2)

        # History should have 2 entries
        assert len(analyzer.news_history["AAPL"]) == 2

    def test_sentiment_trend_stable(self):
        """Test stable sentiment trend."""
        analyzer = NewsSentimentAnalyzer()

        # Add consistent bullish headlines
        for _ in range(10):
            headlines = [
                {"title": "Apple surges", "description": "Growth"}
            ]
            analyzer.analyze_headlines("AAPL", headlines)

        trend = analyzer.get_sentiment_trend("AAPL")
        assert trend in ["strengthening", "weakening", "stable"]

    def test_keyword_detection(self):
        """Test keyword detection works correctly."""
        analyzer = NewsSentimentAnalyzer()

        # Explicitly bullish
        headlines = [
            {"title": "surge jump soar rally climb", "description": "bullish positive"}
        ]
        score = analyzer.analyze_headlines("TEST", headlines)
        assert score.score > 1.0

        # Explicitly bearish
        headlines = [
            {"title": "plunge crash drop decline fall", "description": "bearish negative"}
        ]
        score = analyzer.analyze_headlines("TEST", headlines)
        assert score.score < -1.0


class TestOptionsSentimentAnalyzer:
    """Test options sentiment analysis."""

    def test_initialization(self):
        """Test initializes properly."""
        analyzer = OptionsSentimentAnalyzer(lookback_days=7)
        assert analyzer.lookback_days == 7
        assert analyzer.normal_pcr == 0.7
        assert len(analyzer.pcr_history) == 0

    def test_low_put_call_ratio(self):
        """Test bullish signal from low put/call ratio."""
        analyzer = OptionsSentimentAnalyzer()

        # Low PCR = bullish (more call buying)
        score = analyzer.analyze_put_call_ratio(
            "AAPL",
            put_volume=100,
            call_volume=500,
            put_open_interest=1000,
            call_open_interest=3000,
        )

        assert score.symbol == "AAPL"
        assert score.source == "options"
        assert score.score > 0.0  # Bullish
        assert 0.0 <= score.confidence <= 1.0

    def test_high_put_call_ratio(self):
        """Test bearish signal from high put/call ratio."""
        analyzer = OptionsSentimentAnalyzer()

        # High PCR = bearish (more put buying/hedging)
        score = analyzer.analyze_put_call_ratio(
            "AAPL",
            put_volume=500,
            call_volume=100,
            put_open_interest=3000,
            call_open_interest=1000,
        )

        assert score.symbol == "AAPL"
        assert score.score < 0.0  # Bearish
        assert 0.0 <= score.confidence <= 1.0

    def test_zero_call_volume(self):
        """Test with zero call volume."""
        analyzer = OptionsSentimentAnalyzer()

        score = analyzer.analyze_put_call_ratio(
            "TEST",
            put_volume=100,
            call_volume=0,
            put_open_interest=0,
            call_open_interest=0,
        )

        assert score.data_points == 0
        assert score.score == 0.0

    def test_pcr_history_tracking(self):
        """Test PCR history is tracked."""
        analyzer = OptionsSentimentAnalyzer()

        # Add first ratio
        analyzer.analyze_put_call_ratio("AAPL", 100, 500, 1000, 3000)

        # Add second ratio
        analyzer.analyze_put_call_ratio("AAPL", 200, 600, 1200, 3500)

        # History should have 2 entries
        assert len(analyzer.pcr_history["AAPL"]) == 2

    def test_pcr_trend(self):
        """Test PCR trend detection."""
        analyzer = OptionsSentimentAnalyzer()

        # Add bullish then bearish (PCR falling then rising)
        for i in range(5):
            analyzer.analyze_put_call_ratio("AAPL", 100 + i, 500, 1000, 3000)

        for i in range(5):
            analyzer.analyze_put_call_ratio("AAPL", 300 + i, 300, 2000, 1500)

        trend = analyzer.get_pcr_trend("AAPL")
        assert trend in ["strengthening", "weakening", "stable"]

    def test_pcr_ratio_computation(self):
        """Test put/call ratio is computed correctly."""
        analyzer = OptionsSentimentAnalyzer()

        score = analyzer.analyze_put_call_ratio(
            "TEST",
            put_volume=70,
            call_volume=100,
            put_open_interest=700,
            call_open_interest=1000,
        )

        # PCR should be close to normal_pcr (0.7)
        pcr = score.extra_info['put_call_ratio']
        assert 0.65 < pcr < 0.75


class TestSocialSentimentAnalyzer:
    """Test social sentiment analysis."""

    def test_initialization(self):
        """Test initializes properly."""
        analyzer = SocialSentimentAnalyzer(lookback_days=7)
        assert analyzer.lookback_days == 7
        assert len(analyzer.sentiment_history) == 0

    def test_empty_posts(self):
        """Test with no posts."""
        analyzer = SocialSentimentAnalyzer()

        score = analyzer.analyze_social_posts("AAPL", [])

        assert score.symbol == "AAPL"
        assert score.source == "social"
        assert score.score == 0.0
        assert score.confidence == 0.0
        assert score.data_points == 0

    def test_bullish_posts(self):
        """Test with bullish social posts."""
        analyzer = SocialSentimentAnalyzer()

        posts = [
            {"text": "#bullish #moon #rocket - AAPL is going to the moon!"},
            {"text": "Buy AAPL, this is a winner #bullrun"},
        ]

        score = analyzer.analyze_social_posts("AAPL", posts)

        assert score.symbol == "AAPL"
        assert score.score > 0.5  # Bullish
        assert score.data_points == 2

    def test_bearish_posts(self):
        """Test with bearish social posts."""
        analyzer = SocialSentimentAnalyzer()

        posts = [
            {"text": "#bearish #crash #dump - AAPL is going down"},
            {"text": "Sell AAPL now, avoid this loser"},
        ]

        score = analyzer.analyze_social_posts("AAPL", posts)

        assert score.symbol == "AAPL"
        assert score.score < -0.5  # Bearish
        assert score.data_points == 2

    def test_social_sentiment_history(self):
        """Test social sentiment history tracking."""
        analyzer = SocialSentimentAnalyzer()

        posts1 = [{"text": "#bullish AAPL"}]
        analyzer.analyze_social_posts("AAPL", posts1)

        posts2 = [{"text": "#bearish AAPL"}]
        analyzer.analyze_social_posts("AAPL", posts2)

        assert len(analyzer.sentiment_history["AAPL"]) == 2

    def test_confidence_from_volume(self):
        """Test confidence increases with more posts."""
        analyzer = SocialSentimentAnalyzer()

        # Few posts
        posts_few = [{"text": "#bullish AAPL"}]
        score_few = analyzer.analyze_social_posts("TEST1", posts_few)

        # Many posts
        posts_many = [{"text": "#bullish AAPL"} for _ in range(50)]
        score_many = analyzer.analyze_social_posts("TEST2", posts_many)

        # More posts should give higher confidence
        assert score_many.confidence >= score_few.confidence


class TestCompositeSentimentEngine:
    """Test composite sentiment aggregation."""

    def test_initialization(self):
        """Test initializes properly."""
        engine = CompositeSentimentEngine()
        assert engine.news_analyzer is not None
        assert engine.options_analyzer is not None
        assert engine.social_analyzer is not None

    def test_single_source_news(self):
        """Test composite with only news."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple surges on growth", "description": "Strong earnings"}
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
        )

        assert composite.symbol == "AAPL"
        assert composite.overall_score > 0.0  # Should be bullish
        assert composite.news_score > 0.0
        assert composite.options_score == 0.0  # No options data
        assert composite.social_score == 0.0  # No social data
        assert composite.source_count == 1

    def test_single_source_options(self):
        """Test composite with only options."""
        engine = CompositeSentimentEngine()

        composite = engine.compute_composite_sentiment(
            "AAPL",
            put_volume=100,
            call_volume=500,
            put_oi=1000,
            call_oi=3000,
        )

        assert composite.symbol == "AAPL"
        assert composite.news_score == 0.0  # No news data
        assert composite.options_score > 0.0  # Should be bullish
        assert composite.social_score == 0.0  # No social data
        assert composite.source_count == 1

    def test_multi_source_consensus_bullish(self):
        """Test when all sources agree bullish."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple surges", "description": "Strong growth"}
        ]
        posts = [
            {"text": "#bullish #moon AAPL"}
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
            put_volume=100,
            call_volume=500,
            put_oi=1000,
            call_oi=3000,
            social_posts=posts,
        )

        assert composite.overall_score > 0.5  # Strongly bullish
        assert composite.source_count == 3
        assert composite.sentiment_level == SentimentLevel.BULLISH or \
               composite.sentiment_level == SentimentLevel.STRONGLY_BULLISH

    def test_multi_source_consensus_bearish(self):
        """Test when all sources agree bearish."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple crashes", "description": "Weak earnings"}
        ]
        posts = [
            {"text": "#bearish #dump AAPL"}
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
            put_volume=500,
            call_volume=100,
            put_oi=3000,
            call_oi=1000,
            social_posts=posts,
        )

        assert composite.overall_score < -0.5  # Strongly bearish
        assert composite.source_count == 3
        assert composite.sentiment_level == SentimentLevel.BEARISH or \
               composite.sentiment_level == SentimentLevel.STRONGLY_BEARISH

    def test_sentiment_level_classification(self):
        """Test sentiment level classification."""
        engine = CompositeSentimentEngine()

        # Test extreme bullish
        headlines_strong_bull = [
            {"title": "surge jump soar rally climb gain", "description": "bullish positive"}
        ]
        composite = engine.compute_composite_sentiment(
            "TEST1",
            news_headlines=headlines_strong_bull,
        )
        assert composite.sentiment_level in [
            SentimentLevel.BULLISH,
            SentimentLevel.STRONGLY_BULLISH
        ]

        # Test extreme bearish
        headlines_strong_bear = [
            {"title": "plunge crash drop decline fall", "description": "bearish negative"}
        ]
        composite = engine.compute_composite_sentiment(
            "TEST2",
            news_headlines=headlines_strong_bear,
        )
        assert composite.sentiment_level in [
            SentimentLevel.BEARISH,
            SentimentLevel.STRONGLY_BEARISH
        ]

    def test_signal_strength_calculation(self):
        """Test signal strength is computed correctly."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple surges", "description": "Strong growth"}
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
        )

        # Signal strength = |score| * confidence
        assert 0.0 <= composite.signal_strength <= 1.0
        expected_strength = abs(composite.overall_score) * composite.weighted_confidence
        assert abs(composite.signal_strength - expected_strength) < 0.01

    def test_weighted_confidence(self):
        """Test weighted confidence aggregation."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple surges on growth", "description": "Consensus bullish"}
        ]
        posts = [
            {"text": "#bullish AAPL"} for _ in range(50)
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
            social_posts=posts,
        )

        # Weighted confidence should be reasonable
        assert 0.0 <= composite.weighted_confidence <= 1.0

    def test_trend_detection(self):
        """Test trend detection works."""
        engine = CompositeSentimentEngine()

        headlines = [
            {"title": "Apple surges", "description": "Growth"}
        ]

        composite = engine.compute_composite_sentiment(
            "AAPL",
            news_headlines=headlines,
        )

        assert composite.trend in ["strengthening", "weakening", "stable"]

    def test_boundary_scores(self):
        """Test extreme sentiment scores are bounded."""
        engine = CompositeSentimentEngine()

        # Extreme bullish
        headlines_bull = [
            {"title": " ".join(["surge"] * 20), "description": " ".join(["bullish"] * 20)}
        ]
        composite_bull = engine.compute_composite_sentiment(
            "TEST",
            news_headlines=headlines_bull,
        )
        assert -2.0 <= composite_bull.overall_score <= 2.0

        # Extreme bearish
        headlines_bear = [
            {"title": " ".join(["crash"] * 20), "description": " ".join(["bearish"] * 20)}
        ]
        composite_bear = engine.compute_composite_sentiment(
            "TEST",
            news_headlines=headlines_bear,
        )
        assert -2.0 <= composite_bear.overall_score <= 2.0

    def test_source_weighting(self):
        """Test sources are weighted correctly."""
        engine = CompositeSentimentEngine()

        # Verify weights sum to 1.0
        total_weight = sum(engine.source_weights.values())
        assert abs(total_weight - 1.0) < 0.01

        # Verify news has highest weight (40%)
        assert engine.source_weights['news'] >= engine.source_weights['options']
        assert engine.source_weights['news'] >= engine.source_weights['social']


class TestSentimentDataClasses:
    """Test sentiment data structures."""

    def test_sentiment_score_creation(self):
        """Test SentimentScore creation."""
        score = SentimentScore(
            symbol="AAPL",
            source="news",
            score=1.5,
            confidence=0.8,
            timestamp=datetime.now(),
            data_points=10,
        )

        assert score.symbol == "AAPL"
        assert score.source == "news"
        assert score.score == 1.5
        assert score.confidence == 0.8
        assert score.data_points == 10

    def test_composite_sentiment_creation(self):
        """Test CompositeSentiment creation."""
        now = datetime.now()
        sentiment = CompositeSentiment(
            symbol="AAPL",
            overall_score=1.0,
            news_score=0.8,
            options_score=1.2,
            social_score=0.9,
            weighted_confidence=0.75,
            sentiment_level=SentimentLevel.BULLISH,
            signal_strength=0.75,
            timestamp=now,
            source_count=3,
            trend="strengthening",
        )

        assert sentiment.symbol == "AAPL"
        assert sentiment.overall_score == 1.0
        assert sentiment.sentiment_level == SentimentLevel.BULLISH
        assert sentiment.source_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
