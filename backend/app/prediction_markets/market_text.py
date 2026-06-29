"""
market_text.py — shared, hardened text matching for cross-market alphas (ROADMAP B5).

WHY THIS EXISTS
The cross-market logical-consistency alphas (``CrossMarketArbitrageStrategy`` Phase-2
keyword heuristic, ``LogicalImplicationDetector`` keyword-overlap discovery) decide
whether two markets are "related enough" to be compared for a probability-axiom
violation by counting SHARED WORDS between their question strings. The original screens
used a tiny 12-word skip set (``CrossMarketArbitrageStrategy``) and a length-3 token
filter — so they fired on FILLER words. An adversarial audit (RESEARCH_MEMORY 2026-06-29)
proved this: a first cut of the audit harness injected identical boilerplate
("Market {id} (real sample)") into every record, and the "3+ shared non-trivial words"
screen spuriously paired ~98 completely unrelated market pairs ("phantom signals"),
because filler tokens like ``real``/``sample``/``market`` passed the weak skip set. A
later audit found a second class: questions built from the SAME TEMPLATE but about
different subjects (*"Will Biden's approval exceed 50%"* vs *"Will Macron's approval
exceed 50%"*) shared their template words and so were also wrongly paired.

A spurious pairing is not harmless: it manufactures a fake "inconsistency" signal between
unrelated markets, which (if ever sized) is a real losing trade on noise.

WHAT THIS MODULE PROVIDES (one hardened definition, used by both strategies)
  * ``STOP_WORDS`` — a comprehensive set: English function words PLUS prediction-market
    boilerplate, threshold/comparison verbs ("exceed", "above"), quantity/currency units
    ("percent", "dollars"), generic metric nouns ("approval", "rating", "value"), venue /
    nationality / role modifiers ("nasdaq", "chinese", "president"), and month names. The
    KEY insight that closes the "same template, different subject" hole: the template
    words ARE the filler. Once "approval/rating/exceed/percent/December" are stop words,
    *"Bidens approval rating exceed 50 percent December"* and the Macron version share
    ZERO content tokens — only the distinct subjects (bidens vs macrons) survive, and they
    differ, so the pair is correctly rejected without any fragile entity detection.
  * ``content_tokens(text)`` — lowercase, tokenise on word boundaries, drop stop words and
    tokens shorter than ``MIN_TOKEN_LEN`` (4) and purely-numeric tokens.
  * ``shared_content_tokens(a, b)`` — the intersection of the two markets' content tokens.
  * ``is_content_related(a, b, min_shared)`` — the screen: ``True`` iff the two questions
    share at least ``min_shared`` (default 3) content tokens.

HONEST SCOPE / LIMITATIONS (this is a heuristic, not a classifier)
This screen is deliberately CONSERVATIVE — it raises the bar to pair markets, trading a
few true positives for far fewer phantom pairings (the safe direction: a missed weak
keyword hint is cheap; a fabricated cross-market signal on noise is a real losing trade).
It is STRICTLY more conservative than the original screen (it never pairs anything the old
screen wouldn't have). It does NOT eliminate every false pairing: two genuinely unrelated
markets that coincidentally share 3+ substantive non-filler words (e.g. the same sector
jargon) can still pair. That residual is acceptable because this is a SECONDARY, low-
confidence path — the structured implication RULES and the threshold/entity discovery in
``LogicalImplicationDetector`` (which gates on extracted entities first) are the primary
signals, and a pairing here only becomes a trade after the price-gap, ``min_inconsistency``
and price-range filters and the cost model. We do not over-claim that it is exact.

Pure stdlib (``re``), deterministic, no side effects — trivially CI-importable and tested.
"""

from __future__ import annotations

import re
from typing import Set

# Minimum length for a token to be considered "content". Drops short filler such as
# "win", "the", "of", "bps", and bare two/three-letter noise that the old length-3 floor
# let through.
MIN_TOKEN_LEN = 4

# Default number of shared content tokens required to treat two markets as related.
# Kept at 3 (matching the historical "3+ shared words" intent) but now measured over
# CONTENT tokens, so it is strictly more conservative than the old screen.
DEFAULT_MIN_SHARED = 3

# Comprehensive stop-word set. A token here never counts as shared content even if it
# clears the length floor. The breadth is the whole point: prediction-market questions are
# templated, and the template words (verbs, units, metric nouns, venues, nationalities,
# months) are exactly what makes unrelated markets share tokens. Removing them leaves only
# the genuine SUBJECT/CONTENT words.
STOP_WORDS: frozenset[str] = frozenset(
    {
        # --- standard English function words (length >= 4; shorter ones are removed by
        #     the length floor) ---
        "will", "the", "and", "for", "this", "that", "with", "from", "not", "but",
        "what", "when", "who", "whom", "whose", "how", "why", "which", "where",
        "has", "have", "had", "been", "was", "were", "are", "does", "did", "doing",
        "before", "after", "above", "below", "more", "than", "then", "into", "over",
        "under", "between", "during", "while", "about", "against", "their", "there",
        "they", "them", "these", "those", "such", "each", "any", "all", "both",
        "some", "most", "other", "another", "able", "upon", "onto", "also", "very",
        "just", "only", "ever", "even", "many", "much", "would", "could", "should",
        "shall", "must", "might", "may", "still", "back", "next", "last", "first",
        # --- prediction-market / question boilerplate filler ---
        "market", "markets", "question", "questions", "resolve", "resolved",
        "resolution", "resolves", "outcome", "outcomes", "price", "prices",
        "probability", "prediction", "predict", "predicted", "bet", "bets", "trade",
        "trades", "trading", "contract", "contracts", "yes", "real", "sample", "test",
        "synthetic", "event", "events", "happen", "happens", "occur", "occurs",
        "reach", "reaches", "end", "date", "year", "years", "month", "week", "weeks",
        "day", "days", "time", "deadline", "session", "green", "close", "closes",
        "open", "opens",
        # --- threshold / comparison verbs that recur across unrelated markets ---
        "exceed", "exceeds", "exceeded", "hit", "hits", "cross", "crosses", "surpass",
        "surpasses", "drop", "drops", "fall", "falls", "rise", "rises", "increase",
        "increases", "decrease", "decreases", "expand", "expands", "grow", "grows",
        "win", "wins", "lose", "loses", "sign", "signs", "veto", "vetoes",
        # --- generic metric nouns / quantity / currency / unit filler ---
        "approval", "rating", "ratings", "percent", "percentage", "dollar", "dollars",
        "cents", "point", "points", "stock", "stocks", "shares", "share", "value",
        "level", "number", "total", "rate", "rates", "index", "mark",
        # --- venue / exchange / role / nationality modifiers (NOT a market's subject) ---
        "nasdaq", "nyse", "exchange", "president", "presidential", "senate", "governor",
        "national", "federal", "chinese", "french", "american", "european", "british",
        "russian", "german", "japanese", "indian", "global", "world",
        # --- month names (temporal filler — a shared month never implies relatedness) ---
        "january", "february", "march", "april", "june", "july", "august",
        "september", "october", "november", "december",
    }
)

# Pure-numeric tokens such as "2024" or "150". (The tokeniser already splits on commas
# and dots, so grouped numbers like "1,000" arrive pre-split as "1"/"000" — each then
# dropped by the length floor or this check.) Bare numbers coincidentally match across
# unrelated markets (every 2024 market shares "2024"), so they are not content tokens.
_NUMERIC_RE = re.compile(r"^\d[\d,\.]*$")
# Word-boundary tokeniser: ascii letters/digits runs (lowercased input).
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def content_tokens(text: str) -> Set[str]:
    """Return the set of CONTENT tokens in ``text``.

    A content token is a lowercase word-boundary token that is (a) at least
    ``MIN_TOKEN_LEN`` characters, (b) not in ``STOP_WORDS``, and (c) not a purely
    numeric token. Returns an empty set for ``None``/empty input.
    """
    if not text:
        return set()
    out: Set[str] = set()
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) < MIN_TOKEN_LEN:
            continue
        if tok in STOP_WORDS:
            continue
        if _NUMERIC_RE.match(tok):
            continue
        out.add(tok)
    return out


def shared_content_tokens(a: str, b: str) -> Set[str]:
    """Content tokens shared by both ``a`` and ``b`` (intersection)."""
    return content_tokens(a) & content_tokens(b)


def is_content_related(a: str, b: str, min_shared: int = DEFAULT_MIN_SHARED) -> bool:
    """True iff ``a`` and ``b`` share at least ``min_shared`` CONTENT tokens.

    The hardened replacement for the old "3+ shared non-trivial words" screen: filler,
    boilerplate, template words (threshold verbs, units, metric nouns, venues,
    nationalities, months) and bare numbers can no longer pair two unrelated markets,
    because they are not content tokens. Only genuine subject/content overlap counts.
    See the module docstring for the honest limitation (coincidental substantive overlap
    can still pair; this is a conservative SECONDARY screen, not an exact classifier).
    """
    return len(shared_content_tokens(a, b)) >= min_shared
