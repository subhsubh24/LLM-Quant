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
  as_of: 2026-06-29
  last_run: 2026-06-29          # prior run: self-validation addendum (#82)
  last_deep_audit: 2026-06-29   # daily deep audit w/ live-safety + side-effect + auth lenses ran this run (3 Opus auditors)
  enforced_in_ci: true          # required check (enforce_admins=true, strict=false) + repo auto_merge; loop merges via --auto/direct-on-green and WAITS for CI, never --admin
  validation:                   # self-validation capability readiness — refresh every run from `check_self_validation.py --readiness`
    enforced_in_ci: true        # the coverage gate is a blocking preflight step (9d) inside the required check
    capabilities_total: 9       # +2 this run: executor_state_persistence, backend_route_auth
    unmet: []                   # active + ci_validatable:false capabilities (need an owner secret). NON-EMPTY => urgent OWNER_ACTION + blocks. Must match SELF_VALIDATION.readiness.unmet AND have a PENDING_OPS validation-capability-<id>.
  this_run:
    changes_shipped: 3          # PR-A control-path hardening (persistence + REST validation + route auth + init_db durability fix), PR-B frontend design-taste, PR-C bookkeeping
    changes_abandoned: 0
    abandoned_reasons: []        # dropped pre-build on the value/disjoint rules (NOT abandoned): D2 SELL-path (no-op in current flow), B1 per-leg exec / E7 / B3-derivation (alpha-blocked), C2 impact-calib (egress-blocked)
    verify_cycle_failures: 1     # durable-tables regression test failed under full-suite contamination on first cut; rewrote as a clean-subprocess test (1 fix cycle)
    review_rejections: 0         # 2 Sonnet reviewers + 3 Opus auditors flagged 2 MUST-FIX (auth fail-open log level; deactivate-persist race) + a BUILDS≠WORKS gap — all fixed in ONE consolidated cycle, none rejected the change
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 51             # git: squash-merged (#NN) commits to default, last 7 days
    reverts: 0
    readiness_attempts: 0
    readiness_rejected: 0
    recurring_failures: []       # OA-11 corpus refresh = owner/egress-scope (automatable, OA-13). No recurring wall.
    harness_proposals_open: 0
  signal: improving              # 13th datapoint: drove 3 ship-critical QUALITY_SCORECARD top_gaps (run-risk-readiness durability, security route-auth, design-taste cleanup) to done; an adversarial auditor caught a real BUILDS≠WORKS (durable tables never created in prod) — root-caused + regression-pinned. unmet=[]. Converging.
```

## How to read the latest signal

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
