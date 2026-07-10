#!/usr/bin/env python3
"""per_category_edge_search.py — where, if anywhere, is a crowd beatable? (ROADMAP B9)

Fetches a real leakage-safe resolved-market corpus (Polymarket by default; no credentials),
then measures the crowd's calibration PER market_category and ranks categories by how
miscalibrated (plausibly beatable) the crowd looks. The aggregate crowd Brier (~0.08-0.09)
is dragged down by systematically-sharp categories (Sports, near-certain Crypto), so this
per-category map is how a real edge in a less-efficient category (niche politics, long-horizon
econ) becomes visible instead of hiding behind the aggregate.

DIAGNOSTIC ONLY — it never trades or fits a model, so it cannot p-hack a PnL. A high-ECE
category is a CANDIDATE to target with a real alpha, NOT a validated edge: a downstream
per-category edge test must use the reported Bonferroni-corrected alpha and still pass B2 +
F10 + F11 OOS. Runs anywhere the venue is reachable.

Usage: python scripts/per_category_edge_search.py [--limit 100] [--max-pages 20]
                                                   [--decision-lead-days 7] [--min-category-n 30] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _imp(a, b):
    try:
        return __import__(a, fromlist=["x"])
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        return __import__(b, fromlist=["x"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--decision-lead-days", type=float, default=7.0)
    ap.add_argument("--min-category-n", type=int, default=30)
    ap.add_argument(
        "--tag",
        default=None,
        help=(
            "Gamma server-side category filter (e.g. 'Sports'). Breaks the volumeNum "
            "per-category sampling ceiling: without it, volume-ordering fills the pages "
            "with globally-highest-volume markets and starves a niche category to a thin "
            "slice (the EXP-005 Sports N~135 problem). Pre-register the tag before running."
        ),
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pmf = _imp("backend.app.prediction_markets.polymarket_history_fetcher",
               "app.prediction_markets.polymarket_history_fetcher")
    diag = _imp("backend.app.prediction_markets.per_category_diagnostics",
                "app.prediction_markets.per_category_diagnostics")

    fetcher = pmf.PolymarketHistoryFetcher()
    resolved = fetcher.fetch_resolved_markets(
        limit=args.limit, max_pages=args.max_pages, order="volumeNum", tag=args.tag
    )
    markets = fetcher.build_historical_markets(resolved, timedelta(days=args.decision_lead_days))
    report = diag.per_category_calibration(markets, min_category_n=args.min_category_n)

    out = {
        "n_markets": report.n_markets,
        "aggregate_crowd_brier": report.aggregate_crowd_brier,
        "n_categories_assessed": report.n_categories_assessed,
        "bonferroni_alpha": report.bonferroni_alpha,
        "most_beatable": report.most_beatable,
        "categories": [asdict(c) for c in report.categories],
        "note": report.note,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("=== Per-category crowd calibration (B9 — DIAGNOSTIC, not an edge) ===")
        print(f"  n_markets={out['n_markets']} aggregate_crowd_brier={out['aggregate_crowd_brier']} "
              f"most_beatable={out['most_beatable']} bonferroni_alpha={out['bonferroni_alpha']}")
        for c in out["categories"]:
            print(f"  [{'ok ' if c['sufficient'] else 'n<min'}] {c['category']:<14} n={c['n']:<5} "
                  f"brier={c['crowd_brier']:<8} ece={c['crowd_ece']:<8} base={c['base_rate']:<7} "
                  f"pinned={c['pinned_pct']}")
        print(f"\n  {out['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
