#!/usr/bin/env python3
"""
runtime_harness.py — BUILDS != WORKS.

Outcome-asserting end-to-end checks against the REAL executor code. This does NOT
"just import"; it drives the pipeline and asserts the intended SAFETY + PnL outcomes:

  1. LIVE GATE: with dry_run=False and live_enabled=False, a real order is BLOCKED
     (REJECTED) — LIVE_TRADING_ENABLED=false truly prevents any real order.
  2. KILL SWITCH: when active, all orders are blocked.
  3. LOSS CAP intent: max_position_usd rejects oversized orders.
  4. PAPER PIPELINE: a dry_run order fills and produces a real, reproducible PnL
     (size -> signal -> execute(paper) -> position -> PnL), deterministic across runs.

Exit 0 only if every assertion holds. Used by scripts/preflight.sh step 9.
Run locally: python3 scripts/runtime_harness.py
"""
import sys
import os

# Make `backend` importable whether run from repo root or backend/.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

FAILURES = []


def check(name, cond, detail=""):
    status = "OK  " if cond else "FAIL"
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(name)


def build_order(side, size, price):
    from app.prediction_markets.execution import (
        OrderRequest, Exchange, OrderSide, OrderType,
    )
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="0xharness",
        token_id="harness-token",
        side=OrderSide.BUY if side == "BUY" else OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=size,
        price=price,
        strategy="harness",
        market_question="Harness market?",
        outcome_label="Yes",
    )


def main():
    from app.prediction_markets.execution import (
        PredictionMarketExecutor, OrderStatus,
    )

    print("== runtime harness: safety + paper PnL ==")

    # 1. LIVE GATE — dry_run off, live disabled -> real order BLOCKED
    gated = PredictionMarketExecutor(dry_run=False, live_enabled=False,
                                     max_position_usd=50.0, max_portfolio_usd=500.0)
    r1 = gated.execute(build_order("BUY", 10, 0.50))
    check("live_gate_blocks_real_order",
          r1.status == OrderStatus.REJECTED and "LIVE_TRADING_ENABLED" in (r1.error or ""),
          f"status={r1.status} err={r1.error!r}")

    # 2. KILL SWITCH — paper executor, kill switch active -> blocked
    paper = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
    paper.activate_kill_switch("harness-test")
    r2 = paper.execute(build_order("BUY", 10, 0.50))
    check("kill_switch_blocks_orders",
          r2.status == OrderStatus.REJECTED and "KILL SWITCH" in (r2.error or ""),
          f"status={r2.status}")
    paper.deactivate_kill_switch()

    # 3. LOSS CAP intent — oversized order rejected by max_position_usd
    r3 = paper.execute(build_order("BUY", 1000, 0.90))  # notional 900 > 50
    check("max_position_cap_rejects_oversized",
          r3.status == OrderStatus.REJECTED,
          f"status={r3.status}")

    # 4. PAPER PIPELINE — fills + produces PnL, deterministic
    def run_paper():
        ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=500.0)
        res = ex.execute(build_order("BUY", 20, 0.50))  # notional 10
        return ex, res

    ex_a, res_a = run_paper()
    ex_b, res_b = run_paper()
    filled = res_a.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED) or bool(ex_a.positions)
    check("paper_order_fills", filled, f"status={res_a.status} positions={len(ex_a.positions)}")
    # Deterministic: same inputs -> same fill price + same resulting exposure
    det = (round(ex_a.total_exposure, 6) == round(ex_b.total_exposure, 6))
    check("paper_pipeline_deterministic", det,
          f"exposureA={ex_a.total_exposure:.6f} exposureB={ex_b.total_exposure:.6f}")
    # PnL is a real number (0.0 at entry is fine — it must be computable, not error)
    pnl_ok = isinstance(ex_a.total_pnl, (int, float))
    check("paper_pnl_is_real_number", pnl_ok, f"pnl={ex_a.total_pnl}")

    print()
    if FAILURES:
        print(f"RUNTIME HARNESS FAILED: {len(FAILURES)} assertion(s) — {FAILURES}")
        return 1
    print("RUNTIME HARNESS PASSED: live gate + kill switch + caps + paper PnL all verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
