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
