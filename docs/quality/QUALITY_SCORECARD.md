# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-11 — overall `B`. Ship gate: NOT met.**

A genuinely **improved** cycle since 2026-07-09 (26 commits), re-verified by fresh,
independent, adversarial per-dimension graders (none the maker). **Two ship-critical dimensions
crossed a threshold UPWARD — `security` A→A+ and `tests_evals` A→A+** — because the factory
closed the exact gate-coverage gaps the last scorecard named, and each fix was verified to
genuinely *run* (not skip) and to *fail against pre-fix code*. Four named A→A+ gaps closed in
all. Overall stays **B** and the ship gate stays closed for one unchanged reason:
`business_case_strength` is still **B** — no validated out-of-sample cost-net edge — and this
cycle's make-or-break event is that the research loop **finally TESTED** the last standing
alpha candidate and the integrity machinery **correctly rejected it**.

**The make-or-break event this cycle (Research Run 19, 2026-07-11):** EXP-005 (Sports-category
calibration bucket) was tested for the first time on a real, leakage-safe **N=814** Sports
corpus (`tag_id=1`, resolved via `GET /tags/slug/sports` — more than double the ~300-400 floor
in one pre-registered run, no code change). `CalibrationBucketStrategy` finally traded — 268
trades, headline **+$16,993.97 OOS** — a number a naive read could mistake for an edge. **The
F10/F11 gates caught it:** F11 `indistinguishable_from_zero` (95% CI [-17164.66, 49793.75]
spans 0; hit_rate 49.25%, at/below a coin flip) AND F10 **fragile** (125% of net PnL from one
category bucket, leave-one-out on the top category flips the total to **-$4,319.43**). This is
the discipline working exactly as designed — a plausible headline *caught and rejected*, not
shipped. EXP-005 is now genuinely TESTED (not insufficient-data) and the answer is negative;
the bucket-calibration family is now **refuted/non-robust on 3+ independent real corpora**
(EXP-002, the 4th-run HuggingFace/recency test, and now EXP-005). The +$16,993.97 propagates
into **no** revenue field — `weekly_pnl_paper` stays `null`, `arr_year1` stays 0.

**What the factory closed since 2026-07-09 (verified by fresh adversarial graders, not trusted):**

- **#284 (correctness — the prior A→A+ gap) — GENUINE + CLOSED.** `NOPositionScanner.confidence`
  is now pinned to the units contract: `advanced_strategies.py:277`,
  `confidence=gate_confidence(no_price, estimate.edge)` (= `clip(entry+edge,0,1)`,
  `polymarket_client.py:161`), replacing the `min(adjusted_rate*2, 0.95)` **gate-bypass** that
  lifted a sub-0.5-win-probability longshot above `min_confidence`. Non-tautological: a grader
  reverted the pin and ran the gate tests → **3 failed** (`whale_copy/BUY: confidence 0.9 !=
  clip(entry+edge) 0.65`), restored clean.
- **#280 (correctness — Weather + Whale) — GENUINE.** The two remaining executing strategies are
  likewise pinned (`strategies.py:182,1216`); `test_confidence_units_gated.py` fails pre-fix.
- **#283 (security / tests — the prior A→A+ gate-coverage gap) — GENUINE + CLOSED.**
  `test_security_headers.py` is registered in the blocking gate (`preflight.sh:119`) **and**
  #283 added `fastapi`+`httpx` to `backend/requirements-ci.txt` so it actually RUNS — a second
  review round caught that a bare `importorskip` would SKIP in 100% of CI. Verified:
  `pytest test_security_headers.py` → **3 passed** (not skipped).
- **#298 (tests) — GENUINE.** Registered `test_loss_cap_persist_failclosed.py` +
  `test_confidence_units_gated.py` into the blocking gate (`preflight.sh:122-123`), honestly
  noting #280's own commit had mis-claimed gate registration.
- **#281 (run-risk durability) — GENUINE.** A realized loss that cannot be durably persisted now
  **fails CLOSED** (`activate_kill_switch("loss-persist failure")`), so a restart cannot reset
  the loss cap; `test_loss_cap_persist_failclosed.py` proves it with a `_FailingSaveStore` plus
  profit/breakeven/no-store negative controls (in the gate).
- **#297 (run-risk) — GENUINE.** The circuit-breaker cooldown now honors its full wall-clock
  duration across the UTC day-roll (`_reset_daily_if_needed` no longer clears the breaker;
  `risk_manager.py:262`), tested for both survival and non-stranding.
- **#295/#294 (research tooling) — GENUINE.** `validate_real_oos.py --tag-id` threads an integer
  Gamma category filter — the lever Run 19 used to reach N=814.

The only thing holding the overall at **B** and keeping the ship gate closed is unchanged:

- **business_case_strength = B (ship-critical — THE binding constraint):** still **no validated,
  out-of-sample, cost-net edge**. Revenue $0, the $104k/yr floor unmet (`BUSINESS_CASE.md:28-46`:
  `arr_year1` all 0, `floor_met_year1: false`; `GROWTH_STATUS.md`: `weekly_pnl_paper: null`, all
  `go_live.criteria` false, `status: not_ready`). This cycle's EXP-005 test (N=814) produced a
  fragile, statistically-insignificant result — a **real negative**, joining the refuted
  bucket-calibration family across three real corpora. Honest and well-disciplined, but by the
  rubric an unrealized (honest) case is a **B**; A requires a demonstrated cost-net OOS edge that
  clears F10/F11. (Issue #79, refreshed.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. The #259
STRUCTURAL guardrail was independently re-exercised: `validate_real_oos.evaluate` **raises** on
any `research_only=True` (play-money/Manifold) record (`validate_real_oos.py:51-55`,
`test_validate_real_oos.py:122-140`), so play-money PnL is barred from the real-money floor.
Every positive-looking research number is explicitly annotated fragile/insignificant/unwired.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Runtime harness E2E PASSED (paper order FILLED, deterministic exposure 10.000000==10.000000, live gate REJECTS, kill switch + max-position + loss-cap all trip). Full chain wired scan→DQ→risk→Kelly→multi-leg-skip→dedup→executor→persist (`orchestrator.py:881-1114`); real `PolymarketClient` feed, no synthetic data on the paper path, missing volume honestly neutralized not fabricated (`strategies.py:1400-1425`). Below A+: multi-leg/basket arb (`outcome_idx<0`) still honestly SKIPPED from paper ("per-leg execution not yet built, B1" — `orchestrator.py:1013-1032`). |
| backtest_integrity | A | ✅ | Reproduces bit-identically (re-run this cycle: `seed 42 / hash b3a8d5e0e9579853`, PnL 910,880.71, labeled SYNTHETIC "NOT a validated edge"). Leak guard STRUCTURAL: `MarketView` omits outcome+resolution_time (`walk_forward.py:116-129`); train = `resolution_time < w_start` strict (`:402`); all 3 fetchers RAISE rather than fabricate a decision price. **#286 RNG-seed fix verified non-tautological** (seed=42 reproduces, seed=999 diverges). **F10/F11 gates exist in code and demonstrably rejected EXP-005's +$16,993.97 headline** (`bootstrap_oos_significance.py:161`, `regime_slice.py:315-323`). Below A+: only SYNTHETIC reproduces offline (the N=814 real corpus is NOT committed — must be taken on documented faith); `DEFAULT_IMPACT_COEFF=0.5` still an uncalibrated placeholder (`cost_model.py:44`). |
| correctness_reliability | A | ✅ | Determinism verified (harness exposureA==exposureB; walk-forward identical hash). **#284 (the prior A→A+ gap: NOPositionScanner confidence) CLOSED + non-tautological** (grader reverted the pin → 3 tests fail); #280 pins Weather+Whale; `gate_confidence` is div-by-zero/NaN-safe. Below A+ (NEW residual): **`WalletBehaviorDivergence` was missed** by the #280 sweep — `advanced_strategies.py:1289` still emits `confidence=self._compute_confidence(...)`, a whale-count/accuracy/divergence blend fully decoupled from `entry_price+edge`, on a single-outcome executing `ScanResult`, added to the scanner under `ENABLE_UNVALIDATED_STRATEGIES` (`orchestrator.py:1722`) — the identical wrong-units bug class, one class-member unfixed. Non-blocking (gated off the default paper hot path). |
| security | A+ | ✅ | **UPGRADED A→A+.** The prior gate-coverage gap is CLOSED: `test_security_headers.py` runs in the required gate (`preflight.sh:119` + fastapi/httpx in `requirements-ci.txt`) → 3 passed (not skipped). Fresh secret scan clean (`git ls-files` → only `.env.example`; `sk-`/`AKIA` grep empty; `backend/.env.example` #300 vars are empty placeholders). Auth default-CLOSED + `hmac.compare_digest` (`auth_core.py:57`). Live gate un-flippable via body (`OrderRequest` has no live field; `live_trading_enabled` only READ). No new leak/hole found. |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS, kill switch blocks, max-position rejects $900>$50, loss cap trips net-of-fees at −$41.20 vs −$10. **#281 (loss-persist fail-closed) + #297 (circuit-breaker cooldown across UTC day-roll) both verified GENUINE + non-tautological.** HUMAN-CORE intact (zero `live_trading_enabled = True` assignments in `backend/app`; only READ). Real `render.yaml` (secrets `sync:false`). Below A+: the LIVE kill-switch net-of-fee correctness still rests on a `DEFAULT_FEE_RATE` estimate + assumed fill==limit price (`execution.py:395,406,557`) — the code itself concedes it should prefer a real venue fee field; harmless while paper-only + gated off. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:28-46`); seed hashes reproduce; scorecard parses (overall=B); commits honestly describe diffs (bookkeeping touches only docs). EXP-005 Run 19 numbers match line-for-line across `GROWTH_STATUS.md:286-290` and `RESEARCH_MEMORY.md:2022-2036`, everywhere labeled "NOT a validated edge"; #259 guardrail real + exercised. Below A+ (recurring): the prior scorecard's "1107 collected / 14 errors (13 pandas + 1 fastapi)" is now **stale** — true current is **1134 collected, 13 errors, all `No module named pandas`** (the fastapi error resolved with #283). Direction was conservative/understated, never inflated; corrected here by citing the curated-green gate instead of the drifting raw total. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, bucket-calibration family refuted across 3+ real corpora. EXP-005 (N=814) TESTED this cycle → 268 trades, +$16,993.97 headline but F11 indistinguishable_from_zero (CI spans 0, 49.25% hit-rate) + F10 fragile (leave-one-out −$4,319.43). The +$16,993.97 reaches no revenue field. THE binding constraint (#79). |
| design_taste | A | — | Unchanged (no frontend diff since 2026-07-09; `git diff --stat 44c4a4c HEAD -- frontend/` empty). Systemic null-honesty; charts real-data-fed with labeled axes; no fabricated-data screens. |
| tests_evals | A+ | — | **UPGRADED A→A+.** The prior gate-coverage gap is CLOSED: security-headers + loss-persist + confidence-units-gated suites now in the blocking gate (`preflight.sh:119-123`), each verified to RUN and to FAIL against pre-fix code (non-tautological). Comprehensive in-gate integrity coverage: leakage (`test_walk_forward_pm.py`), seed-hash determinism, loss caps, live gate, calibration, F10/F11 significance+fragility. 13 pandas exclusions honestly documented (`preflight.sh:52-55`). |
| performance | A | — | No hot-path regression (execution/strategies diffs since last grade are +45 lines of additive O(1) per-order safety/units guards). Scan/execute hot loop O(1) per opp; walk_forward cold-path only. Proportionate for a personal paper bot. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-11
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests (incl. newly-registered security-header + loss-persist + confidence-units-gated) + safety + secrets + runtime harness + scorecard-parse + self-validation + GTM-honesty all OK
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap ($900>$50) + per-trade cap + loss cap net-of-fees (-$41.20 vs -$10) + paper PnL, deterministic (exposureA==exposureB==10.000000)
    walk_forward_reproduces: true      # seed 42, seed_hash b3a8d5e0e9579853, total PnL 910,880.71 identical across two runs this cycle (SYNTHETIC demo, labeled NOT a validated edge); #286 RNG-seed fix verified (seed=42 reproduces, seed=999 diverges)
    real_oos_probe: "EXP-005 (Sports-category bucket) FINALLY TESTED this cycle (Research Run 19, tag_id=1, N=814 real leakage-safe records - more than double the ~300-400 floor in one pre-registered run, no code change). CalibrationBucketStrategy traded 268 trades, headline +$16,993.97 OOS - but F11 verdict=indistinguishable_from_zero (95% CI [-17164.66, 49793.75] spans 0; hit_rate 49.25%) AND F10 fragile (125% of PnL from one category bucket; leave-one-out on the top category flips the total to -$4,319.43). A NEGATIVE result correctly caught by the F10/F11 gates - the discipline working as designed. Bucket-calibration family now refuted/non-robust across 3+ real corpora. No edge banked; the +$16,993.97 reaches no revenue field."
    integrity_gates_exercised: "F11 bootstrap significance (bootstrap_oos_significance.py:161, seeded percentile CI, edge only when total_lo>0) and F10 leave-one-out fragility (regime_slice.py:315-323, fragile when removing top category leaves remaining<=0) both exist in code and demonstrably rejected EXP-005's +$16,993.97 headline. Not narrative - matches the recorded numbers."
    play_money_guardrail: "#259 STRUCTURAL - validate_real_oos.evaluate RAISES on any research_only=True (Manifold/play-money) record (validate_real_oos.py:51-55; test_validate_real_oos.py:122-140). Play-money PnL cannot reach the real-money floor."
    leak_guard: "STRUCTURAL - MarketView omits outcome/resolution_time (walk_forward.py:116-129); train=resolution_time<w_start strict (:402); all 3 history fetchers RAISE rather than fabricate a decision-time price (polymarket:388, kalshi:384, manifold:215); research_only excluded from _seed_hash"
    new_fixes_verified: "#284 (NOPositionScanner confidence pinned to units contract - the prior correctness A->A+ gap, CLOSED, grader reverted->3 tests fail), #280 (Weather+Whale confidence pinned), #283 (security-header test now RUNS in the required gate, +fastapi/httpx to requirements-ci.txt, 3 passed not skipped - the prior security/tests A->A+ gap, CLOSED), #298 (loss-persist + confidence-units-gated registered in gate), #281 (realized-loss-persist fails CLOSED so a restart can't reset the loss cap), #297 (circuit-breaker cooldown honors full duration across UTC day-roll) - all verified GENUINE + non-tautological"
    test_collection: "1134 collected, 13 errors (all `No module named pandas`) - the documented heavy-dep exclusions from the light gate; the prior fastapi/test_security_headers.py error is RESOLVED (#283). Corrected from the prior scorecard's stale '1107/14'. To break the recurring drift, cite the curated preflight-green gate rather than a raw total."
    ruff_correctness_gate: "clean - E9/F821/F811 pass (narrow --select; ~150 hygiene findings NOT enforced by design)"
    scorecard_gate: "NOT-READY (business_case_strength: B - ship-critical needs A/A+)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["multi-leg/basket arbitrage (outcome_idx<0) is honestly SKIPPED from paper execution ('per-leg execution not yet built, B1' - orchestrator.py:1013-1032), so the arb strategies in the default set don't yet reach paper fills. Disclosed integrity, not a fake stage; caps below A+."]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the make-or-break real-OOS result is not reproducible from committed artifacts - the N=814 Sports corpus is NOT in the repo (only an 11KB sample fixture), so EXP-005's numbers depend on a live Gamma fetch and must be taken on documented faith. Only the SYNTHETIC engine reproduces offline. Plus DEFAULT_IMPACT_COEFF=0.5 (cost_model.py:44) is an uncalibrated placeholder. Both honesty-preserving, not integrity failures; cap below A+. Caching a frozen real corpus + fitting impact_coeff to real book depth would close to A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["NEW residual: WalletBehaviorDivergence was MISSED by the #280 units-contract sweep - advanced_strategies.py:1289 still emits confidence=self._compute_confidence(...) (a whale-count/accuracy/divergence blend, _compute_confidence:1158) decoupled from entry_price+edge, on a single-outcome executing ScanResult, added to the scanner under ENABLE_UNVALIDATED_STRATEGIES (orchestrator.py:1722) - the identical wrong-units bug class #263/#268/#275/#280/#284 fixed elsewhere, one class-member unfixed. Non-blocking (gated off the default paper hot path), so A not below; but it is the remaining A->A+ item. #284 (the prior A->A+ gap on NOPositionScanner) is CLOSED."]
    - name: security
      grade: "A+"
      ship_critical: true
      top_gaps: []
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["the LIVE kill-switch net-of-fee correctness still rests on a DEFAULT_FEE_RATE estimate and an assumed fill==limit price (execution.py:395,406,557) - the code itself concedes it should prefer a real venue fee field when the venue response carries one. A real venue fee/fill above the 2%/limit assumption would let the hard loss cap undercount true cash loss and trip late on live. Harmless while paper-only + gated off; #281/#297 durability fixes landed this cycle. A non-zero residual on live fidelity."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the reported test count drifted AGAIN (894->1040->1107->actual 1134) and the prior 'all 13/14 errors incl. fastapi' claim is now wrong (the fastapi error resolved with #283; true is 1134/13-all-pandas). Corrected in this scorecard; direction was understated/conservative and self-disclosed, never inflated. Break the cycle by citing the curated preflight-green gate instead of a raw collection total that drifts every cycle."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists - revenue $0, $104k/yr floor unmet. The bucket-calibration family (static + recency) is now REFUTED across 3+ real corpora incl. this cycle's EXP-005 (N=814 Sports, tag_id=1): 268 trades, +$16,993.97 headline but F11 indistinguishable_from_zero (CI [-17164.66, 49793.75] spans 0, hit_rate 49.25%) + F10 fragile (leave-one-out -$4,319.43). Honest but unproven (THE binding constraint, #79). A validated edge requires a NEW pre-registered mechanism (NOT another bucket-calibration parameterization) whose OOS walk_forward PnL has an F11 CI EXCLUDING zero, F10 non-fragile (leave-one-out stays positive), hit-rate meaningfully >50%, sustained several consecutive OOS weeks above the $2k/wk floor with sufficient N. Reusable lever proven this cycle: resolve a category's real Gamma tag_id via GET /tags/slug/<name> then pass --tag-id to validate_real_oos.py (directly applicable to EXP-003 politics next)."]
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
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge - revenue $0, $104k/yr floor unmet. The bucket-calibration family is now REFUTED across 3+ real corpora: EXP-005 (Sports, N=814) TESTED this cycle produced +$16,993.97 headline that the F10/F11 gates correctly rejected (indistinguishable_from_zero, CI spans 0, hit_rate 49.25%; fragile, leave-one-out -$4,319.43). THE binding constraint. Next: a NEW pre-registered MECHANISM (not another bucket parameterization - the family is exhausted) that survives walk_forward + F10 (non-fragile) + F11 (CI excludes 0) cost-net on a real point-in-time non-survivorship panel above the floor. Reusable lever: GET /tags/slug/<name> -> --tag-id (apply to EXP-003 politics). (Issue #79, egress/owner-gated.)"
    - "correctness_reliability (A->A+): pin WalletBehaviorDivergence.confidence to the reconstructed win-probability (entry_price+edge) instead of _compute_confidence(...) (advanced_strategies.py:1289) - the LAST executing strategy still gating on the wrong quantity, missed by the #280 units-contract sweep (added to the scanner under ENABLE_UNVALIDATED_STRATEGIES). Same bug class as #263/#268/#275/#280/#284; #284 closed the NOPositionScanner instance."
    - "backtest_integrity (A->A+): cache a frozen real resolved-market corpus into the repo so a real (not just synthetic) OOS result reproduces offline from committed artifacts, and calibrate the market-impact/capacity term against real order-book depth (cost_model.py:44) rather than the DEFAULT_IMPACT_COEFF=0.5 placeholder."
    - "run_risk_readiness (A->A+): make the LIVE kill-switch net-of a REAL venue fee/fill field when the venue response carries one, rather than the DEFAULT_FEE_RATE + fill==limit estimate (execution.py:395,406,557), so a hard loss cap can't undercount true live cash loss."
    - "artifact_integrity (keep-at-A): stop the recurring test-count drift (now 1134/13-all-pandas) by citing the curated preflight-green gate in docs rather than a raw collection total that changes every cycle."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is refuted across 3+ real corpora, and this cycle's
EXP-005 candidate — finally tested at N=814 — was correctly rejected by the F10/F11 gates as
fragile and statistically indistinguishable from zero) — so the quality gate fails, and
independently the full `preflight.sh` is honest-RED (`floor_met_year1: false`, DoD boxes
unchecked). This is the project's core discipline working exactly as designed: **never let a
number that isn't real drive a decision, and never claim an edge you cannot reproduce
out-of-sample.** This cycle the factory made real, verified progress — closing four named
A→A+ gaps (two of which lifted `security` and `tests_evals` to A+) plus loss-persist and
circuit-breaker durability fixes — and the research loop tested its last standing alpha
candidate honestly to a **negative** result. The one remaining ship-critical gap is correctly,
honestly open.
