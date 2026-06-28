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
  last_run: 2026-06-28          # prior factory run (3-PR real-data/impact/audit-log run, #45-48)
  last_deep_audit: null         # no dated "DEEP AUDIT —" entry recorded in loop-memory yet
  this_run:
    changes_shipped: 1          # the LOOP_HEALTH observability apparatus (this PR)
    changes_abandoned: 0
    abandoned_reasons: []        # [{change, reason}] reason ∈ gate_tsc|gate_test|gate_determinism|gate_build|gate_backtest_nonreproduce|review_value|review_correctness|circuit_breaker|conflict|dead_end|blocked_owner
    verify_cycle_failures: 0
    review_rejections: 0
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 42              # git: squash-merged (#NN) commits, last 7 days
    reverts: 0                  # git: no revert commits in the window
    readiness_attempts: 0       # no GO-live readiness certification attempted (GO = not_ready, pre-launch)
    readiness_rejected: 0
    recurring_failures: []       # nothing has failed >=2 runs yet; WATCH: Polymarket egress-block (403) hit 1x this window -> OA-11 (blocked_owner). A 2nd hit with no resolution => 'stuck' => harness proposal.
    harness_proposals_open: 0    # gh: no open `loop: harness improvement proposal` issues
  signal: bootstrapping          # seed run — first datapoint; no prior LOOP_HEALTH to trend against. Next run can read improving/steady/churning/stuck.
```

## How to read the seed

This is the **first** datapoint, so the signal is `bootstrapping` by definition — there is
nothing prior to trend against. For context (not yet a trend): the last-7-day raw throughput
is healthy — **42 merged PRs, 0 reverts, 0 abandoned this run** — which *if it holds next run*
reads as `improving`/`steady`. The one cloud on the horizon is the **Polymarket egress block**
(403 at the env proxy), which made real-data OOS validation impossible and was correctly handed
to the owner as **OA-11** (`blocked_owner`, not a loop-rule failure). It has been hit **once**.
Per FACTORY_STANDARD §10b, if the same wall blocks convergence on a **second** run without
resolution, that flips the signal toward `stuck` and is the trigger to open one
`loop: harness improvement proposal` issue (e.g. "the loop needs a network-permitted lane for
real-data validation").
