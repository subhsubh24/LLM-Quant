#!/usr/bin/env python3
"""exp010_cost_realism.py — EXP-010: re-score the committed OOS corpus under Polymarket's
REAL price-dependent, per-category taker-fee formula, and check whether any already-refuted
verdict is a cost-model ARTIFACT.

WHY (Research Run 29, 2026-07-23 — verified official fee-schedule mismatch):
``cost_model.py`` prices every fill under a flat multiplicative ``DEFAULT_FEE_RATE = 0.02``
("Polymarket-style", 2% of notional). Run 29 directly WebFetched docs.polymarket.com's
official fee page and found the REAL documented taker fee is a fundamentally different SHAPE:
an ADDITIVE per-contract dollar fee ``feeRate * p * (1 - p)`` with a PER-CATEGORY feeRate
(Politics 0.04, Sports/Economics 0.05, Crypto 0.07, Geopolitical 0; makers free). As a
FRACTION of notional the real fee is ``feeRate * (1 - p)`` vs the flat 0.02, so it is cheaper
than the flat 2% only ABOVE a per-category crossover (Politics p>0.50, Sports/Econ p>0.60,
Crypto p>0.71) and MORE expensive at low prices. The committed corpus is longshot-heavy
(median price ~0.04), so the real formula is, on balance, MORE punitive there — the refutation
is reinforced, not rescued. VISION requires realistic costs, and cost_model.py's own docstring
invites updating the rates "when the real venue fee schedule is wired." So this is a
COST-MODEL-REALISM question, not an alpha-mechanism one: it re-scores ALREADY-COLLECTED data
under a corrected cost input.

WHAT this is NOT: it is NOT re-parameterizing a refuted strategy family (no new config, no new
threshold, no mining). It runs the SAME CalibrationBucketStrategy on the SAME committed corpus
through the SAME F10 (regime-slice fragility) + F11 (bootstrap significance) gates, changing
ONLY the cost model. The pre-registered PREDICTION is a NULL (the diagnosed problem was signal
quality / concentration, not cost). A flip to significant_positive would NOT be an edge claim —
it would be a CANDIDATE requiring the full fresh adversarial audit before anything is claimed.

HONEST BY CONSTRUCTION:
  * NO new data fetch, NO egress — re-scores the committed leakage-safe corpus only.
  * Reconstructs records through the HistoricalMarket constructor (re-validates invariants).
  * Reports the per-category feeRate ASSIGNMENT (incl. which categories used the conservative
    fallback) so the cost change is fully transparent, never silent.
  * NEVER trades, NEVER touches money, reaches NO revenue field.

Usage: python scripts/exp010_cost_realism.py [--corpus data/real_oos_corpus_polymarket.json] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _imp(a, b):
    try:
        return __import__(a, fromlist=["x"])
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        return __import__(b, fromlist=["x"])


DEFAULT_CORPUS = "data/real_oos_corpus_polymarket.json"


def _load_corpus(path: str, wf_mod) -> list:
    """Load a frozen leakage-safe corpus into HistoricalMarket records (offline, no egress).

    Mirrors the audited ``validate_real_oos.load_corpus_from_json`` field-for-field, but is
    inlined here so the light preflight gate does NOT drag in that module's heavy import
    chain (polymarket_client -> requests). Reconstructs through the HistoricalMarket
    constructor so its __post_init__ invariants (price in [0,1], outcome in {0,1}, resolution
    strictly after decision) RE-VALIDATE the committed data on every load — a corrupted or
    tampered corpus fails LOUD, never silently scores garbage.
    """
    from datetime import datetime

    rows = json.loads(Path(path).read_text())
    if not isinstance(rows, list):
        raise ValueError(f"corpus {path} must be a JSON list of records, got {type(rows).__name__}")
    hm = wf_mod.HistoricalMarket
    out = []
    for r in rows:
        liq = r.get("liquidity")
        out.append(hm(
            market_id=str(r["market_id"]),
            decision_time=datetime.fromisoformat(r["decision_time"]),
            resolution_time=datetime.fromisoformat(r["resolution_time"]),
            market_price=float(r["market_price"]),
            model_prob=float(r["model_prob"]),
            outcome=int(r["outcome"]),
            liquidity=float(liq) if liq is not None else None,
            category=r.get("category"),
            research_only=bool(r.get("research_only", False)),
        ))
    return out


def _score(markets, wf_mod, cal_mod, sig_mod, rs_mod, cost_model, *, seed: int = 42) -> dict:
    """Run the CalibrationBucketStrategy on ``markets`` under ``cost_model`` and attach the
    F11 (bootstrap significance) + F10 (regime-slice fragility) gates. Pure + deterministic."""
    res = wf_mod.walk_forward_backtest(
        markets,
        strategy_fn=cal_mod.make_calibration_bucket_strategy(cost_model=cost_model),
        cost_model=cost_model,
        seed=seed,
    )
    pnls = [t.pnl_usd for t in res.trades]
    wins = [t.is_win for t in res.trades]
    sig = sig_mod.bootstrap_oos_significance(pnls, wins)
    category_by_market_id = {
        m.market_id: m.category for m in markets if getattr(m, "category", None)
    }
    regime = rs_mod.analyze_regime_slices(
        res.trades, category_by_market_id=category_by_market_id or None
    )
    # A candidate edge requires BOTH gates: F11 significant_positive AND F10 non-fragile.
    is_validated_edge = bool(sig.is_significant_edge and not regime.fragile)
    return {
        "n_trades": len(res.trades),
        "net_pnl_usd": round(float(sum(pnls)), 2),
        "hit_rate": round((sum(1 for w in wins if w) / len(wins)), 4) if wins else None,
        "f11_verdict": sig.verdict,
        "f11_significant_edge": bool(sig.is_significant_edge),
        "f10_fragile": bool(regime.fragile),
        "f10_fragile_reasons": list(regime.fragile_reasons),
        "is_validated_edge": is_validated_edge,
        "total_pnl_all_windows": round(float(res.total_pnl_usd), 2),
    }


def run_exp010(corpus_path: str) -> dict:
    """The full EXP-010 comparison: flat vs. real Polymarket fee schedule on the same corpus.

    Injectable/importable (no argparse, no printing) so a test can assert the mechanics
    deterministically. Returns a dict with both scores + the flip verdict + the fee mapping.
    """
    wf_mod = _imp("backend.app.prediction_markets.walk_forward",
                  "app.prediction_markets.walk_forward")
    cal_mod = _imp("backend.app.prediction_markets.calibration_bucket_strategy",
                   "app.prediction_markets.calibration_bucket_strategy")
    cm_mod = _imp("backend.app.prediction_markets.cost_model",
                  "app.prediction_markets.cost_model")
    sig_mod = _imp("backend.app.prediction_markets.bootstrap_oos_significance",
                   "app.prediction_markets.bootstrap_oos_significance")
    rs_mod = _imp("backend.app.prediction_markets.regime_slice",
                  "app.prediction_markets.regime_slice")

    markets = _load_corpus(corpus_path, wf_mod)

    flat_model = cm_mod.DEFAULT_COST_MODEL
    schedule = cm_mod.PolymarketFeeSchedule()
    real_model = cm_mod.CostModel(fee_schedule=schedule)

    # Per-category feeRate assignment — transparency on which categories used the fallback.
    cats = Counter(m.category or "None" for m in markets)
    fee_map = {}
    for cat, count in sorted(cats.items(), key=lambda kv: -kv[1]):
        c = None if cat == "None" else cat
        rate = schedule.rate_for(c)
        documented = (c is not None and c.strip().lower() in cm_mod.POLYMARKET_FEE_RATES)
        fee_map[cat] = {
            "n_markets": count,
            "fee_rate": rate,
            "documented": documented,
            "fallback": (not documented),
        }

    flat = _score(markets, wf_mod, cal_mod, sig_mod, rs_mod, flat_model)
    real = _score(markets, wf_mod, cal_mod, sig_mod, rs_mod, real_model)

    verdict_flipped = (flat["is_validated_edge"] != real["is_validated_edge"])
    # The DANGEROUS flip is only NULL/refuted -> validated (a newly-manufactured edge that
    # would need a fresh adversarial audit). The safe direction (was-validated -> refuted)
    # cannot happen here (no prior committed corpus validated), but we flag either.
    flip_to_edge = (not flat["is_validated_edge"] and real["is_validated_edge"])

    return {
        "experiment": "EXP-010",
        "corpus": corpus_path,
        "n_markets": len(markets),
        "fee_map": fee_map,
        "flat_2pct": flat,
        "real_polymarket": real,
        "verdict_flipped": verdict_flipped,
        "flip_to_validated_edge": flip_to_edge,
        "prediction": "NULL (refutation is cost-model-robust; signal quality was the diagnosis, not cost)",
        "note": (
            "A flip_to_validated_edge=True is NOT an edge claim — it is a CANDIDATE that "
            "requires >=3 fresh adversarial Opus auditors before anything is claimed. "
            "flip_to_validated_edge=False confirms the refutation is robust to the cost-model "
            "correction and hardens cost realism for every future backtest."
        ),
    }


def _fmt(result: dict) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append(f"EXP-010 — cost-model realism re-score  (corpus: {result['corpus']})")
    lines.append(f"  markets in corpus: {result['n_markets']}")
    lines.append("-" * 72)
    lines.append("Per-category taker feeRate assignment (real Polymarket schedule):")
    for cat, info in result["fee_map"].items():
        tag = "documented" if info["documented"] else "FALLBACK (conservative)"
        lines.append(
            f"  {cat:<14} n={info['n_markets']:<4} feeRate={info['fee_rate']:.3f}  [{tag}]"
        )
    lines.append("-" * 72)
    for label, key in (("FLAT 2%-of-notional (current default)", "flat_2pct"),
                       ("REAL Polymarket feeRate*p*(1-p) per category", "real_polymarket")):
        s = result[key]
        lines.append(label)
        lines.append(
            f"  n_trades={s['n_trades']}  net_pnl=${s['net_pnl_usd']:,.2f}  "
            f"hit_rate={s['hit_rate']}"
        )
        lines.append(
            f"  F11={s['f11_verdict']} (sig_edge={s['f11_significant_edge']})  "
            f"F10_fragile={s['f10_fragile']}  is_validated_edge={s['is_validated_edge']}"
        )
        if s["f10_fragile_reasons"]:
            lines.append(f"  F10 reasons: {', '.join(s['f10_fragile_reasons'])}")
    lines.append("-" * 72)
    lines.append(f"verdict_flipped: {result['verdict_flipped']}")
    lines.append(f"flip_to_validated_edge: {result['flip_to_validated_edge']}")
    if result["flip_to_validated_edge"]:
        lines.append(
            "  ==> CANDIDATE (NOT an edge): a previously-refuted result now clears both gates "
            "under the corrected cost model. Requires >=3 FRESH adversarial Opus auditors "
            "before ANY edge claim."
        )
    else:
        lines.append(
            "  ==> NULL confirmed: the refutation is ROBUST to the real cost-model correction. "
            "Cost realism is hardened; no edge is manufactured. (Predicted outcome.)"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="EXP-010: re-score committed OOS corpus under the real Polymarket fee formula.")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS, help="path to a committed leakage-safe corpus JSON")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of the report")
    args = ap.parse_args()

    corpus = args.corpus
    if not Path(corpus).exists():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 2

    result = run_exp010(corpus)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_fmt(result))
    # Exit 0 either way — this is a research diagnostic, not a gate. A flip_to_validated_edge
    # is surfaced in the output (and would trigger the audit), it does not fail the process.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
