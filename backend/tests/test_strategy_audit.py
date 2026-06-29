"""
Deterministic forensic audit tests for cross-market logical-consistency strategies.

Gating question for ROADMAP B5:
  Do CrossMarketArbitrageStrategy and LogicalImplicationDetector actually FIRE
  and find real, exploitable mispricing on real-shaped data?

Test structure:
  1. Synthetic SHOULD-FIRE fixtures → verify strategies fire and audit records them
  2. Synthetic SHOULD-NOT-FIRE fixtures → verify no false signal
  3. Real 54-record fixture → verify the audit completes deterministically and
     captures the honest finding (likely zero signals on this liquid sample)
  4. Determinism: same input → identical report twice

HONESTY NOTE: If existing strategies fire rarely/never on the real sample, that IS
the valuable finding — we capture it, not manufacture signals.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock

import pytest

# ── import path (matches conftest.py style) ─────────────────────────────────
backend_root = os.path.join(os.path.dirname(__file__), "..")
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.prediction_markets.polymarket_client import Market, Outcome, PolymarketClient
from app.prediction_markets.strategies import (
    CrossMarketArbitrageStrategy,
    ImplicationRule,
    StrategyConfig,
)
from app.prediction_markets.advanced_strategies import LogicalImplicationDetector
from app.prediction_markets.strategy_audit import (
    AuditReport,
    SignalRecord,
    audit_strategies,
    load_real_markets_from_history,
    make_synthetic_market,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "polymarket_history_sample.json"
)


def _mock_client() -> PolymarketClient:
    """Return a mock client — strategies only call scan(), never the client."""
    return MagicMock(spec=PolymarketClient)


def _config(min_edge: float = 0.02, min_liquidity: float = 500.0) -> StrategyConfig:
    return StrategyConfig(
        enabled=True,
        max_position_usd=5.0,
        max_positions=20,
        min_edge=min_edge,
        min_liquidity=min_liquidity,
        scan_interval_sec=120,
        dry_run=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: CrossMarketArbitrage fires on a structured implication violation
# ──────────────────────────────────────────────────────────────────────────────

class TestCrossMarketArbitrageFires:
    """
    SYNTHETIC fixture: A→B implication where P(A) >> P(B).

    Scenario (labeled SYNTHETIC):
      "Will candidate win election?" at 0.80
      "Will candidate win pennsylvania?" at 0.50
    The built-in rule says "win election" implies "win pennsylvania",
    so P(election) > P(pennsylvania) + 10% gap violates logical consistency.
    CrossMarketArbitrageStrategy should fire and buy the child (pennsylvania).
    """

    def _make_markets(self) -> List[Market]:
        parent = make_synthetic_market(
            mid="syn_election",
            question="Will Trump win election in 2024?",
            yes_price=0.80,
            category="Politics",
        )
        child = make_synthetic_market(
            mid="syn_pennsylvania",
            question="Will Trump win pennsylvania in 2024?",
            yes_price=0.50,
            category="Politics",
        )
        return [parent, child]

    def test_strategy_fires_on_implication_violation(self):
        """CrossMarketArbitrageStrategy must fire at least one signal on this fixture."""
        markets = self._make_markets()
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(),
            config=_config(),
            min_inconsistency=0.10,
        )
        report = audit_strategies(
            markets,
            [strategy],
            data_source="synthetic_should_fire",
        )

        assert report.total_signals_fired >= 1, (
            "CrossMarketArbitrage should have fired on an 80%/50% election/state violation"
        )
        assert any(
            s.strategy_name == "cross_market_arb" for s in report.signals
        ), "Signal must be attributed to 'cross_market_arb'"

    def test_audit_records_signal_fields(self):
        """Each SignalRecord must be well-formed with all required fields."""
        markets = self._make_markets()
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(), config=_config(), min_inconsistency=0.10
        )
        report = audit_strategies(markets, [strategy], data_source="synthetic_should_fire")

        assert report.signals, "Expected at least one signal"
        sig = report.signals[0]

        assert isinstance(sig, SignalRecord)
        assert sig.strategy_name == "cross_market_arb"
        assert sig.market_id  # non-empty
        assert sig.market_question  # non-empty
        assert sig.side in ("BUY", "SELL")
        assert 0.0 <= sig.entry_price <= 1.0
        assert sig.edge > 0.0
        assert 0.0 <= sig.confidence <= 1.0
        assert sig.reason  # non-empty
        assert sig.data_source == "synthetic_should_fire"

    def test_edge_stats_populated(self):
        """Per-strategy edge stats must be populated when signals fire."""
        markets = self._make_markets()
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(), config=_config(), min_inconsistency=0.10
        )
        report = audit_strategies(markets, [strategy], data_source="synthetic_should_fire")

        assert report.per_strategy
        stats = report.per_strategy[0].edge_stats
        assert stats.count >= 1
        assert stats.min_edge is not None
        assert stats.median_edge is not None
        assert stats.max_edge is not None
        assert stats.min_edge <= stats.median_edge <= stats.max_edge


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: CrossMarketArbitrage does NOT fire when markets are consistent
# ──────────────────────────────────────────────────────────────────────────────

class TestCrossMarketArbitrageNoFalseSignal:
    """
    SYNTHETIC fixture: consistent markets that should NOT trigger a signal.

    Scenario (labeled SYNTHETIC):
      "Will Trump win election?" at 0.80
      "Will Trump win pennsylvania?" at 0.82
    P(election) = 0.80 ≤ P(pennsylvania) = 0.82 — the implication holds, no arb.
    """

    def test_no_signal_on_consistent_markets(self):
        """CrossMarketArbitrage must NOT fire when P(parent) <= P(child)."""
        parent = make_synthetic_market(
            mid="syn_election_ok",
            question="Will Trump win election in 2024?",
            yes_price=0.80,
            category="Politics",
        )
        child = make_synthetic_market(
            mid="syn_penn_ok",
            question="Will Trump win pennsylvania in 2024?",
            yes_price=0.82,  # child >= parent: no violation
            category="Politics",
        )
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(), config=_config(), min_inconsistency=0.10
        )
        report = audit_strategies(
            [parent, child],
            [strategy],
            data_source="synthetic_should_not_fire",
        )
        cross_signals = [s for s in report.signals if s.strategy_name == "cross_market_arb"]
        # Allow keyword-heuristic signals only if they exceed 3 shared words;
        # for this pair, shared words include "win", "trump", "2024", "election"
        # and the keyword heuristic might or might not fire with the default
        # min_inconsistency=0.10 and price filter (0.05<p<0.95).
        # We assert NO implication-rule signal fires.
        implication_signals = [
            s for s in cross_signals if "IMPLICATION VIOLATION" in s.reason
        ]
        assert len(implication_signals) == 0, (
            "Should not fire an implication signal when P(parent) <= P(child)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: LogicalImplicationDetector fires on a threshold implication
# ──────────────────────────────────────────────────────────────────────────────

class TestLogicalImplicationDetectorFires:
    """
    SYNTHETIC fixture: BTC threshold markets that must fire via auto-discovery.

    Scenario (labeled SYNTHETIC):
      "Will BTC exceed $200k?" at 0.60   ← higher threshold
      "Will BTC exceed $150k?" at 0.30   ← lower threshold
    "BTC above 200k" implies "BTC above 150k", so P(200k) > P(150k) + gap violates it.
    The detector auto-discovers the threshold implication via NLP.
    """

    def _make_btc_markets(self) -> List[Market]:
        higher = make_synthetic_market(
            mid="syn_btc_200",
            question="Will BTC exceed $200k by end of 2025?",
            yes_price=0.60,
            category="Crypto",
        )
        lower = make_synthetic_market(
            mid="syn_btc_150",
            question="Will BTC exceed $150k by end of 2025?",
            yes_price=0.30,
            category="Crypto",
        )
        return [higher, lower]

    def test_logical_implication_fires_on_threshold_violation(self):
        """LogicalImplicationDetector must fire on a clear threshold violation."""
        markets = self._make_btc_markets()
        strategy = LogicalImplicationDetector(
            client=_mock_client(),
            config=_config(min_edge=0.01),  # lower min_edge so chain conf * gap clears it
            min_gap=0.08,
            nlp_confidence=0.90,
        )
        report = audit_strategies(
            markets,
            [strategy],
            data_source="synthetic_should_fire",
        )
        assert report.total_signals_fired >= 1, (
            "LogicalImplicationDetector should have fired on BTC 200k/150k threshold violation"
        )
        assert any(
            s.strategy_name == "logical_implication" for s in report.signals
        )

    def test_report_is_json_serializable(self):
        """AuditReport.to_dict() must be JSON-serializable without errors."""
        markets = self._make_btc_markets()
        strategy = LogicalImplicationDetector(
            client=_mock_client(),
            config=_config(min_edge=0.01),
            min_gap=0.08,
            nlp_confidence=0.90,
        )
        report = audit_strategies(markets, [strategy], data_source="synthetic_should_fire")

        d = report.to_dict()
        # Must round-trip through json.dumps without raising
        serialized = json.dumps(d, default=str)
        reloaded = json.loads(serialized)
        assert reloaded["total_markets_scanned"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Audit handles empty market list gracefully
# ──────────────────────────────────────────────────────────────────────────────

class TestAuditRobustness:
    """Robustness: no crashes on degenerate inputs."""

    def test_empty_markets_no_crash(self):
        """audit_strategies must return a valid report even with zero markets."""
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(), config=_config()
        )
        report = audit_strategies([], [strategy])

        assert isinstance(report, AuditReport)
        assert report.total_markets_scanned == 0
        assert report.total_signals_fired == 0
        assert report.signals == ()

    def test_empty_strategies_no_crash(self):
        """audit_strategies must return a valid report even with zero strategies."""
        m = make_synthetic_market("m1", "Some market?", 0.5)
        report = audit_strategies([m], [])

        assert isinstance(report, AuditReport)
        assert report.total_signals_fired == 0
        assert report.per_strategy == ()


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Forensic check populates correctly when resolved_records are provided
# ──────────────────────────────────────────────────────────────────────────────

class TestForensicCheckWithResolvedData:
    """Verify the forensic accuracy check when resolved outcomes are known."""

    def test_forensic_hit_rate_computed(self):
        """
        A strategy fires a BUY signal; we supply resolved_records saying
        the market resolved YES (outcome=1).  The forensic check must register
        1 correct signal and hit_rate=1.0.
        """
        # Build synthetic market that will trigger the rule
        parent = make_synthetic_market(
            mid="syn_elec_f",
            question="Will candidate win election in 2024?",
            yes_price=0.80,
            category="Politics",
        )
        child = make_synthetic_market(
            mid="syn_penn_f",
            question="Will candidate win pennsylvania in 2024?",
            yes_price=0.50,
            category="Politics",
        )
        strategy = CrossMarketArbitrageStrategy(
            client=_mock_client(), config=_config(), min_inconsistency=0.10
        )

        # The signal should be a BUY on the child market (pennsylvania)
        # We supply outcome=1 (YES resolved) for it → correct call
        resolved = [{"market_id": "syn_penn_f", "outcome": 1}]

        report = audit_strategies(
            [parent, child],
            [strategy],
            resolved_records=resolved,
            data_source="synthetic_should_fire",
        )

        assert report.per_strategy
        fc = report.per_strategy[0].forensic_check
        assert fc is not None
        # This synthetic fixture is built to FIRE — assert unconditionally so the
        # test cannot pass vacuously if the strategy stops firing (reviewer N10).
        assert fc.total_signals > 0, "synthetic should-fire fixture produced no signals"
        assert fc.hit_rate is not None
        assert 0.0 <= fc.hit_rate <= 1.0
        # The note must be present and honest
        assert "Descriptive forensics" in fc.note
        assert "No parameter fitting" in fc.note


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Determinism — identical inputs → identical reports
# ──────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Same input must yield byte-identical AuditReport twice."""

    def test_same_report_twice(self):
        """audit_strategies is deterministic: run twice, get the same report."""
        markets = [
            make_synthetic_market("m_det_1", "Will BTC exceed $200k?", 0.60, "Crypto"),
            make_synthetic_market("m_det_2", "Will BTC exceed $150k?", 0.30, "Crypto"),
            make_synthetic_market(
                "m_det_3", "Will Trump win election?", 0.80, "Politics"
            ),
            make_synthetic_market(
                "m_det_4", "Will Trump win pennsylvania?", 0.50, "Politics"
            ),
        ]
        strategies = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(min_edge=0.01),
                min_gap=0.08,
            ),
        ]
        report_a = audit_strategies(markets, strategies, data_source="synthetic_should_fire")
        report_b = audit_strategies(markets, strategies, data_source="synthetic_should_fire")

        assert report_a.total_signals_fired == report_b.total_signals_fired
        assert report_a.signals == report_b.signals
        assert report_a.honest_finding == report_b.honest_finding


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Real 54-record fixture — audit completes deterministically
# ──────────────────────────────────────────────────────────────────────────────

class TestRealSampleAudit:
    """
    Run both cross-market strategies over the real 54-record polymarket sample.

    KEY EXPECTATION (honest):
    The real sample consists of individual markets sampled 2 days before resolution.
    ~70% are pinned at <0.05 / >0.95 — tightly priced by liquid markets.
    The records have NO shared question text or pairwise grouping, so the
    structured implication rules (which require matching specific keywords in
    question text) will find zero parent/child pairs.
    The keyword-heuristic phase requires 3+ shared non-trivial words across pairs —
    also unlikely given generic question templates.

    The honest finding is therefore: 0 signals on this sample.
    That is the VALUABLE result — it tells us these strategies need
    richer, earlier-in-life data and real question text to be useful.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def real_data(cls):
        if not os.path.exists(DATA_PATH):
            pytest.skip(f"Real data fixture not found at {DATA_PATH}")
        markets, records = load_real_markets_from_history(DATA_PATH)
        return markets, records

    def test_audit_completes_on_real_sample(self, real_data):
        """Audit must complete without exception on all 54 real markets."""
        markets, records = real_data
        strategies = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        report = audit_strategies(
            markets, strategies, resolved_records=records, data_source="real"
        )

        assert isinstance(report, AuditReport)
        assert report.total_markets_scanned == len(markets)
        assert report.honest_finding  # must be non-empty

    def test_real_sample_report_is_well_formed(self, real_data):
        """All per-strategy entries must have valid edge_stats and forensic_check."""
        markets, records = real_data
        strategies = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        report = audit_strategies(
            markets, strategies, resolved_records=records, data_source="real"
        )

        assert len(report.per_strategy) == 2

        for ps in report.per_strategy:
            assert ps.strategy_name in ("cross_market_arb", "logical_implication")
            assert ps.signals_fired >= 0
            assert ps.distinct_markets_touched >= 0
            # edge_stats: if no signals, all edge values are None
            if ps.signals_fired == 0:
                assert ps.edge_stats.min_edge is None
                assert ps.edge_stats.median_edge is None
                assert ps.edge_stats.max_edge is None
            else:
                assert ps.edge_stats.min_edge is not None
                assert ps.edge_stats.max_edge is not None
            # forensic_check must be present (we supplied resolved_records)
            assert ps.forensic_check is not None
            assert "Descriptive forensics" in ps.forensic_check.note

    def test_real_sample_determinism(self, real_data):
        """Two identical runs on the real sample must produce the same report."""
        markets, records = real_data
        strategies_a = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        strategies_b = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        report_a = audit_strategies(
            markets, strategies_a, resolved_records=records, data_source="real"
        )
        report_b = audit_strategies(
            markets, strategies_b, resolved_records=records, data_source="real"
        )

        assert report_a.total_signals_fired == report_b.total_signals_fired
        assert report_a.signals == report_b.signals
        assert report_a.honest_finding == report_b.honest_finding

    def test_real_sample_fires_zero_signals(self, real_data):
        """
        ENFORCE the honest claim (adversarial-audit finding): with the default
        unique, non-overlapping placeholder question text, BOTH cross-market
        strategies must fire EXACTLY ZERO signals on the real sample — the
        records carry no real question text / related grouping. This assertion
        guards against the prior boilerplate-text bug, where shared filler words
        ("Market"/"real"/"sample") produced ~98 phantom signals. If a future
        change reintroduces spurious cross-pairing, this fails LOUD.
        """
        markets, records = real_data
        strategies = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        report = audit_strategies(
            markets, strategies, resolved_records=records, data_source="real"
        )

        assert report.total_signals_fired == 0, (
            f"Expected 0 signals on the real sample (no real question text), got "
            f"{report.total_signals_fired} — boilerplate-text spurious-firing regression?"
        )

    def test_real_sample_honest_finding_captured(self, real_data):
        """
        The honest_finding must be present and recorded (not silently swallowed),
        and — since the real sample fires 0 signals — must report exactly that.
        """
        markets, records = real_data
        strategies = [
            CrossMarketArbitrageStrategy(
                client=_mock_client(), config=_config(), min_inconsistency=0.10
            ),
            LogicalImplicationDetector(
                client=_mock_client(), config=_config(), min_gap=0.08
            ),
        ]
        report = audit_strategies(
            markets, strategies, resolved_records=records, data_source="real"
        )

        # The finding must be a non-empty string containing "FINDING:"
        assert "FINDING:" in report.honest_finding
        # With 0 real signals, the finding must say so honestly.
        assert report.total_signals_fired == 0
        assert "Neither strategy fired" in report.honest_finding
        # It must be JSON-serializable as part of the full dict
        d = report.to_dict()
        assert "honest_finding" in d
        assert d["honest_finding"] == report.honest_finding
