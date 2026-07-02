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
