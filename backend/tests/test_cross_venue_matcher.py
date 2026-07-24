"""
test_cross_venue_matcher.py — B8 cross-venue coherence matcher + edge (ROADMAP B8).

Proves the matcher REJECTS the adversarial false-pairing classes (the cross-venue analog
of the B5 keyword hardening) and only pairs genuine same-event markets; and that the
cost-net coherence edge/backtest recovers a real injected disagreement, never fabricates
an edge on agreeing venues, honestly models the resolution-divergence downside, and
reproduces deterministically. Pure/offline — uses the REAL Market model (BUILDS≠WORKS).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.prediction_markets.cost_model import CostModel
from app.prediction_markets.cross_venue_matcher import (
    CrossVenueMatch,
    ResolvedCrossVenuePair,
    coherence_edge,
    evaluate_cross_venue_pairs,
    extract_threshold,
    extract_threshold_from_structured_strike,
    find_cross_venue_matches,
    match_markets,
)
from app.prediction_markets.polymarket_client import Market, Outcome

_BASE = datetime(2026, 12, 1, tzinfo=timezone.utc)


def _mkt(
    mid: str,
    question: str,
    yes_price: float,
    end_date=_BASE,
    *,
    n_outcomes: int = 2,
    category: str = "",
) -> Market:
    """Build a real binary (or multi) Market with a given YES midpoint."""
    outcomes = [
        Outcome(token_id=f"{mid}-YES", label="Yes", price=yes_price, midpoint=yes_price, volume=1000.0),
        Outcome(token_id=f"{mid}-NO", label="No", price=1.0 - yes_price, midpoint=1.0 - yes_price, volume=1000.0),
    ]
    if n_outcomes != 2:
        outcomes = [
            Outcome(token_id=f"{mid}-{i}", label=f"O{i}", price=1.0 / n_outcomes, midpoint=1.0 / n_outcomes, volume=10.0)
            for i in range(n_outcomes)
        ]
    return Market(
        id=mid,
        condition_id=mid,
        question=question,
        slug=mid.lower(),
        description="",
        category=category,
        end_date=end_date,
        outcomes=outcomes,
        total_volume=1000.0,
        liquidity=500.0,
        active=True,
        closed=False,
        resolved=False,
    )


# --------------------------------------------------------------------------- #
# extract_threshold                                                            #
# --------------------------------------------------------------------------- #


def test_extract_threshold_percent_with_direction():
    t = extract_threshold("Will approval exceed 50%?")
    assert t is not None
    assert t.unit == "percent" and t.value == 50.0 and t.direction == "up"


def test_extract_threshold_currency_magnitude():
    t = extract_threshold("Will Bitcoin be above $100k on Dec 31?")
    assert t is not None
    assert t.unit == "currency" and t.value == 100_000.0 and t.direction == "up"


def test_extract_threshold_below_direction():
    t = extract_threshold("Will unemployment fall below 4%?")
    # "fall"/"below" → down
    assert t is not None and t.direction == "down" and t.value == 4.0


def test_extract_threshold_bare_year_is_not_a_threshold():
    # A bare year is a date, not a strike → no confident threshold.
    assert extract_threshold("Who wins the 2026 election?") is None


def test_extract_threshold_ambiguous_multiple_numbers_returns_none():
    # Two numeric thresholds → ambiguous → refuse to guess.
    assert extract_threshold("Will GDP be above 3% and CPI above 2%?") is None


def test_extract_threshold_none_when_no_number():
    assert extract_threshold("Will the Democrats win the House?") is None


def test_adjacent_strikes_do_not_match():
    # Adversarial-audit break: a 2% relative tolerance fabricated a "disagreement" between
    # >50% and >51% (different, coherently-priced events). Near-exact tolerance rejects.
    for lo, hi in [("above 50%", "above 51%"), ("above 4%", "above 4.05%"),
                   ("above $100000", "above $102000"), ("above 270", "above 275")]:
        a, b = extract_threshold(lo), extract_threshold(hi)
        assert a is not None and b is not None
        assert not a.matches(b), f"{lo!r} must NOT match {hi!r} (adjacent strikes = different events)"
    # but pure format/rounding differences DO match (same normalized float).
    assert extract_threshold("above $100k").matches(extract_threshold("above $100,000"))
    assert extract_threshold("above $100000").matches(extract_threshold("above $100k"))


def test_negated_comparator_voids_the_strike():
    # Correctly INVERTING a negated bound is a regex rabbit hole (two audits found both a
    # missed AND a spurious inversion), so a negation binding a comparator VOIDS the strike
    # (returns None = no confident threshold). This is tightening-only: a voided strike can
    # only cause a conservative reject/no-trade, NEVER a spurious match. Word forms:
    assert extract_threshold("Will Bitcoin be no more than $100k by December 2026?") is None
    assert extract_threshold("Will Bitcoin be not above 50 percent in December 2026?") is None
    # CONTRACTION forms (the apostrophe tokenizer must still SEE the negation):
    assert extract_threshold("Bitcoin won't exceed $100000 in December 2026") is None
    assert extract_threshold("Bitcoin can't go above $100000 in December 2026") is None
    assert extract_threshold("Bitcoin doesn't rise above 50 percent in December 2026") is None
    assert extract_threshold("Bitcoin isn't above 50 percent in December 2026") is None
    # THE SPURIOUS-INVERSION REGRESSION (final-audit break): a negation in a DIFFERENT
    # clause must not fabricate a match. "no layoffs and unemployment above 4%" voids its
    # strike, so it can never falsely pair with "unemployment below 4%".
    assert extract_threshold("Will there be no layoffs and unemployment above 4% in 2026?") is None
    # A NON-negated comparator is unaffected (control — still a confident strike).
    assert extract_threshold("Will unemployment be above 4% in 2026?").direction == "up"
    assert extract_threshold("Will unemployment be below 4% in 2026?").direction == "down"
    # end-to-end: a negated market never matches a real-strike market (word, contraction,
    # AND the cross-clause regression case).
    real = _mkt("K1", "Will Bitcoin be above $100000 by December 2026?", 0.55)
    for neg_q in ("Will Bitcoin be no more than $100k by December 2026?",
                  "Will Bitcoin won't be above $100k by December 2026?",
                  "Will Bitcoin can't exceed $100000 by December 2026?"):
        assert match_markets(_mkt("P1", neg_q, 0.20), real) is None, neg_q
    # the cross-clause unemployment case (the final regression) also does not match
    poly_unemp = _mkt("P2", "Will there be no layoffs and unemployment above 4% in 2026?", 0.30)
    kalshi_unemp = _mkt("K2", "Will unemployment be below 4% in 2026?", 0.55)
    assert match_markets(poly_unemp, kalshi_unemp) is None


def test_no_threshold_pair_is_not_tradeable():
    # Adversarial-audit break: two markets whose numeric range is SPELLED OUT ("two hundred
    # thousand") yield no digit strike → both threshold=None. With high content overlap +
    # close dates a no-threshold pair used to reach coherence 0.5 and TRADE. It must now be
    # SURFACED but never sized (coherence hard-capped strictly below DEFAULT_MIN_COHERENCE).
    poly = _mkt("P1", "Will Tesla deliver between two hundred thousand and three hundred thousand cars in December 2026?", 0.60)
    kalshi = _mkt("K1", "Will Tesla deliver between six hundred thousand and seven hundred thousand cars in December 2026?", 0.10)
    m = match_markets(poly, kalshi)
    if m is not None:  # surfaced as a low-confidence candidate is acceptable...
        assert m.threshold is None
        assert m.coherence_score < 0.5  # ...but NEVER tradeable on its own
        pair = ResolvedCrossVenuePair(match=m, outcome_a=True, outcome_b=True)
        assert evaluate_cross_venue_pairs([pair]).pairs_traded == 0


def test_threshold_matches_and_mismatches():
    a = extract_threshold("above $100k")
    b = extract_threshold("above $100000")  # same magnitude, same unit
    c = extract_threshold("above $90k")     # different magnitude
    d = extract_threshold("below $100k")    # different direction
    assert a is not None and b is not None and c is not None and d is not None
    assert a.matches(b)
    assert not a.matches(c)
    assert not a.matches(d)


# --------------------------------------------------------------------------- #
# match_markets — TRUE positive                                               #
# --------------------------------------------------------------------------- #


def test_true_same_event_matches():
    poly = _mkt("P1", "Will Bitcoin close above $100k by December 31 2026?", 0.60)
    kalshi = _mkt("K1", "Bitcoin price above $100000 on 2026-12-31 close", 0.52,
                  end_date=_BASE + timedelta(days=1))
    m = match_markets(poly, kalshi)
    assert m is not None
    assert m.threshold is not None and m.threshold.value == 100_000.0
    assert "bitcoin" in m.shared_tokens
    assert 0.0 < m.coherence_score <= 1.0
    # Threshold present + close dates → high confidence.
    assert m.coherence_score >= 0.5


# --------------------------------------------------------------------------- #
# match_markets — adversarial REJECTIONS (the whole point of B8)              #
# --------------------------------------------------------------------------- #


def test_reject_threshold_strike_mismatch():
    poly = _mkt("P1", "Will Bitcoin close above $100k by December 2026?", 0.60)
    kalshi = _mkt("K1", "Will Bitcoin close above $90k by December 2026?", 0.62)
    assert match_markets(poly, kalshi) is None


def test_reject_comparator_direction_mismatch():
    poly = _mkt("P1", "Will approval rating stay above 50 percent in December?", 0.60)
    kalshi = _mkt("K1", "Will approval rating fall below 50 percent in December?", 0.40)
    assert match_markets(poly, kalshi) is None


def test_reject_timeframe_window_mismatch():
    poly = _mkt("P1", "Will Bitcoin be above $100k?", 0.60, end_date=_BASE)
    kalshi = _mkt("K1", "Bitcoin above $100000 outcome", 0.55,
                  end_date=_BASE + timedelta(days=90))  # different resolution window
    assert match_markets(poly, kalshi) is None


def test_reject_missing_end_date_unverifiable_window():
    poly = _mkt("P1", "Will Bitcoin be above $100k?", 0.60, end_date=None)
    kalshi = _mkt("K1", "Bitcoin above $100000 outcome", 0.55, end_date=_BASE)
    assert match_markets(poly, kalshi) is None


def test_reject_same_template_different_subject():
    # The B5 Biden/Macron trap: identical template, different subject → 0 shared content
    # tokens (approval/rating/exceed/percent/December are all stop words).
    poly = _mkt("P1", "Will Bidens approval rating exceed 50 percent in December?", 0.60)
    kalshi = _mkt("K1", "Will Macrons approval rating exceed 50 percent in December?", 0.61)
    assert match_markets(poly, kalshi) is None


def test_reject_one_sided_threshold_specificity_mismatch():
    # One market is strike-defined, the other is not → different specificity.
    poly = _mkt("P1", "Will Ethereum trade above $5000 in December 2026?", 0.30)
    kalshi = _mkt("K1", "Will Ethereum have a strong December 2026 rally?", 0.35)
    # Even if they shared enough tokens, the one-sided threshold rejects.
    assert match_markets(poly, kalshi) is None


def test_reject_non_binary_market():
    poly = _mkt("P1", "Which team wins the championship in December 2026?", 0.25, n_outcomes=4)
    kalshi = _mkt("K1", "Championship winner team December 2026", 0.25)
    assert match_markets(poly, kalshi) is None


def test_reject_insufficient_content_overlap():
    poly = _mkt("P1", "Will the Federal Reserve cut interest rates in December 2026?", 0.60)
    kalshi = _mkt("K1", "Will Argentina qualify for the December 2026 tournament?", 0.55)
    assert match_markets(poly, kalshi) is None


# --------------------------------------------------------------------------- #
# find_cross_venue_matches — determinism + ordering                          #
# --------------------------------------------------------------------------- #


def test_find_matches_deterministic_and_sorted():
    polys = [
        _mkt("P1", "Will Bitcoin close above $100k by December 2026?", 0.60),
        _mkt("P2", "Will Ethereum close above $5000 by December 2026?", 0.30),
    ]
    kalshis = [
        _mkt("K1", "Bitcoin above $100000 close December 2026", 0.52, end_date=_BASE + timedelta(days=1)),
        _mkt("K2", "Ethereum above $5000 close December 2026", 0.34, end_date=_BASE + timedelta(days=1)),
    ]
    r1 = find_cross_venue_matches(polys, kalshis)
    r2 = find_cross_venue_matches(polys, kalshis)
    assert r1 == r2  # deterministic
    assert len(r1) == 2  # BTC↔BTC and ETH↔ETH only; no cross-subject pairs
    ids = {(m.market_a_id, m.market_b_id) for m in r1}
    assert ids == {("P1", "K1"), ("P2", "K2")}
    # Sorted by descending coherence.
    assert r1[0].coherence_score >= r1[1].coherence_score


# --------------------------------------------------------------------------- #
# coherence_edge — cost honesty                                               #
# --------------------------------------------------------------------------- #


def test_coherence_edge_agreeing_venues_no_edge():
    # Both venues price YES at 0.50 → buying YES@0.5 + NO@0.5 pays $1 but costs the double
    # round-trip fee → strictly negative net. No fabricated edge on an efficient market.
    e = coherence_edge(0.50, 0.50)
    assert e.net_edge_per_pair < 0.0


def test_coherence_edge_disagreement_positive_and_side():
    # Venue A cheap YES (0.30), venue B dear YES (0.70): buy YES on A + NO on B (0.30).
    # Costs ~ eff(0.30)+eff(0.30) ≈ 0.61 << 1 → strongly positive.
    e = coherence_edge(0.30, 0.70)
    assert e.buy_yes_on == "a"
    assert e.net_edge_per_pair > 0.30
    # Symmetric: if B is the cheaper YES, buy YES on B.
    e2 = coherence_edge(0.70, 0.30)
    assert e2.buy_yes_on == "b"


# --------------------------------------------------------------------------- #
# evaluate_cross_venue_pairs — the backtest half                             #
# --------------------------------------------------------------------------- #


def _match(mid_a, mid_b, yes_a, yes_b, coherence=0.9) -> CrossVenueMatch:
    return CrossVenueMatch(
        market_a_id=mid_a,
        market_b_id=mid_b,
        question_a="q",
        question_b="q",
        shared_tokens=frozenset({"bitcoin"}),
        threshold=None,
        yes_price_a=yes_a,
        yes_price_b=yes_b,
        end_date_a=_BASE,
        end_date_b=_BASE,
        coherence_score=coherence,
    )


def test_backtest_recovers_injected_disagreement_edge():
    # Same event (both resolve YES), venues disagreed 0.30 vs 0.70 → the coherence trade
    # profits regardless of which way it resolves. Inject 5 such pairs.
    pairs = [
        ResolvedCrossVenuePair(match=_match(f"A{i}", f"B{i}", 0.30, 0.70), outcome_a=True, outcome_b=True)
        for i in range(5)
    ]
    rep = evaluate_cross_venue_pairs(pairs)
    assert rep.pairs_traded == 5
    assert rep.net_pnl > 0.0
    assert rep.wins == 5 and rep.losses == 0
    assert rep.divergent_resolutions == 0


def test_backtest_no_fabricated_edge_on_agreeing_venues():
    # Venues agree (0.50 vs 0.50) → net edge <= 0 → not traded → zero PnL. No fabrication.
    pairs = [
        ResolvedCrossVenuePair(match=_match(f"A{i}", f"B{i}", 0.50, 0.50), outcome_a=True, outcome_b=True)
        for i in range(5)
    ]
    rep = evaluate_cross_venue_pairs(pairs)
    assert rep.pairs_traded == 0
    assert rep.net_pnl == 0.0


def test_backtest_min_coherence_gate_filters_low_confidence():
    # A profitable-looking disagreement but LOW coherence (uncertain match) is not traded.
    pairs = [ResolvedCrossVenuePair(match=_match("A", "B", 0.30, 0.70, coherence=0.2),
                                    outcome_a=True, outcome_b=True)]
    rep = evaluate_cross_venue_pairs(pairs, min_coherence=0.5)
    assert rep.pairs_traded == 0


def test_backtest_divergent_resolution_is_honest_loss():
    # A (mis-)matched pair that resolves OPPOSITELY (A=YES, B=NO): we bought YES on the
    # cheaper venue (A, 0.30) and NO on B. A=YES → YES leg pays $1; B=NO → NO-on-B pays $1
    # too → this particular divergence pays $2 (the upside tail). Flip it to expose the
    # loss tail: A=NO, B=YES → both legs pay $0 → full loss. Both are counted as divergent.
    loss_pair = ResolvedCrossVenuePair(match=_match("A", "B", 0.30, 0.70), outcome_a=False, outcome_b=True)
    rep = evaluate_cross_venue_pairs([loss_pair])
    assert rep.pairs_traded == 1
    assert rep.divergent_resolutions == 1
    assert rep.net_pnl < 0.0  # both legs lose → the honest downside of a wrong match


def test_backtest_deterministic():
    pairs = [
        ResolvedCrossVenuePair(match=_match(f"A{i}", f"B{i}", 0.30, 0.70), outcome_a=True, outcome_b=True)
        for i in range(4)
    ]
    r1 = evaluate_cross_venue_pairs(pairs)
    r2 = evaluate_cross_venue_pairs(pairs)
    assert r1 == r2


def test_backtest_respects_custom_cost_model():
    # A punishing cost model shrinks the tradable edge (higher costs → fewer/negative).
    cheap = CostModel(slippage_rate=0.0, fee_rate=0.0)
    dear = CostModel(slippage_rate=0.05, fee_rate=0.10)
    pair = ResolvedCrossVenuePair(match=_match("A", "B", 0.42, 0.58), outcome_a=True, outcome_b=True)
    r_cheap = evaluate_cross_venue_pairs([pair], cost_model=cheap)
    r_dear = evaluate_cross_venue_pairs([pair], cost_model=dear)
    assert r_cheap.net_pnl >= r_dear.net_pnl


# --------------------------------------------------------------------------- #
# active-gate: an untradeable / no-quote market never enters a coherence pair  #
# (a real-data honesty fix — a Kalshi market with no book presents a NEUTRAL   #
#  0.50 PLACEHOLDER + active=False; the matcher must not read that fabricated  #
#  price and manufacture a bogus cross-venue disagreement).                    #
# --------------------------------------------------------------------------- #


def _untradeable(mid: str, question: str, placeholder_yes: float, end_date=_BASE) -> Market:
    """A binary market that could not be quoted: a NEUTRAL 0.50 placeholder price and
    active=False (exactly what kalshi_client emits for a no-bid/ask/last book)."""
    return Market(
        id=mid, condition_id=mid, question=question, slug=mid.lower(), description="",
        category="", end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}-YES", label="Yes", price=placeholder_yes,
                    midpoint=placeholder_yes, volume=0.0),
            Outcome(token_id=f"{mid}-NO", label="No", price=1.0 - placeholder_yes,
                    midpoint=1.0 - placeholder_yes, volume=0.0),
        ],
        total_volume=0.0, liquidity=0.0,
        active=False, closed=False, resolved=False,
    )


def test_untradeable_market_never_matched_placeholder_price():
    """An active Polymarket market vs. an untradeable (no-quote, 0.50 placeholder) Kalshi
    market that shares content + threshold must NOT match — the 0.50 is fabricated, not a
    real disagreement."""
    poly = _mkt("poly1", "Will Bitcoin exceed $100k by 2026?", 0.20)
    kal_noquote = _untradeable("kal1", "Bitcoin to exceed $100k in 2026", 0.50)
    matches = find_cross_venue_matches([poly], [kal_noquote])
    assert matches == []
    # match_markets returns None directly (the gate is in _yes_price).
    assert match_markets(poly, kal_noquote) is None


def test_active_gate_is_what_blocks_not_content():
    """Control: the SAME market, flipped to active=True with a real quote, DOES match —
    proving it is the active-gate (not the content/threshold) that blocked the pairing."""
    poly = _mkt("poly1", "Will Bitcoin exceed $100k by 2026?", 0.20)
    kal_real = _mkt("kal1", "Bitcoin to exceed $100k in 2026", 0.62)  # active=True, real quote
    matches = find_cross_venue_matches([poly], [kal_real])
    assert len(matches) == 1
    assert matches[0].yes_price_a == 0.20 and matches[0].yes_price_b == 0.62


def test_resolved_market_not_matched():
    """A RESOLVED market (active=False, price settled ~1/0) is also correctly refused for a
    LIVE coherence pairing — you cannot open a coherence trade on a settled market."""
    poly = _mkt("poly1", "Will Bitcoin exceed $100k by 2026?", 0.20)
    kal_resolved = Market(
        id="kal1", condition_id="kal1", question="Bitcoin to exceed $100k in 2026",
        slug="kal1", description="", category="", end_date=_BASE,
        outcomes=[
            Outcome(token_id="kal1-YES", label="Yes", price=1.0, midpoint=1.0, volume=100.0),
            Outcome(token_id="kal1-NO", label="No", price=0.0, midpoint=0.0, volume=100.0),
        ],
        total_volume=100.0, liquidity=100.0, active=False, closed=True, resolved=True,
    )
    assert find_cross_venue_matches([poly], [kal_resolved]) == []


# --------------------------------------------------------------------------- #
# Structured strike (ROADMAP B8) — extract_threshold_from_structured_strike +  #
# the match-probe unblock: a generic-title Kalshi market pairs with a          #
# title-strike Polymarket market via its floor_strike/strike_type.             #
# --------------------------------------------------------------------------- #


def _kalshi_struct_mkt(
    mid: str,
    question: str,
    yes_price: float,
    *,
    floor_strike=None,
    cap_strike=None,
    strike_type=None,
    category: str = "Financials",
    end_date=_BASE,
) -> Market:
    """A Kalshi-shaped Market whose strike lives ONLY in the structured fields."""
    return Market(
        id=mid, condition_id=mid, question=question, slug=mid.lower(),
        description="", category=category, end_date=end_date,
        outcomes=[
            Outcome(token_id=f"{mid}-YES", label="Yes", price=yes_price, midpoint=yes_price, volume=1000.0),
            Outcome(token_id=f"{mid}-NO", label="No", price=1.0 - yes_price, midpoint=1.0 - yes_price, volume=1000.0),
        ],
        total_volume=1000.0, liquidity=0.0, active=True, closed=False, resolved=False,
        resolution_source="kalshi",
        floor_strike=floor_strike, cap_strike=cap_strike, strike_type=strike_type,
    )


def test_structured_strike_greater_maps_to_up_currency():
    m = _kalshi_struct_mkt("k", "Bitcoin price on Jul 20, 2026?", 0.14,
                           floor_strike=110000.0, strike_type="greater")
    t = extract_threshold_from_structured_strike(m)
    assert t is not None
    assert t.value == 110000.0 and t.direction == "up" and t.unit == "currency"


def test_structured_strike_less_maps_to_down():
    m = _kalshi_struct_mkt("k", "Ethereum price at close?", 0.30,
                           cap_strike=4000.0, strike_type="less")
    t = extract_threshold_from_structured_strike(m)
    assert t is not None
    assert t.value == 4000.0 and t.direction == "down" and t.unit == "currency"


def test_structured_strike_between_is_no_confident_strike():
    """A range ("between", both bounds) is NOT a single strike — refuse to guess."""
    m = _kalshi_struct_mkt("k", "Bitcoin price range?", 0.5,
                           floor_strike=60000.0, cap_strike=70000.0, strike_type="between")
    assert extract_threshold_from_structured_strike(m) is None


def test_structured_strike_unknown_type_is_none():
    m = _kalshi_struct_mkt("k", "Some functional market", 0.5,
                           floor_strike=5.0, strike_type="functional")
    assert extract_threshold_from_structured_strike(m) is None


def test_structured_strike_missing_defining_bound_is_none():
    """A 'greater' strike with no floor_strike has no defining bound → None."""
    m = _kalshi_struct_mkt("k", "Bitcoin?", 0.5, cap_strike=100.0, strike_type="greater")
    assert extract_threshold_from_structured_strike(m) is None


def test_structured_strike_non_price_is_refused():
    """Without a currency/percent cue in its own text, a structured strike has no confident
    unit and is REFUSED (None) — a bare-number 'plain' threshold could license a
    magnitude-only false pairing (the cardinal sin), so we never emit one."""
    m = _kalshi_struct_mkt("k", "High temperature in NYC on Jul 20?", 0.4,
                           floor_strike=95.0, strike_type="greater", category="Climate")
    assert extract_threshold_from_structured_strike(m) is None


def test_structured_strike_plain_vs_plain_collision_refused():
    """A magnitude-only coincidence between two UNRELATED 'bitcoin' markets (a Kalshi
    structured 'hashrate 95000' vs a Polymarket 'forum members > 95000') must NOT produce a
    match — refusing 'plain' structured strikes closes this fabricated-disagreement hole."""
    kalshi = _kalshi_struct_mkt("k", "Bitcoin network hashrate settlement", 0.5,
                                floor_strike=95000.0, strike_type="greater", category="Crypto")
    poly = _mkt("poly", "Will Bitcoin forum membership exceed 95000 by Dec 2026?", 0.4)
    assert match_markets(poly, kalshi) is None


def test_no_structured_fields_returns_none():
    """A plain Polymarket-style market (no structured fields) → None (backward compat)."""
    m = _mkt("poly", "Will Bitcoin be above $100k?", 0.2)
    assert extract_threshold_from_structured_strike(m) is None


def test_match_probe_unblock_generic_kalshi_pairs_with_title_strike_polymarket():
    """THE B8 unblock, reproduced offline: a generic-title Kalshi crypto market (strike in
    floor_strike only) now MATCHES a Polymarket market whose strike is in its title. Before
    this change the Kalshi side yielded no threshold, so the specificity gate REJECTED the
    pair (exactly one side strike-defined) — the measured root cause of the 0-match probe."""
    poly = _mkt("poly1", "Will Bitcoin be above $110,000 by Dec 31, 2026?", 0.20,
                end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    kalshi = _kalshi_struct_mkt("KXBTCMAXY-26DEC31-T110000",
                                "Bitcoin price on Dec 31, 2026?", 0.14,
                                floor_strike=110000.0, strike_type="greater",
                                end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    match = match_markets(poly, kalshi)
    assert match is not None
    assert match.threshold is not None
    assert match.threshold.value == 110000.0 and match.threshold.direction == "up"


def test_match_probe_still_rejects_kalshi_with_no_structured_strike():
    """Regression: a generic-title Kalshi market with NO structured strike still fails the
    specificity gate against a title-strike Polymarket market — the fallback does not
    weaken the gate; it only supplies a strike that genuinely exists."""
    poly = _mkt("poly1", "Will Bitcoin be above $110,000 by Dec 31, 2026?", 0.20,
                end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    kalshi_nostrike = _kalshi_struct_mkt("k", "Bitcoin price on Dec 31, 2026?", 0.14,
                                         end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    assert match_markets(poly, kalshi_nostrike) is None


def test_match_probe_rejects_mismatched_structured_strike():
    """Two crypto markets whose strikes DISAGREE ($110k up vs $90k up) are still refused —
    the structured strike is matched on magnitude, not merely presence."""
    poly = _mkt("poly1", "Will Bitcoin be above $90,000 by Dec 31, 2026?", 0.40,
                end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    kalshi = _kalshi_struct_mkt("k", "Bitcoin price on Dec 31, 2026?", 0.14,
                                floor_strike=110000.0, strike_type="greater",
                                end_date=datetime(2026, 12, 31, tzinfo=timezone.utc))
    assert match_markets(poly, kalshi) is None


# --------------------------------------------------------------------------- #
# Resolution-mechanic classifier (B8 step iii — the touch/barrier/terminal gate)          #
# --------------------------------------------------------------------------- #

from app.prediction_markets.cross_venue_matcher import (  # noqa: E402
    TERMINAL_MECHANIC,
    TOUCH_MECHANIC,
    UNKNOWN_MECHANIC,
    classify_resolution_mechanic,
)


def _with_ticker(m: Market, ticker: str) -> Market:
    m.ticker = ticker
    return m


def test_classify_terminal_from_title():
    for q in ("Will Bitcoin close above $100k on Dec 31?",
              "BTC price at the close on 2026-12-31",
              "Will unemployment settle above 4% at expiry?"):
        assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == TERMINAL_MECHANIC, q


def test_classify_touch_from_title():
    for q in ("Will Bitcoin ever reach $100k in 2026?",
              "Will BTC hit $100k at any point this year?",
              "Will ETH touch $5000 before year end?",
              "Will Bitcoin's maximum price exceed $120k in December?"):
        assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == TOUCH_MECHANIC, q


def test_classify_unknown_when_no_cue():
    for q in ("Will Bitcoin be above $100k in December 2026?",
              "Will the Democrats win the House?"):
        assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == UNKNOWN_MECHANIC, q


def test_classify_ambiguous_both_cues_is_unknown():
    # Both a touch cue ("reach") and a terminal cue ("close") → refuse to guess.
    q = "Will Bitcoin reach $100k before the close on Dec 31?"
    assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == UNKNOWN_MECHANIC


def test_classify_touch_from_kalshi_max_ticker():
    # Kalshi generic-title barrier series: the mechanic lives in the TICKER, not the title.
    m = _with_ticker(_kalshi_struct_mkt("k", "Bitcoin price on Dec 31, 2026?", 0.14,
                                        floor_strike=100000.0, strike_type="greater"),
                     "KXBTCMAXY-26DEC31-B100000")
    assert classify_resolution_mechanic(m) == TOUCH_MECHANIC
    m2 = _with_ticker(_kalshi_struct_mkt("k", "Ethereum price on Dec 31, 2026?", 0.2,
                                         floor_strike=5000.0, strike_type="greater"),
                      "KXETHMINY-26DEC31-B5000")
    assert classify_resolution_mechanic(m2) == TOUCH_MECHANIC


def test_bare_high_low_is_not_a_touch_cue():
    # "record high" must NOT be read as a barrier (false-positive guard).
    q = "Will unemployment be at a record high level in December 2026?"
    assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == UNKNOWN_MECHANIC


def test_colloquial_verb_on_percent_stat_is_not_touch():
    # ADVERSARIAL-AUDITOR REGRESSION: a terminal-only percent statistic phrased with a
    # colloquial "hit"/"reach" must NOT be mis-classified as touch (no intraday path exists) —
    # otherwise a genuine same-event pair is falsely rejected as a touch-vs-terminal conflict.
    for q in ("Will US unemployment hit 5% in December 2026?",
              "Will CPI reach 3% in December 2026?",
              "Will the Democrats reach 218 seats in 2026?"):
        assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == UNKNOWN_MECHANIC, q


def test_colloquial_verb_on_currency_price_is_touch():
    # ...but the SAME verbs ARE a barrier cue for a continuous-price (currency) underlying.
    for q in ("Will Bitcoin reach $100k in December 2026?",
              "Will Bitcoin hit $100,000 this year?"):
        assert classify_resolution_mechanic(_mkt("m", q, 0.5)) == TOUCH_MECHANIC, q


def test_percent_stat_same_event_pair_not_falsely_rejected():
    """The end-to-end fix: a terminal-only unemployment pair phrased with 'hit'/'at or above'
    (both -> unknown mechanic now) MATCHES instead of being killed by a spurious conflict."""
    poly = _mkt("P1", "Will US unemployment hit 5% in December 2026?", 0.40, end_date=_BASE)
    kalshi = _mkt("K1", "Will US unemployment be at or above 5% in the December 2026 report?",
                  0.55, end_date=_BASE + timedelta(days=1))
    m = match_markets(poly, kalshi)
    assert m is not None
    assert m.mechanic_a == UNKNOWN_MECHANIC and m.mechanic_b == UNKNOWN_MECHANIC
    assert m.mechanic_confirmed is False


def test_match_rejects_touch_vs_terminal_conflict():
    """The load-bearing gate: same strike + same window + shared content, but one resolves on
    a TOUCH and the other on a TERMINAL close → they can resolve OPPOSITELY → REJECT."""
    touch = _mkt("P1", "Will Bitcoin ever reach $100k in December 2026?", 0.60,
                 end_date=_BASE)
    terminal = _mkt("K1", "Will Bitcoin close above $100000 in December 2026?", 0.52,
                    end_date=_BASE + timedelta(days=1))
    assert match_markets(touch, terminal) is None


def test_match_confirms_same_mechanic():
    """Both TERMINAL → matched AND mechanic_confirmed=True."""
    a = _mkt("P1", "Will Bitcoin close above $100k in December 2026?", 0.60, end_date=_BASE)
    b = _mkt("K1", "Bitcoin close above $100000 in December 2026", 0.52,
             end_date=_BASE + timedelta(days=1))
    m = match_markets(a, b)
    assert m is not None
    assert m.mechanic_a == TERMINAL_MECHANIC and m.mechanic_b == TERMINAL_MECHANIC
    assert m.mechanic_confirmed is True


def test_match_admits_unknown_mechanic_but_flags_unconfirmed():
    """One side has no mechanic cue → NOT rejected (tightening-only) but mechanic_confirmed=False."""
    known = _mkt("P1", "Will Bitcoin close above $100k in December 2026?", 0.60, end_date=_BASE)
    unknown = _mkt("K1", "Will Bitcoin be above $100000 in December 2026?", 0.52,
                   end_date=_BASE + timedelta(days=1))
    m = match_markets(known, unknown)
    assert m is not None  # admitted
    assert m.mechanic_a == TERMINAL_MECHANIC and m.mechanic_b == UNKNOWN_MECHANIC
    assert m.mechanic_confirmed is False


def test_backtest_require_mechanic_confirmed_filters_unconfirmed():
    """The edge-claim gate: require_mechanic_confirmed excludes a semantically-unclassified pair."""
    # Build a disagreeing, coherent pair whose match is NOT mechanic-confirmed.
    unconfirmed = CrossVenueMatch(
        market_a_id="a", market_b_id="b", question_a="q", question_b="q",
        shared_tokens=frozenset({"bitcoin"}), threshold=None,
        yes_price_a=0.30, yes_price_b=0.70, end_date_a=_BASE, end_date_b=_BASE,
        coherence_score=0.9, mechanic_a=TERMINAL_MECHANIC, mechanic_b=UNKNOWN_MECHANIC,
        mechanic_confirmed=False,
    )
    pair = ResolvedCrossVenuePair(match=unconfirmed, outcome_a=True, outcome_b=True)
    # Without the gate the disagreement is traded; with it, it is excluded.
    traded = evaluate_cross_venue_pairs([pair], min_coherence=0.5)
    gated = evaluate_cross_venue_pairs([pair], min_coherence=0.5, require_mechanic_confirmed=True)
    assert traded.pairs_traded == 1
    assert gated.pairs_traded == 0


def test_backtest_default_unchanged_by_mechanic_param():
    """Default (require_mechanic_confirmed=False) is byte-for-byte the prior behavior."""
    confirmed = CrossVenueMatch(
        market_a_id="a", market_b_id="b", question_a="q", question_b="q",
        shared_tokens=frozenset({"bitcoin"}), threshold=None,
        yes_price_a=0.30, yes_price_b=0.70, end_date_a=_BASE, end_date_b=_BASE,
        coherence_score=0.9,
    )
    assert confirmed.mechanic_confirmed is False  # default field value
    pair = ResolvedCrossVenuePair(match=confirmed, outcome_a=True, outcome_b=True)
    r = evaluate_cross_venue_pairs([pair], min_coherence=0.5)
    assert r.pairs_traded == 1
