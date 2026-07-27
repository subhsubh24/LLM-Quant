#!/usr/bin/env python3
"""rescore_with_spread.py — ROADMAP C8: re-score the committed corpora paying a MEASURED
bid/ask half-spread instead of the flat 0.5% slippage stand-in.

WHY (the binding methodological constraint, filed 2026-07-26 by the EXP-006b audit):
Polymarket's CLOB ``/prices-history`` returns the book MIDPOINT, not a traded price. Every
backtest in this repo is built on that series, so every backtest enters and exits at a price
no order could actually get, paying only ``DEFAULT_SLIPPAGE_RATE = 0.005`` to cross. Measured
against real books the half-spread is several times that, and worst precisely in the
low-price band where both refuted families concentrated their signal. EXP-006b's breakeven
cost multiple was 5.93x (th=0.15) / 8.33x (th=0.20) with F11 significance lost at 1.7x/2.9x —
so the size of this correction decides the verdict outright. Until entry and exit pay a
measured half-spread, a result in this family does not mean much.

WHAT THIS RUNS
Two families, both on already-committed bytes, with the cost model as the ONLY thing that
changes:
  * BUCKET  — ``CalibrationBucketStrategy`` on the frozen 187-record OOS corpus
              (the EXP-002/003/005/010/011 lane; already refuted, expected to get worse).
  * FADE    — ``backtest_fade_the_spike`` at the pre-registered th=0.15 and th=0.20 cells on
              the EXP-006b corpus. th=0.15 is the ONLY nominally F11-significant-positive
              cell this project owns, so it is the one place the spread question actually
              decides something rather than merely deepening a loss.

Each is scored under FOUR cost models — flat (the status quo ante) and the three measured
half-spread models from ``prediction_markets.half_spread`` — so the output reports the
verdict across the plausible SPAN of the cost estimate. That is deliberate: picking one
number would be picking the answer.

WHAT THIS IS NOT
Not a new strategy, not a re-parameterization, not a search. Same corpora, same strategies,
same F10/F11 gates, one input changed. NO edge is claimed here under any model; a result
that survives would be a CANDIDATE requiring the full fresh adversarial audit, and a result
that dies under a merely-conservative model has been out-assumed rather than refuted — which
is why the flat and 747-book columns are printed next to the conservative one.

DIRECTION OF ERROR: both half-spread measurements come from OPEN, volume-ordered (liquid)
markets, so they UNDER-state a random market's spread. Every model here is a LOWER bound on
crossing cost. A cell that dies under a lower bound is dead.

Offline + deterministic: no egress, no credentials, no money, reaches no revenue field.

Usage:
  python scripts/rescore_with_spread.py                       # both families, all models
  python scripts/rescore_with_spread.py --family fade --json
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _imp(a: str, b: str):
    """Import under either the repo-root or the ``backend/`` package layout.

    Copied from the sibling harnesses rather than shared, matching this repo's convention
    that each script stays runnable on its own from a bare checkout.
    """
    try:
        return __import__(a, fromlist=["x"])
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        return __import__(b, fromlist=["x"])


DEFAULT_OOS_CORPUS = "data/real_oos_corpus_polymarket.json"
DEFAULT_SPIKE_CORPUS = "data/spike_corpus_politics_b.json.gz"
DEFAULT_SPIKE_CATS = "data/spike_corpus_politics_b_cats.json"
# The two PRE-REGISTERED EXP-006b cells, fixed here so this harness cannot become a search.
FADE_THRESHOLDS = (0.15, 0.20)


def _load_json(path: str):
    p = Path(path)
    if p.suffix == ".gz":
        with gzip.open(p, "rt") as fh:
            return json.load(fh)
    return json.loads(p.read_text())


def _load_oos_corpus(path: str, wf_mod) -> list:
    """Load the frozen leakage-safe OOS corpus into ``HistoricalMarket`` records.

    Reconstructs through the real constructor so ``__post_init__`` RE-VALIDATES every
    committed record (price in [0,1], outcome in {0,1}, resolution strictly after decision)
    on every load — a tampered corpus fails LOUD rather than silently scoring garbage. This
    mirrors ``exp010_cost_realism._load_corpus`` field for field, inlined for the same
    reason: to keep this harness out of the heavy ``requests`` import chain.
    """
    from datetime import datetime

    rows = _load_json(path)
    if not isinstance(rows, list):
        raise ValueError(f"corpus {path} must be a JSON list of records, got {type(rows).__name__}")
    hm = wf_mod.HistoricalMarket
    out = []
    for r in rows:
        liq = r.get("liquidity")
        out.append(
            hm(
                market_id=str(r["market_id"]),
                decision_time=datetime.fromisoformat(r["decision_time"]),
                resolution_time=datetime.fromisoformat(r["resolution_time"]),
                market_price=float(r["market_price"]),
                model_prob=float(r["model_prob"]),
                outcome=int(r["outcome"]),
                liquidity=float(liq) if liq is not None else None,
                category=r.get("category"),
                research_only=bool(r.get("research_only", False)),
            )
        )
    return out


def _cost_models(cm_mod, hs_mod) -> "list[tuple[str, object]]":
    """The four cost models, in reporting order: the status quo first, then measured.

    ``flat`` is constructed with no ``half_spread_model`` at all (not with a zero one) so it
    is BIT-IDENTICAL to every number this repo has already published — the comparison column
    has to be the real prior result, not a re-derivation of it.
    """
    models: "list[tuple[str, object]]" = [("flat", cm_mod.CostModel())]
    for name in ("747book", "depth_probe", "conservative"):
        models.append((name, cm_mod.CostModel(half_spread_model=hs_mod.MODELS[name])))
    return models


def score_bucket(markets, wf_mod, cal_mod, sig_mod, rs_mod, cost_model, *, seed: int = 42) -> dict:
    """CalibrationBucketStrategy on ``markets`` under ``cost_model``, F10 + F11 attached.

    The cost model is threaded into BOTH the engine and the strategy closure, because the
    strategy screens candidates on its own cost-net edge — leaving the strategy on the flat
    model would let it keep taking trades the engine then prices realistically, which is a
    different (and incoherent) experiment.
    """
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
    return {
        "n_trades": len(res.trades),
        "net_pnl_usd": round(float(sum(pnls)), 2),
        "hit_rate": round(sum(1 for w in wins if w) / len(wins), 4) if wins else None,
        "f11_verdict": sig.verdict,
        "f11_ci": [sig.total_ci_low, sig.total_ci_high],
        "f10_fragile": bool(regime.fragile),
        "f10_fragile_reasons": list(regime.fragile_reasons),
        "is_validated_edge": bool(sig.is_significant_edge and not regime.fragile),
        "seed_hash": res.seed_hash,
        # SIZING DIAGNOSTICS — carried because this family holds to RESOLUTION, so a costlier
        # entry does NOT simply subtract: it shrinks the cost-net edge, which shrinks Kelly,
        # which shrinks the position. On a NET-LOSING signal that makes the reported loss
        # SMALLER, which reads like a bug unless the mechanism is visible. These three fields
        # are the mechanism (same trade set, less capital deployed, fewer contracts held), and
        # they are the same effect ROADMAP E8 already records for the per-category caps: a
        # control applied to a losing signal shrinks the loss without improving the edge.
        "budget_deployed_usd": round(float(sum(t.budget_usd for t in res.trades)), 2),
        "contracts_held": round(float(sum(t.contracts for t in res.trades)), 1),
        "n_wins": int(sum(1 for w in wins if w)),
    }


def score_fade(ticks, cats, srb_mod, cost_model, *, threshold: float) -> dict:
    """One pre-registered fade-the-spike cell under ``cost_model``.

    Only ``threshold`` and ``cost_model`` vary; every other knob stays at the engine default
    the EXP-006b pre-registration fixed, so this cannot drift into a grid search.
    """
    cfg = srb_mod.FadeSpikeConfig(threshold=threshold, cost_model=cost_model)
    res = srb_mod.backtest_fade_the_spike(ticks, config=cfg, category_by_market=cats)
    sig = res.significance
    return {
        "threshold": threshold,
        "n_trades": res.n_trades,
        "net_pnl_usd": round(float(res.total_pnl_usd), 2),
        "hit_rate": res.hit_rate,
        "f11_verdict": sig.verdict,
        "f11_ci": [sig.total_ci_low, sig.total_ci_high],
        "f10_fragile": (res.regime.fragile if res.regime else None),
        "f10_fragile_reasons": (list(res.regime.fragile_reasons) if res.regime else []),
        "is_validated_edge": bool(res.is_validated_edge),
    }


def _model_table(hs_mod) -> list:
    """The measured band tables, emitted with the run so the numbers travel with their
    provenance instead of living only in a doc that can drift away from the code."""
    out = []
    for name, model in hs_mod.MODELS.items():
        out.append(
            {
                "model": name,
                "bands": [
                    {
                        "lo": b.lo,
                        "hi": b.hi,
                        "half_spread_frac": b.half_spread_frac,
                        "n": b.n,
                        "source": b.source,
                    }
                    for b in model.bands
                ],
            }
        )
    return out


def run(
    *,
    family: str = "both",
    oos_corpus: str = DEFAULT_OOS_CORPUS,
    spike_corpus: str = DEFAULT_SPIKE_CORPUS,
    spike_cats: str = DEFAULT_SPIKE_CATS,
) -> dict:
    """The full re-score. Importable + injectable (no argparse, no printing) so a test can
    assert the mechanics deterministically."""
    cm_mod = _imp("backend.app.prediction_markets.cost_model", "app.prediction_markets.cost_model")
    hs_mod = _imp("backend.app.prediction_markets.half_spread", "app.prediction_markets.half_spread")
    models = _cost_models(cm_mod, hs_mod)

    result: dict = {
        "experiment": "C8-spread-realism",
        "claims_edge": False,
        "half_spread_models": _model_table(hs_mod),
        "disclosures": [
            "Both half-spread measurements come from OPEN, volume-ordered (LIQUID) markets, "
            "so they UNDER-state a random market's spread — every model here is a LOWER "
            "bound on crossing cost.",
            "The 747-book source publishes no per-band sample size, and three depth-probe "
            "bands rest on n=2/n=3; every band carries its own n so weak evidence is visible.",
            "The measured half-spread REPLACES the flat slippage rather than stacking on it "
            "— crossing the spread is the cost the flat rate stood in for.",
            "Market impact is unchanged and remains a separate add-on; it is inert on these "
            "corpora (every frozen record carries liquidity: null).",
            "NO edge is claimed under any cost model. A cell that survives is a CANDIDATE "
            "for a fresh adversarial audit, not a validated edge.",
        ],
    }

    if family in ("bucket", "both"):
        wf_mod = _imp("backend.app.prediction_markets.walk_forward", "app.prediction_markets.walk_forward")
        cal_mod = _imp(
            "backend.app.prediction_markets.calibration_bucket_strategy",
            "app.prediction_markets.calibration_bucket_strategy",
        )
        sig_mod = _imp(
            "backend.app.prediction_markets.bootstrap_oos_significance",
            "app.prediction_markets.bootstrap_oos_significance",
        )
        rs_mod = _imp("backend.app.prediction_markets.regime_slice", "app.prediction_markets.regime_slice")
        markets = _load_oos_corpus(oos_corpus, wf_mod)
        result["bucket"] = {
            "corpus": oos_corpus,
            "n_markets": len(markets),
            "by_cost_model": {
                name: score_bucket(markets, wf_mod, cal_mod, sig_mod, rs_mod, cm)
                for name, cm in models
            },
        }

    if family in ("fade", "both"):
        srb_mod = _imp(
            "backend.app.prediction_markets.spike_reversal_backtest",
            "app.prediction_markets.spike_reversal_backtest",
        )
        ticks = _load_json(spike_corpus)
        cats = _load_json(spike_cats)
        result["fade"] = {
            "corpus": spike_corpus,
            "n_markets": len(ticks),
            "by_cost_model": {
                name: [score_fade(ticks, cats, srb_mod, cm, threshold=t) for t in FADE_THRESHOLDS]
                for name, cm in models
            },
        }

    result["verdict"] = _verdict(result)
    return result


def _verdict(result: dict) -> dict:
    """An explicit, mechanical read of what survived — never a narrative.

    ``survives_all`` is the only line that could ever support an edge claim, and it requires
    BOTH gates green under EVERY cost model including the conservative one. Anything else is
    reported as not-proven; there is deliberately no partial-credit verdict.
    """
    cells: list = []
    if "bucket" in result:
        for name, s in result["bucket"]["by_cost_model"].items():
            cells.append(("bucket", name, s["is_validated_edge"]))
    if "fade" in result:
        for name, rows in result["fade"]["by_cost_model"].items():
            for s in rows:
                cells.append((f"fade@{s['threshold']}", name, s["is_validated_edge"]))
    survivors = [f"{fam}/{model}" for fam, model, ok in cells if ok]
    measured = [f"{fam}/{model}" for fam, model, ok in cells if ok and model != "flat"]
    return {
        "cells_scored": len(cells),
        "survivors_any_model": survivors,
        "survivors_under_measured_spread": measured,
        "survives_all_measured_models": bool(measured) and len(measured) == len(
            [c for c in cells if c[1] != "flat"]
        ),
        "edge_verdict": "EDGE-NOT-PROVEN" if not measured else "CANDIDATE-REQUIRES-FRESH-AUDIT",
    }


def _fmt(result: dict) -> str:
    lines = ["C8 SPREAD REALISM — re-score paying a MEASURED half-spread", ""]
    if "bucket" in result:
        b = result["bucket"]
        lines.append(f"BUCKET family — {b['corpus']} ({b['n_markets']} markets)")
        lines.append(f"  {'cost model':<14}{'trades':>7}{'net PnL':>12}  {'F11':<26}{'F10 fragile':>12}")
        for name, s in b["by_cost_model"].items():
            lines.append(
                f"  {name:<14}{s['n_trades']:>7}{s['net_pnl_usd']:>12,.2f}  "
                f"{s['f11_verdict']:<26}{str(s['f10_fragile']):>12}"
            )
        lines.append("")
    if "fade" in result:
        f = result["fade"]
        lines.append(f"FADE family — {f['corpus']} ({f['n_markets']} markets)")
        lines.append(
            f"  {'cost model':<14}{'th':>6}{'trades':>7}{'net PnL':>12}  {'F11':<26}{'F10 fragile':>12}"
        )
        for name, rows in f["by_cost_model"].items():
            for s in rows:
                lines.append(
                    f"  {name:<14}{s['threshold']:>6.2f}{s['n_trades']:>7}{s['net_pnl_usd']:>12,.2f}  "
                    f"{s['f11_verdict']:<26}{str(s['f10_fragile']):>12}"
                )
        lines.append("")
    v = result["verdict"]
    lines.append(f"VERDICT: {v['edge_verdict']}  ({v['cells_scored']} cells scored)")
    lines.append(f"  survivors under a measured spread: {v['survivors_under_measured_spread'] or 'none'}")
    lines.append("")
    lines.append("NO edge is claimed. Measured half-spreads come from LIQUID open markets and")
    lines.append("are a LOWER bound on real crossing cost.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="C8 — re-score committed corpora under a measured half-spread")
    ap.add_argument("--family", choices=["bucket", "fade", "both"], default="both")
    ap.add_argument("--oos-corpus", default=DEFAULT_OOS_CORPUS)
    ap.add_argument("--spike-corpus", default=DEFAULT_SPIKE_CORPUS)
    ap.add_argument("--spike-cats", default=DEFAULT_SPIKE_CATS)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    result = run(
        family=args.family,
        oos_corpus=args.oos_corpus,
        spike_corpus=args.spike_corpus,
        spike_cats=args.spike_cats,
    )
    print(json.dumps(result, indent=2) if args.json else _fmt(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
