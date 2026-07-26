#!/usr/bin/env python3
"""fetch_spike_corpus.py — build a REAL, leakage-safe intraday-tick corpus for the
EXP-006 fade-the-spike backtest (``prediction_markets.spike_reversal_backtest``).

WHY THIS EXISTS
The EXP-006 fade engine (built + audited-sound, #385/#387) has never run on real data:
every prior run filed "needs a real point-in-time, non-survivorship intraday-tick corpus"
to ROADMAP as egress-gated. This driver produces exactly that corpus — a JSON map
``{market_id: [{"t": unix_s, "p": 0..1}, ...]}`` in the shape ``run_spike_reversal.py
--data`` consumes — from Polymarket's PUBLIC Gamma + CLOB APIs (no credentials).

It reuses the audited, leakage-safe ``PolymarketHistoryFetcher`` verbatim
(``fetch_resolved_markets`` for the universe, ``fetch_price_history`` for the ticks) — it
does NOT re-implement any parsing. The only new logic here is (a) CHUNKING the hourly
fetch into <=15-day windows (the CLOB caps ``fidelity=60`` at ~360 ticks / 15 days per
request — verified live 2026-07-19) and (b) TRUNCATING each series strictly before
settlement so no fade exit can read a post-resolution pinned tick.

ANTI-LEAKAGE / ANTI-SETTLEMENT-PIN (the load-bearing discipline — read before trusting a number):
  * The market UNIVERSE is selected by a DECISION-TIME-OBSERVABLE, PRE-REGISTERED criterion:
    resolved binary Politics markets (Gamma ``tag_id=2`` = "Politics", verified live), ranked
    by ``order=volumeNum`` (all-time volume). Selection never consults a spike's forward
    behavior — the fade engine detects spikes causally inside each series; markets are not
    picked for having spiked or for how a spike resolved.
  * Each series is TRUNCATED to ticks strictly before ``resolution_time - LEAKAGE_MARGIN``,
    where LEAKAGE_MARGIN >= the engine's reversal horizon (default 24h). This GUARANTEES a
    faded spike's forward-horizon exit tick is strictly pre-resolution — it can never book a
    settlement pin (0.0/1.0) as "reversion". Spikes in the final horizon-window are thereby
    dropped (no clean forward exit) — the correct leakage-safe behavior, not a loss.
  * DISCLOSED SELECTION / SURVIVORSHIP / PINNING BIAS: (1) ``order=volumeNum`` selects LIQUID
    markets (deep books) — a liquidity bias; (2) excluding ambiguous/contested/unsettled
    markets biases toward clean crowd-friendly outcomes; (3) ``--window-cap-days`` bounds each
    fetch to the final active period before resolution, where hype spikes cluster but where the
    crowd is also closer to pinning. All three are PRE-REGISTERED here and OVERSTATE crowd
    calibration / fade-ability — any result MUST say so. These are honest selection profiles,
    not leakage.
  * Cross-market EVENT CORRELATION is NOT removed: several top-volume Politics markets are the
    same underlying event (e.g. "Trump win" / "Harris win" / "Trump inaugurated"). The engine's
    ``max_trades_per_market=1`` caps PER-MARKET, and F10's single-market check gates per-market
    concentration, but same-event cross-market correlation remains a disclosed limitation (as in
    every EXP-006 pilot run). Read the F10 report + cluster caveat before any edge claim.

DETERMINISM: the universe order (volumeNum, fixed pages) and the per-market chunking are
deterministic given a fixed fetch date; the CLOB history for a RESOLVED market is immutable,
so re-running yields the same ticks. The corpus embeds a provenance header (fetch params +
UTC date, passed in via --stamp so the module stays Date.now-free).

Usage:
  python3 scripts/fetch_spike_corpus.py --out data/spike_corpus_politics.json \
      --cats-out data/spike_corpus_politics_cats.json --max-pages 3 \
      --window-cap-days 120 --stamp 2026-07-19
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.polymarket_history_fetcher import (  # noqa: E402
    PolymarketHistoryFetcher,
    ResolvedMarket,
)

# --- PRE-REGISTERED fetch parameters (documented, not tuned on any result) ---
POLITICS_TAG_ID = 2          # Gamma "Politics" tag (verified live 2026-07-19)
FIDELITY_MIN = 60            # hourly ticks — matches the engine's 1h window / 24h horizon
CHUNK_DAYS = 15              # CLOB caps fidelity=60 at ~360 ticks (15 days) per request
DEFAULT_LEAKAGE_MARGIN_HOURS = 24  # >= the engine's default 24h reversal horizon


def _chunked_price_history(
    fetcher: PolymarketHistoryFetcher,
    token_id: str,
    start_ts: int,
    end_ts: int,
) -> list[dict]:
    """Fetch [start_ts, end_ts] hourly ticks in <=CHUNK_DAYS windows and concatenate.

    The CLOB returns 0 ticks for a fidelity=60 request spanning more than ~15 days, so a
    long-lived market MUST be paged in bounded windows. Ticks are merged and de-duplicated
    by timestamp (chunk boundaries can repeat an edge tick); ``clean_ticks`` in the engine
    re-sorts/validates, but we de-dup here to keep the committed corpus tidy.
    """
    span = CHUNK_DAYS * 86400
    merged: dict[int, float] = {}
    cur = start_ts
    while cur < end_ts:
        chunk_end = min(cur + span, end_ts)
        hist = fetcher.fetch_price_history(token_id, cur, chunk_end, fidelity=FIDELITY_MIN)
        for tick in hist:
            try:
                t = int(tick["t"])
                p = float(tick["p"])
            except (KeyError, TypeError, ValueError):
                continue
            merged[t] = p  # last write wins on an exact-duplicate boundary timestamp
        cur = chunk_end
    return [{"t": t, "p": merged[t]} for t in sorted(merged)]


def _build_series(
    fetcher: PolymarketHistoryFetcher,
    rm: ResolvedMarket,
    window_cap_days: int,
    leakage_margin_seconds: int,
) -> list[dict]:
    """Build one market's leakage-safe, pre-settlement-truncated hourly tick series."""
    resolution_ts = int(rm.resolution_time.timestamp())
    # Truncate strictly before settlement so no fade exit can touch a resolution pin.
    cutoff_ts = resolution_ts - leakage_margin_seconds
    # Fetch the final active window (or the whole life if shorter).
    start_ts = cutoff_ts - window_cap_days * 86400
    if rm.start_date is not None:
        start_ts = max(start_ts, int(rm.start_date.timestamp()))
    if start_ts >= cutoff_ts:
        return []
    raw = _chunked_price_history(fetcher, rm.yes_token_id, start_ts, cutoff_ts)
    # Hard leakage guard: drop anything at/after the cutoff (belt-and-suspenders — the
    # fetch already ends at cutoff_ts, but a boundary tick could equal it).
    # PRE-CONDITION on the CUTOFF DERIVATION — the part that was actually wrong.
    #
    # An earlier version of this check re-tested `series[-1]["t"] < cutoff_ts` immediately
    # after the list comprehension that guarantees exactly that: mathematically unreachable
    # dead code that looked like a safety net (a re-reviewer correctly called it vacuous).
    # The filter was never the weak link — `cutoff_ts` was, because it derives from
    # `rm.resolution_time`, which used to resolve to the SCHEDULED `endDate` rather than
    # actual settlement and so sat days late for 22% of markets. So check the DERIVATION:
    # the cutoff must genuinely precede the recorded resolution by the full margin. This
    # fires on a margin misconfiguration or a resolution timestamp that arrives non-finite
    # or reversed — none of which the filter can catch.
    if cutoff_ts != resolution_ts - leakage_margin_seconds or cutoff_ts >= resolution_ts:
        raise AssertionError(
            f"leakage-margin derivation invalid for market {rm.market_id}: cutoff "
            f"{cutoff_ts} is not {leakage_margin_seconds}s before resolution "
            f"{resolution_ts}"
        )
    return [tick for tick in raw if tick["t"] < cutoff_ts]


def _load_exclusions(path: Optional[str], ap: argparse.ArgumentParser) -> set[str]:
    """Read a market-id exclusion set from a JSON list OR any JSON object's keys.

    Accepting an object's keys means a prior corpus's ``--cats-out`` sidecar
    (``{market_id: category}``) is a valid exclusion file with no reshaping, which is the
    common case and removes a step where a hand-built list could silently miss ids.

    Fails LOUD on a missing/unparseable/empty file. A silently-empty exclusion set is the
    dangerous failure here: the run would look like a fresh OOS fetch while actually
    re-selecting the same markets, and the resulting "out-of-sample" verdict would be a
    re-test of in-sample data.
    """
    if not path:
        return set()
    p = Path(path)
    if not p.is_file():
        ap.error(f"--exclude-market-ids: no such file: {path}")
    try:
        blob = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        ap.error(f"--exclude-market-ids: unreadable JSON in {path}: {type(e).__name__}")
    if isinstance(blob, dict):
        ids = {str(k) for k in blob}
    elif isinstance(blob, list):
        ids = {str(x) for x in blob}
    else:
        ap.error(f"--exclude-market-ids: {path} must be a JSON list or object, got "
                 f"{type(blob).__name__}")
    if not ids:
        ap.error(f"--exclude-market-ids: {path} yielded ZERO ids — refusing to run, because "
                 "an empty exclusion set silently produces an overlapping corpus")
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="path for the {market_id:[{t,p}]} tick JSON")
    ap.add_argument("--cats-out", help="path for the {market_id:category} JSON")
    ap.add_argument("--meta-out", help="path for a provenance/metadata JSON")
    ap.add_argument("--max-pages", type=int, default=3, help="Gamma pages (~100 markets/page)")
    ap.add_argument("--window-cap-days", type=int, default=120,
                    help="fetch only the final N days before resolution (bounds fetch, "
                         "focuses on the active hype period — a disclosed selection bound)")
    ap.add_argument("--leakage-margin-hours", type=float, default=DEFAULT_LEAKAGE_MARGIN_HOURS,
                    help="truncate ticks this far before resolution (must be >= the engine "
                         "reversal horizon so no fade exit reads a settlement pin)")
    ap.add_argument("--min-ticks", type=int, default=24,
                    help="drop markets with fewer than this many pre-settlement ticks "
                         "(too thin for hourly spike detection)")
    ap.add_argument("--tag-id", type=int, default=POLITICS_TAG_ID,
                    help="Gamma tag id for the universe (default 2 = Politics)")
    ap.add_argument("--exclude-market-ids",
                    help="path to a JSON list of market ids — or any JSON object whose KEYS "
                         "are market ids, so a prior run's --cats-out sidecar can be passed "
                         "directly. Excluded markets are dropped from the universe BEFORE any "
                         "tick is fetched. This is the ONLY mechanism that makes a second "
                         "corpus structurally DISJOINT from a first: the volumeNum ranking of "
                         "resolved markets is near-stable, so re-fetching with the same "
                         "parameters would silently re-select most of the same markets and a "
                         "'fresh OOS' run would be re-testing already-tested data.")
    ap.add_argument("--stamp", default="unstamped", help="UTC date string for provenance")
    args = ap.parse_args()

    margin_s = int(args.leakage_margin_hours * 3600)
    # Fail LOUD on a config that would DEFEAT the leakage guard: a non-positive margin
    # pushes the truncation cutoff at/after resolution_time, so a fade exit could read a
    # settlement pin. The default is safe; this rejects a foot-gun override.
    if margin_s <= 0:
        ap.error("--leakage-margin-hours must be positive (it must be >= the engine "
                 "reversal horizon so no fade exit can read a settlement pin)")
    if args.window_cap_days <= 0:
        ap.error("--window-cap-days must be positive")
    excluded = _load_exclusions(args.exclude_market_ids, ap)
    fetcher = PolymarketHistoryFetcher()

    print(f"[1/3] fetching resolved markets (tag_id={args.tag_id}, "
          f"order=volumeNum, max_pages={args.max_pages}) ...", file=sys.stderr)
    markets = fetcher.fetch_resolved_markets(
        limit=100, max_pages=args.max_pages, order="volumeNum", tag_id=args.tag_id,
    )
    n_fetched = len(markets)
    if excluded:
        markets = [m for m in markets if str(m.market_id) not in excluded]
        print(f"      excluded {n_fetched - len(markets)} already-tested markets "
              f"({len(excluded)} ids supplied)", file=sys.stderr)
        if not markets:
            # Fail LOUD rather than silently writing an empty "fresh" corpus, which would
            # then be reported as an honest null when in fact nothing was tested.
            print("FATAL: every fetched market was excluded — the universe is exhausted at "
                  "this --max-pages. Raise --max-pages or the corpus is not obtainable.",
                  file=sys.stderr)
            return 2
    print(f"      got {len(markets)} resolved binary markets (of {n_fetched} fetched)",
          file=sys.stderr)

    ticks_by_market: dict[str, list[dict]] = {}
    cats: dict[str, str] = {}
    n_thin = 0
    print(f"[2/3] fetching hourly tick series (window_cap={args.window_cap_days}d, "
          f"leakage_margin={args.leakage_margin_hours}h) ...", file=sys.stderr)
    for i, rm in enumerate(markets):
        try:
            series = _build_series(fetcher, rm, args.window_cap_days, margin_s)
        except Exception as e:  # one bad market must not kill the corpus
            print(f"      [{i}] skip {rm.market_id}: {e}", file=sys.stderr)
            continue
        if len(series) < args.min_ticks:
            n_thin += 1
            continue
        ticks_by_market[rm.market_id] = series
        cats[rm.market_id] = rm.category
        if (i + 1) % 25 == 0:
            print(f"      {i + 1}/{len(markets)} markets processed, "
                  f"{len(ticks_by_market)} kept", file=sys.stderr)

    total_ticks = sum(len(v) for v in ticks_by_market.values())
    print(f"[3/3] kept {len(ticks_by_market)} markets ({total_ticks} ticks total); "
          f"dropped {n_thin} thin (<{args.min_ticks} ticks)", file=sys.stderr)

    Path(args.out).write_text(json.dumps(ticks_by_market))
    print(f"      wrote {args.out}", file=sys.stderr)
    if args.cats_out:
        Path(args.cats_out).write_text(json.dumps(cats, indent=0))
        print(f"      wrote {args.cats_out}", file=sys.stderr)
    if args.meta_out:
        meta = {
            "fetched_utc": args.stamp,
            "source": "Polymarket Gamma + CLOB (public, no credentials)",
            "universe": {
                "tag_id": args.tag_id,
                "tag": "Politics" if args.tag_id == POLITICS_TAG_ID else f"tag_{args.tag_id}",
                "order": "volumeNum",
                "max_pages": args.max_pages, "resolved_binary_only": True,
                "excluded_market_ids_source": args.exclude_market_ids,
                "excluded_market_ids_count": len(excluded),
                "markets_excluded_from_universe": n_fetched - len(markets),
            },
            "ticks": {
                "fidelity_min": FIDELITY_MIN, "chunk_days": CHUNK_DAYS,
                "window_cap_days": args.window_cap_days,
                "leakage_margin_hours": args.leakage_margin_hours,
                "min_ticks": args.min_ticks,
            },
            "markets_fetched": n_fetched,
            "markets_after_exclusion": len(markets),
            "markets_kept": len(ticks_by_market),
            "markets_dropped_thin": n_thin,
            "total_ticks": total_ticks,
            "disclosures": [
                "liquidity-selection bias (volumeNum)",
                "settled-only survivorship bias",
                "final-window sampling bias (window_cap_days)",
                "cross-market same-event correlation NOT removed",
                "ticks truncated strictly before resolution - leakage_margin (no settlement pin)",
            ],
        }
        Path(args.meta_out).write_text(json.dumps(meta, indent=2))
        print(f"      wrote {args.meta_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
