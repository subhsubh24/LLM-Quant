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
  as_of: 2026-06-28
  phase: pre_launch
  engine_built: false
  engine_pct: 58
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
  experiments:
    - id: EXP-001
      name: "Real-Data Pipeline + NO Position Scanner OOS Validation"
      status: proposed
      proposed_date: 2026-06-28
      edge_source: "crowd-miscalibration (in-scope per PLAYBOOK)"
      hypothesis: >
        The NO Position Scanner generates positive net EV — Brier improvement vs
        crowd baseline AND positive net PnL after costs — on resolved Polymarket
        binary markets where YES > 90c, on >= 100 resolved markets across >= 3
        categories. Category reversal base rates (politics 2%, economics 3%,
        crypto 8%, sports 5%) are empirically calibrated, not hardcoded fiction.
      min_sample_n: 100
      oos_plan: >
        Chronological 60/40 split: earliest 60% to empirically calibrate reversal
        base rates per category; most recent 40% as true held-out OOS. Significance
        gate: paired bootstrap CI on per-market Brier difference must exclude 0
        (calibration.py B2 gate). Net PnL must be positive after cost_model costs.
      cost_assumptions: "2% fee + 0.5% slippage (cost_model.py); no liquidity model — conservative capacity"
      significance_threshold: "95% CI excluding 0 on paired-bootstrap Brier improvement; Bonferroni correction if testing multiple categories"
      how_it_could_be_wrong:
        - "Reversal rates empirically near-zero -> strategy dead on arrival"
        - "Near-certainty NO books illiquid -> real slippage erases edge"
        - "Survivorship bias in third-party archive excludes contested/re-resolved markets"
        - "N per category < 50 even with 100+ total -> no category-level significance claims"
        - "Market efficiency increasing (43% spread compression) -> historical edge gone in recent months"
      blocking_dependency: "Build polymarket_history_fetcher.py from PMData (pmdata.dev) or PolyHistorical (polyhistorical.com) to populate HistoricalMarket records"
      factory_next_action: >
        Build polymarket_history_fetcher.py; pull >= 200 resolved markets from
        PMData or PolyHistorical APIs; feed into walk_forward.py; run B2
        calibration eval; report OOS Brier + PnL with bootstrap CI. Only then
        can EXP-001 be declared passing or retired.
  learnings:
    - "Bootstrap: prediction-markets engine runs in paper/dry-run; no validated out-of-sample edge yet."
    - "Kill switch exists in execution.py; LIVE_TRADING_ENABLED master gate added (default false)."
    - "A1 complete: stock/crypto engine + data/AI routes + ML stack + stock frontend retired; asset-agnostic infra kept; ~2GB+ leaner deploy (torch/xgboost/lightgbm dropped)."
    - "D3/D4 done: hard daily/total loss caps enforced at the execution gate + kill-switch auto-trip on breach (incl. the resolution loss path). Verified by harness + 2 fresh auditors."
    - "C2 cost-aware Kelly: sizing now uses cost-NET edge — prior gross-edge sizing systematically over-bet AND over-traded (took trades with negative net edge after fees+slippage). Honest costs LOWER turnover/sizing — correctly."
    - "C1/C3 walk-forward ENGINE built (prediction_markets/walk_forward.py): leakage-free by construction (decision sees no outcome; training only resolves pre-window), event-driven capital accounting (no over-deployment), cost_model costs, deterministic seed_hash. Proven on synthetic data to recover a known edge + report ~0 on no-edge. NOT a validated edge — no real resolved-market data yet, so no floor/DoD box ticked."
    - "B2 calibration eval built (calibration.py): Brier+reliability+ECE with a SIGNIFICANCE gate (paired bootstrap CI must exclude 0). A raw Brier point comparison passed ~21% of pure-noise strategies at N=30 (adversarial-audit finding); the bootstrap gate collapses that to <=1.2%. Honest: measures calibration-vs-crowd, not tradeable edge."
    - "A5 data-quality gates wired into the scan loop (data_quality.py): completeness/price-sanity catch None/NaN/inf/out-of-range/sum-violations; staleness fires via end_date expiry. Bad markets skipped before sizing; valid markets never skipped."
    - "C5 weekly-metrics aggregator (weekly_metrics.py): pure deterministic weekly PnL/Sharpe/hit-rate/max-drawdown from real realized trades. C2 unify done: execution.py sources its fill rates from cost_model (drift fails loud)."
  next_actions:
    - "Feed REAL resolved-Polymarket history into the walk_forward engine to produce a VALIDATED OOS weekly-PnL series + run the B2 calibration eval on live strategy probabilities (the binding constraint — until then no floor/DoD box can tick)."
    - "Apply the cost_model + a liquidity/order-book-depth + market-impact model inside the walk-forward backtest (C2/C3 remainder)."
    - "Wire weekly_metrics + calibration into the live paper run + dashboard so metrics flow end-to-end from real resolutions (C5)."
    - "A4 event/market-universe + persistent resolution tracking (foundation for B2 on real data + the E learning loop); G3 persistent audit log."
  owner_blockers:
    - "Confirm venue ToS + jurisdiction eligibility before any live capability."
```

## engine_pct rationale (pinned to real files)

`engine_pct: 58` reflects what genuinely exists and runs vs. what's required for a
proven, go-live-eligible engine (up from 52: the leakage-free walk-forward backtest
engine (C1/C3 engine), the significance-gated calibration eval (B2), data-quality gates
at the scan path (A5), the weekly-metrics aggregator (C5), and the cost-rate
unification (C2 unify) all landed this run — engine pieces toward a validated edge,
which itself is still absent and remains the bulk of the missing %):

**Exists (counts toward %):**
- Polymarket ingestion + websocket feeds — `backend/app/prediction_markets/polymarket_client.py`, `websocket_feeds.py`
- Strategies + edge/EV + Kelly sizing — `strategies.py`, `advanced_strategies.py`, `quant_models.py`, `orchestrator.py`
- Paper simulator — `paper_simulator.py`
- Risk manager + category caps — `risk_manager.py`
- Kill switch — `execution.py`
- Backtest/validation/metrics infra — `backend/app/backtest/*`

**Added this run (counts toward %):**
- Leakage-free, deterministic walk-forward backtest ENGINE (C1/C3 engine) — `prediction_markets/walk_forward.py` (+ `scripts/run_walk_forward.py`)
- Significance-gated calibration eval (B2) — `prediction_markets/calibration.py`
- Data-quality gates at the scan path (A5) — `prediction_markets/data_quality.py` (wired into `orchestrator`)
- Weekly-metrics aggregator (C5) — `prediction_markets/weekly_metrics.py`
- C2 unify: `execution.py` sources its fill rates from `cost_model` (drift fails loud)

**Missing (keeps % < 100):**
- **Validated, reproducible, cost-realistic out-of-sample weekly-PnL series on REAL data (no proven edge)** — the engine exists; it needs real resolved-Polymarket history
- A *passing* calibration eval on real resolved markets + live strategy probabilities (B2 → unlocks B4)
- Liquidity/market-impact cost model + costs applied inside the walk-forward backtest (C2/C3 remainder)
- Full live path built + paper-validated (D6); persistent audit log (G3)
- A4 event/market-universe + persistent resolution tracking; metrics wired end-to-end into the live run/dashboard (C5 remainder)

`engine_built` flips to `true` (and `engine_pct` to `100`) **only** when the DoD in
ROADMAP is fully `[x]` with proof.
