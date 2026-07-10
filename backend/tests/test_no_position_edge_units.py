"""Regression (B / correctness): NOPositionScanner.edge must be in ABSOLUTE PROBABILITY
units — the same #263 bug class the NearCertaintyStrategy fix closed, on a DIFFERENT live
default-scan strategy.

The orchestrator's ``size_from_scan_result`` reconstructs
``win_probability = entry_price + result.edge`` and then gates the trade COST-NET on that
win_probability (``DEFAULT_COST_MODEL.net_edge(win_probability, entry_price)``). So a
strategy's ``edge`` field MUST be a probability difference (our P(reversal) minus the
market's implied NO price), NOT the Kelly EV-per-dollar.

Before the fix, NOPositionScanner emitted the EV-per-dollar (capped at 2.0) as ``edge``, so
the reconstructed win_probability = NO_price + EV was well ABOVE 1.0 (e.g. 0.03 + 2.0 =
2.03). That garbage win_probability inflates ``net_edge`` and FOOLS the cost-net
profitability gate into passing trades whose TRUE net edge is <= 0. The Kelly clamp bounds
the SIZE but never un-fools the GATE — which is exactly why #263 mattered despite the clamp.

NOPositionScanner is the UNVALIDATED EXP-001 longshot-reversal hypothesis. As of the
#263→#280 units-contract series it is units-correct on BOTH ``edge`` and ``confidence``: its
``confidence`` is now pinned to ``gate_confidence(entry, edge)``, so an honest sub-0.5
reversal signal SELF-GATES under ``min_confidence`` instead of the prior ``*2`` bypass.
(Whether it should ALSO be gated OFF of the default scan is a separate DESIGN decision,
deferred — ROADMAP B1.) The regressions below exercise the strategy directly (offline).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.prediction_markets.advanced_strategies import NOPositionScanner
from app.prediction_markets.polymarket_client import Market, Outcome
from app.prediction_markets.strategies import StrategyConfig


class _DummyClient:
    """NOPositionScanner.scan never touches the client (offline)."""


def _crypto_market(no_price: float = 0.03, hours: float = 24.0) -> Market:
    yes_price = round(1.0 - no_price, 4)
    end = datetime.now(timezone.utc) + timedelta(hours=hours)
    return Market(
        id="m1", condition_id="c1", question="Will BTC reach $250k this week?",
        slug="btc-250k", description="", category="crypto", end_date=end,
        outcomes=[
            Outcome(token_id="YES", label="Yes", price=yes_price, midpoint=yes_price, volume=50_000),
            Outcome(token_id="NO", label="No", price=no_price, midpoint=no_price, volume=50_000),
        ],
        total_volume=50_000, liquidity=20_000, active=True, closed=False, resolved=False,
    )


def _scanner() -> NOPositionScanner:
    return NOPositionScanner(_DummyClient(), StrategyConfig(dry_run=True))


def test_estimate_edge_is_probability_difference():
    """_estimate_reversal.edge == P(reversal) - NO_price (probability units), never the
    EV-per-dollar (which would be > 1 at micro NO prices)."""
    scanner = _scanner()
    no_price = 0.03
    est = scanner._estimate_reversal(no_price=no_price, category="crypto", hours_to_resolution=24.0)
    assert est.edge == (est.adjusted_rate - no_price)
    # A genuine probability edge is small and bounded — NOT the pre-fix EV-per-dollar (>1).
    assert -1.0 <= est.edge <= 1.0
    assert est.edge < 1.0


def test_scan_result_reconstructs_a_valid_win_probability():
    """The orchestrator does win_probability = entry_price + edge. That MUST land in (0, 1]
    and equal the reported P(reversal) (expected_value) — pre-fix it was > 1.0 (garbage)."""
    scanner = _scanner()
    results = scanner.scan([_crypto_market(no_price=0.03, hours=24.0)])
    assert results, "precondition: the scenario produces a NO signal"
    r = results[0]

    reconstructed_win_prob = r.entry_price + r.edge
    # The core regression: a real probability, not > 1.0 (pre-fix: 0.03 + 2.0 = 2.03).
    assert 0.0 < reconstructed_win_prob <= 1.0
    # And it equals the reported P(reversal) the strategy estimated (expected_value=adjusted_rate).
    assert reconstructed_win_prob == r.expected_value


def test_confidence_is_pinned_to_win_probability():
    """UNITS CONTRACT (#263→#280, the last executing default-scan strategy): ``confidence``
    MUST equal ``gate_confidence(entry_price, edge) = clip(entry+edge, 0, 1)`` — the
    win-probability ``orchestrator.kelly_size`` compares against in its
    ``confidence < min_confidence`` pre-filter while it SIZES on that same win-probability.
    The pre-fix ``min(adjusted_rate*2, 0.95)`` inflated confidence ABOVE the win-probability
    to bypass the min_confidence gate; pinning it makes an honest sub-0.5 longshot correctly
    self-gate (the safe outcome for an unvalidated strategy)."""
    from app.prediction_markets.polymarket_client import gate_confidence

    scanner = _scanner()
    results = scanner.scan([_crypto_market(no_price=0.03, hours=24.0)])
    assert results, "precondition: the scenario produces a NO signal"
    r = results[0]
    # Pinned to the reconstructed win-probability — no decoupled heuristic.
    assert r.confidence == gate_confidence(r.entry_price, r.edge)
    # At these micro-price values entry+edge is in-range (no clip), so it equals the sum.
    assert r.confidence == r.entry_price + r.edge
    # A longshot NO buy's honest win-probability sits well below the default min_confidence
    # (0.50) gate — so it self-gates. The pre-fix *2 confidence (>= 0.5) bypassed that gate.
    assert r.confidence < 0.50


def test_kelly_fraction_still_derived_from_ev_per_dollar():
    """The DISPLAY Kelly fraction is still the correct EV-per-dollar / payout_ratio — the
    fix changed only the ``edge`` UNITS, not the Kelly-fraction math."""
    scanner = _scanner()
    est = scanner._estimate_reversal(no_price=0.03, category="crypto", hours_to_resolution=24.0)
    payout_ratio = (1.0 / 0.03) - 1.0
    # kelly_ev is capped at 2.0 in the code (micro-price blow-up guard) — mirror that here.
    kelly_ev = min(est.adjusted_rate * payout_ratio - (1.0 - est.adjusted_rate), 2.0)
    expected_fraction = max(0.0, min(kelly_ev / payout_ratio, 0.25)) if kelly_ev > 0 else 0.0
    assert est.kelly_fraction == expected_fraction
