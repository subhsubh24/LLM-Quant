# SUCCESS PATTERNS — LLM-Quant

> FACTORY_STANDARD §20. The dead-end ledger (LOOP_HEALTH) stops you REPEATING failures;
> this makes you REPEAT successes. **Read it FIRST each run** (with loop-memory). Add an
> entry ONLY when a change worked notably well AND the approach is genuinely reusable —
> not every change (that is noise). Compress near-duplicates; keep it short. **Honest
> only:** every "worked" cites real evidence (a merged PR / a measured result).

Each entry: **PATTERN** — CONTEXT it worked in — WHY it worked — EVIDENCE.

---

- **A per-trade/notional CEILING must RESIZE the order down, not DROP it at the gate — and money comparisons need a 1e-9 epsilon.** — Wiring an owner per-trade cap that was previously inert. — Enforcing the cap only at the execution gate silently REJECTED ordinary Kelly-sized bets (Kelly max $50 vs a $5 cap), starving the paper-validation loop; two review cycles converged on the right shape: clamp the bet DOWN to the cap in the sizer (defense-in-depth gate as backstop), then a 1e-9 money-precision tolerance so a NON-round cap's float noise (1.8×0.65 == 1.17 but 1.17000000000000002 in float) can't reject the resized order. Test with non-round caps + a cent sweep — clean 0.10-lot fixtures never expose the float gap. — Evidence: #264.

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

- **A change to a SAFETY COUNTER earns its credibility from a MONEY-BOUNDARY test that trips ONLY because of the fix + a fresh Opus live-safety audit.** — Netting fees into the loss-cap/kill-switch counters (a stable, guard-tested safety anchor). — The convincing artifact isn't "the counter is now smaller"; it's a boundary test where the GROSS loss is UNDER the cap (pre-fix: no trip) but the NET loss is OVER it (post-fix: trips), so the test FAILS on pre-fix code and pins the exact safety behavior the fix delivers. Pair it with a fresh Opus auditor told to break the conservation/direction claim (it verified BUY→SELL→resolve nets exactly the real fees, no double/under-count). This is how a "stable safety anchor" change ships without churning the anchor. — Evidence: #192 (`test_*_trips_ONLY_because_of_fees`, Opus SAFE).

- **Before branching, hard-reset the local base ref to `origin`; verify any PR-body git-ancestry claim against `origin`, never a local ref.** — All PRs a run were forked from a STALE local base branch ref (an old commit); it was invisible while the changes were file-disjoint from the delta, but produced a merge conflict + redundant work + a FALSE "#X is not an ancestor" claim on the one PR that touched a file the delta had changed. — `git branch -f <base> origin/<base>` (or branch from `origin/<base>`) before creating work branches; and treat a git-ancestry assertion as a CHECKABLE claim (`git merge-base --is-ancestor X origin/<base>`) — a stale-ref-based claim is the same honesty class as an unsourced number. The adversarial review caught it — the gate earning its keep. — Evidence: #196 (rebuilt minimal after 2 reviewers flagged the stale-fork redundancy).

- **Re-probe every env-gated external dependency by hitting its REAL read path each run; a "blocked, confirmed by prior runs" conclusion about EGRESS is overturnable by a direct probe, exactly like a code "unreachable" prior.** — The factory build env's egress to Polymarket/Kalshi/HuggingFace was treated as blocked (owner actions OA-11/13/16) across many runs; a one-line `curl` this run returned HTTP 200 to all five domains + a real 799-record fetch, unblocking the binding-constraint validation the loop had been deferring to the owner. — Owner env/egress changes are INVISIBLE to git and to a prior run's conclusion (FACTORY_STANDARD §28); each run, curl the real endpoint before inferring "still blocked". Same discriminator as the anti-re-litigation rule: reverse a stale conclusion on a direct probe, not a hunch. — Evidence: 2026-07-04 3rd run (probe → HTTP 200 → the first factory-env real OOS run; also triggered #222 gating once data-api proved reachable).

- **Weak-case loop-back: when an alpha is refuted OOS, build the audit-NAMED revised mechanism with FIRST-PRINCIPLES pre-registered params, test it ONCE on a fresh real corpus (no tweak-and-retry), and report the honest result — a refutation is a success, a p-hacked pass is a failure.** — EXP-002 (static bucket) was refuted (lagging a time-varying rate); the named successor (recency-weighted decay) was built, pre-registered (half_life=60 etc.), and run ONCE → also refuted (−$914), AND the static variant's sign flipped across corpora (+$3,330 vs −$2,938) proving non-robustness. — Choose params from first principles/shipped defaults BEFORE looking; run once; if it fails, record the honest refutation + name the next candidate; NEVER re-tune on the corpus just seen. A positive OOS aggregate that flips sign on another honest corpus is NOT edge. — Evidence: #221 + RESEARCH_MEMORY 2026-07-04 (recency alpha REFUTED, static shown non-robust).

- **The UNITS CONTRACT: a strategy's `ScanResult.confidence` (and `edge`) must equal the quantity the orchestrator reconstructs from them, because a downstream GATE reads them literally.** — `orchestrator.kelly_size` reads `confidence` ONLY for `if confidence < min_confidence: skip` and derives `win_probability = entry_price + edge` independently; a strategy emitting a decoupled heuristic (`0.85`, `chain_conf`, `adjusted_rate*2`) makes the safety gate filter on the wrong number. — When adding/auditing ANY strategy, assert `entry_price + edge == the intended win-probability == confidence` (a `win_prob > 1`, or a `confidence` far from `entry+edge`, is the tell). Fix at the emission with a shared clamp helper, edge computation UNCHANGED. The convincing test is a BEHAVIORAL-FLIP (a signal that PASSES the gate pre-fix and is GATED post-fix), proven non-tautological by reverting all N fix-sites → exactly the expected tests fail. SCOPE it honestly to strategies whose signals reach the gate (single-outcome `outcome_idx>=0`); `outcome_idx=-1` multi-leg baskets are `skip_multi_leg`-inert, and a strategy whose thesis needs `win_prob<0.5` (a longshot) is a design question, not a units fix. — Evidence: #263 (NearCertainty edge), #268 (NOPositionScanner edge), #275 (CrossMarketArb + LogicalImplication confidence).
