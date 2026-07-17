# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-17 — overall `B`. Ship gate: NOT met.**

Ninth grade, re-verified by fresh, independent, adversarial per-dimension graders (none the
maker). **One dimension crossed a threshold — upward:** `correctness_reliability` **A → A+**,
because the factory genuinely closed the *sole* named residual that had held it at A for
several cycles (the `WalletBehaviorDivergence` decoupled-confidence bug, #338), and a fresh
adversarial hunt found **no replacement** paper-path correctness finding. Every other grade
held exactly (`security` A+, `tests_evals` A+, the other seven A/B as last cycle). Overall
stays **B** and the ship gate stays closed for the one unchanged reason:
`business_case_strength` is still **B** — **no validated out-of-sample cost-net edge** — and
this cycle's research is a pre-registered *pilot probe* (EXP-006), not a validated result.

**The research event this cycle (Runs 21–25, 2026-07-14 → 2026-07-17):** the loop scoped and
grew a **pilot** of the structurally-different EXP-006 candidate (political price-reversal after
hype spikes) — a *raw lag-1 autocorrelation probe*, **not** a formal strategy backtest (no
strategy code, no cost model, no F10/F11 gate). Across three disjoint samples it measured
negative lag-1 autocorrelation with bootstrap CIs excluding zero (Run 23 N=16, Run 24 N=67,
Run 25 N=14 on a different `volume24hr` sampling axis / 2023–24 era), **but every sample is far
below the pre-registered 100-event floor**, and the writeups honestly flag a 35.7% single-cluster
(Hamas) concentration and an *unverified* ~81 combined N. This is honest preliminary signal
only. It reaches **no** revenue field: `weekly_pnl_paper` stays `null`, `arr_year1` stays 0,
`total_trades` stays 0. The bucket-calibration family remains **refuted/non-robust across 3
independent real per-category corpora** (EXP-002 N=510, EXP-005 Sports N=814, EXP-003 Politics
N=1,369). Do NOT re-test the refuted family; EXP-006 is not yet a testable OOS result.

**What the factory shipped since 2026-07-13 (verified by fresh adversarial graders, not trusted):**

- **#338 (correctness — the A→A+ promotion) — GENUINE.** `WalletBehaviorDivergence.confidence`
  now emits `gate_confidence(avg_price, edge)` (`advanced_strategies.py:1254`) — the same shared
  units-contract helper every other executing strategy uses — and the decoupled
  `_compute_confidence` heuristic is **DELETED repo-wide** (only a NOTE comment survives,
  `:1158`). Non-tautological test pins `confidence == entry_price+edge` and asserts
  `not hasattr(strat, "_compute_confidence")` + a behavioral gate flip
  (`test_confidence_units_gated.py:191-229`). This was the last standing correctness residual
  (same bug class as #263/#268/#275/#280/#284) — now closed.
- **#330 / #362 (run-risk / live-safety) — GENUINE.** Every unbounded venue call on the
  (gated-off) live order path is now time-bounded via `_call_with_timeout` in a daemon thread:
  `create_and_sign_order` + `post_order` (`execution.py:374,379`) and `cancel_order`
  (`execution.py:703`). A timeout returns REJECTED / False with no fabricated fill
  (`execution.py:470-495`), so a stalled py-clob-client call can't hang the event loop.
- **#364 (run-risk / risk-correctness) — GENUINE.** The per-strategy drawdown circuit now nets
  fees into the per-strategy value (`record_pnl(strategy, pnl, fees=result.fees + entry_fee)`,
  `execution.py:1395` → `_strategy_current_value[strategy] += pnl - abs(fees)`,
  `risk_manager.py:256`), scoped so it does **not** double-count `_daily_pnl`. A decayed alpha's
  auto-disable now gates on TRUE net cash PnL. Load-bearing test: gross dd 19.6% < 20% but net
  crosses 20% → disabled (`test_sell_reduce_drawdown.py:118-146`).
- **#350 / #351 (backtest-integrity infra) — GENUINE + correctly advisory.** A leakage-safe
  intraday spike-detection/reversal-labeling *primitive* (`spike_detection.py`, "only unblocks
  the honest test", no trading/PnL claim) + two seed_hash reproducibility invariants pinned in
  `test_walk_forward_pm.py` (research_only-inertness + input-order-invariance, non-vacuous).

The only thing holding the overall at **B** and keeping the ship gate closed is unchanged:

- **business_case_strength = B (ship-critical — THE binding constraint):** still **no validated,
  out-of-sample, cost-net edge**. Revenue $0, the $104k/yr floor unmet (`BUSINESS_CASE.md:28-34`:
  `arr_year1` all 0, `floor_met_year1: false`; `GROWTH_STATUS.md:33-48`: `weekly_pnl_paper: null`,
  `weeks_validated_above_floor: 0`, `total_trades: 0`, `go_live.status: not_ready`). This cycle's
  EXP-006 pilot is honest preliminary signal (N=14–67, below the 100-event floor, no cost/F10/F11
  gate), not a demonstrated edge. By the rubric an unrealized (honest) case is a **B**; A requires
  a demonstrated cost-net OOS edge that clears F10/F11. (Issue #79, refreshed.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. The
walk-forward engine reproduces bit-identically (two runs this cycle: `seed 42 / hash
b3a8d5e0e9579853`, PnL 910,880.71, sha256-identical outputs; SYNTHETIC demo labeled "NOT a
validated edge"). The leak guard is STRUCTURAL (`MarketView` omits outcome/resolution_time,
`walk_forward.py:116-128`; train strictly `< w_start`, `:402`; all history fetchers RAISE rather
than fabricate a decision price, `polymarket_history_fetcher.py:388`, `kalshi_history_fetcher.py:384`).
The #259 STRUCTURAL guardrail still bars play-money PnL from the real-money floor
(`validate_real_oos.py:53`). Every positive-looking research number is explicitly annotated
fragile/insignificant/pilot-not-a-test and reaches no revenue field.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Runtime harness E2E PASSED (paper order FILLED, deterministic exposure 10.000000==10.000000, live gate REJECTS, kill switch + max-position ($900>$50) + loss-cap net-of-fees −$41.20 all trip). Real pipeline `orchestrator.py:885` scan(200)→size→executor→persist, no stubbed stage. Below A+: multi-leg/basket (`outcome_idx<0`) still honestly SKIPPED from paper (`orchestrator.py:1017-1036`, audit-logged not phantom-filled; B1 "per-leg execution not yet built"). |
| backtest_integrity | A | ✅ | **Independently re-reproduced this cycle: two `run_walk_forward.py` runs → seed_hash b3a8d5e0e9579853, PnL 910,880.71, sha256-IDENTICAL (`c7d628ef…`); 104 integrity tests pass.** Leak guard STRUCTURAL (`MarketView` omits outcome/resolution_time `walk_forward.py:116-128`; train `< w_start` `:402`; fetchers RAISE `polymarket_history_fetcher.py:388`, `kalshi_history_fetcher.py:384`). F10 (`regime_slice.py`) + F11 (`bootstrap_oos_significance.py`) auto-run on every real corpus (`validate_real_oos.py:80-96`). EXP-006 handled as a labeled pilot, no p-hacking. Below A+: only SYNTHETIC reproduces offline (real N=510/814/1,369 corpora NOT committed — egress-gated); `DEFAULT_IMPACT_COEFF=0.5` explicit uncalibrated placeholder (`cost_model.py:44`). |
| correctness_reliability | A+ | ✅ | **PROMOTED A→A+.** Determinism verified (harness exposureA==exposureB; walk-forward identical hash). **#338 closed the sole named residual:** `WalletBehaviorDivergence.confidence = gate_confidence(avg_price, edge)` (`advanced_strategies.py:1254`), `_compute_confidence` deleted repo-wide, non-tautological test (`test_confidence_units_gated.py:191-229`). Adversarial hunt found no replacement paper-path finding: no swallowed paper-path errors (live-gate reads fail CLOSED `execution.py:317,845`), no mutable defaults, div-by-zero guarded (`risk_manager.py:262`, `execution.py:611`). |
| security | A+ | ✅ | Fresh secret scan clean (no `sk-`/`AKIA`; only `backend/.env.example`, `frontend/.env.example` tracked; recent commits add only dummy fixtures `api_key="k"`). Auth default-CLOSED + fail-closed + `hmac.compare_digest` (`auth.py:50-59`, `auth_core.py:55`). Live gate un-flippable via body (`OrderRequest` has no live field `execution.py:122-134`; flag only READ, fail-closed at venue layer `:316-320`). `next 14.2.35` (`frontend/package.json:22`). No new hole. |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS, kill switch blocks, max-position rejects $900>$50, loss cap trips net-of-fees −$41.20 vs −$10 + blocks subsequent orders. **#330/#362 (venue-call timeouts, `execution.py:374,379,703`) + #364 (per-strategy drawdown fee-netting, `risk_manager.py:256`) verified GENUINE.** HUMAN-CORE intact (ZERO `live_trading_enabled = True` in `backend/app`; config reads fail-closed). Below A+ (unchanged residual): LIVE kill-switch net-of-fee still rests on `fill==limit` (`filled_price = req.price or 0.50`) + `DEFAULT_FEE_RATE` estimate (`execution.py:456,467,636,644`) not the venue's real fill/fee field — conservative (trips EARLIER), gated-OFF live path only. |
| artifact_integrity | A | ✅ | Every revenue metric honestly 0/null (`BUSINESS_CASE.md:28-34`; `GROWTH_STATUS.md:33-48`); seed hashes reproduce; scorecard parses (overall=B). EXP-003 numbers match line-for-line across `GROWTH_STATUS.md:186-194` + `RESEARCH_MEMORY.md:2154,2183-2194` (472 trades, +$28,815.49, hit_rate 25.64%, CI [-36648.21,105232.67], LOO −$9,665.99). EXP-006 labeled pilot everywhere. Below A+ (recurring nit): docs cite a test count (~1140) BELOW the real collection (**1538 collected, 0 errors with pandas; 1197 collected / 13 pandas-missing errors in the light gate**) — direction understated/honest, never inflated; cite the curated preflight-green gate not the raw total. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, bucket-calibration family refuted across **3** real corpora. This cycle's EXP-006 is a raw-autocorrelation **pilot** (N=14–67, below the 100-event floor, no cost/F10/F11 gate) — honest preliminary signal, reaches no revenue field. THE binding constraint (#79). |
| design_taste | A | — | Unchanged (`git diff --stat 8a52db2..HEAD -- frontend/` empty — no frontend diff since last grade). Systemic null-honesty (`—` sentinels `CalibrationCard.tsx:37`, "Insufficient data — 0 resolved trades" `MetricsPanel.tsx:141-147`); honest recharts axes (P&L anchored $0, equity zoomed labeled `predictions/page.tsx:962-971`); no fabricated-data screens. Below A+: static (already-good), no advancement. |
| tests_evals | A+ | — | Blocking gate GREEN. New in-gate tests verified to RUN + PASS (not skip): `test_strategy_drawdown_disable.py`, `test_strategy_enable_disable.py`, `test_spike_detection.py` (37 passed, 0 skipped); seed_hash invariance guards (#351) in `test_walk_forward_pm.py` (8 passed, non-vacuous); #364 fee-netting covered (`test_sell_reduce_drawdown.py`, 52 passed). Comprehensive in-gate integrity coverage: leakage, seed-hash determinism, loss caps, live gate, calibration, F10/F11. Margin evals correctly ADVISORY-only (absent from `preflight.sh` blocking gate). |
| performance | A | — | No hot-path regression: scan capped `market_limit=200` (`orchestrator.py:900`); walk-forward sorts once by `(decision_time, market_id)` then hash+process (cold path). No egregious scan/execute/persist waste. Proportionate for a personal paper bot. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-17
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests + safety + secrets + runtime harness + scorecard-parse + self-validation (13/13) + GTM-honesty all OK
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap ($900>$50) + per-trade cap + loss cap net-of-fees (-$41.20 vs -$10, blocks subsequent) + paper PnL, deterministic (exposureA==exposureB==10.000000)
    walk_forward_reproduces: true      # seed 42, seed_hash b3a8d5e0e9579853, total PnL 910,880.71 - two runs this cycle produced SHA256-IDENTICAL outputs (c7d628ef...; SYNTHETIC demo, labeled NOT a validated edge); 104 walk-forward/F10/F11/cost/drawdown/calibration gate tests pass
    test_collection: "1538 collected / 0 errors WITH pandas (2.40s); 1197 collected / 13 errors (all `No module named pandas`) in the light CI gate - the documented heavy-dep exclusions (preflight.sh). Docs cite ~1140 (BELOW true count) - direction understated/honest, never inflated. Cite the curated preflight-green gate rather than a raw total that drifts every cycle."
    real_oos_probe: "No real OOS edge test this cycle - the research loop ran a PILOT probe of EXP-006 (political price-reversal after hype spikes), NOT a formal strategy backtest. Runs 23-25 (2026-07-15..17) measured raw lag-1 autocorrelation on Polymarket political markets: Run 23 N=16, Run 24 N=67 (volumeNum axis), Run 25 N=14 (volume24hr axis, 2023-24 era). All three show NEGATIVE mean lag-1 autocorrelation with bootstrap 95% CIs EXCLUDING zero (e.g. Run 25 mean -0.1154, CI [-0.2017,-0.0308], 12/14 individually negative), a 3rd directional corroboration - BUT every sample is FAR BELOW the pre-registered 100-event floor, has NO strategy code / NO cost model / NO F10/F11 gate, and the writeups honestly flag a 35.7% single-cluster (Hamas) concentration + an UNVERIFIED ~81 combined N. Honest preliminary signal ONLY; reaches no revenue field. The bucket-calibration family stays REFUTED across 3 real corpora (EXP-002 N=510, EXP-005 N=814, EXP-003 N=1,369). Do NOT re-test the refuted family; EXP-006 is not yet a testable OOS result."
    integrity_gates_exercised: "F11 bootstrap significance (bootstrap_oos_significance.py:161-177, seeded percentile CI, edge only when significant_positive) and F10 leave-one-out fragility (regime_slice.py:264-330) both exist, are wired to auto-run on every real corpus (validate_real_oos.py:80-96), and previously rejected EXP-003's +$28,815.49 + EXP-005's +$16,993.97 headlines (indistinguishable_from_zero + fragile). Not narrative - matches recorded numbers across GROWTH_STATUS.md + RESEARCH_MEMORY.md line-for-line."
    play_money_guardrail: "#259 STRUCTURAL - validate_real_oos.evaluate RAISES on any research_only=True (Manifold/play-money) record (validate_real_oos.py:46-56). Play-money PnL cannot reach the real-money floor."
    leak_guard: "STRUCTURAL - MarketView omits outcome/resolution_time (walk_forward.py:116-128); train=resolution_time<w_start strict (:402); all history fetchers RAISE rather than fabricate a decision-time price (polymarket_history_fetcher.py:388, kalshi_history_fetcher.py:384); _last_pre_decision_price excludes t>=resolution_ts + NaN/inf; research_only excluded from _seed_hash (invariance test-pinned)"
    new_fixes_verified: "#338 (WalletBehaviorDivergence.confidence pinned to gate_confidence(avg_price,edge) advanced_strategies.py:1254; _compute_confidence DELETED repo-wide; non-tautological test test_confidence_units_gated.py:191-229 - CLOSES the last correctness A->A+ residual), #330/#362 (venue-call timeouts execution.py:374,379,703 - stalled py-clob-client can't hang the loop), #364 (per-strategy drawdown fee-netting risk_manager.py:256; test_sell_reduce_drawdown.py:118-146 gross 19.6%<20% but net crosses -> disabled), #350/#351 (leakage-safe spike-detection primitive + 2 seed_hash invariance tests) - all verified GENUINE by fresh adversarial graders"
    secret_scan: "clean - no sk-/AKIA in tree; only backend/.env.example + frontend/.env.example tracked; recent commits add only dummy test fixtures (api_key='k'); next 14.2.35"
    human_core: "ZERO `live_trading_enabled = True` assignments in backend/app; the flag is only READ, fail-closed at the venue layer (execution.py:316-320,844) with _live_ok=False on any settings exception"
    ruff_correctness_gate: "clean - E9/F821/F811 pass (narrow --select; ~150 hygiene findings NOT enforced by design)"
    scorecard_gate: "NOT-READY (business_case_strength: B - ship-critical needs A/A+)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["multi-leg/basket arbitrage (outcome_idx<0) is honestly SKIPPED from paper execution (orchestrator.py:1017-1036 audit-logs skip_multi_leg rather than booking a phantom fill; 'per-leg execution B1 not yet built'), so the arb strategies in the default set don't reach paper fills. Disclosed integrity, not a fake stage; caps below A+."]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the real-OOS results are not reproducible from committed artifacts - the N=510/814/1,369 real corpora (and the EXP-006 pilot CIs) are NOT in the repo (only a 54-record synthetic sample fixture), so those numbers depend on a live Gamma fetch and must be taken on documented faith. Only the SYNTHETIC engine reproduces offline (re-verified sha256-identical this cycle). Plus DEFAULT_IMPACT_COEFF=0.5 (cost_model.py:44) is an uncalibrated placeholder. Both honesty-preserving, not integrity failures; cap below A+. Caching a frozen real corpus + fitting impact_coeff to real book depth would close to A+."]
    - name: correctness_reliability
      grade: "A+"
      ship_critical: true
      top_gaps: []
    - name: security
      grade: "A+"
      ship_critical: true
      top_gaps: []
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["unchanged residual: the LIVE kill-switch net-of-fee correctness still rests on a DEFAULT_FEE_RATE estimate and an assumed fill==limit price (execution.py:456,467,636,644: filled_price = req.price or 0.50; fees estimated at the default rate) rather than the venue's real fill price / fee field - acknowledged in-code, conservative (caps trip EARLIER not later), gated-OFF live path only. #330/#362 (venue-call timeouts) + #364 (per-strategy drawdown fee-netting) landed this cycle. A non-zero residual on live fidelity; harmless while paper-only + gated off."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the reported test count is stale/understated (docs cite ~1140; real collection is 1538/0-errors with pandas, 1197/13-pandas-missing in the light gate). Direction is understated/conservative and self-disclosed, never inflated. Break the cycle by citing the curated preflight-green gate instead of a raw collection total that changes every cycle as test files are added."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists - revenue $0, $104k/yr floor unmet. The bucket-calibration family (static + recency) is REFUTED across 3 independent real per-category corpora (EXP-002 N=510, EXP-005 Sports N=814, EXP-003 Politics N=1,369). This cycle's EXP-006 (political price-reversal after hype spikes) is a raw lag-1 autocorrelation PILOT (Runs 23-25, N=14-67, below the pre-registered 100-event floor, no strategy code / no cost model / no F10/F11 gate) - honest directional signal but NOT a validated edge, and it reaches no revenue field. Honest but unproven (THE binding constraint, #79). A validated edge requires a NEW pre-registered MECHANISM (NOT another bucket-calibration parameterization - that family is exhausted) whose OOS walk_forward PnL has an F11 CI EXCLUDING zero, F10 non-fragile (leave-one-out stays positive), hit-rate meaningfully >50%, sustained several consecutive OOS weeks above the $2k/wk floor with sufficient N. EXP-006 must reach N>=100 + a full strategy/cost/F10/F11 backtest before it can count."]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: ["static since last grade (no frontend diff, 8a52db2..HEAD empty). Already-good null-honesty + honest axes; no regression, no advancement - the only thing below A+."]
    - name: tests_evals
      grade: "A+"
      ship_critical: false
      top_gaps: []
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) - cold backtest path only, low stakes."]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge - revenue $0, $104k/yr floor unmet. The bucket-calibration family is REFUTED across 3 independent real per-category corpora (EXP-002 N=510, EXP-005 Sports N=814, EXP-003 Politics N=1,369). This cycle's EXP-006 (political price-reversal) is a raw-autocorrelation PILOT (N=14-67, below the 100-event floor, no strategy/cost/F10/F11 gate) - honest directional signal, not a validated edge, reaches no revenue field. THE binding constraint. Next: EXP-006 must reach N>=100 with a full strategy + cost model + F10 (non-fragile) + F11 (CI excludes 0) walk_forward cost-net on a real point-in-time non-survivorship panel above the floor - OR a NEW mechanism does. (Issue #79, egress/owner-gated.)"
    - "backtest_integrity (A->A+): cache a frozen real resolved-market corpus into the repo so a real (not just synthetic) OOS result reproduces offline from committed artifacts, and calibrate the market-impact/capacity term against real order-book depth (cost_model.py:44) rather than the DEFAULT_IMPACT_COEFF=0.5 placeholder."
    - "run_risk_readiness (A->A+): make the LIVE kill-switch net-of a REAL venue fee/fill field when the venue response carries one, rather than the DEFAULT_FEE_RATE + fill==limit estimate (execution.py:456,467,636,644), so a hard loss cap can't undercount true live cash loss."
    - "functional_reality (A->A+): build per-leg execution (B1) so multi-leg/basket arbitrage (outcome_idx<0) reaches paper fills instead of being audit-logged as skip_multi_leg (orchestrator.py:1017-1036)."
    - "artifact_integrity (keep-at-A): stop the recurring test-count drift (docs cite ~1140 vs real 1538/0-errors) by citing the curated preflight-green gate in docs rather than a raw collection total that changes every cycle."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is refuted across **3** independent real
per-category corpora, and this cycle's EXP-006 candidate is a *pilot probe* at N=14–67, far
below the 100-event floor, with no strategy/cost/F10/F11 gate — honest directional signal, not
a validated result) — so the quality gate fails, and independently the full `preflight.sh` is
honest-RED (`floor_met_year1: false`, DoD boxes unchecked). This is the project's core
discipline working exactly as designed: **never let a number that isn't real drive a decision,
and never claim an edge you cannot reproduce out-of-sample.** This cycle the factory shipped
real, verified progress on the non-binding dimensions — most notably closing the last standing
correctness residual (#338, promoting `correctness_reliability` to **A+**), venue-call timeouts
(#330/#362), per-strategy drawdown fee-netting (#364), and leakage-safe EXP-006 pilot infra
(#350/#351) — and the research loop grew an honest pilot of its next candidate. The one
remaining ship-critical gap is correctly, honestly open.
