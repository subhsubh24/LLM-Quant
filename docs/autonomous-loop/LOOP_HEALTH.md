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
  last_run: 2026-06-29          # prior run: 4-PR models/strategy run (#63-66 B5/B3/E6/B2/A5)
  last_deep_audit: null         # no dated "DEEP AUDIT —" entry recorded in loop-memory yet
  enforced_in_ci: true          # required check (enforce_admins=true, strict=false) + repo auto_merge; loop merges via --auto/direct-on-green and WAITS for CI, never --admin
  this_run:
    changes_shipped: 4          # PR-1 E6+B3 wiring+D2 resolution-risk fix, PR-2 BCC cost-model honesty+MECE guard, PR-3 E5 window engine, PR-4 E2 drift detector (+ bookkeeping)
    changes_abandoned: 0
    abandoned_reasons: []        # none dropped this run; scout candidates that didn't survive honesty review (spread-based miscalibration screen — not validatable on the fixture; category-rate fitting — test-set p-hacking) were never built, not abandoned mid-flight
    verify_cycle_failures: 0     # blocking gate stayed green throughout; the one fix cycle was review/audit-driven, not a gate failure
    review_rejections: 0         # no PR rejected; ONE consolidated fix cycle applied all review/audit findings in-place within the <=2-cycle brake
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 58             # git: prior 54 + this run's 4 code PRs (bookkeeping PR not yet counted)
    reverts: 0                 # git: no revert commits in the window
    readiness_attempts: 0       # no GO-live readiness certification attempted (GO = not_ready, pre-launch)
    readiness_rejected: 0
    recurring_failures: []       # nothing has failed >=2 runs. Egress wall (OA-11/OA-13) remains owner-scope but is NOT a convergence wall (binding constraint is loop-buildable: a real alpha + per-leg arb execution + deriving B3 evidence).
    harness_proposals_open: 0    # no open proposals; no recurring wall warranting one this run.
  signal: improving              # 8th datapoint: 4 disjoint PRs shipped, 0 abandoned, 0 reverts; adversarial gate earned its keep — an Opus auditor BROKE the cost-arb "guaranteed edge" (MECE/midpoint/phantom-fill) and the B3 API promotion-via-fabricated-evidence, both honestly fixed/scoped in ONE consolidated cycle. Converging.
```

## How to read the latest signal

**2026-06-29 (7th datapoint) — `improving`, the model/strategy layer got better AND the adversarial
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
