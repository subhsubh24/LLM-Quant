#!/usr/bin/env python3
"""capacity_probe.py — measure the REAL order-book depth distribution on live Polymarket
markets, so the capacity analysis sweeps a range grounded in observed data instead of a
guessed one.

WHY THIS EXISTS
`backend/app/prediction_markets/capacity.py` can price any (size, depth) pair, but depth at a
past decision instant is UNOBTAINABLE: Polymarket serves `liquidity: null` on resolved markets
and returns HTTP 404 from CLOB `/book` for a settled token (both verified live 2026-07-26).
That is why every committed OOS record carries `liquidity: null` — the venue does not retain
the value, so no amount of fetcher plumbing can recover it.

Depth IS observable on OPEN markets, right now. This probe samples it and writes a committed
artifact, which does two things:
  1. It bounds the capacity sweep with real numbers (what depth actually looks like in the
     categories this bot trades) rather than an invented range.
  2. It is the first half of the buildable path to a MEASURED capacity curve: capture depth at
     DECISION time going forward, and future corpora become capacity-testable instead of
     capacity-assumed.

WHAT IT MEASURES (and the honest limits of each)
  * `depth_at_touch_contracts` — size resting at the best ask. What a small taker actually
    lifts. Narrow but exact.
  * `depth_within_2c` / `depth_within_5c` — cumulative ask size within 2 / 5 cents of the
    touch. The practical executable depth for a taker willing to pay a bounded amount of
    slippage. This is the number the capacity analysis should key on.
  * `total_ask_contracts` — the whole visible ask ladder. Reported for context and
    deliberately NOT used as capacity: on a prediction market the far tail of the book is
    penny-priced resting orders (a 3.96M-contract order at $0.001 was observed), which are
    real but are not depth anyone can trade against at a useful price.

DISCLOSED BIASES (this is a SNAPSHOT of OPEN markets)
  * Open markets sampled by volume are the LIQUID end. Depth here OVERSTATES what a
    randomly-chosen market offers.
  * A single instant. Depth varies with time of day, news, and time-to-resolution.
  * Open markets are not the same population as the RESOLVED markets in the OOS corpora, so
    this is a plausibility range for the sweep — not a measurement of the corpora's depth.
    Nothing here licenses a capacity CLAIM; it makes the sweep honest.

Read-only. Public endpoints, no credentials, no orders, no writes to any venue.

Usage:
  python3 scripts/capacity_probe.py --out data/depth_probe_polymarket.json \
      --limit 60 --stamp 2026-07-26
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.prediction_markets.polymarket_client import (  # noqa: E402
    PolymarketClient,
)

# Slippage bands the executable-depth measures use. Pre-registered here, not tuned.
BAND_CENTS = (0.02, 0.05)
# How many ask levels (best-first) to persist per token for offline impact calibration.
LADDER_LEVELS = 40


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank percentile on an already-sorted list. Stdlib-only and deterministic.

    Nearest-rank (rather than interpolating) is deliberate: these are order sizes, and an
    interpolated value between two real book levels is not a size anyone can trade.
    """
    if not sorted_vals:
        raise ValueError("percentile of an empty sample")
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _summarize(vals: list[float]) -> dict:
    if not vals:
        # Never fabricate a distribution. An empty sample is reported as empty.
        return {"n": 0}
    s = sorted(vals)
    return {
        "n": len(s),
        "min": round(s[0], 4),
        "p25": round(_percentile(s, 0.25), 4),
        "median": round(median(s), 4),
        "p75": round(_percentile(s, 0.75), 4),
        "max": round(s[-1], 4),
    }


def probe_market(client: PolymarketClient, token_id: str) -> dict | None:
    """Depth statistics for one token's ask side, or None if the book is not a real quote.

    Uses `get_order_book`, which already drops malformed levels and REFUSES a one-sided
    book rather than fabricating a 0/1 quote — so a market with no real two-sided market is
    skipped, not counted as zero depth (which would understate the distribution and look
    like conservatism while actually being a data error).
    """
    book = client.get_order_book(token_id)
    if book is None:
        return None
    asks = book.asks
    if not asks:
        return None
    best_ask = book.best_ask
    row: dict = {
        "token_id": token_id,
        "best_bid": book.best_bid,
        "best_ask": best_ask,
        "spread": round(book.spread, 6),
        "n_ask_levels": len(asks),
        "depth_at_touch_contracts": round(
            sum(a["size"] for a in asks if a["price"] == best_ask), 4
        ),
        "total_ask_contracts": round(sum(a["size"] for a in asks), 4),
    }
    for band in BAND_CENTS:
        row[f"depth_within_{int(band * 100)}c_contracts"] = round(
            sum(a["size"] for a in asks if a["price"] <= best_ask + band), 4
        )
    # Persist the ASK LADDER itself (best-first, bounded), not just summary statistics.
    # This is what makes the impact coefficient CALIBRATABLE offline: walking a real ladder
    # gives the true cost of filling N contracts with no model parameter at all, which is
    # the only way to check whether `DEFAULT_IMPACT_COEFF` resembles this venue. Bounded to
    # keep the artifact reviewable; the tail beyond this is penny-priced and untradeable.
    row["ask_ladder"] = [
        {"price": a["price"], "size": round(a["size"], 4)} for a in asks[:LADDER_LEVELS]
    ]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", required=True, help="path for the depth-probe JSON artifact")
    ap.add_argument("--limit", type=int, default=60,
                    help="number of open markets to sample (rate-limit budget)")
    ap.add_argument("--tag-id", type=int, default=None,
                    help="optional Gamma tag id to restrict the sample to one category")
    ap.add_argument("--stamp", default="unstamped", help="UTC date string for provenance")
    args = ap.parse_args()
    if args.limit <= 0:
        ap.error("--limit must be positive")

    client = PolymarketClient()
    print(f"[1/2] fetching up to {args.limit} open markets ...", file=sys.stderr)
    markets = client.get_markets(limit=args.limit, tag_id=args.tag_id)
    print(f"      got {len(markets)} markets", file=sys.stderr)

    rows: list[dict] = []
    n_no_book = 0
    print("[2/2] probing order books ...", file=sys.stderr)
    for m in markets:
        for outcome in m.outcomes:
            if not outcome.token_id:
                continue
            try:
                row = probe_market(client, outcome.token_id)
            except Exception as e:
                # One bad market must not kill the probe; the skip is COUNTED, not hidden.
                print(f"      skip {outcome.token_id}: {type(e).__name__}", file=sys.stderr)
                n_no_book += 1
                continue
            if row is None:
                n_no_book += 1
                continue
            row["market_id"] = m.id
            row["gamma_liquidity_usd"] = m.liquidity
            rows.append(row)

    if not rows:
        # Fail LOUD. An empty artifact that later gets read as "depth is zero" would drive
        # the capacity analysis to a confidently wrong conclusion.
        print("FATAL: no market returned a real two-sided book — refusing to write an "
              "empty depth artifact.", file=sys.stderr)
        return 2

    summary = {
        band: _summarize([r[band] for r in rows])
        for band in (
            "depth_at_touch_contracts",
            "depth_within_2c_contracts",
            "depth_within_5c_contracts",
            "total_ask_contracts",
        )
    }
    summary["spread"] = _summarize([r["spread"] for r in rows])

    artifact = {
        "probed_utc": args.stamp,
        "source": "Polymarket Gamma (open markets) + CLOB /book (public, no credentials)",
        "universe": {"limit": args.limit, "tag_id": args.tag_id, "open_markets_only": True},
        "tokens_probed": len(rows),
        "tokens_without_real_two_sided_book": n_no_book,
        "summary": summary,
        "rows": rows,
        "disclosures": [
            "OPEN markets only — depth at a PAST decision instant is unobtainable "
            "(Gamma serves liquidity:null on resolved markets; CLOB /book 404s on a "
            "settled token, both verified live 2026-07-26)",
            "volume-ordered sample = the LIQUID end; depth here OVERSTATES a random market",
            "a single instant — depth varies with time of day, news and time-to-resolution",
            "open markets are a DIFFERENT population from the resolved markets in the OOS "
            "corpora, so this bounds the capacity sweep and does NOT measure those corpora",
            "total_ask_contracts includes penny-priced tail levels and is reported for "
            "context only — it is NOT tradeable capacity",
        ],
    }
    Path(args.out).write_text(json.dumps(artifact, indent=2))
    print(f"      wrote {args.out} ({len(rows)} tokens, {n_no_book} without a real book)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
