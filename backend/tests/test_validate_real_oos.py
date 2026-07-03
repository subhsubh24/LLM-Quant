"""Deterministic test for the real-data OOS validator's core (no network).

Locks that `evaluate()`: (1) returns a well-formed report, (2) the crowd baseline trades 0
(model_prob==crowd is a tautology), and (3) the B4a calibration alpha RECOVERS a known injected
edge (so a green result means the validator can actually detect an edge, not just report null)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import validate_real_oos as v  # noqa: E402
from app.prediction_markets import walk_forward as wf  # noqa: E402
from app.prediction_markets import calibration_bucket_strategy as cal  # noqa: E402


def _synthetic(n: int = 300):
    """Crowd prices every market at 0.5 but 70% resolve YES — a real, learnable injected edge."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    out = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0
        out.append(wf.HistoricalMarket(
            market_id=f"syn{i}",
            decision_time=base + dt.timedelta(days=i),
            resolution_time=base + dt.timedelta(days=i + 1),
            market_price=0.5, model_prob=0.5, outcome=outcome,
        ))
    return out


def test_report_shape_and_baseline_is_a_tautology():
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    assert {"corpus", "crowd_baseline", "calibration_alpha_b4a", "verdict"} <= set(r)
    assert r["crowd_baseline"]["trades"] == 0            # model_prob == crowd -> no edge -> 0 trades
    assert r["corpus"]["n_markets"] == 300


def test_alpha_recovers_a_known_injected_edge():
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    alpha = r["calibration_alpha_b4a"]
    assert alpha["trades"] > 0                            # the calibration model finds the 0.5-vs-0.7 gap
    assert alpha["total_pnl_usd"] > 0                     # and profits from it OOS
    assert "validated edge" in r["verdict"]               # honest: recovering a synthetic edge is NOT a validated one


def test_report_includes_regime_slice_and_flags_concentration():
    """ROADMAP F10 wiring: a run where the alpha trades carries a regime-slice report so a
    concentrated (fragile) edge cannot hide behind the aggregate number. The _synthetic()
    corpus is priced at a single level (0.5) with a single 1-day horizon, so the alpha's
    entire edge concentrates in ONE confidence/horizon bucket — which the guard MUST flag
    fragile (the anti-overfitting point: this aggregate edge is not regime-robust)."""
    r = v.evaluate(_synthetic(), wf, cal, seed=42)
    assert "regime_slice_alpha" in r
    rs = r["regime_slice_alpha"]
    assert rs["n_trades"] == r["calibration_alpha_b4a"]["trades"] > 0
    assert isinstance(rs["fragile"], bool) and isinstance(rs["fragile_reasons"], list)
    # A single-price, single-horizon corpus is maximally concentrated → fragile with reasons.
    assert rs["fragile"] is True
    assert len(rs["fragile_reasons"]) > 0
    assert rs["has_positive_edge"] is True
    # With a positive edge the concentration shares are real numbers (not fabricated Nones).
    assert rs["top_confidence_bucket_pnl_share"] is not None
    # And the fragility is surfaced in the human-readable verdict.
    assert "FRAGILE" in r["verdict"]


def test_regime_slice_absent_edge_reports_no_shares():
    """When the alpha does not trade (calibrated crowd), the regime report is present,
    empty, and honestly reports no positive edge / null concentration shares."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    markets = [wf.HistoricalMarket(market_id=f"c{i}", decision_time=base + dt.timedelta(days=i),
                                   resolution_time=base + dt.timedelta(days=i + 1),
                                   market_price=0.7, model_prob=0.7, outcome=1 if (i % 10) < 7 else 0)
               for i in range(300)]
    r = v.evaluate(markets, wf, cal, seed=42)
    rs = r["regime_slice_alpha"]
    assert rs["n_trades"] == 0
    assert rs["fragile"] is False              # no positive edge → nothing to flag
    assert rs["top_market_pnl_share"] is None  # never fabricated when there is no PnL


def test_no_edge_verdict_on_calibrated_crowd():
    """A well-calibrated crowd (price == outcome-rate) gives the alpha nothing -> 0 trades, NO-EDGE verdict."""
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    # price 0.7, 70% YES => crowd is right; alpha should abstain/not-beat -> 0 trades
    markets = [wf.HistoricalMarket(market_id=f"c{i}", decision_time=base + dt.timedelta(days=i),
                                   resolution_time=base + dt.timedelta(days=i + 1),
                                   market_price=0.7, model_prob=0.7, outcome=1 if (i % 10) < 7 else 0)
               for i in range(300)]
    r = v.evaluate(markets, wf, cal, seed=42)
    assert r["calibration_alpha_b4a"]["trades"] == 0
    assert "NO EDGE" in r["verdict"]
