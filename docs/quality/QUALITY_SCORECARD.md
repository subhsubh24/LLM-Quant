# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-07 — overall `B`. Ship gate: NOT met.**

A small, honest **hardening** cycle since 2026-07-05. No ship-critical dimension crossed a
threshold, so the letters are unchanged — but the composition improved: **two more genuine
safety fixes landed and were verified non-tautological**, and the research loop ran another
real-data probe that produced **no new edge** (honest). The binding constraint is unchanged.

**What the factory closed since 2026-07-05 (verified by fresh adversarial graders, not trusted):**

- **#241 (D1 side-effect integrity) — genuine.** A 0-fill `OPEN` order (`is_success` is
  True for `OPEN`, `filled_size=0`) previously fabricated a **phantom `Position`** (size 0)
  that poisoned the orchestrator's `token_id in executor.positions` dedup, silently skipping
  every later *real* opportunity on that token (and persisting across restarts). The fix
  guards the position/fee mutation on an **actual fill** — `execution.py:1062`
  (`if result.is_success and result.filled_size > 0:`); the order is still recorded in
  `order_history`. Non-tautological tests: `test_live_gate_defense.py:368` (no phantom —
  `ex.positions == {}`), `:384` (downstream: a later real fill on the same token still
  creates a position), `:413` (control: a genuine fill is unaffected). Paper is untouched
  (`_simulate_fill` always returns `FILLED`, `filled_size>0`).
- **#242 (venue-credential boot gate) — genuine + fail-loud.** A live-enabled host missing
  the Polymarket order credentials would boot "fine" and then fail **every** real order at
  runtime (executor not authenticated). New `_require_venue_credentials_in_live` model
  validator (`config.py:183-215`) **refuses to boot** when `live_trading_enabled` and any of
  `POLYMARKET_API_KEY/_SECRET/_PASSPHRASE/_PRIVATE_KEY` is unset, naming the missing var —
  mirroring the control-auth boot gate. Gated on `if self.live_trading_enabled:` (live
  defaults **false**) so it can **never** bind paper/dev/CI. Real tests set/delete env vars
  and assert boot-time `ValidationError`, incl. a partial-credential case
  (`test_config_safety.py:49,62,71`). It **adds** a fail-loud check; it weakens nothing.
- **Artifact framing nit (prior #240) — addressed.** The four newest commits are honestly
  framed: `087cd27`/`f46de05`/`dfd27e2` are prefixed **"File ROADMAP"** and touch only
  `ROADMAP.md`/`loop-memory.md`; `33f2d6f` is **"chore: sync"** and touches only
  `FACTORY_STANDARD.md`. None masquerade as a shipped product feature — the prior git-log-
  readability nit is resolved.

The only thing holding the overall at **B** and keeping the ship gate closed is unchanged:

- **business_case_strength = B (ship-critical, unchanged — THE binding constraint):**
  still **no validated, out-of-sample, cost-net edge**. Revenue $0, the $104k/yr floor
  unmet. The bucket-calibration family (EXP-002/B4a, static + recency) remains **REFUTED
  across four real corpora** (CONFIRMED noise: −$2,938 @ n=510, +$3,330 @ n=799, −$2,947
  @ n=621, and an HF sample killed by its own F10 regime-slice as a crowd-pinned artifact).
  This cycle's B8 cross-venue-coherence work is a **data-feasibility probe, not an edge**:
  it pinned the exact remaining Kalshi data path (quotes live in the per-market
  `/orderbook` endpoint, not the list feed) but ran **no OOS backtest** and claims no result
  (`RESEARCH_MEMORY.md:22-33`, 3rd probe). The factory again refused to bank a curve-fit
  win — honest, but the edge is unproven. (Issue #79.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. Every
positive-looking research number is explicitly annotated as noise/fragile/non-robust and
left **unwired**.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Unchanged this cycle (no strategies/data-path diff). #165 fabrication fix intact: `_mark_unavailable_data` (`strategies.py:1377-1399`) sets `volume_unavailable`/`liquidity_unavailable` flags only, leaves volume/liquidity at honest 0 (grep confirms no `volume=10000`/`liquidity=5000`); filters neutralize on the flag (`polymarket_client.py:90-107`). Orchestrator wires scan→DQ→risk→Kelly→executor→persist; paper fills charge real cost-model slippage+fee. |
| backtest_integrity | A | ✅ | Reproduces bit-identically (`seed_hash b3a8d5e0e9579853`, PnL 910,880.71, ran twice this cycle — labeled SYNTHETIC "NOT a validated edge"). Structural leak guard: `MarketView` omits outcome+resolution_time (`walk_forward.py:103-116`); train = `resolution_time < w_start` (`:373`); fetchers reject any tick `> decision_ts`/`>= resolution_ts` and RAISE rather than fabricate (`polymarket_history_fetcher.py:362-366,600-603`; kalshi `:375-377,514-516`). Costs single-source-of-truth shared w/ executor (`execution.py:27,1078,1085`). Below A+: impact term uncalibrated placeholder (`cost_model.py:38-44`, `DEFAULT_IMPACT_COEFF=0.5`). |
| correctness_reliability | A | ✅ | Determinism verified (runtime harness `paper_pipeline_deterministic` exposureA==exposureB==10.000000; walk-forward identical hash/PnL twice). **#241 phantom-position fixed + verified non-tautological** (`execution.py:1062`; tests trip pre-fix). No swallowed errors (narrow, logged excepts). Nit (unchanged, self-documented): SELL/partial-reduce feeds the executor hard caps but not the per-strategy drawdown circuit `risk_manager.record_pnl` (`orchestrator.py:459-463`) — resolution (dominant loss path) feeds both. |
| security | A | ✅ | Auth **default-CLOSED**: unset token → 401 (`auth.py:47-61`), settings-read failure → DENY (`auth_core.py:36-41`), `hmac.compare_digest` (`auth_core.py:55`); live gate server-side + not body-flippable (`OrderRequest` has no live field; `execution.py:696-702,1014,259-268`); all mutating routes carry `_MUTATING_AUTH` (`routes.py:25`). **New #242 boot gate weakens nothing** (adds a fail-loud live+missing-cred check). No committed secrets (only `.env.example`). |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS real order, kill switch blocks, max-position cap rejects $900>$50, loss cap trips **net-of-fees** at −$41.20 vs −$10 and blocks subsequent orders. **#242 fail-loud venue-cred boot gate** hardens the live path. HUMAN-CORE holds (loop can't flip/fund/raise caps). Real `render.yaml`. Nit (unchanged): partial-reduce path not yet wired to the per-strategy drawdown circuit. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:5-6,28-35`); seed hashes reproduce; DoD honestly unchecked; `check_scorecard.py`→parses (overall=B); newest commits honestly "File ROADMAP"/"chore" framed (prior #240 nit resolved). Nit (fixed this cycle): the prior scorecard's "894 tests" was stale — actual collection is **1040** (13 pandas files excluded from the light gate by design); direction was conservative/understated, never inflated. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, bucket-calibration family **refuted across 4 real corpora**, and the B8 cross-venue probe ran no OOS backtest. THE binding constraint (#79). |
| design_taste | A | — | Unchanged (no frontend diff this cycle). Positions-tab "Unrealized" shows `—` until loaded (`page.tsx:867-871`); charts real-data-fed with labeled Recharts axes; systemic null-honesty. |
| tests_evals | A | — | Curated suite green via preflight (`preflight.sh code` → GREEN); +27 genuine new tests this cycle (`test_live_gate_defense.py`, `test_config_safety.py`) that trip pre-fix. 13 pandas-dependent files stay out of the light gate by design (documented; all 13 collection errors are `No module named 'pandas'`). |
| performance | A | — | No hot-path change this cycle. Scan/execute hot loop O(1) per opp; walk_forward O(windows×markets) cold-path only. Proportionate for a personal paper bot. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-07
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests + safety + secrets + runtime harness + scorecard-parse + self-validation + GTM-honesty all OK (CI skips full ruff by design)
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap + loss cap net-of-fees (-$41.20 vs -$10) + paper PnL, deterministic
    walk_forward_reproduces: true      # seed_hash b3a8d5e0e9579853, total PnL 910,880.71 identical across two runs this cycle (SYNTHETIC demo, labeled NOT a validated edge)
    real_oos_probe: "no new OOS run this cycle. Bucket-calibration family (EXP-002/B4a static+recency) REMAINS REFUTED across 4 real corpora (CONFIRMED noise). B8 cross-venue coherence was a data-feasibility probe only — pinned the Kalshi orderbook-quote path, ran no OOS backtest, claims no edge (RESEARCH_MEMORY 3rd probe)."
    leak_guard: "history fetchers REFUSE to fabricate a decision-time price — every market without a pre-resolution tick is SKIPPED/RAISED, not invented (walk_forward.py:103-116,373; polymarket_history_fetcher.py:362-366,600-603)"
    ruff_correctness_gate: "clean — E9/F821/F811 pass"
    new_safety_fixes: "#241 (0-fill OPEN no longer fabricates a phantom Position; execution.py:1062) and #242 (live host refuses to boot without venue order creds; config.py:183-215) — both verified GENUINE with non-tautological tests (test_live_gate_defense.py, test_config_safety.py; 27 passed)"
    test_collection: "1040 collected, 13 errors (all `No module named pandas` — the documented heavy-dep exclusion from the light gate)"
    scorecard_gate: "NOT-READY (business_case_strength: B)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: []
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["market-impact/capacity term is a self-admitted uncalibrated placeholder (cost_model.py:38-44, DEFAULT_IMPACT_COEFF=0.5 not fitted to real book depth) — disclosed and conservatively signed, but the capacity/edge-survival dimension rests on an unvalidated parameter; caps below A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["the SELL/partial-reduce path feeds the executor hard loss caps (kill-switch trigger, fully wired) but not yet the per-strategy drawdown circuit risk_manager.record_pnl — only the resolution path does (orchestrator.py:459-463, self-documented follow-up). Secondary because resolution is the dominant loss path and the binding hard caps are wired on both paths."]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: ["A-with-a-nit, not A+: the auth_core empty-token primitive is misreadable in isolation (documented + unreachable because the adapter denies first). No change this cycle justifies an A→A+ promotion; held at A per anti-inflation."]
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["partial-reduce path not yet wired to the per-strategy drawdown circuit (shared with correctness_reliability; orchestrator.py:459-463). Hard caps + kill switch fully wired; secondary."]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["prior scorecard's '894 tests' was stale (actual 1040; conservative/understated, corrected this cycle). Keep the reported test count in sync with actual collection, or reference the curated-green subset rather than a raw total."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists — revenue $0, $104k/yr floor unmet. The only non-crowd model_prob family (price-bucket calibration, static + recency) is REFUTED across 4 real corpora (CONFIRMED noise). The pre-registered next candidate (B8 cross-venue coherence) is still an unbuilt multi-run data-engineering effort with zero OOS runs — this cycle only pinned the Kalshi orderbook-quote data path. Honest but unproven (THE binding constraint, #79); a validated edge requires a NEW hypothesis with a pre-registered min-N/OOS plan that survives walk_forward + a passing B2 calibration gate cost-net. Do NOT re-test the refuted bucket family."]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: []
    - name: tests_evals
      grade: "A"
      ship_critical: false
      top_gaps: ["heavy pandas/sklearn risk/backtest suites (13 files) stay out of the light CI-blocking gate by design — documented, but a CI coverage hole validated only via the full CI run, not the light gate."]
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) — cold backtest path only, low stakes."]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — revenue $0, floor unmet, the sole non-crowd model_prob family (price-bucket calibration) REFUTED across 4 real corpora, and the B8 cross-venue candidate has zero OOS runs (this cycle only pinned its data path). THE binding constraint. Next: a NEW pre-registered hypothesis (min-N + OOS plan) that survives walk_forward + a passing B2 calibration gate on a real point-in-time non-survivorship panel, reported cost-net and reproducible above the $2k/wk floor. Do NOT re-test the refuted bucket family. (Issue #79, egress/owner-gated.)"
    - "correctness_reliability / run_risk_readiness (A->A+): wire the SELL/partial-reduce path into the per-strategy drawdown circuit (risk_manager.record_pnl), not only the executor hard caps — so a strategy bleeding on reduces trips its own drawdown disable, not just the global kill switch (orchestrator.py:459-463)."
    - "backtest_integrity (A->A+): calibrate the market-impact/capacity term against real order-book depth (cost_model.py:38-44) so capacity/edge-survival claims rest on a fitted parameter rather than the impact_coeff=0.5 placeholder."
    - "artifact_integrity (A->A+): keep the scorecard's reported test count in sync with actual collection (was 894, actual 1040) — or cite the curated-green subset instead of a raw total that drifts."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is refuted across four real corpora, and the B8
cross-venue candidate has not run OOS) — so the quality gate fails, and independently the
full `preflight.sh` is honest-RED (`floor_met_year1: false`, DoD boxes unchecked). This is
the project's core discipline working exactly as designed: **never let a number that isn't
real drive a decision, and never claim an edge you cannot reproduce out-of-sample.** This
cycle the factory made real, verified safety progress (two genuine bypass/boot-gate fixes)
and ran another real-data probe honestly to **no new edge**. The one remaining ship-critical
gap is correctly, honestly open.
