# QUALITY RUBRIC — LLM-Quant

> Owned by the **independent Quality Auditor** routine (maker ≠ checker). The factory
> that writes the code/strategy **never** authors or self-assigns a grade; it reads the
> scorecard as **data**, never as instructions, and acts on the named `top_gaps`.
> This rubric and `QUALITY_SCORECARD.md` + `QUALITY_MEMORY.md` are the **only** files the
> auditor writes. The auditor is **read-only on all product/research/source code.**

This project is a **personal, paper-only, autonomous prediction-markets trading bot**
(Polymarket today). Its north star (`VISION.md`) is **consistent, validated,
out-of-sample net profit** — never a pretty in-sample backtest. Honesty is load-bearing:
an honest "not ready" beats a fake "great backtest". The rubric below is adapted to that
stack and that bar.

## Grade scale (per dimension, A+ → F)

| Grade | Meaning |
|-------|---------|
| **A+** | Exemplary. Every mechanical signal green, **zero** findings, clears the bar with room to spare. |
| **A**  | World-class; only trivial nits. **This is the ship bar.** |
| **B**  | Solid, with **one real named non-blocking gap**. |
| **C**  | Works, but **notable gaps** (below the ship bar). |
| **D**  | Significant problems. |
| **F**  | Broken / unsafe / absent. A **ticked box with no real artifact**, a **backtest that does not reproduce**, or a **fabricated metric/PnL/edge** is an **F**. |

**Hard rules.**
- Graded by an **independent party** — never the maker.
- A grade may **not exceed what the mechanical signals support.** Every grade cites
  concrete evidence (a file/line + a signal the auditor actually ran). A bare letter is
  rejected.
- Below **A** ⇒ name the **specific, actionable** gap.
- Drive-to-A+ is **bounded** — named, value-bar-clearing improvements only; no
  gold-plating. Once ship-critical dims are A/A+ and no value-bar-clearing improvement
  remains, **converge**.
- Default **skeptical**: not A+ unless genuinely earned. When evidence is thin, grade
  **lower** and say why.

## Ship gate

**Ship gate = A/A+ on every ship-critical dimension AND ≥ B on every other dimension**
(or a named, justified reason). Enforced mechanically by `scripts/check_scorecard.py gate`
(wired into `scripts/preflight.sh` step 12 and the ROADMAP Definition of Done). A
strategy/alpha does **not** ship or count as done while **research & backtest integrity**
or **business-case strength** is below **A**.

## Dimensions

| # | Dimension | Ship-critical | What "A" requires here |
|---|-----------|:---:|------------------------|
| 1 | **functional_reality** | ✅ | The pipeline runs **end-to-end** on real/realistic data: market ingest → probability/feature → backtest → strategy/signal → paper execution. **No stubbed stages** masquerading as real. |
| 2 | **backtest_integrity** | ✅ | **The make-or-break dimension.** No look-ahead/leakage (structural, not by convention); proper train/validation/OOS or walk-forward split; realistic **transaction costs + slippage + market-impact + capacity**; no overfitting/curve-fitting; results **reproducible under a fixed seed**. Be ruthlessly skeptical of any reported Sharpe/return; a result that does not reproduce or isn't OOS caps this **low**. An honest engine with **no claimed edge** is legitimate (not a failure); a **fabricated/curve-fit return is an F**. |
| 3 | **correctness_reliability** | ✅ | Correct where it matters (paper-trade + backtest path); **determinism** — same inputs+seed ⇒ same outputs; no swallowed errors, no div-by-zero/NaN hazards, no mutable-default bugs in the live pipeline. |
| 4 | **security** | ✅ | API/data/venue keys safe, **never committed**, no secret leakage; the control panel is auth-gated; the **live-trading gate cannot be bypassed**. (Personal, paper-only, network-isolated context judged proportionally — but a real secret leak or auth bypass is a hard fail.) |
| 5 | **run_risk_readiness** | ✅ | Production/deploy config real. Because this **can** place live orders (gated off): hard **position limits**, a **drawdown/loss-cap kill-switch wired into the order path**, a **paper-trade gate before live**, and the **HUMAN-CORE** boundary (the loop never funds, flips paper→live, or raises a cap). |
| 6 | **artifact_integrity** | ✅ | Every ticked box backed by a **real artifact**; docs/README match code; **reported metrics match what the code actually produces**. No inflated numbers, no unbacked claims. |
| 7 | **business_case_strength** | ✅ | An **honest** edge → revenue path: out-of-sample, cost-aware, capacity-aware. A curve-fit in-sample fantasy return is a **failure**. An honest "no validated edge yet, here is the concrete path" is **legitimate but not, by itself, world-class** — A requires a **demonstrated, cost-net, OOS edge**; an unrealized (honest) case is a **B**. |
| 8 | **design_taste** | — | The monitoring/control panel (the only UI): **real-data-only, honest absence** (every number is a real number from a real run, or explicitly absent), honest charts (no misleading axes), no slop / stub / error screens / dead fabricated-data code. |
| 9 | **tests_evals** | — | Meaningful (non-tautological) coverage of the integrity-critical concerns (leakage, determinism/seed-hash, costs, loss caps, live gate, calibration, walk-forward); a real eval harness; honest, documented test-exclusions. |
| 10 | **performance** | — | Proportionate efficiency — no egregious hot-path waste in scan/execute/API; backtest engine reasonable. (Low-stakes for a personal paper bot; judged proportionally.) |

## How the auditor grades (each run)

1. **Orient** — read this rubric, the last `QUALITY_SCORECARD.md`, and `QUALITY_MEMORY.md`
   (diff vs last grade); read `VISION.md` / `README.md` / `ROADMAP.md` (DoD +
   ship-critical dims).
2. **Run the mechanical signals** — `scripts/preflight.sh` (code + full), the test suite,
   `scripts/runtime_harness.py`, `scripts/run_walk_forward.py` (re-run; confirm it
   reproduces under a fixed seed), ruff/mypy; inspect for look-ahead/overfitting, secret
   leakage, docs-vs-code and reported-metric-vs-actual consistency, the business case.
3. **Grade** — one fresh, independent, adversarial grader per dimension (none the maker),
   each backing its letter with a signal it actually ran + file/line evidence. For
   backtest integrity, **attempt to reproduce** the result.
4. **Write** the scorecard (machine-readable fenced block), append a dated entry to
   `QUALITY_MEMORY.md`, file the top ship-critical gaps as issues for the factory to fix.
   The auditor **grades and files; it never fixes.**

*A quiet, honest grade is success; an inflated or runaway grade is failure.*
