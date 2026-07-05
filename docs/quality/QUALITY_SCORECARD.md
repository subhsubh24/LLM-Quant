# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-05 — overall `B`. Ship gate: NOT met.**

The composition improved this cycle: **`functional_reality` recovered B→A**. The
2026-07-03 gap — `strategies.py` fabricating `volume=10000`/`liquidity=5000` on the
Gamma-zero-volume (degraded) path and thereby flipping BUY-gate decisions on invented
liquidity (#165/#202) — is **genuinely fixed and verified**. `_mark_unavailable_data`
(`strategies.py:1374-1399`) now only sets `volume_unavailable`/`liquidity_unavailable`
**flags** and leaves `total_volume`/`liquidity` at their honest `0`; the filters
(`polymarket_client.py:90-107` `volume_below`/`liquidity_below`) *neutralize* on the flag
instead of passing on a synthetic number, so a zero-volume degraded market surfaces via a
genuine **skip**, never a fake value. A real regression test pins it
(`test_data_availability_flags.py`, incl. `"$10,000" not in results[0].reason`). Three
named A→A+ nits from the last grade are also closed: the positions-tab "Unrealized" now
shows `—` until loaded (#206, `page.tsx:867-871`), durable-state restart-survival is now
tested **through the production `get_executor()` singleton seam** (#207,
`test_executor_state_persistence.py:213-232`), and the `ruff.toml` comment now accurately
describes the correctness-only CI gate.

Only **one** thing holds the overall at **B** and keeps the ship gate closed:

- **business_case_strength = B (ship-critical, unchanged — THE binding constraint):**
  there is still **no validated, out-of-sample, cost-net edge**. Revenue $0, the
  $104k/yr floor unmet. This cycle's research made the no-edge finding **stronger, not
  weaker**: the bucket-calibration family (EXP-002/B4a, static *and* recency) was tested
  across **four real corpora** and is **CONFIRMED noise, not an edge** (−$2,938 @ n=510,
  +$3,330 @ n=799, −$2,947 @ n=621, and an HF sample whose apparent edge is a
  crowd-pinned-market artifact) — `RESEARCH_MEMORY.md`, Research Run 15. The prior
  −$480.86 "probe" is now understood as small-sample noise, honestly labelled. This is the
  honest north-star state and the factory graded its own alpha **REFUTED** rather than
  curve-fit it — exactly the integrity the rubric rewards. (Issue #79.)

No fabricated PnL, no unreproducible backtest, no fabricated edge was found anywhere. The
"§34 pre-launch funnel / public demo" (#240) is **spec-only** (+32 lines to
`FACTORY_STANDARD.md`, explicitly a no-op for a personal tool) — there is **no** demo
displaying invented numbers; the feared artifact-integrity failure does not materialize.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | **B→A (fixed).** #165 fabrication gone: `_mark_unavailable_data` (`strategies.py:1374-1399`) sets flags only, leaves volume/liquidity at honest 0; filters neutralize on the flag (`polymarket_client.py:90-107`), never pass on a synthetic value; regression test `test_data_availability_flags.py` asserts `"$10,000" not in reason`. Orchestrator wires scan→DQ→risk→Kelly→executor→persist (`orchestrator.py:32-45,395-428`); paper fills charge real cost-model slippage+2% fee (`execution.py:1058-1091`). |
| backtest_integrity | A | ✅ | Reproduces bit-identically (`seed_hash b3a8d5e0e9579853`, PnL 910,880.71, ran twice); structural leak guard (`MarketView` omits outcome+resolution_time `walk_forward.py:103-116`; train = `resolution_time < w_start` `:373`); fetcher rejects any tick `> decision_ts`/`>= resolution_ts` and RAISES rather than fabricate (`polymarket_history_fetcher.py:361-366,594-603`); costs single-source-of-truth shared w/ executor (`execution.py:27`, pinned by `test_cost_model`). Bucket family REFUTED across 4 corpora, honestly. Below A+: impact term uncalibrated toy (`cost_model.py:38-44,110-116`). |
| correctness_reliability | A | ✅ | Determinism verified (identical hash/PnL twice); the two adversarial fixes are **genuine**: SELL-to-open-a-short rejected at the gate before fill (`execution.py:956-964`, `test_short_open_rejected.py`), closing the phantom-fill/loss-cap bypass (#215); resolved position settles into loss caps **at most once across restart** via persist-before-count + defer-on-probe-failure (`orchestrator.py:417-432,519-528`, #204). Nit: SELL/partial-reduce feeds executor hard caps but not yet the per-strategy drawdown circuit (`orchestrator.py:459-463`, self-documented follow-up). |
| security | A | ✅ | Auth **default-CLOSED**: unset token → 401 (`auth.py:49-59`), `BACKEND_AUTH_DISABLED` sole opt-out, settings-read failure → DENY (`auth_core.py:36-41`), constant-time compare; live gate server-side + not body-flippable (`execution.py:696-702,1014`, `OrderRequest` carries no live flag); all mutating routes carry `_MUTATING_AUTH` (`routes.py:25`); no committed secrets (only `.env.example`). |
| run_risk_readiness | A | ✅ | Harness PASSED: live gate REJECTS real order, kill switch blocks, max-position cap rejects $900>$50, loss cap trips **net-of-fees** at −$41.20 vs −$10 and blocks subsequent orders. Durable state fails CLOSED on unreadable store; **#207 closed** — restart-survival now tested through the production `get_executor()` seam (`test_executor_state_persistence.py:213-232`). HUMAN-CORE holds. Real `render.yaml`. |
| artifact_integrity | A | ✅ | Every metric honestly 0/null (`BUSINESS_CASE.md:5-6,28-37`); "894 tests"=894; seed hashes reproduce; DoD honestly unchecked; `check_scorecard.py gate`→NOT-READY; `ruff.toml` comment now matches the shipped correctness-only gate (last grade's stale-comment nit fixed). Nit: #240 commit *subject* reads as a shipped demo but the diff is spec-only (+32 lines `FACTORY_STANDARD.md §34`, marked a no-op) — a git-log reader could mistake docs for a built feature. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge**: revenue $0, floor unmet, and the bucket-calibration family is now **refuted across 4 real corpora** (CONFIRMED noise). THE binding constraint (#79). |
| design_taste | A | — | #206 fixed: positions-tab "Unrealized" shows `—` until loaded (`page.tsx:867-871`); charts real-data-fed with labeled Recharts axes (`page.tsx:30-39`); systemic null-honesty. Every number traces to a real API response. |
| tests_evals | A | — | 67 test files; curated suite green via preflight; regression coverage verified non-tautological (data-availability flag test asserts the fabricated string is absent; short-reject test has 3 fail-pre-fix repros + 2 reduce controls; get_executor seam test trips a real loss-cap breach). 13 pandas-dependent files stay out of the light gate by design (documented). |
| performance | A | — | Scan/execute hot loop O(1) per opp; only nested loops are bounded correlation scans; walk_forward O(windows×markets) is cold-path only. Proportionate for a personal paper bot; no new hot-path regressions this cycle. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-05
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + curated tests + safety + secrets + harness + scorecard-parse + self-validation (CI skips full ruff by design)
    runtime_harness: passed            # live gate REJECTS + kill switch + max-position cap + loss cap net-of-fees (-$41.20 vs -$10) + paper PnL, deterministic
    walk_forward_reproduces: true      # seed_hash b3a8d5e0e9579853, total PnL 910,880.71 identical across two runs (SYNTHETIC demo, labeled NOT a validated edge)
    real_oos_probe: "bucket-calibration family (EXP-002/B4a static+recency) REFUTED across 4 real corpora: -$2,938 (n=510), +$3,330 (n=799), -$2,947 (n=621), HF crowd-pinned artifact — CONFIRMED noise, honestly disclosed (RESEARCH_MEMORY Run 15). Kalshi leg egress-throttled (429)."
    leak_guard: "history fetchers REFUSE to fabricate a decision-time price — every market without a pre-resolution tick is SKIPPED, not invented (validate_real_oos.py output)"
    ruff_correctness_gate: "clean — E9/F821/F811 pass"
    ruff_full: "131 findings (cosmetic hygiene F401/E402/F841; zero F821/E9; unenforced by design)"
    scorecard_gate: "NOT-READY (business_case_strength: B)"
    issue_165_fix: verified        # flags-not-fabrication; regression test asserts synthetic value absent from BUY reason
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: []
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["market-impact/capacity term is a self-admitted uncalibrated placeholder (cost_model.py:38-44,110-116; impact_coeff=0.5 not fitted to real book depth) — disclosed and conservatively signed, but the capacity/edge-survival dimension rests on an unvalidated parameter; caps below A+."]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["the SELL/partial-reduce path feeds the executor hard loss caps (kill-switch trigger, fully wired) but does not yet feed the per-strategy drawdown circuit risk_manager.record_pnl — only the resolution path does (orchestrator.py:459-463, self-documented follow-up). Secondary because resolution is the dominant loss path and the binding hard caps are wired."]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: []
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: []
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["#240 commit subject ('§34 pre-launch funnel — public demo of the core aha') reads as a shipped feature, but the diff is spec-only (+32 lines FACTORY_STANDARD.md §34, explicitly a no-op for a personal tool). Internally honest; the risk is a git-log/roadmap reader mistaking documentation for a built demo. Prefer 'docs/spec:' framing over 'factory:' feature framing when the diff adds no product code."]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists — revenue $0, $104k/yr floor unmet. The only non-crowd model_prob family (price-bucket calibration, static + recency) is now REFUTED across 4 real corpora (CONFIRMED noise: -$2,938/n=510, +$3,330/n=799, -$2,947/n=621, HF crowd-pinned artifact). Honest but unproven (THE binding constraint, #79); a validated edge requires a NEW hypothesis with a pre-registered min-N/OOS plan that survives walk_forward + a passing B2 calibration gate cost-net."]
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
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — revenue $0, floor unmet, and the sole non-crowd model_prob family (price-bucket calibration) is now REFUTED across 4 real corpora (CONFIRMED noise). THE binding constraint. Next: a NEW pre-registered hypothesis (min-N + OOS plan) that survives walk_forward + a passing B2 calibration gate on a real point-in-time non-survivorship panel, reported cost-net and reproducible above the $2k/wk floor. Do NOT re-test the refuted bucket family. (Issue #79, egress/owner-gated.)"
    - "correctness_reliability (A->A+): wire the SELL/partial-reduce path into the per-strategy drawdown circuit (risk_manager.record_pnl), not only the executor hard caps — so a strategy bleeding on reduces trips its own drawdown disable, not just the global kill switch (orchestrator.py:459-463)."
    - "backtest_integrity (A->A+): calibrate the market-impact/capacity term against real order-book depth (cost_model.py:38-44) so capacity/edge-survival claims rest on a fitted parameter rather than the impact_coeff=0.5 placeholder."
    - "artifact_integrity (A->A+): when a 'factory: §N' commit adds only spec/docs (no product code), frame the subject as 'docs/spec:' rather than 'public demo of ...' so the git log / ROADMAP cannot be misread as a shipped feature (#240)."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **One ship-critical dimension is B** — `business_case_strength` (no validated
OOS edge; the only non-crowd alpha family is now refuted across four real corpora) — so the
quality gate fails, and independently the full `preflight.sh` is honest-RED
(`floor_met_year1: false`, DoD boxes unchecked). This is the project's core discipline
working exactly as designed: **never let a number that isn't real drive a decision, and
never claim an edge you cannot reproduce out-of-sample.** The factory made real, verified
progress this cycle (functional_reality recovered B→A, three A→A+ nits closed, a genuine
SELL-short loss-cap bypass fixed) and — most creditably — ran its own candidate alpha to a
**REFUTED** verdict rather than curve-fitting it. The one remaining ship-critical gap is
correctly, honestly open.
