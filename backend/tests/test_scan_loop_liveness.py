"""Regression (D / §6 live-safety — event-loop liveness): ``scan_and_execute`` must run
the blocking scanner OFF the event loop and serialize concurrent cycles.

The scanner is synchronous and makes many rate-limited Gamma/CLOB HTTP calls (each
timeout-bounded, but sequential + rate-limited via blocking ``time.sleep``). Running it
directly on the async event loop starves EVERYTHING else on that loop for the whole
scan — the mark-to-market loop, the snapshot loop, and every concurrent HTTP handler,
INCLUDING ``POST /prediction-markets/kill-switch/activate``. That is the §6 failure:
"a graceful try/catch is useless if the runtime hangs first." The fix offloads the scan
to a worker thread (``asyncio.to_thread``), mirroring the offload the ``/scan`` route
already uses.

Offloading introduces a yield point into a method that previously ran atomically on the
loop, so a manual ``/bot/scan-now`` could now overlap the background ``_scan_loop``. A
per-orchestrator ``asyncio.Lock`` restores the "one cycle at a time" invariant so two
cycles never interleave their sizing/execution against shared executor state.

Both tests trip on the pre-fix code (synchronous scan, no lock) and pass on the fix.
"""

from __future__ import annotations

import asyncio
import threading
import time

from app.prediction_markets.orchestrator import PredictionMarketOrchestrator


def test_scan_offloads_the_blocking_scanner_off_the_event_loop():
    """While the scanner is mid-scan, a coroutine scheduled on the SAME loop must still
    make progress. We prove it cross-thread: the scanner (which runs in a worker thread
    post-fix) waits on a ``threading.Event`` that a loop coroutine sets. Post-fix the loop
    is live, so the event gets set and the scanner observes it. Pre-fix the scanner blocks
    the loop, the setter never runs, and the wait times out → ``scan_saw_loop_progress``
    stays False.
    """
    loop_progressed = threading.Event()
    observed = {"loop_ran_during_scan": False}

    class _CoopScanner:
        strategies: list = []

        def scan(self, market_limit: int = 200):
            # Wait (in whatever thread this runs on) for the loop coroutine to signal.
            # Post-fix: this runs in a worker thread, the loop is free → set within ~50ms.
            # Pre-fix: this runs ON the loop, blocking it → the setter never runs → timeout.
            observed["loop_ran_during_scan"] = loop_progressed.wait(timeout=3.0)
            return []

    orch = PredictionMarketOrchestrator(scanner=_CoopScanner())

    async def _loop_worker():
        # Yield first so the scan starts, then signal from the event loop.
        await asyncio.sleep(0.05)
        loop_progressed.set()

    async def _run():
        await asyncio.gather(orch.scan_and_execute(), _loop_worker())

    asyncio.run(_run())

    assert observed["loop_ran_during_scan"] is True, (
        "the event loop was starved during the scan — scanner is not offloaded"
    )


def test_concurrent_cycles_do_not_interleave():
    """The ``_scan_lock`` must serialize concurrent cycles even though the scan now yields
    the loop. We measure the peak number of scans running at once across two concurrent
    ``scan_and_execute`` calls: it must be exactly 1. Without the lock (but with the
    thread offload) both scans would run in worker threads simultaneously → peak 2.
    """
    state = {"current": 0, "peak": 0}
    guard = threading.Lock()

    class _CountingScanner:
        strategies: list = []

        def scan(self, market_limit: int = 200):
            with guard:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.15)
            with guard:
                state["current"] -= 1
            return []

    orch = PredictionMarketOrchestrator(scanner=_CountingScanner())

    async def _run():
        await asyncio.gather(orch.scan_and_execute(), orch.scan_and_execute())

    asyncio.run(_run())

    assert state["peak"] == 1, f"cycles overlapped (peak={state['peak']}) — lock not holding"
    # Both cycles still ran (serialized, not dropped).
    assert orch.total_scans == 2
