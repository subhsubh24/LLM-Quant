#!/usr/bin/env python3
"""fetch_kalshi_history.py — pull REAL leakage-safe resolved-Kalshi history (ROADMAP A3).

This is the driver the owner (or a network-permitted host) runs to produce a
leakage-safe ``HistoricalMarket`` dataset from Kalshi's PUBLIC resolved markets.
No credentials are required — Kalshi market data is public.

HONESTY — read before trusting any number this enables:
  * ``market_price`` is a genuine pre-resolution price tick at/before ``decision_time``
    (the fetcher RAISES rather than fabricating; the settled result is NEVER the
    decision price). This is leakage-safe by construction.
  * ``model_prob`` is seeded to the crowd price (``market_price``) — a NAIVE BASELINE
    with ZERO edge by construction. A real validated edge requires a real model that
    OVERRIDES ``model_prob`` with an independent decision-time estimate (ROADMAP track B).
  * SELECTION / SURVIVORSHIP BIAS: only unambiguously resolved markets (status finalized,
    result yes/no) are kept; ``--decision-lead-days`` is PRE-REGISTERED here (not tuned
    after seeing PnL). Any eval on this sample overstates crowd calibration.

DEEP HISTORICAL TIER (``--historical``): Kalshi's LIVE ``/markets?status=settled`` feed
only serves a rolling ~3-month window (``GET /historical/cutoff``), so the default fetch
sees only recent, sports-heavy markets. ``--historical`` queries the SEPARATE public
``/historical/*`` tier (no auth) that reaches MULTI-YEAR resolved history — the depth that
funds a real Kalshi OOS corpus. Pair it with ``--series-ticker`` to target a category
(e.g. ``KXJOBLESS`` weekly initial-jobless-claims; ``KXECONSTATU3`` monthly unemployment).

Usage:
  # deep employment-category corpus (the NBER-flagged weakest-calibrated Kalshi segment):
  python3 scripts/fetch_kalshi_history.py --out data/kalshi_jobless.json \\
      --historical --series-ticker KXJOBLESS --max-pages 3 --decision-lead-days 3
  # default (live rolling window):
  python3 scripts/fetch_kalshi_history.py --out data/kalshi_history.json \\
      --limit 200 --max-pages 2 --decision-lead-days 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.kalshi_history_fetcher import (  # noqa: E402
    KalshiHistoryFetcher,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/kalshi_history.json",
                    help="output file path (JSON)")
    ap.add_argument("--limit", type=int, default=200,
                    help="markets per Kalshi API page")
    ap.add_argument("--max-pages", type=int, default=5,
                    help="BOUND on paging (never unbounded)")
    ap.add_argument("--decision-lead-days", type=float, default=7.0,
                    help="decision_time = resolution_time - this "
                         "(PRE-REGISTER; do not tune on PnL)")
    ap.add_argument("--categories", nargs="*", default=None,
                    help="keep only these categories (PRE-REGISTER before seeing results)")
    ap.add_argument("--series-ticker", default=None,
                    help="restrict to ONE Kalshi series (e.g. KXJOBLESS) — required in "
                         "practice to reach a target category on the historical tier")
    ap.add_argument("--historical", action="store_true",
                    help="query Kalshi's deep /historical/* tier (multi-year resolved "
                         "history) instead of the live ~3-month rolling window")
    ap.add_argument("--merge", action="store_true",
                    help="union new records into an existing --out file "
                         "(dedupe by ticker/market_id) so a scheduled refresh "
                         "ACCUMULATES a growing OOS corpus instead of overwriting")
    args = ap.parse_args()

    lead = timedelta(days=args.decision_lead_days)
    f = KalshiHistoryFetcher()

    print(
        f"fetching resolved Kalshi markets "
        f"(limit={args.limit}, max_pages={args.max_pages}) ..."
    )
    resolved = f.fetch_resolved_markets(
        limit=args.limit,
        max_pages=args.max_pages,
        categories=args.categories,
        series_ticker=args.series_ticker,
        historical=args.historical,
    )
    print(f"  -> {len(resolved)} unambiguously-settled binary markets")

    print(f"building leakage-safe records (decision_lead={args.decision_lead_days}d) ...")
    markets = f.build_historical_markets(resolved, lead, historical=args.historical)
    skipped = len(resolved) - len(markets)
    print(
        f"  -> {len(markets)} leakage-safe HistoricalMarket records "
        f"({skipped} skipped: no pre-decision tick)"
    )

    if not markets:
        print(
            "NO records built — every market was too short-lived for the lead, or "
            "egress is blocked. Nothing written.",
            file=sys.stderr,
        )
        return 1

    rows = [
        {
            "market_id": m.market_id,
            "decision_time": m.decision_time.isoformat(),
            "resolution_time": m.resolution_time.isoformat(),
            "market_price": m.market_price,
            "model_prob": m.model_prob,  # crowd baseline; a real model overrides this
            "outcome": m.outcome,
            "category": m.category,  # for per-category (B9/EXP-009) calibration diagnostics
        }
        for m in markets
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.merge and out.exists():
        existing = json.loads(out.read_text())
        by_id = {r["market_id"]: r for r in existing}
        before = len(by_id)
        for r in rows:
            by_id.setdefault(r["market_id"], r)  # keep the FIRST capture (never overwrite)
        rows = sorted(by_id.values(), key=lambda r: r["market_id"])
        print(f"merged: {before} existing + {len(rows) - before} new = {len(rows)} total")

    out.write_text(json.dumps(rows, indent=2, sort_keys=True))
    print(f"wrote {len(rows)} records -> {out}")
    print(
        "NOTE: model_prob is the crowd baseline (no edge). Feed --data to "
        "scripts/run_walk_forward.py to validate the PIPELINE on real data; a real "
        "EDGE still needs a real model (ROADMAP track B)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
