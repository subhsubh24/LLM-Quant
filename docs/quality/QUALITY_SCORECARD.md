# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-09 — overall `B`. Ship gate: NOT met.**

A substantive **safety/correctness/units-contract hardening** cycle since 2026-07-07 (26
commits, ~3,500 LOC, +13 new test files). No ship-critical dimension crossed a grade
threshold, so the letters are unchanged — but the composition improved materially and was
re-verified by fresh, independent, adversarial per-dimension graders (none the maker):
**#253 genuinely CLOSED the prior correctness/run-risk A→A+ gap** (the SELL/partial-reduce
path now feeds the per-strategy drawdown circuit, not only the executor hard caps), and
several more safety fixes (#264 per-order cap, #272 live-fill venue-fee accounting, #260
short-open quarantine, #269 secret-value log hygiene, #265 security headers) landed and were
confirmed **non-tautological** (their tests fail against the pre-fix code). The research loop
ran two more real-data probes (Runs 16–17) to **no new edge** and honestly **corrected a prior
Manifold "softer crowd" overclaim downward**. The binding constraint is unchanged.

**What the factory closed since 2026-07-07 (verified by fresh adversarial graders, not trusted):**

- **#253 (correctness / run-risk — the prior A→A+ gap) — GENUINE + CLOSED.** The SELL/reduce
  branch now feeds realized PnL to the per-strategy drawdown circuit
  (`execution.py:1219-1227`, `risk_manager.record_pnl(pos.strategy, pnl)`; wired via
  `orchestrator.py:640`). Non-tautological: pre-#253 (`git show 41ab6da^`) had **0**
  `record_pnl` call sites in the reduce path; HEAD has 3. `test_sell_reduce_drawdown.py`
  asserts a strategy bleeding on reduces ALONE now lands in `rm._disabled_strategies` —
  structurally impossible pre-fix. No double-count: reduce shrinks `pos.size` first, the
  remainder settles via MTM later — disjoint portions, each `record_pnl`'d once.
- **#264 (per-order MAX_PER_TRADE_USD ceiling) — GENUINE.** `execution.py:1051` rejects
  `notional > max_per_trade_usd` *before* the max-position check (tighter bound wins), $5
  fail-loud fallback. `test_max_per_trade_cap.py:43` fills-blocks an order under the $50
  position cap but over the $5 per-trade cap — would have FILLED pre-fix.
- **#272 (live fills charge the venue fee) — GENUINE + conservatively signed.** Both live
  paths set `fees = filled_size*price*DEFAULT_FEE_RATE` (`execution.py:406,557`), the same
  rate paper already charged; the close nets it into `record_realized_pnl` so hard loss caps
  trip **earlier**, never later. Paper path (`_simulate_fill`) untouched → determinism intact.
- **#260 (BUY-on-short quarantine) — GENUINE.** `execution.py:1016-1029` rejects a BUY on a
  token holding a legacy `side="short"` row (`logger.critical`), closing a loss-cap-bypass
  (`test_short_open_rejected.py:67`).
- **#269 (boot-error secret-value log hygiene) — GENUINE + gated.** `config.py:253-262`
  re-raises with `errors(include_input=False)` + `from None`, so no `input_value={...}`
  (holding token/key values) reaches the logs; only var *names* are named
  (`test_config_safety.py:117-149`, in the blocking gate). Fails pre-fix (pydantic v2
  `ValidationError` isn't a `ValueError`, so the old `raises(ValueError)` wouldn't catch).
- **#265 (security headers + /health info-hygiene) — GENUINE.** nosniff / X-Frame-Options
  DENY / Referrer-Policy / HSTS via non-clobbering `setdefault`; `/health` no longer leaks
  `live_trading_enabled` (recon-probe closed).
- **#263/#268/#275 (units-contract: edge/confidence in absolute probability units)** —
  behavioral flips, not renames. A 0.40-fair-value cross-market BUY now sizes to **$0**
  (gated) where the pre-fix hardcoded `confidence=0.85` bypassed the gate
  (`test_confidence_units.py:147-170`).

The only thing holding the overall at **B** and keeping the ship gate closed is unchanged:

- **business_case_strength = B (ship-critical, unchanged — THE binding constraint):**
  still **no validated, out-of-sample, cost-net edge**. Revenue $0, the $104k/yr floor
  unmet (`BUSINESS_CASE.md:28-46`: `arr_year1` all 0, `floor_met_year1: false`;
  `GROWTH_STATUS.md`: `weekly_pnl_paper: null`, all 10 `go_live.criteria` false). The
  bucket-calibration family (EXP-002/B4a static + recency) remains **REFUTED across four real
  corpora**. This cycle's EXP-005 (Sports-category bucket, motivated by B9's worst-ECE
  finding) ran on real leakage-safe data and **abstained on sub-floor N** — 134–135 Sports
  markets vs. `min_bucket_n=30`×10 buckets required; the mechanism made **0 trades**, F11
  `verdict: insufficient_data` (an honest zero, NOT a measured negative). Run 17 replicated
  N≈135 across three pulls and sharpened the diagnosis to a `volumeNum` sampling-axis ceiling
  (a fetcher-design gap, not an edge). The prior "materially softer Manifold crowd" framing
  was **corrected downward** to "less-pinned research corpus, not a proven beatable crowd."
  No edge banked, no floor number moved. (Issue #79.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. The
#259 STRUCTURAL guardrail was independently exercised: `validate_real_oos.evaluate` **raises**
on any `research_only=True` (play-money/Manifold) record, so play-money PnL is barred from the
real-money floor. Every positive-looking research number is explicitly annotated as
noise/insufficient/unwired and left **unwired**.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Runtime harness E2E PASSED (paper order FILLED, deterministic exposure 10.000000==10.000000). No fabricated data feeds the paper path (`polymarket_client.py:87-107` flags-only, real value stays honest 0). Full chain wired scan→DQ→risk→Kelly→dedup→executor→persist (`orchestrator.py:896-1128`). Manifold is structurally research-only (`manifold_history_fetcher.py:227`). Below A+: multi-leg/basket arb (`outcome_idx<0`) honestly skipped from paper ("per-leg execution not yet built, B1" — `orchestrator.py:1013-1032`). |
| backtest_integrity | A | ✅ | Reproduces bit-identically (`seed 42 / hash b3a8d5e0e9579853`, PnL 910,880.71, labeled SYNTHETIC "NOT a validated edge"). Leak guard STRUCTURAL: `MarketView` omits outcome+resolution_time (`walk_forward.py:115-127`); train = `resolution_time < w_start` strict (`:385`); all three fetchers (incl. new manifold) RAISE rather than fabricate a decision price (`polymarket_history_fetcher.py:362`, `kalshi:384`, `manifold:215`). New `research_only` field excluded from `_seed_hash`. Below A+: only synthetic reproduces + `DEFAULT_IMPACT_COEFF=0.5` uncalibrated placeholder (`cost_model.py:44`). |
| correctness_reliability | A | ✅ | Determinism verified (harness exposureA==exposureB; walk-forward identical hash/PnL). **#253 (prior A→A+ gap) CLOSED + non-tautological**; 17 new units/reduce tests pass. Below A+ (new residual): **NOPositionScanner still emits `confidence=min(adjusted_rate*2.0, 0.95)` decoupled from entry+edge** (`advanced_strategies.py:265`) — an executing default-scan strategy gating on the wrong quantity, same bug class as #263/#268/#275 fixed elsewhere. |
| security | A | ✅ | Secret scan clean (no tracked `.env`, no secret-shaped assignments; venue creds from env only). Auth default-CLOSED (`auth.py:54-61` unset→401, `auth_core.py:36-41,55` fail-closed + `hmac.compare_digest`); all 12 mutating routes carry `_MUTATING_AUTH`. Live gate server-side, NOT body-flippable (`OrderRequest` has no live field). **#269/#265 genuine.** Below A+: `test_security_headers.py` (fastapi) is NOT in the light blocking gate — #265 hardening has zero regression coverage there. |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS, kill switch blocks, max-position rejects $900>$50, loss cap trips net-of-fees at −$41.20 vs −$10. **#264 per-order cap + #272 live-fill fee accounting + #253 drawdown wiring + #260 short quarantine all confirmed** (20 targeted tests pass). HUMAN-CORE intact (`live_trading_enabled` only ever READ, never assigned True). Real `render.yaml` (all secrets `sync:false`). Below A+: live kill-switch net-of-fee correctness rests on a `DEFAULT_FEE_RATE` *estimate* + assumed fill==limit price (`execution.py:395-406,557`) — a real venue fee/fill above assumption would trip the cap late on live. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:28-46`); seed hashes reproduce; DoD honestly unchecked; `check_scorecard.py`→parses (overall=B). Commits honestly describe diffs; bookkeeping commits touch only docs. #259 play-money guardrail structural + exercised. Below A+ (corrected this cycle): the prior scorecard's "1040 collected / 13 errors (all pandas)" is now **stale and incomplete** — actual is **1107 collected, 14 errors (13 pandas + 1 fastapi/`test_security_headers.py`)**. Direction was understated (conservative), never inflated, and self-disclosed — but corrected here. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, bucket-calibration family refuted across 4 real corpora, EXP-005 Sports abstained on sub-floor N (0 trades, `insufficient_data`), Manifold overclaim corrected down. THE binding constraint (#79). |
| design_taste | A | — | Unchanged (no frontend diff since 2026-07-07). Systemic null-honesty; charts real-data-fed with labeled axes; no fabricated-data screens. |
| tests_evals | A | — | Curated suite green via preflight (`preflight.sh code` → GREEN); +60 genuine new tests this cycle, verified non-tautological (`test_confidence_units.py`, `test_sell_reduce_drawdown.py` fail against pre-fix code). #270 registered the 4 light-path regression tests in the blocking gate (verified present). Below A+: `test_security_headers.py` can't collect (no fastapi in light gate) + is registered nowhere → #265's headers have no blocking-gate coverage. |
| performance | A | — | No hot-path regression this cycle (execution/orchestrator diffs are additive safety/units wiring). Scan/execute hot loop O(1) per opp; walk_forward O(windows×markets) cold-path only. Proportionate for a personal paper bot. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-09
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests + safety + secrets + runtime harness + scorecard-parse + self-validation + GTM-honesty all OK (CI skips full ruff by design)
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap + per-trade cap + loss cap net-of-fees (-$41.20 vs -$10) + paper PnL, deterministic (exposureA==exposureB==10.000000)
    walk_forward_reproduces: true      # seed 42, seed_hash b3a8d5e0e9579853, total PnL 910,880.71 identical across two runs this cycle (SYNTHETIC demo, labeled NOT a validated edge)
    real_oos_probe: "no new edge. EXP-005 (Sports-category bucket) ran on real leakage-safe data and ABSTAINED on sub-floor N (134-135 Sports markets vs min_bucket_n=30x10 required): 0 trades, F11 verdict=insufficient_data (an honest zero, NOT a measured negative). Run 17 replicated N~135 across 3 pulls, sharpened the diagnosis to a volumeNum sampling-axis ceiling. Bucket-calibration family still REFUTED across 4 real corpora. Manifold softer-crowd overclaim CORRECTED downward. No edge banked."
    play_money_guardrail: "#259 STRUCTURAL — validate_real_oos.evaluate RAISES on any research_only=True (Manifold/play-money) record; exercised directly by a grader (fires). Play-money PnL cannot reach the real-money floor."
    leak_guard: "STRUCTURAL — MarketView omits outcome/resolution_time (walk_forward.py:115-127); train=resolution_time<w_start strict (:385); all 3 history fetchers RAISE rather than fabricate a decision-time price (polymarket:362, kalshi:384, manifold:215); research_only excluded from _seed_hash"
    new_safety_fixes: "#253 (SELL/reduce feeds per-strategy drawdown circuit — the prior A->A+ gap, CLOSED), #264 (per-order MAX_PER_TRADE_USD ceiling), #272 (live fills charge venue fee so loss caps net it), #260 (BUY-on-short quarantine), #269 (boot-error secret-value log hygiene), #265 (security headers + /health hygiene), #263/#268/#275 (units-contract) — all verified GENUINE + non-tautological (tests fail against pre-fix code)"
    test_collection: "1107 collected, 14 errors (13 `No module named pandas` + 1 `No module named fastapi` on test_security_headers.py) — the documented heavy-dep exclusions from the light gate; corrected from the prior scorecard's stale '1040/13-all-pandas'"
    ruff_correctness_gate: "clean — E9/F821/F811 pass (narrow --select; ~150 hygiene findings NOT enforced by design)"
    scorecard_gate: "NOT-READY (business_case_strength: B — ship-critical needs A/A+)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["multi-leg/basket arbitrage (outcome_idx<0) is honestly SKIPPED from paper execution ('per-leg execution not yet built, B1' — orchestrator.py:1013-1032), so the arb strategies in the default set don't yet reach paper fills. Disclosed integrity, not a fake stage; caps below A+."]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["only a SYNTHETIC demo reproduces (no validated real OOS result exists yet) and the market-impact/capacity term is a self-admitted uncalibrated placeholder (cost_model.py:44, DEFAULT_IMPACT_COEFF=0.5 not fitted to real book depth). Both honesty-preserving, not integrity failures; cap below A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["NEW residual: NOPositionScanner still emits confidence=min(adjusted_rate*2.0, 0.95) decoupled from entry_price+edge (advanced_strategies.py:265) — an executing default-scan strategy whose min_confidence gate filters on the wrong quantity (same bug class as #263/#268/#275, which fixed only its EDGE units, not its confidence). #253 (the prior A->A+ gap) is CLOSED; this is the remaining A->A+ item."]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: ["test_security_headers.py requires fastapi and is NOT in the light blocking gate (registered nowhere) — the #265 header/hygiene hardening has zero regression coverage in the required CI gate. The load-bearing auth DECISION is still covered via the fastapi-free auth_core/test_backend_auth.py, so this is a defense-in-depth coverage hole, not an exploitable weakness; caps below A+."]
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["the LIVE kill-switch net-of-fee correctness rests on a DEFAULT_FEE_RATE estimate and an assumed fill==limit price (execution.py:395-406,557) — the code comment admits it should prefer a real venue fee field when present. A real venue fee/fill above the 2%/limit assumption would let the hard loss cap undercount true cash loss and trip late on live. Harmless while paper-only + gated off; a non-zero residual on live fidelity."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["the reported test count drifted again (894 -> 1040 -> actual 1107) and the prior 'all 13 errors are pandas' claim is now incomplete (there are 14; the 14th is fastapi/test_security_headers.py). Corrected in this scorecard; direction was understated/conservative and self-disclosed, never inflated. Keep the count synced with actual collection (or cite the curated-green subset instead of a raw total that drifts)."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists — revenue $0, $104k/yr floor unmet. The bucket-calibration family (static + recency) is REFUTED across 4 real corpora; EXP-005 (Sports-category bucket) ABSTAINED on sub-floor N (134-135 markets vs min_bucket_n=30x10; 0 trades, F11 insufficient_data — an honest zero, not a measured negative); Run 17 diagnosed a volumeNum sampling-axis fetch ceiling, not an edge; the Manifold softer-crowd claim was corrected DOWN. Honest but unproven (THE binding constraint, #79). A validated edge requires a NEW pre-registered hypothesis (min-N + OOS plan) surviving walk_forward + a passing B2 calibration gate cost-net on a real point-in-time non-survivorship panel, above the floor. Do NOT re-test the refuted bucket family; the honest next step is a fetcher redesign to break the volumeNum ceiling and reach testable N."]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: []
    - name: tests_evals
      grade: "A"
      ship_critical: false
      top_gaps: ["test_security_headers.py cannot collect in the light env (no fastapi) and is registered in no gate, so #265's security-header hardening has no blocking-gate regression coverage. Either vendor fastapi into the light gate, mark the test importorskip with a documented skip, or wire it into the full CI gate. (13 pandas exclusions remain honestly documented.)"]
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) — cold backtest path only, low stakes."]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — revenue $0, $104k/yr floor unmet. The sole non-crowd model_prob family (price-bucket calibration) is REFUTED across 4 real corpora, and EXP-005 (Sports bucket) ABSTAINED on sub-floor N (134-135 markets vs 30x10 required; 0 trades, F11 insufficient_data). THE binding constraint. Next: a NEW pre-registered hypothesis (min-N + OOS plan) that survives walk_forward + a passing B2 calibration gate on a real point-in-time non-survivorship panel, reported cost-net and reproducible above the $2k/wk floor. The honest immediate step is a fetcher redesign to break the volumeNum sampling ceiling and reach testable N. Do NOT re-test the refuted bucket family. (Issue #79, egress/owner-gated.)"
    - "correctness_reliability (A->A+): pin NOPositionScanner.confidence to the reconstructed win-probability (entry_price+edge, the #263/#268/#275 units contract) instead of min(adjusted_rate*2.0, 0.95) — an executing default-scan strategy currently gates on the wrong quantity (advanced_strategies.py:265)."
    - "security / tests_evals (A->A+): give the #265 security-header hardening real blocking-gate coverage — test_security_headers.py needs fastapi (absent from the light gate) and is registered nowhere, so a header/hygiene regression is invisible to required CI."
    - "run_risk_readiness (A->A+): make the LIVE kill-switch fee net-of a REAL venue fee/fill field when the venue response carries one, rather than the DEFAULT_FEE_RATE + fill==limit estimate (execution.py:395-406,557), so a hard loss cap can't undercount true live cash loss."
    - "backtest_integrity (A->A+): calibrate the market-impact/capacity term against real order-book depth (cost_model.py:44) so capacity/edge-survival claims rest on a fitted parameter rather than the impact_coeff=0.5 placeholder."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is refuted across four real corpora, and this
cycle's EXP-005 candidate abstained on sub-floor N) — so the quality gate fails, and
independently the full `preflight.sh` is honest-RED (`floor_met_year1: false`, DoD boxes
unchecked). This is the project's core discipline working exactly as designed: **never let a
number that isn't real drive a decision, and never claim an edge you cannot reproduce
out-of-sample.** This cycle the factory made real, verified safety/correctness progress
(closing the prior partial-reduce drawdown gap plus five more non-tautological fixes) and ran
two more real-data probes honestly to **no new edge**. The one remaining ship-critical gap is
correctly, honestly open.
