"""Regression tests for issue #165 — the degraded-data path must NEUTRALIZE the
volume/liquidity filter WITHOUT fabricating a passing value.

Before the fix, ``PredictionMarketScanner`` injected ``total_volume=10000`` /
``liquidity=5000`` for every zero-volume/zero-liquidity market whenever the venue
(Gamma) stopped returning volume (>80% zero). Those synthetic numbers sit *above*
every strategy filter threshold (``min_volume`` 1000/5000, ``min_liquidity`` 500/1000),
so they flipped real BUY-gate decisions reject->pass on INVENTED liquidity and leaked
into spread/reason estimates — fabricated data in the live decision path.

The fix marks the missing dimension with per-market ``volume_unavailable`` /
``liquidity_unavailable`` flags (leaving the real 0/unknown value untouched); each
strategy's ``market.volume_below(...)`` / ``market.liquidity_below(...)`` filter is
neutralized for the unavailable dimension only. These tests pin that behavior and
FAIL on the pre-fix fabrication.
"""

from datetime import datetime, timedelta, timezone

from app.prediction_markets.polymarket_client import Market, Outcome, PolymarketClient
from app.prediction_markets.strategies import (
    NearCertaintyStrategy,
    PredictionMarketScanner,
    StrategyConfig,
)


def _outcome(token_id: str, label: str, price: float) -> Outcome:
    return Outcome(token_id=token_id, label=label, price=price, midpoint=price, volume=0.0)


def _market(total_volume: float = 0.0, liquidity: float = 0.0, yes_price: float = 0.90) -> Market:
    return Market(
        id="m1",
        condition_id="cond1",
        question="Will it resolve YES?",
        slug="will-it-resolve-yes",
        description="",
        category="Test",
        end_date=datetime.now(timezone.utc) + timedelta(days=1),
        outcomes=[
            _outcome("tok_yes", "Yes", yes_price),
            _outcome("tok_no", "No", round(1.0 - yes_price, 6)),
        ],
        total_volume=total_volume,
        liquidity=liquidity,
        active=True,
        closed=False,
        resolved=False,
    )


# --------------------------------------------------------------------------- #
# Market.volume_below / liquidity_below helper semantics
# --------------------------------------------------------------------------- #

def test_volume_below_known_value_is_filtered():
    m = _market(total_volume=500.0)
    assert m.volume_unavailable is False
    assert m.volume_below(1000.0) is True   # 500 < 1000, known -> filtered
    assert m.volume_below(400.0) is False   # 500 >= 400


def test_volume_below_unavailable_neutralizes_filter():
    m = _market(total_volume=0.0)
    m.volume_unavailable = True
    # Unavailable -> the filter is neutralized regardless of the threshold, and
    # WITHOUT fabricating a passing number (total_volume stays the honest 0).
    assert m.volume_below(1000.0) is False
    assert m.volume_below(1_000_000.0) is False
    assert m.total_volume == 0.0


def test_liquidity_below_known_value_is_filtered():
    m = _market(liquidity=300.0)
    assert m.liquidity_unavailable is False
    assert m.liquidity_below(500.0) is True
    assert m.liquidity_below(200.0) is False


def test_liquidity_below_unavailable_neutralizes_filter():
    m = _market(liquidity=0.0)
    m.liquidity_unavailable = True
    assert m.liquidity_below(500.0) is False
    assert m.liquidity_below(1_000_000.0) is False
    assert m.liquidity == 0.0


# --------------------------------------------------------------------------- #
# Scanner marks the flags — and does NOT fabricate a value (the #165 fix)
# --------------------------------------------------------------------------- #

def _scanner() -> PredictionMarketScanner:
    return PredictionMarketScanner(PolymarketClient(), use_clob=False)


def test_scanner_marks_unavailable_without_fabricating():
    """THE anti-fabrication regression — FAILS on pre-fix code.

    Pre-fix the scanner set ``total_volume=10000`` / ``liquidity=5000``. The fix
    only sets the flags; the real values must stay 0.
    """
    scanner = _scanner()
    scanner._volume_unavailable = True
    scanner._liquidity_unavailable = True
    m = _market(total_volume=0.0, liquidity=0.0)

    scanner._mark_unavailable_data([m])

    assert m.volume_unavailable is True
    assert m.liquidity_unavailable is True
    # The honest values are UNTOUCHED — no fabricated 10000/5000.
    assert m.total_volume == 0.0
    assert m.liquidity == 0.0


def test_scanner_leaves_real_values_filtered_in_degraded_scan():
    """A market that carries a REAL volume/liquidity in an otherwise-degraded scan
    is NOT flagged (flag only when the value is missing == 0), so it stays filtered
    on its real value."""
    scanner = _scanner()
    scanner._volume_unavailable = True
    scanner._liquidity_unavailable = True
    m = _market(total_volume=50.0, liquidity=25.0)  # real, known, tiny

    scanner._mark_unavailable_data([m])

    assert m.volume_unavailable is False
    assert m.liquidity_unavailable is False
    assert m.volume_below(1000.0) is True      # still filtered on the real value
    assert m.liquidity_below(500.0) is True


def test_scanner_no_flags_when_data_available():
    scanner = _scanner()
    scanner._volume_unavailable = False
    scanner._liquidity_unavailable = False
    m = _market(total_volume=0.0, liquidity=0.0)

    scanner._mark_unavailable_data([m])

    assert m.volume_unavailable is False
    assert m.liquidity_unavailable is False


# --------------------------------------------------------------------------- #
# End-to-end: the intent is preserved (a zero-volume market is NOT discarded when
# volume is genuinely unavailable) — without fabricating a number.
# --------------------------------------------------------------------------- #

def test_filter_neutralized_end_to_end_preserves_intent():
    strat = NearCertaintyStrategy(PolymarketClient(), StrategyConfig(), min_volume=1000)
    m = _market(total_volume=0.0, yes_price=0.90)  # near-certain YES, zero volume

    # Data available (flag unset): the zero-volume market is filtered out.
    assert strat.scan([m]) == []

    # Data unavailable (flag set): the filter is neutralized, so the near-certain
    # opportunity is surfaced — the intended degraded-mode behavior, honestly.
    m.volume_unavailable = True
    results = strat.scan([m])
    assert len(results) >= 1
    assert results[0].side == "BUY"
    # The reason string reports the REAL volume (0), never a fabricated 10000.
    assert "$10,000" not in results[0].reason
