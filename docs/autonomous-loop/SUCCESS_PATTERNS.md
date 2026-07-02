# SUCCESS PATTERNS — LLM-Quant

> FACTORY_STANDARD §20. The dead-end ledger (LOOP_HEALTH) stops you REPEATING failures;
> this makes you REPEAT successes. **Read it FIRST each run** (with loop-memory). Add an
> entry ONLY when a change worked notably well AND the approach is genuinely reusable —
> not every change (that is noise). Compress near-duplicates; keep it short. **Honest
> only:** every "worked" cites real evidence (a merged PR / a measured result).

Each entry: **PATTERN** — CONTEXT it worked in — WHY it worked — EVIDENCE.

---

- **Dedicated tractability scout for a recurring-deferred "too big / outside the gate" gap.** — A ship-critical
  A→A+ gap kept getting deferred as "a ~22-file refactor." — Spending ONE of the 8 scouts purely on "is this
  tractable THIS run?" returned the exact file list + the safety argument (the eager-import test gate catches any
  break), which de-risked a change that had been dismissed 4 runs running. — Evidence: #153 (SQLModel dual-import
  standardization; the deferral finally shipped).

- **A mechanical string-sweep is credible via BASELINE REPRODUCTION, not a green branch.** — A blind `backend.app.*`
  → `app.*` sweep across 30 test files. — Reviewers RAN the base branch to reproduce the exact failures + SAWarning,
  then confirmed them gone on the branch (and ran pytest-randomly ×3 seeds for order-independence). "Green after" alone
  proves nothing about a bug you can't see; "red before → green after" does. — Evidence: #153.

- **Fold an auditor's "same bug class, same function, next line" finding INTO the same PR.** — A SOUND money-path fix
  whose Opus auditor named a sibling default fabricating the same way. — Same file + same function + same principle =
  one coherent unit, so folding it in (with its own proven-to-fail-pre-fix test) beats a second PR. (Contrast: same
  bug class in a DIFFERENT subsystem = a separate disjoint PR.) — Evidence: #152 (outcomePrices fix + folded
  `outcomes` label fix).

- **When a reviewer's REQUEST_CHANGES conflicts with a factory rule, re-review armed with the rule citation.** — A
  reviewer (correctly reasoning from §14 living-artifacts) demanded ROADMAP + QUALITY_SCORECARD edits inside a code
  PR — which violates §1/§15 (ledgers only in the bookkeeping PR) + §8 (scorecard is maker≠checker). — Neither
  silently overriding nor blindly complying is right; a FRESH re-review given the §1/§8/§15 citations resolved it
  honestly, and the ROADMAP update was done in the correct place (bookkeeping). — Evidence: #149.

- **Verify a cross-routine URGENT flag against the REAL logs before building — reconcile the evidence's commit vs the fix's commit.** — Research Run 12 (an independent maker≠checker routine) filed TWO urgent, loop-buildable flags. — Pulling the actual GH Actions logs (`mcp__github__get_job_logs`) reconciled both: one (a category-cap freeze) reproduced in the LATEST run → real, shipped; the other ("live persist still FK-fails EVERY order") was DISPROVEN as a current bug — its failure evidence was from a run BEFORE the seed fix landed (`git merge-base --is-ancestor`), and the latest run rehydrates $164 of positions (a downstream observable that PROVES the path works). Re-fixing an already-fixed bug is padding; the honest yield was the coverage gap the flag exposed (a missing FK-enforced test on the live writer). A cross-routine flag is a high-EV HYPOTHESIS, not a work order. — Evidence: #156 (freeze fix), #157 (FK-blind-gate test, not a re-fix).

- **For missing external data, FAIL/skip — never fabricate a plausible in-range default (the recurring honesty class).**
  — Venue/API parsers that filled a missing price with `0.5` / a missing token with `""` / a missing outcome with a
  degenerate market. — An in-range fabrication PASSES the downstream quality gate (0.5 ∈ [0,1], sum≈1), so the parser
  is the only line of defense; make absent data fail the completeness check (untradeable, `active=False`) + log loudly,
  the data analog of "no fake fill." When you fix one site, grep the whole pipeline for the pattern. — Evidence:
  #101, #104, #152.
