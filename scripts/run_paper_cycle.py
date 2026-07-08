#!/usr/bin/env python3
"""run_paper_cycle.py — one FORWARD paper-trading cycle against REAL live markets.

This is "live trading validation with PAPER money": the bot scans real open markets, makes
real decisions, records each trade AS IF filled (cost-aware paper fill — it NEVER touches a
venue), and books realized PnL when markets resolve. It is the honest forward test of edge,
distinct from the resolved-market backtest.

SAFETY (belt-and-suspenders, on top of the executor's own gate):
  * REFUSES to run if LIVE_TRADING_ENABLED is true — a paper cycle must never run in a
    live-configured process. Real-money order placement is HUMAN-CORE and never automated.
  * Uses the dry-run/paper executor (init_orchestrator → get_executor(dry_run=True)); the
    executor's LIVE gate blocks any real order regardless.

REQUIREMENTS: network egress to Polymarket's PUBLIC Gamma/CLOB APIs (no credentials — public
read-only data). Run on a network-permitted host (the deployed backend, or a GitHub Actions
runner). Persistence goes to the configured DATABASE_URL (Neon for a durable forward record;
falls back to local SQLite, which is ephemeral on a CI runner — see docs/ci/PROPOSED_CI.md).

Usage: python scripts/run_paper_cycle.py [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _settings():
    try:
        from backend.app.config import get_settings
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.config import get_settings  # type: ignore
    return get_settings()


def assert_paper_safe(settings) -> None:
    """HARD SAFETY: a paper cycle must never run with the live money path enabled.
    Real order placement is human-core, never automated. Raises SystemExit if violated."""
    if getattr(settings, "live_trading_enabled", False):
        raise SystemExit(
            "REFUSING to run a paper cycle: LIVE_TRADING_ENABLED is true. Paper validation must "
            "run with the live path OFF (real order placement is human-core, never automated)."
        )


async def _run() -> dict:
    settings = _settings()
    assert_paper_safe(settings)

    # Only ImportError falls back to the backend/-cwd layout — a REAL error (e.g. a bad
    # DATABASE_URL raising at db.database import time) must propagate with its true message,
    # not be masked into a confusing ModuleNotFoundError.
    try:
        from backend.app.db.database import init_db
        from backend.app.prediction_markets.orchestrator import init_orchestrator, get_orchestrator
    except ImportError:
        from app.db.database import init_db  # type: ignore
        from app.prediction_markets.orchestrator import init_orchestrator, get_orchestrator  # type: ignore

    # Ensure the durable tables exist so the forward record actually persists (audit log,
    # executor safety-state, strategy registry) — the same create_all the backend runs at boot.
    init_db()

    orch = init_orchestrator()  # real default scanner + dry-run (paper) executor
    if orch is None or orch.scanner is None:
        raise SystemExit(
            "No scanner configured — cannot reach the market universe. On the cloud loop this is "
            "the Polymarket egress block (OA-11/OA-13); run where Gamma/CLOB are reachable."
        )

    # Second safety assertion: the executor must be in dry-run/paper mode.
    if getattr(orch.executor, "dry_run", None) is False:
        raise SystemExit("Executor is not in dry_run mode — refusing to place real orders.")

    # 1) FORWARD: scan real open markets, decide, paper-execute (cost-aware, no venue call).
    scan = await orch.scan_and_execute()
    # 2) SETTLE: refresh live prices + book realized PnL on resolved paper positions. Mirror
    #    the orchestrator's own _mtm_loop — the resolution logic lives on mtm_engine, not orch.
    #    `check_resolutions()` returns the COUNT of positions durably settled this cycle (0 when
    #    none), so the forward-paper telemetry can distinguish "0 booked" (a real, healthy 0)
    #    from "settlement did not run" (None: no mtm engine) or an error (a string). Before the
    #    Run-16 fix the method returned None implicitly, so this field was permanently null.
    settled = None
    mtm = getattr(orch, "mtm_engine", None)
    if mtm is not None:
        try:
            mtm.update_prices()
            settled = mtm.check_resolutions()
        except Exception as e:  # settlement is best-effort; a scan already happened
            settled = f"resolution check failed (non-fatal): {type(e).__name__}: {e}"

    return {
        "mode": "paper",
        "live_trading_enabled": bool(getattr(settings, "live_trading_enabled", False)),
        "dry_run": bool(getattr(orch.executor, "dry_run", True)),
        "scan": scan,
        "resolutions": settled,
        "total_scans": getattr(orch, "total_scans", None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()
    try:
        result = asyncio.run(_run())
    except SystemExit as e:
        print(f"run_paper_cycle: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        s = result.get("scan") or {}
        print("PAPER CYCLE (real markets, paper fills — no venue touched)")
        print(f"  live_trading_enabled : {result['live_trading_enabled']}  dry_run: {result['dry_run']}")
        print(f"  opportunities        : {s.get('opportunities', '?')}")
        print(f"  executed (paper)     : {s.get('executed', '?')}")
        print(f"  resolutions booked   : {result.get('resolutions')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
