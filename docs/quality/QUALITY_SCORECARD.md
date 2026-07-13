# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-13 — overall `B`. Ship gate: NOT met.**

A **steady-state** cycle since 2026-07-11 (~26 commits), re-verified by fresh, independent,
adversarial per-dimension graders (none the maker). **No dimension crossed a threshold in either
direction** — every ship-critical grade held (`security` A+, `tests_evals` A+, the other six A/B
exactly as last cycle). Overall stays **B** and the ship gate stays closed for the one unchanged
reason: `business_case_strength` is still **B** — no validated out-of-sample cost-net edge — and
this cycle's make-or-break research event is that the loop **TESTED its next standing candidate
(EXP-003, Politics) and the integrity gates correctly rejected it**, refuting the
bucket-calibration family on a **3rd** independent real per-category corpus.

**The make-or-break event this cycle (Research Run 20, 2026-07-12):** EXP-003 (Politics-category
calibration bucket) was tested for the first time on a real, leakage-safe **N=1,369** Politics
corpus (`tag_id=2`, the largest per-category corpus tested to date, via the same `GET
/tags/slug/<name>` → `--tag-id` lever proven on EXP-005). `CalibrationBucketStrategy` traded 472
trades, headline **+$28,815.49 OOS** — a number a naive read could mistake for a strong edge. **The
F10/F11 gates caught it, harder than EXP-005:** F11 `indistinguishable_from_zero` (95% CI
[-36648.21, 105232.67] spans 0 by a WIDER margin than EXP-005; hit_rate **25.64%**, starkly *below*
a coin flip) AND F10 **fragile** (134% of net PnL from one category bucket, 57% from ONE market;
leave-one-out on the top category flips the total to **-$9,665.99**). This is the discipline working
exactly as designed — a large plausible headline *caught and rejected*, not banked. The
bucket-calibration family (static + recency) is now **refuted/non-robust across 3 independent real
per-category corpora** — EXP-002 (all-cat, N=510), EXP-005 (Sports, N=814), and now EXP-003
(Politics, N=1,369). A new, structurally-different candidate (EXP-006, political price-reversal after
hype spikes) is logged but **not yet tested** (needs intraday-history infra the repo lacks). The
+$28,815.49 propagates into **no** revenue field — `weekly_pnl_paper` stays `null`, `arr_year1`
stays 0.

**What the factory shipped since 2026-07-11 (verified by fresh adversarial graders, not trusted):**

- **#314 (run-risk durability) — GENUINE.** A loss-cap AUTO-TRIP whose safety-state persist fails
  transiently now **fails CLOSED**: `_persist_state` marks `_safety_persist_pending` on failure
  (`execution.py:902-923`) and `_retry_pending_safety_persist()` re-attempts the write at the order
  gate (`:924-946`); `record_realized_pnl` halts the session if a realized loss can't be durably
  recorded (`:984-998`). Closes the durability hole the #281 fix (non-breach branch only) left open;
  regression test in the already-registered gate file is non-tautological (persist-pending assertions
  FAIL with the retry removed).
- **#322 (tests — false-coverage trap) — GENUINE.** `test_backend_auth_fastapi.py` registered in the
  blocking gate (`preflight.sh:120`), closing the #283 false-coverage trap for the auth adapter;
  verified to RUN and PASS (default-CLOSED dependency test passes, not skipped).
- **LLM safety hardening (`analyst.py`) + `test_llm_safety.py` (in the gate, `preflight.sh:108`) —
  GENUINE.** A hard 30s per-call timeout via ThreadPoolExecutor (`analyst.py:351`) and a spend cap
  that RAISES `LLMBudgetExceeded` fail-loud under a single lock *before* dispatch (`:76-92`, `:262`),
  explicitly re-raised rather than swallowed by the generic `except Exception → None` (`:363-365`).
  14 tests pass, non-tautological (timeout→None, cap-blocks, cap-accumulates, no-key no-accrual).
  A real cost/DoS-exhaustion hardening on the AI path.
- **#313 (security) — GENUINE.** `next` bumped 14.1.0 → 14.2.35 (`frontend/package.json:22`) for the
  Dec-11 RSC DoS advisory.
- **Margin evals (advisory) — GENUINE + correctly non-blocking.** A cost-per-outcome eval suite
  (`backend/evals/margin/`, `scripts/margin_eval.py`) + a CI-hermetic change-triggered runner that
  never fails CI — correctly kept OUT of the blocking integrity gate (`margin` absent from
  `preflight.sh`), so a non-deterministic advisory eval can't red-block a merge.

The only thing holding the overall at **B** and keeping the ship gate closed is unchanged:

- **business_case_strength = B (ship-critical — THE binding constraint):** still **no validated,
  out-of-sample, cost-net edge**. Revenue $0, the $104k/yr floor unmet (`BUSINESS_CASE.md:28-34`:
  `arr_year1` all 0, `floor_met_year1: false`; `GROWTH_STATUS.md`: `weekly_pnl_paper: null`,
  `weeks_validated_above_floor: 0`, `total_trades: 0`). This cycle's EXP-003 test (N=1,369) produced
  a fragile, statistically-insignificant, sub-chance-hit-rate result — a **real negative**, now the
  3rd refutation of the bucket-calibration family across real corpora. Honest and well-disciplined,
  but by the rubric an unrealized (honest) case is a **B**; A requires a demonstrated cost-net OOS
  edge that clears F10/F11. (Issue #79, refreshed.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. The
walk-forward engine reproduces bit-identically (two runs this cycle: `seed 42 / hash
b3a8d5e0e9579853`, PnL 910,880.71, sha256-identical outputs; SYNTHETIC demo labeled "NOT a validated
edge"). The leak guard is STRUCTURAL (`MarketView` omits outcome/resolution_time,
`walk_forward.py:116-128`; train strictly `< w_start`, `:402`; all history fetchers RAISE rather than
fabricate a decision price). The #259 STRUCTURAL guardrail still bars play-money PnL from the
real-money floor (`validate_real_oos.py:53`). Every positive-looking research number is explicitly
annotated fragile/insignificant/unwired and reaches no revenue field.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Runtime harness E2E PASSED (paper order FILLED, deterministic exposure 10.000000==10.000000, live gate REJECTS, kill switch + max-position + loss-cap all trip). `orchestrator.py`/`strategies.py` unchanged since last grade (no diff); real `PolymarketClient` feed, no stubbed stage on the paper path. Below A+: multi-leg/basket arb (`outcome_idx<0`) still honestly SKIPPED from paper ("per-leg execution not yet built"). |
| backtest_integrity | A | ✅ | **Independently re-reproduced this cycle: two `run_walk_forward.py` runs → seed_hash b3a8d5e0e9579853, PnL 910,880.71, sha256-IDENTICAL outputs; 76 gate tests pass.** Leak guard STRUCTURAL (`MarketView` omits outcome/resolution_time `walk_forward.py:116-128`; train `< w_start` `:402`; fetchers RAISE `polymarket_history_fetcher.py:388`, `kalshi_history_fetcher.py:384`). F10/F11 gates exist, wired, tested, and demonstrably rejected EXP-003's +$28,815.49 headline. Below A+: only SYNTHETIC reproduces offline (real N=510/814/1,369 corpora NOT committed — egress-gated, results negative); `DEFAULT_IMPACT_COEFF=0.5` an explicit uncalibrated placeholder (`cost_model.py:38-44`). |
| correctness_reliability | A | ✅ | Determinism verified (harness exposureA==exposureB; walk-forward identical hash). **NEW LLM safety hardening verified GENUINE** (fail-loud `LLMBudgetExceeded` under lock `analyst.py:76-92`; 30s hard timeout `:351`; re-raised not swallowed `:363-365`; 14 tests pass in-gate). Below A+ (unchanged residual): `WalletBehaviorDivergence` still emits `confidence=self._compute_confidence(...)` decoupled from entry+edge (`advanced_strategies.py:1260,1289`) — but genuinely quarantined behind `ENABLE_UNVALIDATED_STRATEGIES` (default false, `orchestrator.py:1701,1719-1722`), off the live paper path, with a passing gating test. Residual in-tree, not a regression. |
| security | A+ | ✅ | Fresh secret scan clean (`git ls-files` env/secret/credential → only examples; `sk-`/`AKIA` grep empty; diff since 5233823 introduces no secret material — only proper Actions `${{ secrets.* }}` injection). Auth default-CLOSED + `hmac.compare_digest` (`auth_core.py:55`). Live gate un-flippable via body (`OrderRequest` has no live field; `live_trading_enabled` only READ, fail-closed at venue layer `execution.py:262-290`). **NEW: next 14.2.35 (Dec-11 RSC DoS advisory, #313) + LLM DoS/cost hardening (30s timeout + $20 spend cap).** No new hole. |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS, kill switch blocks, max-position rejects $900>$50, loss cap trips net-of-fees at −$41.20 vs −$10 + blocks subsequent orders. **#314 (loss-cap-auto-trip persist retry / fail-closed) verified GENUINE** (`execution.py:902-946,984-998`; halts if a realized loss can't be durably recorded so a restart can't reset the budget). HUMAN-CORE intact (ZERO `live_trading_enabled = True` assignments in `backend/app`; only READ). Below A+ (unchanged residual): LIVE kill-switch net-of-fee still rests on `DEFAULT_FEE_RATE` + fill==limit (`execution.py:394,406,557`) — acknowledged in-code, conservative (trips earlier not later), gated-OFF live path only. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:28-34`); seed hashes reproduce; scorecard parses (overall=B). EXP-003 Run 20 numbers match line-for-line across `GROWTH_STATUS.md` (16,178-183,242,407-411) and `RESEARCH_MEMORY.md` (2154,2184-2194,2248-2250) — 472 trades, +$28,815.49, CI [-36648.21,105232.67], hit_rate 25.64%, LOO −$9,665.99 — everywhere labeled "edge-not-proven". Below A+ (recurring nit): test collection drifted 1134→**1140 collected, 13 errors (all `No module named pandas`)** — direction understated/honest, never inflated; break the cycle by citing the curated preflight-green gate not the raw total. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, bucket-calibration family now refuted across **3** real corpora. EXP-003 (Politics, N=1,369) TESTED this cycle → 472 trades, +$28,815.49 headline but F11 indistinguishable_from_zero (CI spans 0, 25.64% hit-rate — below chance) + F10 fragile (LOO −$9,665.99, 57% PnL from one market). The +$28,815.49 reaches no revenue field. THE binding constraint (#79). |
| design_taste | A | — | Unchanged (no frontend UI diff since last grade — `git diff --stat 5233823 HEAD -- frontend/src` empty; only the next.js security bump + package-lock). Systemic null-honesty; charts real-data-fed with labeled axes; no fabricated-data screens. |
| tests_evals | A+ | — | Blocking gate GREEN. **NEW registrations verified to RUN + PASS (not skip):** `test_llm_safety.py` (`preflight.sh:108`, 14 pass, non-tautological) + `test_backend_auth_fastapi.py` (`preflight.sh:120`, closes #283 false-coverage trap, #322). Comprehensive in-gate integrity coverage: leakage, seed-hash determinism, loss caps, live gate, calibration, F10/F11. Margin evals correctly ADVISORY-only (absent from `preflight.sh`; CI-hermetic runner never red-blocks). Heavy-dep exclusions honestly documented (`preflight.sh:52-55`). |
| performance | A | — | No hot-path regression (only +39 additive O(1) durability guards in `execution.py` since last grade; `orchestrator`/`strategies` unchanged). Scan/execute hot loop O(1) per opp; walk_forward cold-path only. Proportionate for a personal paper bot. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-13
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests (incl. newly-registered test_llm_safety + test_backend_auth_fastapi) + safety + secrets + runtime harness + scorecard-parse + self-validation (12/12) + GTM-honesty all OK
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap ($900>$50) + per-trade cap + loss cap net-of-fees (-$41.20 vs -$10) + paper PnL, deterministic (exposureA==exposureB==10.000000)
    walk_forward_reproduces: true      # seed 42, seed_hash b3a8d5e0e9579853, total PnL 910,880.71 - two runs this cycle produced SHA256-IDENTICAL outputs (SYNTHETIC demo, labeled NOT a validated edge); 76 walk-forward/F10/F11/cost gate tests pass
    real_oos_probe: "EXP-003 (Politics-category bucket) TESTED this cycle (Research Run 20, 2026-07-12, tag_id=2, N=1,369 real leakage-safe records - the largest per-category corpus tested, via the GET /tags/slug/<name> -> --tag-id lever). CalibrationBucketStrategy traded 472 trades, headline +$28,815.49 OOS - but F11 verdict=indistinguishable_from_zero (95% CI [-36648.21, 105232.67] spans 0 by a WIDER margin than EXP-005; hit_rate 25.64% - starkly BELOW a coin flip) AND F10 fragile (134% of PnL from one category bucket, 57% from ONE market; leave-one-out on the top category flips the total to -$9,665.99). A NEGATIVE result correctly caught by the F10/F11 gates - the discipline working as designed. Bucket-calibration family now refuted/non-robust across 3 independent real per-category corpora (EXP-002 N=510, EXP-005 N=814, EXP-003 N=1,369). No edge banked; the +$28,815.49 reaches no revenue field. EXP-006 (political price-reversal) logged but NOT yet tested (needs intraday-history infra)."
    integrity_gates_exercised: "F11 bootstrap significance (bootstrap_oos_significance.py, seeded percentile CI, edge only when total_lo>0) and F10 leave-one-out fragility (regime_slice.py, fragile when removing top category leaves remaining<=0) both exist in code, are wired + tested, and demonstrably rejected EXP-003's +$28,815.49 headline. Not narrative - matches the recorded numbers across GROWTH_STATUS.md + RESEARCH_MEMORY.md."
    play_money_guardrail: "#259 STRUCTURAL - validate_real_oos.evaluate RAISES on any research_only=True (Manifold/play-money) record (validate_real_oos.py:53). Play-money PnL cannot reach the real-money floor."
    leak_guard: "STRUCTURAL - MarketView omits outcome/resolution_time (walk_forward.py:116-128); train=resolution_time<w_start strict (:402); all history fetchers RAISE rather than fabricate a decision-time price (polymarket_history_fetcher.py:388, kalshi_history_fetcher.py:384); research_only excluded from _seed_hash"
    new_fixes_verified: "#314 (loss-cap AUTO-TRIP persist retry / fail-closed - a realized loss that can't be durably recorded HALTS so a restart can't reset the loss budget; execution.py:902-946,984-998; non-tautological regression test), #322 (test_backend_auth_fastapi.py registered in the gate, closing the #283 false-coverage trap; runs+passes not skips), LLM safety hardening (fail-loud LLMBudgetExceeded under lock + 30s hard timeout in analyst.py; test_llm_safety.py in the gate, 14 pass), #313 (next 14.1.0->14.2.35, Dec-11 RSC DoS advisory) - all verified GENUINE by fresh adversarial graders"
    test_collection: "1140 collected, 13 errors (all `No module named pandas`) - the documented heavy-dep exclusions from the light gate (preflight.sh:52-55). Drifted +6 from last cycle's 1134 (new test files); direction honest/understated, never inflated. Cite the curated preflight-green gate rather than a raw total that drifts every cycle."
    ruff_correctness_gate: "clean - E9/F821/F811 pass (narrow --select; ~150 hygiene findings NOT enforced by design)"
    scorecard_gate: "NOT-READY (business_case_strength: B - ship-critical needs A/A+)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["multi-leg/basket arbitrage (outcome_idx<0) is honestly SKIPPED from paper execution ('per-leg execution not yet built'), so the arb strategies in the default set don't yet reach paper fills. Disclosed integrity, not a fake stage; caps below A+. (orchestrator.py/strategies.py unchanged since last grade.)"]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the real-OOS results are not reproducible from committed artifacts - the N=510/814/1,369 real corpora are NOT in the repo (only a 54-record synthetic sample fixture), so EXP-002/005/003's numbers depend on a live Gamma fetch and must be taken on documented faith. Only the SYNTHETIC engine reproduces offline (re-verified sha256-identical this cycle). Plus DEFAULT_IMPACT_COEFF=0.5 (cost_model.py:38-44) is an uncalibrated placeholder. Both honesty-preserving, not integrity failures; cap below A+. Caching a frozen real corpus + fitting impact_coeff to real book depth would close to A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["unchanged residual: WalletBehaviorDivergence still emits confidence=self._compute_confidence(...) (advanced_strategies.py:1260,1289) decoupled from the entry_price+edge units contract every other executing strategy uses - the same wrong-units bug class fixed elsewhere, one class-member unfixed. Genuinely quarantined behind ENABLE_UNVALIDATED_STRATEGIES (default false, orchestrator.py:1701,1719-1722), off the live paper path, with a passing gating test - so A not below, but it is the remaining A->A+ item. Pin it to gate_confidence(entry, edge) like the others."]
    - name: security
      grade: "A+"
      ship_critical: true
      top_gaps: []
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["unchanged residual: the LIVE kill-switch net-of-fee correctness still rests on a DEFAULT_FEE_RATE estimate and an assumed fill==limit price (execution.py:394,406,557) - acknowledged in-code ('prefer a real venue fee field when the response carries one'), conservative (caps trip EARLIER not later), gated-OFF live path only. #314 loss-cap-auto-trip durability landed this cycle. A non-zero residual on live fidelity; harmless while paper-only + gated off."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the reported test count drifted AGAIN (1107->1134->actual 1140, all 13 errors `No module named pandas`). Direction was understated/conservative and self-disclosed, never inflated. Break the cycle by citing the curated preflight-green gate instead of a raw collection total that changes every cycle as test files are added."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists - revenue $0, $104k/yr floor unmet. The bucket-calibration family (static + recency) is now REFUTED across 3 independent real per-category corpora incl. this cycle's EXP-003 (N=1,369 Politics, tag_id=2): 472 trades, +$28,815.49 headline but F11 indistinguishable_from_zero (CI [-36648.21, 105232.67] spans 0, hit_rate 25.64% - below chance) + F10 fragile (leave-one-out -$9,665.99, 57% PnL from one market). Honest but unproven (THE binding constraint, #79). A validated edge requires a NEW pre-registered MECHANISM (NOT another bucket-calibration parameterization - that family is exhausted) whose OOS walk_forward PnL has an F11 CI EXCLUDING zero, F10 non-fragile (leave-one-out stays positive), hit-rate meaningfully >50%, sustained several consecutive OOS weeks above the $2k/wk floor with sufficient N. Candidate EXP-006 (political price-reversal after hype spikes) is logged but needs intraday-history infra the repo lacks."]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: []
    - name: tests_evals
      grade: "A+"
      ship_critical: false
      top_gaps: []
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) - cold backtest path only, low stakes."]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge - revenue $0, $104k/yr floor unmet. The bucket-calibration family is now REFUTED across 3 independent real per-category corpora: EXP-002 (N=510), EXP-005 (Sports N=814), and this cycle's EXP-003 (Politics N=1,369) - 472 trades, +$28,815.49 headline that the F10/F11 gates correctly rejected (indistinguishable_from_zero, CI spans 0, hit_rate 25.64% below chance; fragile, leave-one-out -$9,665.99). THE binding constraint. Next: a NEW pre-registered MECHANISM (not another bucket parameterization - the family is exhausted) that survives walk_forward + F10 (non-fragile) + F11 (CI excludes 0) cost-net on a real point-in-time non-survivorship panel above the floor. EXP-006 (political price-reversal) logged but needs intraday-history infra. (Issue #79, egress/owner-gated.)"
    - "correctness_reliability (A->A+): pin WalletBehaviorDivergence.confidence to the reconstructed win-probability (entry_price+edge / gate_confidence) instead of _compute_confidence(...) (advanced_strategies.py:1260,1289) - the last executing strategy still gating on the wrong quantity, currently quarantined behind ENABLE_UNVALIDATED_STRATEGIES. Same bug class as #263/#268/#275/#280/#284."
    - "backtest_integrity (A->A+): cache a frozen real resolved-market corpus into the repo so a real (not just synthetic) OOS result reproduces offline from committed artifacts, and calibrate the market-impact/capacity term against real order-book depth (cost_model.py:38-44) rather than the DEFAULT_IMPACT_COEFF=0.5 placeholder."
    - "run_risk_readiness (A->A+): make the LIVE kill-switch net-of a REAL venue fee/fill field when the venue response carries one, rather than the DEFAULT_FEE_RATE + fill==limit estimate (execution.py:394,406,557), so a hard loss cap can't undercount true live cash loss."
    - "artifact_integrity (keep-at-A): stop the recurring test-count drift (now 1140/13-all-pandas) by citing the curated preflight-green gate in docs rather than a raw collection total that changes every cycle."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is now refuted across **3** independent real
per-category corpora, and this cycle's EXP-003 candidate — tested at N=1,369 — was correctly
rejected by the F10/F11 gates as fragile and statistically indistinguishable from zero, with a
sub-chance 25.64% hit rate) — so the quality gate fails, and independently the full
`preflight.sh` is honest-RED (`floor_met_year1: false`, DoD boxes unchecked). This is the
project's core discipline working exactly as designed: **never let a number that isn't real
drive a decision, and never claim an edge you cannot reproduce out-of-sample.** This cycle the
factory shipped real, verified progress on the non-binding dimensions — loss-cap-auto-trip
durability (#314), auth-adapter gate coverage (#322), fail-loud LLM cost/timeout hardening, and
a next.js security bump (#313) — and the research loop tested its next standing candidate to a
**negative** result. The one remaining ship-critical gap is correctly, honestly open.
