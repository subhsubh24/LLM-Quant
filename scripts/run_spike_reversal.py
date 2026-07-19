#!/usr/bin/env python3
"""run_spike_reversal.py — CLI for the EXP-006 fade-the-spike backtest.

Runs the leakage-safe, cost-net, F10/F11-gated fade-the-spike engine
(``prediction_markets.spike_reversal_backtest``) on either a built-in SYNTHETIC demo or a
real per-market intraday-tick corpus, and prints the honest verdict.

HONESTY: the synthetic demo proves the ENGINE is honest — it RECOVERS an injected
cost-net reversion edge and reports EDGE-NOT-PROVEN when there is none. It is NOT a
validated edge. A real EXP-006 result requires a real, point-in-time, non-survivorship
intraday-tick corpus (``PolymarketHistoryFetcher.fetch_price_history`` output per market)
fed via --data, reaching N >= the pre-registered floor, F11 significant_positive, and F10
non-fragile. Until then the go-live floor box stays unchecked.

Usage:
  python3 scripts/run_spike_reversal.py                      # synthetic engine demo
  python3 scripts/run_spike_reversal.py --data ticks.json [--category-data cats.json] [--json]

--data schema: a JSON object mapping market_id -> a list of {"t": unix_seconds, "p": 0..1}
  ticks (the exact shape the Polymarket CLOB price-history fetcher returns).
--category-data schema (optional): a JSON object mapping market_id -> coarse category string.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.spike_reversal_backtest import (  # noqa: E402
    FadeSpikeConfig,
    backtest_fade_the_spike,
)


def _synthetic(n_markets: int = 120) -> dict[str, list[dict]]:
    """A deterministic corpus whose spikes PARTIALLY REVERT beyond round-trip cost — a
    known injected edge the engine must recover. Bands + directions are varied so the
    recovered edge is BROAD (spread across confidence bands, weeks, both spike directions).
    NOT a claim about real markets — it exercises the engine, like walk_forward's demo."""
    bands = [0.2, 0.3, 0.45, 0.6, 0.7, 0.8]
    dirs = ["UP", "DOWN"]
    move, revert = 0.15, 0.075
    stagger, confirm_dt, forward_dt = 3 * 86400, 1800, 5400
    out: dict[str, list[dict]] = {}
    for i in range(n_markets):
        band = bands[i % len(bands)]
        direction = dirs[i % len(dirs)]
        base = i * stagger
        if direction == "UP":
            confirm = 1.0 - band
            baseline = confirm - move
            forward = confirm - revert
        else:
            confirm = band
            baseline = confirm + move
            forward = confirm + revert
        out[f"syn{i:04d}"] = [
            {"t": base, "p": round(baseline, 4)},
            {"t": base + confirm_dt, "p": round(confirm, 4)},
            {"t": base + forward_dt, "p": round(forward, 4)},
        ]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="EXP-006 fade-the-spike backtest")
    ap.add_argument("--data", help="path to a {market_id: [{t,p},...]} tick JSON")
    ap.add_argument("--category-data", help="optional {market_id: category} JSON")
    ap.add_argument("--threshold", type=float, default=None, help="spike threshold (0..1 move)")
    ap.add_argument("--horizon-hours", type=float, default=None, help="reversal horizon in hours")
    ap.add_argument("--max-per-market", type=int, default=None, help="max trades per market")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    if args.data:
        ticks = json.loads(Path(args.data).read_text())
        source = args.data
    else:
        ticks = _synthetic()
        source = "SYNTHETIC engine demo (NOT a validated edge)"
    categories = json.loads(Path(args.category_data).read_text()) if args.category_data else None

    kwargs = {}
    if args.threshold is not None:
        kwargs["threshold"] = args.threshold
    if args.horizon_hours is not None:
        kwargs["horizon_seconds"] = int(args.horizon_hours * 3600)
    if args.max_per_market is not None:
        kwargs["max_trades_per_market"] = args.max_per_market
    cfg = FadeSpikeConfig(**kwargs) if kwargs else None

    res = backtest_fade_the_spike(ticks, config=cfg, category_by_market=categories)
    sig = res.significance

    if args.json:
        print(json.dumps({
            "source": source,
            "n_markets_scanned": res.n_markets_scanned,
            "n_spikes_detected": res.n_spikes_detected,
            "n_spikes_unlabelable": res.n_spikes_unlabelable,
            "n_trades": res.n_trades,
            "n_markets_traded": res.n_markets_traded,
            "total_pnl_usd": res.total_pnl_usd,
            "hit_rate": res.hit_rate,
            "f11_verdict": sig.verdict,
            "f11_total_ci": [sig.total_ci_low, sig.total_ci_high],
            "f10_fragile_raw": (res.regime.fragile if res.regime else None),
            "f10_fragile_reasons_raw": (list(res.regime.fragile_reasons) if res.regime else []),
            "size_robustness": res.size_robustness,
            "magnitude_strata": [
                {
                    "band": s.label,
                    "n_trades": s.n_trades,
                    "total_pnl_usd": s.total_pnl_usd,
                    "hit_rate": s.hit_rate,
                    "mean_reversal_fraction": s.mean_reversal_fraction,
                    "mean_magnitude": s.mean_magnitude,
                }
                for s in res.strata
            ],
            "is_validated_edge": res.is_validated_edge,
            "verdict": res.verdict,
        }, indent=2))
    else:
        print(f"source            : {source}")
        print(f"markets scanned   : {res.n_markets_scanned}")
        print(f"spikes detected   : {res.n_spikes_detected} "
              f"({res.n_spikes_unlabelable} unlabelable/dropped)")
        print(f"trades / markets  : {res.n_trades} / {res.n_markets_traded}")
        print(f"total PnL (USD)   : {res.total_pnl_usd:,.2f}")
        print(f"hit rate          : {res.hit_rate}")
        print(f"F11 significance  : {sig.verdict} "
              f"(total CI [{sig.total_ci_low}, {sig.total_ci_high}])")
        if res.regime is not None:
            print(f"F10 (raw) fragile : {res.regime.fragile}  "
                  f"top-market share {res.regime.top_market_pnl_share}")
        # Salience breakdown (Run 21 caution: do the LARGEST spikes revert too, or only small ones?)
        print("magnitude strata  : |move| band | N | net PnL | hit | mean reversion")
        for s in res.strata:
            print(f"                    {s.label:>10} | {s.n_trades:>3} | "
                  f"{s.total_pnl_usd:>10,.2f} | {s.hit_rate} | {s.mean_reversal_fraction}")
        # Config-independent, significance-aware largest-spike gate status (Run 21 caution).
        print(f"size-robustness   : {res.size_robustness}")
        print(f"VALIDATED EDGE    : {res.is_validated_edge}")
        print(f"\n{res.verdict}")
        if not args.data:
            print("\nNOTE: synthetic demo — proves the engine recovers a known cost-net")
            print("reversion edge + reports EDGE-NOT-PROVEN otherwise. NOT a validated OOS")
            print("result; feed --data a real intraday-tick corpus (N >= floor) to test EXP-006.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
