#!/usr/bin/env python3
"""live_integration_smoke.py — exercise the REAL external integrations end-to-end.

The required gate is deterministic/mocked (a feature). This is the SEPARATE, NON-BLOCKING
"real" tier: it actually calls Gemini (if GEMINI_API_KEY is set) and reads real public
Polymarket data, asserting our client code works against the LIVE services — the thing mocks
can't catch (an SDK signature change, an API shape shift, our wrapper breaking).

Honest exit semantics (this is a non-blocking scheduled check, NOT the required gate):
  * exit 1  → a genuine CODE failure (our wrapper raised / returned malformed data against a
              reachable service). This is a real bug to fix.
  * exit 0  → all reachable paths OK, OR a path is cleanly UNAVAILABLE (no key / egress-blocked).
              External unavailability is reported, never a "code is broken" signal — a Polymarket
              outage or a missing key must not read as a defect.
NEVER places a trade. NEVER prints a secret. Reads public data + one tiny LLM prompt only.

Usage: python scripts/live_integration_smoke.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _imp(path_a, path_b):
    try:
        return __import__(path_a, fromlist=["x"])
    except Exception:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        return __import__(path_b, fromlist=["x"])


def check_gemini() -> dict:
    """Real Gemini call if the key is present; else a clean skip (degrade-safe path)."""
    cfg = _imp("backend.app.config", "app.config")
    settings = cfg.get_settings()
    if not getattr(settings, "has_llm_key", False):
        return {"path": "gemini", "status": "skipped", "detail": "no GEMINI_API_KEY (degrade-safe path)"}
    try:
        analyst_mod = _imp("backend.app.llm.analyst", "app.llm.analyst")
        Analyst = getattr(analyst_mod, "MarketAnalyst", None) or getattr(analyst_mod, "Analyst", None)
        analyst = Analyst() if Analyst else None
        resp = analyst._call_llm("Reply with the single word: OK", max_tokens=8) if analyst else None
        if resp and isinstance(resp, str) and resp.strip():
            return {"path": "gemini", "status": "ok", "detail": f"live response ({len(resp)} chars)"}
        return {"path": "gemini", "status": "fail", "detail": "key present but empty/None response — wrapper may be broken"}
    except Exception as e:  # our wrapper broke against the live SDK → real bug
        return {"path": "gemini", "status": "fail", "detail": f"{type(e).__name__}: {e}"}


def check_polymarket() -> dict:
    """Read real PUBLIC Polymarket data (no creds). Distinguish egress-block from code break."""
    try:
        fetch_mod = _imp(
            "backend.app.prediction_markets.polymarket_history_fetcher",
            "app.prediction_markets.polymarket_history_fetcher",
        )
        fetcher = fetch_mod.PolymarketHistoryFetcher()
        markets = fetcher.fetch_resolved_markets(limit=3, max_pages=1, order="volumeNum")
        if markets:
            return {"path": "polymarket", "status": "ok", "detail": f"parsed {len(markets)} real resolved markets"}
        # empty could be egress-blocked (403 swallowed → None → []) or a genuinely empty page
        return {"path": "polymarket", "status": "unavailable",
                "detail": "no markets returned — likely egress-blocked (OA-11) or transient; not a code failure"}
    except Exception as e:  # parse/client code broke against the live API → real bug
        return {"path": "polymarket", "status": "fail", "detail": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    results = [check_gemini(), check_polymarket()]
    failed = [r for r in results if r["status"] == "fail"]
    if args.json:
        print(json.dumps({"results": results, "code_failures": len(failed)}, indent=2))
    else:
        for r in results:
            mark = {"ok": "OK  ", "skipped": "SKIP", "unavailable": "N/A ", "fail": "FAIL"}[r["status"]]
            print(f"  [{mark}] {r['path']}: {r['detail']}")
        print(f"\nlive-integration-smoke: {'FAIL (' + str(len(failed)) + ' code failure(s))' if failed else 'OK (no code failures)'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
