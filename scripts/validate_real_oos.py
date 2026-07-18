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
from datetime import datetime, timedelta
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
    # STRUCTURAL RESEARCH-ONLY GUARDRAIL (ROADMAP A8): this is the REAL-MONEY OOS floor lane —
    # its verdict feeds go-live-eligibility. A PLAY-MONEY (research_only) record (e.g. Manifold)
    # validates a METHOD but a play-money edge does NOT transfer to real money, so it must NEVER
    # be scored here. Fail LOUD if any slips in (an accidental copy-paste of the research venue
    # into the floor lane) — never silently average play money into the real-money floor.
    research = [getattr(m, "market_id", "?") for m in markets if getattr(m, "research_only", False)]
    if research:
        raise ValueError(
            "validate_real_oos.evaluate is the REAL-MONEY floor lane and refuses research_only "
            f"(play-money) records — {len(research)} found (e.g. {research[:3]}). A play-money edge "
            "never counts toward the profit floor / go-live-eligibility (ROADMAP A8 guardrail)."
        )
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


# ---------------------------------------------------------------------------
# FROZEN CORPUS (ROADMAP F2 / backtest-integrity) — serialize a real leakage-safe
# corpus to a committed JSON artifact so a REAL (not just synthetic) OOS result
# reproduces OFFLINE, deterministically, from committed data — no live egress needed.
# The bytes stored are the SAME leakage-safe HistoricalMarket fields the fetcher built
# (the settled outcome is NEVER the decision price — the fetcher RAISES rather than
# fabricating). Freezing changes NO number: `--from-corpus <file>` replays the exact
# same evaluate() the live fetch would, at a pinned seed, to the SAME seed_hash.
# ---------------------------------------------------------------------------
def corpus_to_rows(markets) -> list:
    """Serialize HistoricalMarket records to a deterministic, JSON-safe row list.

    Every field the walk-forward + F10/F11 gates consume is captured (incl. the coarse
    ``category`` the regime-slice CATEGORY concentration check needs — which the older
    fetch_polymarket_history serializer dropped). Datetimes are ISO-8601 (tz preserved).
    Rows are sorted by (market_id, decision_time) so the file is byte-stable across
    re-serializations of the same corpus (a clean git diff, a reproducible artifact)."""
    rows = [
        {
            "market_id": m.market_id,
            "decision_time": m.decision_time.isoformat(),
            "resolution_time": m.resolution_time.isoformat(),
            "market_price": m.market_price,
            "model_prob": m.model_prob,   # == crowd baseline; a real model overrides this
            "outcome": m.outcome,
            "liquidity": m.liquidity,
            "category": m.category,
            "research_only": m.research_only,
        }
        for m in markets
    ]
    rows.sort(key=lambda r: (r["market_id"], r["decision_time"]))
    return rows


def load_corpus_from_json(path: str, wf_mod) -> list:
    """Load a frozen corpus back into HistoricalMarket records (offline, no egress).

    Reconstructs through the HistoricalMarket constructor so its __post_init__ invariants
    (price in [0,1], outcome in {0,1}, resolution strictly after decision) RE-VALIDATE the
    committed data on every load — a corrupted/tampered corpus fails LOUD, never silently
    scores garbage. datetime.fromisoformat round-trips the tz-aware isoformat above."""
    rows = json.loads(Path(path).read_text())
    if not isinstance(rows, list):
        raise ValueError(f"frozen corpus {path} must be a JSON list of records, got {type(rows).__name__}")
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


def fetch_venue(venue: str, limit: int, max_pages: int, lead_days: float, tag_id=None):
    """Fetch leakage-safe HistoricalMarket records for a venue. Returns (markets, status).
    NEVER raises on egress/empty (returns []+note); only a genuine code bug returns a 'code-error'
    status. For Kalshi this doubles as the OA-15 live-contract check: real records = contract holds.

    ``tag_id`` (Polymarket only) is Gamma's INTEGER server-side category filter (ROADMAP A7/#285):
    it breaks the ``order=volumeNum`` per-category N ceiling so a whole page budget lands inside one
    pre-registered category (resolve the id once from ``GET /tags``; a string category NAME is
    silently ignored by Gamma — only the int filters). It is NOT applicable to the kalshi or
    polymarket_v1_hf lanes; passing it there is a no-op for those venues (reported in the status)."""
    # A --tag-id passed with a non-Polymarket venue is IGNORED — surface it in EVERY return
    # status of that lane (incl. the polymarket_v1_hf early returns) so it is never silently
    # dropped (honest, matches the docstring's "reported in the status" claim).
    note = "" if (tag_id is None or venue == "polymarket") else \
        f" (note: --tag-id is Polymarket-only; ignored for {venue})"
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
                return [], f"N/A — {e} (install `datasets` on a permitted host to run the HF lane)" + note
            if markets:
                return markets, "ok" + note
            return [], "N/A — 0 leakage-safe records (HF egress-blocked / schema-unconfirmed / lead too large)" + note
        if venue == "polymarket":
            m = _imp("backend.app.prediction_markets.polymarket_history_fetcher",
                     "app.prediction_markets.polymarket_history_fetcher")
            f = m.PolymarketHistoryFetcher()
            # tag_id (int, optional) forwards to Gamma's server-side category filter so a
            # pre-registered category (e.g. 100639="Games") fills the whole page budget
            # instead of being starved by the global volumeNum ranking (ROADMAP A7/#285).
            resolved = f.fetch_resolved_markets(
                limit=limit, max_pages=max_pages, order="volumeNum", tag_id=tag_id)
        else:  # kalshi (public market data — no credentials)
            m = _imp("backend.app.prediction_markets.kalshi_history_fetcher",
                     "app.prediction_markets.kalshi_history_fetcher")
            f = m.KalshiHistoryFetcher()
            resolved = f.fetch_resolved_markets(limit=limit, max_pages=max_pages)
        markets = f.build_historical_markets(resolved, timedelta(days=lead_days))
        if markets:
            return markets, "ok" + note
        return [], "N/A — 0 leakage-safe records (egress-blocked / contract-unconfirmed / lead too large)" + note
    except Exception as e:  # a real code break in the fetcher/parser (NOT egress)
        return [], f"code-error {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=100,
                    help="markets per Gamma page (Gamma caps each page at 100 regardless)")
    ap.add_argument("--max-pages", type=int, default=10,
                    help="BOUND on paging; grow the corpus via THIS, not --limit")
    ap.add_argument("--decision-lead-days", type=float, default=2.0)
    ap.add_argument("--tag-id", type=int, default=None,
                    help="Polymarket-only INTEGER Gamma tag id (server-side category filter, "
                         "ROADMAP A7/#285) — breaks the volumeNum per-category N ceiling so a "
                         "PRE-REGISTERED category fills the page budget. Resolve once from GET /tags "
                         "(e.g. 100639='Games'); a category NAME is silently ignored by Gamma. "
                         "Ignored for the kalshi / polymarket_v1_hf lanes.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--venues", default="polymarket,kalshi",
                    help="comma-separated: polymarket,kalshi,polymarket_v1_hf "
                         "(polymarket_v1_hf = A6 HuggingFace archive, opt-in; needs `datasets` "
                         "installed on a permitted host — omitted from the default cron)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--from-corpus", default=None,
                    help="REPLAY a FROZEN corpus (a committed JSON produced by --freeze-corpus) "
                         "OFFLINE — no live fetch, no egress. Reproduces the exact same real OOS "
                         "result deterministically from committed data (ROADMAP F2 / backtest "
                         "integrity). Mutually exclusive with a live fetch.")
    ap.add_argument("--freeze-corpus", default=None,
                    help="After the live fetch, SERIALIZE the combined leakage-safe corpus to this "
                         "JSON path (incl. category for the F10 regime-slice check), so the real OOS "
                         "result can later be reproduced offline via --from-corpus. Run on a "
                         "Polymarket-permitted host.")
    args = ap.parse_args()

    wf_mod = _imp("backend.app.prediction_markets.walk_forward", "app.prediction_markets.walk_forward")
    cal_mod = _imp("backend.app.prediction_markets.calibration_bucket_strategy",
                   "app.prediction_markets.calibration_bucket_strategy")

    # OFFLINE REPLAY of a frozen corpus — deterministic, no venue fetch, no egress. This is
    # the reproduce-from-committed-artifacts path: the same evaluate() the live lane runs,
    # over pinned bytes, to the same seed_hash. NEVER trades, NEVER touches money.
    if args.from_corpus:
        markets = load_corpus_from_json(args.from_corpus, wf_mod)
        result = evaluate(markets, wf_mod, cal_mod, seed=args.seed,
                          decision_lead_days=args.decision_lead_days)
        out = {"frozen_corpus": args.from_corpus, "combined": result}
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            c, a = result["corpus"], result["calibration_alpha_b4a"]
            print(f"[FROZEN {args.from_corpus}] n={c['n_markets']} | B4a {a['trades']}tr "
                  f"${a['total_pnl_usd']:,.2f} — {result['verdict']}")
        return 0

    per_venue, all_markets, code_error = {}, [], False
    for venue in [v.strip() for v in args.venues.split(",") if v.strip()]:
        markets, status = fetch_venue(venue, args.limit, args.max_pages, args.decision_lead_days,
                                      tag_id=args.tag_id)
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

    # FREEZE the fetched corpus to a committed artifact so this real OOS result reproduces
    # OFFLINE (no egress) via --from-corpus. Only write when we actually fetched records.
    if args.freeze_corpus:
        if all_markets:
            p = Path(args.freeze_corpus)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(corpus_to_rows(all_markets), indent=2, sort_keys=True) + "\n")
            out["frozen_to"] = str(p)
        else:
            out["frozen_to"] = "SKIPPED — 0 records fetched (nothing to freeze)"

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
