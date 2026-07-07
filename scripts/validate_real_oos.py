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

Usage: python scripts/validate_real_oos.py [--limit 100] [--max-pages 10] [--decision-lead-days 2] [--json]
       NOTE: Gamma caps each page at 100 rows regardless of --limit, so the effective
       corpus size is ~min(--limit,100) * --max-pages; grow it via --max-pages, not --limit.
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

    # ROADMAP F10 — anti-overfitting integrity: an aggregate OOS PnL >= floor can still
    # hide a FRAGILE edge concentrated in one horizon / confidence bucket / lucky window /
    # a few markets. Slice the alpha's realized OOS trades and FLAG concentration. This is
    # the go-live audit's regime-slice check, now produced automatically on every real run.
    # The resolved-history fetchers now derive a coarse correlation category and thread it
    # onto each HistoricalMarket (market_category.derive_market_category), so we build a
    # category_by_market_id map and pass it in — enabling analyze_regime_slices' CATEGORY
    # dimension (per-category concentration + leave-one-out on the top category) on real OOS
    # trades, alongside the horizon / confidence / time / single-market checks. A genuinely
    # unlabeled corpus (empty map) still degrades honestly (category checks not assessed).
    rs_mod = _imp("backend.app.prediction_markets.regime_slice",
                  "app.prediction_markets.regime_slice")
    category_by_market_id = {
        m.market_id: m.category for m in markets if getattr(m, "category", None)
    }
    alpha_regime = rs_mod.analyze_regime_slices(
        alpha.trades, category_by_market_id=category_by_market_id or None
    )

    # ROADMAP F11 — significance on the TRADEABLE result. F10 (above) flags whether the PnL is
    # CONCENTRATED; F11 asks the orthogonal question: is the realized PnL distinguishable from
    # ZERO at all? A green total over a small N is routinely noise (a few lucky longshots), so
    # the money claim gets the same bootstrap-CI gate B2 puts on the calibration claim. Only a
    # `significant_positive` verdict (total-PnL CI excludes 0) is candidate edge evidence.
    sig_mod = _imp("backend.app.prediction_markets.bootstrap_oos_significance",
                   "app.prediction_markets.bootstrap_oos_significance")
    alpha_sig = sig_mod.bootstrap_oos_significance(
        [t.pnl_usd for t in alpha.trades], [t.is_win for t in alpha.trades], seed=seed,
    )

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
        "regime_slice_alpha": {
            "n_trades": alpha_regime.n_trades,
            "total_pnl_usd": round(alpha_regime.total_pnl_usd, 2),
            "has_positive_edge": alpha_regime.has_positive_edge,
            "fragile": alpha_regime.fragile,
            "fragile_reasons": list(alpha_regime.fragile_reasons),
            "top_market_pnl_share": alpha_regime.top_market_pnl_share,
            "top_confidence_bucket_pnl_share": _top_slice_pnl_share(alpha_regime.by_confidence),
            "top_horizon_bucket_pnl_share": _top_slice_pnl_share(alpha_regime.by_horizon),
            "n_categories": len(category_by_market_id and set(category_by_market_id.values()) or []),
            "top_category_pnl_share": alpha_regime.top_category_pnl_share,
            "top_category_budget_share": round(alpha_regime.top_category_budget_share, 4),
        },
        "significance_alpha_f11": {
            "n_trades": alpha_sig.n_trades,
            "total_pnl_usd": alpha_sig.total_pnl_usd,
            "total_ci_low": alpha_sig.total_ci_low,
            "total_ci_high": alpha_sig.total_ci_high,
            "hit_rate": alpha_sig.hit_rate,
            "hit_rate_ci_low": alpha_sig.hit_rate_ci_low,
            "hit_rate_ci_high": alpha_sig.hit_rate_ci_high,
            "verdict": alpha_sig.verdict,
            "is_significant_edge": alpha_sig.is_significant_edge,
        },
        "biases_disclosed": ["liquidity-selection (volumeNum order)", "survivorship (clean-resolution only)",
                             "late-life pinning (decision sampled near resolution)"],
        "verdict": (
            "NO EDGE — the calibration alpha traded 0 (crowd well-calibrated on this liquid, near-resolution "
            "sample; needs earlier-life sampling for headroom)."
            if alpha.n_trades == 0 else
            f"alpha took {alpha.n_trades} trades, net ${round(alpha.total_pnl_usd, 2)} OOS"
            + (" — FRAGILE edge (concentration): " + "; ".join(alpha_regime.fragile_reasons)
               if alpha_regime.fragile else "")
            + f" — F11 significance: {alpha_sig.verdict} "
            f"(total-PnL 95% CI [{alpha_sig.total_ci_low}, {alpha_sig.total_ci_high}])"
            + " — NOT a validated edge; requires a larger corpus + a passing B2 calibration eval "
            "+ a NON-fragile (unconcentrated) result whose total-PnL CI EXCLUDES 0 (F11 "
            "significant_positive) over sufficient N, >= floor."
        ),
    }


def _top_slice_pnl_share(slices) -> "float | None":
    """The largest single bucket's share of net PnL among a regime-slice tuple, or None
    when there is no positive net PnL to attribute (each SlicePnL.pnl_share is already
    None in that case — honest, never a fabricated share)."""
    shares = [s.pnl_share for s in slices if s.pnl_share is not None]
    return round(max(shares), 4) if shares else None


def fetch_venue(venue: str, limit: int, max_pages: int, lead_days: float):
    """Fetch leakage-safe HistoricalMarket records for a venue. Returns (markets, status).
    NEVER raises on egress/empty (returns []+note); only a genuine code bug returns a 'code-error'
    status. For Kalshi this doubles as the OA-15 live-contract check: real records = contract holds."""
    try:
        if venue == "polymarket_v1_hf":
            # ROADMAP A6 — the HuggingFace Polymarket-v1 archive (~1.3M markets). Streams +
            # assembles directly (no separate resolved-market step). LAZY-imports `datasets`;
            # a MISSING optional dep is reported N/A (not a code bug), so the default cron
            # (which doesn't install `datasets`) never reddens — this venue is OPT-IN, run on
            # a permitted host with `pip install datasets`.
            m = _imp("backend.app.prediction_markets.polymarket_v1_hf_fetcher",
                     "app.prediction_markets.polymarket_v1_hf_fetcher")
            try:
                markets = m.PolymarketV1HFFetcher().build_historical_markets(
                    decision_lead=timedelta(days=lead_days), max_rows=limit * max_pages,
                )
            except ImportError as e:
                return [], f"N/A — {e} (install `datasets` on a permitted host to run the HF lane)"
            if markets:
                return markets, "ok"
            return [], "N/A — 0 leakage-safe records (HF egress-blocked / schema-unconfirmed / lead too large)"
        if venue == "polymarket":
            m = _imp("backend.app.prediction_markets.polymarket_history_fetcher",
                     "app.prediction_markets.polymarket_history_fetcher")
            f = m.PolymarketHistoryFetcher()
            resolved = f.fetch_resolved_markets(limit=limit, max_pages=max_pages, order="volumeNum")
        else:  # kalshi (public market data — no credentials)
            m = _imp("backend.app.prediction_markets.kalshi_history_fetcher",
                     "app.prediction_markets.kalshi_history_fetcher")
            f = m.KalshiHistoryFetcher()
            resolved = f.fetch_resolved_markets(limit=limit, max_pages=max_pages)
        markets = f.build_historical_markets(resolved, timedelta(days=lead_days))
        if markets:
            return markets, "ok"
        return [], "N/A — 0 leakage-safe records (egress-blocked / contract-unconfirmed / lead too large)"
    except Exception as e:  # a real code break in the fetcher/parser (NOT egress)
        return [], f"code-error {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=100,
                    help="markets per Gamma page (Gamma caps each page at 100 regardless)")
    ap.add_argument("--max-pages", type=int, default=10,
                    help="BOUND on paging; grow the corpus via THIS, not --limit")
    ap.add_argument("--decision-lead-days", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--venues", default="polymarket,kalshi",
                    help="comma-separated: polymarket,kalshi,polymarket_v1_hf "
                         "(polymarket_v1_hf = A6 HuggingFace archive, opt-in; needs `datasets` "
                         "installed on a permitted host — omitted from the default cron)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wf_mod = _imp("backend.app.prediction_markets.walk_forward", "app.prediction_markets.walk_forward")
    cal_mod = _imp("backend.app.prediction_markets.calibration_bucket_strategy",
                   "app.prediction_markets.calibration_bucket_strategy")

    per_venue, all_markets, code_error = {}, [], False
    for venue in [v.strip() for v in args.venues.split(",") if v.strip()]:
        markets, status = fetch_venue(venue, args.limit, args.max_pages, args.decision_lead_days)
        if status.startswith("code-error"):
            code_error = True
        if markets:
            per_venue[venue] = evaluate(markets, wf_mod, cal_mod, seed=args.seed,
                                        decision_lead_days=args.decision_lead_days)
            all_markets.extend(markets)
        else:
            per_venue[venue] = {"status": status}

    combined = (evaluate(all_markets, wf_mod, cal_mod, seed=args.seed,
                         decision_lead_days=args.decision_lead_days)
                if all_markets else {"status": "no records from any venue (egress-blocked / run on a permitted host)"})
    out = {"per_venue": per_venue, "combined": combined}

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for venue, r in per_venue.items():
            if "corpus" in r:
                c, b, a = r["corpus"], r["crowd_baseline"], r["calibration_alpha_b4a"]
                print(f"[{venue}] n={c['n_markets']} Brier={c['crowd_brier']} pinned={c['price_pinned_pct']:.0%} "
                      f"| baseline {b['trades']}tr ${b['total_pnl_usd']:,.2f} | B4a {a['trades']}tr ${a['total_pnl_usd']:,.2f}")
            else:
                print(f"[{venue}] {r['status']}")
        if "corpus" in combined:
            c, a = combined["corpus"], combined["calibration_alpha_b4a"]
            print(f"[COMBINED] n={c['n_markets']} | B4a {a['trades']}tr ${a['total_pnl_usd']:,.2f} — {combined['verdict']}")
    return 1 if code_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
