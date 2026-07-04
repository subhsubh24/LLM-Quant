#!/usr/bin/env python3
"""fetch_polymarket_history.py — pull REAL leakage-safe resolved-Polymarket history (OA-11).

This is the driver the owner (or a network-permitted loop run) executes to satisfy
PENDING_OPS **OA-11**: the autonomous build env blocks egress to Polymarket, so the
leakage-safe fetcher (`prediction_markets/polymarket_history_fetcher.py`) cannot pull
real history there. Run this where Polymarket's PUBLIC Gamma + CLOB APIs are reachable
(no credentials needed — read-only public data) to produce a real, committed
`HistoricalMarket` dataset for the walk-forward + calibration evals.

HONESTY — read before trusting any number this enables:
  * The dataset's `market_price` is a genuine pre-resolution CLOB tick at/before
    `decision_time` (the fetcher RAISES rather than fabricating; settled outcome is
    NEVER the decision price). This is leakage-safe by construction.
  * `model_prob` is seeded to the crowd price (`market_price`) — a NAIVE BASELINE with
    ZERO edge by construction. A real validated edge requires a real model that
    OVERRIDES `model_prob` with an independent decision-time estimate (ROADMAP track B).
    So a walk-forward on this file proves the PIPELINE runs on real data; it does NOT,
    by itself, demonstrate an edge. Do not let a ~0 (or cost-negative) result be read
    as either success or failure of a strategy that does not exist yet.
  * SELECTION/SURVIVORSHIP BIAS: only unambiguously-settled binary markets are kept;
    `--decision-lead` is PRE-REGISTERED here (not tuned after seeing PnL). Any eval on
    this sample overstates crowd calibration and must say so.

Usage:
  python3 scripts/fetch_polymarket_history.py --out data/polymarket_history.json \
      --limit 100 --max-pages 10 --decision-lead-days 7 [--min-volume 5000]

  NOTE: Gamma silently caps each page at 100 rows regardless of --limit, so the
  effective corpus size is ~min(--limit, 100) * --max-pages. GROW the corpus via
  --max-pages, not --limit (a larger --limit alone still yields one 100-row page).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.polymarket_history_fetcher import (  # noqa: E402
    PolymarketHistoryFetcher,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/polymarket_history.json")
    ap.add_argument("--limit", type=int, default=100,
                    help="markets per Gamma page (Gamma caps each page at 100 regardless)")
    ap.add_argument("--max-pages", type=int, default=10,
                    help="BOUND on paging (never unbounded); grow the corpus via THIS, not --limit")
    ap.add_argument("--order", default="volumeNum",
                    help="Gamma sort field (desc). 'volumeNum' harvests markets that actually "
                         "traded; the fetcher default 'endDate' surfaces never-traded junk.")
    ap.add_argument("--decision-lead-days", type=float, default=7.0,
                    help="decision_time = resolution_time - this (PRE-REGISTER; do not tune on PnL)")
    ap.add_argument("--min-volume", type=float, default=0.0,
                    help="keep only resolved markets with at least this much volume")
    ap.add_argument("--fidelity", type=int, default=60, help="CLOB price sampling, minutes")
    ap.add_argument("--merge", action="store_true",
                    help="union new records into an existing --out file (dedupe by market_id) so a "
                         "scheduled refresh ACCUMULATES a growing OOS corpus instead of overwriting "
                         "the latest top-volume snapshot")
    args = ap.parse_args()

    lead = timedelta(days=args.decision_lead_days)
    f = PolymarketHistoryFetcher()

    print(f"fetching resolved markets (limit={args.limit}, max_pages={args.max_pages}, order={args.order}) ...")
    resolved = f.fetch_resolved_markets(limit=args.limit, max_pages=args.max_pages, order=args.order)
    print(f"  -> {len(resolved)} unambiguously-settled binary markets")

    if args.min_volume > 0:
        kept = [r for r in resolved if r.volume >= args.min_volume]
        print(f"  -> {len(kept)} after min-volume>={args.min_volume:g} filter")
        resolved = kept

    print(f"building leakage-safe records (decision_lead={args.decision_lead_days}d) ...")
    markets = f.build_historical_markets(resolved, lead, fidelity=args.fidelity)
    print(f"  -> {len(markets)} leakage-safe HistoricalMarket records "
          f"({len(resolved) - len(markets)} skipped: no pre-decision tick)")

    if not markets:
        print("NO records built — every market was too short-lived for the lead, or "
              "egress is blocked. Nothing written.", file=sys.stderr)
        return 1

    rows = [
        {
            "market_id": m.market_id,
            "decision_time": m.decision_time.isoformat(),
            "resolution_time": m.resolution_time.isoformat(),
            "market_price": m.market_price,
            "model_prob": m.model_prob,  # == crowd baseline; a real model overrides this
            "outcome": m.outcome,
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
            by_id.setdefault(r["market_id"], r)  # keep the FIRST capture of a market (never overwrite history)
        rows = sorted(by_id.values(), key=lambda r: r["market_id"])
        print(f"merged: {before} existing + {len(rows) - before} new = {len(rows)} total")

    out.write_text(json.dumps(rows, indent=2, sort_keys=True))
    print(f"wrote {len(rows)} records -> {out}")
    print("NOTE: model_prob is the crowd baseline (no edge). Feed --data to "
          "scripts/run_walk_forward.py to validate the PIPELINE on real data; a real "
          "EDGE still needs a real model (ROADMAP track B).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
