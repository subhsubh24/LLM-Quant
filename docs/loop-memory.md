# LOOP MEMORY — LLM-Quant

Cross-run lessons for the autonomous factory loop. Append; read before each run.

## 2026-06-27 — Bootstrap

- **What this repo is:** a *personal* prediction-markets profit bot, not a product.
  Re-mapped from the cross-project "factory" process. Source of truth = `ROADMAP.md`
  + the profit case in `docs/BUSINESS_CASE.md`.
- **Default branch:** `claude/llm-stock-trading-app-fXupf` (origin/HEAD). PR against it.
- **Honest baseline:** the prediction-markets engine runs in paper/dry-run, but there
  is **no validated out-of-sample edge yet** — `floor_met: false`, metrics `0/null`.
  Do **not** tick DoD boxes without reproduced, cost-realistic OOS proof.
- **Already present (don't rebuild):** Polymarket client + websocket feeds, strategies
  + Kelly sizing + orchestrator, paper simulator, risk manager with category caps,
  **kill switch** in `execution.py`, backtest/validation infra under
  `backend/app/backtest/`.
- **Added this run:** `LIVE_TRADING_ENABLED` master gate (default false) wired so no
  real order is possible unless the owner flips it AND `dry_run` is off; the full
  apparatus (VISION/ROADMAP/preflight/runbook/YAML blocks/research docs).
- **Lowest incomplete ROADMAP item to advance next:** A1 (retire stock/crypto data
  paths, keep asset-agnostic infra) — **do this carefully**; the prediction-markets
  module is the keeper, the stock/crypto code lives under `backend/app/trading/`,
  `backend/app/strategies/`, `backend/app/data/` (crypto/alpaca/binance). Don't break
  the asset-agnostic backtest/metrics/risk infra.
- **Gate tooling reality:** `pytest` available; **no ruff/mypy installed** — preflight
  degrades gracefully (skips with a warning, still runs pytest + import smoke).
- **Real-money brake:** never trade real money, never fund, never flip
  `LIVE_TRADING_ENABLED`, never raise a cap. Those are HUMAN-CORE
  (`PENDING_OPS.md` / `LIVE_RUNBOOK.md`).
- **Doc sprawl:** 28 root `.md` files consolidated — legacy audit/plan files moved to
  `docs/legacy/` (history preserved); the coherent source of truth is
  VISION/ROADMAP/BUSINESS_CASE/GROWTH_STATUS/PENDING_OPS + `docs/growth/`.
