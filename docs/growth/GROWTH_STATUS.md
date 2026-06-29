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
  as_of: 2026-06-29
  phase: pre_launch
  engine_built: false
  engine_pct: 66
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
      blocking_dependency: "RESOLVED IN CODE: polymarket_history_fetcher.py is built + leakage-safe + fixture-tested (uses Polymarket's OWN public Gamma closed=true + CLOB prices-history — no third-party key needed). REMAINING BLOCKER is now ENVIRONMENTAL: outbound HTTPS to gamma-api.polymarket.com / clob.polymarket.com is egress-blocked (403) in the autonomous build env, so the fetcher can't pull real history here. Run it where Polymarket is reachable (PENDING_OPS OA-11) to populate real HistoricalMarket records."
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
    - "A2 resolved-history fetcher BUILT (polymarket_history_fetcher.py): leakage-safe ingest of real resolved markets + a PRE-resolution price snapshot into HistoricalMarket. The settled outcomePrice is NEVER used as the decision price; raises rather than fabricating; timeout/max-pages-bounded; discloses selection/survivorship bias + late-life pinning. 3 Opus auditors CANNOT-BREAK-LEAKAGE. This RESOLVES the named code blocker for OOS validation — but the autonomous env's EGRESS POLICY blocks Polymarket (403), so the real fetch is now a human-core step (OA-11)."
    - "C2/C3 market-impact model BUILT (cost_model.effective_buy_price_with_impact, applied in walk_forward): simplified conservative sqrt-impact, floored at the flat rate, capped at 1.0, deployed==budget to machine epsilon (no double-count); thin books strictly worsen PnL. seed_hash now covers liquidity+impact_coeff. Honestly a non-calibrated toy. 3 Opus auditors CANNOT-BREAK."
    - "G3 audit log DONE (audit_log.py): durable PredictionAuditLog table + best-effort observer in the scan loop records every decision + every would-be order (filled/rejected/gated). Side-effect-honest (event derived from the REAL OrderResult, never a fake fill); execution.py untouched; non-fatal. 3 Opus auditors CANNOT-BREAK."
    - "ENVIRONMENT REALITY: the binding constraint (validated OOS edge on REAL resolved-Polymarket data) is now blocked by the autonomous env's network EGRESS POLICY, not by missing code. The loop built everything buildable offline; the real-data run is OA-11 (owner runs the fetcher where Polymarket is reachable, or widens egress)."
    - "C5 metrics WIRED end-to-end (#56): metrics_aggregator + orchestrator.get_resolved_trades() + GET /prediction-markets/metrics/{weekly,floor-status,calibration} flow weekly PnL/Sharpe/hit-rate/drawdown + calibration from REAL resolved positions. Calibration reports honestly degenerate (never a fake pass) while model_prob==crowd. Backend done; dashboard UI remains."
    - "Live gate DEFENSE-IN-DEPTH (#57): LIVE_TRADING_ENABLED now also enforced fail-closed inside PolymarketExecutor.place_order() (both venue paths), plus side-effect-honest fill parsing (no FILLED without a real match). Opus auditor: SAFE — CANNOT-BREAK; paper provably unaffected."
    - "Real-data REPRODUCTION canary (#58): walk-forward + crowd Brier on the real 54-record fixture proven bit-for-bit reproducible (seed_hash 8dc358439ffb5746, crowd Brier 0.0933, 0 trades), pinned so drift fails loud. Proves determinism on REAL data; claims NO edge (model_prob==crowd)."
    - "B5 forensic audit harness (#59): existing cross-market alphas fire 0 signals on the real sample (no real question text / grouping). Adversarial auditor caught a boilerplate-text phantom-signal bug (98 false signals) — fixed + enforced by a regression test. Surfaced a real strategy weakness (keyword screen too weak), logged for future B-track."
    - "LLM spend cap + timeout ENFORCED (#60): LLM_SPEND_CAP_USD now fails loud before overspend (was config-only); every Gemini call now has a timeout (was none). LLM is not on the scan loop; hardens the /learn path per the standing hard rule."
    - "GATE STRENGTHENED: the blocking preflight now runs the new live-gate/metrics/canary/audit tests (99 -> 176 enforced tests), so these safety/honesty checks are required on every future change."
    - "B5 keyword screen HARDENED (#63): the weak '3+ shared words / 12-word skip set' cross-market relatedness screen (which paired on filler boilerplate AND same-template/different-subject text) is replaced by market_text.is_content_related — >=3 shared CONTENT tokens over a comprehensive stopword set. Rejects every adversarial-audit false positive (Biden/Macron, Bitcoin/Tesla, inflation/unemployment, Apple-Tesla-on-Nasdaq) while genuinely-related pairs still fire; strictly more conservative than before (190->0 phantom pairs). Honest SECONDARY-screen, not an exact classifier. Two fix cycles vs 5 reviewers/auditors."
    - "B2 multiple-comparison correction CODE-ENFORCED (#65): evaluate_calibration(strategies_screened=K) applies Bonferroni effective_alpha=alpha/K — the anti-p-hacking requirement is now a tested feature, not a doc note. Only ever TIGHTENS the gate (verified monotone, 0 False->True flips across thousands of datasets); strategies_screened=1 is bit-identical to prior behavior."
    - "B3/E6 learning-loop ENGINES built (#64): strategy_registry.py (alpha lifecycle state machine with a fail-loud integrity gate — promotion impossible without recorded backtest+OOS+calibration evidence) + per_strategy_metrics.py (pure per-strategy realized-PnL attribution, reconciles to total, no fabricated rows). Pure deterministic engines; NOT yet wired into the live loop (no DoD box). Opus auditors could not bypass the promotion gate or find fabricated attribution."
    - "A5 wall-clock staleness now FIRES (#66): Market carries a fetched_at ingest timestamp (stamped at parse), so the fetch-age staleness gate flags a stale in-memory snapshot in the live scan path (was a no-op). Never enters any backtest seed_hash."
    - "GATE STRENGTHENED again: the blocking preflight now also runs test_calibration/data_quality/market_text/strategy_registry/per_strategy_metrics (176 -> ~290 enforced tests)."
  next_actions:
    - "WIRE the new learning-loop engines into the live loop: per_strategy_metrics against orchestrator.get_resolved_trades() (tag by PredictionPosition.strategy) for real per-strategy attribution; strategy_registry to record real alpha state transitions (persisted). These touch the orchestrator (shared file) — a focused follow-up."
    - "Build a real decision-time alpha (B-track) that forms model_prob != crowd on LESS-PINNED markets — the now-wired metrics + canary + audit harness + the new lifecycle/attribution engines will measure + govern it honestly the moment it exists. This is the binding loop-buildable constraint."
    - "Harden the cross-market keyword screen (B5): the '3+ shared words' heuristic fires on filler words (phantom signals on boilerplate) — require shared CONTENT words / a stop-word list, with tests."
    - "Build the dashboard UI component (frontend, folds with F5) that renders the new /prediction-markets/metrics/* endpoints so paper metrics are visible end-to-end."
    - "OA-11 (human-core): RUN polymarket_history_fetcher in a network-permitted environment (or widen the autonomous env's egress allowlist to Polymarket) so REAL resolved-history flows into walk_forward + the B2 calibration eval. The fetcher is built + leakage-safe; only the egress block stops the OOS run. Until then no floor/DoD box can tick."
    - "Once real data is available: produce a VALIDATED OOS weekly-PnL series + a passing B2 calibration eval on live strategy probabilities; calibrate the market-impact model against real OrderBook depth."
    - "Wire weekly_metrics + calibration into the live paper run + dashboard so metrics flow end-to-end from real resolutions (C5 remainder)."
    - "A4 event/market-universe + persistent resolution tracking (foundation for B2 on real data + the E learning loop); confirm the audit log's DATABASE_URL is durable (OA-10)."
  owner_blockers:
    - "Confirm venue ToS + jurisdiction eligibility before any live capability."
```

## engine_pct rationale (pinned to real files)

`engine_pct: 66` (up from 64) adds this run's learning-loop engine pieces: the alpha
lifecycle registry with a fail-loud integrity gate (B3) + the per-strategy realized-PnL
attribution primitive (E6) — both pure/deterministic, the first concrete E-track
infrastructure — plus the hardened cross-market relatedness screen (B5), the
code-enforced Bonferroni multiple-comparison correction on the calibration gate (B2), and
the now-functional wall-clock staleness gate (A5). These are engine/quality/integrity
pieces; the lifecycle + attribution engines are not yet wired into the live loop, and the
validated edge ITSELF is still absent (the canary honestly shows 0 trades / no edge), so
the bulk of the missing % remains. Prior rationale (engine_pct 64, up from 61): this run's
end-to-end metrics wiring (C5 backend +
API), the venue-layer fail-closed live gate (D5 defense-in-depth), the real-data
reproduction canary (C3/F2), the forensic strategy-audit harness (B5 groundwork), and
enforced LLM timeout + spend cap (G2) — all engine/safety/measurement pieces. The
validated edge ITSELF is still absent (the canary honestly shows 0 trades / no edge), so
the bulk of the missing % remains. Prior rationale (engine_pct 61, up from 58: the
leakage-safe resolved-history fetcher
(A2 ingest — the named code blocker for OOS validation), the market-impact cost model
applied inside the walk-forward backtest (C2/C3 remainder), and the durable decision +
would-be-order audit log (G3) all landed this run. These are engine/safety pieces toward
a validated edge; the validated edge ITSELF is still absent — now gated on an
ENVIRONMENTAL egress block (Polymarket is unreachable from the autonomous env), not on
missing code — and remains the bulk of the missing %):

**Exists (counts toward %):**
- Polymarket ingestion + websocket feeds — `backend/app/prediction_markets/polymarket_client.py`, `websocket_feeds.py`
- Strategies + edge/EV + Kelly sizing — `strategies.py`, `advanced_strategies.py`, `quant_models.py`, `orchestrator.py`
- Paper simulator — `paper_simulator.py`
- Risk manager + category caps — `risk_manager.py`
- Kill switch — `execution.py`
- Backtest/validation/metrics infra — `backend/app/backtest/*`

**Exists from prior runs (counts toward %):**
- Leakage-free, deterministic walk-forward backtest ENGINE (C1/C3 engine) — `prediction_markets/walk_forward.py` (+ `scripts/run_walk_forward.py`)
- Significance-gated calibration eval (B2) — `prediction_markets/calibration.py`
- Data-quality gates at the scan path (A5) — `prediction_markets/data_quality.py` (wired into `orchestrator`)
- Weekly-metrics aggregator (C5) — `prediction_markets/weekly_metrics.py`
- C2 unify: `execution.py` sources its fill rates from `cost_model` (drift fails loud)

**Added this run (counts toward %):**
- Leakage-safe resolved-history fetcher (A2 ingest — the named code blocker for OOS validation) — `prediction_markets/polymarket_history_fetcher.py`
- Market-impact / order-book-depth cost model, applied size-aware in the backtest (C2/C3 remainder) — `cost_model.effective_buy_price_with_impact` + `walk_forward._settle`
- Durable decision + would-be-order audit log (G3 DONE) — `prediction_markets/audit_log.py` (observer in `orchestrator`)

**Missing (keeps % < 100):**
- **Validated, reproducible, cost-realistic out-of-sample weekly-PnL series on REAL data (no proven edge)** — the engine + the ingest fetcher exist; running the fetcher on real history is EGRESS-BLOCKED in the autonomous env (OA-11: run where Polymarket is reachable)
- A *passing* calibration eval on real resolved markets + live strategy probabilities (B2 → unlocks B4)
- Market-impact model CALIBRATED against real OrderBook depth (the current model is a conservative non-calibrated toy)
- Full live path built + paper-validated (D6)
- A4 event/market-universe + persistent resolution tracking; metrics wired end-to-end into the live run/dashboard (C5 remainder)

`engine_built` flips to `true` (and `engine_pct` to `100`) **only** when the DoD in
ROADMAP is fully `[x]` with proof.
