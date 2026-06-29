"""
Tests for market_text.py — the hardened cross-market relatedness screen (ROADMAP B5).

These pin the property that matters: filler/boilerplate overlap can NO LONGER pair two
unrelated markets, while genuine shared content tokens still register as related. This is
the regression guard for the phantom-signal bug an adversarial audit found (a weak skip
set paired ~98 unrelated markets on shared boilerplate — RESEARCH_MEMORY 2026-06-29).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.prediction_markets.market_text import (  # noqa: E402
    DEFAULT_MIN_SHARED,
    STOP_WORDS,
    content_tokens,
    is_content_related,
    shared_content_tokens,
)


class TestContentTokens:
    def test_drops_short_tokens(self):
        # "win" (3), "of" (2), "to" (2) are all below the length-4 floor.
        toks = content_tokens("Will A win race to top of poll")
        assert "win" not in toks
        assert "race" in toks  # 4 chars, content
        assert "poll" in toks

    def test_drops_stop_words(self):
        toks = content_tokens("Will the market resolve before the deadline this year")
        # All of these are filler in STOP_WORDS and must be excluded.
        for filler in ("will", "the", "market", "resolve", "before", "deadline",
                       "this", "year"):
            assert filler not in toks

    def test_drops_pure_numeric_tokens(self):
        toks = content_tokens("Will Bitcoin surge 150000 by 2024")
        assert "150000" not in toks
        assert "2024" not in toks
        assert "bitcoin" in toks  # "exceed"/"surge" filler-ish; bitcoin is the subject
        assert "exceed" in STOP_WORDS  # threshold verb is now filler

    def test_empty_and_none(self):
        assert content_tokens("") == set()
        assert content_tokens(None) == set()  # type: ignore[arg-type]

    def test_stop_words_is_frozenset(self):
        assert isinstance(STOP_WORDS, frozenset)
        assert "market" in STOP_WORDS


class TestRelatedness:
    def test_boilerplate_only_pair_is_not_related(self):
        # The exact phantom-signal shape: identical boilerplate, no shared real content.
        q1 = "Market 123 (real sample) will resolve"
        q2 = "Market 456 (real sample) will resolve"
        # "sample"/"market"/"real"/"resolve"/"will" are all filler → 0 shared content.
        assert shared_content_tokens(q1, q2) == set()
        assert not is_content_related(q1, q2)

    def test_unrelated_questions_sharing_filler_not_related(self):
        q1 = "Will the Lakers win the championship before the deadline this year"
        q2 = "Will the Fed cut rates before the deadline this year"
        # Shared tokens are all filler (will/the/before/deadline/this/year) → not related.
        assert not is_content_related(q1, q2)

    def test_genuinely_related_questions_are_related(self):
        # Same subject (Trump), varying sub-condition (Iowa vs Texas) → related: shares
        # 3+ content tokens. ("presidential" is template filler now, but donald/trump/
        # primary remain real content.)
        q1 = "Will Donald Trump win the presidential primary in Iowa"
        q2 = "Will Donald Trump win the presidential primary in Texas"
        shared = shared_content_tokens(q1, q2)
        assert {"donald", "trump", "primary"} <= shared
        assert is_content_related(q1, q2)

    def test_min_shared_threshold_respected(self):
        # Exactly 2 shared content tokens — below DEFAULT_MIN_SHARED (3) → not related,
        # but related when the caller lowers the bar to 2.
        q1 = "Bitcoin Ethereum forecast"
        q2 = "Bitcoin Ethereum outlook"
        assert len(shared_content_tokens(q1, q2)) == 2
        assert not is_content_related(q1, q2, DEFAULT_MIN_SHARED)
        assert is_content_related(q1, q2, 2)

    def test_symmetry(self):
        a = "Will Donald Trump win the presidential primary in Iowa"
        b = "Will Donald Trump win the presidential primary in Texas"
        assert is_content_related(a, b) == is_content_related(b, a)
        assert is_content_related(a, b) is True


class TestTemplateFalsePositives:
    """Same-template/different-subject pairs must NOT be related (adversarial-audit class).

    The breadth of STOP_WORDS is what closes this: the template words (approval, rating,
    exceed, percent, December, stock, dollars, …) are filler, so two questions built from
    the same template share zero CONTENT tokens once their distinct subjects differ.
    """

    def test_biden_vs_macron_not_related(self):
        a = "Will Bidens approval rating exceed 50 percent by December?"
        b = "Will Macrons approval rating exceed 50 percent by December?"
        assert shared_content_tokens(a, b) == set()  # only bidens vs macrons survive
        assert not is_content_related(a, b)

    def test_bitcoin_vs_tesla_not_related(self):
        a = "Will Bitcoin exceed 100000 dollars before December 2026?"
        b = "Will Tesla stock exceed 500 dollars before December 2026?"
        assert not is_content_related(a, b)

    def test_inflation_vs_unemployment_not_related(self):
        a = "Will US inflation exceed 4 percent by June 2026?"
        b = "Will US unemployment exceed 5 percent by June 2026?"
        assert not is_content_related(a, b)

    def test_nationality_only_overlap_not_related(self):
        # "Chinese" is a nationality modifier (stop word), not a subject.
        a = "Will Chinese manufacturing output expand in the third quarter"
        b = "Will Chinese consumer spending expand in the third quarter"
        assert "chinese" not in shared_content_tokens(a, b)
        assert not is_content_related(a, b)

    def test_acronym_subject_pairs_correctly(self):
        # Short acronym subjects (NBA, Fed) are NOT dropped — they are content tokens of
        # length >= 3? No: the length floor is 4, so genuinely-related markets must share
        # OTHER content too. Here championship/finals/deciding carry the relatedness.
        a = "Will the championship finals reach a seventh deciding contest"
        b = "Will the championship finals avoid a seventh deciding contest"
        assert is_content_related(a, b)

    def test_same_subject_different_threshold_still_related(self):
        # Same subject (Bitcoin), different numeric threshold → genuinely related.
        a = "Will Bitcoin settle above 100000 on the Coinbase platform feed"
        b = "Will Bitcoin settle above 150000 on the Coinbase platform feed"
        shared = shared_content_tokens(a, b)
        assert "bitcoin" in shared and "coinbase" in shared
        assert is_content_related(a, b)
