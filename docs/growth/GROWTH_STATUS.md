# GROWTH STATUS — LLM-Quant (model / performance)

Re-mapped from the cross-project "growth" shape to a **profit/model** status. Phase
maps: research/backtest → `pre_launch`, paper → `launching`, live → `post_launch`.

**Contract:** the research + alpha method this status is produced under is defined in
[`RESEARCH_PLAYBOOK.md`](RESEARCH_PLAYBOOK.md). Cross-run learning is logged in
[`RESEARCH_MEMORY.md`](RESEARCH_MEMORY.md) — **read it first** each run.

`engine_pct` is pinned to real anchor files; `engine_built == (engine_pct == 100)`.
All metric fields are **real numbers or 0/null — never invented.**

<!-- GROWTH_STATUS
project: llm-quant
as_of: 2026-06-27
phase: pre_launch
engine_built: false
engine_pct: 45
venues_connected:
  - polymarket_paper
awaiting_connect:
  - kalshi
  - polymarket_live
metrics:
  weekly_pnl_paper: null
  weekly_pnl_live: null
  hit_rate: null
  brier_calibration: null
  sharpe: null
  max_drawdown_pct: null
  live_enabled: false
experiments: []
learnings:
  - "Bootstrap: prediction-markets engine runs in paper/dry-run; no validated out-of-sample edge yet."
  - "Kill switch exists in execution.py; LIVE_TRADING_ENABLED master gate added (default false)."
next_actions:
  - "Build leakage-free walk-forward OOS backtest with realistic costs (ROADMAP C1-C3)."
  - "Add calibration eval (Brier/reliability) — ROADMAP B2."
  - "Wire hard daily+total loss caps with kill-switch auto-trip (ROADMAP D3/D4)."
  - "Retire stock/crypto data paths; keep asset-agnostic infra (ROADMAP A1)."
owner_blockers:
  - "Confirm venue ToS + jurisdiction eligibility before any live capability."
-->

## engine_pct rationale (pinned to real files)

`engine_pct: 45` reflects what genuinely exists and runs vs. what's required for a
proven, go-live-eligible engine:

**Exists (counts toward %):**
- Polymarket ingestion + websocket feeds — `backend/app/prediction_markets/polymarket_client.py`, `websocket_feeds.py`
- Strategies + edge/EV + Kelly sizing — `strategies.py`, `advanced_strategies.py`, `quant_models.py`, `orchestrator.py`
- Paper simulator — `paper_simulator.py`
- Risk manager + category caps — `risk_manager.py`
- Kill switch — `execution.py`
- Backtest/validation/metrics infra — `backend/app/backtest/*`

**Missing (keeps % < 100):**
- Validated, reproducible, cost-realistic **out-of-sample** weekly-PnL series (no proven edge)
- Calibration eval (B2)
- Hard daily+total loss caps auto-tripping the kill switch (D3/D4)
- Full live path built + paper-validated (D6)
- BUILDS≠WORKS end-to-end runtime harness producing real reproducible PnL (F3)

`engine_built` flips to `true` (and `engine_pct` to `100`) **only** when the DoD in
ROADMAP is fully `[x]` with proof.
