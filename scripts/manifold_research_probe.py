#!/usr/bin/env python3
"""manifold_research_probe.py — RESEARCH-ONLY probe: is a PLAY-money crowd beatable? (A8)

Fetches real resolved binary markets from Manifold's PUBLIC API (no credentials), assembles
leakage-safe records at a chosen decision lead, and reports the crowd's calibration (Brier +
reliability). The question A8 exists to answer: both real-money crowds we've measured
(Polymarket, Kalshi) are sharp (Brier ~0.08-0.09) — is Manifold's PLAY-money crowd *softer*,
i.e. where a calibration/reasoning method would first show an edge?

RESEARCH ONLY — PLAY MONEY. A Manifold finding validates the METHOD and NEVER counts toward
the profit floor, go-live eligibility, or any real-money decision. Every line of output is
labeled `research_only`. This script NEVER trades and NEVER touches money.

Usage: python scripts/manifold_research_probe.py [--limit 1000] [--max-pages 20]
                                                  [--decision-lead-days 7] [--json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _imp(a, b):
    try:
        return __import__(a, fromlist=["x"])
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        return __import__(b, fromlist=["x"])


def probe(markets, cal_mod) -> dict:
    """Pure analysis on already-fetched leakage-safe records (injectable for tests)."""
    n = len(markets)
    if n == 0:
        return {"research_only": True, "status": "no leakage-safe records "
                "(egress-blocked / lead too large / crowd never traded pre-decision)"}
    prices = [m.market_price for m in markets]
    outs = [m.outcome for m in markets]
    crowd_brier = sum((p - o) ** 2 for p, o in zip(prices, outs)) / n
    pinned = sum(1 for p in prices if p < 0.05 or p > 0.95) / n

    # B2 reliability / ECE on the crowd price itself (how well-calibrated is the play crowd?).
    curve = cal_mod.reliability_curve(prices, outs)
    ece = cal_mod.expected_calibration_error(curve)

    return {
        "research_only": True,
        "venue": "manifold (PLAY MONEY — never counts toward the real-money floor)",
        "n_markets": n,
        "yes_base_rate": round(sum(outs) / n, 4),
        "crowd_brier": round(crowd_brier, 4),
        "crowd_ece": round(ece, 4),
        "price_pinned_pct": round(pinned, 3),
        "price_median": round(statistics.median(prices), 4),
        "interpretation": (
            "Compare crowd_brier to the sharp real-money crowds (Polymarket/Kalshi ~0.08-0.09). "
            "A materially HIGHER Brier/ECE here = a softer, more-beatable crowd — a place to "
            "test a calibration/reasoning method. A method that beats THIS crowd but not the "
            "real-money crowds is an informative METHOD finding, NOT a real-money edge."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=1000, help="per-page market list size (<=1000)")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--decision-lead-days", type=float, default=7.0,
                    help="sample the decision price this many days before resolution")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mf = _imp("backend.app.prediction_markets.manifold_history_fetcher",
              "app.prediction_markets.manifold_history_fetcher")
    cal = _imp("backend.app.prediction_markets.calibration", "app.prediction_markets.calibration")

    fetcher = mf.ManifoldHistoryFetcher()
    resolved = fetcher.fetch_resolved_markets(limit=args.limit, max_pages=args.max_pages)
    markets = fetcher.build_historical_markets(resolved, timedelta(days=args.decision_lead_days))
    result = probe(markets, cal)
    result["resolved_binary_fetched"] = len(resolved)
    result["decision_lead_days"] = args.decision_lead_days

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("=== Manifold research probe (RESEARCH ONLY — PLAY MONEY) ===")
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
