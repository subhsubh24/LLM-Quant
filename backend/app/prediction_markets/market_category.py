"""Deterministic market-category derivation for risk bucketing.

WHY THIS EXISTS (a confirmed live production bug — 2026-07-02):
The risk manager caps exposure *per category* (`max_category_exposure_usd`, default
$200) so the bot cannot over-concentrate in one correlated theme. But real Polymarket
Gamma markets ship an EMPTY top-level ``category`` field, so every market collapsed to
the ``"General"`` bucket — turning the per-category cap into a de-facto GLOBAL cap
*below* the real portfolio cap ($500). In the live forward-paper cycle this froze the
loop: 154/154 opportunities skipped with "Category 'General' exposure: $164.18 + $50 >
$200". The per-category correlation limit only works if markets actually get spread
across real categories.

This module derives a coarse but REAL category from the signals the parser already has —
the raw category (if the venue ever populates it), the market's ``tags`` list, and the
question text — mapping each market into a small fixed set of correlated buckets. The
granularity is deliberately COARSE: the goal is correlation-risk bucketing (don't pile
the whole bankroll into "Sports" or "Crypto"), NOT precise topic classification, so a
handful of broad buckets is exactly right — too-granular buckets (one per market) would
defeat the correlation cap entirely.

Pure + deterministic (no clock, no randomness, no I/O): same inputs -> same bucket, so
it never perturbs a backtest seed_hash and is trivially testable offline. It NEVER
invents a confident category it cannot support — an unclassifiable market honestly falls
through to ``"General"`` (the shared bucket), which is the correct conservative default
(those markets still share ONE cap rather than each getting a free unlimited bucket).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional

# Collapse every run of non-alphanumeric characters to a single space so keyword matching
# is punctuation-insensitive ("government?" == "government", "vs." == "vs", "$62,000" ==
# "62 000"). Applied identically to the text and each keyword so matching is uniform.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# The fixed set of correlation buckets. Coarse on purpose (see module docstring).
CATEGORY_CRYPTO = "Crypto"
CATEGORY_POLITICS = "Politics"
CATEGORY_ECONOMICS = "Economics"
CATEGORY_WEATHER = "Weather"
CATEGORY_ENTERTAINMENT = "Entertainment"
CATEGORY_SCIENCE_TECH = "ScienceTech"
CATEGORY_SPORTS = "Sports"
CATEGORY_GENERAL = "General"

# Canonical names we accept verbatim when a venue DOES populate a category/tag, mapping
# common venue spellings onto our bucket set. Lower-cased keys.
_CANONICAL_ALIASES = {
    "crypto": CATEGORY_CRYPTO,
    "cryptocurrency": CATEGORY_CRYPTO,
    "politics": CATEGORY_POLITICS,
    "political": CATEGORY_POLITICS,
    "elections": CATEGORY_POLITICS,
    "election": CATEGORY_POLITICS,
    "geopolitics": CATEGORY_POLITICS,
    "economics": CATEGORY_ECONOMICS,
    "economy": CATEGORY_ECONOMICS,
    "finance": CATEGORY_ECONOMICS,
    "business": CATEGORY_ECONOMICS,
    "weather": CATEGORY_WEATHER,
    "climate": CATEGORY_WEATHER,
    "entertainment": CATEGORY_ENTERTAINMENT,
    "pop culture": CATEGORY_ENTERTAINMENT,
    "movies": CATEGORY_ENTERTAINMENT,
    "music": CATEGORY_ENTERTAINMENT,
    "awards": CATEGORY_ENTERTAINMENT,
    "science": CATEGORY_SCIENCE_TECH,
    "tech": CATEGORY_SCIENCE_TECH,
    "technology": CATEGORY_SCIENCE_TECH,
    "ai": CATEGORY_SCIENCE_TECH,
    "space": CATEGORY_SCIENCE_TECH,
    "sports": CATEGORY_SPORTS,
    "sport": CATEGORY_SPORTS,
    "soccer": CATEGORY_SPORTS,
    "football": CATEGORY_SPORTS,
    "basketball": CATEGORY_SPORTS,
    "baseball": CATEGORY_SPORTS,
    "tennis": CATEGORY_SPORTS,
    "hockey": CATEGORY_SPORTS,
    "esports": CATEGORY_SPORTS,
}

# Ordered keyword rules over the combined (question + tags) text. ORDER MATTERS: the
# first bucket whose keywords match wins, so more-specific / less-ambiguous themes are
# checked before the broad "Sports" verbs (win/game/match) that would otherwise swallow
# e.g. "win the presidential election". Each entry is (bucket, keywords). Keywords are
# matched as whitespace-delimited substrings against a space-padded, lower-cased text so
# that "btc" does not match inside "arbtc" — see `_normalize` + `_match_keyword_rules`.
_KEYWORD_RULES = [
    (CATEGORY_CRYPTO, [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol", "dogecoin",
        "doge", "xrp", "ripple", "cardano", "altcoin", "stablecoin", "coinbase",
        "binance", "memecoin", "nft",
    ]),
    (CATEGORY_POLITICS, [
        "election", "elections", "president", "presidential", "senate", "senator",
        "congress", "governor", "primary", "parliament", "prime minister", "chancellor",
        "referendum", "impeach", "cabinet", "nominee", "nomination", "ballot",
        "democrat", "republican", "biden", "trump", "putin", "government", "coup",
        "sanction", "sanctions", "ceasefire", "war", "treaty",
    ]),
    (CATEGORY_ECONOMICS, [
        "fed", "federal reserve", "interest rate", "interest rates", "rate hike",
        "rate cut", "bps", "basis points", "inflation", "cpi", "gdp", "recession",
        "unemployment", "jobs report", "nonfarm", "tariff", "tariffs", "stock market",
        "s&p", "nasdaq", "dow", "earnings", "ipo",
    ]),
    (CATEGORY_WEATHER, [
        "weather", "temperature", "hurricane", "storm", "rainfall", "snowfall",
        "tornado", "heatwave", "degrees", "celsius", "fahrenheit", "climate",
    ]),
    (CATEGORY_ENTERTAINMENT, [
        "movie", "film", "box office", "oscar", "oscars", "academy award", "grammy",
        "emmy", "golden globe", "album", "billboard", "netflix", "celebrity",
        "rotten tomatoes", "streaming", "tour", "concert",
    ]),
    (CATEGORY_SCIENCE_TECH, [
        "spacex", "nasa", "rocket", "launch", "satellite", "gpt", "openai", "gemini",
        "llm", "artificial intelligence", " ai ", "vaccine", "fda", "clinical trial",
        "iphone", "apple event", "tesla", "quantum",
    ]),
    (CATEGORY_SPORTS, [
        "world cup", "fifa", "nba", "nfl", "nhl", "mlb", "ufc", "premier league",
        "champions league", "wimbledon", "atp", "wta", "olympics", "olympic",
        "super bowl", "playoff", "playoffs", "grand prix", "formula 1", "f1",
        "match", "tournament", "championship", "league", "vs", "defeat",
        "win the", "advance to", "score",
    ]),
]


def _normalize(text: str) -> str:
    """Lower-case, collapse punctuation to spaces, and pad with single spaces.

    The padding makes every real word space-bounded, so a whole-token / whole-phrase
    check (``f" {kw} " in normalized``) matches "eth" in "will eth flip" but NOT inside
    "ethereum" or "together", and a multi-word phrase like "world cup" only where those
    two tokens are adjacent.
    """
    return f" {_NON_ALNUM.sub(' ', text.lower()).strip()} "


def _match_keyword_rules(text: str) -> Optional[str]:
    padded = _normalize(text)
    for bucket, keywords in _KEYWORD_RULES:
        for kw in keywords:
            token = _normalize(kw).strip()
            if token and f" {token} " in padded:
                return bucket
    return None


def _normalize_known(value: str) -> Optional[str]:
    """Map a raw category/tag string onto a canonical bucket, or None if unknown."""
    key = (value or "").strip().lower()
    if not key:
        return None
    if key in _CANONICAL_ALIASES:
        return _CANONICAL_ALIASES[key]
    return None


def derive_market_category(
    question: str,
    raw_category: str = "",
    tags: Optional[Iterable[str]] = None,
) -> str:
    """Derive a coarse, deterministic correlation bucket for a market.

    Priority (first non-empty wins):
      1. An explicit ``raw_category`` the venue populated, if it maps to a known bucket.
      2. Any ``tag`` that maps to a known bucket (venue-provided taxonomy).
      3. A keyword scan of the question text (+ tags) into the fixed bucket set.
      4. ``"General"`` — the honest shared default for an unclassifiable market (it still
         shares ONE cap; it does NOT get a private unlimited bucket).

    NEVER fabricates a confident category: an empty/unknown input flows to ``"General"``.
    """
    tag_list: List[str] = [str(t) for t in (tags or []) if str(t).strip()]

    # 1. explicit raw category (only if it resolves to a known bucket — an unknown
    #    free-text category is treated as absent rather than trusted blindly).
    known = _normalize_known(raw_category)
    if known:
        return known

    # 2. venue tags mapped to a known bucket.
    for tag in tag_list:
        known = _normalize_known(tag)
        if known:
            return known

    # 3. keyword scan of question + tags.
    combined = " ".join([question or ""] + tag_list)
    matched = _match_keyword_rules(combined)
    if matched:
        return matched

    # 4. honest shared default.
    return CATEGORY_GENERAL
