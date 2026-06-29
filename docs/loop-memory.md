# LOOP MEMORY — LLM-Quant

Cross-run lessons for the autonomous factory loop. Append; read before each run.

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
