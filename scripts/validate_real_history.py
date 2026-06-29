#!/usr/bin/env python3
"""validate_real_history.py — deterministic regression canary for the 54-record
real Polymarket history fixture (ROADMAP C3/F2/B2).

PURPOSE
Proves that the walk-forward engine reproduces bit-for-bit on REAL committed data
(not only on synthetic data) and anchors the honest crowd-calibration baseline.
This is a regression gate — any drift in seed_hash, trade count, or crowd Brier
flags a silent change to the fixture, cost model, or walk-forward logic.

HONEST SCOPE
The crowd Brier (~0.09) and 0-trade result are NOT evidence of an edge; they are
the OPPOSITE: they confirm model_prob == market_price (the crowd baseline) so the
engine correctly makes 0 trades. A real edge requires a real model (ROADMAP track B)
that produces an independent model_prob from decision-time information.

KNOWN BIASES IN THIS FIXTURE (must be stated in any eval):
  1. Liquidity-selection — --order volumeNum keeps only deep markets.
  2. Survivorship — only unambiguously-settled binary markets are included.
  3. Late-life pinning — ~70% of markets had already pinned to <0.05 / >0.95 two
     days before resolution; the crowd looks extremely sharp here.

DESIGN
  - Pure fixture read: no network calls, no Polymarket API access required.
  - Runs entirely offline; safe in CI and in the autonomous build environment.
  - Timeout-safe: reads one small JSON file and does deterministic arithmetic.

Usage:
    python3 scripts/validate_real_history.py            # prints JSON report
    python3 scripts/validate_real_history.py --human    # human-readable summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from backend.app.prediction_markets.walk_forward import (  # noqa: E402
    HistoricalMarket,
    walk_forward_backtest,
)
from backend.app.prediction_markets.calibration import (  # noqa: E402
    ResolvedPrediction,
    brier_score,
)

_FIXTURE_PATH = _REPO_ROOT / "data" / "polymarket_history_sample.json"


def load_fixture(path: Path = _FIXTURE_PATH) -> list[HistoricalMarket]:
    """Load the committed 54-record Polymarket history fixture."""
    rows = json.loads(path.read_text())
    markets: list[HistoricalMarket] = []
    for r in rows:
        markets.append(
            HistoricalMarket(
                market_id=str(r["market_id"]),
                decision_time=__import__("datetime").datetime.fromisoformat(r["decision_time"]),
                resolution_time=__import__("datetime").datetime.fromisoformat(r["resolution_time"]),
                market_price=float(r["market_price"]),
                model_prob=float(r["model_prob"]),
                outcome=int(r["outcome"]),
            )
        )
    return markets


def crowd_baseline_brier(markets: list[HistoricalMarket]) -> float:
    """Compute the crowd Brier score using market_price as BOTH the prediction and the
    baseline.

    Since model_prob == market_price in this fixture, this measures the crowd's own
    calibration, NOT any model advantage. The result (~0.09) is the honest floor for
    what a real model would need to beat after costs.
    """
    samples = [
        ResolvedPrediction(
            market_id=m.market_id,
            predicted_prob=m.market_price,  # crowd price as the prediction
            market_price=m.market_price,    # same, so improvement == 0
            outcome=m.outcome,
        )
        for m in markets
    ]
    preds = [s.predicted_prob for s in samples]
    outcomes = [s.outcome for s in samples]
    return brier_score(preds, outcomes)


def run_report(fixture_path: Path = _FIXTURE_PATH) -> dict:
    """Load the fixture, run the walk-forward backtest, compute crowd Brier, and
    return a JSON-serialisable report dict.

    All values are deterministic given the committed fixture and default config.
    """
    markets = load_fixture(fixture_path)

    result = walk_forward_backtest(
        markets,
        # All defaults match scripts/run_walk_forward.py for reproducibility.
        initial_bankroll=10_000.0,
        seed=42,
    )

    crowd_brier = crowd_baseline_brier(markets)

    pinned = sum(1 for m in markets if m.market_price < 0.05 or m.market_price > 0.95)
    yes_count = sum(m.outcome for m in markets)

    return {
        # ------------------------------------------------------------------ #
        # DETERMINISM ANCHOR — any change to fixture, cost model, or engine   #
        # will change this hash and fail the regression canary test.           #
        # ------------------------------------------------------------------ #
        "seed_hash": result.seed_hash,
        "seed": result.seed,
        "n_records": len(markets),
        "n_windows": result.n_windows,

        # ------------------------------------------------------------------ #
        # TRADE / PnL SECTION                                                 #
        # 0 trades is correct: model_prob == market_price → no net edge →     #
        # engine correctly does not bet.  This is NOT a bug; it proves the     #
        # engine is honest.                                                    #
        # ------------------------------------------------------------------ #
        "total_trades": result.n_trades,
        "total_pnl_usd": result.total_pnl_usd,
        "final_bankroll_usd": result.final_bankroll,
        "weekly_pnl_series": [
            [wk.isoformat(), pnl] for wk, pnl in result.weekly_pnl
        ],

        # ------------------------------------------------------------------ #
        # CROWD BASELINE CALIBRATION                                           #
        # This is the CROWD's own Brier, not a model advantage.               #
        # ~0.09 is very sharp (0=perfect, 0.25=coin-flip) because these are  #
        # liquid markets sampled 2 days before resolution — most already pinned.
        # ------------------------------------------------------------------ #
        "crowd_baseline_brier": crowd_brier,
        "fraction_pinned_lt05_gt95": pinned / len(markets),
        "yes_base_rate": yes_count / len(markets),

        # ------------------------------------------------------------------ #
        # HONESTY NOTES — printed alongside any result that could be          #
        # misread as a model edge                                              #
        # ------------------------------------------------------------------ #
        "honesty_notes": [
            "crowd_baseline_brier measures the crowd's OWN calibration, not a model edge",
            "model_prob == market_price in this fixture → 0 trades is correct, not a failure",
            "known biases: liquidity-selection (volumeNum), survivorship, late-life pinning",
            "a real edge requires a real model with independent model_prob (ROADMAP track B)",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic regression canary: real Polymarket history fixture"
    )
    ap.add_argument(
        "--human", action="store_true",
        help="print a human-readable summary instead of raw JSON"
    )
    ap.add_argument(
        "--fixture", default=str(_FIXTURE_PATH),
        help="path to the resolved-market history JSON (default: data/polymarket_history_sample.json)"
    )
    args = ap.parse_args()

    report = run_report(Path(args.fixture))

    if args.human:
        print("=" * 60)
        print("REAL DATA REGRESSION CANARY — Polymarket history fixture")
        print("=" * 60)
        print(f"fixture records  : {report['n_records']}")
        print(f"seed / hash      : {report['seed']} / {report['seed_hash']}")
        print(f"OOS windows      : {report['n_windows']}")
        print()
        print("WALK-FORWARD RESULT (crowd baseline, 0-edge)")
        print(f"  total trades   : {report['total_trades']}")
        print(f"  total PnL      : ${report['total_pnl_usd']:,.2f}")
        print(f"  final bankroll : ${report['final_bankroll_usd']:,.2f}")
        if report["weekly_pnl_series"]:
            print("  weekly PnL series:")
            for wk, pnl in report["weekly_pnl_series"]:
                print(f"    {wk}  {pnl:+,.2f}")
        else:
            print("  weekly PnL series: (empty — 0 trades, as expected)")
        print()
        print("CROWD BASELINE CALIBRATION")
        print(f"  crowd Brier    : {report['crowd_baseline_brier']:.6f}")
        print(f"  pinned (<5%/>95%): {report['fraction_pinned_lt05_gt95']:.1%}")
        print(f"  YES base rate  : {report['yes_base_rate']:.1%}")
        print()
        print("HONESTY NOTES")
        for note in report["honesty_notes"]:
            print(f"  * {note}")
    else:
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
