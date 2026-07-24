"""
cross_venue_matcher.py — the cross-VENUE coherence edge (ROADMAP B8).

WHY THIS EXISTS (the edge thesis, per VISION)
When the SAME real-world event is priced differently on Polymarket vs. Kalshi, one
venue is wrong. Trading that disagreement is a **logical-consistency / arbitrage** edge
that does NOT require out-calibrating the crowd (unlike B4/B4a, which lost money OOS
against a sharp crowd): the two crowds can each be individually well-calibrated yet
INCONSISTENT with each other across venues. That makes this possibly the more *robust*
alpha — but it hinges entirely on one hard, adversarial problem: **event-matching**.

THE HARD PART — event-matching, done adversarially (the B5 lesson, cross-venue)
Deciding that a Polymarket market and a Kalshi market resolve on the SAME underlying
event is the whole game. A FALSE pairing is not harmless: it manufactures a fake
"disagreement" between two markets that actually resolve on DIFFERENT questions, and if
sized that is a real losing trade (and worse, the two legs can resolve OPPOSITELY — see
the risk note below). So the matcher is deliberately CONSERVATIVE and rejects, not pairs,
when it cannot confirm sameness. It layers three independent gates, each of which alone
kills a distinct class of false pairing that a naive "same words" screen would accept:

  1. **Content overlap** (reuses the hardened B5 ``market_text`` primitive) — rejects the
     "same template, different subject" trap (*"Will Biden's approval exceed 50%?"* vs the
     Macron version share ZERO content tokens) and obvious unrelated pairs.
  2. **Numeric-threshold consistency** — rejects the "same subject, different strike"
     trap (*"BTC above $100k"* vs *"BTC above $90k"*; *"approval > 50%"* vs *"> 55%"*),
     INCLUDING the comparator DIRECTION (*"above 50%"* vs *"below 50%"* is not the same
     event). Extraction is confidence-gated: an ambiguous string (0 or >1 numeric
     thresholds) yields "no confident threshold" rather than a fabricated one.
  3. **Resolution-timeframe overlap** — rejects the "same question, different window"
     trap (*"BTC above $100k by Dec 2026"* vs *"...by Jun 2026"*): the two ``end_date``s
     must fall within ``max_days_apart``. If EITHER end_date is missing we cannot confirm
     the window, so we REJECT (conservative: never pair on an unverifiable timeframe).

The boolean MATCH answers "could these be the same event?"; a separate, bounded
``coherence_score`` ∈ [0, 1] answers "how CONFIDENT are we?" (more shared content, a
matched explicit threshold, and closer resolution dates → higher). The backtest/caller
only ever trades a match whose ``coherence_score >= min_coherence`` — so the weak,
no-threshold, bare-token-overlap pairings never become trades on their own.

THE COHERENCE TRADE + its cost model
For two matched BINARY markets with YES prices ``p_a`` (venue A) and ``p_b`` (venue B),
buy YES on the cheaper venue and NO on the dearer one. At resolution exactly one leg pays
$1 **iff both venues resolve the same way**, so the pair costs
``eff(p_cheap_yes) + eff(1 - p_dear_yes)`` and returns $1 — a net edge only when the
disagreement exceeds the round-trip cost of BOTH venues' fees+slippage. If the venues
AGREE (``p_a == p_b``) the two effective costs sum to ``(1+slip)(1+fee) > 1`` → negative
edge, so an efficient cross-venue market is correctly never traded (no fabricated edge).

THE RISK THAT MAKES THE MATCHER LOAD-BEARING (disclosed, not hidden)
This is NOT locked arbitrage. If a *falsely-matched* pair resolves OPPOSITELY (event A
YES while event B NO), the "buy YES on A + NO on B" position pays $0 and loses the whole
stake. That downside is exactly why the matcher must be strict — the edge is only real to
the extent the two markets are genuinely the same event. We also inherit the standing
prediction-market caveats: prices here are venue MIDPOINTS, not executable asks (a fired
match is a candidate to verify against live depth, not locked profit), and per-venue
liquidity/impact is not modeled. So a fired match is a *screen*, never a booked profit.

SCOPE (DECISION COROLLARY — do NOT wire live until proven)
This module is the MATCHER + a deterministic, cost-net coherence primitive + an
offline evaluation over RESOLVED matched pairs (the backtest half). It is pure stdlib +
``cost_model`` + the ``Market`` model + ``market_text`` — no network, no orchestrator, no
executor. Per the DECISION COROLLARY we build the matcher + backtest FIRST; live routing
is far downstream and gated on real data from BOTH venues, realistic per-venue costs, and
an OOS edge ≥ floor that ≥3 adversarial auditors cannot break. Nothing here ticks a
DoD/floor box — it is infrastructure for a *candidate* edge, not a validated edge.

Deterministic, side-effect-free, trivially CI-importable and fixture-tested.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from .cost_model import DEFAULT_COST_MODEL, CostModel
from .market_text import content_tokens
from .polymarket_client import Market

# --------------------------------------------------------------------------- #
# Tunable defaults (single source of truth; deterministic).                    #
# --------------------------------------------------------------------------- #

# Minimum shared CONTENT tokens (B5 ``market_text`` definition) for two markets to be
# considered plausibly-related. Cross-venue phrasing differs, so this is the NECESSARY
# screen, not the whole decision — the threshold + timeframe gates add the discrimination.
DEFAULT_MIN_SHARED_CONTENT = 2

# Maximum days between the two venues' resolution dates to accept them as the same window.
# Two venues often close a market at slightly different times for the same event; a few
# days' tolerance is realistic, a few WEEKS is a different event.
DEFAULT_MAX_DAYS_APART = 4.0

# Relative tolerance when comparing two extracted numeric strikes of the SAME unit. It
# must ONLY absorb true format/rounding differences ($100k vs $100,000 vs $100000 all
# normalise to the identical float 100000.0), NOT ADJACENT STRIKES — an adversarial audit
# showed a 2% relative tolerance fabricated a "disagreement" between `>50%` and `>51%` (or
# $100k vs $102k), which are DIFFERENT events pricing coherently, not a venue mismatch.
# Near-exact (float-rounding only): 50 vs 51 → reject; 100000 vs 100001 → reject.
_THRESHOLD_REL_TOL = 1e-6

# When NEITHER market yields a confident numeric strike, the pairing rests on content-token
# overlap alone — plausible but NOT confident enough to size. Its coherence is hard-capped
# strictly BELOW ``DEFAULT_MIN_COHERENCE`` so it is SURFACED but never traded on its own
# (the module contract: "the weak, no-threshold, bare-token-overlap pairings never become
# trades"). This also closes the spelled-out-number hole ("two hundred thousand" yields no
# digit strike → both sides None → must not reach the trade bar via content score alone).
_NO_THRESHOLD_COHERENCE_CAP = 0.45

# Minimum coherence score for the backtest/caller to actually TRADE a match. Below this a
# pairing is "plausible but not confident" and is surfaced but never sized.
DEFAULT_MIN_COHERENCE = 0.5
assert _NO_THRESHOLD_COHERENCE_CAP < DEFAULT_MIN_COHERENCE  # no-threshold pairs never trade by default

# Negation words that INVERT a comparator's direction when they bind it: "no more than X"
# means ≤ X (down), not "more" (up); "no fewer than X" means ≥ X (up). Without this a
# negated bound is read as its opposite and pairs two OPPOSITE-meaning markets as the same
# event (the resolution-divergence risk this module exists to prevent).
_NEGATIONS = frozenset(
    {"no", "not", "never", "cannot", "cant", "wont", "dont", "doesnt", "isnt", "arent"}
)


# --------------------------------------------------------------------------- #
# Numeric-threshold extraction (confidence-gated).                             #
# --------------------------------------------------------------------------- #

# Comparator words → normalized DIRECTION. "above 50%" and "below 50%" are NOT the same
# event, so direction is part of the threshold identity.
_UP_WORDS = frozenset(
    {"above", "over", "exceed", "exceeds", "exceeded", "greater", "more", "least",
     "atleast", "surpass", "surpasses", "top", "reach", "reaches", "hit", "hits",
     "higher", "minimum"}
)
_DOWN_WORDS = frozenset(
    {"below", "under", "less", "fewer", "lower", "most", "atmost", "beneath",
     "maximum"}
)

# Filler words a comparator may reach across to bind a number ("at least the 50%"), but
# which do not themselves stop the search. Anything NOT here (a content word or a number)
# breaks the comparator→number chain.
_COMPARATOR_CONNECTORS = frozenset(
    {"the", "a", "an", "at", "to", "of", "in", "on", "by", "than", "or", "and", "be",
     "is", "are", "will", "stay", "remain", "close", "trade", "price"}
)

# A numeric token with an optional currency prefix and an optional magnitude/percent
# suffix: $100k, 100,000, 50%, 3.5, 1.2bn, 90000. Captured groups: (sign?) number, suffix.
_NUM_RE = re.compile(
    r"(?P<cur>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?"
    r"(?P<suf>%|k|m|bn|b|mm|thousand|million|billion)?(?![a-z])",
    re.IGNORECASE,
)

_SUFFIX_MULT = {
    "k": 1_000.0, "thousand": 1_000.0,
    "m": 1_000_000.0, "mm": 1_000_000.0, "million": 1_000_000.0,
    "b": 1_000_000_000.0, "bn": 1_000_000_000.0, "billion": 1_000_000_000.0,
}


@dataclass(frozen=True)
class Threshold:
    """A single, confidently-extracted numeric threshold from a market question.

    ``value`` is the magnitude-normalized number (``$100k`` → 100000.0, ``50%`` → 50.0).
    ``unit`` is a coarse class — ``"percent"``, ``"currency"``, or ``"plain"`` — so a 50%
    threshold never matches a $50 threshold. ``direction`` is ``"up"`` / ``"down"`` /
    ``"none"`` (no comparator word found near the number).
    """

    value: float
    unit: str
    direction: str

    def matches(self, other: "Threshold", rel_tol: float = _THRESHOLD_REL_TOL) -> bool:
        """True iff same unit, same direction (or one side is directionless), and the
        magnitudes agree within ``rel_tol`` (relative)."""
        if self.unit != other.unit:
            return False
        if self.direction != other.direction and "none" not in (self.direction, other.direction):
            return False
        scale = max(abs(self.value), abs(other.value), 1e-9)
        return abs(self.value - other.value) / scale <= rel_tol


def _normalize_number(num: str, suf: Optional[str], cur: Optional[str]) -> Tuple[float, str]:
    """(magnitude, unit-class) from a regex-captured number + suffix + currency prefix."""
    base = float(num.replace(",", ""))
    suf_l = (suf or "").lower()
    if suf_l == "%":
        return base, "percent"
    mult = _SUFFIX_MULT.get(suf_l, 1.0)
    value = base * mult
    unit = "currency" if cur else "plain"
    return value, unit


_PERCENT_TAIL_RE = re.compile(r"\s*(percent|percentage|pct)\b")


def extract_threshold(text: str) -> Optional[Threshold]:
    """Extract a SINGLE confident numeric STRIKE, or ``None`` if absent/ambiguous.

    The core problem is separating the market's STRIKE (``$100k``, ``50%``, ``above 3``)
    from incidental DATE/COUNT numbers (``Dec 31``, ``2026``, ``12-31``) that pollute any
    naive number scan. Rule (never fabricate a threshold):

      * a number is a STRIKE CANDIDATE only if it carries a UNIT — a ``$`` prefix, a
        magnitude suffix (``k``/``m``/``bn``), or a following ``percent`` word — OR a
        comparator word (``above``/``below``/``exceed``/...) directly precedes it. Bare
        unitless numbers with no comparator (day-of-month, years, plain counts) are
        IGNORED, so a date can never be mistaken for a strike;
      * a bare year (plain integer in [1900, 2099]) is always ignored;
      * ZERO candidates → ``None`` (no strike); MORE THAN ONE → ``None`` (ambiguous —
        we refuse to guess which defines the market). Exactly one → that threshold.

    Direction comes from the nearest preceding comparator; ``"none"`` if absent (a unit-
    bearing number with no comparator is still a strike — e.g. a bare ``$100k``).
    """
    if not text:
        return None
    lowered = text.lower()
    candidates: List[Threshold] = []
    for m in _NUM_RE.finditer(lowered):
        num, suf, cur = m.group("num"), m.group("suf"), m.group("cur")
        value, unit = _normalize_number(num, suf, cur)
        # A trailing "percent"/"pct" word makes a plain number a percent strike (so
        # "50 percent" matches "50%").
        if unit == "plain" and _PERCENT_TAIL_RE.match(lowered[m.end():]):
            unit = "percent"
        # Direction from the nearest preceding comparator — but only one that BINDS this
        # number: walk back over connector filler ("the"/"on"/"by"/...) and STOP at the
        # first comparator (up/down) OR the first intervening NUMBER. Stopping at a number
        # is what prevents "above $100000 on 2026-12-31" from binding "above" to the "12"
        # (the "$100000" between them breaks the chain).
        # Apostrophes are stripped FIRST so contractions tokenize to their negation form
        # ("won't"→"wont") — otherwise "[a-z]+" splits "won't"→["won","t"].
        prefix = lowered[: m.start()].replace("'", "").replace("’", "")
        prefix_tokens = re.findall(r"[a-z]+|\d[\d,\.]*", prefix)
        direction = "none"
        negated = False
        for i in range(len(prefix_tokens) - 1, -1, -1):
            w = prefix_tokens[i]
            if w in _UP_WORDS or w in _DOWN_WORDS:
                direction = "up" if w in _UP_WORDS else "down"
                # NEGATION handling — the SAFE way. Correctly INVERTING a negated bound
                # ("no more than" = ≤) is a regex rabbit hole: two prior audits showed both
                # a MISSED inversion (contractions) and — worse — a SPURIOUS inversion
                # (a negation from a different clause, "no layoffs and unemployment above
                # 4%", flipping "above" and fabricating a match with "below 4%"). So we do
                # NOT try to guess the true direction: if a negation plausibly binds this
                # comparator, the strike's direction is UNRELIABLE and we VOID the strike
                # (below). This is TIGHTENING-ONLY — a voided strike yields "no confident
                # threshold", which can only cause a conservative reject / no-trade, NEVER a
                # spurious match. A negated market is honestly surfaced (no threshold), never
                # falsely paired. Generous detection is safe precisely because a false
                # positive here only removes a match.
                for j in range(i - 1, max(-1, i - 6), -1):
                    tj = prefix_tokens[j]
                    if tj in _NEGATIONS:
                        negated = True
                        break
                    if tj in _UP_WORDS or tj in _DOWN_WORDS or tj[:1].isdigit():
                        break
                break
            if w in _COMPARATOR_CONNECTORS:
                continue
            break  # a non-connector, non-comparator token (incl. a number) breaks the chain
        if negated:
            # A negated comparator → direction unreliable → not a confident strike. Skip it
            # (if it was the only number, extract_threshold returns None → the pair is
            # rejected as one-sided or falls to the un-tradeable no-threshold cap).
            continue
        has_unit = unit in ("percent", "currency") or suf is not None
        # Drop bare years (a date, not a strike): plain, no unit, integer in [1900, 2099].
        if not has_unit and value.is_integer() and 1900 <= value <= 2099:
            continue
        # A unitless number is only a strike if a comparator binds it; otherwise it is a
        # date/count/noise and is ignored (this is what keeps "Dec 31" out).
        if not has_unit and direction == "none":
            continue
        candidates.append(Threshold(value=value, unit=unit, direction=direction))
    if len(candidates) != 1:
        return None  # zero → no strike; >1 → ambiguous, refuse to guess
    return candidates[0]


# --------------------------------------------------------------------------- #
# Structured strike (ROADMAP B8).                                              #
# --------------------------------------------------------------------------- #

# Kalshi ``strike_type`` values that define a single directional strike. A ">="/">"
# strike is bounded BELOW by ``floor_strike`` (resolves YES when the value is at/above it
# → direction "up"); a "<="/"<" strike is bounded ABOVE by ``cap_strike`` (resolves YES
# below it → direction "down"). A "between"/range strike (both bounds) is NOT a single
# strike and yields no confident threshold (refuse to guess which bound defines it).
_GREATER_STRIKE_TYPES = frozenset({"greater", "greater_or_equal", "gte", "gt"})
_LESS_STRIKE_TYPES = frozenset({"less", "less_or_equal", "lte", "lt"})

# A currency cue in the market's OWN text — the only signal we trust to call a structured
# strike "currency" (the structured fields carry a bare number, no unit). Conservative by
# design: no cue → "plain", which can only REMOVE a match, never fabricate one.
_CURRENCY_CUE_RE = re.compile(r"\$|\busd\b|\bdollar|\bprice\b")


def _infer_structured_unit(market: "Market") -> str:
    """Coarse unit class for a STRUCTURED strike, read ONLY from an explicit cue in the
    market's own title/category — never assumed.

    The structured strike fields carry only a NUMBER, not a unit, so pairing a Kalshi
    strike against a Polymarket ``$``-denominated threshold needs to know whether the
    number is dollars, a percent, or a plain count. We take that ONLY from an unambiguous
    cue in the market's own text, so a non-price strike (temperature, index level, vote
    count) stays ``"plain"`` and can NEVER spuriously match a ``"currency"`` market. This
    is tightening-only: a conservative "plain" only removes a match, never fabricates one.

    Reads ``question`` when present (a live ``Market``) else ``title`` (a
    ``KalshiResolvedMarket`` from the history fetcher), so the SAME structured-strike unit
    inference works on both the LIVE and the RESOLVED-history paths — the B8 historical
    co-listed corpus needs the resolved records to yield the same threshold the live ones do.
    """
    market_text = getattr(market, "question", None) or getattr(market, "title", "")
    text = f"{market_text} {getattr(market, 'category', '')}".lower()
    if "%" in text or "percent" in text:
        return "percent"
    if _CURRENCY_CUE_RE.search(text):
        return "currency"
    return "plain"


def _is_finite_number(x) -> bool:
    """True iff ``x`` is a real, finite int/float. Type-safe: a non-numeric value (e.g. a
    raw string that skipped ``_to_float``) returns False rather than raising, so the
    docstring's 'a non-finite value yields None' holds even if ``Market`` is constructed
    from unsanitized structured fields somewhere other than ``kalshi_client._parse_market``.
    """
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def extract_threshold_from_structured_strike(market: "Market") -> Optional[Threshold]:
    """Extract a :class:`Threshold` from a venue's STRUCTURED strike fields
    (``floor_strike`` / ``cap_strike`` / ``strike_type``), or ``None``.

    Kalshi crypto/scalar markets carry a GENERIC title ("Bitcoin price on Jul 20, 2026?")
    so :func:`extract_threshold` (title-text) returns None, while the real strike lives
    ONLY in the structured fields. This reads that structured strike so such a market can
    pair against a Polymarket market whose strike IS in its title. It NEVER fabricates a
    pairing: a range strike ("between", both bounds present), a missing/unknown/functional
    ``strike_type``, a bound-less directional type, or a non-finite value all yield
    ``None`` (refuse to guess).

    CRITICAL — refuses a ``"plain"`` (unit-less) strike. The structured fields carry only a
    NUMBER, so a strike whose market text gives no currency/percent cue has no confident
    unit. A bare-number "plain" threshold would let a magnitude-only coincidence license a
    match (e.g. a Kalshi "hashrate ≥ 95000" pairing a Polymarket "forum members > 95000"
    on the shared token "bitcoin") — a FABRICATED cross-venue disagreement, the cardinal
    sin. B8's target markets (crypto/price) always carry a ``$``/``price`` cue →
    ``"currency"``, so refusing ``"plain"`` loses no target coverage and closes the hole
    (tightening-only). Only a ``currency`` or ``percent`` structured strike yields a
    threshold.

    NOTE (semantic scope, ROADMAP B8 step iii — NOW BUILT): a returned threshold is a
    same-STRIKE candidate. The resolution MECHANIC (Kalshi KXBTCMAXY barrier / daily-terminal
    vs. Polymarket touch) is classified separately by :func:`classify_resolution_mechanic`
    and enforced in :func:`match_markets`: a CONFIDENT touch-vs-terminal conflict is rejected,
    and every surviving match carries ``mechanic_confirmed`` so an OOS/edge claim can require
    both legs share a known mechanic (``evaluate_cross_venue_pairs(require_mechanic_confirmed=True)``).
    A same-strike pair with an unclassifiable mechanic is admitted but flagged, never silently
    treated as semantically confirmed.
    """
    strike_type = getattr(market, "strike_type", None)
    if not strike_type:
        return None
    st = str(strike_type).lower().strip()
    floor = getattr(market, "floor_strike", None)
    cap = getattr(market, "cap_strike", None)
    unit = _infer_structured_unit(market)
    if unit == "plain":
        # No confident unit signal → refuse (do not license a magnitude-only match).
        return None
    if st in _GREATER_STRIKE_TYPES and _is_finite_number(floor):
        return Threshold(value=float(floor), unit=unit, direction="up")
    if st in _LESS_STRIKE_TYPES and _is_finite_number(cap):
        return Threshold(value=float(cap), unit=unit, direction="down")
    # "between"/range, "functional"/"custom"/"structured"/"unknown", or a directional
    # type with its defining bound absent → no confident single strike.
    return None


# --------------------------------------------------------------------------- #
# Resolution-mechanic classifier (ROADMAP B8 step iii — the touch/barrier/terminal gate). #
# --------------------------------------------------------------------------- #
# Two markets on the SAME strike can still resolve OPPOSITELY if they resolve on a
# DIFFERENT MECHANIC. A TOUCH / BARRIER market ("does BTC EVER reach $100k during the
# window", Kalshi ``KXBTCMAXY``/``KXBTCMINY``) resolves YES the instant the strike is
# touched; a TERMINAL market ("is BTC above $100k AT the close/expiry", Kalshi daily-close
# series) resolves on the value at a SINGLE instant. A barrier that is touched then retraces
# resolves YES while the co-strike terminal resolves NO — so a same-strike pair whose
# mechanics DIFFER is NOT the same event and, sized, is exactly the OPPOSITELY-resolving
# false pairing the module docstring warns is the cardinal risk.
#
# This is a CONSERVATIVE classifier: it returns ``"touch"``, ``"terminal"``, or
# ``"unknown"`` and is used TIGHTENING-ONLY. Only a CONFIDENT ``touch`` vs ``terminal``
# conflict HARD-REJECTS a pair; an ``"unknown"`` on either side (neither cue found, OR BOTH
# cues found = genuinely ambiguous) NEVER hard-rejects — instead the pair is admitted with
# ``mechanic_confirmed=False`` so a downstream edge-claim consumer can require BOTH legs be
# the SAME known mechanic before trading (``evaluate_cross_venue_pairs(require_mechanic_
# confirmed=True)``). So a same-strike pair that clears the matcher is no longer a
# SEMANTICALLY-UNCLASSIFIED candidate silently — its mechanic status is explicit.
TOUCH_MECHANIC = "touch"
TERMINAL_MECHANIC = "terminal"
UNKNOWN_MECHANIC = "unknown"

# UNAMBIGUOUS touch/barrier text cues — an explicit intraday-PATH word that means "reached at
# any instant during the window" regardless of the underlying. These are barrier cues for ANY
# unit. Deliberately OMITS bare "high"/"low" (false positives — "record high unemployment").
_UNAMBIGUOUS_TOUCH_RE = re.compile(
    r"\b(ever|touch(?:es|ed|ing)?|intraday|at any (?:point|time)|any\s?time)\b",
    re.IGNORECASE,
)
# COLLOQUIAL barrier verbs / extremum words. For a CONTINUOUS-PRICE (currency) underlying these
# are genuine barrier cues (BTC "reaches"/"hits" $100k, its "maximum" over the year). But for a
# DISCRETE TERMINAL statistic (a monthly econ print, a vote count) "unemployment HIT 5%" reads
# as TERMINAL, not an intraday barrier — so these fire as touch ONLY when the strike unit is
# currency (adversarial-auditor finding: colloquial verbs over-classified terminal-only
# underlyings as touch and manufactured a false conflict). This also removes the bare "max"/"min"
# proper-noun false positive (a name like "Max" carries no currency strike, so it never fires).
_PRICE_CONTEXT_TOUCH_RE = re.compile(
    r"\b(reach(?:es|ed|ing)?|hit(?:s|ting)?|max(?:imum)?|min(?:imum)?|peak)\b",
    re.IGNORECASE,
)
# TERMINAL text cues — resolution at a single instant (close/expiry/settlement/end). Deliberately
# OMITS the generic "as of" (an "as of <date>" window phrase is not reliably a terminal-mechanic
# cue — keeping it risked a false terminal that manufactured a conflict).
_TERMINAL_MECHANIC_RE = re.compile(
    r"\b(clos(?:e|es|ed|ing)|settl(?:e|es|ed|ement)|expir(?:y|ation|es|ed)|"
    r"end of (?:day|the day|the month|the year|month|year)|at the end|"
    r"final\s+(?:value|price|level))\b",
    re.IGNORECASE,
)
# Kalshi STRUCTURED barrier hint: a MAX/MIN series ticker (KXBTCMAXY / KXBTCMINY / *MAX / *MIN)
# is an extremum-over-window = barrier, stronger than free text. Matched on the ticker only.
_KALSHI_BARRIER_TICKER_RE = re.compile(r"(?:MAX|MIN)[A-Z]?\b", re.IGNORECASE)


def _market_ticker_text(market: "Market") -> str:
    """Concatenated Kalshi ticker/series-ticker text (lower-cased), or "" — used only for the
    structured barrier hint. Polymarket markets carry no ticker, so this is "" for them."""
    parts = []
    for attr in ("ticker", "series_ticker"):
        v = getattr(market, attr, None)
        if v:
            parts.append(str(v))
    return " ".join(parts)


def classify_resolution_mechanic(market: "Market") -> str:
    """Classify how a market RESOLVES: ``"touch"`` (barrier — YES if the strike is ever
    reached during the window), ``"terminal"`` (YES on the value at close/expiry), or
    ``"unknown"`` (no confident cue, or genuinely ambiguous both-cues text).

    Pure + deterministic (regex over the question text + any Kalshi ticker). CONSERVATIVE:
    when both a touch and a terminal cue appear it returns ``"unknown"`` rather than guessing,
    so an ambiguous market never manufactures a mechanic conflict.
    """
    text = str(getattr(market, "question", "") or "")
    ticker = _market_ticker_text(market)
    # Unconditional path words + the Kalshi MAX/MIN barrier ticker are touch for any unit.
    touch = bool(_UNAMBIGUOUS_TOUCH_RE.search(text)) or bool(_KALSHI_BARRIER_TICKER_RE.search(ticker))
    # Colloquial barrier verbs (reach/hit/max/min/peak) are touch ONLY for a continuous-price
    # (currency) underlying — for a terminal-only percent/plain statistic they read as terminal.
    if not touch and _PRICE_CONTEXT_TOUCH_RE.search(text):
        thr = extract_threshold(text) or extract_threshold_from_structured_strike(market)
        if thr is not None and thr.unit == "currency":
            touch = True
    terminal = bool(_TERMINAL_MECHANIC_RE.search(text))
    if touch and not terminal:
        return TOUCH_MECHANIC
    if terminal and not touch:
        return TERMINAL_MECHANIC
    # neither cue (no signal) OR both cues (ambiguous) → not confidently classified.
    return UNKNOWN_MECHANIC


def _threshold_for(market: "Market") -> Optional[Threshold]:
    """The market's confident strike: its TITLE-TEXT threshold if present, else its
    STRUCTURED strike (Kalshi ``floor_strike``/``strike_type``).

    Title text wins when both exist — a human-readable, already unit-typed strike is the
    stronger, more directly verifiable signal. The structured fallback fires only for the
    generic-title case that title parsing cannot cover, so behavior is IDENTICAL to the
    prior title-only matcher for every market that has no structured strike (all
    Polymarket markets, and any Kalshi market without these fields).
    """
    thr = extract_threshold(market.question)
    if thr is not None:
        return thr
    return extract_threshold_from_structured_strike(market)


# --------------------------------------------------------------------------- #
# The match.                                                                   #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CrossVenueMatch:
    """A confirmed same-event pairing across two venues (venue-agnostic A/B).

    ``yes_price_a`` / ``yes_price_b`` are the YES midpoints on each venue at match time.
    ``coherence_score`` ∈ [0, 1] is the CONFIDENCE (not the edge) — trade only when it
    clears ``min_coherence``. Frozen + hashable so a set of matches is deterministic.
    """

    market_a_id: str
    market_b_id: str
    question_a: str
    question_b: str
    shared_tokens: frozenset
    threshold: Optional[Threshold]
    yes_price_a: float
    yes_price_b: float
    end_date_a: Optional[datetime]
    end_date_b: Optional[datetime]
    coherence_score: float
    # Resolution-mechanic classification of each leg (ROADMAP B8 step iii). A pair with a
    # CONFIDENT touch-vs-terminal conflict never reaches here (match_markets returns None),
    # so these are either equal-and-known (``mechanic_confirmed=True``) or carry an
    # ``"unknown"`` on at least one side (``mechanic_confirmed=False`` — a semantically
    # unclassified candidate a downstream edge claim must still gate). Defaulted so the
    # backtest half and existing constructions are unchanged.
    mechanic_a: str = UNKNOWN_MECHANIC
    mechanic_b: str = UNKNOWN_MECHANIC
    mechanic_confirmed: bool = False


def _yes_price(market: Market) -> Optional[float]:
    """The YES-outcome midpoint of a binary market, or ``None`` if not a clean binary
    OR not currently tradeable.

    The ``active`` gate is load-bearing on REAL data: a venue that cannot quote a market
    (e.g. a Kalshi market with no bid/ask/last book) presents a NEUTRAL PLACEHOLDER price
    (0.50) and marks the market ``active=False`` — the data analog of a fake fill (the
    #101/#102/#193 honesty rule). Without this gate the matcher reads that fabricated 0.50
    and can manufacture a bogus cross-venue "disagreement" against a real market. Gating on
    ``active`` also correctly refuses a RESOLVED market (whose price has settled to ~1/0),
    so only genuinely tradeable, real-quote markets ever enter a coherence pairing. (The
    RESOLVED-pair backtest builds ``CrossVenueMatch`` directly from pre-resolution snapshot
    prices and never routes through this function, so it is unaffected.)
    """
    if not getattr(market, "is_binary", False):
        return None
    if not getattr(market, "active", False):
        return None
    for o in market.outcomes:
        if str(o.label).strip().lower() in ("yes", "y"):
            return float(o.price)
    # Fall back to the first outcome if labels are non-standard but there are exactly two.
    if len(market.outcomes) == 2:
        return float(market.outcomes[0].price)
    return None


def _days_apart(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 86400.0


def match_markets(
    market_a: Market,
    market_b: Market,
    *,
    min_shared_content: int = DEFAULT_MIN_SHARED_CONTENT,
    max_days_apart: float = DEFAULT_MAX_DAYS_APART,
) -> Optional[CrossVenueMatch]:
    """Decide whether two markets (one per venue) resolve on the SAME event.

    Returns a :class:`CrossVenueMatch` if ALL hard gates pass, else ``None``. The gates,
    each killing a distinct false-pairing class (see the module docstring):

      * both are clean BINARY markets with a readable YES price;
      * they share ``>= min_shared_content`` B5 content tokens;
      * their numeric thresholds are consistent — if BOTH have a confident threshold they
        must match (magnitude + unit + direction); if EXACTLY ONE has a threshold the
        pairing is REJECTED (a specificity mismatch — one market is strike-defined, the
        other is not); if NEITHER has one, the pairing rests on content overlap alone and
        is admitted but scored lower. Each side's threshold comes from :func:`_threshold_for`
        — its TITLE text if parseable, else its STRUCTURED strike (Kalshi
        ``floor_strike``/``strike_type``), so a generic-title Kalshi market no longer fails
        the specificity gate against a title-strike Polymarket market (ROADMAP B8);
      * their resolution windows overlap (``end_date`` within ``max_days_apart``); a
        missing end_date on either side REJECTS (window unverifiable).
    """
    price_a = _yes_price(market_a)
    price_b = _yes_price(market_b)
    if price_a is None or price_b is None:
        return None

    thr_a = _threshold_for(market_a)
    thr_b = _threshold_for(market_b)
    if thr_a is not None and thr_b is not None:
        if not thr_a.matches(thr_b):
            return None
        matched_threshold: Optional[Threshold] = thr_a
    elif (thr_a is None) != (thr_b is None):
        # Exactly one side is strike-defined → different specificity → not the same event.
        return None
    else:
        matched_threshold = None

    # RESOLUTION-MECHANIC gate (B8 step iii): a CONFIDENT touch-vs-terminal conflict on the
    # same strike is NOT the same event (a barrier that is touched then retraces resolves YES
    # while the co-strike terminal resolves NO → the OPPOSITELY-resolving false pairing). This
    # is tightening-only: it rejects ONLY a confident conflict; an "unknown" on either side is
    # admitted (with mechanic_confirmed=False) rather than rejected, so no previously-matched
    # pair with an unclassifiable mechanic is lost.
    mech_a = classify_resolution_mechanic(market_a)
    mech_b = classify_resolution_mechanic(market_b)
    if mech_a != UNKNOWN_MECHANIC and mech_b != UNKNOWN_MECHANIC and mech_a != mech_b:
        return None
    mechanic_confirmed = (mech_a != UNKNOWN_MECHANIC and mech_a == mech_b)

    # Content-overlap gate, conditioned on threshold strength: a MATCHED numeric strike is
    # strong same-event evidence, so a single shared subject token (e.g. "bitcoin") is
    # enough alongside it; WITHOUT a threshold the pairing rests on token overlap alone and
    # must clear the full ``min_shared_content`` bar (the B5 conservative screen).
    shared = content_tokens(market_a.question) & content_tokens(market_b.question)
    min_needed = 1 if matched_threshold is not None else min_shared_content
    if len(shared) < min_needed:
        return None

    days = _days_apart(market_a.end_date, market_b.end_date)
    if days is None or days > max_days_apart:
        return None

    coherence = _coherence_score(
        shared_count=len(shared),
        has_threshold=matched_threshold is not None,
        days_apart=days,
        max_days_apart=max_days_apart,
    )

    return CrossVenueMatch(
        market_a_id=str(market_a.id),
        market_b_id=str(market_b.id),
        question_a=market_a.question,
        question_b=market_b.question,
        shared_tokens=frozenset(shared),
        threshold=matched_threshold,
        yes_price_a=price_a,
        yes_price_b=price_b,
        end_date_a=market_a.end_date,
        end_date_b=market_b.end_date,
        coherence_score=coherence,
        mechanic_a=mech_a,
        mechanic_b=mech_b,
        mechanic_confirmed=mechanic_confirmed,
    )


def _coherence_score(
    *, shared_count: int, has_threshold: bool, days_apart: float, max_days_apart: float
) -> float:
    """Bounded [0, 1] confidence that a passing match is truly the same event.

    Monotone in each input's favorable direction: more shared content tokens, an explicit
    matched threshold, and closer resolution dates all RAISE confidence. Deterministic and
    continuous. This is CONFIDENCE, not edge — sizing uses the cost-net coherence edge.
    """
    # Content component: 2 shared tokens → 0.5, saturating toward 1.0 by ~5 tokens.
    content = min(1.0, 0.25 * float(shared_count))
    # Threshold component: an explicit, matched numeric strike is strong evidence.
    threshold = 1.0 if has_threshold else 0.0
    # Timeframe component: 1.0 for same-day, linearly to 0.0 at max_days_apart.
    tf = 1.0 - min(1.0, max(0.0, days_apart) / max(max_days_apart, 1e-9))
    # Weighted blend; threshold is weighted heavily because it is the sharpest gate.
    score = 0.35 * content + 0.45 * threshold + 0.20 * tf
    score = min(1.0, max(0.0, score))
    # HARD CAP: a match with no confident numeric strike rests on token overlap alone. It
    # is surfaced but must never be sized on its own — cap it strictly below the trade bar
    # (closes the both-sides-None hole, incl. spelled-out numbers, where high content
    # overlap + a close date could otherwise reach DEFAULT_MIN_COHERENCE).
    if not has_threshold:
        score = min(score, _NO_THRESHOLD_COHERENCE_CAP)
    return round(score, 6)


def find_cross_venue_matches(
    markets_a: Sequence[Market],
    markets_b: Sequence[Market],
    *,
    min_shared_content: int = DEFAULT_MIN_SHARED_CONTENT,
    max_days_apart: float = DEFAULT_MAX_DAYS_APART,
) -> List[CrossVenueMatch]:
    """All confirmed same-event matches across two venues' market lists.

    Deterministic: results are sorted by descending ``coherence_score`` then by the id
    pair, so the same inputs always yield the same order (reproducibility contract). This
    is O(|A|*|B|) by design — the venue market universes are small per scan and each
    pairwise decision is cheap; there is no fitting, no state, no network.
    """
    out: List[CrossVenueMatch] = []
    for ma in markets_a:
        for mb in markets_b:
            match = match_markets(
                ma, mb, min_shared_content=min_shared_content, max_days_apart=max_days_apart
            )
            if match is not None:
                out.append(match)
    out.sort(key=lambda m: (-m.coherence_score, m.market_a_id, m.market_b_id))
    return out


# --------------------------------------------------------------------------- #
# The cost-net coherence edge + offline evaluation (the backtest half).        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CoherenceEdge:
    """The cost-net edge of the two-leg coherence trade on a matched pair.

    ``net_edge_per_pair`` is the profit per 1-contract-each pair AFTER both venues' fees +
    slippage, ASSUMING the two markets resolve identically (the matcher's job). It is the
    disagreement that survives the round-trip cost of both legs; <= 0 when the venues
    agree closely enough that the double cost eats the gap. ``buy_yes_on`` is ``"a"`` or
    ``"b"`` — the cheaper-YES venue we buy YES on (NO on the other).
    """

    net_edge_per_pair: float
    buy_yes_on: str
    yes_cost: float
    no_cost: float


def coherence_edge(
    yes_price_a: float, yes_price_b: float, cost_model: CostModel = DEFAULT_COST_MODEL
) -> CoherenceEdge:
    """Cost-net edge of buying YES on the cheaper venue + NO on the dearer one.

    Buy YES where YES is cheaper (venue A if ``yes_a <= yes_b``, else B) and NO on the
    other venue (its NO price is ``1 - yes_other``). Both legs pay the venue's
    ``effective_buy_price`` (slippage + fee). If both markets resolve the same way exactly
    one leg pays $1, so ``net = 1 - (yes_cost + no_cost)``. Deterministic, no side effects.
    """
    if yes_price_a <= yes_price_b:
        buy_yes_on, yes_p, no_p = "a", yes_price_a, 1.0 - yes_price_b
    else:
        buy_yes_on, yes_p, no_p = "b", yes_price_b, 1.0 - yes_price_a
    yes_cost = cost_model.effective_buy_price(yes_p)
    no_cost = cost_model.effective_buy_price(no_p)
    net = 1.0 - (yes_cost + no_cost)
    return CoherenceEdge(
        net_edge_per_pair=net, buy_yes_on=buy_yes_on, yes_cost=yes_cost, no_cost=no_cost
    )


@dataclass(frozen=True)
class ResolvedCrossVenuePair:
    """A matched pair with the REAL resolved outcomes of BOTH venues' markets.

    ``outcome_a`` / ``outcome_b`` are the realized YES(True)/NO(False) resolutions on each
    venue. They are USUALLY equal (same event) — but ``outcome_a != outcome_b`` is exactly
    the resolution-divergence risk a false match carries, so the evaluator models it
    honestly rather than assuming equality.
    """

    match: CrossVenueMatch
    outcome_a: bool
    outcome_b: bool


@dataclass(frozen=True)
class CrossVenueBacktestReport:
    """Deterministic, honest summary of the coherence trade over resolved matched pairs."""

    pairs_considered: int
    pairs_traded: int
    net_pnl: float
    wins: int
    losses: int
    divergent_resolutions: int  # pairs whose two venues resolved OPPOSITELY (the real risk)
    per_pair_pnl: Tuple[float, ...] = field(default_factory=tuple)


def evaluate_cross_venue_pairs(
    pairs: Sequence[ResolvedCrossVenuePair],
    *,
    cost_model: CostModel = DEFAULT_COST_MODEL,
    min_coherence: float = DEFAULT_MIN_COHERENCE,
    min_net_edge: float = 0.0,
    require_mechanic_confirmed: bool = False,
) -> CrossVenueBacktestReport:
    """Realized cost-net PnL of the coherence trade over RESOLVED matched pairs.

    Trades only pairs whose ``coherence_score >= min_coherence`` AND whose cost-net
    coherence edge ``> min_net_edge`` (an efficient, agreeing pair is not traded — no
    fabricated edge). When ``require_mechanic_confirmed`` is True (the honest gate for any
    OOS/edge CLAIM, ROADMAP B8 step iii), a pair is ALSO skipped unless BOTH legs classify
    to the SAME known resolution mechanic (``match.mechanic_confirmed``) — so a
    semantically-unclassified same-strike pair never contributes to a claimed edge. Default
    False keeps the backtest byte-for-byte unchanged (mechanic status is still recorded on
    every match, so a caller can measure the confirmed-only subset without re-matching).
    PnL per traded pair, 1 contract per leg:

        payout = (1 if outcome_[cheap-yes venue] else 0)      # the YES leg
               + (1 if not outcome_[other venue]  else 0)     # the NO leg
        pnl    = payout - (yes_cost + no_cost)

    When both venues resolve identically exactly one leg pays $1 → ``pnl == net_edge``.
    When a (mis-)matched pair resolves OPPOSITELY the position can pay $0 or $2 — the
    honest downside/upside of a wrong match, counted in ``divergent_resolutions``. Pure
    and deterministic: same pairs + same config → same report (reproducibility contract).
    """
    traded = 0
    net = 0.0
    wins = 0
    losses = 0
    divergent = 0
    per_pair: List[float] = []
    for p in pairs:
        edge = coherence_edge(p.match.yes_price_a, p.match.yes_price_b, cost_model)
        if p.match.coherence_score < min_coherence or edge.net_edge_per_pair <= min_net_edge:
            continue
        if require_mechanic_confirmed and not p.match.mechanic_confirmed:
            # Semantically-unclassified same-strike pair: excluded from a claimed edge.
            continue
        traded += 1
        if p.outcome_a != p.outcome_b:
            divergent += 1
        # Which venue we bought YES on decides the payout mapping.
        if edge.buy_yes_on == "a":
            yes_wins, no_wins = p.outcome_a, (not p.outcome_b)
        else:
            yes_wins, no_wins = p.outcome_b, (not p.outcome_a)
        payout = (1.0 if yes_wins else 0.0) + (1.0 if no_wins else 0.0)
        pnl = payout - (edge.yes_cost + edge.no_cost)
        net += pnl
        per_pair.append(round(pnl, 8))
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1
    return CrossVenueBacktestReport(
        pairs_considered=len(pairs),
        pairs_traded=traded,
        net_pnl=round(net, 8),
        wins=wins,
        losses=losses,
        divergent_resolutions=divergent,
        per_pair_pnl=tuple(per_pair),
    )
