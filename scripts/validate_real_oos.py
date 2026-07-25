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


def _lead_days(markets) -> list:
    """Per-record decision lead in days, measured from the data itself."""
    return [
        (m.resolution_time - m.decision_time).total_seconds() / 86400.0 for m in markets
    ]


def _measured_lead_days(markets) -> "float | None":
    """The corpus's ACTUAL decision lead (median), or None on an empty corpus.

    Reporting the caller's *requested* lead as if it described the data is how the frozen
    replay came to publish ``decision_lead_days: 2.0`` (the CLI default) for a corpus whose
    187 records are uniformly 7.0 — a reported metric that did not describe the data, and
    one the committed test (which hard-codes 7.0) silently disagreed with.
    """
    leads = _lead_days(markets)
    return round(statistics.median(leads), 4) if leads else None


def _measured_lead_days_range(markets) -> "list | None":
    """``[min, max]`` lead in days — makes a NON-uniform corpus visible instead of letting a
    single median imply a uniformity the data does not have."""
    leads = _lead_days(markets)
    return [round(min(leads), 4), round(max(leads), 4)] if leads else None


def evaluate(
    markets, wf_mod, cal_mod, *, seed: int = 42, decision_lead_days: float = 2.0,
    category_exposure_cap: "float | None" = None,
    cumulative_category_budget_cap: "float | None" = None,
) -> dict:
    """Pure OOS evaluation on already-fetched leakage-safe markets (injectable for tests):
    crowd baseline vs. the B4a calibration alpha, + corpus stats + an honest verdict.

    When ``category_exposure_cap`` and/or ``cumulative_category_budget_cap`` is set (each a
    fraction in (0, 1]), an ADDITIONAL ``concentration_capped_variant`` block is appended: the
    Run 20-22 named per-CATEGORY de-concentration controls, run on BOTH the static calibration
    alpha AND the recency-weighted alpha, each with F10/F11 — the honest test of whether
    bounding correlated-cluster concentration rescues the REFUTED bucket family (it cannot
    create an edge; it only removes concentration). ``category_exposure_cap`` bounds CONCURRENT
    open exposure; ``cumulative_category_budget_cap`` bounds the LIFETIME per-category budget
    SHARE F10 actually gates on (the faithful control, Run 21). Default None/None leaves the
    report byte-for-byte unchanged, so the live/frozen lanes and their pinned outputs are
    untouched."""
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

    report = {
        "corpus": {
            "n_markets": n, "yes_base_rate": round(sum(outs) / n, 4),
            "crowd_brier": round(crowd_brier, 4), "price_pinned_pct": round(pinned, 3),
            "price_median": round(statistics.median(prices), 4),
            # MEASURED from the corpus, not echoed from the CLI. `..._requested` keeps the
            # caller's parameter visible (it is what the LIVE lane actually fetches with) and
            # `..._range` surfaces a non-uniform corpus rather than hiding it behind a median.
            "decision_lead_days": _measured_lead_days(markets),
            "decision_lead_days_requested": decision_lead_days,
            "decision_lead_days_range": _measured_lead_days_range(markets),
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

    if category_exposure_cap is not None or cumulative_category_budget_cap is not None:
        rec_mod = _imp(
            "backend.app.prediction_markets.recency_weighted_bucket_strategy",
            "app.prediction_markets.recency_weighted_bucket_strategy",
        )

        def _variant(strategy_fn, *, concurrent=None, cumulative=None) -> dict:
            """Run one strategy (optionally de-concentrated) through walk_forward + F10 + F11 and
            return the honest compact result. Category labels feed F10 exactly as the primary
            alpha's do. ``concurrent`` = per-category CONCURRENT exposure cap;
            ``cumulative`` = per-category CUMULATIVE budget-SHARE cap (the F10-faithful one)."""
            res = wf_mod.walk_forward_backtest(
                markets, strategy_fn=strategy_fn, seed=seed,
                category_exposure_cap=concurrent,
                cumulative_category_budget_cap=cumulative,
            )
            reg = rs_mod.analyze_regime_slices(
                res.trades, category_by_market_id=category_by_market_id or None
            )
            sig = sig_mod.bootstrap_oos_significance(
                [t.pnl_usd for t in res.trades], [t.is_win for t in res.trades], seed=seed,
            )
            # The cumulative cap admits a DISCLOSED bootstrap slack: the exempt first deployed
            # trade can push its category above the cap by up to (its budget ÷ total budget),
            # which shrinks as turnover grows. Report that bound so the faithful-share check
            # allows exactly it — never more (see walk_forward's cap docstring).
            budgets = [t.budget_usd for t in res.trades]
            total_b = sum(budgets)
            max_trade_budget_share = (max(budgets) / total_b) if total_b > 0 else 0.0
            return {
                "trades": res.n_trades,
                "total_pnl_usd": round(res.total_pnl_usd, 2),
                "seed_hash": res.seed_hash,
                "f10_fragile": reg.fragile,
                "f10_fragile_reasons": list(reg.fragile_reasons),
                # A non-fragile F10 pass is VACUOUS when the aggregate is non-positive — F10 only
                # assesses concentration on a POSITIVE edge (there is nothing to concentrate).
                "f10_nonfragile_is_vacuous": (not reg.fragile) and res.total_pnl_usd <= 0.0,
                "top_category_budget_share": round(reg.top_category_budget_share, 4),
                "max_trade_budget_share": round(max_trade_budget_share, 4),
                "f11_verdict": sig.verdict,
                "f11_total_ci": [sig.total_ci_low, sig.total_ci_high],
                "f11_is_significant_edge": sig.is_significant_edge,
            }

        conc = category_exposure_cap
        cum = cumulative_category_budget_cap

        def _bound(capped: dict, uncapped: dict) -> bool:
            # Machine-readable disclosure: did the cap actually ENGAGE, or was it a no-op on
            # this corpus? (A concurrent cap does not bind when turnover recycles category room.)
            return (
                capped["trades"] != uncapped["trades"]
                or capped["total_pnl_usd"] != uncapped["total_pnl_usd"]
            )

        def _family(make) -> dict:
            """Build the uncapped + (present) capped variants for one strategy family."""
            uncapped = _variant(make(), concurrent=None, cumulative=None)
            out = {"uncapped": uncapped}
            if conc is not None:
                cc = _variant(make(), concurrent=conc, cumulative=None)
                cc["cap_bound"] = _bound(cc, uncapped)
                out["concurrent_capped"] = cc
            if cum is not None:
                mc = _variant(make(), concurrent=None, cumulative=cum)
                mc["cap_bound"] = _bound(mc, uncapped)
                # The FAITHFUL check: the cumulative cap's job is to bound F10's own
                # top_category_budget_share to <= cum + the DISCLOSED bootstrap slack (the exempt
                # first trade). Include that slack term — under-allowing it would falsely flag a
                # correctly-operating cap. Meaningful only where the cap actually ENGAGED (a
                # single-category / no-op corpus legitimately keeps share=1.0 and does not bind).
                # RESIDUAL GUARD: if a strategy trades a SINGLE category even though the corpus
                # carries >=2 (so walk_forward's <2-category no-op did NOT trigger and the cap
                # engaged), the book collapses to the bootstrap trade at share==1.0 with
                # max_trade_budget_share==1.0 — which would pass the slack check VACUOUSLY. A
                # realized 100% share is definitionally NOT de-concentrated below the cap, so we
                # require share strictly < 1.0 to call it bounded (this is unreachable in the
                # shipped evaluate() flow — the bucket alphas trade across categories — but keeps
                # the "BOUND, holding at/under the cap" verdict honest if a future single-category
                # strategy ever engages the cap).
                mc["cumulative_share_bounded"] = (
                    mc["trades"] == 0
                    or (mc["top_category_budget_share"] < 1.0 - 1e-9
                        and mc["top_category_budget_share"] <= cum + mc["max_trade_budget_share"] + 1e-6)
                )
                out["cumulative_capped"] = mc
            return out

        calibration = _family(cal_mod.make_calibration_bucket_strategy)
        recency_weighted = _family(rec_mod.make_recency_weighted_bucket_strategy)
        families = (calibration, recency_weighted)

        conc_views = [f["concurrent_capped"] for f in families if "concurrent_capped" in f]
        cum_views = [f["cumulative_capped"] for f in families if "cumulative_capped" in f]
        all_views = [f["uncapped"] for f in families] + conc_views + cum_views

        any_conc_bound = any(v["cap_bound"] for v in conc_views)
        any_cum_bound = any(v["cap_bound"] for v in cum_views)
        # The faithful-share check is only meaningful where the cap ENGAGED — a no-op corpus
        # (single-category / cap>=1) legitimately keeps a 100% share and is NOT a breach.
        engaged_cum_views = [v for v in cum_views if v["cap_bound"]]
        cum_share_bounded_where_engaged = all(
            v["cumulative_share_bounded"] for v in engaged_cum_views
        )
        any_validated = any(
            v["f11_is_significant_edge"] and not v["f10_fragile"] for v in all_views
        )
        report["concentration_capped_variant"] = {
            "category_exposure_cap": conc,
            "cumulative_category_budget_cap": cum,
            "concurrent_cap_bound_on_this_corpus": any_conc_bound,
            "cumulative_cap_bound_on_this_corpus": any_cum_bound,
            "cumulative_share_bounded_where_engaged": cum_share_bounded_where_engaged,
            "calibration": calibration,
            "recency_weighted": recency_weighted,
            "seed_hash_note": (
                "seed_hash excludes strategy_fn (walk_forward contract), so different strategies "
                "with the same data+config share a hash — compare trades/PnL, NOT hashes, across "
                "variants."
            ),
            "verdict": _concentration_verdict(
                conc=conc, cum=cum, any_conc_bound=any_conc_bound, any_cum_bound=any_cum_bound,
                engaged_share_bounded=cum_share_bounded_where_engaged,
                all_views=all_views, any_validated=any_validated,
            ),
        }
    return report


def _concentration_verdict(*, conc, cum, any_conc_bound, any_cum_bound,
                           engaged_share_bounded, all_views, any_validated) -> str:
    """Honest, evidence-derived verdict for the de-concentration variant. It NEVER hard-codes a
    PnL sign or narrates a cap that was not requested — it reads the ACTUAL realized state:
      * mentions the concurrent / cumulative cap ONLY when that cap was requested, and reports
        whether it bound;
      * names the REAL reason no validated de-concentrated edge exists — net-negative signal,
        F11-insignificant positive noise, or an F11-significant-positive result that is still
        F10-FRAGILE on a non-category dimension (which a CATEGORY cap cannot fix) — rather than
        assuming negativity.
    """
    if any_validated:
        return (
            "A variant is BOTH F11-significant-positive AND F10-non-fragile on this corpus — "
            "record it and re-test on a LARGER pre-registered per-category corpus before any "
            "claim (single-corpus significance is not a validated edge)."
        )
    parts = [
        "A per-category de-concentration cap is a RISK CONTROL, not an alpha: it can only "
        "reduce/reallocate exposure, never manufacture PnL."
    ]
    if conc is not None:
        parts.append("Concurrent cap: " + ("BOUND" if any_conc_bound else "did not bind") + " here.")
    if cum is not None:
        if any_cum_bound:
            parts.append(
                "Cumulative budget-share cap: BOUND, "
                + ("holding every engaged family's top_category_budget_share at/under the cap "
                   "(+ disclosed bootstrap slack)."
                   if engaged_share_bounded else
                   "but a realized top share EXCEEDED cap + disclosed slack — investigate.")
            )
        else:
            parts.append("Cumulative budget-share cap: did not bind here (no-op or nothing to reallocate).")
    positive_sig = [v for v in all_views if v["total_pnl_usd"] > 0 and v["f11_is_significant_edge"]]
    positive_any = [v for v in all_views if v["total_pnl_usd"] > 0]
    if positive_sig:
        reasons = sorted({r for v in positive_sig for r in v["f10_fragile_reasons"]})
        joined = ("; ".join(reasons))[:240]
        parts.append(
            "No variant is BOTH F11-significant-positive AND F10-non-fragile: the "
            "F11-significant positive variant(s) remain F10-FRAGILE"
            + (f" ({joined})" if joined else "")
            + " — and a CATEGORY de-concentration cap does not address horizon / confidence / "
            "single-market concentration. NOT a validated edge."
        )
    elif positive_any:
        parts.append(
            "No variant clears the bar: the positive PnL is not F11-distinguishable from zero "
            "(noise). NOT a validated edge."
        )
    else:
        parts.append(
            "The signal is net-NEGATIVE on this corpus — no concentration control can manufacture "
            "an edge from a losing signal. Honest NULL."
        )
    parts.append(
        "The cumulative cap the family test needed now EXISTS; the remaining ingredient is a "
        "net-positive-but-fragile per-category corpus (egress-gated; filed to "
        "RESEARCH_MEMORY/ROADMAP)."
    )
    return " ".join(parts)


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
    ap.add_argument("--category-exposure-cap", type=float, default=None,
                    help="Fraction in (0, 1]. When set, ALSO run the per-CATEGORY CONCURRENT "
                         "exposure-cap variant (Run 20-22's named concentration fix) on both the "
                         "static calibration and recency-weighted bucket alphas, each with F10/F11 — "
                         "the honest test of whether bounding correlated-cluster concentration "
                         "rescues the REFUTED bucket family. Off by default (report unchanged).")
    ap.add_argument("--cumulative-category-budget-cap", type=float, default=None,
                    help="Fraction in (0, 1]. When set, ALSO run the per-CATEGORY CUMULATIVE "
                         "budget-SHARE cap variant — the F10-FAITHFUL de-concentration control "
                         "(Run 21) the concurrent cap could not provide: it bounds the LIFETIME "
                         "Σ-budget share F10's top_category_budget_share measures. Off by default.")
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
                          decision_lead_days=args.decision_lead_days,
                          category_exposure_cap=args.category_exposure_cap,
                          cumulative_category_budget_cap=args.cumulative_category_budget_cap)
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
                                        decision_lead_days=args.decision_lead_days,
                                        category_exposure_cap=args.category_exposure_cap,
                                        cumulative_category_budget_cap=args.cumulative_category_budget_cap)
            all_markets.extend(markets)
        else:
            per_venue[venue] = {"status": status}

    combined = (evaluate(all_markets, wf_mod, cal_mod, seed=args.seed,
                         decision_lead_days=args.decision_lead_days,
                         category_exposure_cap=args.category_exposure_cap,
                         cumulative_category_budget_cap=args.cumulative_category_budget_cap)
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
