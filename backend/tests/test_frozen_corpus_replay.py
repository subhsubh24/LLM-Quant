"""Frozen real-OOS corpus — offline reproducibility guard (ROADMAP F2 / backtest integrity).

The real N=hundreds Polymarket OOS corpus used to exist only as a live Gamma fetch, so a
*real* (not just synthetic) out-of-sample result could NOT be reproduced from committed
artifacts — the sole gap holding `backtest_integrity` below A+. This suite pins the frozen
corpus + its offline replay so a reviewer/CI can reproduce the EXACT real OOS result with no
egress:

  1. the committed corpus loads and is structurally leakage-safe;
  2. replaying it is bit-for-bit DETERMINISTIC (same seed -> same seed_hash + PnL);
  3. serialization round-trips losslessly (a clean, byte-stable git artifact);
  4. the frozen result is HONEST — it never claims a validated edge (the F10/F11 gates that
     rejected the live result must reject the frozen one identically);
  5. the #259 play-money guardrail still fires on the frozen path.

No network. Pure replay of committed bytes.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_real_oos as v  # noqa: E402
from app.prediction_markets import walk_forward as wf  # noqa: E402
from app.prediction_markets import calibration_bucket_strategy as cal  # noqa: E402

CORPUS = ROOT / "data" / "real_oos_corpus_polymarket.json"


def _load():
    return v.load_corpus_from_json(str(CORPUS), wf)


def test_committed_corpus_exists_and_loads():
    assert CORPUS.exists(), f"frozen corpus missing: {CORPUS}"
    markets = _load()
    # A real corpus of meaningful size — enough that a walk-forward has windows to run.
    assert len(markets) >= 50, f"frozen corpus too small ({len(markets)}) to be a useful OOS sample"


def test_committed_corpus_is_structurally_leakage_safe():
    """Every record must satisfy the HistoricalMarket invariants (the loader re-validates
    them through __post_init__, so a tampered corpus fails LOUD) and carry a resolution
    STRICTLY after its decision — the leak-guard boundary the fetcher enforces."""
    for m in _load():
        assert 0.0 <= m.market_price <= 1.0
        assert m.outcome in (0, 1)
        assert m.resolution_time > m.decision_time     # strictly-positive holding period (no free lunch)


def test_committed_corpus_is_real_money_only():
    """This is the REAL-MONEY floor lane's corpus — no play-money (research_only) record may
    be committed here (it would be refused by evaluate() anyway; this catches it at rest)."""
    assert all(not m.research_only for m in _load())


def test_committed_corpus_carries_category_metadata():
    """The freeze serializer captures `category` (which the older fetch serializer dropped),
    so the F10 regime-slice CATEGORY concentration check can run on the frozen corpus. The
    key must be present on every row (value may be None for an uncategorized market)."""
    rows = json.loads(CORPUS.read_text())
    assert rows and all("category" in r for r in rows)


def test_replay_is_deterministic():
    """Same corpus + same seed -> identical seed_hash AND identical PnL on both the crowd
    baseline and the B4a alpha. This is the reproduce-from-committed-artifacts guarantee."""
    markets = _load()
    r1 = v.evaluate(markets, wf, cal, seed=42, decision_lead_days=7.0)
    r2 = v.evaluate(markets, wf, cal, seed=42, decision_lead_days=7.0)
    assert r1["crowd_baseline"]["seed_hash"] == r2["crowd_baseline"]["seed_hash"]
    assert r1["calibration_alpha_b4a"]["seed_hash"] == r2["calibration_alpha_b4a"]["seed_hash"]
    assert r1["calibration_alpha_b4a"]["total_pnl_usd"] == r2["calibration_alpha_b4a"]["total_pnl_usd"]
    assert r1["crowd_baseline"]["total_pnl_usd"] == r2["crowd_baseline"]["total_pnl_usd"]


def test_crowd_baseline_is_a_tautology_on_real_data():
    """model_prob == crowd price on this corpus (naive baseline), so the baseline trades 0 —
    proving the frozen corpus carries no accidental injected edge in model_prob."""
    r = v.evaluate(_load(), wf, cal, seed=42, decision_lead_days=7.0)
    assert r["crowd_baseline"]["trades"] == 0


def test_frozen_result_never_claims_a_validated_edge():
    """HONESTY: the whole point is a REPRODUCIBLE real result, not an edge claim. Whatever
    the alpha does on this corpus, it must NOT be a validated edge — either it trades 0, or
    the F10 regime-slice flags it FRAGILE, or F11 finds it not-significant. A frozen corpus
    that silently reported a clean, significant, non-fragile edge would be exactly the
    'a great backtest that isn't real' trap; this guard makes that impossible to commit."""
    r = v.evaluate(_load(), wf, cal, seed=42, decision_lead_days=7.0)
    alpha = r["calibration_alpha_b4a"]
    sig = r["significance_alpha_f11"]
    regime = r["regime_slice_alpha"]
    not_validated = (
        alpha["trades"] == 0
        or regime["fragile"]
        or not sig["is_significant_edge"]
    )
    assert not_validated, (
        "frozen corpus reports a clean, non-fragile, F11-significant edge — that is a "
        "validated-edge claim and must NOT live in a committed backtest artifact without "
        "going through the full go-live gate"
    )
    # The human-readable verdict always ends with the honest disclaimer.
    assert "NOT a validated edge" in r["verdict"] or r["verdict"].startswith("NO EDGE")


def test_serialization_round_trips_losslessly(tmp_path):
    """load -> corpus_to_rows -> json file -> load -> corpus_to_rows is a FIXED POINT: the
    frozen artifact is byte-stable, so re-freezing the same corpus produces no spurious git
    diff (and no silent data drift on a re-serialize)."""
    rows1 = v.corpus_to_rows(_load())
    tmp = tmp_path / "roundtrip.json"
    tmp.write_text(json.dumps(rows1, indent=2, sort_keys=True) + "\n")
    rows2 = v.corpus_to_rows(v.load_corpus_from_json(str(tmp), wf))
    assert rows1 == rows2


def test_play_money_guardrail_holds_on_the_frozen_path():
    """#259 STRUCTURAL guardrail: even loaded from a frozen file, a research_only (play-money)
    record must be REFUSED by the real-money floor lane. Inject one and assert evaluate raises."""
    markets = _load()[:60]
    poisoned = markets + [wf.HistoricalMarket(
        market_id="playmoney-manifold-x",
        decision_time=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        resolution_time=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
        market_price=0.5, model_prob=0.5, outcome=1, research_only=True,
    )]
    with pytest.raises(ValueError, match="research_only"):
        v.evaluate(poisoned, wf, cal, seed=42)
