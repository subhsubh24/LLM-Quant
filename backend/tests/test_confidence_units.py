"""Regression (B / correctness): a ScanResult's ``confidence`` must equal the fair-value
win-probability the orchestrator reconstructs — the #263/#268 UNITS CONTRACT applied to
``CrossMarketArbitrageStrategy`` and ``LogicalImplicationDetector`` (two trade-executing
default-scan strategies that emitted a decoupled heuristic confidence).

SCOPE — this PR fixes those two; it makes NO claim of closing the gap on every strategy.
Deliberately NOT changed, each for a documented reason:
  * ``MarketMakingStrategy`` (0.80), ``SameMarketArbitrageStrategy`` (0.99),
    ``FlashCrashStrategy`` (0.95) emit ``outcome_idx == -1`` (multi-leg baskets), which the
    orchestrator SKIPS at ``skip_multi_leg`` (orchestrator.py:1013) BEFORE any order is
    placed (per-leg execution is an unbuilt B1 follow-up). Their confidences are INERT —
    they never gate a real trade — so touching them would be churn on non-executing signals.
  * ``NOPositionScanner`` IS trade-executing (``outcome_idx = no_idx``, single-outcome) and
    DOES still carry a decoupled confidence (``min(adjusted_rate*2, 0.95)`` at
    advanced_strategies.py:265; #268 fixed only its ``edge`` units, not its ``confidence``).
    It is a RESIDUAL FINDING, deliberately out of scope here: it is a longshot-reversal
    strategy whose thesis is ``P(reversal) = adjusted_rate < 0.5`` by design, and its
    ``*2`` confidence is an intentional bypass of the ``min_confidence`` gate. Pinning its
    confidence to the honest win-probability (``= adjusted_rate``, typically < 0.5) would
    gate out most of its signals — i.e. effectively DISABLE the strategy. Whether a
    sub-0.5-win-probability strategy that structurally evades the safety gate should exist
    is a separate DESIGN decision (twice deferred, loop-memory 2026-07-08c), not a
    units-contract correctness fix — so it is tracked, not folded in here.
  * ``NearCertaintyStrategy`` is already contract-correct (``win_probability == confidence``).

Why it matters (the exact bug):
``orchestrator.kelly_size`` reads ``ScanResult.confidence`` for ONE thing only — the
pre-filter ``if confidence < config.min_confidence: return 0.0`` — treating it as the
signal's own probability estimate. Kelly then sizes on ``win_probability = entry_price +
edge``. So a strategy that emits a confidence DECOUPLED from ``entry_price + edge`` (a
hardcoded 0.85, the relationship ``chain_conf``, ...) makes the ``min_confidence`` gate
filter on the WRONG quantity: a BUY whose true fair value is below ``min_confidence`` sails
through the gate, and a strong signal whose relationship confidence is low is wrongly
dropped. Both strategies are on the DEFAULT (non-gated) scan path
(``orchestrator._build_default_scanner``: ``LogicalImplicationDetector`` standalone,
``CrossMarketArbitrageStrategy`` inside the ``AdaptiveBuySignalThreshold`` wrapper), and
``logical_implication`` has fired in real paper/live-validation runs — so this manifests in
real scans.

The fix pins ``confidence = gate_confidence(entry_price, edge) = clip(entry+edge, 0, 1)``
at every emission. These tests trip on the PRE-FIX code (confidence was 0.85 / chain_conf /
0.75) and pass on the fixed code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from app.prediction_markets.advanced_strategies import LogicalImplicationDetector
from app.prediction_markets.polymarket_client import (
    Market,
    Outcome,
    ScanResult,
    gate_confidence,
)
from app.prediction_markets.strategies import (
    CrossMarketArbitrageStrategy,
    ImplicationRule,
    StrategyConfig,
)
from app.prediction_markets.orchestrator import KellyConfig, size_from_scan_result


class _DummyClient:
    """The scan paths under test never touch the client (fully offline)."""


def _market(
    mid: str,
    question: str,
    yes_price: float,
    category: str = "Crypto",
    volume: float = 50_000.0,
    liquidity: float = 50_000.0,
) -> Market:
    end = datetime.now(timezone.utc) + timedelta(days=30)
    return Market(
        id=mid,
        condition_id=f"c_{mid}",
        question=question,
        slug=mid,
        description="",
        category=category,
        end_date=end,
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=yes_price, midpoint=yes_price, volume=volume),
            Outcome(token_id=f"{mid}_no", label="No", price=round(1.0 - yes_price, 4), midpoint=round(1.0 - yes_price, 4), volume=volume),
        ],
        total_volume=volume,
        liquidity=liquidity,
        active=True,
        closed=False,
        resolved=False,
    )


def _assert_invariant(results: List[ScanResult]) -> None:
    """Every emitted signal's confidence == clip(entry+edge, 0, 1) — the units contract."""
    for r in results:
        expected = gate_confidence(r.entry_price, r.edge)
        assert abs(r.confidence - expected) < 1e-9, (
            f"{r.strategy}/{r.side}: confidence {r.confidence} != clip(entry+edge) "
            f"{expected} (entry={r.entry_price}, edge={r.edge})"
        )
        assert 0.0 <= r.confidence <= 1.0


# ── gate_confidence: the helper's own contract ──

def test_gate_confidence_buy_in_range():
    # A BUY at 0.10 with a 0.30 edge → fair value 0.40 (below the 0.50 min_confidence gate).
    assert gate_confidence(0.10, 0.30) == 0.40


def test_gate_confidence_clamps_sell_above_one():
    # A SELL's entry+edge can exceed 1.0 — must clamp, never emit a >1 confidence.
    assert gate_confidence(0.95, 0.20) == 1.0


def test_gate_confidence_clamps_below_zero():
    assert gate_confidence(0.01, -0.50) == 0.0


# ── CrossMarketArbitrageStrategy (rules path) ──

def _cross_strategy() -> CrossMarketArbitrageStrategy:
    rules = [ImplicationRule("alpha wins", "alpha takes state", "implies", "Politics")]
    return CrossMarketArbitrageStrategy(_DummyClient(), StrategyConfig(dry_run=True), custom_rules=rules)


def test_cross_market_implies_confidence_is_fair_value_not_hardcoded():
    # parent P=0.40 > child P=0.10 + min_inconsistency(0.10) → violation.
    # win_probability = entry(0.10) + edge(0.30) = 0.40 (the parent's implied fair value).
    parent = _market("p", "Will alpha wins the election?", 0.40, category="Politics")
    child = _market("c", "Will alpha takes state XYZ?", 0.10, category="Politics")
    results = _cross_strategy().scan([parent, child])

    implies = [r for r in results if r.side == "BUY" and r.strategy == "cross_market_arb"]
    assert implies, "expected an implication-violation BUY signal"
    r = implies[0]
    # PRE-FIX this was a hardcoded 0.85; the contract requires the reconstructed fair value.
    assert abs(r.confidence - 0.40) < 1e-9
    _assert_invariant(results)


def test_cross_market_low_fair_value_signal_is_gated_out_after_fix():
    """The behavioral payoff: a BUY whose true fair value (0.40) is below min_confidence
    (0.50) must now size to $0. PRE-FIX the hardcoded confidence=0.85 sailed through the
    gate and Kelly sized a real bet on a 40%-probability outcome."""
    parent = _market("p", "Will alpha wins the election?", 0.40, category="Politics")
    child = _market("c", "Will alpha takes state XYZ?", 0.10, category="Politics")
    results = _cross_strategy().scan([parent, child])
    r = next(r for r in results if r.side == "BUY")

    # Isolate the deterministic Kelly path (where the min_confidence gate lives); the
    # Monte-Carlo pricing enhancement is a separate stochastic re-estimate, not what the
    # confidence gate governs.
    kcfg = KellyConfig(use_monte_carlo=False)  # default min_confidence = 0.50
    assert kcfg.min_confidence == 0.50
    bet_usd, contracts = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_usd == 0.0 and contracts == 0.0, (
        "a signal whose fair value (0.40) is below min_confidence (0.50) must be gated out"
    )

    # Control: pre-fix the SAME signal with a hardcoded 0.85 confidence would NOT be gated —
    # prove the gate is what changed (fabricate the old confidence and confirm it sizes > 0).
    r.confidence = 0.85
    bet_usd_prefix, _ = size_from_scan_result(r, bankroll=1_000.0, config=kcfg)
    assert bet_usd_prefix > 0.0, "sanity: the pre-fix hardcoded confidence bypassed the gate"


# ── LogicalImplicationDetector (threshold-implication path) ──

def test_logical_implication_confidence_is_fair_value_not_chain_conf():
    # Two BTC threshold markets on the same entity: "above 150k" implies "above 100k".
    # Mispricing: P(above 150k)=0.40 > P(above 100k)=0.10 → BUY the 100k market.
    # edge = gap(0.30) * chain_conf(0.90) = 0.27; win_probability = 0.10 + 0.27 = 0.37.
    m_high = _market("h", "Will Bitcoin trade above $150,000 in 2025?", 0.40)
    m_low = _market("l", "Will Bitcoin trade above $100,000 in 2025?", 0.10)
    det = LogicalImplicationDetector(_DummyClient(), StrategyConfig(dry_run=True))
    results = det.scan([m_high, m_low])

    buys = [r for r in results if r.side == "BUY" and r.strategy == "logical_implication"]
    assert buys, "expected a transitive-implication BUY signal"
    _assert_invariant(results)
    # The specific fair value on the emitted BUY (PRE-FIX this was chain_conf=0.90).
    r = buys[0]
    assert abs(r.confidence - (r.entry_price + r.edge)) < 1e-9
    assert r.confidence < 0.50, "the 100k buy's true fair value is well below 0.50"
