# GROWTH STATUS — LLM-Quant (model / performance)

Re-mapped from the cross-project "growth" shape to a **profit/model** status. Phase
maps: research/backtest → `pre_launch`, paper → `launching`, live → `post_launch`.

**Contract:** the research + alpha method this status is produced under is defined in
[`RESEARCH_PLAYBOOK.md`](RESEARCH_PLAYBOOK.md). Cross-run learning is logged in
[`RESEARCH_MEMORY.md`](RESEARCH_MEMORY.md) — **read it first** each run.

`engine_pct` is pinned to real anchor files; `engine_built == (engine_pct == 100)`.
All metric fields are **real numbers or 0/null — never invented.**

```yaml
GROWTH_STATUS:
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
    weekly_pnl_paper: null          # most recent completed eval window, NET USD (realistic costs); dashboard trends this over snapshots
    weekly_pnl_live: null
    weekly_pnl_target_usd: 2000     # the go-live floor ($2K/wk)
    weeks_validated_above_floor: 0  # consecutive OOS paper weeks >= floor (SUSTAINED — not one lucky week)
    hit_rate: null
    brier_calibration: null         # lower is better; must beat the naive crowd baseline
    sharpe: null
    max_drawdown_pct: null
    total_trades: 0
    live_enabled: false
  # The GO signal — when it is safe + proven enough to risk REAL money. DERIVED from
  # the gates, NEVER hand-set: scripts/preflight.sh FAILS if status=eligible without
  # the real proof, so this can't be faked. Even at 'eligible', the OWNER makes the
  # final call (human-core). 'confidence: high' only when ALL criteria hold.
  go_live:
    status: not_ready               # not_ready | eligible
    confidence: none                # none | building | high
    criteria:                       # every one must be true for status=eligible
      validated_weekly_pnl_ge_floor: false        # OOS paper >= floor, realistic costs
      sustained_track_record: false               # >= several consecutive validated weeks (not one lucky week)
      sufficient_sample_size: false               # enough N for significance / tight CI above floor
      calibration_passes: false                   # Brier/reliability eval holds vs crowd
      backtest_reproduces_deterministically: false # same seed -> same PnL
      adversarial_auditors_passed: false          # >= 3 fresh Opus auditors each FAILED to break the edge
      live_path_safe_by_default: false            # caps + kill switch + LIVE_TRADING_ENABLED default off, proven
      runbook_complete: false                     # docs/growth/LIVE_RUNBOOK.md complete
      quality_ship_critical_all_A: false          # every ship-critical quality dim A/A+
      preflight_full_gate_green: false            # scripts/preflight.sh (full) exits 0
    blocking:                       # honest: what's stopping GO right now
      - "No validated out-of-sample edge yet — build the leakage-free, cost-realistic walk-forward backtest + calibration eval (ROADMAP C1-C3, B2)."
    owner_decision_required: true   # even at 'eligible', the human makes the final real-money GO call
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
```

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
