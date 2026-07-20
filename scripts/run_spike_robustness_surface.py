#!/usr/bin/env python3
"""run_spike_robustness_surface.py — CLI for the EXP-006 config robustness surface.

Runs the pre-registered (threshold × window × horizon) grid of the leakage-safe,
cost-net, F10/F11-gated fade-the-spike engine over a real intraday-tick corpus and prints
the honest FAMILY verdict — is the default's EDGE-NOT-PROVEN a config artifact, or is the
whole fade config family null?

HONESTY: this reuses the SINGLE committed corpus, so it is a WITHIN-SAMPLE
config-sensitivity map, NOT an out-of-sample test. No cell can be a validated edge, however
green (see ``prediction_markets/spike_robustness_surface`` module docstring). Selecting the
greenest cell is p-hacking and is refused: a green cell is at most a hypothesis for a FRESH
pre-registered OOS on NEW data.

Usage:
  python3 scripts/run_spike_robustness_surface.py --data data/spike_corpus_politics.json.gz \
      [--category-data data/spike_corpus_politics_cats.json] [--json]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path


def _load_json(path: str):
    """Read a JSON file, transparently gunzipping a ``.gz`` path (matches run_spike_reversal)."""
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt") as fh:
            return json.load(fh)
    return json.loads(p.read_text())


# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.spike_robustness_surface import (  # noqa: E402
    run_robustness_surface,
    summarize,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="EXP-006 config robustness surface")
    ap.add_argument("--data", required=True, help="path to a {market_id: [{t,p},...]} tick JSON(.gz)")
    ap.add_argument("--category-data", help="optional {market_id: category} JSON")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    ticks = _load_json(args.data)
    categories = _load_json(args.category_data) if args.category_data else None

    surface = run_robustness_surface(ticks, category_by_market=categories)

    if args.json:
        print(json.dumps({
            "source": args.data,
            "categories": bool(categories),
            "k_cells": surface.k_cells,
            "family_verdict": surface.family_verdict,
            "n_validated": surface.n_validated,
            "chance_green_expectation": surface.chance_green_expectation,
            "n_positive_pnl": surface.n_positive_pnl,
            "n_f11_significant_positive": surface.n_f11_significant_positive,
            "n_f11_significant_negative": surface.n_f11_significant_negative,
            "n_f10_gate_fragile": surface.n_f10_gate_fragile,
            "default_cell": (
                {
                    "threshold": surface.default_cell.threshold,
                    "window_seconds": surface.default_cell.window_seconds,
                    "horizon_seconds": surface.default_cell.horizon_seconds,
                    "n_trades": surface.default_cell.n_trades,
                    "total_pnl_usd": surface.default_cell.total_pnl_usd,
                    "hit_rate": surface.default_cell.hit_rate,
                    "f11_verdict": surface.default_cell.f11_verdict,
                    "f10_gate_fragile": surface.default_cell.f10_gate_fragile,
                    "is_validated_edge": surface.default_cell.is_validated_edge,
                }
                if surface.default_cell is not None else None
            ),
            "cells": [
                {
                    "threshold": c.threshold,
                    "window_seconds": c.window_seconds,
                    "horizon_seconds": c.horizon_seconds,
                    "is_default": c.is_default,
                    "n_trades": c.n_trades,
                    "n_markets_traded": c.n_markets_traded,
                    "total_pnl_usd": c.total_pnl_usd,
                    "hit_rate": c.hit_rate,
                    "f11_verdict": c.f11_verdict,
                    "f11_ci": [c.f11_ci_low, c.f11_ci_high],
                    "f10_gate_fragile": c.f10_gate_fragile,
                    "f10_gate_reasons": list(c.f10_gate_reasons),
                    "size_robustness": c.size_robustness,
                    "is_validated_edge": c.is_validated_edge,
                }
                for c in surface.cells
            ],
            "validated_cells": [
                {
                    "threshold": c.threshold,
                    "window_seconds": c.window_seconds,
                    "horizon_seconds": c.horizon_seconds,
                    "n_trades": c.n_trades,
                    "total_pnl_usd": c.total_pnl_usd,
                }
                for c in surface.validated_cells
            ],
            "caveats": list(surface.caveats),
        }, indent=2))
    else:
        # Compact per-cell table then the honest family block.
        print("threshold | window |  horizon |   N |   net PnL |   hit | F11                     | F10gate | VALID")
        print("-" * 104)
        for c in surface.cells:
            mark = " *" if c.is_default else "  "
            hit = f"{c.hit_rate:.3f}" if c.hit_rate is not None else "  -  "
            f10 = "n/a" if c.f10_gate_fragile is None else str(c.f10_gate_fragile)
            print(
                f"{c.threshold:>8.2f}{mark}| {c.window_seconds:>5}s | {c.horizon_seconds:>7}s | "
                f"{c.n_trades:>3} | {c.total_pnl_usd:>9,.2f} | {hit:>5} | "
                f"{c.f11_verdict:<23} | {f10:>5}   | {c.is_validated_edge}"
            )
        print("-" * 104)
        print("(* = pre-registered DEFAULT cell)\n")
        print(summarize(surface))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
