"""
Regression: NearCertaintyStrategy must emit `edge` in ABSOLUTE probability units.

The orchestrator reconstructs the win probability of every ScanResult uniformly as
``win_probability = entry_price + result.edge`` (orchestrator.size_from_scan_result).
It does NOT branch per strategy. Therefore every strategy's `edge` MUST be in the same
absolute price/probability units — i.e. ``edge == true_prob - price`` — or the
orchestrator silently misinterprets it and mis-sizes the Kelly bet.

NearCertaintyStrategy used to emit ``edge = expected_value / price`` (a RELATIVE return),
which the orchestrator then read as an absolute delta. That inflated the reconstructed
win probability above the strategy's own stated ``confidence`` and, at the low end of the
[0.80, 0.99] scan band, pushed it ABOVE 1.0 — a systematic over-sizing bug on the active
default paper strategy.

These tests trip on the pre-fix ``/ price`` division and pass only with the absolute-EV
edge. They assert the load-bearing invariant directly:
``entry_price + edge == confidence`` and ``entry_price + edge <= 1.0``.
"""

from datetime import datetime, timedelta, timezone

from app.prediction_markets.polymarket_client import Market, Outcome
from app.prediction_markets.strategies import NearCertaintyStrategy, StrategyConfig
from app.prediction_markets.polymarket_client import PolymarketClient


def _near_certain_market(yes_price: float, mid: str = "nc") -> Market:
    no_price = round(1.0 - yes_price, 4)
    return Market(
        id=mid,
        condition_id=mid,
        question="Will X resolve YES?",
        slug=mid,
        description="",
        category="Crypto",
        end_date=datetime.now(timezone.utc) + timedelta(hours=24),
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price, midpoint=yes_price, volume=100_000),
            Outcome(token_id=f"{mid}_no", label="No", price=no_price, midpoint=no_price, volume=100_000),
        ],
        total_volume=100_000,
        liquidity=50_000,
        active=True,
        closed=False,
        resolved=False,
        resolution_source="polymarket",
        tags=[],
        neg_risk=False,
    )


def _scan_yes(yes_price: float):
    strat = NearCertaintyStrategy(client=PolymarketClient(), config=StrategyConfig(), min_volume=0)
    results = strat.scan([_near_certain_market(yes_price)])
    # The first (YES) outcome is the near-certain leg we care about.
    yes_hits = [r for r in results if r.entry_price == yes_price]
    assert yes_hits, f"expected a near-certainty signal on the YES leg at {yes_price}"
    return yes_hits[0]


def test_edge_is_absolute_probability_units_mid_band():
    """At price 0.95 the reconstructed win prob must equal confidence (0.98), not 0.9816."""
    r = _scan_yes(0.95)
    reconstructed_win_prob = r.entry_price + r.edge
    # Absolute-EV edge: true_prob(0.98) - price(0.95) == 0.03  (NOT 0.03/0.95 == 0.0316).
    assert abs(r.edge - (r.confidence - r.entry_price)) < 1e-9
    assert abs(reconstructed_win_prob - r.confidence) < 1e-9
    assert reconstructed_win_prob <= 1.0


def test_edge_does_not_push_win_prob_above_one_at_low_band():
    """The pre-fix `/price` edge made win_prob = 0.80 + 0.18/0.80 = 1.025 (> 1) — a garbage
    input to Kelly. The absolute-EV edge keeps it at exactly confidence (0.98)."""
    r = _scan_yes(0.80)
    reconstructed_win_prob = r.entry_price + r.edge
    assert reconstructed_win_prob <= 1.0, (
        f"win probability {reconstructed_win_prob} exceeds 1.0 — relative-edge regression"
    )
    assert abs(reconstructed_win_prob - r.confidence) < 1e-9


def test_reconstructed_win_prob_matches_confidence_across_band():
    """The invariant holds across the profitable part of the scan band. (Above ~0.98 the
    2%-reversal EV goes negative and the strategy correctly emits no signal, so the band
    tested here stops below that breakeven.)"""
    for yes_price in (0.80, 0.85, 0.90, 0.95, 0.97):
        r = _scan_yes(yes_price)
        reconstructed_win_prob = r.entry_price + r.edge
        assert abs(reconstructed_win_prob - r.confidence) < 1e-9, (
            f"at price {yes_price}: win_prob {reconstructed_win_prob} != confidence {r.confidence}"
        )
        assert reconstructed_win_prob <= 1.0
