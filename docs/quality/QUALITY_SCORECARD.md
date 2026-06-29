# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-06-29 — overall `B`. Ship gate: NOT met.**

The engineering is genuinely strong: six of seven ship-critical dimensions grade **A**,
backed by 447 passing tests, an outcome-asserting runtime harness, and a **leak-free,
deterministic, reproducible** walk-forward backtest engine. The binding constraint is
the project's north star itself — **there is no validated, out-of-sample, cost-net
edge yet** (revenue is $0; the $104k/yr floor is unmet and honestly disclosed) — which
holds **business_case_strength** to **B** and keeps the quality ship-gate closed. This
is the correct, honest state, not a defect to paper over.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Real Gamma/CLOB ingest → orchestrator wires every stage → real paper fills; no stubbed stages (`runtime_harness.py` PASSED). |
| backtest_integrity | A | ✅ | Structural leakage guard (`MarketView` omits `outcome`), expanding-window OOS, costs via single source of truth, reproducible (`seed_hash b3a8d5e0e9579853`, identical PnL across runs). |
| correctness_reliability | A | ✅ | 447 tests pass; deterministic (seeded local RNG); guarded divisions; no bare excepts in live path. 169 ruff findings are cosmetic (119 F401) and in legacy modules. |
| security | A | ✅ | No committed secrets; env-driven config; frontend HMAC session + middleware gate; live gate + kill switch fail-closed, server-side. |
| run_risk_readiness | A | ✅ | Live gate default-off + two-layer fail-closed; kill switch wired into order path; loss caps auto-trip; HUMAN-CORE boundary holds; real `render.yaml`. |
| artifact_integrity | A | ✅ | Spot-checked claims all backed by real artifact + passing test; GO-integrity can't be faked; reported test counts ≈ reality. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path — but **no validated OOS edge exists**, so revenue is unproven ($0, floor unmet). |
| design_taste | B | — | Load-bearing metrics views honest (real-data-only, explicit "—"/absent) — but a dead `equity-chart.tsx` ships fabricated `Math.random()` data and the portfolio bar chart has a non-zero baseline. |
| tests_evals | A | — | 39 files / ~964 behavior-pinning tests cover leakage, determinism, costs, caps, live gate, calibration; exclusions honest/documented. |
| performance | A | — | Proportionate; heapq event sim; no egregious hot-path waste (minor O(n²) in cold backtest dedup). |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-06-29
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + 447 tests + safety + secrets + harness
    pytest_curated: "447 passed, 1 xfailed"
    runtime_harness: passed            # live gate + kill switch + loss caps + paper PnL
    walk_forward_reproduces: true       # seed_hash b3a8d5e0e9579853, identical PnL across runs
    preflight_full_scope: red           # HONEST: floor_met false + 10 DoD boxes unchecked
    ruff: "169 findings (cosmetic; unenforced in CI by design)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["live Gamma/CLOB ingest path never exercised by an automated check"]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["no model_prob strategy has been run OOS on a real bias-controlled resolved-market panel (only synthetic + a 54-record biased fixture)"]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["lint unenforced in CI (ruff omitted) — a future shadowing F811/F821 could regress silently"]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: ["backend FastAPI state-mutating routes (kill-switch deactivate, config) have no auth; only the frontend is gated"]
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["kill-switch + realized-PnL state is in-memory only; a backend restart silently un-trips the kill switch and resets accumulated loss"]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["ROADMAP prose modestly overstates a few test counts; AUDIT_STATUS.txt is stale legacy"]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists yet — revenue $0, $104k/yr floor unmet; honest but unproven (the binding constraint)"]
    - name: design_taste
      grade: "B"
      ship_critical: false
      top_gaps: ["dead frontend/components/charts/equity-chart.tsx ships fabricated Math.random() data", "portfolio bar chart uses a non-zero (series-min) baseline with no axis labels"]
    - name: tests_evals
      grade: "A"
      ship_critical: false
      top_gaps: ["the cheap walk_forward leakage/determinism suite is not in the curated CI-blocking subset"]
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["walk_forward duplicate-id check is O(n^2); per-window train rebuild is O(windows*markets) — cold backtest path only"]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — run CalibrationBucketStrategy through walk_forward on a real, point-in-time, non-survivorship resolved-market panel and report a cost-net OOS weekly-PnL series. THE binding constraint."
    - "run_risk_readiness: persist kill-switch + realized-PnL counters to the durable DB and rehydrate on init — a restart must not silently un-trip a tripped kill switch."
    - "security: add a shared-secret bearer token on the backend's state-mutating routes (kill-switch, config, execution) so the gate is credential-protected server-side, not just network-isolated."
    - "design_taste: delete the dead fabricated-data equity-chart.tsx and fix the portfolio bar chart baseline/axis labels."
    - "correctness/tests: add a correctness-only ruff gate (F811/F821/E7/E9) to CI and add the cheap walk_forward suite to the curated preflight subset."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **business_case_strength is B** (ship-critical), so the quality gate fails —
and independently the full `preflight.sh` is honest-RED (`floor_met_year1: false`, 10 DoD
boxes unchecked). Both reflect the same truth: **a validated, reproducible, cost-realistic
out-of-sample edge does not exist yet.** The engine to *find and prove* one is, however,
of genuinely high quality.
