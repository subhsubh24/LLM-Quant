#!/usr/bin/env python3
"""validate_real_oos.py — fetch REAL resolved Polymarket history and validate the edge OOS.

The "fetch + validate in place" data lane: pulls a fresh real resolved-market corpus from
Polymarket's PUBLIC APIs (no credentials), then runs the leakage-safe walk-forward backtest
BOTH with the crowd baseline AND with the real B4a alpha (`CalibrationBucketStrategy`), and
reports the honest OOS result. Runs anywhere Polymarket is reachable (a GitHub Actions runner,
a permitted host) — the autonomous factory env is egress-blocked, so this closes the loop the
factory can't. NEVER trades, NEVER touches money.

Honest by construction:
  * The corpus is leakage-safe (decision-time price is a pre-resolution tick; the settled
    outcome is never the decision price — the fetcher raises rather than fabricating).
  * The calibration alpha ABSTAINS on uncalibrated/insufficient buckets and trades 0 on a
    well-calibrated crowd — a 0-trade / ~$0 result is reported AS a null edge, never dressed up.
  * Discloses the known biases (liquidity-selection, survivorship, late-life pinning).

Usage: python scripts/validate_real_oos.py [--limit 250] [--max-pages 2] [--decision-lead-days 2] [--json]
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


def evaluate(markets, wf_mod, cal_mod, *, seed: int = 42, decision_lead_days: float = 2.0) -> dict:
    """Pure OOS evaluation on already-fetched leakage-safe markets (injectable for tests):
    crowd baseline vs. the B4a calibration alpha, + corpus stats + an honest verdict."""
    prices = [m.market_price for m in markets]
    outs = [m.outcome for m in markets]
    n = len(markets)
    crowd_brier = sum((p - o) ** 2 for p, o in zip(prices, outs)) / n
    pinned = sum(1 for p in prices if p < 0.05 or p > 0.95) / n

    baseline = wf_mod.walk_forward_backtest(markets, seed=seed)                       # model_prob==crowd -> ~0
    alpha = wf_mod.walk_forward_backtest(markets, strategy_fn=cal_mod.make_calibration_bucket_strategy(), seed=seed)

    return {
        "corpus": {
            "n_markets": n, "yes_base_rate": round(sum(outs) / n, 4),
            "crowd_brier": round(crowd_brier, 4), "price_pinned_pct": round(pinned, 3),
            "price_median": round(statistics.median(prices), 4), "decision_lead_days": decision_lead_days,
        },
        "crowd_baseline": {"trades": baseline.n_trades, "total_pnl_usd": round(baseline.total_pnl_usd, 2),
                           "seed_hash": baseline.seed_hash},
        "calibration_alpha_b4a": {"trades": alpha.n_trades, "total_pnl_usd": round(alpha.total_pnl_usd, 2),
                                  "seed_hash": alpha.seed_hash},
        "biases_disclosed": ["liquidity-selection (volumeNum order)", "survivorship (clean-resolution only)",
                             "late-life pinning (decision sampled near resolution)"],
        "verdict": (
            "NO EDGE — the calibration alpha traded 0 (crowd well-calibrated on this liquid, near-resolution "
            "sample; needs earlier-life sampling for headroom)."
            if alpha.n_trades == 0 else
            f"alpha took {alpha.n_trades} trades, net ${round(alpha.total_pnl_usd, 2)} OOS — NOT a validated "
            f"edge; requires a larger corpus + a passing B2 calibration eval + >= floor over sufficient N."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--decision-lead-days", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    fetch_mod = _imp("backend.app.prediction_markets.polymarket_history_fetcher",
                     "app.prediction_markets.polymarket_history_fetcher")
    wf_mod = _imp("backend.app.prediction_markets.walk_forward",
                  "app.prediction_markets.walk_forward")
    cal_mod = _imp("backend.app.prediction_markets.calibration_bucket_strategy",
                   "app.prediction_markets.calibration_bucket_strategy")

    # 1) Fetch real resolved history (public, no creds). Distinguish egress-block from a code bug.
    try:
        f = fetch_mod.PolymarketHistoryFetcher()
        resolved = f.fetch_resolved_markets(limit=args.limit, max_pages=args.max_pages, order="volumeNum")
        markets = f.build_historical_markets(resolved, timedelta(days=args.decision_lead_days))
    except Exception as e:  # a real code break in the fetcher/parser
        print(f"  validate-real-oos: FAIL (fetcher code error) {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if not markets:
        # No leakage-safe records — most likely egress-blocked (403) or a too-large lead. Not a code failure.
        print("  validate-real-oos: N/A — 0 leakage-safe records (egress-blocked, or lead too large). "
              "Run where Polymarket is reachable (GitHub runner / permitted host).")
        return 0

    report = evaluate(markets, wf_mod, cal_mod, seed=args.seed,
                      decision_lead_days=args.decision_lead_days)
    alpha_res = report["calibration_alpha_b4a"]

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        c = report["corpus"]
        b = report["crowd_baseline"]
        print(f"REAL-DATA OOS VALIDATION  (n={c['n_markets']} real resolved markets)")
        print(f"  crowd Brier={c['crowd_brier']}  pinned={c['price_pinned_pct']:.0%}  YES-rate={c['yes_base_rate']}")
        print(f"  crowd baseline : {b['trades']} trades  ${b['total_pnl_usd']:,.2f}  (hash {b['seed_hash']})")
        print(f"  B4a alpha      : {alpha_res['trades']} trades  ${alpha_res['total_pnl_usd']:,.2f}  (hash {alpha_res['seed_hash']})")
        print(f"  VERDICT: {report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
