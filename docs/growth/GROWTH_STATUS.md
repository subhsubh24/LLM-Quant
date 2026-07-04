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
  as_of: 2026-07-04
  phase: pre_launch
  engine_built: false
  engine_pct: 74   # unchanged (2026-07-04 2nd run, #215/#216/#217): a SAFETY + coverage + artifact run — #215 closed a REACHABLE loss-cap bypass (a bare SELL fabricated a `side="short"` position via the unconditional paper fill; a BUY 'to close' scaled it up recording $0 PnL → the D3/D4 kill switch never saw the loss; reachable via CrossMarketArbitrage's executable SELL in the default scanner); #216 gated the LIVE Monte-Carlo pricing tests (previously ungated); #217 removed the last stock-era render.yaml residue (FRED_API_KEY). Safety/correctness/coverage/artifact convergence, NOT new completeness or a validated edge, so engine_pct does not move. 2 Sonnet/PR + a fresh Opus live-safety auditor SAFE on #215 (2 non-blocking residual caveats: the 1e-9 boundary + legacy short-row remediation — filed for a dedicated follow-up). Prior (2026-07-03 2nd run, #187/#188/#189/#190): a mature-engine HARDENING sweep — WS price_change staleness-honesty guard (#187) + §12 path-param bounds (#188) + F7 api/main.py import hygiene (#189) + §10 dead-code removal (#190). Correctness/security/hygiene/tech-debt convergence, NOT new completeness or a validated edge, so engine_pct does not move. (DEFERRED with a recorded note: the loss-cap-net-of-fees safety fix — verified real at both call sites, awaiting a dedicated run + fresh Opus live-safety audit.) Prior (2026-07-03, #179/#180/#182): the B8 cross-venue coherence matcher + backtest (a CANDIDATE edge, gated off, not validated) + F10 regime-slice wiring into the real-OOS lane + a blocking-gate coverage registration. New alpha-candidate INFRA + anti-overfitting integrity + test coverage — not a validated edge, so engine_pct does not move. Prior (2026-07-01, #116/#117): an INTEGRITY fix (removed a fabricated whale seed + gated two UNVALIDATED strategies out of the default scan behind ENABLE_UNVALIDATED_STRATEGIES, default off) + an A1 stock-era DEAD-CODE removal (legacy db.models stack + yfinance strategy_tester — also kills the stock_prices dual-registration fragility). Both are correctness/honesty/tech-debt work, not new completeness, so engine_pct does not move. No new edge. Prior context (#104): settlement side-effect-integrity fix; (#99-#102): ingest-honesty + §12 hardening.
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
    - id: EXP-002
      name: "Horizon-Effect Calibration Bias (7-day decision_lead corpus)"
      status: proposed
      proposed_date: 2026-06-29
      edge_source: "crowd-miscalibration + resolution-timing edge (in-scope per PLAYBOOK)"
      hypothesis: >
        Binary Polymarket markets with YES probability 65-90% at 7 days to resolution
        are systematically underpriced vs their empirical resolution rate — the crowd
        under-assigns probability to favorites at early horizons (calibration slope > 1.0,
        per Le 2026 on Kalshi; only ~3% of traders drive price discovery in illiquid
        early-life markets). A CalibrationBucketStrategy that replaces crowd_prob with
        per-bucket empirical resolution rates (fitted from the oldest 60% of a 7-day-lead
        corpus) produces a positive net Brier improvement on the OOS 40%, surviving
        realistic costs (2% fee + 0.5% slippage).
      min_sample_n: 100
      oos_plan: >
        Run fetch_polymarket_history.py with --decision-lead-days 7 (the script default —
        NO code changes needed). Target >= 200 resolved markets. Chronological 60/40 split:
        oldest 60% to fit per-bucket empirical resolution rates; newest 40% as held-out OOS.
        Significance gate: paired bootstrap CI on per-market Brier difference excludes 0
        (B2 calibration.py, Bonferroni if testing multiple buckets). Net PnL positive after
        cost_model costs on the OOS set. Min 30 records per bucket for any bucket-level claim.
      cost_assumptions: >
        2% fee + 0.5% slippage (cost_model.py). At 7-day decision_lead, spreads are wider
        than near-resolution — assume 1-2% additional effective slippage for conservative
        capacity. Target only markets with volume >= $2K at decision time (reduce impact).
      significance_threshold: "95% CI excluding 0 on paired-bootstrap Brier improvement (B2 gate); Bonferroni correction across tested price buckets"
      how_it_could_be_wrong:
        - "Calibration slope effect is Kalshi-specific; Polymarket may already price this in via institutional arbs"
        - "At 7 days, even high-volume markets are mostly pinned on large events — same 70% pinning problem as the 2-day corpus"
        - "Slippage at 7 days materially higher than the 0.5% model — illiquid early-life markets"
        - "Per-bucket fitting overfits with < 50 records per bucket — OOS rates revert to crowd"
        - "The Le 2026 slope=1.32 is at > 1 month, not at 7 days — the slope may be near 1.0 at a 7-day horizon"
        - "Research Run 11 (2026-07-01): a secondary comparative analysis (Calibration City 671K markets + brier.fyi 971 cross-linked markets) reports Polymarket calibration BEATING Kalshi's at close and time-averaged -- the opposite direction needed for a Kalshi-anchored (Le 2026) effect to transfer 1:1 to Polymarket. Non-peer-reviewed and unreproduced by us, but it independently reinforces this pre-mortem item rather than contradicting it -- raises the bar before trusting a Kalshi-shaped finding on Polymarket data."
      blocking_dependency: >
        NO CODE CHANGES NEEDED. Infrastructure is complete: fetch_polymarket_history.py
        already accepts --decision-lead-days (default 7.0). ONLY BLOCKER: re-run OA-11
        with 7-day lead from a network-permitted environment.
        Command: python3 scripts/fetch_polymarket_history.py --decision-lead-days 7
        --limit 500 --max-pages 3 --min-volume 1000 --merge
        --out data/polymarket_history_7d.json
      factory_next_action: >
        (1) OWNER: re-run OA-11 with 7-day decision_lead (command above) to produce a
        >= 200 record 7-day-lead corpus. (2) FACTORY: build CalibrationBucketStrategy
        (in strategies.py): accepts a pre-fitted bucket_rates dict {(lo, hi): empirical_rate};
        returns model_prob = bucket_rate when crowd_prob falls in a calibrated bucket;
        ABSTAINS (no signal) if bucket has < min_bucket_n training samples (never hardcode
        fiction); raises if no calibration data provided at all. (3) Run 60/40 OOS test,
        B2 gate, report Brier improvement + net PnL with bootstrap CI.
    - id: EXP-003
      name: "Domain-Calibrated Political Strategy (Partisan Underconfidence)"
      status: proposed
      proposed_date: 2026-06-30
      edge_source: "crowd-miscalibration (domain-specific; in-scope per PLAYBOOK)"
      hypothesis: >
        Binary Polymarket markets categorised as "politics" or "elections" are
        systematically MORE underconfident than other categories at ALL decision horizons
        — crowd prices chronically compressed toward 50% via bilateral partisan
        cancellation (Le 2026: dominant calibration component, explains a large fraction
        of the 87.3% calibration variance across 292M trades on Kalshi + Polymarket).
        A CalibrationBucketStrategy fitted EXCLUSIVELY on political-category resolved
        markets produces a positive net Brier improvement on the OOS 40%, with the
        miscalibration robust across decision horizons (unlike the general horizon effect,
        which primarily manifests at >30 days).
      min_sample_n: 100
      oos_plan: >
        (A) PREFERRED — Polymarket-v1 HuggingFace (OA-16): extract daily_aligned Parquet,
        filter to "politics"/"elections" category, reconstruct pre-resolution price
        snapshots at desired decision_lead. (B) ALTERNATIVE — OA-11 with filter:
        python3 scripts/fetch_polymarket_history.py --decision-lead-days 7 --limit 500
        --max-pages 3 --categories "politics,elections" --merge
        --out data/polymarket_history_politics.json
        Chronological 60/40 split. CalibrationBucketStrategy (already built) fitted on
        oldest 60%. B2 significance gate: bootstrap CI excludes 0. Bonferroni correction
        across tested price buckets.
      cost_assumptions: >
        2% fee + 0.5% slippage (cost_model.py). Political markets at 60-90% YES have
        moderate book depth; conservative 1% additional effective slippage assumed.
        Focus on markets with volume >= $2K at decision time to reduce impact.
      significance_threshold: >
        95% CI excluding 0 on paired-bootstrap Brier improvement (B2 gate, strategies_screened=3
        for Bonferroni across EXP-001/EXP-002/EXP-003). Net PnL positive after costs on OOS set.
        Min 30 records per price bucket for any bucket-level claim.
      how_it_could_be_wrong:
        - "Polymarket political user base (international/crypto-native) may not show the same partisan bilateral cancellation as Kalshi's US-regulated base — the Le 2026 effect may be Kalshi-specific"
        - "Only ~10-30 active political Polymarket markets per month — accumulating 100+ resolved markets takes 4-6 months; N is slow"
        - "Political miscalibration may concentrate at >30 days (peak partisan uncertainty) and be near-zero at 7-day horizon (late pinning)"
        - "With <100 political markets, per-bucket N < 30 threshold triggers abstain — strategy produces zero signals"
        - "Le 2026 covers the 2020-2024 US election super-cycle; post-cycle calibration pattern may differ in non-election-year markets"
        - "Research Run 11 (2026-07-01): same cross-platform calibration nuance as EXP-002 -- a secondary source (Calibration City/brier.fyi) reports Polymarket generally BETTER calibrated than Kalshi, which would work against (not for) a Kalshi-anchored political-underconfidence effect transferring cleanly to Polymarket. Unreproduced by us; logged as a reason for caution, not a refutation."
      blocking_dependency: >
        MECHANISM: CalibrationBucketStrategy is already built (calibration_bucket_strategy.py).
        DATA: need a political-category resolved corpus. Two paths: (A) OA-16 — owner downloads
        Polymarket-v1 HuggingFace daily_aligned Parquet (no Polymarket API egress, CC-BY-4.0,
        1.3M markets); or (B) OA-11 re-run with --categories filter (existing script, no code
        change). Path A is preferred (larger corpus, no live API egress).
      factory_next_action: >
        Loop-buildable (no new data required first): build polymarket_v1_hf_fetcher.py that
        reads the daily_aligned Parquet from HuggingFace (huggingface_hub Python library,
        dataset TimeSeventeen/Polymarket-v1) and assembles leakage-safe HistoricalMarket records
        — same structural anti-leakage guarantee as polymarket_history_fetcher.py. Once owner
        confirms HuggingFace egress is accessible (OA-16 step 1), run the fetcher to extract
        the political corpus and feed EXP-003.
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
    - "B4a FIRST model_prob != crowd alpha BUILT (calibration_bucket_strategy.py): per-price-bucket empirical-calibration model + strategy; fits per-bucket YES-rates on a leakage-safe training set, ABSTAINS below min_bucket_n (default 30, never hardcodes), RAISES on empty fit; plugs into walk_forward (fresh model per call) + a live wrapper that abstains entirely without a fitted model (no fake control, left UNWIRED). 24 tests: recovers an injected OOS edge, 0/$0 on a well-calibrated crowd, cost band suppresses sub-threshold miscalibration, leakage-safe + reproduces. 3 fresh Opus auditors CANNOT-BREAK (no leakage, no fabricated edge, no overclaim). The MECHANISM, not a validated edge — needs the 7-day OOS corpus (OA-11) to prove a real edge; no DoD/floor box ticked."
    - "E5/E2 learning engines WIRED into the live loop (metrics_aggregator.compute_evaluation_windows + compute_calibration_drift; orchestrator.get_resolved_evaluation_trades + get_resolved_predictions; GET /metrics/evaluation-windows + /metrics/calibration-drift). Honest degenerate path: zero-trade windows never fabricated, Brier null without per-trade calibration, drift returns insufficient_data (never a false 'no drift = good'). 2 Sonnet + 1 Opus auditor CANNOT-BREAK."
    - "C5 dashboard UI BUILT (frontend/components/metrics/*): MetricsPanel + Weekly/Floor/Calibration/PerStrategy/EvaluationWindows cards render all /prediction-markets/metrics/* endpoints under a new Metrics tab; honest degenerate rendering (floor NOT MET with real avg, calibration note verbatim + Brier '—', drift 'not enough data', nulls as '—', a 0-trades banner). npm run build clean. F5 Playwright visual-verification of these states still pending."
    - "GATE STRENGTHENED again: test_calibration_bucket_strategy.py added to the blocking preflight list."
    - "Research Run 10 (2026-06-30): academic synthesis. Le 2026 (292M trades, Kalshi+Polymarket) confirms domain-specific calibration decomposition: political markets show PERSISTENT underconfidence (compression toward 50%) at ALL horizons — the dominant calibration component (bilateral partisan cancellation). EXP-003 proposed. Prediction Arena 2026: ALL 6 frontier LLMs lost money live-trading on Kalshi (-16% to -30.8%); Polymarket only -1.1% avg. PolyBench 2026: only 2/7 LLMs positive (MiMo-V2-Flash +17.6% CWR, Gemini-3-Flash +6.2%) — Gemini models show positive calibration, relevant for B4 design. MAJOR DATA FINDING: Polymarket-v1 HuggingFace dataset (arxiv 2606.04217, June 2026) — 1.3M markets, 1.2B trades, CC-BY-4.0, Parquet, includes market metadata + outcomes in daily_aligned layer — could bypass OA-11 entirely (proposed OA-16). Insider trading on Polymarket: ~25% of large longshot bets ($2500+, <35%) resolve YES vs 14% baseline; proposed as a DEFENSIVE adverse selection filter (avoid these markets), not an edge to copy. Cross-venue arb: confirmed bot-dominated (Kalshi now #1 by volume at $14.8B/mo April 2026). Binding constraint UNCHANGED: no validated OOS edge; OA-11/OA-15 (egress) OR new OA-16 (HuggingFace download) needed."
    - "Research Run 12 (2026-07-02): production-forensics on the now-live OA-17 forward-paper cycle
      (live-validation.yml, every 6h on GH Actions, Neon DATABASE_URL secret set). URGENT finding:
      the orchestrator's real order-persist path (_persist_order) has no default-portfolio guard and
      fails EVERY order with a Postgres ForeignKeyViolation, confirmed live today — despite two prior
      fixes (#139/#140) believed to cover this; the guarded path (persistence.save_order/save_position)
      is never called by the live loop. The forward-paper track record this mechanism was built to
      produce may not be durably accumulating. SECOND finding: the D2 per-category $200 cap has become
      a de facto GLOBAL cap because Market.category is empty on real Polymarket data (everything
      buckets as 'General') plus the in-memory category map resets every fresh process — confirmed
      live: 98/98 opportunities skipped in the most recent scheduled run. Both are loop-buildable code
      fixes, no data/egress/owner action needed. THIRD (insufficient data): logical_implication +
      adaptive_threshold fired real signals on live MECE question sets (LeBron team markets, FIFA WC
      winners) for the first time — not an edge claim, no resolutions yet. FOURTH: confirmed (not just
      theorized) that GitHub Actions runners have working Polymarket/Gemini egress, de-risking OA-13
      Option B. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "Research Run 11 (2026-07-01): SELF-VALIDATION — tested OA-16's premise directly from the autonomous env's own proxy: huggingface.co is 403-blocked (confirmed via the proxy's own diagnostic, not just an app error), and data-api.polymarket.com (the whale-feed's dependency) is ALSO 403-blocked. The egress block is broad-scope (Polymarket + HuggingFace + Data API), not a narrow allowlist gap — OA-16 step 1 can only be verified from the OWNER's own network, never from this env. A secondary comparative-calibration source (Calibration City 671K markets + brier.fyi 971 cross-linked markets) reports Polymarket calibration beating Kalshi's — the opposite direction a Kalshi-anchored effect (Le 2026) needs to transfer cleanly to Polymarket; added as a pre-mortem caution to EXP-002/EXP-003 (not a refutation — non-peer-reviewed, unreproduced by us). URGENT INTEGRITY FINDING (not an alpha claim): `WhaleCopyTradingStrategy` + `WeatherArbitrageStrategy` are wired UNCONDITIONALLY into `orchestrator._build_default_scanner()` (live in the paper scan loop today) despite NEVER being logged as proposed/tracked in ROADMAP or RESEARCH_MEMORY, and with zero tests. Worse: `whale_feed.py`'s hardcoded `KNOWN_WHALES` seed pairs the real trader name 'Theo4' with a WRONG on-chain address (verified against Theo4's actual public Polymarket profile address, which differs completely), and a third seed address is a self-evidently fake sequential-hex placeholder (`0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0`). Since the feed's dynamic `/holders` self-correction is also unreachable here (Data API 403), in this env the strategy runs on the fabricated seed alone, silently (logged warning, strategy continues), inflating the reported strategy count with a contributor producing no real signal. Full detail + recommended factory fix in RESEARCH_MEMORY 2026-07-01."
    - "Factory run (2026-07-03): B8 cross-venue coherence matcher + backtest BUILT (#179, prediction_markets/cross_venue_matcher.py) — the strongest reason to run two venues: trade the price gap when the SAME event is priced differently on Polymarket vs Kalshi (a logical-consistency edge that does NOT require out-calibrating the crowd, unlike B4a which lost -$639 OOS). Adversarially-hardened event-matcher (content + numeric-strike + timeframe gates; boolean match separated from a bounded coherence_score) + cost-net coherence primitive (no fabricated edge when venues agree) + resolved-pair backtest that honestly models the resolution-divergence downside. The adversarial gate broke it 4x/3 cycles (adjacent-strike tolerance, no-threshold cap, negation parsing x2) — the negation rabbit hole was ended by ELIMINATING the fragile inversion heuristic: a negated comparator now VOIDS the strike (tightening-only, can never fabricate a match). NO orchestrator/executor wiring (DECISION COROLLARY); a CANDIDATE edge, NOT validated (no DoD/floor box). F10 regime-slice report WIRED into validate_real_oos (#180) — anti-overfitting concentration check on every real OOS run; fixed a structurally-false category FRAGILE on an unlabeled corpus at the regime_slice root. Blocking-gate coverage: registered test_market_category (the #156 confirmed-outage fix, was NOT in the required gate), test_weekly_metrics, test_cross_venue_matcher (#182). Binding constraint UNCHANGED (validated OOS edge, owner/egress-blocked OA-11/15/16); B8 gives a second, possibly-more-robust alpha CANDIDATE once real dual-venue corpora exist. Dropped A3 Kalshi-category routing as padding (Kalshi not live-scanned; the loop already dropped this nit — the value reviewer caught it)."
    - "Factory run 3 (2026-07-02): ADDRESSED both of Research Run 12's URGENT loop-buildable flags. (1) LIVE-FREEZE FIXED (#156): the forward-paper cycle was skipping 154/154 opportunities on a de-facto-global category cap (real Polymarket markets ship empty `category` → everything bucketed 'General' → per-category $200 cap < $500 portfolio cap). New pure `market_category.py` derives a coarse real correlation bucket (tags → keyword scan) at parse time; `Position` carries category so rehydrated positions count in their real bucket across the fresh-process cycle. Opus safety auditor SAFE (the $500 global backstop still binds at both risk-manager + executor layers). (2) The FK-persist flag was VERIFIED-AND-DISPROVEN as a live bug (its 6/6-fail evidence predated the #140 seed; live runs now rehydrate $164 of positions — impossible if `_persist_order` still FK-failed) — so instead of re-fixing a non-bug, #157 hardened the live writer (in-transaction `_ensure_default_portfolio`) and closed the genuine gap: a missing FK-enforced (`PRAGMA foreign_keys=ON`) regression test on the live writer, since the SQLite gate was FK-blind by construction. No validated edge / no DoD box ticked — an operational unfreeze + coverage. Two more unguarded `portfolio_id=1` writers (`_take_snapshot`, `api/routes.py:445`) remain as a fast follow-up."
    - "Research Run 13 (2026-07-03): SELF-VALIDATED (direct job-log read, not self-report) that both Research Run 12 URGENT fixes hold live: the category-cap freeze stayed broken through the 2026-07-02 09:36 + 14:31 runs (98/98, 154/154 skipped) then fixed itself by 19:55 the same day (10/94 executed) and stayed fixed through 07-03 09:37 (6/108 executed, diverse categories: FIFA WC, Fed decision, MLB, esports, geopolitics, NVIDIA); zero ForeignKeyViolation/exception recurrence across 5 full job logs grepped. Zero resolutions yet (`resolutions: null` every run) — expected, not a bug: bankroll_remaining fell $500→$153.89 as positions opened but time hasn't passed for the short-dated ones (this week's Elon tweet-count window, a within-2-weeks Iran deadline) to resolve; the near-term binding constraint for real calibration/PnL evidence is now simply ELAPSED TIME, not a code defect. Minor non-blocking note: Gemini client fails to construct in every inspected smoke-test step (LLM not on the scan-decision critical path, degrades safely per G2, but no live Gemini connectivity currently for future B4 work). NEW DATA-SOURCE LEAD: Dune Analytics ships a free-tier unified Polymarket+Kalshi resolved-market dataset (simpler than HF parquet, uniquely spans BOTH venues — useful for EXP-004) but is CONFIRMED egress-blocked from the autonomous env (dune.com 403, same broad-allowlist signature as the other 3 blocked domains) and needs a free DUNE_API_KEY; not yet built as a fetcher, recommended to the factory. A secondary favorite-longshot-bias search surfaced two non-academic sources making OPPOSITE-direction claims about near-zero-price calibration — treated as noise per playbook discipline, not evidence either way. No new EXP proposed (proposing one against a zero-resolution track record would be premature). Full detail: RESEARCH_MEMORY 2026-07-03."
    - "Factory run 2 (2026-07-04): SAFETY — reject SELL-to-open-a-short (#215, D3/D4). A bare SELL on an un-held token fabricated a fictional `side=\"short\"` position via the paper `_simulate_fill` (fills unconditionally — a phantom fill the live venue would REJECT, since you can't sell CTF tokens you don't own), and a BUY 'to close' it scaled the position UP recording $0 realized PnL → the hard loss caps + kill switch (D3/D4) never saw the loss. REACHABLE in the live default scan: CrossMarketArbitrageStrategy emits an executable outcome_idx=0 SELL (strategies.py:627/686), routed at orchestrator.py:1033; skip-held guarantees any executed SELL is on an un-held token. Reproduced end-to-end (bare SELL→FILLED short 100@0.30; BUY-to-close→size 200, realized_pnl 0.0). Fix: `_check_risk` rejects a SELL whose size exceeds the covering long; SELL-to-reduce-a-held-long is preserved. 5 tests (3 fail-pre-fix); 2 Sonnet + a fresh Opus live-safety auditor SAFE (6 executed attack vectors). This OVERTURNED a twice-dropped 'SELL/short unreachable' prior with new specific evidence + a repro (the mirror of the anti-re-litigation rule). Also #216 gated test_simulation_engine (48 tests of the LIVE Monte-Carlo pricing feeding Kelly, previously ungated) + #217 removed the last stock-era render.yaml residue (FRED_API_KEY). No DoD/floor box ticked. Two non-blocking Opus-flagged follow-ups: the 1e-9 boundary tightening + legacy short-row remediation (guard the _update_position BUY-on-short branch)."
  next_actions:
    - "URGENT, loop-buildable, no owner/data action needed (Research Run 12, 2026-07-02): the live
      OA-17 forward-paper cycle's real write path (orchestrator._persist_order, orchestrator.py:1034)
      has NO _ensure_default_portfolio guard and fails EVERY order persist with a Postgres
      ForeignKeyViolation — confirmed live in today's GitHub Actions logs (run 28563250362, 6/6
      executions failed to save), despite two prior fixes (#139, #140) that were believed to cover
      this. persistence.py's guarded save_order/save_position are never called by the live loop; the
      init_db() seed (#140) does not appear sufficient in production (root cause of WHY still needs
      RCA). Fix: route _persist_order through the guarded persistence.save_order/save_position (one
      write path, not three) AND add a PRAGMA-foreign_keys-ON SQLite (or Postgres-parity) regression
      test to the blocking gate — the current SQLite-only CI cannot catch this bug class by
      construction, which is why it has now recurred. Until fixed, do not read edge into any
      forward-paper numbers collected since OA-17 went live. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "URGENT, loop-buildable (Research Run 12, 2026-07-02): the D2 per-category exposure cap has
      become a de facto GLOBAL $200 cap, not a per-category one — Market.category is empty on real
      Polymarket data (polymarket_client.py:799 parses raw.get('category','')), so risk_manager.py:157
      buckets every real market as 'General', and the in-memory _market_categories map resets empty
      every fresh GH-Actions process, so rehydrated positions ALSO default to 'General'. Confirmed
      live: the 2026-07-02T09:36 scheduled run skipped 98/98 real opportunities on 'General exposure
      $164.18 > $200'. Since these positions won't resolve for weeks/months, this freezes the forward
      loop until fixed. Fix: derive category from a real Polymarket field (tags/event grouping) instead
      of the empty 'category' key, and/or read the category already stored on PredictionPosition rows
      back on rehydration instead of re-defaulting to General. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "NOTABLE, insufficient data (Research Run 12, 2026-07-02): LogicalImplicationDetector
      ('logical_implication') and AdaptiveBuySignalThreshold ('adaptive_threshold') fired real signals
      live today for the first time (0 signals on the 2026-06-29 sterile fixture) on genuinely
      MECE real-world question sets (LeBron James team markets, FIFA World Cup winner candidates) —
      a plausible confirmation the B5-hardened relatedness screen generalizes to real text. NOT an
      edge claim: no resolutions yet, N<10, and per the finding above most fills likely never
      persisted. All fired trades bought near-zero-price longshots (0.25-1.65 cents) — the highest
      real-slippage-risk regime per EXP-002's pre-mortem. Revisit once persistence (above) is fixed
      and a real track record can accumulate."
    - "CONFIRMED (Research Run 12, 2026-07-02): GitHub Actions runners have working Polymarket +
      Gemini egress (proven repeatedly by live-validation.yml, not just theorized) — de-risks OA-13
      Option B (the staged-but-unapplied refresh-polymarket-data.yml). The only remaining step is the
      owner applying that staged workflow file."
    - "HIGHEST-EV owner action (two paths, either unblocks all calibration alphas at once): PATH A (new OA-16, PREFERRED) — verify HuggingFace egress is accessible, download Polymarket-v1 daily_aligned Parquet (1.3M markets, CC-BY-4.0, no Polymarket API key needed, broader corpus than OA-11); PATH B (existing OA-11) — re-run `python3 scripts/fetch_polymarket_history.py --decision-lead-days 7 --limit 500 --max-pages 3 --min-volume 1000 --merge --out data/polymarket_history_7d.json` from a network-permitted host. Either path produces the corpus needed for EXP-002 + EXP-003 (same CalibrationBucketStrategy mechanism, already built)."
    - "LOOP-BUILDABLE (no data needed): build polymarket_v1_hf_fetcher.py — reads the daily_aligned Parquet from HuggingFace (huggingface_hub Python library, dataset TimeSeventeen/Polymarket-v1) and assembles leakage-safe HistoricalMarket records with the same structural anti-leakage guarantee as polymarket_history_fetcher.py. Once built, OA-16 step 2 (owner runs it) can bypass OA-11 entirely."
    - "NEW (Research Run 13, 2026-07-03): Dune Analytics ships a unified, free-tier Polymarket+Kalshi resolved-market dataset (5 public tables, every resolved market carries its final outcome, hourly candlestick prices back to 2021-2022) — simpler to consume than the OA-16 HuggingFace parquet path AND uniquely spans BOTH venues in one schema (directly useful for EXP-004 cross-venue coherence, which no single existing source covers). CONFIRMED egress-blocked from the autonomous env (dune.com/api.dune.com/docs.dune.com all 403 at the proxy, same broad-allowlist signature as gamma-api/CLOB/HuggingFace/Data-API — the 4th domain in this class). Requires a free DUNE_API_KEY (not fully keyless like the Gamma/CLOB path) — a new, distinct owner-action class. NOT yet built as a fetcher (research-agent scope ends at surfacing the lead); recommend the factory build dune_fetcher.py (mirrors how polymarket_v1_hf_fetcher.py originated) and file the owner step once fixture-tested. GitHub Actions runner reachability to dune.com is untested (plausible but unconfirmed)."
    - "EXP-002 + EXP-003 share the same BUILT mechanism (calibration_bucket_strategy.py) and differ only in the corpus: EXP-002 uses all price ranges at 7-day lead; EXP-003 filters to politics/elections category. Once the corpus arrives, both can be tested in one run: fit on oldest 60%, OOS on newest 40%, B2 significance gate with Bonferroni correction across the two strategies."
    - "B4 LLM research design implication (Prediction Arena + PolyBench findings): if B4 is built, do NOT design an autonomous LLM trader (Prediction Arena proves 5/6 models lose money). Design LLM as a TARGETED RESEARCH TOOL for specific question categories (domain-specific calibration assistance). Use Gemini (already have GEMINI_API_KEY) — PolyBench shows Gemini-3-Flash achieves positive CWR. Gated on B2 producing a passing eval first."
    - "EXP-002 factory build DONE (calibration_bucket_strategy.py) — the CalibrationBucketStrategy is built, tested (24 deterministic tests, 3 Opus auditors CANNOT-BREAK), and plugs into walk_forward. ONLY remaining EXP-002 blocker is the real corpus (OA-11 or OA-16)."
    - "Once real data is available: produce a VALIDATED OOS weekly-PnL series + a passing B2 calibration eval on live strategy probabilities; calibrate the market-impact model against real OrderBook depth; wire the fitted-model fit path into a research/owner entry point + the B3 lifecycle."
    - "A4 event/market-universe + persistent resolution tracking (foundation for B2 on real data + the E learning loop); confirm the audit log's DATABASE_URL is durable (OA-10)."
    - "DONE (2026-07-01, #116) — the Research Run 11 whale/weather integrity finding: the fabricated `KNOWN_WHALES` seed in `whale_feed.py` is REMOVED (now `[]`; the feed uses only real `/leaderboard`+`/holders` discovery — real signal or none, never a fabrication), and `WhaleCopyTradingStrategy` + `WeatherArbitrageStrategy` are gated OUT of BOTH default scanners behind `ENABLE_UNVALIDATED_STRATEGIES` (default off). Tracked as ROADMAP B7. 2 Sonnet reviewers APPROVE + 1 Opus integrity auditor SOUND (verified no fabricated wallet enters any path even via the still-deployed `wallet_divergence` consumer). REMAINING to re-enable either strategy (B7): a B3 `PROPOSED` entry + a `strategy_audit.py` forensic pass + OOS validation (whale additionally needs `data-api.polymarket.com` reachable — egress-blocked in-env)."
  owner_blockers:
    - "Confirm venue ToS + jurisdiction eligibility before any live capability."
    - "OA-16: verify HuggingFace egress from owner's environment; download Polymarket-v1 daily_aligned Parquet (CC-BY-4.0, no API key). This is the preferred path over OA-11 (broader corpus, no Polymarket API egress needed). CONFIRMED (2026-07-01, research run): huggingface.co and data-api.polymarket.com are BOTH 403-blocked from the autonomous env's own proxy — this is a broad-scope block, not a narrow gap, so step 1 must be verified from the owner's own network/host; the loop cannot self-serve it. See PENDING_OPS OA-16."
```

## engine_pct rationale (pinned to real files)

`engine_pct: 73` (up from 72) is a **security + safety + side-effect-integrity hardening**
run (no new edge). (#96) closes the last unguarded state-mutating route — `/prediction-markets/scan`
now carries the shared-secret bearer like its sibling `/bot/scan-now` — bounds the user inputs
(`market_limit`/search `limit`/`query`/kill-switch `reason`), and **bounds-validates `risk/config`**
so a non-positive `daily_loss_limit_usd` (which would DISABLE the loss cap) is rejected 422
(pure `risk_config_validation.py` in the CI gate). (#95) removes a **phantom fill**: the orchestrator
built one empty-token order for multi-leg `outcome_idx == -1` arbitrage baskets that the paper
executor "filled," booking a position that never traversed a real per-leg path — now skipped honestly
until per-leg execution (B1) exists. (#94) makes the durable-state guard **actually fail closed**:
a rehydrate failure trips the kill switch instead of silently resuming a halted bot (an Opus auditor
proved the first cut was dead code because the store swallowed read errors; fixed so `load()` raises
on an unreadable store + a real-store fail-closed test, re-audit FIX-HOLDS) + a defense-in-depth
empty-token reject at the executor gate. The validated EDGE is still absent (binding constraint stays
the 7-day-lead OOS corpus, OA-11 / OA-15), so no DoD/floor box ticks.

### Prior

`engine_pct: 72` (up from 71) adds a **second venue DATA adapter** + a fresh deep-audit
hardening pass (no new edge). A3: `kalshi_client.py` + `kalshi_history_fetcher.py` ingest
public Kalshi market data + leakage-safe resolved history behind the SAME `Market`/`Outcome`
interface (offline-validated; the live status/price contract is documented-but-unverified,
disclosed honestly; an adversarial parsing auditor caught — and the maker fixed — a
BUILDS≠WORKS where the offline fixtures encoded request-filter words as live response values
that would have dropped every live market). Hardening (#91): a live-only boot-guard that
refuses to start with `LIVE_TRADING_ENABLED` on while `BACKEND_API_TOKEN` is empty (no
unauthenticated kill-switch/execute on a real-money deploy), a category-cap under-count fix
keyed to the executor's REAL per-trade cap, risk-score div-by-zero guards, MTM client reuse,
and API exception-detail leak sanitization (§12). The validated EDGE is still absent (the
binding constraint stays the 7-day-lead OOS corpus, OA-11 / now also Kalshi OA-15), so no
DoD/floor box ticks. Prior rationale (engine_pct 71, up from 70) is run-risk-readiness +
security + side-effect hardening of the
control path (no new edge): the kill-switch + realized-PnL loss counters now PERSIST and
rehydrate across a restart (`executor_state_store.py`) — and a BUILDS≠WORKS fix makes the
durable audit-log/registry/executor tables actually get created at startup (they silently
no-op'd before); state-mutating backend routes are now guarded by a degrade-safe shared-secret
token (`auth_core.py` + OA-14); and the REST order path validates the venue body so no fill is
reported without a real acknowledgement (D1). The validated EDGE is still absent (the binding
constraint stays the 7-day-lead OOS corpus, OA-11), so no DoD/floor box ticks. Prior rationale
(engine_pct 70, up from 68) adds the FIRST `model_prob != crowd` alpha mechanism
(`CalibrationBucketStrategy` — the per-bucket empirical-calibration model + strategy, the
EXP-002 build, leakage-safe + abstaining + 3-Opus-auditor-clean), WIRES the last two pure
learning engines into the running system (E5 evaluation-windows + E2 calibration-drift now
flow from the resolved stream through new read-only endpoints with an honest
degenerate/insufficient-data path), and makes paper metrics VISIBLE end-to-end (the
`frontend/components/metrics/` dashboard renders every `/metrics/*` endpoint with honest
empty/degenerate states). The validated EDGE itself is still absent — the calibration-bucket
strategy is the MECHANISM that *could* produce model_prob != crowd, but proving a real edge
needs the 7-day-lead OOS corpus (OA-11, owner/egress-scope), so no DoD/floor box ticks and
the bulk of the missing % remains. Prior rationale (engine_pct 68, up from 66) WIRES the
previously-pure learning-loop engines into the
running system and adds two more: per-strategy realized-PnL attribution (E6) flows from
resolved positions through a new `/metrics/per-strategy` endpoint; the alpha-lifecycle
registry (B3) is now persisted (a durable singleton table) + exposed read-only, seeded
honestly with deployed strategies as PROPOSED (truthfully: no alpha has passed the
integrity gate); market RESOLUTION losses now feed the per-strategy drawdown auto-disable
(D2 — the dominant binary-loss path was bypassing it); the only true logical-arbitrage
strategy now costs its basket through the canonical cost model + gates the multi-outcome
branch on `neg_risk` MECE (B5 honesty); and two new pure learning engines exist — an
evaluation-window engine with realized-vs-backtest overfit reconciliation (E5) and a
significance-gated calibration-drift detector (E2, FP-rate ~1–4% vs 47% for a naive
point comparison). The validated EDGE itself is still absent (no model_prob != crowd
alpha), and B3 evidence is still caller-asserted (authenticity-derivation is a named
follow-up), so the bulk of the missing % remains. Prior rationale (engine_pct 66, up from
64) adds this run's learning-loop engine pieces: the alpha
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
- Paper/forward execution — the dry-run `execution.py` executor + the forward paper cycle `scripts/run_paper_cycle.py` (rehydrates OPEN positions across runs — ROADMAP D8, #143; the standalone `paper_simulator.py` was retired as dead code in #126)
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
