"""test_real_data_validation.py — deterministic regression canary on REAL data (C3/F2/B2).

WHAT THIS TESTS
  1. Bit-for-bit reproduction on the committed 54-record Polymarket history fixture:
     two independent run_report() calls must produce identical seed_hash, PnL, and Brier.
  2. The seed_hash is pinned to a committed expected value — any drift (fixture edit,
     cost-model change, or engine change) fails LOUD here rather than silently.
  3. The crowd Brier is in a sane range and stable across two runs (sanity + determinism).
  4. The "0 trades because model_prob == market_price" property holds — this proves the
     engine is honest (does not bet when there is no edge), not that it is broken.
  5. Basic fixture integrity: exactly 54 records, all market_price in [0,1], binary outcomes.

HONEST SCOPE
These tests do NOT claim a model edge. They prove REPRODUCIBILITY and anchor the CROWD
BASELINE. A real edge requires a real model (ROADMAP track B); see data/README.md and
docs/autonomous-loop/OA11_REAL_DATA_VALIDATION.md for full context and known biases.

PINNED EXPECTED VALUES (as of 2026-06-28 run on real data, seed=42, default config):
  EXPECTED_SEED_HASH  = "44cc4fd8dd1aefc7"   (was "8dc358439ffb5746" before ROADMAP C6)
  EXPECTED_N_RECORDS  = 54
  EXPECTED_N_TRADES   = 0      (model_prob == market_price → no net edge → no bet)
  EXPECTED_CROWD_BRIER ≈ 0.0933  (crowd is very sharp; ~70% of markets pinned 2d before resolution)

If any of these change, the cause must be identified and these values updated explicitly —
no silent drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Mirror conftest.py: add backend root so absolute imports work.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.validate_real_history import load_fixture, run_report, crowd_baseline_brier  # noqa: E402

# ---------------------------------------------------------------------------
# Committed expected values — pin these explicitly so any drift fails loud.
# Discovered by running the real fixture through the engine on 2026-06-28.
# ---------------------------------------------------------------------------
#
# MIGRATION (2026-07-26, ROADMAP C6): this hash moved ONCE, deliberately, from
# "8dc358439ffb5746" to "44cc4fd8dd1aefc7". `_seed_hash` now fingerprints `market_categories`
# UNCONDITIONALLY, closing a reproducibility hole where two datasets identical in every
# fingerprinted field but differing only in category labels shared ONE hash with up to 3.9x
# different PnL. The DATA and the RESULT are unchanged — same 54 records, same 0 trades, same
# crowd Brier; only the fingerprint's input set widened. See
# docs/autonomous-loop/SEED_HASH_CATEGORY_MIGRATION.md.
EXPECTED_SEED_HASH = "44cc4fd8dd1aefc7"
EXPECTED_N_RECORDS = 54
EXPECTED_N_TRADES = 0          # model_prob == market_price → engine correctly makes 0 trades
EXPECTED_CROWD_BRIER = 0.09330668518518523   # crowd Brier on the 54-record fixture


class TestFixtureIntegrity:
    """Sanity checks on the raw fixture before any engine code runs."""

    def test_fixture_loads_expected_record_count(self):
        """The committed fixture must contain exactly 54 records."""
        markets = load_fixture()
        assert len(markets) == EXPECTED_N_RECORDS, (
            f"fixture record count changed: expected {EXPECTED_N_RECORDS}, got {len(markets)}"
        )

    def test_all_market_prices_in_unit_interval(self):
        """Every market_price (and model_prob) must be in [0, 1]."""
        markets = load_fixture()
        for m in markets:
            assert 0.0 <= m.market_price <= 1.0, (
                f"market_price out of [0,1]: market_id={m.market_id} price={m.market_price}"
            )
            assert 0.0 <= m.model_prob <= 1.0, (
                f"model_prob out of [0,1]: market_id={m.market_id} prob={m.model_prob}"
            )

    def test_outcomes_are_binary(self):
        """All outcomes must be 0 or 1 (binary resolution)."""
        markets = load_fixture()
        for m in markets:
            assert m.outcome in (0, 1), (
                f"non-binary outcome: market_id={m.market_id} outcome={m.outcome}"
            )

    def test_model_prob_equals_market_price_for_all_records(self):
        """model_prob == market_price for all records in this fixture.

        This is the structural property that guarantees 0 edge and 0 trades.
        The fixture README documents this explicitly: model_prob is the crowd
        baseline (== market_price) — zero edge by construction.
        """
        markets = load_fixture()
        for m in markets:
            assert m.model_prob == m.market_price, (
                f"model_prob != market_price for market_id={m.market_id}: "
                f"model_prob={m.model_prob}, market_price={m.market_price}"
            )


class TestDeterministicReproduction:
    """Bit-for-bit reproduction on REAL data: run twice, assert identical results."""

    def test_seed_hash_is_stable_across_two_runs(self):
        """The seed_hash must be identical on two independent run_report() calls.

        This anchors the DATA + CONFIG fingerprint on real (not synthetic) markets.
        If the hash changes, the fixture, cost model, or engine changed.
        """
        report_a = run_report()
        report_b = run_report()
        assert report_a["seed_hash"] == report_b["seed_hash"], (
            "seed_hash is not deterministic across two runs on the same fixture"
        )

    def test_seed_hash_equals_committed_expected_value(self):
        """The seed_hash must equal the pinned expected value from the initial real run.

        This is the regression gate: any drift fails LOUD here. If the engine or fixture
        legitimately changes, update EXPECTED_SEED_HASH with the new confirmed value.
        """
        report = run_report()
        assert report["seed_hash"] == EXPECTED_SEED_HASH, (
            f"seed_hash drifted: expected {EXPECTED_SEED_HASH!r}, got {report['seed_hash']!r}. "
            "Check if fixture, cost model, or walk-forward logic changed."
        )

    def test_pnl_is_identical_across_two_runs(self):
        """Total PnL and the weekly PnL series must be bit-identical on two runs."""
        report_a = run_report()
        report_b = run_report()
        assert report_a["total_pnl_usd"] == report_b["total_pnl_usd"], (
            "total_pnl_usd differs across runs — engine is not deterministic on real data"
        )
        assert report_a["weekly_pnl_series"] == report_b["weekly_pnl_series"], (
            "weekly_pnl_series differs across runs — engine is not deterministic on real data"
        )

    def test_crowd_brier_is_stable_across_two_runs(self):
        """The crowd Brier must be identical on two independent calls."""
        report_a = run_report()
        report_b = run_report()
        assert report_a["crowd_baseline_brier"] == report_b["crowd_baseline_brier"], (
            "crowd_baseline_brier differs across runs — Brier computation is not deterministic"
        )


class TestObservedBehavior:
    """Assert the REAL observed behavior of the engine on the fixture."""

    def test_zero_trades_because_model_equals_crowd(self):
        """The engine must make exactly 0 trades on this fixture.

        model_prob == market_price throughout, so there is no net edge above the
        min_edge threshold. This is correct behavior, not a bug. Pinning this as an
        assertion means any accidental introduction of a spurious edge in the default
        strategy will be caught immediately.
        """
        report = run_report()
        assert report["total_trades"] == EXPECTED_N_TRADES, (
            f"expected {EXPECTED_N_TRADES} trades (model==crowd), got {report['total_trades']}. "
            "If strategy logic changed, investigate whether the new trades reflect a real edge."
        )

    def test_crowd_brier_in_sane_range(self):
        """Crowd Brier must be in the sane range (0, 0.25).

        0 = perfect calibration, 0.25 = coin-flip baseline. The real fixture gives ~0.09,
        reflecting a sharp crowd on liquid markets sampled 2 days before resolution.
        Values outside (0, 0.25) would indicate a data or computation error.
        """
        report = run_report()
        brier = report["crowd_baseline_brier"]
        assert 0.0 < brier < 0.25, (
            f"crowd_baseline_brier={brier} is outside the sane range (0, 0.25)"
        )

    def test_crowd_brier_matches_committed_expected_value(self):
        """Crowd Brier must match the pinned expected value exactly.

        Any change to the fixture (even a single record) will change the Brier and
        fail this test. Update EXPECTED_CROWD_BRIER only after a verified fixture refresh.
        """
        report = run_report()
        assert report["crowd_baseline_brier"] == pytest.approx(EXPECTED_CROWD_BRIER, rel=1e-9), (
            f"crowd_baseline_brier drifted: expected {EXPECTED_CROWD_BRIER}, "
            f"got {report['crowd_baseline_brier']}. Fixture may have been modified."
        )
