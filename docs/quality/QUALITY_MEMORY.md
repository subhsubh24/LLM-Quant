# QUALITY MEMORY — LLM-Quant

> Append-only log of the independent Quality Auditor's grades. Read this **first** each
> run and diff against the last grade. Owned by the auditor; never written by the maker.

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
