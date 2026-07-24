# QUALITY MEMORY — LLM-Quant

> Append-only log of the independent Quality Auditor's grades. Read this **first** each
> run and diff against the last grade. Owned by the auditor; never written by the maker.

---

## 2026-07-24 — overall `C` (↓ from B) · ship gate NOT met (10th grade — the largest downward revision in project history, and MOST OF IT IS A CORRECTION OF MY OWN PRIOR GRADES, not a factory regression)

**Diff vs 2026-07-17:** overall **B → C**. **Seven dimensions moved down:**
`correctness_reliability` **A+ → C**, `backtest_integrity` **A → B**, `functional_reality` **A → B**,
`artifact_integrity` **A → B**, `design_taste` **A → B**, `tests_evals` **A+ → B**,
`performance` **A → B**. `security` **A+ → A**. Held: `run_risk_readiness` **A**,
`business_case_strength` **B** (still the binding business constraint).

**READ THIS FIRST — the honest framing.** Of the seven downgrades, **five rest on defects that
PRE-DATE this cycle** and that my own prior grades missed: the Metrics-tab 404s (introduced
2026-07-17), the unseeded Monte-Carlo pricer, the O(n²) rescan, the fabricated MC sizing
parameters, and the doc/code drift. **The failure mode was mine.** Prior cycles graded several
dimensions by inference — *"`git diff --stat` since the last grade is empty ⇒ the prior grade
holds"* — most explicitly `design_taste` on 2026-07-17 ("static (already-good), no advancement").
That is not grading; that is assuming. A dimension with no diff can still be wrong, and this
cycle it was: a one-line-per-URL prefix bug had the entire Metrics tab rendering six HTTP-404
error cards the whole time. **Lesson for every future run: never let "no diff" substitute for a
mechanical signal. Re-verify the artifact, not the diff.**

**The one genuinely NEW defect — a reproducibility-fingerprint hole (cross-verified 3×):**
`_seed_hash` does not fingerprint `m.category`, but since #388/#404 `category` is
**PnL-determining** whenever either per-category cap is active (`walk_forward.py:540-552`,
`cat_room` sizes the trade DOWN). I reproduced it myself — two datasets identical in every
fingerprinted field, differing ONLY in category labels:
`category_exposure_cap=0.10` → **same hash `0bf8214f4c56f8a6`**, trades 5 vs 15, PnL $3,769.24 vs
$5,811.48; `cap=0.20` → **same hash**, PnL $4,961.66 vs $12,948.43 (**2.6×**). An independent
grader extended it to the cumulative lane at **3.9×**, defeating the `effective_cumulative_cap`
mitigation (`walk_forward.py:459-466` keys on distinct-category **count**, so
same-count-different-assignment collides). The engine's own comment (`walk_forward.py:669-673`)
asserts *"category … never affects a decision or PnL"* as fact, and a gate test
(`test_walk_forward_category.py:50`) **pins the false invariant** while only exercising the
cap-free case. This is the same bug class the repo itself caught and fixed for `fee_schedule`
in #413 — applied incompletely.

**Bounding it honestly — NO PUBLISHED NUMBER IS WRONG.** `b3a8d5e0e9579853` (synthetic) and
`79a4cca4b966138f` / −$3,228.02 (frozen corpus) are both cap-free and both reproduced
**sha256-identical** under my own hands. I initially called the hole "latent"; **a grader
corrected me and was right**: the cumulative lane **binds** on the frozen corpus (39→27 trades,
−$3,228.02→−$1,684.13, `top_category_budget_share` 0.3816→0.2445) and **publishes**
`seed_hash 2e4380ec2cd1f9c6` — a hash that cannot distinguish a different category assignment. I
verified that correction directly before recording it. What is unsound is the claim that the
hash *certifies* a capped run, not any committed result.

**What the factory genuinely earned — residual (a) CLOSED (#377).** A **real** (not synthetic)
OOS result now reproduces **offline from committed bytes**: `data/real_oos_corpus_polymarket.json`
(187 records) + `--from-corpus` → byte-identical across two runs, 39 trades, **−$3,228.02**, F11
**significant_negative**. I verified the corpus invariants directly: uniform **7.0-day** decision
lead, **zero** records with `decision_time >= resolution_time`, all `research_only: false`, zero
`0x` addresses, base rate 0.246 matching the reported `yes_base_rate`. A grader confirmed the
loader **fails loud** on every shape mutation (`outcome=2`, price out of range, resolution ≤
decision, duplicate ids) and that injected leakage is caught by a committed test. This closes the
exact A→A+ gap the last two scorecards named, and is why `backtest_integrity` is a **B**, not lower.

**Research — two honest nulls, faithfully reported.** EXP-006 fade-the-spike got its first
real-data OOS run (#390: N=108, +$285.44 but F11 `indistinguishable_from_zero`, F10 fragile;
large spikes |move|≥0.25 N=43 **LOSE** −$657.34 at 33% hit) and then a pre-registered 60-cell
surface (#393): **0/60 validate**, 0 significant_positive, 18 significant_**NEGATIVE**, every
positive-PnL cell also F10-fragile, and the tool **refuses to select a cell**. EXP-006 joins
bucket-calibration as **REFUTED**. EXP-010 (#410) re-scored the corpus under Polymarket's **real**
price-dependent per-category fee — making the refutation **worse** (−$3,228 → −$3,502) — and the
loop reported that faithfully rather than keeping the kinder flat model. The fee formula
`fee = C × feeRate × p × (1−p)` was verified **verbatim against docs.polymarket.com**. Both nulls
reproduced exactly.

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**
  (runtime harness passed, scorecard parses, self-validation 16 capabilities `unmet=[]`).
- Full `scripts/preflight.sh` → **honest-RED** (`floor_met_year1: false`, 10 DoD boxes, quality
  below the go-live bar).
- `scripts/run_walk_forward.py` ×2 → **sha256-IDENTICAL** (`c7d628ef…`), seed 42 / hash
  `b3a8d5e0e9579853`, PnL 910,880.71 (SYNTHETIC, labeled NOT a validated edge).
- `scripts/validate_real_oos.py --from-corpus …` ×2 → **sha256-IDENTICAL** (`60bba984…`), n=187,
  39 trades, −$3,228.02, F11 significant_negative CI [−4325.52, −2403.58].
- `pytest` over the 78 preflight-registered files → **1374 passed / 1 xfailed / 0 skipped**;
  `--collect-only` → 1375 collected / 13 errors (all `No module named pandas`, documented).
- `ruff check backend/app --select E9,F821,F811` → clean (131 hygiene findings unenforced by design).
- Secret scan clean; ZERO `live_trading_enabled = True`; `next 14.2.35`.
- `check_scorecard.py gate` → **NOT-READY** on 5 ship-critical dimensions.

**Grades (fresh adversarial per-dimension graders, none the maker — 6 subagents covering all 10 dims):**
functional_reality **B**, backtest_integrity **B**, correctness_reliability **C**, security **A**,
run_risk_readiness **A**, artifact_integrity **B**, business_case_strength **B**, design_taste **B**,
tests_evals **B**, performance **B**.

**Anti-inflation check run in BOTH directions.** This cycle I gave graders pointedly adversarial
framing ("A+ is a high bar to HOLD — find a replacement finding"), which can manufacture findings.
So I personally re-verified every grade-moving defect before accepting it: the `_seed_hash`
collision (reproduced myself), the MC pricer (`orchestrator.py:212-236`, `use_monte_carlo` default
`True` at `:68`, 9 tests disabling it), the Metrics 404 (`MetricsPanel.tsx:88-103` vs
`main.py:146`, panel live at `page.tsx:1037`), the quadratic (`spike_detection.py:247-252`),
`ROADMAP.md:106`'s "48 test files" vs **93** actual, the fee-shape contradiction
(`GROWTH_STATUS.md:842` vs `cost_model.py:53-57`), and the broken `detect.mjs`. **Every downgrade
is backed by a defect I confirmed with my own hands — none rests on grader assertion alone.**
I also declined to over-punish: `tests_evals` stayed **B** and not lower because mutation testing
killed **10/10** mutants (the suite is genuinely non-tautological and there is **no** false-coverage
trap), and `business_case_strength` stayed **B** and not **C** because honest, reproducible negative
results are legitimate scientific progress even though they are not revenue.

**Why `correctness_reliability` fell A+ → C (the steepest drop, and the one I weighed longest):**
the dimension's stated A-bar names determinism explicitly, and determinism is broken **twice
independently** — the `_seed_hash`/category collision on the research lane, and an **unseeded**
`EnhancedContractPricer()` (`orchestrator.py:212`) on the **production-default** paper path
(`DETERMINISTIC? False`, ~1.7e-6). Add a latent swallowed-crash (`polymarket_client.py:892` lacks
the tz guard all four sibling parsers have; `orchestrator.py:885` swallows the resulting
`TypeError` into a permanent silent scan blackout) and a gate test pinning a false invariant.
More than one real gap, striking the dimension's core requirement, = **C**, not B. The prior **A+**
was plainly too high: the unseeded pricer pre-dates this cycle entirely and was never caught.

**Overall = C:** five ship-critical dimensions below A. Ship gate correctly closed.

**Issues:** **#79 kept open + refreshed** (business case — the binding constraint, now with the
stale-`BUSINESS_CASE.md` gap named). **New issues filed** for `correctness_reliability`,
`functional_reality`, `backtest_integrity`, `artifact_integrity` and the `design_taste`
Metrics-tab break.

**Weakest link (honest, unchanged):** there is still no validated out-of-sample edge, and **both**
mechanisms tested to date are now dead. The nearest thing to a validated result this project owns
is an honest, reproducible **loss** — correctly labeled, correctly gated, reaching no revenue
field. That discipline is why this is a C and not an F. The engineering around it needs a
correctness pass, not a rewrite.

---

## 2026-07-17 — overall `B` · ship gate NOT met (9th grade — `correctness_reliability` A→A+ PROMOTED (#338 closed the last named residual); everything else held; business_case still the lone binding B; EXP-006 grew as an honest PILOT, not a validated edge)

**Diff vs 2026-07-13:** overall unchanged at **B**. **Exactly one dimension crossed a threshold —
upward:** `correctness_reliability` **A → A+**. The other nine held exactly: functional_reality A,
backtest_integrity A, security A+, run_risk_readiness A, artifact_integrity A,
business_case_strength B, design_taste A, tests_evals A+, performance A. The binding constraint
(`business_case_strength`, B) is unchanged: still no validated OOS cost-net edge.

**Why correctness_reliability promoted (a genuine, bounded drive-to-A+):** for several cycles the
*sole* named residual on this dimension was `WalletBehaviorDivergence.confidence` emitting a
decoupled `_compute_confidence(...)` heuristic instead of the shared `gate_confidence(entry, edge)`
units contract (the #263/#268/#275/#280/#284 bug class). #338 closed it: `advanced_strategies.py:1254`
now emits `confidence = gate_confidence(avg_price, edge)`, `_compute_confidence` is DELETED repo-wide
(only a NOTE comment survives, `:1158`), and the regression test is non-tautological
(`test_confidence_units_gated.py:191-229` pins `confidence == entry_price+edge`, asserts
`not hasattr(strat, "_compute_confidence")`, includes a behavioral gate flip). A fresh adversarial
grader hunted for a REPLACEMENT paper-path finding — swallowed errors, mutable defaults, div-by-zero,
non-determinism — and found none (the live fill==limit approximation is a run-risk matter, not
paper-correctness; peak-relative drawdown can't self-trip on a never-positive strategy but is
globally backstopped by the hard loss caps — by-design, not a bug). Zero paper-path findings +
determinism verified = A+. This is the named, value-bar-clearing improvement the rubric asks for, not
inflation — the grade rose only because a real, verified fix removed the only thing holding it back.

**The research event this cycle — EXP-006 grown as an honest PILOT (Runs 21–25, negative-lag signal, NOT a validated edge):**
the loop scoped (Run 21: the "needs a NEW intraday fetcher" blocker was OVERSTATED — the existing CLOB
interval-candlestick path suffices) and grew a *pre-registered pilot probe* of EXP-006 (political
price-reversal after hype spikes). This is a **raw lag-1 autocorrelation probe, NOT a formal strategy
backtest** — no strategy code, no cost model, no F10/F11 gate. Runs 23/24/25 measured N=16 / 67
(volumeNum axis) / 14 (volume24hr axis, 2023–24 era), all with negative mean lag-1 autocorrelation and
bootstrap 95% CIs EXCLUDING zero (Run 25: mean −0.1154, CI [−0.2017,−0.0308], 12/14 individually
negative) — a 3rd directional corroboration — **but every sample is FAR below the pre-registered
100-event floor**, and the writeups honestly flag a 35.7% single-cluster (Hamas) concentration + an
UNVERIFIED ~81 combined N. External research (QuantPedia mean-reversion) refined the cost caution:
the 10bps cost-collapse is TURNOVER-dependent (favor threshold-triggered trades over every hourly
wiggle). Honest preliminary signal ONLY; reaches no revenue field. The bucket-calibration family stays
REFUTED across 3 real corpora (EXP-002 N=510, EXP-005 N=814, EXP-003 N=1,369).

**What the factory shipped since 2026-07-13 (fresh adversarial graders, verified not trusted):**
- **#338 (correctness — the promotion) — GENUINE.** See above. Closes the last correctness A→A+ residual.
- **#330 / #362 (run-risk / live-safety) — GENUINE.** Every unbounded venue call on the gated-off live
  order path is now time-bounded via `_call_with_timeout` (daemon thread): `create_and_sign_order` +
  `post_order` (`execution.py:374,379`) + `cancel_order` (`:703`). Timeout → REJECTED/False, no
  fabricated fill (`:470-495`). A stalled py-clob-client call can't hang the event loop.
- **#364 (run-risk / risk-correctness) — GENUINE.** Per-strategy drawdown circuit nets fees into the
  per-strategy value (`risk_manager.py:256`, scoped to NOT double-count `_daily_pnl`) so a decayed
  alpha's auto-disable gates on TRUE net cash PnL. Load-bearing test: gross dd 19.6% < 20% but net
  crosses → disabled (`test_sell_reduce_drawdown.py:118-146`).
- **#350 / #351 (backtest-integrity infra) — GENUINE + correctly advisory.** Leakage-safe intraday
  spike-detection/reversal-labeling PRIMITIVE (`spike_detection.py`, no trading/PnL claim) + two
  seed_hash reproducibility invariants pinned in `test_walk_forward_pm.py` (research_only-inertness +
  input-order-invariance, non-vacuous).

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**
  (import smoke + curated tests + safety + secret scan + runtime harness + scorecard-parse +
  self-validation 13/13 + GTM honesty all OK).
- `E2E_RUN_PASSED=0 python3 scripts/runtime_harness.py` → **PASSED** (live gate REJECTS, kill switch
  blocks, max-position rejects $900>$50, loss cap trips net-of-fees −$41.20 vs −$10 + blocks subsequent,
  deterministic exposure 10.000000==10.000000).
- `python3 scripts/run_walk_forward.py` twice → **reproduces** (`seed 42 / hash b3a8d5e0e9579853`,
  PnL 910,880.71; sha256-IDENTICAL outputs `c7d628ef…`; SYNTHETIC demo, labeled NOT a validated edge).
  104 walk-forward/F10/F11/cost/drawdown/calibration gate tests pass.
- `python3 -m pytest backend --collect-only` → **1538 collected / 0 errors WITH pandas**; 1197/13
  (pandas-missing) in the light gate — the documented heavy-dep exclusions. Docs cite ~1140 (BELOW
  true) — understated/honest, never inflated.
- Secret scan clean (no sk-/AKIA; only .env.example tracked). ZERO `live_trading_enabled = True` in
  backend/app. `next 14.2.35`.
- `python3 scripts/check_scorecard.py gate` → **NOT-READY (business_case_strength: B)** (honest).

**Grades (fresh adversarial per-dimension graders, none the maker — 4 subagents covered all 10 dims):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A+** (↑ from A),
security **A+**, run_risk_readiness **A**, artifact_integrity **A**, business_case_strength **B**,
design_taste **A**, tests_evals **A+**, performance **A**.

**Anti-inflation note:** I promoted `correctness_reliability` but did NOT promote any other dimension
despite genuine shipped work (#330/#362/#364/#350/#351). None addressed the binding constraint, and
each remaining A-graded ship-critical dim carries a named non-blocking residual that is the textbook
**A**, not A+: the un-committed real corpora + uncalibrated `DEFAULT_IMPACT_COEFF` (backtest_integrity),
the DEFAULT_FEE_RATE + fill==limit live-fee estimate (run_risk), the stale/understated test count
(artifact_integrity), the deferred multi-leg execution (functional_reality). `business_case_strength`
stays **B** — the EXP-006 pilot is honest directional signal at N=14–67, far below the 100-event floor,
with no strategy/cost/F10/F11 gate, so by rubric it is not, and is not presented as, a validated edge.
No grade exceeds its evidence.

**Backtest integrity (make-or-break) — reproduction + gate-exercise:** engine remains leak-free
(structural `MarketView` guard; fetchers RAISE rather than fabricate), reproducible (two runs this
cycle, sha256-identical). F10/F11 auto-run on every real corpus (`validate_real_oos.py:80-96`) and
previously rejected EXP-003's +$28,815.49 + EXP-005's +$16,993.97 headlines. Held at **A** (not A+)
only because the sole offline-reproducible number is synthetic and `DEFAULT_IMPACT_COEFF=0.5` remains
a placeholder. No fabricated PnL, no unreproducible backtest, no fabricated edge found anywhere.

**Weakest link (honest, unchanged):** there is no validated out-of-sample edge. The engine to find
one is world-class and getting sharper (correctness now A+), but the edge itself is unproven; the
EXP-006 pilot is a promising direction that must reach N≥100 + a full strategy/cost/F10/F11 backtest
before it can count. Everything downstream is gated correctly and honestly.

---

## 2026-07-13 — overall `B` · ship gate NOT met (8th grade — STEADY STATE: no dimension crossed a threshold; EXP-003 Politics TESTED + correctly REJECTED → bucket-calibration family now refuted on a 3rd real corpus; business_case still the lone binding B)

**Diff vs 2026-07-11:** overall unchanged at **B**, and — unlike last cycle — **no dimension crossed
a threshold in either direction.** All ten grades held exactly: functional_reality A, backtest_integrity
A, correctness_reliability A, security A+, run_risk_readiness A, artifact_integrity A,
business_case_strength B, design_taste A, tests_evals A+, performance A. The binding constraint
(`business_case_strength`, B) is unchanged: still no validated OOS cost-net edge.

**The make-or-break event this cycle — EXP-003 (Politics) TESTED, negative:** Research Run 20
(2026-07-12) resolved Gamma's Politics tag (`tag_id=2`) and ran `validate_real_oos.py --tag-id 2` →
**N=1,369** leakage-safe records (the largest per-category corpus tested to date, via the same
`GET /tags/slug/<name>` lever proven on EXP-005 last cycle — the 2026-07-11 scorecard predicted this
exact next test). `CalibrationBucketStrategy` traded 472 trades, headline **+$28,815.49 OOS** — but
F11 `indistinguishable_from_zero` (95% CI [-36648.21, 105232.67] spans 0 by a WIDER margin than
EXP-005; hit_rate **25.64%**, starkly *below* a coin flip) AND F10 **fragile** (134% of PnL from one
category bucket, 57% from ONE market; leave-one-out flips to **−$9,665.99**). A real **negative** —
the bucket-calibration family (static + recency) is now refuted/non-robust across **3** independent
real per-category corpora (EXP-002 N=510, EXP-005 N=814, EXP-003 N=1,369). EXP-006 (political
price-reversal after hype spikes) is logged but NOT yet tested (needs intraday-history infra the repo
lacks). The +$28,815.49 reaches no revenue field.

**What the factory shipped since 2026-07-11 (fresh adversarial graders, verified not trusted):**
- **#314 (run-risk durability) — GENUINE.** A loss-cap AUTO-TRIP whose safety-state persist fails
  transiently now fails CLOSED: `_persist_state` marks `_safety_persist_pending`, `_retry_pending_safety_persist()`
  re-attempts at the order gate, and `record_realized_pnl` halts if a realized loss can't be durably
  recorded (`execution.py:902-946,984-998`). Closes the durability hole #281 (non-breach branch only)
  left open; regression test non-tautological (persist-pending assertions FAIL with the retry removed).
- **#322 (tests — false-coverage trap) — GENUINE.** `test_backend_auth_fastapi.py` registered in the
  blocking gate (`preflight.sh:120`), closing the #283 false-coverage trap for the auth adapter;
  verified to RUN + PASS (not skip).
- **LLM safety hardening + `test_llm_safety.py` (in-gate) — GENUINE.** Fail-loud `LLMBudgetExceeded`
  under a single lock before dispatch (`analyst.py:76-92,262`), re-raised not swallowed (`:363-365`);
  30s hard timeout via ThreadPoolExecutor (`:351`). 14 tests pass, non-tautological. A real cost/DoS
  hardening on the AI path (`preflight.sh:108`).
- **#313 (security) — GENUINE.** `next` 14.1.0 → 14.2.35 (`frontend/package.json:22`, Dec-11 RSC DoS advisory).
- **Margin evals (advisory) — GENUINE + correctly NON-blocking.** Cost-per-outcome suite
  (`backend/evals/margin/`, `scripts/margin_eval.py`) + CI-hermetic runner kept OUT of the blocking
  gate (`margin` absent from `preflight.sh`) — a non-deterministic advisory eval can't red-block a merge.

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**.
- `E2E_RUN_PASSED=0 python3 scripts/runtime_harness.py` → **PASSED** (live gate REJECTS, kill switch
  blocks, max-position rejects $900>$50, loss cap trips net-of-fees −$41.20 vs −$10 + blocks subsequent
  orders, deterministic exposure 10.000000==10.000000).
- `python3 scripts/run_walk_forward.py` twice → **reproduces** (`seed 42 / hash b3a8d5e0e9579853`,
  PnL 910,880.71; a grader confirmed the two JSON outputs are sha256-IDENTICAL; SYNTHETIC demo, labeled
  NOT a validated edge). 76 walk-forward/F10/F11/cost gate tests pass.
- `python3 -m pytest backend --collect-only` → **1140 collected, 13 errors (all `No module named
  pandas`)** — the documented heavy-dep exclusions; drifted +6 from 1134 (new test files).
- HUMAN-CORE: zero `live_trading_enabled = True` assignments in `backend/app`. Secret scan clean.
- `python3 scripts/check_scorecard.py gate` → **NOT-READY (business_case_strength: B)** (honest).

**Grades (fresh adversarial per-dimension graders, none the maker — 3 subagents covered the 6
ship-critical + changed dims; the 4 unchanged dims graded from direct diff + harness evidence):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**, security **A+**,
run_risk_readiness **A**, artifact_integrity **A**, business_case_strength **B**, design_taste **A**,
tests_evals **A+**, performance **A**.

**Anti-inflation note:** I did NOT promote any dimension despite genuine shipped work (#314, #322, LLM
safety, next.js). None of it addressed the binding constraint (business_case), and each ship-critical
dim already carries a named non-blocking residual that keeps it at A rather than A+: WalletBehaviorDivergence's
decoupled confidence (still present, quarantined behind ENABLE_UNVALIDATED_STRATEGIES), the DEFAULT_FEE_RATE
live-fee estimate (still present, conservative + gated off), the uncalibrated DEFAULT_IMPACT_COEFF, and
the un-committed real corpora. A world-class dimension with a named non-blocking gap is the textbook **A**,
not A+. No grade exceeds its evidence.

**Backtest integrity (make-or-break) — reproduction + gate-exercise:** engine remains leak-free
(structural `MarketView` guard; fetchers RAISE rather than fabricate), reproducible (a grader
independently re-ran and confirmed sha256-identical outputs). The F10/F11 gates were shown to exist,
be wired + tested, and demonstrably reject EXP-003's +$28,815.49 headline — matching the recorded
numbers across GROWTH_STATUS.md + RESEARCH_MEMORY.md line-for-line. Held at **A** (not A+) only because
the sole offline-reproducible number is synthetic and DEFAULT_IMPACT_COEFF=0.5 remains a placeholder.

**Business case (the binding B) — EXP-003 TESTED, negative:** revenue $0, floor unmet, no validated
OOS edge, bucket-calibration family now refuted on 3 real corpora. Issue #79 refreshed with the Run 20
evidence. A validated edge requires a NEW pre-registered mechanism (not another bucket parameterization)
that clears F10 (non-fragile) + F11 (CI excludes 0) cost-net above the $2k/wk floor. No push notification
sent — steady-state grade, no regression, the scorecard IS the dashboard.

---

## 2026-07-11 — overall `B` · ship gate NOT met (7th grade — improved cycle: `security` A→A+ and `tests_evals` A→A+; the last standing alpha candidate TESTED and correctly REJECTED; business_case still the lone binding B)

**Diff vs 2026-07-09:** overall unchanged at **B**, but **two ship-critical dimensions crossed a
threshold UPWARD** — `security` **A→A+** and `tests_evals` **A→A+** — because the factory closed
the exact gate-coverage gaps the last scorecard named, and each fix was verified by a fresh,
independent, adversarial grader to genuinely *run* (not skip) and to *fail against pre-fix code*.
Four named A→A+ gaps closed in all. The make-or-break event: the research loop **finally TESTED**
its last standing alpha candidate (EXP-005) at real N=814, and the F10/F11 integrity gates
**correctly rejected** the +$16,993.97 headline as fragile + statistically insignificant — the
discipline working exactly as designed. The binding constraint (`business_case_strength`, B) is
unchanged: still no validated OOS cost-net edge.

**What the factory closed since 2026-07-09 (fresh adversarial graders, verified not trusted):**
- **#284 (correctness — the prior A→A+ gap) — GENUINE + CLOSED.** `NOPositionScanner.confidence`
  pinned to the units contract (`advanced_strategies.py:277`,
  `confidence=gate_confidence(no_price, estimate.edge)`), replacing the `min(adjusted_rate*2, 0.95)`
  **gate-bypass**. Non-tautological: grader reverted the pin → 3 gate tests fail, restored clean.
- **#280 (correctness — Weather + Whale)** — the two remaining executing strategies pinned
  (`strategies.py:182,1216`); `test_confidence_units_gated.py` fails pre-fix.
- **#283 (security / tests — the prior A→A+ gate-coverage gap) — GENUINE + CLOSED.**
  `test_security_headers.py` registered in the blocking gate (`preflight.sh:119`) AND `fastapi`+
  `httpx` added to `requirements-ci.txt` so it actually RUNS (a second review round caught that a
  bare `importorskip` would SKIP in 100% of CI). Verified → 3 passed, not skipped.
- **#298 (tests)** — registered `test_loss_cap_persist_failclosed.py` + `test_confidence_units_gated.py`
  into the gate (`preflight.sh:122-123`), honestly noting #280's own commit had mis-claimed it.
- **#281 (run-risk durability)** — a realized loss that cannot be durably persisted now **fails
  CLOSED** (`activate_kill_switch("loss-persist failure")`) so a restart can't reset the loss cap;
  `_FailingSaveStore` test + profit/breakeven/no-store controls (in the gate).
- **#297 (run-risk)** — circuit-breaker cooldown now honors its full wall-clock duration across the
  UTC day-roll (`risk_manager.py:262` no longer clears the breaker on daily reset).
- **#295/#294 (research tooling)** — `validate_real_oos.py --tag-id` threads an integer Gamma
  category filter — the lever Run 19 used to reach N=814.

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**.
- `E2E_RUN_PASSED=0 python3 scripts/runtime_harness.py` → **PASSED** (live gate REJECTS, kill switch
  blocks, max-position rejects $900>$50, loss cap trips net-of-fees −$41.20 vs −$10 + blocks
  subsequent orders, deterministic exposure 10.000000==10.000000).
- `python3 scripts/run_walk_forward.py` twice → **reproduces** (`seed 42 / hash b3a8d5e0e9579853`,
  PnL 910,880.71 identical; SYNTHETIC demo, labeled NOT a validated edge).
- `python3 -m pytest backend --collect-only` → **1134 collected, 13 errors (all `No module named
  pandas`)** — the fastapi/`test_security_headers.py` error from last cycle is RESOLVED (#283).
- `python3 scripts/check_scorecard.py gate` → **NOT-READY (business_case_strength: B)** (honest).

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**,
security **A+**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A**, tests_evals **A+**, performance **A**.

**Anti-inflation note:** I promoted `security` and `tests_evals` to A+ ONLY because each grader
verified the named gate-coverage gap is genuinely closed AND found NO new hole (the security-header
test provably RUNS rather than skips; the new gate tests fail against pre-fix code). I did **NOT**
promote `correctness_reliability` despite #284 closing its named prior gap, because the grader
surfaced a **NEW residual**: `WalletBehaviorDivergence` (`advanced_strategies.py:1289`,
`confidence=self._compute_confidence(...)` decoupled from entry+edge) — the identical wrong-units
bug class the #280 sweep missed on one executing class-member. A world-class dimension with a named
non-blocking gap is the textbook **A**, not A+. No grade exceeds its evidence.

**Backtest integrity (make-or-break) — reproduction + gate-exercise:** engine remains leak-free
(structural `MarketView` guard; fetchers RAISE rather than fabricate), reproducible (identical
hash + PnL; #286 RNG-seed fix verified — seed=42 reproduces, seed=999 diverges). The F10/F11 gates
were shown to **exist in code and demonstrably reject** EXP-005's +$16,993.97 headline
(`bootstrap_oos_significance.py:161`, `regime_slice.py:315-323`) — not narrative. Held at **A** (not
A+) only because the sole *offline-reproducible* number is synthetic (the N=814 real corpus is not
committed) and `DEFAULT_IMPACT_COEFF=0.5` remains an uncalibrated placeholder.

**Business case (the binding B) — EXP-005 TESTED, negative:** Research Run 19 (2026-07-11) resolved
Gamma's real Sports tag (`tag_id=1` via `GET /tags/slug/sports`) and ran `validate_real_oos.py
--tag-id 1` in one pre-registered run → **N=814** leakage-safe Sports records (>2× the ~300-400
floor, no code change). `CalibrationBucketStrategy` finally traded (268 trades, +$16,993.97 OOS
headline) but F11 `indistinguishable_from_zero` (95% CI [-17164.66, 49793.75] spans 0, hit_rate
49.25%) AND F10 **fragile** (125% of PnL from one category bucket; leave-one-out flips to
−$4,319.43). A real **negative** result — the bucket-calibration family is now refuted across 3+
independent real corpora (EXP-002, the 4th-run HuggingFace/recency test, and now EXP-005). The
+$16,993.97 propagates into NO revenue field (`weekly_pnl_paper: null`, `arr_year1: 0`). Revenue
$0, floor unmet, ship gate correctly closed. Reusable lever proven: resolve a category's real Gamma
`tag_id` via `GET /tags/slug/<name>` then `--tag-id` (directly applicable to EXP-003 politics).

**Artifact-integrity correction this cycle:** the prior scorecard's "1107 collected / 14 errors (13
pandas + 1 fastapi)" is now **stale** — true current is **1134 collected, 13 errors, all pandas**
(the fastapi error resolved with #283). Third consecutive cycle the reported raw count lags reality
(894→1040→1107→1134); direction always conservative/understated, never inflated. The standing fix:
cite the curated preflight-green gate rather than a raw collection total that drifts every cycle.

**Issues:** **#79 refreshed** with the 2026-07-11 evidence (EXP-005 TESTED at N=814 → fragile +
statistically insignificant, the tag_id per-category lever, next-mechanism guidance) — the
ship-critical binding constraint, still egress/owner-gated. The A→A+ nits (WalletBehaviorDivergence
confidence, frozen real corpus + impact-coeff calibration, live-fee real-field, test-count drift)
are named in the scorecard `top_gaps` for the factory; not separately filed to avoid issue spam
(non-ship-critical A-dimension improvements, tracked on the dashboard via the scorecard).

**Weakest link (honest, unchanged):** there is still no validated out-of-sample edge. The engine to
find one is high quality and materially better hardened + gate-covered this cycle (2 dims to A+),
and it just demonstrated it will *reject* a plausible-but-fragile headline rather than bank it — but
the edge itself is unproven, and everything downstream is gated correctly and honestly.

---

## 2026-07-09 — overall `B` · ship gate NOT met (6th grade — substantive safety/units-contract cycle; the prior partial-reduce A→A+ gap CLOSED; business_case still the lone binding B)

**Diff vs 2026-07-07:** overall unchanged at **B**, letters unchanged across all ten
dimensions — but this was a **substantive** cycle (26 commits, ~3,500 LOC, +13 test files),
not a token one, and the composition improved materially. The headline: **#253 genuinely
CLOSED the prior correctness_reliability / run_risk_readiness A→A+ gap** (SELL/partial-reduce
now feeds the per-strategy drawdown circuit). Five more safety/security fixes and the
units-contract family landed and were re-verified **non-tautological** by fresh, independent,
adversarial per-dimension graders (none the maker). The research loop ran two more real-data
probes to **no new edge** and honestly **corrected a prior Manifold overclaim downward**. The
binding constraint (`business_case_strength`, B) is unchanged.

**What the factory closed since 2026-07-07 (fresh adversarial graders, verified not trusted):**
- **#253 (the prior A→A+ gap) — GENUINE + CLOSED.** The SELL/reduce branch now feeds realized
  PnL to the per-strategy drawdown circuit (`execution.py:1219-1227`,
  `risk_manager.record_pnl(pos.strategy, pnl)`; wired via `orchestrator.py:640`).
  Non-tautological: pre-#253 (`git show 41ab6da^`) had **0** `record_pnl` sites in the reduce
  path, HEAD has 3; `test_sell_reduce_drawdown.py` proves a strategy bleeding on reduces ALONE
  now auto-disables — structurally impossible pre-fix. No double-count (reduce shrinks
  `pos.size` first; the remainder settles via MTM later — disjoint portions).
- **#264 (per-order MAX_PER_TRADE_USD ceiling)** — `execution.py:1051` rejects
  `notional > max_per_trade_usd` before the max-position check; `test_max_per_trade_cap.py:43`
  would have FILLED pre-fix.
- **#272 (live fills charge the venue fee)** — both live paths set the fee at
  `DEFAULT_FEE_RATE` (`execution.py:406,557`), netted into `record_realized_pnl` so hard loss
  caps trip **earlier**; paper `_simulate_fill` untouched → determinism intact.
- **#260 (BUY-on-short quarantine)** — `execution.py:1016-1029` rejects a BUY on a legacy
  short row (loss-cap-bypass closed; `test_short_open_rejected.py:67`).
- **#269 (boot-error secret-value log hygiene)** — `config.py:253-262` re-raises with
  `errors(include_input=False)` + `from None`; only var names leak, never values
  (`test_config_safety.py:117-149`, in the blocking gate; fails pre-fix).
- **#265 (security headers + /health info-hygiene)** — nosniff/X-Frame-Options DENY/Referrer/
  HSTS via non-clobbering `setdefault`; `/health` no longer leaks `live_trading_enabled`.
- **#263/#268/#275 (units-contract)** — edge/confidence in absolute probability units;
  behavioral flips, not renames (`test_confidence_units.py:147-170`: a 0.40-fair-value BUY now
  sizes to $0 where pre-fix `confidence=0.85` bypassed the gate).

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**
  (import smoke + curated tests + safety + secret scan + runtime harness + scorecard parse +
  self-validation + GTM honesty).
- `python3 scripts/runtime_harness.py` → **PASSED** (live gate REJECTS real order, kill switch
  blocks, max-position rejects $900>$50, loss cap trips net-of-fees at −$41.20 vs −$10 and
  blocks subsequent orders, deterministic exposure 10.000000==10.000000).
- `python3 scripts/run_walk_forward.py` twice → **reproduces** (`seed 42 / hash
  b3a8d5e0e9579853`, PnL 910,880.71 identical; SYNTHETIC demo, labeled NOT a validated edge).
- `python3 -m pytest backend --collect-only` → **1107 collected, 14 errors** (13
  `No module named pandas` + 1 `No module named fastapi` on `test_security_headers.py`). New
  units/reduce/cap tests (60) pass; verified non-tautological.
- `python3 scripts/check_scorecard.py gate` → **NOT-READY (business_case_strength: B)** (honest).

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A**, tests_evals **A**, performance **A**.

**Anti-inflation note:** #253 closed the named prior A→A+ gap on both correctness_reliability
and run_risk_readiness — but I did **NOT** promote either to A+, because each grader surfaced
a real NEW non-blocking finding: correctness has the **NOPositionScanner confidence residual**
(`advanced_strategies.py:265`, `confidence=min(adjusted_rate*2.0, 0.95)` decoupled from
entry+edge — the same units-contract bug class, unfixed on this executing default-scan
strategy); run-risk has the **live kill-switch fee-estimate residual** (nets on
`DEFAULT_FEE_RATE` + assumed fill==limit, not a real venue fee field). A world-class dimension
with a named non-blocking gap is the textbook **A**, not A+. No grade exceeds its evidence.

**Backtest integrity (make-or-break) — reproduction attempted again:** engine remains
leak-free (structural `MarketView` guard; all three fetchers — including the new
`manifold_history_fetcher` — RAISE rather than fabricate a decision price), cost-realistic
(single source of truth with the executor), reproducible (identical hash + PnL). The new
`research_only` field is excluded from `_seed_hash`. The #259 play-money guardrail was
exercised directly (`validate_real_oos.evaluate` RAISES on any `research_only=True` record).
**No unreproducible backtest, no fabricated PnL, no banked edge found.** Held at **A** (not
A+) only because the sole reproducing number is synthetic and `DEFAULT_IMPACT_COEFF=0.5`
remains an uncalibrated placeholder.

**Business case (the binding B) — unchanged:** still no validated OOS cost-net edge. EXP-005
(Sports-category bucket, motivated by B9's worst-ECE finding) ran on real leakage-safe data
and **abstained on sub-floor N** (134–135 Sports markets vs. `min_bucket_n=30`×10 required):
0 trades, F11 `insufficient_data` — an honest zero, NOT a measured negative. Run 17 replicated
N≈135 across three pulls and diagnosed a `volumeNum` sampling-axis fetch ceiling (fetcher-
design gap, not an edge). Bucket-calibration family still REFUTED across 4 corpora. The prior
"materially softer Manifold crowd" framing was **corrected downward** to "less-pinned research
corpus, not a proven beatable crowd." Revenue $0, floor unmet, ship gate correctly closed.

**Artifact-integrity correction this cycle:** the prior scorecard's "1040 collected / 13
errors (all pandas)" is now **stale and incomplete** — actual is **1107 collected, 14 errors
(13 pandas + 1 fastapi)**. Direction was understated (conservative), never inflated, and
self-disclosed; corrected in this scorecard. The recurring lesson: sync the reported count
with actual collection, or cite the curated-green subset rather than a drifting raw total.

**Issues:** **#79 kept open + refreshed** with the 2026-07-09 evidence (EXP-005 abstain,
Manifold correction, the volumeNum-ceiling next step) — the ship-critical binding constraint,
still egress/owner-gated. The four A→A+ nits (NOPositionScanner confidence, security-header
gate coverage, live-fee real-field, impact-coeff calibration) are named in the scorecard
`top_gaps` for the factory; not separately filed to avoid issue spam (they are non-ship-
critical A-dimension improvements, tracked on the dashboard via the scorecard).

**Weakest link (honest, unchanged):** there is still no validated out-of-sample edge. The
engine to find one is high quality and materially better hardened this cycle, but the edge
itself is unproven, and everything downstream is gated correctly and honestly.

---

## 2026-07-07 — overall `B` · ship gate NOT met (5th grade — small hardening cycle; two more verified safety fixes; business_case still the lone binding B)

**Diff vs 2026-07-05:** overall unchanged at **B**, letters unchanged across all ten
dimensions — an honest read of a small **hardening** cycle. No ship-critical dimension
crossed a threshold. Composition improved: two more genuine safety fixes landed and were
verified non-tautological, the prior #240 git-log-framing nit is resolved, and the research
loop ran another real-data probe to **no new edge**. The binding constraint
(`business_case_strength`, B) is unchanged.

**What the factory closed since 2026-07-05 (fresh adversarial graders, verified not trusted):**
- **#241 (D1 side-effect integrity)** — a 0-fill `OPEN` order (`is_success` True for OPEN,
  `filled_size=0`) previously fabricated a **phantom `Position`** (size 0) that poisoned the
  orchestrator's `token_id in executor.positions` dedup, silently skipping later *real*
  opportunities on that token (and persisting across restart). Fixed by gating the
  position/fee mutation on an actual fill — `execution.py:1062`
  (`if result.is_success and result.filled_size > 0:`). Non-tautological tests
  (`test_live_gate_defense.py:368,384,413`) trip pre-fix; the order is still recorded in
  `order_history`; paper is unaffected (`_simulate_fill` returns FILLED, filled_size>0).
- **#242 (venue-credential boot gate)** — a live-enabled host missing the Polymarket order
  credentials would boot "fine" and fail **every** real order at runtime (executor not
  authenticated). New `_require_venue_credentials_in_live` model validator
  (`config.py:183-215`) refuses to boot when `live_trading_enabled` and any of
  `POLYMARKET_API_KEY/_SECRET/_PASSPHRASE/_PRIVATE_KEY` is unset. Gated on
  `if self.live_trading_enabled:` (live defaults false) → can never bind paper/dev/CI. Real
  env-var tests assert boot-time `ValidationError`, incl. a partial-credential case
  (`test_config_safety.py:49,62,71`). It adds a fail-loud check; weakens nothing.
- **Prior #240 artifact-framing nit — resolved.** The four newest commits are honestly
  framed: `087cd27`/`f46de05`/`dfd27e2` are prefixed **"File ROADMAP"** (touch only
  `ROADMAP.md`/`loop-memory.md`); `33f2d6f` is **"chore: sync"** (`FACTORY_STANDARD.md`).
  None masquerade as a shipped feature.

**Mechanical signals actually run (cold start):**
- `pip install -r backend/requirements-ci.txt`; `bash scripts/preflight.sh code` → **GREEN**
  (import smoke + curated tests + safety + secrets + runtime harness + scorecard-parse +
  self-validation + GTM-honesty OK; full ruff skipped in CI by design).
- `scripts/runtime_harness.py` → **PASSED**: live gate REJECTS real order, kill switch
  blocks, max-position cap rejects $900>$50, loss cap trips **net-of-fees** at −$41.20 vs
  −$10 and blocks subsequent orders; paper fills, deterministic.
- `scripts/run_walk_forward.py` twice → **reproduces** bit-identically (`seed_hash
  b3a8d5e0e9579853`, total PnL 910,880.71; SYNTHETIC demo, labeled NOT a validated edge).
- `ruff check backend/app --select E9,F821,F811` → **clean**. Secret scan clean (only
  `.env.example`). `pytest --collect-only` → 1040 collected, 13 errors (all
  `No module named 'pandas'` — the documented light-gate exclusion).
- `pytest test_live_gate_defense.py test_config_safety.py` → **27 passed**.

**Grades (fresh adversarial per-dimension graders, none the maker):**
functional_reality **A**, backtest_integrity **A**, correctness_reliability **A**,
security **A**, run_risk_readiness **A**, artifact_integrity **A**,
business_case_strength **B**, design_taste **A**, tests_evals **A**, performance **A**.

**Anti-inflation overrides (held grades DOWN):**
- **security** — the grader recommended **A+**. I **held it at A**: A+ requires *zero*
  findings, and the grader itself named a (trivial) nit (the `auth_core` empty-token
  primitive is misreadable in isolation, though documented + unreachable). Nothing changed
  this cycle to justify an A→A+ promotion — #242 only adds a boot gate. Textbook A.
- **correctness_reliability / run_risk_readiness** — the grader leaned **A−** on the
  unchanged partial-reduce → per-strategy-drawdown-circuit gap (`orchestrator.py:459-463`).
  Held at **A** (consistent with prior cycles): the binding hard loss caps + kill switch are
  fully wired on **both** paths; the missing piece is only the *secondary* per-strategy
  drawdown auto-disable on the non-dominant partial-reduce path. A world-class dim with a
  named, non-blocking, secondary nit is the textbook A, not a downgrade to B.

**Backtest integrity (make-or-break) — reproduction attempted again:** leak-free
(structural `MarketView` guard; fetchers reject any tick `> decision_ts`/`>= resolution_ts`
and RAISE), cost-realistic (single source of truth with the executor), reproducible
(identical hash + PnL across two runs this cycle). **No new OOS run;** the bucket family
remains **REFUTED across 4 corpora**, and the B8 cross-venue work is a data-feasibility
probe with **zero OOS runs** (it pinned the Kalshi orderbook-quote path only). No
unreproducible backtest, no fabricated PnL, no fabricated edge. Held at **A** (not A+): the
impact/capacity term is an uncalibrated `impact_coeff=0.5` placeholder.

**Artifact-integrity finding (conservative, corrected):** the prior scorecard reported
"894 tests"; actual collection is **1040**. Direction is **understated, never inflated**, so
no integrity violation — but a stale reported metric. Corrected in this scorecard; the
A→A+ item is "keep the reported count in sync (or cite the curated-green subset)."

**Overall = B:** the sole ship-critical dim below A is **business_case_strength** (no
validated OOS edge; the only non-crowd alpha family is refuted across four corpora and the
B8 candidate has not run OOS — THE binding constraint). Ship gate correctly closed.

**Issues:** **#79 kept open + updated** (business case — unchanged binding constraint;
2026-07-07 grade re-confirms no new edge, B8 still an unbuilt data-eng effort). #241 and
#242 landed as verified factory fixes (no auditor issue needed — both close cleanly and no
ship-critical dim regressed).

**Weakest link (honest, unchanged):** still no validated out-of-sample edge — and this
cycle the factory again earned credit by running its own candidate probe to **no new edge**
rather than curve-fitting one. Everything downstream stays gated correctly and honestly.

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
