# QUALITY MEMORY — LLM-Quant

> Append-only log of the independent Quality Auditor's grades. Read this **first** each
> run and diff against the last grade. Owned by the auditor; never written by the maker.

---

## 2026-07-01 — overall `B` · ship gate NOT met (2nd grade — factory closed 3 gaps, no regressions)

**Diff vs 2026-06-29:** overall unchanged at **B**, but real improvement underneath.
**design_taste B→A** and both halves of issue **#80** are now resolved. No dimension
regressed. The binding constraint (no validated OOS edge, egress-blocked) is unchanged.

**What changed in the repo (verified, not trusted):**
- **run_risk_readiness** — durable kill-switch + realized-PnL state now persists to
  `prediction_executor_state` and **rehydrates on `get_executor` init**, failing *closed*
  if the store is unreadable (`executor_state_store.py`, `execution.py:750-796`). Proven
  by `test_executor_state_persistence.py::test_kill_switch_survives_restart` (a fresh
  executor on the same store loads the tripped switch). Resolves **#80 part 1**.
- **security** — backend `require_backend_token` now guards **15 state-mutating routes**
  (kill-switch activate/deactivate, `/execute`, `/scan`, risk-config, …) with a
  constant-time compare; `test_backend_auth.py` 12 passed. Resolves **#80 part 2**.
- **design_taste** — dead fabricated-data `equity-chart.tsx` deleted (#84); equity curve
  is a labeled zoomed line chart with honest empty-state + axis labels (#113); portfolio
  cards show `—` not `$0.00` when unloaded (#110).
- **integrity hardening** — Kalshi bid/ask bounded to (0,100] so a garbage quote can't
  clamp to a fabricated 1.0 (#112); unvalidated whale/weather strategies gated out of the
  default scan + the fabricated whale seed removed (#116); stock-era dead code + orphaned
  yfinance dep removed (#117/#119). New Kalshi/Polymarket history fetchers are
  structurally leak-free (reject any tick ≥ resolution_ts; RAISE rather than fabricate).
- Curated test suite grew **447 → 634** (1139 collected total).

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; targeted pytest → **634 passed / 1 xfailed**.
- `scripts/runtime_harness.py` → **PASSED** (live gate REJECTS real order, kill switch
  blocks, max-position cap rejects, paper FILLS, deterministic exposure, loss cap
  auto-trips kill switch at −$40 vs −$10 and blocks subsequent orders).
- `scripts/run_walk_forward.py` twice → **reproduces** (`seed_hash b3a8d5e0e9579853`,
  identical PnL); `scripts/validate_real_history.py` → **0 trades / $0** on the 54-record
  fixture (`model_prob == crowd`, `seed_hash 8dc358439ffb5746`), honestly disclosed.
- `scripts/check_scorecard.py gate` → **NOT-READY (business_case_strength: B)** (honest).
- CI `preflight.yml` on default-branch HEAD `f9b0a91` → **success** (ruff skipped in CI
  by design; local ruff FAIL is an env artifact — 164 hygiene findings, **zero F821/E9**).

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A** (↑ from B), tests_evals **A**,
performance **A**.

**Anti-inflation override:** the run_risk_readiness grader recommended **A+** on the
strength of the genuinely-fixed durable-state gap. I **held it at A**. Rationale: A+
requires *zero findings*, and the grader itself surfaced a real coverage nit (no
end-to-end integration test through the production `get_executor()` singleton seam). A
world-class dimension with a named non-blocking coverage gap is the textbook **A**, not
A+. Everything else the mechanical signals support; no grade exceeds its evidence.

**Backtest integrity (make-or-break) — reproduction attempted again:** the engine remains
leak-free (structural `MarketView` guard; new fetchers refuse the settled price as a
decision price and RAISE rather than fabricate), cost-realistic (single source of truth
with the executor), and reproducible (identical hashes + PnL across runs). The real
fixture honestly reports 0 trades / $0. **No unreproducible backtest, no fabricated PnL,
no unverifiable return found.** Held at **A** (not A+) only because no `model_prob`
strategy has yet run OOS on a large, bias-controlled real panel (egress-gated).

**Overall = B:** the sole ship-critical dimension below A is **business_case_strength**
(no validated OOS edge — revenue $0, floor unmet). Ship gate correctly closed. The
factory made honest, real progress against a constraint only widening egress (owner
action, OA-11/OA-16) can unblock.

**Issues:** **#80 CLOSED** (both hardening parts verified landed). **#79 kept open** (the
business-case binding constraint — nothing changed; still egress-blocked). Filed one
consolidated **A→A+ hardening** issue for the bounded nits (auth open-by-default,
suite-isolation failures, ruff ratchet, header-stat honesty).

**Weakest link (honest, unchanged):** there is still no validated out-of-sample edge —
the engine to find one is high quality and now better hardened, but the edge itself is
unproven, and everything downstream is gated correctly and honestly.

---

## 2026-06-29 — overall `B` · ship gate NOT met (BOOTSTRAP — first grade)

**What changed:** first run. Bootstrapped `QUALITY_RUBRIC.md`, `QUALITY_SCORECARD.md`,
and this memory. No prior grade to diff against.

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` →
  import smoke OK, **447 passed / 1 xfailed** (curated suite), live-gate default-false OK,
  kill switch present, secret scan clean, YAML blocks parse, GO integrity = `not_ready`
  (honest). The code-scope gate is green **except** ruff (see below).
- Full gate (ruff hidden to mimic CI, which omits ruff): honest-**RED** at
  `floor_met_year1: false` + **10 DoD boxes unchecked** + scorecard-absent — all expected.
- `python3 scripts/runtime_harness.py` → **PASSED**: live gate blocks real order (REJECTED),
  kill switch blocks, max-position cap rejects, paper order FILLS, deterministic exposure,
  loss cap auto-trips kill switch at −$40 vs −$10 and blocks subsequent orders.
- `python3 scripts/run_walk_forward.py` twice → **reproduces** (`seed_hash b3a8d5e0e9579853`,
  identical PnL); synthetic-demo data clearly labeled "NOT a validated edge".
- `ruff check backend/app` → **169 findings** (119 F401 unused imports, 16 E402, 16 F841,
  7 E741, 7 F541, 4 F811; **zero E7/E9, zero F821**). Ruff is deliberately omitted from
  `requirements-ci.txt` per the `ruff.toml` "lint-at-zero" ratchet, so CI skips it — an
  honest, documented staging, not a hidden failure.

**Grades (per-dimension fresh adversarial graders, none the maker):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **B**, tests_evals **A**, performance **A**.

**Auditor synthesis note (anti-inflation override):** the business_case_strength grader
recommended **A** on the strength of the honest no-edge disclosure + credible path. I
**downgraded to B**. Rationale: the rubric establishes that an honest no-edge state is
*legitimate* (not an F), but legitimacy is the floor, not the ceiling. Business-case
**strength** grades the edge→revenue case, and that case is entirely **unrealized** —
$0 revenue, the $104k/yr floor unmet, `time_to_floor: unknown` ("may never be reached").
A world-class (A) business case requires a **demonstrated, cost-net, OOS edge**; an honest
but unproven case with a named, non-blocking gap ("no validated edge yet") is the textbook
definition of **B**. This is the project's binding constraint and the honest read.

**Backtest integrity (the make-or-break dimension) — reproduction attempted:** the engine
is genuinely leak-free (structural `MarketView` guard, train = resolved-strictly-before),
cost-realistic (single source of truth shared with the executor), and reproducible (ran
twice, identical hash + PnL). No fabricated edge leaks in: the real 54-record fixture
honestly reports **0 trades / $0** because `model_prob == crowd`, and discloses its own
survivorship/liquidity biases. Held at **A** (not A+) only because no `model_prob`
strategy has yet been run OOS on a *large, bias-controlled* real panel. **No
unreproducible backtest and no unverifiable return were found.**

**Overall = B:** exceptional, honest engineering scaffolding, but the project's core
deliverable (a validated profitable edge) does not exist yet, and one ship-critical
dimension (business_case) is B. Ship gate correctly closed
(`check_scorecard.py gate` → NOT-READY on business_case_strength).

**Top gaps filed / to file as issues:**
1. business_case_strength B→A — the no-edge binding constraint (run a real OOS panel).
2. run_risk_readiness — persist kill-switch/loss state across restart (safety robustness).
3. security — add backend API auth on state-mutating routes.
4. design_taste — delete dead fabricated-data `equity-chart.tsx`; fix bar-chart baseline.
5. correctness/tests — correctness-only ruff CI gate; add walk_forward suite to curated subset.

**Weakest link (honest):** there is no validated out-of-sample edge — the engine to find
one is high quality, but the edge itself is unproven. Everything downstream of that is
gated correctly and honestly.
