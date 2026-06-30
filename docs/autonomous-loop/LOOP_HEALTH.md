# LOOP HEALTH — is the LOOP getting better, or just busier?

> The deep audit (FACTORY_STANDARD §10) grades the **product**; the QUALITY_SCORECARD
> grades the **product**. This file grades the **loop itself** — whether the autonomous
> factory is *converging* (shipping durable, correct changes that move the DoD) or merely
> *churning* (re-attempting dead-ends, racking up reverts, walling on the same failure).

## Contract (read before editing)

- **Update EVERY run, in the bookkeeping PR, with REAL counts** — derived from `git`/`gh`
  and from what actually happened *this run*. Never hand-wave or round up.
- **Honest only.** Same anti-gaming rule as the governing number and the GO signal: a
  fabricated "improving" signal is a lie. If the loop churned, say `churning`. If it
  stalled, say `stuck`. The point of the metric is to catch that, not to look good.
- **Dashboard-readable.** The fenced `LOOP_HEALTH:` block below is parsed the same way as
  `BUSINESS_CASE_SUMMARY` / `GROWTH_STATUS` / `OWNER_ACTIONS` (fenced ```yaml, top-level
  key). Keep it well-formed.
- **Observability, NOT a ship gate.** `preflight.sh` does not block on this — it is a
  mirror the loop holds up to itself. (Contrast: the GO signal and the loss caps ARE gates.)
- **Classify every abandoned change** (`abandoned_reasons`) so the loop does not re-attempt
  the same dead-end — the build-loop's "don't repeat the failed path."
- **A `churning` or `stuck` signal is the trigger to open ONE
  `loop: harness improvement proposal` issue** — the ONLY channel by which the loop's own
  rules improve (it cannot edit its routine / `.claude`). A recurring wall that never raises
  a proposal is itself a dead signal. See FACTORY_STANDARD §10b.

`reason` ∈ `gate_tsc` · `gate_test` · `gate_determinism` · `gate_build` ·
`gate_backtest_nonreproduce` (this stack: a backtest that won't reproduce bit-for-bit) ·
`review_value` · `review_correctness` · `circuit_breaker` · `conflict` · `dead_end` ·
`blocked_owner` (handed to a human-core owner action — e.g. an egress/network or live-key
wall the loop must not route around).

`signal` ∈ `bootstrapping` (no prior data point to trend against) · `improving` (shipping
up, abandon/revert down vs. last run) · `steady` (converging at a stable rate) · `churning`
(high abandon/revert vs. shipped) · `stuck` (recurring failures / no convergence — open a
harness proposal).

```yaml
LOOP_HEALTH:
  project: LLM-Quant
  as_of: 2026-06-30
  last_run: 2026-06-30          # prior run (same day, earlier): A3 Kalshi adapter + deep-audit hardening (#91-#92)
  last_deep_audit: 2026-06-30   # 8-Haiku scout sweep w/ correctness + security + quality-reconcile + artifact-freshness lenses ran this run
  enforced_in_ci: true          # required check (enforce_admins=true, strict=false) + repo auto_merge; loop merges via --auto/direct-on-green and WAITS for CI, never --admin
  validation:                   # self-validation capability readiness — refresh every run from `check_self_validation.py --readiness`
    enforced_in_ci: true        # the coverage gate is a blocking preflight step (9d) inside the required check
    capabilities_total: 10      # unchanged this run (no new capability; backend_route_auth coverage widened to /scan + risk-config bounds)
    unmet: []                   # active + ci_validatable:false capabilities (need an owner secret). NON-EMPTY => urgent OWNER_ACTION + blocks. Must match SELF_VALIDATION.readiness.unmet AND have a PENDING_OPS validation-capability-<id>.
  this_run:
    changes_shipped: 3          # #96 API security hardening; #95 side-effect integrity (no phantom arb fill); #94 executor fail-closed hardening; + this bookkeeping PR
    changes_abandoned: 0
    abandoned_reasons: []        # deferred pre-build on the disjoint/value rules (NOT abandoned): B1-full per-leg execution (risky, larger follow-up), B6 enable/disable (collides routes.py w/ #96), E-track wiring (DECISION COROLLARY — no real alpha drives it), F7 lint + F5 Playwright (repeatedly deferred). DROPPED as redundant (not abandoned): cost-model impact tests (19 already), A5 staleness fixture (already covered).
    verify_cycle_failures: 0     # local preflight step-3 ruff FAILs (ruff installed locally, absent in CI) — a known false alarm, verified GREEN with ruff hidden = CI parity; not a real gate failure
    review_rejections: 1         # #94 Opus live-safety auditor returned NOT-SAFE (the fail-closed branch was DEAD CODE vs the production store — load() swallowed all errors -> never raised), + 2 reviewers flagged a now-stale docstring; ALL fixed in ONE consolidated cycle (load() raises on unreadable vs None-on-absent + real-store fail-closed test + empty-token defense-in-depth + docstrings) -> fresh re-audit FIX-HOLDS. None abandoned.
    process_incidents: 1         # STALE local default-branch ref: PR-C/PR-A were branched from a ~25-commit-old local ref (pre-auth/Kalshi); caught via a scout-vs-session-start guard-status contradiction, fixed by fetch origin + reset ref + rebase. Lesson recorded; no bad code shipped.
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 55             # git: squash-merged (#NN) commits to default, last 7 days (+3 this run)
    reverts: 0
    readiness_attempts: 0
    readiness_rejected: 0
    recurring_failures: []       # OA-11 (Polymarket) + OA-15 (Kalshi) corpus refresh = owner/egress-scope. No recurring wall.
    harness_proposals_open: 0
  signal: improving              # 15th datapoint: 3 file-disjoint code PRs from an 8-scout sweep (security + side-effect integrity + executor fail-closed); the adversarial gate earned its keep TWICE — a NOT-SAFE BUILDS!=WORKS (dead fail-closed branch) fixed + FIX-HOLDS, and a stale-base hazard caught before it shipped. unmet=[]. Converging.
```

## How to read the latest signal

**2026-06-30 (15th datapoint — factory run, 2nd of the day) — `improving`, the adversarial gate killed a fail-safe that was DEAD CODE in prod, and a stale-base hazard was caught before it shipped.**
An 8-Haiku scout sweep across tracks A–G surfaced the maximal file-disjoint, value-bar-clearing set; shipped **3
code PRs + this bookkeeping**, all ship-critical-dimension hardening: (#96) **API security** — guard the lone
unguarded state-mutating route `/prediction-markets/scan`, bound user inputs, and bounds-validate `risk/config` so a
non-positive daily-loss cap (which would DISABLE loss protection) is rejected 422; (#95) **side-effect integrity** —
stop fabricating a phantom fill (empty token_id) for multi-leg `outcome_idx == -1` arbitrage baskets, skipping them
honestly until per-leg execution (B1) exists; (#94) **executor fail-closed** — a durable-store rehydrate failure now
trips the kill switch instead of silently resuming a halted bot. **The gate earned its keep twice:** (1) a fresh Opus
live-safety auditor returned **NOT-SAFE** on #94 — the new fail-closed branch only fired if `load()` raised, but the
production `ExecutorStateStore.load()` swallowed every error and returned `None`, so it was **dead code against the
only store that ships** (a DB-down restart would still resume un-halted); fixed by making `load()` distinguish ABSENT
(None) from UNREADABLE (raise) + a REAL-store fail-closed test + a defense-in-depth empty-token reject, and a fresh
**re-audit returned FIX-HOLDS**. (2) A **stale local default-branch ref** (lagging origin by ~25 commits, pre-auth)
nearly based two PRs on old code — caught when a security scout's "/scan is the only unguarded route" contradicted the
session-start read (which showed every route guarded); recovered by fetching origin, resetting the ref, and rebasing,
which in turn surfaced a false-green test the stale base had hidden. **No DoD/floor box ticked** — hardening across
security/§12, run-risk-readiness (D3/D4), and side-effect integrity (B1); engine_pct 72→73. Binding constraint
unchanged: the 7-day-lead OOS corpus + a real alpha (OA-11/OA-15, owner/egress-scope), so no harness proposal
warranted. unmet=[].

### Earlier

**2026-06-30 (14th datapoint — factory run) — `improving`, the adversarial gate caught TWO real defects the tests passed over.**
An 8-Haiku scout sweep across tracks A–G surfaced the maximal file-disjoint, value-bar-clearing set; shipped **2
code PRs + this bookkeeping**: (#92) ROADMAP **A3 — a second-venue Kalshi DATA adapter** (`kalshi_client.py` +
`kalshi_history_fetcher.py`) behind the SAME `Market`/`Outcome`/`HistoricalMarket` interface, with the same
structural anti-leakage guarantee as the Polymarket fetcher, fully offline fixture-tested, no new credential; and
(#91) a **deep-audit hardening pass** (live-only control-auth boot-guard; category-cap under-count fix; risk-score
div-by-zero guards; MTM client reuse; API exception-detail leak sanitization). **The gate earned its keep twice:**
(1) a fresh Opus **parsing auditor returned BROKEN** on the Kalshi adapter — the offline fixtures had encoded
Kalshi's *request-side filter* words (`"open"`/`"finalized"`) as if they were *live response* values, so the
adapter would have dropped **every live market** (a BUILDS≠WORKS: 45 green tests proving nothing about real
behavior); fixed to the documented response contract (`active`/`settled`/`determined`, `settled` discovery filter,
one-sided-book honesty, `p=0` tick fix) + an honest "documented-but-unverified-live" disclosure + a loud
warning-on-unknown-status net, and a **re-audit returned FIX-HOLDS**; (2) an Opus **live-safety auditor** found the
category-cap fix used the wrong cap field (`RiskConfig.max_single_position_usd` $50 vs the executor's real
`max_position_usd` ~$5) → a ~10x over-reservation, corrected to read the executor's actual cap. Both fixed in ONE
cycle each (≤2-cycle brake), merged on green required checks. **Anti-scarcity + anti-padding both held:** deferred
B6 strategy-control + D6 reconciler (genuinely buildable but collide with #91 on `orchestrator.py` — the disjoint
rule, not scarcity), F5 Playwright (real exec risk + can't CI-gate; a focused run suits it better), and F7 lint
(low value / risky on the trading path); a deep-audit scout found NO real defect beyond the audit findings, so none
was invented. No DoD/floor box ticked — venue infra + hardening, not a validated edge; binding constraint stays the
7-day-lead OOS corpus (OA-11 Polymarket, new OA-15 Kalshi — owner/egress-scope), so no harness proposal warranted.

### Earlier

**2026-06-29 (13th datapoint — factory run) — `improving`, the adversarial gate caught a real BUILDS≠WORKS the tests missed.**
Shipped 3 file-disjoint PRs from an 8-scout sweep, all driving named QUALITY_SCORECARD top_gaps: (A) control-path
hardening — durable kill-switch + realized-PnL persistence so a restart can't un-trip the halt or reset the loss
budget (run-risk-readiness top_gap), REST venue-fill validation (side-effect integrity, D1), and a degrade-safe
shared-secret on the 12 state-mutating backend routes (security top_gap, OA-14); (B) frontend design-taste — deleted
the dead `Math.random()` `equity-chart.tsx` and fixed the WeeklyMetricsCard P&L axis to always include $0; (C) this
bookkeeping. **The headline win — an Opus live-safety auditor proved a BUILDS≠WORKS the unit tests passed over:** the
durable audit-log/registry/executor tables were never created at startup (`init_db`'s `create_all` ran *before* their
lazy import), so the "durable" persistence silently no-op'd in prod. Root-caused (import the table modules in `init_db`
before `create_all`) and pinned with a cold-start subprocess regression test. **The gate earned its keep again:** 2
Sonnet reviewers + 3 Opus auditors (auth REAL+SOUND, side-effect SOUND, live-safety SAFE) flagged 2 MUST-FIX (auth
fail-open log→CRITICAL; deactivate-persist race) + several hardening nits — all fixed in ONE consolidated cycle (≤2-cycle
brake), then re-verified green. **Anti-scarcity + anti-padding both held:** dropped D2-SELL-path (a no-op in the current
held-to-resolution flow — would be a fake control) and the alpha/egress-blocked items (B1/E7/B3-derivation/C2) on the
value+disjoint rules, not invented. No DoD/floor box ticked — hardening, not a validated edge; binding constraint stays
OA-11 (7-day OOS corpus, owner/egress-scope), so no harness proposal warranted.

### Earlier

**2026-06-29 (11th datapoint) — `improving`, the loop can now mechanically prove it validates the app.**
Added a **self-validation coverage gate** (`docs/ci/SELF_VALIDATION.md` manifest +
`scripts/check_self_validation.py`, blocking preflight step 9d): every *active* capability must be
really `validated`/`gated_off`/`degrades_safely`, and every credential the code reads must be
declared — a **new, undeclared** credential **surfaces + blocks every PR** (proven end-to-end with a
simulated `KALSHI_API_KEY`). By design the gate needs zero keys to validate the active app; keys are
only for *activation* (live = human-core) or *enhancement* (Gemini = optional). The factory routine
now maintains the manifest as part of shipping any capability. 8 regression tests; seeded green.

### Earlier

**2026-06-29 (10th datapoint — factory run) — `improving`, the binding constraint now has a BUILT mechanism, and disjoint discipline held under contention.**
Shipped 3 file-disjoint code PRs + 1 bookkeeping from an 8-scout sweep: the FIRST `model_prob != crowd`
alpha mechanism (`CalibrationBucketStrategy` — per-bucket empirical calibration, leakage-safe, abstaining,
3-Opus-auditor-clean), the E5/E2 learning engines WIRED into the resolved stream + read-only endpoints
(honest insufficient-data/degenerate paths), and a frontend metrics dashboard rendering every `/metrics/*`
endpoint with honest empty/degenerate states. **Disjoint discipline under contention:** 3 genuinely-buildable
items (B6, per-leg arb, A4) all wanted `orchestrator.py`, which the E5/E2 PR already owned — correctly deferred
to a later run (the disjoint rule, NOT scarcity); Kalshi A3 + lint F7 were dropped on the value bar (premature /
cosmetic). **Anti-padding both ways:** a deep-audit scout found NO real defect, so no defect-PR was invented.
**The adversarial gate earned its keep:** both Sonnet reviewers caught a shared-mutable-model-in-closure bug
(fresh-model-per-call fix + a re-fit test) and an Opus auditor named an idealized-test honesty gap (added a
cost-band-suppression test) — all fixed in ONE cycle, shipped on mechanical verification (≤2-cycle brake).
No DoD/floor box ticked — B4a is the mechanism for an edge, not a validated edge; the highest-EV unlock stays
OA-11 (the 7-day OOS corpus, owner/egress-scope), so no harness proposal is warranted.

### Earlier

**2026-06-29 (9th datapoint — research run) — `steady`, EXP-002 proposed with zero code waste.**
Research-only run. Fixture calibration audit (54 records) + academic synthesis (Le 2026 Kalshi
calibration decomposition, PolyBench LLM-ensemble results, 3%-of-traders price-discovery study) converged
on EXP-002: the 54-record corpus is pinned at 48h and cannot test any calibration hypothesis. The
fetch_polymarket_history.py script already accepts `--decision-lead-days` (no code change needed); re-running
OA-11 with 7-day lead is the single highest-EV owner action to unlock all calibration alphas. Correctly
classified a fixture calibration anomaly (near-certainty-NO bucket: stated 0.8%, empirical 5.9%, p≈0.029)
as "insufficient data" — N=34 with ~2 YES outcomes, in-sample, biased sample; not an edge claim.
No code PRs; 1 bookkeeping PR (RESEARCH_MEMORY + GROWTH_STATUS + LOOP_HEALTH).

### Earlier

**2026-06-29 (7th datapoint — factory run) — `improving`, the model/strategy layer got better AND the adversarial
gate earned its keep again.** Shipped 4 file-disjoint PRs (#63–#66) from an 8-scout sweep: hardened the
cross-market keyword relatedness screen (B5), made the calibration gate's multiple-comparison correction
code-enforced (B2 Bonferroni), and built the first concrete learning-loop engines — an alpha lifecycle
registry with a fail-loud integrity gate (B3) and a per-strategy realized-PnL attribution primitive (E6).
**Anti-padding worked:** an 8th scout's alleged cost_model "extreme-price" bug did not survive scrutiny
(the floor is conservative, the safe direction), so it was dropped pre-build rather than shipped as busywork.
**The two-gate discipline caught real defects across two fix cycles:** a fresh Opus auditor broke the first
B5 hardening cut (entity-gating still admitted venue/nationality-shared pairs AND dropped acronym subjects)
→ simplified to a broad-stopword content screen; Sonnet/Opus reviewers caught a naive-timestamp round-trip
that broke determinism on non-UTC hosts and a frozen-dataclass-with-mutable-dict — all fixed within the
≤2-cycle brake, then merged on a green required check (no 3rd audit on a strictly-more-conservative change).
Gate strengthened 176→~290 enforced tests. No DoD/floor box ticked — these are engine/integrity pieces; the
binding constraint stays loop-buildable (a real alpha + wiring the new engines), so no harness proposal is
warranted.

### Earlier

**2026-06-29 (6th datapoint) — `improving`, closed the data-access gap hands-off.** Staged the
real-data refresh automation (OA-13): the fetcher now `--merge`s to ACCUMULATE a growing OOS corpus,
and a scheduled GitHub Action (or the env egress allowlist) keeps it fresh without a human — the
loop's egress wall stops being a recurring manual residual. Honest scope: the permanent toggle is
owner-irreducible (platform/`.github/` settings), so it's staged + tracked, not faked.

### Earlier

**2026-06-29 (5th datapoint) — `improving`, the adversarial gate earned its keep.** Shipped 5
file-disjoint PRs (#56–#60) from an 8-scout sweep: C5 metrics wired end-to-end, a venue-layer
fail-closed live gate, a real-data reproduction canary, a forensic strategy-audit harness, and
enforced LLM timeout + spend cap. **0 abandoned, 0 reverts.** The two-gate discipline caught real
defects pre-merge: 2 Sonnet reviewers flagged precision bugs in the metrics aggregator (iterator
double-consume; float-equality degenerate check) and — most importantly — a fresh Opus honesty
auditor **broke** the strategy-audit claim ("0 signals on the real sample" was FALSE: the harness's
own boilerplate question text produced ~98 phantom signals). All were fixed in ONE consolidated
cycle and are now guarded by loud regression tests; the blocking gate was extended from 99 to 176
enforced tests so the new safety/metrics/canary/audit checks bind every future change. The binding
constraint stays loop-buildable (a real decision-time alpha producing model_prob != crowd), not an
environmental wall — so no harness proposal is warranted.

### Earlier

**2026-06-28 (4th datapoint) — `improving`, the required check now has teeth.** Hardened the
gate enforcement so it actually binds the loop: `enforce_admins=true` (an `--admin` merge can no
longer bypass), `strict=false` (parallel file-disjoint PRs still auto-merge), repo
`allow_auto_merge=true`, and the merge protocol switched to `gh pr merge --squash --auto` in
ROADMAP "Shipping protocol" **and in all three PR-merging routine prompts** (factory / research /
auditor) — so every future autonomous run waits for CI instead of force-merging. Also shipped a
prod boot-guard: `E2E_DISABLE_RATE_LIMIT` can never be active with `LIVE_TRADING_ENABLED`
(`enforced_in_ci: true`). No open proposals.

### Earlier

**2026-06-28 (3rd datapoint) — `improving`, first harness proposal raised AND resolved.** Staged
the required-check + lint-at-zero work (`docs/ci/PROPOSED_CI.md`), raised harness issue **#51**
for the one piece the loop can't self-apply (branch protection = admin scope) — and the owner
authorized it the same day, so it was applied: the branch is now protected requiring
`code + safety gate (blocking)`, so a change that regresses the live gate / kill switch /
paper-pipeline reproduction **can no longer auto-merge** (OA-12 done, `harness_proposals_open`
back to 0). Held lint-at-zero *off* (166 ruff findings in trading code) rather than red-block the
now-required gate — exactly "verify green before requiring" (ratchet tracked as ROADMAP F7). The
META channel did its full job: raise → action → close, not a silent wall and not a hanging issue.

### Earlier

**2026-06-28 (2nd datapoint) — `improving`.** Throughput is healthy (**43 merged / 0 reverts /
0 abandoned** over 7 days), and the wall that loomed last run got knocked down: the **Polymarket
egress block** (403 at the env proxy) that made real-data OOS validation impossible was resolved
*for data access* by running the leakage-safe fetcher from a network-permitted host (54 real
records, pipeline reproduces — see `OA11_REAL_DATA_VALIDATION.md`). It did NOT recur as a
convergence wall, so it is **not** trending toward `stuck`; the residual is only *periodic
refresh scheduling* (OA-11, `blocked_owner`). Crucially the binding constraint **moved** from
data-access to "need a real alpha model" — which is **loop-buildable** (track B), i.e. forward
motion, not a dead-end. Per FACTORY_STANDARD §10b, had that same wall blocked a second run with
no progress, the rule would have flipped the signal to `stuck` and required one
`loop: harness improvement proposal`. It didn't — so none is opened, honestly.
