# QUALITY MEMORY — LLM-Quant

> Append-only log of the independent Quality Auditor's grades. Read this **first** each
> run and diff against the last grade. Owned by the auditor; never written by the maker.

---

## 2026-07-05 — overall `B` · ship gate NOT met (4th grade — functional_reality recovered B→A; 3 A→A+ nits closed; business_case still the lone binding B)

**Diff vs 2026-07-03:** overall unchanged at **B**, but the composition genuinely
improved. **`functional_reality` recovered B→A** — the 2026-07-03 ship-critical gap is
**fixed and verified**. Now **only one** ship-critical dim is below A
(`business_case_strength`, B — same binding constraint as 2026-07-01), and this cycle's
research made that no-edge finding **stronger**, not weaker.

**What the factory closed since 2026-07-03 (verified, not trusted):**
- **functional_reality B→A (#165/#202)** — the synthetic `volume=10000`/`liquidity=5000`
  fabrication on the Gamma-zero-volume path is **gone**. `_mark_unavailable_data`
  (`strategies.py:1374-1399`) now sets `volume_unavailable`/`liquidity_unavailable`
  **flags** and leaves volume/liquidity at honest `0`; the filters
  (`polymarket_client.py:90-107`) *neutralize* on the flag rather than pass on a synthetic
  number. A zero-volume degraded market surfaces via a genuine **skip**. Pinned by a real
  regression test (`test_data_availability_flags.py`, asserts `"$10,000" not in
  results[0].reason`). Fresh adversarial grader confirmed by reading the code + running the
  test. **#165 and #202 resolved.**
- **run_risk_readiness A→A+ nit closed (#207)** — durable restart-survival is now tested
  through the production `get_executor()` singleton seam
  (`test_executor_state_persistence.py:213-232`): trips a real `record_realized_pnl(-15.0)`
  loss-cap breach, drops the singleton, asserts the halt + budget survive. Held at **A**.
- **design_taste A→A+ nit closed (#206)** — positions-tab "Unrealized" shows `—` until
  loaded (`page.tsx:867-871`), matching the portfolio tab's null-honesty bar.
- **artifact A→A+ nit closed** — `ruff.toml` comment now accurately describes the shipped
  correctness-only E9/F821/F811 gate (no longer claims full-lint enforcement is withheld).
- **correctness — two genuine safety fixes verified**: SELL-to-open-a-short is rejected at
  the risk gate *before* the unconditional fill (`execution.py:956-964`,
  `test_short_open_rejected.py`), closing the phantom-fill/loss-cap bypass (**#215**); a
  resolved position now settles into the loss caps **at most once across a restart** via
  persist-before-count + defer-on-probe-failure (`orchestrator.py:417-432,519-528`, **#204**).

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**
  (import smoke + curated tests + safety + secrets + runtime harness + scorecard-parse +
  self-validation coverage all OK; full ruff skipped in CI by design).
- `scripts/runtime_harness.py` → **PASSED**: live gate REJECTS real order, kill switch
  blocks, max-position cap rejects $900>$50, loss cap trips **net-of-fees** at −$41.20 vs
  −$10 and blocks subsequent orders; paper fills, deterministic.
- `scripts/run_walk_forward.py` twice → **reproduces** bit-identically (`seed_hash
  b3a8d5e0e9579853`, total PnL 910,880.71; SYNTHETIC demo, labeled NOT a validated edge).
- `scripts/validate_real_oos.py` → the leak guard **refuses to fabricate a decision-time
  price**: every market without a pre-resolution tick is SKIPPED, not invented (Polymarket
  + Kalshi; Kalshi leg egress-throttled 429). No fabricated fills.
- `ruff check backend/app --select E9,F821,F811` → **clean**; full ruff → **131** cosmetic.
  Secret scan clean (only `.env.example`).

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **A** (↑ from B), backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A**, tests_evals **A**, performance **A**.

**Backtest integrity (make-or-break) — reproduction attempted again + edge honesty
audited:** leak-free (structural `MarketView` guard omits outcome+resolution_time; fetchers
reject any tick `> decision_ts`/`>= resolution_ts` and RAISE rather than fabricate),
cost-realistic (single source of truth with the executor, pinned by `test_cost_model`),
reproducible (identical hash + PnL across two runs). **The candidate alpha was REFUTED, not
inflated:** the price-bucket-calibration family (EXP-002/B4a static + recency) was tested
across **four real corpora** (−$2,938 @ n=510, +$3,330 @ n=799, −$2,947 @ n=621, HF
crowd-pinned artifact) and honestly declared **CONFIRMED noise, not an edge**
(`RESEARCH_MEMORY.md`, Run 15). The prior −$480.86 probe is now correctly understood as
small-sample noise. **No unreproducible backtest, no fabricated PnL, no fabricated edge.**
Held at **A** (not A+): the impact/capacity term is an uncalibrated `impact_coeff=0.5`
placeholder.

**Anti-inflation notes (held grades at A, not A+):**
- **artifact_integrity** — the grader leaned A− on the #240 finding: the commit *subject*
  ("§34 pre-launch funnel — public demo of the core aha") reads as a shipped feature, but
  the diff is **spec-only** (+32 lines `FACTORY_STANDARD.md §34`, explicitly a no-op for a
  personal tool). Internally honest — **there is no demo displaying invented numbers**, so
  the feared artifact failure does not materialize. Graded **A** with the framing nit named
  (prefer `docs/spec:` over feature framing when the diff adds no product code).
- **correctness_reliability** — genuine determinism + two real bypass fixes, but a named
  non-blocking gap remains: the SELL/partial-reduce path feeds the executor hard caps (the
  binding kill-switch trigger) but not yet the per-strategy drawdown circuit
  (`risk_manager.record_pnl`). Secondary (resolution is the dominant loss path; hard caps
  wired) → **A**, not a downgrade to B.

**Overall = B:** the sole ship-critical dim below A is **business_case_strength** (no
validated OOS edge; the only non-crowd alpha family is now refuted across four corpora —
THE binding constraint). Ship gate correctly closed.

**Issues:** **#79 kept open + updated** (business case — unchanged binding constraint,
reinforced by the 4-corpora refutation). **#202 + #165 CLOSED** (functional_reality
fabrication verified fixed). **#125 CLOSED** (all four items + the three follow-on A→A+
nits — ruff.toml comment, positions-tab honesty, get_executor seam — now resolved).

**Weakest link (honest):** still no validated out-of-sample edge — and this cycle the
factory earned credit by running its own candidate alpha to a **REFUTED** verdict rather
than curve-fitting it. Everything downstream stays gated correctly and honestly.

---

## 2026-07-03 — overall `B` · ship gate NOT met (3rd grade — 4 of 5 #125 nits closed; a new ship-critical integrity gap surfaced)

**Diff vs 2026-07-01:** overall unchanged at **B**, but the composition shifted.
**Four of the five #125 A→A+ hardening nits are genuinely fixed** (auth default-closed,
suite-ordering, correctness ruff gate, dashboard header honesty) — verified, not trusted.
Against that, one dimension I hold **lower** than the last grade: **functional_reality
A→B**. Not a code regression — a real integrity gap the 2026-07-01 grade **missed** and
this run's adversarial grader caught + I confirmed by reading the code. Overall stays B;
now **two** ship-critical dims are B (business_case + functional_reality).

**What the factory closed since 2026-07-01 (verified):**
- **security** — mutating-route auth is now **default-CLOSED**: an unset `BACKEND_API_TOKEN`
  → **401 DENY** (`auth.py:47-61`), `BACKEND_AUTH_DISABLED` the sole dev opt-out, fail-closed
  on a settings-read error; `test_backend_auth_fastapi.py` proves it. Resolves **#125 item 1**.
- **correctness** — the SQLModel `DeclarativeMeta` dual-registration order-dependence is
  **gone**: the pandas-free suite passes **identically in default and fully-reversed file
  order** (951 passed), all test imports standardized to `app.*` (`eb615c9`). Resolves **#125 item 2**.
- **artifact/correctness** — a **correctness-only ruff gate** (`--select E9,F821,F811`) is
  enforced in CI (`preflight.sh:129` + ruff in `requirements-ci.txt`) and passes clean.
  Resolves **#125 item 3** (the "enforce a correctness gate" branch), *except* the
  `ruff.toml:3-7` comment was left stale — see the artifact nit below.
- **design_taste** — the header stat row + strategy strip now show **"—" when unloaded**
  (`page.tsx:574,604-613`), no hardcoded `+$0.00`. Resolves **#125 item 4**.
- Curated suite **634 → 894** passing; loss caps are now **net of fees** (`#192`), CLOB
  prices coerced to `[0,1]` at source (`#193`), gated-live REST fill sets `filled_price`
  None-safely (`#199`), cross-venue coherence matcher added (`#179`).

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN,
  894 passed / 1 xfailed**; full gate → honest-**RED** (`floor_met_year1: false`, 10 DoD
  boxes, quality NOT-READY).
- `scripts/runtime_harness.py` → **PASSED** (live gate REJECTS real order, kill switch
  blocks, max-position cap rejects, paper FILLS, deterministic, loss cap net-of-fees trips
  the kill switch at net **−$41.20** vs −$10 and blocks subsequent orders).
- `scripts/run_walk_forward.py` twice → **reproduces** (`seed_hash b3a8d5e0e9579853`,
  identical PnL; labeled SYNTHETIC). `validate_real_history.py` → **0 trades / $0**
  (`8dc358439ffb5746`, honest). **NEW: `validate_real_oos.py`** → the B4a alpha ran on
  **real Polymarket history (n=52)**: **3 trades, net −$480.86** — an honest **LOSS**,
  explicitly "NOT a validated edge"; Kalshi leg egress-blocked (429).
- `ruff check backend/app --select E9,F821,F811` → **clean**; full ruff → **131 findings**
  (cosmetic; down from 164). Secret scan clean (only `.env.example` committed).

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **B** (↓ from A), backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A**, tests_evals **A**, performance **A**.

**Anti-inflation overrides (held two grades DOWN):**
- **run_risk_readiness** — the grader recommended **A+** (kill switch wired, loss cap
  net-of-fees conservative, durable state fail-closed, HUMAN-CORE intact). I **held it at
  A**: the prior named coverage nit still stands — `test_executor_state_persistence.py`
  (13 tests) never exercises the production `get_executor()` singleton seam end-to-end. A
  world-class dim with a real named coverage nit is the textbook A, not A+.
- **functional_reality** — graded **B**, below the prior A. The pipeline genuinely runs
  end-to-end (real n=52 OOS trades, real paper fills, fail-closed live gate), but
  `strategies.py:1451-1457` **fabricates** `volume=10000`/`liquidity=5000` on the
  Gamma-zero-volume path, and those values clear every filter threshold (`min_volume`
  1000/5000; `min_liquidity` 500/1000), flipping real BUY-gate decisions on invented
  liquidity. Fabricated data in the live decision path is a real named gap = B, not a
  trivial nit. This is issue **#165** (previously MED); it now caps a ship-critical dim.

**Backtest integrity (make-or-break) — reproduction attempted again:** leak-free
(structural `MarketView` guard; fetchers reject any tick `> decision_ts`/`>= resolution_ts`
and RAISE rather than fabricate), cost-realistic (single source of truth with the
executor), reproducible (identical hashes + PnL across two runs). The only real result is
a **loss**, honestly labeled. **No unreproducible backtest, no fabricated PnL, no
fabricated edge found.** Held at **A** (not A+): impact term is an uncalibrated toy and
n=52/3-trades is statistically meaningless.

**Overall = B:** two ship-critical dims below A — `business_case_strength` (no validated
OOS edge; the sole real probe is a loss — THE binding constraint) and `functional_reality`
(synthetic data on the degraded BUY path). Ship gate correctly closed.

**Issues:** **#79 kept open** (business case — unchanged binding constraint). **#165
elevated** via an auditor comment: it now caps a ship-critical dimension at B (was a MED
enhancement). **#125 updated**: 4 of 5 items closed; only the stale `ruff.toml:3-7` comment
+ the positions-tab honesty nit + the singleton-seam coverage nit remain.

**Weakest link (honest):** still no validated out-of-sample edge — and this run added a
second, narrower honesty gap (fabricated liquidity on degraded data). Both are the same
discipline: never let a number that isn't real drive a decision.

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
