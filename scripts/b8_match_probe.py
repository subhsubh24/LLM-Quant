#!/usr/bin/env python3
"""b8_match_probe.py — reproducible cross-venue MATCH feasibility probe (ROADMAP B8).

Counts CANDIDATE co-listed Polymarket<->Kalshi crypto pairs found by the EXISTING
``cross_venue_matcher`` after the structured-strike parser (PR #400). This is a LIVE
network probe against Kalshi + Polymarket, so the exact counts vary with the live order
book — it is a documented, re-runnable METHOD + a point-in-time measurement, NOT a
bit-reproducible artifact. It counts pairs only (no PnL, no selection) so it cannot be
p-hacked into an edge.

HONESTY: a "candidate pair" is a same-STRIKE, same-window, same-content match. It is NOT
semantically classified — the touch/barrier/terminal resolution-mechanic classifier
(ROADMAP B8 step iii) is still outstanding and MUST gate any pair before it is treated as
the same event for an OOS/edge claim. A candidate count is a feasibility signal, never an
edge.

Usage:  python scripts/b8_match_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.prediction_markets.cross_venue_matcher import (  # noqa: E402
    extract_threshold,
    extract_threshold_from_structured_strike,
    find_cross_venue_matches,
)
from app.prediction_markets.kalshi_client import KalshiClient  # noqa: E402
from app.prediction_markets.polymarket_client import PolymarketClient  # noqa: E402

# Kalshi crypto series carrying structured numeric strikes (daily terminal, year barrier).
CRYPTO_SERIES = [
    "KXBTCD", "KXBTC", "KXETHD", "KXETH",
    "KXBTCMAXY", "KXETHMAXY", "KXBTCMINY", "KXETHMINY",
]


def main() -> int:
    kc = KalshiClient()
    kalshi = []
    for s in CRYPTO_SERIES:
        try:
            kalshi += kc.get_markets(limit=200, status="open", series_ticker=s)
        except Exception as e:  # noqa: BLE001 — a probe: log and continue
            print(f"  [warn] kalshi {s}: {type(e).__name__}: {e}")
    k_trad = [m for m in kalshi if m.active]
    k_title = [m for m in k_trad if extract_threshold(m.question) is not None]
    k_struct_only = [
        m for m in k_trad
        if extract_threshold(m.question) is None
        and extract_threshold_from_structured_strike(m) is not None
    ]
    print(
        f"KALSHI crypto: tradeable={len(k_trad)} | title-strike={len(k_title)} | "
        f"STRUCTURED-ONLY(new via parser)={len(k_struct_only)}"
    )

    pc = PolymarketClient()
    poly = []
    for q in ("bitcoin", "ethereum"):
        try:
            poly += pc.search_markets(q, limit=100)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] polymarket search {q!r}: {type(e).__name__}: {e}")
    try:
        poly += pc.get_markets(limit=300)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] polymarket get_markets: {type(e).__name__}: {e}")
    seen, polyu = set(), []
    for m in poly:
        if m.id not in seen:
            seen.add(m.id)
            polyu.append(m)
    p_trad = [m for m in polyu if getattr(m, "active", False) and getattr(m, "is_binary", False)]
    print(f"POLYMARKET: tradeable_binary={len(p_trad)}")

    matches = find_cross_venue_matches(p_trad, k_trad)
    print(f"\n=== CANDIDATE cross-venue pairs (UNCLASSIFIED — step iii pending): {len(matches)} ===")
    for mt in matches[:10]:
        print(
            f"  thr={mt.threshold} coh={mt.coherence_score:.2f} | "
            f"A={mt.question_a[:44]!r} B={mt.question_b[:44]!r}"
        )
    print(
        "\nNOTE: candidates are same-strike/window/content only. Touch/barrier/terminal "
        "mechanic classification (B8 step iii) still gates any OOS/edge use."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
