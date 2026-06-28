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
  as_of: 2026-06-28
  last_run: 2026-06-28          # prior run: OA-11 real-data validation (#50)
  last_deep_audit: null         # no dated "DEEP AUDIT —" entry recorded in loop-memory yet
  this_run:
    changes_shipped: 1          # CI required-check staging + lint standard (PROPOSED_CI.md + ruff.toml)
    changes_abandoned: 0
    abandoned_reasons: []        # [{change, reason}] reason ∈ gate_tsc|gate_test|gate_determinism|gate_build|gate_backtest_nonreproduce|review_value|review_correctness|circuit_breaker|conflict|dead_end|blocked_owner
    verify_cycle_failures: 0
    review_rejections: 0
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 44             # git: squash-merged (#NN) commits, last 7 days
    reverts: 0                 # git: no revert commits in the window
    readiness_attempts: 0       # no GO-live readiness certification attempted (GO = not_ready, pre-launch)
    readiness_rejected: 0
    recurring_failures: []       # nothing has failed >=2 runs. Egress wall resolved for data access last run; residual is scheduling only (OA-11).
    harness_proposals_open: 1    # gh issue #51 — make the blocking gate a REQUIRED check (branch protection) + enable lint-at-zero. The META channel working as designed: a workflow-scope improvement the loop can't self-apply, raised + tracked (OA-12).
  signal: improving              # 3rd datapoint: 44 merged / 0 reverts / 0 abandoned; staged the required-check correctly (verify-green-before-requiring) instead of red-blocking the gate, and routed the un-self-appliable part to the META channel. Converging.
```

## How to read the latest signal

**2026-06-28 (3rd datapoint) — `improving`, first harness proposal open.** Staged the
required-check + lint-at-zero work (`docs/ci/PROPOSED_CI.md`): the functional gate is already
green, so the high-value step is the owner's one-time branch-protection toggle (OA-12) — raised
as harness issue **#51** (`harness_proposals_open: 1`). Held lint-at-zero *off* (166 ruff
findings in trading code) rather than red-block the required gate — exactly "verify green before
requiring." This is the META channel doing its job: the loop builds + stages everything it can,
and the one thing it cannot self-apply (admin/`.github/` scope) becomes a tracked proposal, not a
silent wall.

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
