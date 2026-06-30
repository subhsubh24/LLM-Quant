# LOOP MEMORY — LLM-Quant

Cross-run lessons for the autonomous factory loop. Append; read before each run.

## 2026-06-30 (5th run) — ONE genuine side-effect-integrity fix (phantom 0.0 settlement); the binding constraint is now OWNER-BLOCKED, and anti-scarcity meant shipping small, not padding

- **Shipped 1 file-disjoint code PR + 1 bookkeeping** from a deliberately SKEPTICAL 4-Haiku scout sweep (data/alpha · risk/safety
  · backtest/learning · quality/frontend), each primed with "default to NOTHING-GENUINE; 4 hardening runs already today; egress
  blocked." 3 of 4 scouts returned NOTHING-GENUINE. (#104) **MTM resolution side-effect integrity** — `check_resolutions()` settled
  a held position at a fabricated `winning_price=0.0` (a phantom TOTAL loss) whenever the held `token_id` was ABSENT from a resolved
  market's `outcomes` (a data inconsistency: re-resolved/stale market, malformed/short `clobTokenIds`). That invented loss fed
  `record_realized_pnl()` and could **AUTO-TRIP the kill switch on a fiction** (halting the whole bot), and cached the position
  resolved so it never reconciled. Fixed with a `None` sentinel: settle only when the token is present (a found loser still settles
  at a real 0.0), else log loudly + skip + leave UNCACHED to retry. engine_pct stays 74 (a correctness fix, not new completeness).
  No DoD/floor box ticked.
- **THE pattern — the same honesty bug class keeps recurring in new functions; once named, audit for it everywhere.** #101 ("a
  missing quote is not a 50/50 market"), #95 (no phantom fill), the Kalshi one-sided-book fix, and now #104 are all the SAME defect:
  *absent/incomplete data silently upgraded into a confident value* (a 0.5 price, an empty-token fill, a midpoint, a 0.0 total-loss
  settlement). **Lesson: when you fix one "fabricate a plausible default for missing data" bug, grep the WHOLE pipeline for the
  pattern — every place that defaults a missing/absent field to an in-range value instead of failing/skipping. The settlement path
  was the analog the prior data-ingest fixes hadn't reached.**
- **THE gate earned its keep WITHOUT a fix cycle — and the value was the REPRODUCTION, not a catch.** All 3 reviewers (2 Sonnet + 1
  Opus safety auditor) cleared #104 first pass, but Reviewer B AND the Opus auditor each INDEPENDENTLY restored the pre-fix logic and
  ran the regression test, capturing the real failure (`[KILL SWITCH] ACTIVATED — realized $-50.00 breaches -$5.00`). On the 5th run
  of the day, with heavy padding-scrutiny, that independent reproduction is exactly what distinguishes a genuine value-bar-clearing
  fix from busywork — the reviewers proved reachability (#101's `active=False` does NOT gate this path; resolution gates only on
  `resolved`) rather than rubber-stamping. **Lesson: a regression test that "fails loud on the pre-fix code" is only credible if
  someone actually RUNS it against the old code — make the reviewers do it; a green test on the new code proves nothing about the bug.**
- **Anti-SCARCITY vs anti-PADDING, the honest call on a near-empty barrel.** 5th factory run today; 4 prior runs already hardened the
  engine; egress universally blocked → the binding constraint (a real OOS corpus + alpha) is OWNER-scope and untouchable. The honest
  maximal set was ONE fix — not zero (a real kill-switch-on-fiction defect was there) and not a padded 3-4 (the other scouts genuinely
  found nothing; the one extra find, NearCertaintyStrategy 72h-vs-720h, is ROADMAP F1 = an OWNER trading-behavior decision the loop must
  NOT make unilaterally, so it was SURFACED not built). **Lesson: on a mature engine with the headline constraint owner-blocked, "ship
  exactly the genuine fixes, however few" beats both stopping at zero (scarcity) and inflating to look busy (padding). 1 is a fine
  number when the gate-verified barrel holds 1.**
- **THE meta-signal worth surfacing to the OWNER (not a harness proposal).** 5 runs in one day, all hardening, no DoD movement, because
  real convergence requires data the loop CANNOT fetch (egress 403/000 for Polymarket + Kalshi + HuggingFace). This is NOT `churning`
  /`stuck` (0 reverts, 0 abandoned, durable correct changes) and NOT a loop-rule deficiency (egress is environmental + already tracked
  across OA-11/13/15/16), so per §10b NO harness proposal is warranted. BUT the highest-value next action has clearly MOVED to the
  owner's side: action **OA-16** (download the Polymarket-v1 HuggingFace corpus — 1.3M markets, CC-BY-4.0, the preferred bypass) or
  **OA-13** (widen egress). **Lesson: when the loop is healthy but DoD-blocked on an owner action, the right channel is the routine
  NOTIFICATION (surface the owner action), not a harness proposal (which is for the loop's own rules) and not silence (which wastes the
  run's signal).**
- **Two pre-existing latent issues the Opus auditor flagged for a FUTURE run (orthogonal to #104, not folded in to respect scope/≤2-cycle
  brake):** (1) `check_resolutions` fetches via `get_market_by_slug(pos.market_id)` but positions are created with `market_id=opp.market.id`
  (the Gamma numeric id, not the slug) — if `id != slug`, the fetch returns None and resolution may **never fire in prod** (the existing
  tests mock `get_market_by_slug`, so they can't catch it). (2) `_persist_resolution` swallows failures, so in-memory settlement and the DB
  can diverge. Both are real candidates for the next sweep — verify #1 against the actual Polymarket id/slug semantics first.
- **Process: SKEPTICAL scouts (4, Haiku) + 2 Sonnet reviewers + 1 Opus safety auditor, all reading `git diff base...branch` objects (not the
  shared tree). Local gate: 619 pass; ruff is a local-only artifact (`/root/.local/bin/ruff`; CI has none) — verified my diff added 0 new
  ruff findings (orchestrator 14→14, test 0→0) before relying on the required check.** Squash auto-merge on the required check; bookkeeping in
  this separate PR.

## 2026-06-30 (4th run) — data-integrity + security hardening (4-PR run); the live WS feed had NO price validation (cache-poisoning), and the Polymarket parser FABRICATED a DQV-passing 0.5/0.5 market

- **Shipped 4 file-disjoint code PRs + 1 bookkeeping** from an 8-Haiku scout sweep (data-integrity / security /
  correctness / artifact-freshness lenses) across tracks A–G: (#99) **§12 input-bounds + error-hygiene** — bound the
  remaining UNBOUNDED read endpoints (`/markets`,`/orders`,`/price-history`,`/pnl-history`,`/bot/activity`) + quant-model
  float params (`mid_price`∈[0,1], `hours_to_resolution`>0, bayesian signal, mc-kelly fraction/bankroll), and sanitize the
  unauthenticated `/status` raw-`str(e)` leak to the exception TYPE name only; (#100) **WS price validation** — the live
  `websocket_feeds._handle_message` did a bare `float(change["price"])` with NO validation; (#101) **Polymarket parse
  honesty** — the Gamma parser fabricated a `0.5`/`""` for incomplete outcome arrays; (#102) **CalibrationBucketStrategy
  active-gate** (the Opus auditor's named finding). engine_pct 73→74. No DoD/floor box ticked — data-integrity + security
  hardening, not a validated edge.
- **THE headline gap — the live WS price path had ZERO validation, and the batch DQV gate doesn't cover it.** ROADMAP A5
  wired `DataQualityValidator` into the orchestrator SCAN loop, so it's easy to assume "prices are validated." But the
  real-time `websocket_feeds.py` cache (`_prices`) is written by `_handle_message` with a bare `float(change["price"])`
  and consumed by `orchestrator.update_prices()` → `pos.current_price` → `unrealized_pnl`. DQV never sees it. A malformed
  `"inf"`/`"nan"`/`"1.5"` would silently poison the cache; an `inf` bid/ask flows through `midpoint` into P&L + circuit
  breakers. **Lesson: a data-quality gate validates the PATH it's wired into, not "the data" — enumerate every WRITER to a
  shared cache (batch fetch AND the live WS feed AND last-trade), not just the one the gate guards.**
- **THE side-effect-integrity catch — a fabricated price that PASSES the quality gate is the data analog of a fake fill.**
  The Polymarket parser padded a missing price with a hardcoded `0.5` and a missing token with `""`. A symmetric
  fabricated `0.5/0.5` SUMS TO 1.0 and (with both tokens present) PASSES `DataQualityValidator` as a tradeable market —
  the exact Kalshi one-sided-book trap in a new place. **Lesson: fabricating a "reasonable-looking" default for missing
  data is a correctness bug even when the default is in-range — the quality gate is tuned to catch GARBAGE, not PLAUSIBLE
  fabrications. Make the fabrication FAIL the gate (sentinel `0.0`, sum≠1) AND mark the market untradeable (`active=False`),
  not invent a value that slips through. A missing quote is not a 50/50 market.**
- **THE reviewer catch (Reviewer A REQUEST_CHANGES) — a stale-but-fresh timestamp.** PR-#100's first cut refreshed the
  `last_trade_price` timestamp UNCONDITIONALLY, even when both price and size were rejected. Since `data_age_seconds` (the
  300s staleness eviction) derives from that timestamp, a flood of all-invalid last-trade messages would keep a STALE quote
  looking fresh forever. **Lesson: when validation rejects an update, don't advance the freshness clock either — a rejected
  write must be a true no-op (value AND timestamp), or you trade staleness for a subtler stale-but-fresh bug.** Fixed with
  an `updated` flag + a regression test.
- **THE auditor catch (Opus SOUND, with a named LOW finding) — the honesty invariant relies on EVERY consumer checking
  `active`.** The parse fix's protection is "mark the bad market `active=False`, every strategy skips it." The auditor
  enumerated all deployed strategies (all gate on `active`) and found ONE that didn't: `CalibrationBucketStrategy.scan`. For
  a NON-price failure mode the YES price is a real in-range value, so it would leak. UNWIRED today (abstains with
  `model=None`) so not a live break, but it's the B4a alpha mechanism that WILL be wired. **Lesson: a guard that relies on
  "every consumer checks the flag" is only as strong as the consumer that forgets — when you add an honesty flag, grep
  EVERY reader and confirm each gates on it, including the unwired-but-coming ones; fix them before they're wired.** Shipped
  as #102 in the SAME run (disjoint file).
- **Anti-padding held HARD under a mature engine + an egress-blocked constraint.** All egress (HuggingFace, Polymarket,
  Kalshi) is 403 this run, so binding-constraint work (OOS corpus + alpha) is owner-scope. The 8 scouts surfaced ~25
  candidates; I rejected ~20: a kelly-fraction seed_hash "determinism bug" that's a FALSE POSITIVE (the `_seed_hash`
  docstring deliberately excludes the strategy_fn); `paper_simulator.py` cost-leak (the module is imported NOWHERE — dead);
  a "scan unguarded" finding ALREADY fixed in #96 (stale ROADMAP read); a kill-switch multi-process race (overengineered for
  the singleton) and a loss-cap FP-boundary "fix" that would make the cap LOOSER (wrong, unsafe direction); E-track polish
  (unwired); the SELL-path risk wiring (a held-to-resolution no-op ALREADY deferred 2026-06-29); F7 lint activation (staged
  ratchet). **Lesson: in a mature repo with the headline constraint owner-blocked, the honest maximal set is small +
  defensive — verify each scout claim against the ACTUAL code (is the module wired? is the "bug" the documented contract? is
  the safe direction tighter or looser?) before selecting; a Haiku scout's confident finding is a hypothesis, not a work item.**
- **Process / env: local gate needs `pip install -r backend/requirements-ci.txt` + `fastapi` (importorskip tests), and
  ruff must be REMOVED from the env (`/root/.local/bin/ruff`) — `preflight` step 3 `bad`s on ruff findings ONLY when ruff is
  present; CI has no ruff, so the 166 pre-existing findings don't red the gate. Verified my diff added 0 new ruff findings
  (statistics identical before/after) before relying on that.** Reviewed via `git diff BASE...HEAD` objects (not the shared
  tree); ONE consolidated fix cycle; split integration branch into 4 disjoint branches; auto-merge on the required check.

## 2026-06-30 (2nd run) — security + side-effect-integrity + executor fail-closed (3-PR run); an Opus auditor broke a fail-safe that was DEAD CODE in prod, and a STALE local default-ref nearly shipped PRs on old code

- **Shipped 3 file-disjoint code PRs + 1 bookkeeping** from an 8-Haiku scout sweep across tracks A–G:
  (#96) **API security hardening** — `/prediction-markets/scan` was the one state-mutating route still UNGUARDED
  (its sibling `/bot/scan-now` was guarded) → added `_MUTATING_AUTH`; bounded `market_limit`/search `limit`/`query`/
  kill-switch `reason`; and **risk/config now bounds-validates** so a non-positive `daily_loss_limit_usd` (which would
  DISABLE the loss cap — the check is `realized_loss > limit`) returns 422. Pure fastapi-free `risk_config_validation.py`
  in the CI gate + importorskip fastapi adapter tests. (#95) **Side-effect integrity** — the orchestrator built ONE
  order with an EMPTY token_id for multi-leg arb opportunities (`outcome_idx == -1`); the paper executor `_simulate_fill`
  fills ANY order → a phantom fill + empty-key position that never traversed a real per-leg path. Now skipped honestly
  (audit `skip_multi_leg`) until per-leg execution (B1) is built (DECISION COROLLARY). (#94) **Executor fail-closed
  hardening** — a durable-store rehydrate failure now FAILS CLOSED (kill switch ACTIVE) instead of silently resuming a
  killed bot, + loud loss-cap config coercion. No DoD/floor box ticked — hardening across security/§12, run-risk-readiness
  (D3/D4), and side-effect integrity (B1); engine_pct 72→73.
- **THE win — an Opus live-safety auditor returned NOT-SAFE on a fail-safe that my unit test "proved."** PR-94's new
  fail-closed branch in `attach_state_store` only fires if `_rehydrate_state()` RAISES. But the PRODUCTION store
  `ExecutorStateStore.load()` wrapped its whole read in `try/except → return None`, so it NEVER raised — the fail-closed
  branch was **dead code against the only store that ships**, and a real DB-unreachable restart would still silently
  resume a halted bot. My test passed only because it used a bespoke boom-store whose `load()` raises (no production path
  does). **Lesson: a fail-CLOSED guard is only real if the dependency it guards actually SIGNALS the failure. A
  best-effort `except → return None` swallow that collapses "unreadable" into "absent" defeats any downstream
  fail-closed. Fix: make `load()` distinguish a genuinely ABSENT row (return None → fresh) from an UNREADABLE store
  (RAISE), and TEST the REAL store against a broken engine (missing table), not a bespoke raiser. Re-audit returned
  FIX-HOLDS.** Also added a defense-in-depth empty-token reject in `_check_risk` (a PR-95 auditor caveat) so no path can
  phantom-fill an empty-token order.
- **THE process hazard — a STALE local default-branch ref nearly shipped PRs based on ~25-commit-old code.** Session
  started in DETACHED HEAD at the real latest (`e4b1efe`), but the LOCAL `claude/llm-stock-trading-app-fXupf` ref pointed
  at a stale `19e882a` (~#73, before the auth + Kalshi work). PR-B was created via `git checkout -b` from the detached
  HEAD (correct base), but PR-C and PR-A were branched via `git checkout <local-default-ref>` → **wrong, stale base**.
  Caught it when the security scout's "/scan is the only unguarded route" contradicted my session-start read showing ALL
  routes guarded: `git show <local-ref>:routes.py` had ZERO `_MUTATING_AUTH` and no `auth_core.py`. **Lesson: NEVER trust
  the local default-branch ref in a long-lived/detached checkout — it can lag origin badly. Before branching every PR:
  `git fetch origin <default> && git branch -f <default> origin/<default>` (or branch straight from `origin/<default>`).
  Diagnose drift by OBSERVING git objects (`git show <ref>:<file>`, `git merge-base`), not by theorizing.** Recovered by
  fetching origin, resetting the local ref, and rebasing PR-C/PR-A onto the true base — which immediately surfaced a
  second real bug the stale base had hidden: PR-C's test passed on the old code but FAILED on the real code (the #91
  category-cap hardening rejected the test opp upstream of the multi-leg branch), forcing a permissive-risk fix. Stale
  base = false-green tests.
- **Anti-scarcity + anti-padding both held:** DROPPED cost-model impact sensitivity tests (already 19 tests) and the A5
  staleness fixture (already covered) as redundant; DEFERRED B1-full per-leg execution (risky, larger follow-up), B6
  enable/disable (collides routes.py with PR-A), the E-track wiring (DECISION COROLLARY — unwired plumbing no real alpha
  drives), F7 lint + F5 Playwright (repeatedly deferred for good reasons). The maximal disjoint value-bar set this run was
  the 3 security/safety/integrity PRs the deep-audit scouts surfaced — all ship-critical-dimension work.
- **Process: 2 Sonnet reviewers + 1 Opus safety auditor per money/safety-path PR (8 reviewers), ONE consolidated fix
  cycle on PR-94 (load() + docstrings + empty-token guard + tests) + a fresh re-audit (FIX-HOLDS).** Reviewers ran
  read-only via `git --no-pager diff base...branch` (objects, not the working tree — avoids the shared-tree git hazard).

## 2026-06-30 — A3 Kalshi venue adapter + deep-audit hardening (2-PR run); the gate caught a BUILDS≠WORKS the tests passed over

- **Shipped 2 file-disjoint code PRs + 1 bookkeeping** from an 8-Haiku scout sweep across tracks A–G:
  (#92) **A3 — a second-venue Kalshi DATA adapter** (`kalshi_client.py` + `kalshi_history_fetcher.py` +
  `scripts/fetch_kalshi_history.py`) behind the SAME `Market`/`Outcome`/`HistoricalMarket` interface
  (imported, never redefined), offline fixture-tested, no new credential (public data); and (#91) a
  **deep-audit hardening pass** (live-only control-auth boot-guard; category-cap under-count fix;
  risk-score div-by-zero guards; MTM `PolymarketClient` reuse; routes.py exception-detail leak
  sanitization). engine_pct 71→72. No DoD/floor box ticked — venue infra + hardening, not a validated edge.
- **THE win — an Opus parsing auditor returned BROKEN on a Kalshi adapter with 45 green tests.** The
  offline fixtures had encoded Kalshi's **request-side FILTER words** (`status="open"`, `status="finalized"`)
  as if they were the values a **live response** carries — but a real Kalshi `/markets` response market
  carries `status:"active"`, and resolved markets are `settled`/`determined`; the discovery filter
  `"finalized"` is not even a valid Kalshi filter value. So the adapter would have mapped **every live
  market to untradeable** (dropped) and the history fetcher would have pulled nothing — while 45 tests
  passed because they tested the code against its own wrong assumptions. **Lesson: green tests against
  self-authored fixtures prove NOTHING about a venue contract you can't reach. When egress blocks live
  verification, (a) encode the DOCUMENTED contract (not a guess), (b) be ROBUST to a set of plausible
  values per state, (c) FAIL LOUD on an unrecognized value (log a warning + treat as untradeable) so a
  real-run mismatch surfaces immediately instead of silently dropping/mis-trading, and (d) DISCLOSE in
  SELF_VALIDATION that the contract is documented-but-unverified-live + add an owner OA to confirm on first
  fetch. A re-audit (FIX-HOLDS) is warranted after a BROKEN→fixed correctness change.**
- **Win #2 — a live-safety auditor caught a ~10x risk over-reservation in my own fix.** The category-cap
  fix reserved `RiskConfig.max_single_position_usd` ($50), but the executor's REAL per-trade notional cap is
  the decoupled `executor.max_position_usd` (~$5 in prod). The fix was conservative (over-blocks, safe
  direction) but 10x too aggressive AND the justification cited the wrong field. **Lesson: when a gate
  estimates "how much could this add," read the ACTUAL enforced cap from the object that enforces it
  (`executor.max_position_usd`), not a same-named config field that isn't wired to it.**
- **Honest one-sided-book fix (side-effect-integrity flavor):** a 0/0 Kalshi book used to fall through to a
  fabricated **0.50** that passed DataQualityValidator as a *tradeable* market, and a one-sided book
  averaged the quote with 0. Fixed: midpoint only when both sides quoted; else the quoted side; else
  `last_price`; else **forced untradeable** (`active=False`). **Lesson: a missing quote is not a 50/50
  market; fabricating a midpoint from a one-sided/empty book invents a tradeable price out of nothing (the
  data analog of a fake fill).**
- **Disjoint discipline under contention (anti-scarcity, not padding):** B6 (per-strategy enable/disable —
  the scan loop already gates on `strategy.config.enabled`, only needs a persisted store + endpoint) and D6
  (a venue reconciler) were genuinely buildable but BOTH wanted `orchestrator.py`, which the hardening PR
  already owned — deferred to a later run (the disjoint rule). F5 (Playwright) deferred on exec-risk +
  can't-CI-gate; F7 lint on low-value/trading-path-risk. A deep-audit scout found NO real defect beyond the
  audit findings, so none was invented.
- **Process / git hazard:** review/audit subagents running `git`/`pytest` in the SHARED working tree left
  stray staged files on a sibling branch (an auditor checked out the other branch to run its tests). The
  pushed commits stayed clean (the source of truth), but **don't let reviewer subagents mutate git state in
  the shared tree** — give them `git diff BASE...BRANCH` (reads objects, not the working tree); accept that a
  per-branch `pytest` needs that branch checked out. Cleaned by unstage + `rm`; re-verified the pushed PR
  diffs via the API.

## 2026-06-29 — DETERMINATION: authed-journey-tier-in-CI directive = SKIP (personal bot, no auth tier)

- **Directive:** enforce an AUTHENTICATED journey tier in CI (sign-up → dashboard, sign-in, paywall →
  checkout, account) against a real auth backend, as a required check. Its scope line: *"If your
  project has no users/auth (e.g. a personal bot), skip — there's no authed tier to enforce."*
- **Evidence-based determination (read the code, didn't assume):**
  - LLM-Quant is a **personal bot** (VISION: "Not a product. Not marketed. No users.").
  - Auth = a **single shared-password owner gate**: `frontend/lib/auth.ts` `checkPassword` compares
    against one `APP_PASSWORD` env (constant-time), stateless HMAC cookie. **No user lookup, no DB,
    no sessions table.**
  - **NO signup / register / accounts / paywall / checkout / billing** (grep across `frontend/` = 0
    matches); **no Supabase / next-auth / Stripe**. So NONE of the directive's enumerated authed
    journeys exist, and the Supabase auth-backend + CSP `connect-src` machinery has no analog.
  - **No journey/Playwright/e2e suite and no Node/browser CI job** (gate is Python-only; F5 — the
    Playwright visual/journey suite — is deliberately deferred product work).
- **Decision: SKIP, per the directive's explicit personal-bot carve-out.** Building a Node + Playwright
  + browser CI tier for a single-password personal dashboard would be disproportionate and is exactly
  what the scope clause excludes. `required_status_checks` unchanged: `["code + safety gate (blocking)"]`
  (enforce_admins=true, strict=false).
- **The one honest residual (NOT this directive's job):** the owner-gate flow (password → /predictions
  dashboard) renders are not exercised at runtime by the current gate — a small frontend BUILDS≠WORKS
  gap that belongs to **ROADMAP F5** (the deferred UI journey suite), to be built as product work if/when
  justified, NOT as a forced authed-tier required check.
- **Lesson:** "skip" must still be earned by EVIDENCE — confirm no users/signup/paywall/auth-backend by
  reading the code, then record the determination so the loop doesn't re-litigate this directive every run.

## 2026-06-29 — GTM honesty gate (validate_gtm): a growth number with no source is a fabrication risk

- **Parity ask:** AptDesignerAI added a required `validate-gtm` check (GTM analog of
  `validate-capabilities`). Built the same here, adapted to stack + product.
- **Stack adaptation:** wrote it in **Python** (`scripts/validate_gtm.py`), not `.mjs` — the preflight
  gate runs Python, not Node, and `requirements-ci.txt` is Python-only; a Node script would force Node
  into the gate job. Mirrors the reference's OUTCOME (fail-closed on a sourceless metric + GTM_SCORECARD
  validity), wired as blocking preflight step **9e**.
- **Product adaptation (the real insight):** LLM-Quant is a PERSONAL bot — NOT marketed, no users — so
  the literal `funnel/acquisition/pmf/channels` GTM sections don't exist. The meaningful analog of "a
  growth number with no source" is the performance **`metrics`** block (weekly_pnl/hit_rate/…), whose
  "connected source" is **`venues_connected`**. So the rule becomes: you cannot report a paper/live PnL
  or hit-rate with ZERO connected venues. Same honesty principle, mapped to the product's real growth
  surface.
- **Two traps avoided:** (1) TARGET/CONFIG keys (`weekly_pnl_target_usd`, `*_floor`, `*_cap`,
  `live_enabled`, `engine_pct`) are EXCLUDED from the tripwire — a target is not reported traction, so
  it must not trip the gate. (2) The grade-validity check flags any short non-grade string (e.g. `Z`),
  not just malformed A–F — my first regex was too narrow and a test caught it.
- **Readiness N/A:** the reference's `--readiness` requires a GTM_SCORECARD; this bot has no GTM
  auditor/scorecard and won't, so GTM readiness is N/A and `--readiness` is deliberately NOT wired into
  the gate (would red-block). Documented in the script.
- **Lesson:** GTM-rigor parity for a no-GTM product isn't vacuous — re-map "growth metric" to the
  product's actual traction numbers (here: trading performance sourced by connected venues) and the
  same fail-closed honesty gate becomes genuinely protective. Green pre-launch (all metrics 0/null);
  11 regression tests; now a blocking step inside the required check.

## 2026-06-29 — Canonical sync: FACTORY_STANDARD.md re-synced to AptDesignerAI + routine anchored to it

- **Canonical sync (authorized):** overwrote `FACTORY_STANDARD.md` VERBATIM with the canonical copy
  at `github.com/subhsubh24/AptDesignerAI/FACTORY_STANDARD.md` (product-agnostic, ahead of ours —
  adds the §6 **VALIDATION CAPABILITY** principle + other deltas; reflowed to ~80col). Confirmed
  **byte-identical** via git blob sha (`caa40a8b04dddc400343a6ac6ffe8748a4b8517c` on both). Structure
  intact (22 `##` headings, §0–19 + §6b + §10b); ROADMAP's §6b/§10b/§14 references still resolve.
  This is the ONLY way this file changes — never as loop work, only a deliberate canonical sync.
- **Routine anchor fix:** the model/strategy factory routine's `ORIENT FIRST` read FACTORY_STANDARD
  only implicitly. Changed it to read **FACTORY_STANDARD.md FIRST** (the shared discipline every
  factory follows identically), THEN ROADMAP.md — so every run is grounded in the standard before the
  product specifics. Self-validation gate left as-is (it's good); this only adds the missing anchor.
- **Lesson:** the standard being byte-identical across factories is only useful if each loop actually
  READS it first — the manifest/gate enforces product behavior, but the shared *judgment* (value bar,
  disjoint rule, BUILDS≠WORKS, deep-audit cadence) lives in FACTORY_STANDARD and must be the first read.

## 2026-06-29 — Control-path hardening (3-PR run); an auditor caught a BUILDS≠WORKS the tests passed

- **Drove 3 named QUALITY_SCORECARD top_gaps to done** (consume-the-grade, never self-grade): run-risk-readiness
  ("kill switch + realized-PnL are in-memory only; a restart un-trips the halt") → durable
  `executor_state_store.py` (singleton table, mirrors audit-log/registry), persisted on every kill-switch/PnL
  mutation, rehydrated on the production executor in `get_executor()`; security ("state-mutating routes have no
  auth") → a degrade-safe shared-secret bearer guard on the 12 mutating routes; design-taste (dead `Math.random()`
  `equity-chart.tsx` + floating P&L axis) → deleted + axis fixed. Shipped as 3 file-disjoint PRs (backend / frontend /
  bookkeeping), rebased onto the newly-merged #82.
- **THE win — an Opus live-safety auditor broke a BUILDS≠WORKS my unit tests passed over.** The persistence tests
  passed because they call `init_db(engine)` / `create_all` explicitly. But in PROD, `init_db()` runs `create_all`
  BEFORE the table modules are imported (they're imported lazily inside orchestrator/executor construction, which runs
  AFTER `init_db` at startup) — so the durable tables were **never created**, every load/save hit "no such table" and
  was swallowed. The audit-log (G3) + registry (B3) durability had the SAME latent bug, silently, for runs. **Lesson:
  a `table=True` class only gets a table if its module is imported BEFORE `create_all`. Lazy-imported table modules are
  invisible to a startup `create_all` that ran first. A test that imports the module then calls `create_all` CANNOT
  catch this — you must test the real cold-start path (a clean subprocess with a temp DATABASE_URL, asserting the
  tables exist). Fix: import all table-bearing modules in `init_db` before `create_all`, pinned by a subprocess
  regression that fails loud.**
- **Test-isolation lesson (the regression test itself):** a first cut used `importlib.reload(db)` + env to point at a
  temp DB; it passed in isolation but FAILED in the full suite (other tests had already imported the table modules /
  bound the module-level engine, contaminating global SQLModel.metadata + the reloaded engine). **A clean subprocess is
  the robust way to test "cold-start prod behaviour" — module-global state (SQLModel.metadata, lru_cached settings, a
  module-level `engine`) leaks across tests in one process and makes reload-based tests lie.**
- **CI-light constraint shaped the auth design:** CI installs only `requirements-ci.txt` (no fastapi). So the auth
  DECISION lives in a pure, fastapi-free `backend/app/auth_core.py` (CI-tested: open-when-unset, constant-time match,
  all mismatches denied), and `api/auth.py` is a thin FastAPI adapter. **Lesson: put a security primitive's decision in
  a framework-free module so the lightweight gate can validate it; keep the framework binding to a trivial adapter — and
  verify the adapter once for real (a TestClient 401 check) where the framework IS installed (guarded by `importorskip`
  so CI skips it).** Also: `backend/app/api/__init__.py` eagerly imports fastapi, so a CI-safe pure module must live
  OUTSIDE the `api` package (it's at `backend/app/auth_core.py`).
- **Degrade-safe auth, not a fake control:** `BACKEND_API_TOKEN` unset (default) ⇒ auth disabled ⇒ unchanged paper/dev
  (existing route tests pass with no token); set ⇒ enforced. This is the LIVE_TRADING_ENABLED pattern (a real, tested,
  enforced control shipped OFF by default), NOT the removed-fake-UI-toggle anti-pattern — the auditor confirmed
  REAL+SOUND. The owner-irreducible half (set the token + a frontend SERVER-SIDE proxy so the browser never holds the
  secret) is OA-14; a browser SPA can't hold a shared secret, so a NEXT_PUBLIC token would defeat the purpose.
- **Process:** ONE consolidated fix cycle for all 5 reviewer/auditor reports (2 Sonnet + 3 Opus), re-verified green — no
  3rd audit on strictly-more-conservative/honesty + a well-tested root-cause fix (≤2-cycle brake). Anti-scarcity AND
  anti-padding both held: dropped D2-SELL-path (a no-op in the held-to-resolution flow = a fake control) and the
  alpha/egress-blocked items (B1/E7/B3-derivation/C2) on the value+disjoint rules, not invented.

## 2026-06-29 — Self-validation ADDENDUM: readiness mode + UNMET surfacing + 5 pitfalls + honesty-reconcile

- Cross-factory alignment of the self-validation gate. Added: a `--readiness` mode
  (`check_self_validation.py --readiness`) wired into preflight step 9d; a per-capability
  **`ci_validatable`** flag; a **readiness** block (`enforced_in_ci`, `capabilities_total`, `unmet`)
  mirrored in BOTH `SELF_VALIDATION.readiness` and `LOOP_HEALTH.validation`.
- **Surfacing (don't let unmet capabilities die in CI logs):** an ACTIVE capability that is
  `ci_validatable:false` (needs an owner-only secret) is UNMET → the checker requires it to appear
  in BOTH an urgent PENDING_OPS `OWNER_ACTION` `validation-capability-<service>` AND
  `LOOP_HEALTH.validation.unmet`. In only one place = invisible to the owner/dashboard = a gate
  failure. (unmet=[] today — no active capability needs a secret to validate.)
- **The 5 pitfalls, checked against this repo:** (1) scan is `backend/app` runtime code only — NOT
  tests/scripts/CI (no false drift from CI-only env vars). (2) pyyaml is a DECLARED ci dep + the gate
  now FAILS (not skips) if it's absent — a vanished parser must never silently disable the check.
  (3) per-PR scoped/base-diff machinery is N/A here: LLM-Quant runs FULL readiness on every PR
  (stronger than scoping), so no `fetch-depth:0`/base-ref diff needed. (4) two modes shipped: default
  coverage + `--readiness` (any unmet fails, wired into the gate). (5) HONESTY: each mock/degrade/
  gated capability carries a `real_flow_note` proving the genuinely-critical path is really exercised,
  and the factory's adversarial auditors now reconcile that a 'validated' capability isn't a stubbed
  un-exercised critical path (the email-verification trap in a new form).
- **Lesson:** "validated" is a claim that must survive an adversary — a mock is only honest if the
  real money/side-effect path is exercised elsewhere; and an unmet capability is only safe if it is
  LOUD in every channel the owner reads, not buried in a CI log.

## 2026-06-29 — Self-validation coverage gate: the loop can prove it validates the app it builds

- **Ask:** ensure the factory can validate the app itself — has all the env keys it needs to
  self-validate, and if it hits a NEW service needing a new key, it SURFACES that and BLOCKS
  subsequent PRs until provided. Don't let an unvalidatable capability ship silently.
- **Key reframe (the honest answer to "does it have all the keys"):** the gate is DESIGNED to need
  ZERO external keys to validate the active app — it's in-process / deterministic / mocked. So the
  loop CAN fully self-validate the core app with no credentials. Keys only ever matter for
  *activation* (live trading = human-core) or *enhancement* (Gemini = optional, degrades to
  templates). That's a feature, not a gap.
- **Built (blocking, in the `code` gate as step 9d):**
  - `docs/ci/SELF_VALIDATION.md` — manifest: every capability → how it's validated + which credential
    + status; `credential_inventory` lists every external cred the code reads (13 today).
  - `scripts/check_self_validation.py` — enforces TWO things: (1) every `active` capability must be
    `validated`/`gated_off`/`degrades_safely` (an active+unvalidated cap fails); (2) every credential
    the CODE reads (a `*_api_key/_secret/_token/_url/...` Settings field OR `os.environ.get` of that
    shape under backend/app) must be DECLARED — a NEW undeclared one fails the gate. That's the
    "new service surfaces + blocks" forcing function.
  - `backend/tests/test_self_validation.py` (8 tests, in the gate) + factory-routine discipline (update
    the manifest in the SAME PR that adds/activates a capability; gate it off or record the
    OWNER_ACTION if a key is genuinely required; NEVER fake a validation).
- **Proven end-to-end:** appended a simulated `os.environ.get("KALSHI_API_KEY")` to a real module →
  gate FAILED with the key surfaced ("Until then, every PR is blocked"); reverted → green. Seeded
  green against current code (13 creds all declared) so it blocks only FUTURE violations, never the
  loop today (verify-green-before-requiring).
- **Lesson:** the resolution for a capability that needs a key the CI gate can't have is the
  gated-live-path pattern generalized — either GATE IT OFF (validated_as_off) so no active flow
  depends on it, or declare the OWNER_ACTION + block. Both are honest; faking the validation is the
  only forbidden move. The cleanest "self-validation" guarantee is a gate that needs no secrets to
  exercise the real pipeline — keys are for turning capabilities ON, never for proving they work.

## 2026-06-29 — Wired the learning loop (E6+B3) + honest cost-arb + E5/E2 engines (5-PR run)
- **Shipped 4 file-disjoint code PRs + 1 bookkeeping** from an 8-Haiku-scout sweep: PR-1 (orchestrator E6
  attribution + B3 lifecycle persistence + D2 resolution-risk fix), PR-2 (SameMarketArbitrage cost-model
  net edge + neg_risk MECE guard), PR-3 (E5 evaluation-window engine), PR-4 (E2 calibration-drift detector).
  Integrated gate green (419→421 tests, runtime harness deterministic, walk-forward reproduces) BEFORE split.
  engine_pct 66→68. No DoD/floor box ticked — wiring + correctness + infra, not a validated edge.
- **THE adversarial win — an Opus auditor BROKE a "guaranteed arbitrage" my own tests "proved."** PR-2 made
  the SameMarketArbitrage *cost accounting* honest (cost-model net edge vs flat `discount-0.02`), and 8 tests
  asserted the conservatism. But the auditor showed the strategy is NOT a locked arbitrage as WIRED: (1) the
  multi-outcome branch had no MECE check (could fire on a non-exhaustive candidate list); (2) `outcome.price`
  is the CLOB **midpoint**, not the ask you'd pay, and flat 0.5% slippage ≠ the real half-spread; (3) the
  orchestrator `outcome_idx=-1` path records ONE phantom fill (empty token_id), never placing a real per-leg
  order. **Lesson: "costed the basket correctly" ≠ "real guaranteed arbitrage." A dutch-book is only real
  if the outcomes are provably MECE (gate on `neg_risk`; binary is MECE by construction), you price the ASK
  with real depth, and you place+confirm each leg separately. Disclose midpoint/MECE/execution gaps; never
  ship a half-true "guaranteed". Tests that assert a convenient sub-claim (cost monotonicity) do NOT prove
  the headline claim — an auditor that RUNS the code finds what the tests were written to miss.**
- **Honesty win #2 — don't expose a gate that trusts self-asserted evidence over an API.** The B3 registry
  gates on the PRESENCE of caller-supplied backtest/OOS/calibration booleans (audit trail, not authenticity).
  My planned `POST /strategies/transition` let a 4-call walk reach PROMOTED with fabricated evidence. **Fix:
  removed the public write endpoint (GET read only); real transitions only via trusted in-process code that
  DERIVES evidence from the actual E5/E2 results (follow-up). Lesson (DECISION COROLLARY): never expose a
  control whose authenticity-backing isn't built — a gate on self-asserted evidence over an open endpoint is
  a rubber stamp.**
- **BUILDS≠WORKS — a reviewer caught my B3 wiring as a silent no-op.** The orchestrator is constructed with
  `scanner=None` (scanner attached AFTER, in `_get_orchestrator`), so the registry seeded empty and — because
  I persisted the empty seed — never re-seeded on the next boot → `GET registry` would return `[]` forever in
  the normal API path. **Fix: idempotent `sync_registry_with_scanner()` called after scanner attach; persist
  ONLY when something was actually added (never overwrite a real registry with an empty seed). Lesson: when an
  object is populated from state attached AFTER `__init__`, your init-time seeding runs against an empty
  object — make seeding idempotent + re-callable, and never persist an empty seed that wedges the next boot.**
- **Pre-existing import-order fragility (avoided, not introduced).** `test_prediction_markets.py` imports
  models via `app.*` while the newer suites use `backend.app.*`; running a `backend.app.*` suite BEFORE
  `test_prediction_markets` re-registers a non-`extend_existing` table (`PredictionPortfolio`) and crashes.
  The preflight list puts `test_prediction_markets.py` FIRST, so appending the 4 new suites at the END is
  safe (verified 421 passed in that order). **Lesson: append new test files to the gate list AFTER
  `test_prediction_markets.py`; the real fix (add `extend_existing=True` to the legacy models.py tables) is a
  separate, deliberate hardening — don't reorder the gate.** New `table=True` classes (B3 store) DO use the
  `extend_existing` + lazy-import recipe and are dual-import-safe (auditor-confirmed).
- **Process: ONE consolidated fix cycle for ALL 5 reviewer/auditor reports.** 2 Sonnet reviewers + 3 fresh
  Opus auditors ran against the integrated diff; I applied every finding in a single pass (MECE guard +
  honesty docs + endpoint removal + S1 seeding + deep-freeze immutability + reconcile threshold echo + minor
  cleanups), re-ran the full gate green, and shipped on mechanical verification — no 3rd audit on
  strictly-more-conservative/honesty-only changes (the ≤2-cycle brake).

## 2026-06-29 — Automate the real-data refresh (close OA-11 hands-off, without an egress change)

- **Why:** the cloud loop's env blocks Polymarket egress (403), so real OOS data only arrived when a
  human ran the fetcher. Owner asked to make the data path itself work. Honest constraint: BOTH
  "permanent" fixes are owner-scope — widening the env egress allowlist is a platform setting I have
  no tool for, and a backend cron needs the backend deployed + creds.
- **The third path I CAN leverage:** GitHub-hosted runners have open internet → they CAN reach
  Polymarket. Staged a scheduled GitHub Action (`docs/ci/PROPOSED_DATA_REFRESH.md`) that runs the
  fetcher and opens an auto-merging data-only PR. Can't write `.github/` headless, so it's staged +
  OA-13 + the owner picks Option A (egress allowlist, zero files) or Option B (the workflow + one PAT).
- **Made the refresh actually USEFUL:** re-running the fetcher returns the SAME ~54 top-volume markets
  (they don't change day-to-day), so plain overwrite never grows the corpus. Added `--merge` (union
  by `market_id`, never overwrite an earlier capture) so a scheduled refresh ACCUMULATES across weeks.
  Verified: seeded 49 + fetched → 54 merged.
- **The GITHUB_TOKEN caveat baked into the staged YAML:** a PR opened by the default `GITHUB_TOKEN`
  does NOT trigger other workflows, so `preflight.yml` (the required check) would never run and the PR
  could never satisfy branch protection → it would wedge. Fix documented: open the PR with a PAT
  (`DATA_REFRESH_PAT`). **Lesson: any bot-opened PR that must pass a REQUIRED check needs a PAT, not
  GITHUB_TOKEN — else the gate never fires and auto-merge hangs forever.**
- **Honesty held:** did NOT claim to "fix" egress (I can't change the platform). Stated plainly which
  parts are owner-irreducible, and delivered the parts I can (the `--merge` capability + the staged,
  caveat-correct automation). The edge work (less-pinned sampling + a real model) stays loop track B.

## 2026-06-28 — Make the required check have TEETH: enforce_admins + merge via --auto (never --admin)

- **Why:** requiring a check WITHOUT "administrators included" is toothless for the loop — its
  `--admin` merge bypasses it. The fix has two halves: (1) `enforce_admins=true` so even the
  loop's admin token must wait for CI; (2) switch the loop's merge protocol to `--auto` so it
  doesn't get stuck (auto-merge WAITS for the required check, then merges).
- **Repo/CI (one PR, shipped via `--auto` to prove the behavior):**
  - `enforce_admins=true`, `strict=false` (parallel file-disjoint PRs still auto-merge), repo
    `allow_auto_merge=true`.
  - **No new `.github/workflows/ci.yml`** — the existing `preflight.yml` already provides the
    required functional gate (`code + safety gate (blocking)` = paper/backtest reproduces
    deterministically; LLM-Quant has no UI journey). Mirrored the OUTCOME, didn't duplicate the
    workflow (and didn't touch `.github/`).
  - **Test-only rate-limit bypass:** there's no inbound limiter to bypass (gate is in-process),
    so wiring `E2E_DISABLE_RATE_LIMIT` to a limiter would be a fake control. What's REAL: a prod
    **boot-guard** (`config._forbid_test_bypass_in_live` + `test_config_safety.py`, wired into
    the preflight test list) that hard-refuses to boot if the flag is ever set with
    `LIVE_TRADING_ENABLED` — a future CI convenience can never weaken live.
  - Docs: ROADMAP "Shipping protocol" (the `--auto`, never-`--admin` rule); PROPOSED_CI §A3/A5/A6;
    LOOP_HEALTH `enforced_in_ci: true`.
- **Routines self-updated via RemoteTrigger** (factory / research / auditor — all merge PRs): added
  the `--auto`/never-`--admin` MERGE rule to each prompt. Procedure: GET → change ONLY
  `events[0].data.message.content` → PUT full job_config (model/cron/sources/allowed_tools/MCP
  preserved) → re-GET + diff to confirm only the intended text changed.
- **Lesson:** branch protection that excludes admins is security theater for an admin-token loop —
  you must set `enforce_admins=true` AND change the loop's own merge command to `--auto` IN THE
  SAME change, or the next autonomous run either bypasses the gate (admin) or wedges (can't merge).
  `strict=false` is the detail that keeps parallel disjoint PRs flowing without serial rebases.
- **Ordering (no lockout):** shipped the repo + routine changes and proved a PR auto-merges green
  FIRST, then flipped `enforce_admins=true`, then re-validated end-to-end.
- **COMPLETED 2026-06-28:** repo `allow_auto_merge=true`; protection = `enforce_admins=true`,
  `strict=false`, contexts `["code + safety gate (blocking)"]`. All three PR-merging routines
  (factory / research / auditor) carry the `--auto`/never-`--admin` rule (verified via re-get:
  only message content changed; model/cron/tools/sources/MCP preserved). End-to-end proof: PR #54
  sat OPEN/BLOCKED with auto-merge armed and merged ONLY after the required gate went green — the
  loop now waits for CI, cannot `--admin`-bypass. `LOOP_HEALTH.enforced_in_ci: true`.

## 2026-06-28 — Branch protection APPLIED (owner-authorized): the required check is now enforced

- Owner authorized the OA-12 toggle, so I applied it directly: `gh api -X PUT .../branches/<default>/protection`
  requiring **only** `code + safety gate (blocking)`, `strict=true`, `enforce_admins=false`
  (manual override retained). Verified `.protected == true`. The green gate is now **REQUIRED** —
  a regression of the live gate / kill switch / paper-pipeline reproduction can no longer
  auto-merge. Closed harness issue #51; OA-12 → done; `harness_proposals_open` → 0.
- **Lesson / scope clarity:** a `gh api` branch-protection call is a **repo-settings** action, NOT
  a `.github/` file edit — so it's inside what the loop may do *with owner authorization* (the
  "never touch `.github/`" rule is about files/workflows that hang headless runs). I have admin on
  this repo; I confirmed permission first, required ONLY the blocking job (never the honest-red
  informational one), and left `enforce_admins=false` so the owner keeps an override. The check was
  already proven green on every recent PR, so requiring it could not freeze merges.

## 2026-06-28 — Deploy automation: stage required-check + lint-at-zero; raise the FIRST harness proposal

- **Why:** make the owner's recurring work ~zero — a change that builds but is broken-for-a-user
  (or lint-dirty) must not auto-merge; and migrations shouldn't be a manual step.
- **Diagnosis first (didn't assume):** (1) the branch is **NOT protected** — the green
  `code + safety gate (blocking)` is advisory, nothing actually blocks a bad merge. (2) The
  **functional gate already exists + is real**: `preflight.sh code` runs the deterministic
  paper/backtest reproduction harness — exactly the gate the directive specifies for LLM-Quant
  (no UI journeys). (3) **Lint is silently skipped in CI** (`ruff` not in `requirements-ci.txt`;
  preflight runs it only `if command -v ruff`), and the tree has **166 ruff findings** in
  runtime-sensitive code. (4) **No migration framework** — schema is `SQLModel.create_all`
  (idempotent, already runs on deploy) → **Part B N/A**. (5) **No inbound rate limiter** (only
  CORS) and the gate is **in-process** (no server) → `E2E_RATE_LIMIT_BYPASS` + trusted-host envs
  are **N/A**; adding them would be unwired fake controls (DECISION COROLLARY).
- **Shipped (one PR):** `docs/ci/PROPOSED_CI.md` (staged required-check config + the exact
  branch-protection `gh api` command + gotchas + Part B skip rationale); `ruff.toml` (pins the
  lint standard for the ratchet); ROADMAP F7; PENDING_OPS OA-12 (branch protection); LOOP_HEALTH
  (`harness_proposals_open: 1`); this entry. **Raised gh issue #51** (label
  `loop: harness improvement proposal`) — the FIRST use of the META channel.
- **The key judgment — verify-green-before-requiring:** I did NOT add `ruff` to the CI deps now,
  because the tree isn't clean → it would turn the **required** gate red and **block all
  auto-merges**. And I did NOT bulk `ruff --fix` the trading path (removing an "unused" import on
  a `table=True` model / strategy registry can silently break registration — cf. the SQLModel
  double-registration incident). **Lesson: enabling a lint/required gate before the tree is green
  is a self-inflicted merge freeze. Stage it, pin the standard, ratchet to zero module-by-module
  with the gate green after each, THEN flip it on.**
- **The META channel, first real use:** branch protection is admin/`.github/`-settings scope —
  the loop genuinely cannot self-apply it. Rather than leave it as a silent wall, it became a
  tracked proposal (#51) + OWNER_ACTION (OA-12) + LOOP_HEALTH counter. **Lesson: the loop builds
  + stages + verifies everything it can; the irreducible human step (the one-time `.github/`
  apply + repo settings) is raised through the ONE channel that improves the loop's own rules —
  never silently dropped.**
- **How to apply:** when a change needs `.github/`/admin/repo-settings, build + stage the exact
  config in `docs/`, raise ONE harness-proposal issue with copy-paste owner steps, add an
  OWNER_ACTION, bump `harness_proposals_open`. Never flip a required check red.

## 2026-06-28 — OA-11: actually RAN the fetcher on real Polymarket data (egress was env-specific)

- **What/why:** owner asked me to "do OA-11" (the egress wall blocking real-data OOS validation).
  Tested reachability FROM THIS SESSION first — `gamma-api`/`clob.polymarket.com` return **HTTP
  200**. The 403 egress block is **cloud-routine-env-specific, not universal**; from a permitted
  host the public APIs are reachable with no credentials. So I did the data half for real.
- **Shipped (one PR):** `scripts/fetch_polymarket_history.py` (reusable driver); an `order` param
  on `fetch_resolved_markets` + a forwarding test; `data/polymarket_history_sample.json` (54 real
  leakage-safe records) + `data/README.md`; `docs/autonomous-loop/OA11_REAL_DATA_VALIDATION.md`
  (findings); bookkeeping (PENDING_OPS OA-11, ROADMAP A2, LOOP_HEALTH, this entry).
- **THE bug only a real run could find:** `fetch_resolved_markets` hardcoded `order=endDate`,
  which surfaces **never-traded junk** — markets closed early with a far-future endDate (saw
  `endDate=2028-01-01` on a "closed" market) and an EMPTY CLOB price history → every one skipped
  by the anti-leakage guard → **0 records**, every lead. Fix: `order=volumeNum` harvests markets
  that ACTUALLY TRADED → 54/100 yield a leakage-safe record. **Lesson: ordering resolved markets
  by endDate is a trap; order by volume to get markets with real CLOB history. Offline fixtures
  never exposed this — only a live run did. The 30/90-day price-history probes also taught that
  CLOB `/prices-history` rejects windows that are "too long" (400) and the fetcher's small
  [decision-buffer, resolution] windows are why it works.**
- **THE honest finding (the real value, not a PnL number):** on the most-liquid recently-resolved
  markets, **crowd Brier ≈ 0.09** and **~70% are already price-pinned (<0.05/>0.95) two days out**
  — and staying at leads of 5d/7d kept the SAME ~54 markets ~70% pinned (they pinned early); 14d →
  0 markets. So the crowd is *very sharp* exactly where deep CLOB history exists, and walk-forward
  makes **0 trades** because `model_prob == crowd` by construction (the fetcher seeds it to the
  crowd baseline; a real model must override it). It reproduces deterministically (seed_hash
  `8dc358439ffb5746`). **Lesson: unblocking egress was necessary but NOT sufficient. The binding
  constraint MOVED from "can't reach data" → "(a) sample markets before they pin + (b) build a
  real alpha model (track B)." Both are loop-buildable — this is convergence, not a dead-end. Did
  NOT tick the floor box; fitting model_prob on this same sample would be leakage/overfitting and
  is forbidden.**
- **Honesty guard held:** refused to manufacture an edge. The committed dataset + every doc state
  the liquidity-selection + survivorship + late-life-pinning biases explicitly.
- **How to apply:** to grow a real OOS corpus, schedule `fetch_polymarket_history.py --order
  volumeNum` on a network-permitted host (OA-11, now `in_progress`/medium). Next edge work is
  track B (a model forming an independent decision-time probability on less-pinned markets), not
  another data-access task.

## 2026-06-28 — Made "self-improving" measurable: LOOP_HEALTH metric + abandoned-change classification

- **Why:** we grade the PRODUCT every run (deep audit §10, QUALITY_SCORECARD §8) but never
  graded the LOOP itself — so there was no way to tell *convergence* (durable, correct,
  DoD-moving change) from *churn* (re-attempting dead-ends, reverts, walling on the same
  failure), and abandoned build-changes weren't classified, so a dead-end could be re-tried
  next run. Fixed both.
- **Shipped (this is observability, NOT a ship gate — `preflight.sh` does not block on it):**
  - `docs/autonomous-loop/LOOP_HEALTH.md` — **seeded**, not left for the loop to bootstrap.
    Fenced `LOOP_HEALTH:` block (dashboard-readable, parses under pyyaml), with a contract:
    update REAL counts every bookkeeping run; honest-only (same anti-gaming rule as the
    number/GO signal); classify every abandoned change; `churning`/`stuck` → open one
    `loop: harness improvement proposal`. Seeded with **real** rolling-7d from git: **42
    merged PRs, 0 reverts, 0 abandoned**; signal = `bootstrapping` (first datapoint — no prior
    LOOP_HEALTH to trend against; you can't honestly claim `improving` without a comparison).
  - `FACTORY_STANDARD.md` §10b (canonical sync, byte-identical, verbatim from the directive;
    file now 22 `##` headings, structure intact). The PRODUCT-vs-LOOP distinction + the two
    rules (classify abandoned; honest signal → harness proposal as the ONLY meta channel).
  - `ROADMAP.md` F6 (standing loop-health discipline, ongoing/never-done) + LOOP_HEALTH added
    to the dashboard-readable living-artifacts list.
- **`reason` taxonomy adapted to this stack:** added `gate_backtest_nonreproduce` (a backtest
  that won't reproduce bit-for-bit — the quant analog of `gate_tsc`) and `blocked_owner` (a
  wall handed to a human-core OA, e.g. the egress/live-key constraints the loop must not route
  around) alongside the generic `gate_test`/`review_value`/`circuit_breaker`/`dead_end`.
- **META self-check (the loop-of-the-loop), per the directive — reviewed the last ~10 runs:**
  the only candidate recurring wall is the **Polymarket egress-block (403 at the env proxy)**
  that made real-data OOS validation impossible last run. It has been hit **exactly once**
  (this 06-28 window) and was correctly routed to the owner as **OA-11** (`blocked_owner`) —
  a network/environment constraint, not a loop-rule deficiency. `gh issue list` shows **zero**
  open harness-improvement proposals. **Conclusion: no proposal is warranted yet** — the ≥2-run
  recurrence threshold is not met. **Going forward (now in §10b + F6):** if that same wall
  blocks convergence on a SECOND run without resolution, the signal flips toward `stuck` and
  that IS the trigger to open one harness-improvement-proposal (e.g. "the loop needs a
  network-permitted lane for real-data validation"). Recorded here so next run sees the count.
- **How to apply:** every bookkeeping run, refresh LOOP_HEALTH from `git`/`gh` + this run;
  classify each abandoned change so the loop doesn't repeat the failed path; read the signal
  honestly; `churning`/`stuck` → one harness proposal (the only way the loop's OWN rules
  improve, since it can't edit its routine/`.claude`). Improving the PRODUCT is autonomous;
  improving the LOOP's rules is human-gated and happens ONLY via that signal.

## 2026-06-28 — Real-data ingest + impact model + audit log (3-PR run); binding constraint is now ENVIRONMENTAL

- **Shipped 3 file-disjoint code PRs (#45 fetcher, #46 cost-impact, #47 audit-log) + this
  bookkeeping PR** from an 8-scout sweep. All merged to default; each PR's "code + safety gate
  (blocking)" CI GREEN; integration (all 3 on one branch) preflight code GREEN + runtime harness
  deterministic before the split. engine_pct 58→61. **No DoD/floor box ticked** (see below).
- **THE headline finding — the binding constraint moved from CODE to NETWORK EGRESS.** The named
  blocker for ALL OOS validation was "no fetcher for real resolved-Polymarket history." Built it
  (`polymarket_history_fetcher.py`) using Polymarket's OWN public Gamma `closed=true` + CLOB
  `prices-history` (no third-party key needed). BUT the autonomous env's egress policy returns
  **403 at the proxy** for gamma-api.polymarket.com / clob.polymarket.com — confirmed via
  `curl "$HTTPS_PROXY/__agentproxy/status"` (recentRelayFailures: connect_rejected). So the loop
  CANNOT pull real data itself; the real-data OOS run is now human-core **OA-11** (run the fetcher
  where Polymarket is reachable, or widen egress). **Lesson: when the binding constraint needs an
  external network the env blocks, BUILD the capability leakage-correctly + fixture-test it offline
  + hand the owner a precise OA, rather than faking data or ticking a box. Per the proxy README,
  a 403 egress denial is reported, never routed around.**
- **The anti-leakage core the auditors hammered:** a resolved market's `outcomePrices` settle to
  ~[1,0]/[0,1] = THE ANSWER. Using that as the decision-time price = 100% look-ahead. The fetcher
  takes `market_price` ONLY from a CLOB price-history tick at-or-before `decision_time` AND strictly
  before `resolution_time`, and RAISES rather than fabricating if none exists. A fresh Opus auditor
  confirmed CANNOT-BREAK-LEAKAGE but flagged a real honesty gap: the "unambiguously settled" filter
  excludes contested/re-resolved markets → sample biased toward clean outcomes. **Lesson: a resolved
  market's settled price is the answer — never let it become a decision input; and disclose the
  survivorship bias of a "clean-resolution-only" filter or the eval will overstate crowd calibration.**
- **CI integration bug the gate CAUGHT (not the unit tests):** the new `audit_log.PredictionAuditLog`
  (`table=True`) crashed the whole prediction-markets test suite with `InvalidRequestError: Table
  'prediction_audit_log' is already defined` — because the repo is imported under BOTH `app.*` (tests,
  via conftest sys.path) and `backend.app.*` (production/relative), and the orchestrator's EAGER
  top-level `from .audit_log import` registered the table twice. Fix: make the orchestrator import
  LAZY (in `__init__`, matching the repo's lazy `from .models import` pattern) + add
  `__table_args__ = {"extend_existing": True}` as a defensive guard. **Lesson: a new SQLModel
  `table=True` class imported EAGERLY can double-register under the repo's dual import paths and take
  down import — import table-bearing modules lazily like the existing `from .models` calls, and add
  `extend_existing=True`. The per-PR unit run passed; only the FULL-suite gate exposed it — always
  run the integrated gate, not just the per-module tests.**
- **Reviewer A caught a determinism MUST-FIX:** `_seed_hash` omitted the new `impact_coeff`, so two
  runs with different impact but identical data/seed shared a hash yet produced different PnL — a
  reproducibility-fingerprint violation. Added it to the payload + a regression test (chose a
  non-saturated depth=2000 so impact_coeff actually moves PnL; at a very thin book both coeffs
  saturate at the 1.0 cap and PnL coincides, hiding the effect). **Lesson: when you add a config
  field that affects PnL, add it to the determinism fingerprint IN THE SAME CHANGE, and test it in a
  regime where it actually bites.**
- **Process that worked:** 3 maker subagents (worktree-free, strict disjoint file ownership, no git)
  built the 3 PRs in parallel; 2 Sonnet reviewers + 3 fresh Opus auditors reviewed the integrated
  diff BEFORE splitting/pushing (so fixes landed once, not per-branch); then split base→3 branches via
  `git checkout tmp/all-work -- <files>`, pushed, opened PRs, merged after CI green. Auto-merge is OFF
  at the repo level — merge directly via the API once the blocking check is green.

## 2026-06-28 — Backtest/edge-integrity push: C3 engine + B2 calibration + A5 DQ + C5 metrics + C2 unify (5-PR run)

- **Shipped 5 file-disjoint code PRs (#39-#43) + 1 bookkeeping PR** from an 8-scout sweep.
  All merged to default; per-PR CI "code + safety gate" GREEN; integration branch (all 5
  merged) preflight code GREEN before merge. engine_pct 52→58.
- **The disjoint partition that worked:** each shared mutable file had exactly ONE owner —
  orchestrator.py→A5, execution.py→C2, and the rest were new-file-only modules. Verified
  truly disjoint before committing; all 5 auto-merged with zero conflicts.
- **CI-package gotcha (cost a relocate):** `backend/app/backtest/__init__.py` eagerly
  imports pandas/yfinance (stock residue), and pandas is NOT in `requirements-ci.txt` — so
  ANY module placed under `backend/app/backtest/` is un-importable in the CI gate. Moved the
  C3 + C5 modules into the CI-clean `prediction_markets/` package (where they belong anyway,
  depending only on cost_model). **Lesson: before adding a module to a package, check that
  package's `__init__` doesn't pull heavy deps absent from the CI surface.**
- **ADVERSARIAL AUDITORS EARNED THEIR KEEP (2 verify cycles, real bugs each time):**
  - **B2 calibration:** first cut used `passes = strategy_brier < baseline_brier` (raw point
    comparison). A fresh Opus auditor MEASURED a ~21% false-positive rate on pure noise at
    N=30 + showed a K-strategy selection attack passes near-certainly. Fixed with a
    deterministic PAIRED BOOTSTRAP CI (must exclude 0); re-audit measured FP ≤1.2%.
    **Lesson: a go-live gate that compares two point estimates with no significance test is
    p-hackable theatre — require a CI/bootstrap, and prefer "insufficient data" over noise.**
  - **C3 walk-forward:** first cut batch-settled per window → sized every candidate off the
    STALE start-of-window bankroll with no free-cash cap → an auditor forced final bankroll
    NEGATIVE (deploying cash it didn't have, inflating PnL). Rewrote to an event-driven cash
    sim (open debits cash, resolution credits payout, budget hard-capped at free cash). A
    SECOND re-audit then found the rewrite introduced a heap crash (comparing un-orderable
    BacktestTrade on equal (resolution_time, market_id)), an over-claiming seed_hash (omitted
    strategy/bankroll/costs), and intra-instant capital recycling on zero-duration markets.
    Fixed all: unique-market_id + positive-duration required (fail loud), heap tie-break
    counter, honest hash contract. **Lesson: a backtest must model that capital is TIED UP
    until resolution — batch-settling a window is a silent over-deployment / free-lunch; and
    a rewrite needs its own fresh audit (cycle 2 found 3 new bugs the cycle-1 fix introduced).**
- **Honesty held:** NO DoD/floor box ticked. These are ENGINE pieces — the walk-forward
  engine runs on SYNTHETIC data only (proves it's leakage-free + reproduces + recovers a
  known edge; does NOT prove a real edge); B2 has no real resolved markets to pass on yet.
  The binding constraint is unchanged: a VALIDATED OOS edge on REAL resolved-Polymarket data.
- **A5 staleness was nearly shipped as a no-op:** an auditor proved `check_staleness` always
  returned [] in production because `Market` carries no fetch timestamp and the orchestrator
  passed none. Fixed by adding an `end_date`-expiry check that fires with the data Market
  actually has. **Lesson: a gate that can't fire on real data is a misleading no-op — give
  it a signal the live path actually carries, or say so loudly.**

## 2026-06-28 — A1 finished + C2 cost-aware sizing + D3/D4 loss caps (multi-PR run)

- **Shipped 4 file-disjoint code PRs + 1 bookkeeping PR this run** (8-scout sweep → maximal
  disjoint set): A1-backend retirement, A1-frontend retirement, C2 cost-aware Kelly,
  D3/D4 loss caps. All merged to the default branch; gate green; integration branch
  verified (90 tests + harness deterministic) before merge.
- **A1 is DONE.** Deleted `backend/app/{models,signals,data,features,strategies}` (none
  imported by `prediction_markets/` — verified), rewrote `api/routes.py` 2379→1058 (39
  routes, 0 stock), removed crypto_ws from main.py, deleted stock frontend pages, dropped
  torch/torchvision/xgboost/lightgbm/statsmodels/pandas-datareader (~2GB+ leaner).
  **Kept** asset-agnostic infra (backtest/simulation/portfolio/execution/monitoring/llm).
  One surgical fix in a keeper: `backtest/engine.py` BaseRanker import → local Protocol.
- **Latent bug found + fixed:** `_polymarket_client`/`_prediction_scanner` were referenced
  via `global` but NEVER declared at module level → `_get_polymarket_client()` would
  NameError on first call. The Polymarket status/markets/scan routes were unrunnable. Used
  an AST check to prove only those two (not `_prediction_executor`/`_orchestrator_instance`)
  were missing. Lesson: a `global x; if x is None` with no module-level `x = None` is a
  latent NameError — grep/AST for it when touching singletons.
- **C2 (cost-aware Kelly):** sizing used GROSS edge, ignoring the 2% fee + 0.5% slippage the
  executor charges → systematic over-betting + over-trading. New `cost_model.py` (single
  source of truth) → size on net edge. Auditors confirmed the costs CANCEL correctly
  (cash deployed == budget; no double-charge) — pinned by an end-to-end test.
- **D3/D4 (loss caps) — ADVERSARIAL AUDIT CAUGHT A REAL HOLE:** the first cut enforced caps
  on the position-reduce path only. A fresh Opus auditor proved that market RESOLUTION
  losses (the PRIMARY way binary positions lose) bypassed the cap entirely, because
  `orchestrator.check_resolutions` realized PnL without feeding the executor's counter —
  and the gate reads that same counter (single point of failure). FIXED: added
  `executor.record_realized_pnl(pnl)` in check_resolutions + a regression test; a fresh
  re-audit returned ENFORCED. **Lesson: enumerate EVERY realized-loss path, not just the
  obvious one; a "known follow-up" that defeats a safety control is NOT acceptable to
  defer.** Watch-item: `PaperTradingSimulator.sell` realizes PnL independently but is a
  self-contained backtest class not wired into the live flow — would need the same hook if
  ever wired in.
- **Process that worked:** 2 Sonnet reviewers/PR + a disjoint-checker + 3 fresh Opus
  adversarial auditors on the money-path. Reviewers caught quality nits (duplicate import,
  unused imports); auditors caught the one real safety bug. Integration-branch dry-run
  before merge confirmed all four auto-merge cleanly (C2 + D4 share orchestrap.py at
  disjoint hunks — git merged them without conflict).
- **No DoD/floor box ticked** — still no validated OOS edge; this run was retirement +
  correctness + safety, not an alpha. engine_pct 45→52.

## 2026-06-28 — Gate-on-unbuilt-loop audit + DECISION COROLLARY

- **Auth is CLEAN:** single shared-password gate (login → checkPassword → cookie → app).
  **No signup, no email verification, no "check your email", no reset/2FA** — so LLM-Quant
  does NOT have the email-verification dead-end outage. (Verified the code, not assumed.)
- **Found + fixed a generalized gate-on-unbuilt-loop:** the predictions panel's
  per-strategy enable/disable toggle was a **FAKE control** — `toggleStrategy` only flipped
  local React state; the orchestrator ran every strategy regardless. A user "disabling"
  Flash Crash saw it dimmed while the bot kept trading it.
  - **Decision (explicit):** REMOVE the gate (don't fake a control whose backend loop
    isn't built). Strip is now a **read-only status display** (per-strategy positions +
    PnL); the "Strategies" stat reads "N active" not "X/7 enabled". Frontend builds.
  - Real control deferred to **ROADMAP B6** — re-add the toggle ONLY once a journey test
    proves toggling actually changes which strategies the bot runs.
  - Not logged in PENDING_OPS: it's a build decision, not a human-core owner action
    (PENDING_OPS OWNER_ACTIONS is dashboard-read owner blockers — a build decision would
    pollute it). Recorded here + in ROADMAP B6 instead.
- **DECISION COROLLARY** added to FACTORY_STANDARD §6 (canonical sync): never introduce a
  feature/gate whose dependency loop doesn't exist — wire it and prove the loop, or don't
  gate on it. A gate on an unbuilt loop is a self-inflicted outage.

## 2026-06-28 — Adopted deep-diagnosis discipline

- Added [`docs/autonomous-loop/DEEP_DIAGNOSIS.md`](autonomous-loop/DEEP_DIAGNOSIS.md):
  for any "builds/deploys but the user hits an error," **observe the real environment**
  (Railway backend logs, Vercel function logs, query Neon directly via `psql
  "$DATABASE_URL"` / Neon console, or reproduce the journey) BEFORE theorizing; separate
  **code vs data vs config** with evidence; prove ONE hypothesis against the live system;
  find the **uncaught throw**; verify the fix in the real data (not the build); fix the
  ROOT cause + add a regression that fails LOUD; **peel the layers** until the journey
  works end-to-end; stay honest.
- Two hard rules: (a) every external/LLM/3rd-party call needs a **timeout** shorter than
  the runtime budget (esp. Vercel functions; also Gemini/Polymarket on the backend);
  (b) an `.optional()` env var a critical path actually requires is a latent outage —
  make it **fail loud** (the password gate already fails closed; don't let `DATABASE_URL`
  silently no-op).
- Stack note: we're on **Neon (not Supabase)** — no Data API/MCP; query the DB directly.
- Record each real incident here (symptom → layer → proof → root cause → loud regression
  → end-to-end confirmation). The dashboard-0% fix (2026-06-27) is a worked example.

## 2026-06-28 — Side-effect integrity (a "success" the user can't verify is a LIE)

- Canonical sync: FACTORY_STANDARD §6 now ends with the **SIDE-EFFECT INTEGRITY**
  paragraph (byte-identical) — no fake success; verify the EFFECT end-to-end, not the
  message. Read it every run.
- ROADMAP: added the two rules to the BUILDS≠WORKS standard + **F4.1 side-effect
  round-trip** (generalized to this trading bot: the effect = a paper order really
  logged/filled; the runtime harness already proves that + that the live gate/kill
  switch block real orders; the UI-never-shows-fake-success round-trip rides on F5).
- **P0 FIXED** (real fake-success bugs in the predictions panel):
  - `resetPortfolio` swallowed errors and unconditionally cleared the UI + showed
    "Portfolio reset" even if the backend reset failed/was down → now only clears +
    claims success when the reset API actually returns ok; error toast otherwise.
  - `toggleBot` stop had no `res.ok` check → showed "Bot stopped" even if stop failed
    (bot could still be running) → now contingent on ok; error toast otherwise; the
    silent catch now surfaces an error.
  - (start branch + runScan were already contingent; legacy bot/dashboard re-fetch real
    state so they self-correct.) Frontend builds.
- Going forward: any new "sent/saved/submitted/charged/executed/done" message MUST be
  downstream of the real op succeeding; auditors + the deep-audit functional-reality
  lens hunt for fake success.

## 2026-06-27 — Canonical sync: FACTORY_STANDARD §6b (design taste)

- Synced FACTORY_STANDARD.md to the new canonical (still **byte-identical** across
  factories): added **§6b "Design taste — ELIMINATE generic-AI frontend"** between §6
  and §7. THE DESIGNER QUESTION ("Would an experienced product designer intentionally
  make this decision?") runs on EVERY UI change; generated-AI slop is a release-blocking
  FAIL; enforced by Reviewer B + the §10 deep-audit design lens + the §7 readiness
  visual review (judging the §6 screenshots).
- **Applies to LLM-Quant** — it HAS a user-facing surface: the monitoring/control
  panel (dashboard, predictions, bot, login). Every UI change to that panel must clear
  §6b; folds together with F5 (Playwright screenshot capture) so the visual lenses have
  artifacts to judge. NOT N/A here.
- Canonical sync only (the single way FACTORY_STANDARD.md changes) — treat as a
  read-only stable anchor again afterward.

## 2026-06-28 — A1 Increment 1: deleted the stock/crypto trading engine

- Advanced the LOWEST incomplete item (A1). Removed the entire `backend/app/trading/`
  module (master-bot, quant-bot, options-bot, leap-options + stat-arb engines, live
  equity/crypto brokers + auto-connect, ML training/backtester) plus its whole API
  surface and test suite.
- **Coupling map (verified before cutting):** `prediction_markets/` imports NOTHING
  from `trading/` — fully decoupled. The ONLY external importers of `trading/` were
  `api/routes.py`, `api/main.py`, and 4 root scripts — and **every** `..trading` import
  was function-local (lazy), so deleting the module never broke app import-time, only
  the handlers that called it (which were removed together).
- **Mechanics that worked:** computed the removable route set authoritatively by
  "handler body contains `..trading`" (91 of 164 router handlers), deleted by union of
  line ranges + absorbed the banner comments. routes.py 4614→2444 lines; router
  164→73 routes (survivors = prediction-markets + read-only data/AI/learn). Verified:
  zero `app.trading` refs repo-wide, `from backend.app.api.main import app` imports,
  `preflight.sh code` GREEN, runtime harness deterministic.
- **Dep reality (important):** torch/xgboost/lightgbm/tensorflow/sklearn/cvxpy are
  used by `models/`, `portfolio/`, `signals/` too — NOT trading-only — so the big ML
  deps can't drop until those stock modules are retired (later A1 increments). Only the
  crypto-exchange libs (`binance`/`python-binance`/`ccxt`) + `ta-lib` were trading-only
  and were dropped this run. `statsmodels`/`torchvision` weren't in root requirements.
- **Env note:** ruff IS installed in this container now (loop-memory previously said it
  wasn't), so `preflight.sh` step 3 fails LOCALLY on 572 pre-existing lint errors. CI
  does NOT install ruff (`backend/requirements-ci.txt` has no ruff) → the gate degrades
  gracefully and is GREEN in CI. Don't be alarmed by the local ruff FAIL; verify the
  gate with ruff hidden to reproduce CI. (Cleaning the lint debt is a future quality item.)
- **Scope honesty:** A1 is `[~]`, not done. Read-only stock/crypto data + AI routes,
  the stock quant-research routes, the stock frontend, and the stock ML stack remain —
  each a separate coherent increment. No DoD box ticked (floor still not met).

## 2026-06-27 — GO signal + PnL metrics exposed to the dashboard

- GROWTH_STATUS now exposes weekly PnL + profit metrics (weekly_pnl_paper/live,
  weekly_pnl_target_usd=2000, weeks_validated_above_floor, hit_rate, brier, sharpe,
  max_drawdown_pct, total_trades) — the dashboard trends weekly_pnl over its snapshots.
- New **`go_live`** block = the rigorous real-money GO signal (status not_ready|eligible,
  confidence none|building|high, 10 criteria, blocking[], owner_decision_required).
  It is **DERIVED, never hand-set**: `preflight.sh` **step 9c** FAILS (in BOTH scopes)
  if status=eligible while any criterion is false / floor_met not true / any DoD box
  unchecked. So a fake/random GO can't ship — proven (set eligible w/ false criteria →
  gate fails). Turns green only on a SUSTAINED validated track record; even then the
  owner makes the final call (HUMAN-CORE).
- Dashboard side (separate repo) must add parsing + UI for `go_live` + the weekly-PnL
  trend — see the message handed to the owner for the dashboard agent.

## 2026-06-27 — Canonical sync: FACTORY_STANDARD gains visual verification

- Synced `FACTORY_STANDARD.md` to the new canonical (still **byte-identical** across
  every factory repo): added **visual verification** so a page can't pass while
  rendering blank/broken/unstyled/"vibe-coded".
  - §6: the journey suite **captures a screenshot** of every page + key state
    (empty/loading/error, authed + logged-out) and commits them; a screenshot only
    counts if something JUDGES it.
  - §7 (Gate 2) + §10 (deep-audit lens): the readiness gate and the design/taste
    lens **VISUALLY REVIEW** those screenshots on a vision-capable model against the
    VISION design bar — a blank/broken/overlapping/unstyled/off-brand page is a
    release-blocking FAIL / design BUG, even if DOM assertions pass. Bounded: judge in
    the deep audit + at the readiness gate, not on every micro-change.
- This was a **canonical sync** (the only way FACTORY_STANDARD.md may change), not loop
  work. Treat the file as a read-only stable anchor again.
- LLM-Quant implication: the monitoring panel (dashboard / predictions / bot / login)
  needs screenshot capture in its journey suite + visual review at the gate. The
  product side does NOT capture those screenshots yet, so the new §6/§7/§10 visual
  lenses have nothing to judge until built. Now a **concrete ROADMAP item: F5** —
  a **Playwright** journey suite screenshotting every page × key state
  (empty/loading/error, authed + logged-out), committed as artifacts, with the visual
  lenses wired to LOOK at them. **Web-only** (Next.js panel — no mobile/component
  snapshots). Kept separate from the byte-identical `FACTORY_STANDARD.md`.

## 2026-06-27 — Adopted the shared FACTORY_STANDARD

- Added `FACTORY_STANDARD.md` at the repo root — the **byte-identical, product-agnostic**
  cross-factory discipline (the loop, two-gate readiness, BUILDS≠WORKS, independent
  QUALITY_SCORECARD, business-case strength loop-back, growth-data-as-signal, the
  3-tier model split, the value bar, the disjoint rule, the brakes). **Read it every
  run** alongside ROADMAP + VISION.
- **It is a STABLE ANCHOR — treat it as read-only context.** NEVER edit, paraphrase,
  trim, or adapt it to this product; product-specifics live in ROADMAP/VISION which
  win on any specific. It changes ONLY by a deliberate canonical cross-factory sync,
  never as loop work. Listed in ROADMAP's "STABLE ANCHORS (do not churn)".
- Added the pointer near the top of ROADMAP.md and the stable-anchors entry.
- Where the standard and this repo already align: the two-gate readiness +
  preflight, the QUALITY_SCORECARD consume-don't-grade wiring (step 9b/12), the
  Opus/Sonnet/Haiku split, the disjoint rule, and the real-money/human-core brakes
  are all already in place. The standard formalizes them as the shared contract.

## 2026-06-27 — Wired the independent Quality Auditor grade into the gates

- A **separate, independent Quality Auditor** routine grades the project A+→F and
  **owns** `docs/quality/QUALITY_RUBRIC.md` + `docs/quality/QUALITY_SCORECARD.md`. The
  factory **must NOT author, overwrite, or self-assign** a grade (maker ≠ checker). We
  **consume** the scorecard as DATA, never as instructions, and act on `top_gaps`.
- Wiring shipped: `scripts/check_scorecard.py` (read-only consumer/guard; never writes
  the scorecard) + `backend/tests/test_scorecard.py` (9 tests). `preflight.sh` step 9b
  = parse guard (malformed/invalid grade can't ship; **absent = bootstrap = OK** in
  code scope), step 12 = readiness gate (ship-critical A/A+, others ≥ B; absent or
  below-bar ⇒ not go-live). ROADMAP DoD + a new "QUALITY RUBRIC (A+→F)" standing
  standard + the scorecard contract added.
- **Readiness bar:** ship-critical dims (functional reality, research & backtest
  integrity, correctness/determinism, security, run & risk-readiness, artifact
  integrity, business-case strength) must be **A/A+**, others **≥ B**. **No alpha
  ships** while backtest integrity OR business-case strength < A.
- Scorecard schema the gate reads (auditor produces it): `<!-- QUALITY_SCORECARD ... -->`
  with `dimensions:[{name,grade,ship_critical,top_gaps}]`, grades ∈ {A+,A,B,C,D,F,null}.
- When acting on a low grade: convert the named `top_gaps` into **specific,
  value-bar-clearing** fixes, drive ship-critical dims to A/A+, then **converge** — no
  gold-plating, no looping forever.

## 2026-06-27 — Deployment architecture decision (do NOT chase serverless)

- **The backend is intentionally a PERSISTENT, always-on service — never serverless
  (Vercel/Netlify functions).** It has a continuous scan loop (asyncio background
  task), persistent WebSocket feeds, and in-memory positions/risk/activity state.
  Serverless breaks all three. **Do not** spend runs porting the backend to
  serverless — it's a large refactor that makes the bot worse. If "one platform" is
  ever wanted, run BOTH frontend + backend on Railway/Render (not Vercel functions).
- Deploy shape: **frontend → Vercel** (Next.js, `frontend/`), **backend → Railway /
  Render / Fly** (persistent), **DB → Neon Postgres** (`DATABASE_URL`). See
  `docs/DEPLOYMENT.md` (the single source for deploy steps).
- **DB = Neon** (switched from Supabase). The dialect-aware engine needs NO code
  change — Neon is just Postgres; the pooled `-pooler` endpoint + `pool_pre_ping`
  handle autosuspend/reconnect, and `?sslmode=require` rides in the URL. Use the
  **pooled** connection string.
- One-click configs shipped: `render.yaml` (root), `backend/railway.json`; the
  `backend/Dockerfile` binds `${PORT:-8000}` for any host. Backend needs ~1GB+ RAM
  (heavy ML deps: torch/xgboost/lightgbm) → free tiers OOM. Trimming those for a
  prediction-markets-only build (ROADMAP A1) would let it run leaner.
- CORS: all frontend calls are cross-origin direct calls; set `CORS_ALLOW_ORIGINS`
  (env) to the Vercel origin or the backend rejects them.
- **No Data API lockdown on Neon.** Neon has no PostgREST/anon Data API (unlike
  Supabase), so the public-table exposure risk doesn't exist — the DB is reachable
  only via `DATABASE_URL`. Just keep that string server-side (OA-9).

## 2026-06-27 — Bootstrap

- **What this repo is:** a *personal* prediction-markets profit bot, not a product.
  Re-mapped from the cross-project "factory" process. Source of truth = `ROADMAP.md`
  + the profit case in `docs/BUSINESS_CASE.md`.
- **Default branch:** `claude/llm-stock-trading-app-fXupf` (origin/HEAD). PR against it.
- **Honest baseline:** the prediction-markets engine runs in paper/dry-run, but there
  is **no validated out-of-sample edge yet** — `floor_met: false`, metrics `0/null`.
  Do **not** tick DoD boxes without reproduced, cost-realistic OOS proof.
- **Already present (don't rebuild):** Polymarket client + websocket feeds, strategies
  + Kelly sizing + orchestrator, paper simulator, risk manager with category caps,
  **kill switch** in `execution.py`, backtest/validation infra under
  `backend/app/backtest/`.
- **Added this run:** `LIVE_TRADING_ENABLED` master gate (default false) wired so no
  real order is possible unless the owner flips it AND `dry_run` is off; the full
  apparatus (VISION/ROADMAP/preflight/runbook/YAML blocks/research docs).
- **Lowest incomplete ROADMAP item to advance next:** A1 (retire stock/crypto data
  paths, keep asset-agnostic infra) — **do this carefully**; the prediction-markets
  module is the keeper, the stock/crypto code lives under `backend/app/trading/`,
  `backend/app/strategies/`, `backend/app/data/` (crypto/alpaca/binance). Don't break
  the asset-agnostic backtest/metrics/risk infra.
- **Gate tooling reality:** `pytest` available; **no ruff/mypy installed** — preflight
  degrades gracefully (skips with a warning, still runs pytest + import smoke).
- **Real-money brake:** never trade real money, never fund, never flip
  `LIVE_TRADING_ENABLED`, never raise a cap. Those are HUMAN-CORE
  (`PENDING_OPS.md` / `LIVE_RUNBOOK.md`).
- **Doc sprawl:** 28 root `.md` files consolidated — legacy audit/plan files moved to
  `docs/legacy/` (history preserved); the coherent source of truth is
  VISION/ROADMAP/BUSINESS_CASE/GROWTH_STATUS/PENDING_OPS + `docs/growth/`.

## 2026-06-29 — 5-PR run: metrics e2e + live-gate depth + real-data canary + audit harness + LLM caps

- **Shipped 5 file-disjoint code PRs (#56 C5 metrics, #57 venue-layer live gate, #58 real-data
  canary, #59 strategy-audit harness, #60 LLM timeout+spend-cap) + this bookkeeping PR** from an
  8-scout (Haiku) sweep across tracks A–G. All auto-merged after the blocking gate went green;
  integration verified before split (176 PM tests + runtime harness deterministic). engine_pct 61→64.
  **No DoD/floor box ticked** — none of these is a validated edge (the canary honestly shows 0 trades).
- **THE adversarial gate earned its keep — an Opus honesty auditor BROKE a claim that all my own
  checks missed.** PR-4's audit harness reported "0 signals fired on the real 54-record sample" and
  the tests/docstrings asserted ~0 — but the auditor ran it and found **98 phantom signals**. Root
  cause: the harness's own `load_real_markets_from_history` injected IDENTICAL boilerplate question
  text ("Market {id} (real sample)") into all 54 records; `CrossMarketArbitrageStrategy`'s keyword
  screen fires on "3+ shared non-trivial words", so it spuriously paired unrelated markets. The test
  deliberately did NOT assert the count, so the false prose was never checked. **Lesson: a forensic
  finding stated in prose but not ENFORCED by an assertion is a lie waiting to happen — pin the claim
  with a test (here: `total_signals_fired == 0`), and never feed a strategy synthetic filler text that
  shares words; use unique opaque placeholders. The fix also revealed a real strategy weakness (the
  keyword screen pairs on filler words) — logged to RESEARCH_MEMORY for a future B-track fix; I did
  NOT change the strategy in the audit PR (behavior change needs its own deliberate work).**
- **Sonnet reviewers caught real precision bugs in the metrics aggregator:** (1) `len(list(trades))`
  computed AFTER `summarize(trades)` already consumed the sequence → silently reports 0 for any
  one-shot iterator (materialize once at function entry); (2) `_is_degenerate` used `==` float equality
  → use `math.isclose` (a price round-trip can differ by epsilon). **Lesson: materialize a Sequence
  param before iterating it twice; never `==` floats on a degenerate-detection path.** All review/audit
  findings were fixed in ONE consolidated cycle (within the ≤2-verify/≤2-review brake), then merged.
- **Live-path safety done right (Opus auditor: SAFE — CANNOT-BREAK):** the LIVE_TRADING_ENABLED gate
  was only at the `PredictionMarketExecutor.execute()` interface; added a fail-closed check INSIDE
  `PolymarketExecutor.place_order()` (both venue paths) so a direct venue-level call can't bypass it,
  and it fails CLOSED if settings raise. Hardened response parsing so no FILLED is reported without a
  real matched execution. Paper is provably unaffected (dry_run routes through `_simulate_fill` and
  never reaches `place_order`). **Lesson: enforce a safety gate at the LOWEST level, not just the
  interface; and a "fill" must be downstream of a real match, never assumed from a non-error response.**
- **GATE STRENGTHENED deliberately:** added the new live-gate/metrics/canary/audit test files to
  `scripts/preflight.sh`'s blocking test list (99→176 enforced tests) so these safety/honesty checks
  are REQUIRED on every future change. (preflight.sh is a stable anchor — changed with deliberate
  intent, verified green before requiring; left `test_llm_safety` out as it has a real-time timeout
  test and the LLM is off the trading path.)
- **Process / git lesson:** the default branch advanced (#54/#55) WHILE I worked (I was based on the
  older tip). The new commits were file-disjoint from my changes, so I `git stash -u` → checkout the
  new origin tip → `stash pop` to rebase cleanly, then re-ran the gate against the NEW base (config.py
  + a boot-guard had changed upstream) before splitting/pushing. **Lesson: always re-fetch + re-verify
  against the CURRENT default tip before opening PRs — the branch moves under you in an active repo.**
- **Binding constraint unchanged + loop-buildable:** a real decision-time alpha producing
  `model_prob != crowd` on less-pinned markets. The measurement apparatus is now complete (metrics
  e2e, calibration honesty, reproduction canary, audit harness) — the next run builds the alpha, not
  more infra. Egress (OA-11) remains owner-scope for refreshing the real corpus.

## 2026-06-29 — 4-PR models/strategy run: B5 screen + B2 anti-p-hacking + B3/E6 engines + A5 staleness

- **Shipped 4 file-disjoint code PRs (#63 B5 keyword-screen hardening, #64 B3/E6 lifecycle+attribution
  engines, #65 B2 Bonferroni correction, #66 A5 fetched_at staleness) + this bookkeeping PR** from an
  8-scout Haiku sweep across tracks A–G. All auto-merged after the blocking gate went green; integration
  verified before split (374 PM tests + runtime harness deterministic). engine_pct 64→66. **No DoD/floor
  box ticked** — these are engine/quality/integrity/learning-loop pieces, not a validated edge.
- **Scout sweep → DROPPED a fake fix (anti-padding worked):** an 8th scout flagged a cost_model
  "extreme-price floor" bug. On inspection the 1e-6 floor RAISES cost (conservative/safe direction) →
  reduces sizing, not oversizes — NOT a real bug. Dropped PR-C. **Lesson: scout findings are leads, not
  orders — verify the direction of an alleged safety bug before building a fix; a floor that over-states
  cost is the safe side.**
- **THE adversarial lesson — a free-text relatedness heuristic is inherently leaky; entity-gating was
  whack-a-mole.** B5's first hardening cut (≥3 shared content tokens AND ≥1 shared capitalized "entity")
  was BROKEN by a fresh Opus re-auditor BOTH ways: still paired same-template pairs sharing a venue/
  nationality/role word (Apple/Tesla "on the Nasdaq"; "Chinese mfg" vs "Chinese spending"), AND wrongly
  REJECTED real pairs whose only entity was a <4-char acronym dropped by the length floor (NBA, Fed —
  contradicting my own docstring that listed NBA as an example). The robust fix was SIMPLER: drop entity
  detection, rely on a COMPREHENSIVE stopword set (template words = filler) so same-template/different-
  subject pairs share zero content tokens. **Lesson: when an auditor keeps finding edge cases in a
  heuristic, the answer is usually a simpler, broader, honestly-disclosed-as-imperfect rule — not more
  clever detection. Document it as a conservative SECONDARY screen; accept conservative false negatives
  (safe) over fabricated signals (a real losing trade).**
- **Two-fix-cycle discipline (stayed within the ≤2 brake):** cycle 1 (2 Sonnet + 3 Opus auditors) found
  the false-positive class → fixed with entity-gating + reconciliation + tz-normalize. cycle 2 (1 fresh
  Opus re-auditor) found entity-gating incomplete → simplified to stopwords-only. Then merged WITHOUT a
  3rd audit (mechanically verified all named cases + full gate). **Lesson: a rewrite needs its own fresh
  audit (cycle-2 caught the cycle-1 fix's new holes), but the brake means apply cycle-2's findings and
  ship on mechanical verification — don't spiral into a 3rd audit on a strictly-more-conservative change.**
- **Reviewers/auditors earned their keep (real bugs each):** Sonnet A + Auditor 3 both caught
  strategy_registry.from_dict NOT normalizing naive timestamps → to_dict would reinterpret them in the
  host's LOCAL tz, breaking byte-stable round trips on a non-UTC host (fixed with _require_aware). Sonnet B
  caught per_strategy_metrics' frozen-dataclass-with-mutable-dict (weekly_pnl mutable despite frozen=True →
  MappingProxyType) and a weekly/total reconciliation gap (total now derived from the weekly series →
  reconciles exactly). **Lesson: "frozen=True" does NOT freeze a contained dict; use MappingProxyType.
  And derive a total from its parts so the two views can't drift.**
- **Determinism guard held:** A5's Market.fetched_at is stamped with now() but only on the LIVE Market
  dataclass; the backtest uses a separate HistoricalMarket and _seed_hash enumerates fields explicitly,
  so fetched_at never enters any reproducible fingerprint (Opus-auditor-confirmed + 22 walk-forward tests).
  **Lesson: when adding a now()-stamped field, prove it's excluded from every seed_hash/reproducible path
  before shipping — here the separate backtest type made it safe.**
- **GATE STRENGTHENED (deliberate, verify-green-first):** added test_calibration/data_quality/market_text/
  strategy_registry/per_strategy_metrics to preflight.sh's blocking list (176→~290 enforced tests). All
  green before requiring (the verify-green-before-requiring rule).
- **Process:** built all 4 on one integration branch, verified the integrated gate + harness, then split
  via `git checkout <base> -- <files>` into 4 disjoint branches off the new default tip, pushed, opened
  PRs, all 4 required-check-green in ~25s, merged squash. The new test files were added to the gate in the
  ONE bookkeeping PR (preflight.sh is a shared anchor — one owner).
- **Binding constraint unchanged + loop-buildable:** a real decision-time alpha (model_prob != crowd on
  less-pinned markets). The governance apparatus is now stronger (hardened screen, p-hack-resistant
  calibration gate, lifecycle registry, per-strategy attribution); next run WIRES the engines into the
  orchestrator + starts the alpha. Egress (OA-11) remains owner-scope for refreshing the real corpus.

## 2026-06-29 — 3-PR run: first model_prob!=crowd alpha (B4a) + E5/E2 wired + metrics dashboard

- **Shipped 3 file-disjoint code PRs + 1 bookkeeping** from an 8-Haiku-scout sweep across A–G:
  PR-1 (B4a `calibration_bucket_strategy.py` — the FIRST model_prob != crowd alpha mechanism,
  new files only), PR-2 (E5/E2 wiring — orchestrator + routes + metrics_aggregator + tests),
  PR-3 (frontend metrics dashboard — `frontend/components/metrics/*`, frontend-only). Integrated
  gate green before split (288→444 PM tests + runtime harness deterministic + harness safe).
  engine_pct 68→70. **No DoD/floor box ticked** — B4a is the MECHANISM for an edge, not a
  validated edge (needs the 7-day OOS corpus, OA-11).
- **Disjoint partition that worked:** PR-1 = new files only (no shared-file touch — I deliberately
  did NOT wire CalibrationBucketStrategy into the default scanner, because unfitted it is a no-op
  and wiring it without real fitted rates would be a gate-on-unbuilt-loop). PR-2 OWNED the shared
  files (orchestrator.py + routes.py + metrics_aggregator.py). PR-3 = frontend only. **Lesson: when
  a new alpha needs no live data yet, ship it as a standalone tested module + leave it UNWIRED — it
  stays fully file-disjoint from the orchestrator-owning PR, and an honest abstaining strategy is
  not a fake control.**
- **Disjoint discipline DROPPED 4 genuinely-buildable items (not scarcity — shared-file conflict):**
  scouts surfaced B6 (per-strategy enable/disable), per-leg arb execution (B1 follow-up), and A4
  resolution-tracking — ALL three want orchestrator.py, which PR-2 already owned. Kalshi A3 was
  dropped on VALUE (a 2nd venue with the same pinning problem + zero alpha is premature; the binding
  constraint is alpha, not venue count — the scout's reasoning held). Lint-ratchet F7 was dropped on
  VALUE (removing unused imports from money-path files for ZERO CI benefit — ruff isn't in CI — is
  cosmetic prep, and Phase-1 collided with PR-2's metrics_aggregator.py). **Lesson: only ONE PR can
  own a heavily-shared file (orchestrator/routes) per run; pick the highest-value owner (here the
  named E5/E2 next-action) and defer the rest to a later run — that's the disjoint rule, not
  artificial scarcity. And anti-padding cuts both ways: a deep-audit scout found NO real defect, so
  no defect-PR was invented.**
- **The adversarial gate earned its keep again (2 Sonnet + 3 Opus, ONE consolidated fix cycle):**
  - **Both Sonnet reviewers independently caught a shared mutable model in the StrategyFn closure**
    (one CalibrationBucketModel re-fit per call): harmless under walk_forward's serial use but a
    latent re-use bug, and an empty training set would RAISE and crash the backtest. Fixed with a
    FRESH model per call + an empty-training abstain guard + `test_strategy_fn_refits_on_each_call`.
    **Lesson: a closure holding a mutable model is not "pure" — build it inside the call; make "no
    data" abstain, never raise on a hot path; prove re-use with a test.**
  - **Opus auditor 1 named the idealized-test trap:** the "0 trades on a well-calibrated crowd" test
    hits exactly 0 only because the synthetic empirical rate lands on the penny; a real finite-sample
    crowd jitters off and WOULD noise-trade (losing to costs — the auditor measured negative mean PnL
    over 20 seeds). Fixed by annotating the idealization + adding
    `test_cost_band_suppresses_subthreshold_miscalibration` (the real load-bearing mechanism).
    **Lesson: a clean synthetic test can be honest about the MECHANISM while over-cleanly implying
    real-world behaviour — name the idealization and test the load-bearing assumption directly.**
  - **All 3 Opus auditors returned CANNOT-BREAK** on leakage (structural via walk_forward's frozen
    pre-window training + outcome-free MarketView), fabricated-edge/p-hacking (min_bucket_n floor +
    cost band), E5/E2 honesty (insufficient_data fires before build_baseline; zero-trade windows
    never fabricated; chronological split can't invert), live-safety (read-only; execution.py
    untouched; the kill switch/caps/live gate all still pass the harness), determinism, and
    import/registration (no new table=True; no cycle though cbs imports both strategies.py and
    walk_forward.py). Shipped on mechanical verification after the one fix cycle (≤2-cycle brake;
    strictly-more-correct/honesty-only changes, no 3rd audit).
- **PR-2 honesty pattern — mirror the existing reviewed path, don't diverge:** `get_resolved_predictions`
  reconstructs ResolvedPrediction (predicted_prob = market_price + edge_at_entry, skip edge==0)
  EXACTLY like the already-shipped calibration endpoint. A reviewer flagged the reconstruction's
  semantic dependence on what edge_at_entry stores — but since the current reality is 0 non-degenerate
  predictions (it never runs on real data yet) and the calibration endpoint uses the identical
  reconstruction, the right call was to KEEP it consistent + add a "keep in sync" comment, not invent
  a divergent reconstruction. **Lesson: when wiring a second consumer of the same DB-to-model mapping,
  mirror the existing reviewed path byte-for-byte and add a sync comment — divergence is the silent
  honesty bug, not the duplication.**
- **Env note:** the autonomous container lacks `pydantic_settings`/`fastapi` until
  `pip install -r backend/requirements-ci.txt`; preflight's import-smoke fails until then. routes.py
  imports fastapi, so the gate never imports routes.py — the new endpoints are verified by
  source-level route-registration uniqueness + exercising their pure `compute_*` wrappers (same as
  the existing metrics endpoints). **Lesson: install requirements-ci.txt first to reproduce CI; the
  blocking gate tests pure logic, not the ASGI app boot.**
