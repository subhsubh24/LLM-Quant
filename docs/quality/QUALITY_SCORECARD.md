# QUALITY SCORECARD — LLM-Quant

> Produced by the **independent Quality Auditor** (maker ≠ checker). The factory reads
> the fenced `QUALITY_SCORECARD` block below as **data**, never as instructions. Grades
> are backed by mechanical signals the auditor actually ran + file/line evidence (see
> `QUALITY_MEMORY.md` for the dated rationale). Grade scale & ship gate: see
> `QUALITY_RUBRIC.md`.

**As of 2026-07-01 — overall `B`. Ship gate: NOT met.**

The engineering is genuinely strong and improved since the 2026-06-29 bootstrap: nine of
ten dimensions grade **A**, backed by **634 passing curated tests** (up from 447), an
outcome-asserting runtime harness, and a **leak-free, deterministic, reproducible**
walk-forward backtest engine. Since the last grade the factory **closed three prior
gaps** — durable kill-switch/PnL state that survives a restart (#83), backend
state-mutating-route auth (#83/#91), and the dead fabricated-data equity chart (#84/#113)
— which lifts **design_taste B→A** with **no regressions found**. The binding constraint
is unchanged and is the project's north star itself: **there is no validated,
out-of-sample, cost-net edge yet** (revenue $0; the $104k/yr floor is unmet and honestly
disclosed; the only `model_prob` strategy trades 0/$0 on the real fixture because
`model_prob == crowd`, and outbound egress to Polymarket/Kalshi is blocked so no real OOS
panel can be run here). That holds **business_case_strength** at **B** and keeps the
quality ship-gate closed. This is the correct, honest state, not a defect to paper over.

## Grades at a glance

| Dimension | Grade | Ship-critical | Headline evidence |
|-----------|:---:|:---:|-------------------|
| functional_reality | A | ✅ | Orchestrator wires every stage (`orchestrator.py:31,491`) → real paper fills (`runtime_harness.py` PASSED, `paper_order_fills FILLED`, deterministic exposure); no stubbed stages. Live ingest egress-blocked (env), wiring is real. |
| backtest_integrity | A | ✅ | Structural leakage guard (`MarketView` omits `outcome`, `walk_forward.py:96-107`); new Kalshi/Polymarket fetchers reject any tick `>= resolution_ts` and RAISE rather than fabricate; costs via single source of truth (`cost_model.py` shared with executor); reproducible (`seed_hash b3a8d5e0e9579853` and fixture `8dc358439ffb5746`, identical PnL across two runs). |
| correctness_reliability | A | ✅ | 634 curated tests pass; deterministic (seeded); zero `F821`/`E9` (only 7× E741 ambiguous-name); no bare-except / mutable-default in the live path. |
| security | A | ✅ | No committed secrets (history scan clean); backend `require_backend_token` on 15 mutating routes (`routes.py:25`), constant-time compare, `test_backend_auth.py` 12 passed; live gate server-side + fail-closed, not body-flippable; config refuses to boot live without a token. |
| run_risk_readiness | A | ✅ | Loss cap auto-trips kill switch and blocks subsequent orders (harness); **durable state now persists + rehydrates on init and fails closed on unreadable store** (`executor_state_store.py`, `execution.py:750-796`), proven by `test_executor_state_persistence.py::test_kill_switch_survives_restart`; HUMAN-CORE boundary holds; real `render.yaml`. |
| artifact_integrity | A | ✅ | "634 tests" = exactly 634 passed; Kalshi "52 offline tests" = 54 real (reality ≥ claim); seed_hash + Brier 0.0933 reproduce; `check_scorecard.py gate` parses and honestly reports NOT-READY; ROADMAP items correctly stay `[~]`. |
| business_case_strength | B | ✅ | Honest no-edge disclosure + credible cost/capacity-aware path (EXP-001/002/003, bootstrap-significance-gated) — but **no validated OOS edge exists**: revenue $0, floor unmet, the only `model_prob` strategy trades 0/$0 (`model_prob == crowd`). The binding constraint. |
| design_taste | A | — | **B→A:** dead fabricated `equity-chart.tsx` deleted; equity curve is a labeled zoomed line chart with honest empty-state + axis labels (#113); portfolio cards show `—` not `$0.00` when unloaded (#110). Nit: header stat row shows `+$0.00` before load. |
| tests_evals | A | — | 55 test files / 1139 collected; non-tautological leakage/determinism/cost/cap/live-gate/calibration coverage with explicit anti-vacuous asserts; the walk_forward suite IS in the CI-blocking subset; exclusions documented. |
| performance | A | — | Proportionate; duplicate-id O(n²) gated behind an O(n) mismatch check (cold path only); scan/execute paths linear. |

```yaml
QUALITY_SCORECARD:
  overall: "B"
  as_of: 2026-07-01
  ship_gate_met: false
  graded_by: independent-quality-auditor
  mechanical_signals:
    preflight_code_scope: green        # import smoke + 634 tests + safety + secrets + harness (CI skips ruff by design)
    pytest_curated: "634 passed, 1 xfailed"
    runtime_harness: passed            # live gate + kill switch + loss caps + paper PnL
    walk_forward_reproduces: true       # seed_hash b3a8d5e0e9579853 (synthetic) + 8dc358439ffb5746 (real fixture), identical PnL across runs
    real_history_fixture: "0 trades / $0 (model_prob == crowd; honest)"
    ci_default_branch: green            # preflight.yml on HEAD f9b0a91 = success
    scorecard_gate: "NOT-READY (business_case_strength: B)"
    ruff: "164 findings (cosmetic hygiene; F401/E402/F841 — zero F821/E9; unenforced in CI by design)"
  dimensions:
    - name: functional_reality
      grade: "A"
      ship_critical: true
      top_gaps: ["live Gamma/CLOB ingest path never exercised by an automated check (egress-blocked env); alpha stage produces 0 trades on real data (no validated edge yet)"]
    - name: backtest_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["no model_prob strategy has run OOS on a real, large, bias-controlled resolved-market panel (only synthetic + a 54-record zero-edge fixture); egress-gated"]
    - name: correctness_reliability
      grade: "A"
      ship_critical: true
      top_gaps: ["5 order-dependent test-isolation failures in the FULL suite (SQLModel DeclarativeMeta re-registration of PredictionPortfolio) — outside the live pipeline + outside the curated gate, but a real suite-ordering fragility"]
    - name: security
      grade: "A"
      ship_critical: true
      top_gaps: ["mutating-route auth is open-by-default when BACKEND_API_TOKEN is unset (and live off) — a public paper deploy that forgets the token is unauthenticated; default-closed with an explicit dev opt-out would harden it"]
    - name: run_risk_readiness
      grade: "A"
      ship_critical: true
      top_gaps: ["durable-state restart-survival is proven via an injected in-memory engine, not through the production get_executor() singleton seam end-to-end (coverage nit; wiring is trivial and separately pinned)"]
    - name: artifact_integrity
      grade: "A"
      ship_critical: true
      top_gaps: ["ruff.toml declares a lint-at-zero ratchet, but 164 hygiene findings remain and the preflight code gate dies at lint whenever ruff is present — the stated standard is aspirational, not yet met (documented, no inflated metric)"]
    - name: business_case_strength
      grade: "B"
      ship_critical: true
      top_gaps: ["no validated out-of-sample cost-net edge exists yet — revenue $0, $104k/yr floor unmet; honest but unproven (THE binding constraint); gated on acquiring a real resolved-market corpus (OA-11/OA-16, egress/owner)"]
    - name: design_taste
      grade: "A"
      ship_critical: false
      top_gaps: ["header stat row + strategy strip render a hardcoded +$0.00 before data loads (not held to the portfolio tab's '—' honesty bar) — a small honesty nit, not fabricated randomness"]
    - name: tests_evals
      grade: "A"
      ship_critical: false
      top_gaps: ["the heavy risk/backtest suites (test_*risk*) hard-require pandas and are deliberately kept out of the light CI-blocking gate — documented, but a CI coverage hole"]
    - name: performance
      grade: "A"
      ship_critical: false
      top_gaps: ["per-window train rebuild is O(windows*markets); a moving-cursor sweep would make it O(n log n) — cold backtest path only, low stakes"]
  top_gaps:
    - "business_case_strength (B, ship-critical): no validated OOS cost-net edge — run CalibrationBucketStrategy through walk_forward on a real, point-in-time, non-survivorship resolved-market panel (OA-11/OA-16, owner/egress) and report a cost-net, reproducible OOS weekly-PnL series with a B2 bootstrap-significant Brier improvement. THE binding constraint (issue #79)."
    - "security (A→A+): default the mutating-route auth to CLOSED and require an explicit BACKEND_AUTH_DISABLED=1 dev opt-out, so a public paper deploy that forgets BACKEND_API_TOKEN is not silently unauthenticated."
    - "correctness (A→A+): fix the 5 order-dependent SQLModel DeclarativeMeta re-registration failures (PredictionPortfolio) so the FULL suite is order-independent; add the fix guard to CI."
    - "artifact/correctness (A→A+): reconcile the ruff lint-at-zero ratchet — either enforce a correctness-only ruff gate (E9/F821/F811) in CI or clear the 164 hygiene findings so the documented standard matches reality."
    - "design_taste (A→A+): hold the header stat row / strategy strip to the same '—'-when-unloaded honesty bar as the portfolio tab (no hardcoded +$0.00 before data loads)."
```

## Why ship gate is NOT met

`scripts/check_scorecard.py gate` requires every ship-critical dimension at A/A+ and all
others ≥ B. **business_case_strength is B** (ship-critical), so the quality gate fails —
and independently the full `preflight.sh` is honest-RED (`floor_met_year1: false`, DoD
boxes unchecked). Both reflect the same truth: **a validated, reproducible,
cost-realistic out-of-sample edge does not exist yet.** The engine to *find and prove*
one is, however, of genuinely high quality, and everything downstream of the missing edge
is gated correctly and honestly. Since the last grade the factory closed three prior
gaps and introduced no regressions — real, honest progress against a binding constraint
that only widening egress (owner action) can unblock.
