#!/usr/bin/env python3
"""run_walk_forward.py — CLI for the leakage-free walk-forward backtest (ROADMAP C3).

Loads a resolved-market history (JSON) or a built-in SYNTHETIC demo, runs the
deterministic walk-forward engine, and prints the reproducible weekly-PnL series plus
the seed_hash (proof of determinism: same data + seed → same hash → same PnL).

HONESTY: the synthetic demo proves the ENGINE is honest (it recovers an injected edge
and reproduces). It is NOT a validated edge. A real validated-OOS result requires a
real resolved-Polymarket-history JSON fed via --data. Until then the go-live floor box
stays unchecked.

Usage:
  python3 scripts/run_walk_forward.py                 # synthetic engine demo
  python3 scripts/run_walk_forward.py --data hist.json --seed 42 [--json]

JSON schema for --data: a list of objects with keys
  market_id, decision_time (ISO), resolution_time (ISO), market_price, model_prob, outcome
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.walk_forward import (  # noqa: E402
    HistoricalMarket,
    walk_forward_backtest,
)


def _load(path: str) -> list[HistoricalMarket]:
    rows = json.loads(Path(path).read_text())
    out = []
    for r in rows:
        out.append(
            HistoricalMarket(
                market_id=str(r["market_id"]),
                decision_time=datetime.fromisoformat(r["decision_time"]),
                resolution_time=datetime.fromisoformat(r["resolution_time"]),
                market_price=float(r["market_price"]),
                model_prob=float(r["model_prob"]),
                outcome=int(r["outcome"]),
            )
        )
    return out


def _synthetic(n: int = 300) -> list[HistoricalMarket]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    markets = []
    for i in range(n):
        outcome = 1 if (i % 10) < 7 else 0   # 70% YES — a real, deterministic edge
        markets.append(
            HistoricalMarket(
                market_id=f"syn{i}",
                decision_time=base + timedelta(days=i),
                resolution_time=base + timedelta(days=i + 1),
                market_price=0.50,            # crowd misprices YES
                model_prob=0.70,              # model is right
                outcome=outcome,
            )
        )
    return markets


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward prediction-market backtest")
    ap.add_argument("--data", help="path to resolved-market history JSON")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bankroll", type=float, default=10_000.0)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    if args.data:
        markets = _load(args.data)
        source = args.data
    else:
        markets = _synthetic()
        source = "SYNTHETIC engine demo (NOT a validated edge)"

    res = walk_forward_backtest(markets, initial_bankroll=args.bankroll, seed=args.seed)

    if args.json:
        print(json.dumps({
            "source": source,
            "seed": res.seed,
            "seed_hash": res.seed_hash,
            "n_windows": res.n_windows,
            "n_trades": res.n_trades,
            "total_pnl_usd": res.total_pnl_usd,
            "final_bankroll": res.final_bankroll,
            "weekly_pnl": [[wk.isoformat(), pnl] for wk, pnl in res.weekly_pnl],
        }, indent=2))
    else:
        print(f"source          : {source}")
        print(f"seed / hash     : {res.seed} / {res.seed_hash}")
        print(f"windows / trades: {res.n_windows} / {res.n_trades}")
        print(f"total PnL (USD) : {res.total_pnl_usd:,.2f}")
        print(f"final bankroll  : {res.final_bankroll:,.2f}")
        print("weekly PnL series:")
        for wk, pnl in res.weekly_pnl:
            print(f"  {wk.isoformat()}  {pnl:+,.2f}")
        if not args.data:
            print("\nNOTE: synthetic demo — proves the engine reproduces + recovers a")
            print("known edge. NOT a validated OOS result; feed --data real history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
