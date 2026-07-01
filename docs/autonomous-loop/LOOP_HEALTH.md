# LOOP HEALTH — is the LOOP getting better, or just busier?

> The deep audit (FACTORY_STANDARD §10) grades the **product**; the QUALITY_SCORECARD
> grades the **product**. This file grades the **loop itself** — whether the autonomous
> factory is *converging* (shipping durable, correct changes that move the DoD) or merely
> *churning* (re-attempting dead-ends, racking up reverts, walling on the same failure).

## Contract (read before editing)

- **Update EVERY run, in the bookkeeping PR, with REAL counts** — derived from `git`/`gh`
  and from what actually happened *this run*. Never hand-wave or round up.
- **Honest only.** Same anti-gaming rule as the governing number and the GO signal: a
  fabricated "improving" signal is a lie. If the loop churned, say `churning`. If it
  stalled, say `stuck`. The point of the metric is to catch that, not to look good.
- **Dashboard-readable.** The fenced `LOOP_HEALTH:` block below is parsed the same way as
  `BUSINESS_CASE_SUMMARY` / `GROWTH_STATUS` / `OWNER_ACTIONS` (fenced ```yaml, top-level
  key). Keep it well-formed.
- **Observability, NOT a ship gate.** `preflight.sh` does not block on this — it is a
  mirror the loop holds up to itself. (Contrast: the GO signal and the loss caps ARE gates.)
- **Classify every abandoned change** (`abandoned_reasons`) so the loop does not re-attempt
  the same dead-end — the build-loop's "don't repeat the failed path."
- **A `churning` or `stuck` signal is the trigger to open ONE
  `loop: harness improvement proposal` issue** — the ONLY channel by which the loop's own
  rules improve (it cannot edit its routine / `.claude`). A recurring wall that never raises
  a proposal is itself a dead signal. See FACTORY_STANDARD §10b.

`reason` ∈ `gate_tsc` · `gate_test` · `gate_determinism` · `gate_build` ·
`gate_backtest_nonreproduce` (this stack: a backtest that won't reproduce bit-for-bit) ·
`review_value` · `review_correctness` · `circuit_breaker` · `conflict` · `dead_end` ·
`blocked_owner` (handed to a human-core owner action — e.g. an egress/network or live-key
wall the loop must not route around).

`signal` ∈ `bootstrapping` (no prior data point to trend against) · `improving` (shipping
up, abandon/revert down vs. last run) · `steady` (converging at a stable rate) · `churning`
(high abandon/revert vs. shipped) · `stuck` (recurring failures / no convergence — open a
harness proposal).

```yaml
LOOP_HEALTH:
  project: LLM-Quant
  as_of: 2026-07-01
  last_run: 2026-07-01          # prior run (3rd of 2026-07-01): factory run 21 — whale/weather integrity gate-off (#116) + A1 db.models dead-code (#117)
  last_deep_audit: 2026-07-01   # 8-Haiku skeptical scout sweep (A1-residue · correctness/test-isolation · security-default-closed · frontend-honesty · risk/exec-safety · data/backtest-integrity · ruff/F7 · self-validation-honesty) ran THIS factory run
  enforced_in_ci: true          # required check (enforce_admins=true, strict=false) + repo auto_merge; loop merges direct-on-green after reviews, WAITS for CI, never --admin
  validation:                   # self-validation capability readiness — refresh every run from `check_self_validation.py --readiness`
    enforced_in_ci: true        # the coverage gate is a blocking preflight step (9d) inside the required check
    capabilities_total: 10      # unchanged this run: #126 KEPT analyst.py (the declared llm_analysis capability) so the count/credential inventory are untouched; #129's backend_auth_disabled is a bool flag, not a credential/capability
    unmet: []                   # active + ci_validatable:false capabilities (need an owner secret). NON-EMPTY => urgent OWNER_ACTION + blocks. Must match SELF_VALIDATION.readiness.unmet AND have a PENDING_OPS validation-capability-<id>.
  this_run:
    changes_shipped: 4          # 4 file-disjoint code PRs (#126 A1 /learn+paper_simulator dead-code removal; #127 D2 drawdown auto-disable counter revived; #128 frontend "—" pre-load honesty; #129 security default-CLOSED control auth) + this bookkeeping
    changes_abandoned: 1
    abandoned_reasons: ["correctness/SQLModel dual-import (QUALITY_SCORECARD A→A+ top_gap): scout proposed adding __table_args__={'extend_existing':True} to the 7 models.py table classes, but VERIFIED against real code that fix is INSUFFICIENT — it resolves the Table-level dup but the real root cause is the DUAL IMPORT PATH (app.* via conftest's sys.path vs backend.app.* in prod, mixed across 21 vs 27 test files) causing an ambiguous Relationship class-registry ('Multiple classes found for path PredictionPosition'). The real fix is a test-import-path standardization (a ~21-file refactor), too broad to do cleanly alongside 4 other PRs + it's OPTIONAL A→A+ polish OUTSIDE the CI-blocking gate (the 5 failures only surface in a specific full-suite ordering). reason=dead_end (the simple fix) + deferred as scope; do it as a focused next-run PR. Also NOTHING-shipped from: the WeatherArbitrageStrategy edge-formula bug (real math error but the strategy is GATED-OFF/unvalidated B7 — polishing gated code fails the value bar; re-derive it in the B3/OOS re-validation) and the NaN-settlement guard (IMPOSSIBLE-STATE: polymarket_client.py:712 already coerces non-finite outcome prices to a finite 0.0 sentinel at parse time, so a NaN can't reach settlement — a guard on an unreachable state = padding). ruff correctness-gate (F7) deferred: its E9/F821/F811 gate needs paper_simulator.py's F811 gone (now removed by #126) + 3 orchestrator/strategies F811 fixes — a clean next-run follow-up once #126 landed."]
    verify_cycle_failures: 0
    review_rejections: 2         # #127 (risk): BOTH Sonnet reviewers REQUEST_CHANGES on the SAME real regression — the diff removed the record_execution strategy-increment but left test_prediction_markets.py::test_record_execution_with_strategy asserting the OLD behaviour (`assert 0==1`), and that file IS in the curated CI gate → the PR's own gate would go RED. Fixed in 1 cycle (rewrote it to test_record_execution_does_not_track_strategy_trades). #129 (security): Reviewer B REQUEST_CHANGES — stale auth_core.py docstring/CRITICAL-log ("open" when now default-closed) + test_backend_auth.py comments + a MISSING test_config_safety case for the new live+opt-out boot refusal. Fixed in 1 cycle (doc scoping + test_live_with_auth_disabled_refuses_to_boot). Both within the ≤2-cycle brake. #126 (A1): A APPROVE + B APPROVE. #128 (design): A APPROVE + B APPROVE. Opus safety auditors: #127 SOUND, #129 SAFE.
    process_incidents: 1         # a reviewer/auditor subagent left a git worktree lock on the fix-strategy-drawdown branch; removed via `git worktree remove --force` before applying the review fix. Not a code/gate incident.
    circuit_breaker_trips: 0
  rolling_7d:
    merged_prs: 77             # +5 this run (#126 #127 #128 #129 + bookkeeping); loop-cadence count — the true 7d repo total is higher (the separate Quality Auditor / FACTORY_STANDARD-sync routines merged #118–#124 in the same window)
    reverts: 0
    readiness_attempts: 0
    readiness_rejected: 0
    recurring_failures: []       # OA-11 (Polymarket) + OA-15 (Kalshi) corpus + OA-16 (HuggingFace bypass) all owner/egress-scope. ALL egress 000 in-env AGAIN this run (gamma / huggingface / kalshi curl -> 000) — confirmed owner-scope, not a loop wall. NOT trending `stuck`: convergence is owner-blocked, not rule-blocked.
    harness_proposals_open: 0
  signal: improving              # 22nd datapoint: factory run, 4th of 2026-07-01 — the biggest run of the day: 4 file-disjoint value-bar-clearing code PRs from an 8-Haiku scout sweep, all reviewed (2 Sonnet each + Opus safety audits on the 2 safety-touching PRs). (#126) A1 — the LOWEST incomplete ROADMAP item: deleted the dead /learn teaching surface (explainer/tutor/memo, OpenAI-from-nonexistent-key) + paper_simulator.py, KEEPING analyst.py (the declared llm_analysis Gemini capability + B4 scaffolding) so the self-validation gate/credential inventory stay untouched. (#127) D2 — revived the structurally-DEAD per-strategy drawdown auto-disable: the trade counter only incremented in record_execution from a venue payload that never carries a `strategy` tag, so `trades>=min_trades` could never fire; moved counting to record_pnl. (#128) frontend design_taste — "—" not a fabricated +$0.00 on the header P&L + strategy strip before data loads (the exact QUALITY_SCORECARD gap; positions-tab real-zero correctly left alone). (#129) security A→A+ — control auth is now DEFAULT-CLOSED (no token => 401) with a BACKEND_AUTH_DISABLED=1 dev opt-out that can never be live. THE GATE EARNED ITS KEEP: #127's both Sonnet reviewers caught a curated-gate-red stale test (fixed 1 cycle); #129's Reviewer B caught stale auth docs + a missing boot-refusal test (fixed 1 cycle); Opus auditors returned SOUND (#127) + SAFE (#129). ANTI-PADDING held: DROPPED the NaN-settlement guard (impossible state — parser already coerces to finite) + the weather edge-formula fix (gated-off unvalidated strategy) + ABANDONED the correctness SQLModel fix after PROVING the scout's extend_existing fix insufficient (real cause = dual import path, a 21-file test refactor, deferred as a focused next-run PR + it's outside the CI gate). No DoD/floor box ticked; engine_pct stays 74 (dead-code removal + correctness/security/honesty hardening, not new completeness). BINDING CONSTRAINT STILL OWNER-BLOCKED: real DoD/floor movement needs a real less-pinned point-in-time OOS corpus + a real alpha — OA-16 (HuggingFace Polymarket-v1, preferred) / OA-13 / OA-11 / OA-15 — ALL egress 000 in-env again. NOT churning/stuck (0 reverts, 1 abandon with a classified dead_end reason, 4 durable PRs, 2 clean fix cycles), so no harness proposal; highest-value next action is the owner's, surfaced via notification. unmet=[]. NEXT-RUN NOTES: (1) THE correctness A→A+ top_gap real fix — standardize the test import path (app.* vs backend.app.*) so the 7 PredictionPortfolio-family models register once; extend_existing alone is proven insufficient (relationship class-registry dup); a focused ~21-file refactor. (2) ruff correctness-gate F7 is now clean-able: paper_simulator's F811 is gone (#126), so a `ruff --select E9,F821,F811` gate needs only the orchestrator.py (2×) + strategies.py (1×) redundant-import F811 fixes + adding ruff to requirements-ci.txt + the preflight.sh select — verify green then require. (3) the last A1 residue: config.data_provider Literal + its /status echo (config-only). (4) WeatherArbitrageStrategy edge formula is `(1-P)*C - P` but should be `C - P` — fix inside the B7 re-validation, not standalone. (5) auth_core.configured_token still calls get_settings twice per request via the adapter (cheap, lru_cache; optional tidy). (6) confirm the Gamma ?id= + Kalshi status/price contract on the first real fetch (egress-blocked).
```

## How to read the latest signal

**2026-07-01 (22nd datapoint — factory run, 4th of the day) — `improving`, the biggest run of the day: 4 file-disjoint value-bar-clearing PRs across A1 + risk + design + security, all through the two-gate review.**
An 8-Haiku skeptical scout sweep (A1-residue · correctness/test-isolation · security-default-closed · frontend-honesty · risk/exec · data/backtest · ruff-F7 · self-validation-honesty) surfaced the maximal disjoint set; shipped **4 code PRs + this bookkeeping**: **(#126)** the LOWEST incomplete ROADMAP item **A1** — deleted the dead `/learn` teaching surface (`explainer/tutor/memo`, which built an OpenAI client from a **non-existent** `settings.openai_api_key`) + the dead `paper_simulator.py`, deliberately **KEEPING** `analyst.py` (the declared `llm_analysis` Gemini capability + B4 scaffolding) so the self-validation gate/credential inventory stay untouched; **(#127)** **D2** — revived the structurally-**DEAD** per-strategy drawdown auto-disable (its trade counter only incremented in `record_execution` from a venue payload that never carries a `strategy` tag, so `trades>=min_trades` could never fire → moved counting to `record_pnl`); **(#128)** **design_taste** — `—` not a fabricated `+$0.00` on the header P&L + strategy strip before data loads (the positions-tab real-zero correctly left alone); **(#129)** **security A→A+** — control auth is now **DEFAULT-CLOSED** (no token ⇒ 401) with a `BACKEND_AUTH_DISABLED=1` dev opt-out that config refuses to honour with live money. **The two-gate discipline earned its keep:** #127's **both** Sonnet reviewers caught a stale curated-gate test that would have shipped a RED gate (fixed 1 cycle); #129's Reviewer B caught stale `auth_core` docs + a missing live-opt-out boot-refusal test (fixed 1 cycle); the Opus safety auditors returned **SOUND** (#127, loss caps untouched, no false-disable) and **SAFE** (#129, no fail-open, both live-boot refusals proven). **Anti-padding held HARD:** DROPPED the NaN-settlement guard (impossible state — the parser already coerces non-finite prices to a finite sentinel) and the weather edge-formula fix (a real bug but on a GATED-OFF unvalidated strategy — re-derive it in the B7 re-validation, not standalone), and **ABANDONED** the correctness SQLModel A→A+ fix after PROVING the scout's `extend_existing` fix INSUFFICIENT (the real cause is the dual `app.*`/`backend.app.*` import path — a ~21-file test refactor, deferred as a focused next-run PR, and it's outside the CI-blocking gate). No DoD/floor box ticked; `engine_pct` stays **74** (dead-code + correctness/security/honesty hardening, not new completeness). **Binding constraint STILL OWNER-BLOCKED:** a real less-pinned point-in-time OOS corpus + a real alpha — ALL egress (Polymarket / Kalshi / HuggingFace) `000` in-env again. Owner action **OA-16** (preferred) / **OA-13** / **OA-11** / **OA-15**. NOT `churning`/`stuck` (0 reverts, 1 abandon with a classified `dead_end` reason, 4 durable PRs, 2 clean fix cycles), so no harness proposal — the highest-value next action is the owner's, surfaced via notification. **Next-run notes:** (1) the correctness A→A+ top_gap REAL fix — standardize the test import path (`app.*` vs `backend.app.*`) so the `PredictionPortfolio`-family models register once (`extend_existing` alone proven insufficient — relationship class-registry dup); (2) the ruff correctness-gate **F7** is now clean-able (paper_simulator's F811 gone via #126; only 3 orchestrator/strategies redundant-import F811s remain + add ruff to `requirements-ci.txt` + the `--select E9,F821,F811` preflight step); (3) the last A1 residue: `config.data_provider` Literal + its `/status` echo (config-only); (4) the WeatherArbitrageStrategy edge formula `(1-P)*C - P` should be `C - P` — fix inside B7 re-validation; (5) confirm the Gamma `?id=` + Kalshi contract on the first real fetch (egress-blocked).

### Earlier

**2026-07-01 (21st datapoint — factory run, 3rd of the day) — `improving`, an INTEGRITY + A1 dead-code run: 2 genuine file-disjoint PRs, the headline from a MERGED independent research finding.**
The highest-EV start was NOT a scout sweep — it was the **independent Research Run 11 (#115) integrity finding** (a maker≠checker flag already merged), which named a real BUILDS≠WORKS/honesty gap: `WhaleCopyTradingStrategy` + `WeatherArbitrageStrategy` were wired **unconditionally** into BOTH default scanners despite being untracked in ROADMAP/RESEARCH_MEMORY, with zero tests and zero B3 evidence, and the whale feed ran on a **fabricated `KNOWN_WHALES` seed** (unverifiable addresses; one a self-evident sequential-hex placeholder). Verified against real code, then shipped **2 code PRs + this bookkeeping**: **(#116)** removed the fabricated seed (now `[]` — the feed uses only real `/leaderboard`+`/holders` discovery, real signal or none) and gated both strategies **off-by-default** behind `ENABLE_UNVALIDATED_STRATEGIES` (the `LIVE_TRADING_ENABLED` pattern), with a pure regression suite + ROADMAP **B7** tracking; **(#117)** an **A1** stock-era dead-code removal — deleted the legacy `db/models.py` equity/paper-trading SQLModel stack (registered only by `create_all`, read by nothing) + the yfinance `strategy_tester.py` (imported nowhere), which **also removes the `stock_prices` dual-registration `SAWarning`/fragility** — the exact residue A1's own text named. **The 6-reviewer gate earned its keep twice:** the Opus BUILDS≠WORKS auditor **RAN `init_db`** and confirmed the 10 prediction/durable tables still build with the dual-registration warning gone (#117 SOUND); Reviewer B caught that deleting `strategy_tester.py` **orphaned the `yfinance` dependency** line (fixed in 1 cycle, removed from both requirements files). **Anti-padding held hard:** the frontend "`|| 0` fabrication" scout finding was **dropped after proving the backend always serializes those fields** and the blocks are load-guarded — so every `|| 0` renders a REAL value, and "fixing" a real `0`/`$0.00` to `—` would HIDE real info (wrong direction, unlike the #110 unloaded-summary case); data/risk/security/backtest scouts returned NOTHING-GENUINE on a mature engine. No DoD/floor box ticked; `engine_pct` stays **74** (integrity + dead-code, not new completeness). **Binding constraint STILL OWNER-BLOCKED:** real DoD/floor movement needs a real, less-pinned, point-in-time OOS corpus + a real alpha — ALL egress (Polymarket / Kalshi / HuggingFace) is `000`/blocked in-env again. Owner action **OA-16** (HuggingFace Polymarket-v1, preferred) / **OA-13** / **OA-11** / **OA-15**. NOT `churning`/`stuck` (0 reverts/abandons, 2 durable PRs, 1 clean fix cycle), so no harness proposal — the highest-value next action is the owner's, surfaced via notification. **Next-run notes:** (1) the REST of the A1 stock-era residue is a coherent next chunk (deferred — collides with `routes.py` which #116 touched): the `/learn/*` `QuantExplainer`/`QuantTutor` + `llm/analyst.py` + `llm/memo.py` dead-LLM surface + the `config.data_provider` Literal + the dead `paper_simulator.py` — do it as ONE focused A1 PR; (2) `whale_feed.py:97/115` still logs "using hardcoded seeds"/"N hardcoded" (now always 0) — a stale-log micro-tidy; (3) SELL-path `record_pnl` still a held-to-resolution no-op; (4) a gated-live OPEN-status resting order books a zero-size phantom position (unreachable, live default off — defense-in-depth candidate); (5) confirm the Gamma `?id=` + Kalshi status/price contract on the first real fetch (egress-blocked).

### Earlier

**2026-07-01 (20th datapoint — factory run, 2nd of the day) — `improving`, honest small run: 2 genuine hardening PRs shipped, ~8 candidates rejected after proving each against real code; the binding constraint stays OWNER-BLOCKED.**
Started, per the strongest recent loop-memory lesson ("a deferred next-run note IS the next run's headline — mine the prior auditor's flags first"), by investigating the prior run's 3 NEXT-RUN NOTES by OBSERVING the real code before scouting — and **disproved all 3** as non-value-bar-clearing: `paper_simulator.py` is dead (imported nowhere in `backend/app`, tests, or scripts); `_persist_resolution`'s `get_session()` genuinely commits on clean exit and re-raises-then-logs on failure, so the swallow is reporting-only, **not** a #108-class silent no-op; the Gamma `?id=` live-confirm is egress-blocked. So the prior flags produced no headline — the diligence itself was the value (avoided fixing dead code / a non-bug). Then a **7-Haiku skeptical scout sweep** (data/venues · model/alpha · risk/exec · security/§12 · quality/frontend/artifact · correctness/dead-code · learning-wiring) surfaced ~10 candidates; each was **verified against the actual code** and only 2 were genuine + file-disjoint. Shipped **2 code PRs + this bookkeeping**: (#112) **Kalshi bid/ask bounded to (0,100]** — the `yes_bid`/`yes_ask` checks were a bare `> 0` while the `last_price` branch already bounds to `(0,100]`; an out-of-range cent quote (`yes_bid=150`) passed and **clamped to a fabricated `1.0` certain-outcome price** — now a rejected side falls through to untradeable, never a fabricated certainty (data-honesty, same class as #101 and the Kalshi one-sided-book fix; 2 regression tests **proven to fail on pre-fix code**); (#113) **Equity Curve** — the portfolio chart's hand-rolled bars scaled height as `(value − seriesMin)/range` with **no axis labels**, so a 0.5% move on a ~$1000 book rendered as a ~50% bar; replaced with a recharts **labeled line chart + a starting-balance reference line** (the `design_taste` top_gap the QUALITY_SCORECARD names; the sibling `WeeklyMetricsCard` was already fixed, this one overlooked). **The adversarial gate earned its keep:** #113 Reviewer B (value/honesty) **REQUEST_CHANGES** — the PR claimed parity with the `$0`-anchored P&L sibling but used a pure `dataMin/dataMax` zoom; fixed in **1 cycle** by adding the starting-balance reference line (the honest anchor for a *value* series, vs `$0` for a *P&L delta* series) + disclosing the deliberate deviation, and a fresh re-review APPROVED. **Anti-scarcity AND anti-padding both held:** rejected ~8 candidates after proving each against real code — 4 WalletBehaviorDivergence div-by-zeros (impossible-state: the deployed alphas are non-zero constants with no zero-injection path + the whale-trade data is unfed = padding); the `/learn/explain` "unauthenticated LLM spend" (UNREACHABLE — `has_llm_key` gates on `gemini_api_key` but the explainer builds `OpenAI(api_key=settings.openai_api_key)` and `openai_api_key` **does not exist** on `Settings` → `AttributeError` → template fallback; dead/broken stock-era legacy, not frontend-wired); the price/pnl-history try-except (WRONG DIRECTION — degrading a DB-down 500 to an empty list would **fabricate a "no data" success**, dishonest; a 500 is honest for a read endpoint); and the multi-run-deferred SELL-path `record_pnl` (no new reachability evidence). No DoD/floor box ticked; engine_pct stays **74** (correctness + honesty hardening, not new completeness). **Binding constraint STILL OWNER-BLOCKED:** real DoD/floor movement needs a real, less-pinned, point-in-time OOS corpus + a real alpha — and ALL egress (Polymarket / Kalshi / HuggingFace) is `000`/blocked in-env again this run, so the loop cannot fetch it. Owner action **OA-16** (HuggingFace Polymarket-v1, preferred) / **OA-13** (egress allowlist) / **OA-11** / **OA-15**. NOT `churning`/`stuck` (0 reverts/abandons, durable correct changes), so no harness proposal — the highest-value next action is the owner's, surfaced via notification. **Next-run notes:** (1) SELL-path realized PnL still doesn't feed `risk_manager.record_pnl` — re-verify whether a SELL opp actually realizes PnL in prod (the `executor.execute` path) before building; (2) the `/learn/*` QuantExplainer surface is dead/broken stock-era legacy — a candidate for deliberate A1 stock-residue DELETION, scoped on its own; (3) `paper_simulator.py` remains dead — deletion candidate; (4) confirm the Gamma `?id=` + Kalshi status/price contract on the first real fetch (egress-blocked).

### Earlier

**2026-07-01 (19th datapoint — factory run, 1st of the day) — `improving`, found + fixed a HIGH-severity BUILDS≠WORKS that 5 prior skeptical scout sweeps missed: the settlement path was DEAD in prod.**
The headline was NOT a scout find — it was the prior run's **NEXT-RUN NOTE** (the #104 Opus auditor's flag), investigated FIRST this run by observing the real code. `MarkToMarketEngine.check_resolutions()` looked positions up via `get_market_by_slug(pos.market_id)`, but positions store `market_id=opp.market.id` — the Gamma **numeric** id, a **DISTINCT field** from the URL `slug`. Querying Gamma's `slug` filter with a numeric id matches **nothing**, so `market` was always `None` → **no position ever settled in production**: resolution PnL never realized, the executor loss caps + kill switch never fed on the dominant binary-market loss path (D3/D4), MTM never reconciled. Every unit test passed because the fakes are `def get_market_by_slug(self, _slug)` — **they ignore the argument** (a mock that accepts any input can't catch a wrong-key bug). Shipped **3 file-disjoint code PRs + this bookkeeping**: (#108) **resolution lookup by id** — new `get_market_by_id()` (queries the `id` filter) + a regression test **proven to FAIL on pre-fix code** (position never settles), plus a same-file order-book honesty fix (`get_order_book` no longer fabricates best_bid=0/best_ask=1 for an empty/one-sided book → a bogus 100%-wide spread a strategy reads via `book.spread`); (#109) **§12 input bounds** on the last two unbounded state-mutating request models (`PlaceOrderRequest`/`/execute`, `SubscribeRequest`/`/feeds/subscribe` — size=inf/price=NaN/oversized-list gaps closed); (#110) **frontend honesty** — Portfolio cards show `—` not a fabricated `$0.00`/`0` when the summary hasn't loaded. **The adversarial gate earned its keep: 7 reviewers (2 Sonnet each + 1 Opus safety auditor on the money-path #108), 0 fix cycles** — BOTH #108 Sonnet reviewers AND the Opus auditor independently **reverted the one-line fix and confirmed the regression test fails on pre-fix code** (`0.0 == -50.0`), and the Opus auditor independently validated that deferring the known `_persist_resolution`-swallow issue is SAFE (`executor.positions` is never rehydrated — `load_positions_into_executor` has **0 callers** — and the safety-critical loss counters + kill-switch state persist independently BEFORE `_persist_resolution`, so a swallowed write is reporting-only degradation, not a double-count). **`improving`** (3 PRs vs the prior run's 1, 0 abandoned/revert, a real high-severity defect closed). No DoD/floor box ticked; engine_pct stays 74 (correctness/security/honesty hardening, not new completeness). **Binding constraint STILL OWNER-BLOCKED:** real DoD/floor movement needs a real, less-pinned, point-in-time OOS corpus + a real alpha — and ALL egress (Polymarket / Kalshi / HuggingFace) is `000`/blocked in-env again, so the loop cannot fetch it. Owner action **OA-16** (Polymarket-v1 HuggingFace corpus, preferred) / **OA-13** (egress allowlist) / **OA-11**. NOT `churning`/`stuck` (0 reverts/abandons, durable correct changes), so no harness proposal — the highest-value next action is the owner's, surfaced via notification. **Next-run notes:** (1) `paper_simulator._resolve_market` (`paper_simulator.py:366`) has the SAME slug-vs-id call but degrades safely (falls back to a `get_markets()` scan matching `m.id`/`m.condition_id`) — a follow-up tidy, give it `get_market_by_id`; (2) `_persist_resolution` still swallows DB failures (reporting-only divergence, non-safety-critical this run); (3) confirm the Gamma `?id=` filter param on the first real fetch (documented-but-unverified-live, egress-blocked).

### Earlier

**2026-06-30 (18th datapoint — factory run, 5th of the day) — `steady`, ONE genuine side-effect-integrity fix; the binding constraint is now OWNER-BLOCKED and convergence needs an owner data action.**
A deliberately SKEPTICAL 4-Haiku scout sweep (data/alpha · risk/safety · backtest/learning · quality/frontend lenses) — primed with "default to nothing-genuine; 4 hardening runs already today; egress blocked" — surfaced exactly **ONE** genuine, file-disjoint, value-bar-clearing fix; **3 of 4 scouts returned NOTHING-GENUINE**. Shipped **1 code PR + this bookkeeping**: (#104) **side-effect integrity on the settlement path** — `MarkToMarketEngine.check_resolutions()` settled a held position at a fabricated `winning_price=0.0` (a phantom TOTAL loss) whenever the held `token_id` was ABSENT from a resolved market's `outcomes` (a data inconsistency: a re-resolved/stale market, a malformed/short `clobTokenIds` array). That invented loss fed `record_realized_pnl()` and could **AUTO-TRIP the kill switch on a fiction** (halting the whole bot), and cached the position resolved so it never reconciled — the same honesty class as #101 ("a missing quote is not a 50/50 market") and #95 (no phantom fill). Fixed with a `None` sentinel: settle only when the token is present (a found loser still settles at real 0.0), else log loudly + skip + leave uncached to retry. **The adversarial gate earned its keep with NO fix cycle:** 2 Sonnet reviewers + 1 fresh Opus safety auditor all cleared it first pass — and **two of them INDEPENDENTLY REPRODUCED** the kill-switch-on-fiction failure against pre-fix code (`[KILL SWITCH] ACTIVATED — realized $-50.00 breaches -$5.00`), proving it's a real defect, not padding. **`steady`, honestly:** 1 PR vs the prior run's 4 — after 5 runs today the engine-hardening barrel is near-empty, so honest output is small (anti-padding > volume). The one owner-gated find (NearCertaintyStrategy 72h-vs-720h, ROADMAP F1) was SURFACED, not built — it's a trading-behavior decision the loop must not make unilaterally. **THE headline: the binding constraint is OWNER-BLOCKED.** No DoD/floor box can move without a real, point-in-time, less-pinned OOS corpus + a real alpha — and ALL egress (Polymarket / Kalshi / HuggingFace) is blocked in-env again this run, so the loop cannot fetch it. Real convergence now needs the owner to action **OA-16** (download the Polymarket-v1 HuggingFace corpus — 1.3M markets, CC-BY-4.0, the preferred bypass) or **OA-13** (widen egress) / **OA-11**. This is NOT `churning`/`stuck` (0 reverts, 0 abandoned, a durable correct change), so no harness proposal is warranted — but the highest-value next action is now the owner's, surfaced via notification. **Next-run note:** the Opus auditor flagged two pre-existing, orthogonal latent issues to investigate — (1) `check_resolutions` fetches via `get_market_by_slug(pos.market_id)` but positions store the Gamma numeric `id`, not the slug, so if `id != slug` resolution may never fire in prod; (2) `_persist_resolution` swallows failures, so in-memory vs DB settlement can diverge.

### Earlier

**2026-06-30 (17th datapoint — factory run, 4th of the day) — `improving`, a data-integrity + security hardening sweep; the adversarial gate caught a stale-quote bug and named the one consumer missing the active-gate.**
An 8-Haiku scout sweep across tracks A–G (data-integrity / security / correctness / artifact-freshness lenses) surfaced the maximal file-disjoint, value-bar-clearing set; shipped **4 code PRs + this bookkeeping**, all ship-critical-dimension (functional-reality / security / artifact-integrity) hardening: (#99) **§12** — bound the remaining UNBOUNDED read endpoints + quant-model float params (resource-exhaustion + NaN/inf-into-model) and sanitize the unauthenticated `/status` raw-exception leak; (#100) **BUILDS≠WORKS** — the live WS price path did a bare `float()` with NO validation, so NaN/inf/out-of-range could silently poison the in-memory price cache that strategies+executor read (the batch path has DQV; the feed did not) → coerce + range-check every field, skip the update on a bad primary price; (#101) **side-effect integrity** — the Polymarket parser FABRICATED a `0.5`/empty-token "tradeable 50/50" market that PASSES DQV (the data analog of a fake fill) → now marked untradeable (`active=False`), un-fabricated data fails DQV; (#102) **honesty-invariant completion** — gate `CalibrationBucketStrategy.scan` on `market.active` (the one consumer the parse fix relied on that wasn't gating). **The gate earned its keep twice:** (1) Reviewer A returned REQUEST_CHANGES on #100 — the `last_trade_price` timestamp refreshed even when ALL fields were rejected, so a garbage flood could keep a stale quote looking fresh (defeating the 300s staleness eviction); fixed in ONE cycle + a regression test. (2) the Opus data-integrity auditor (**SOUND** — could not get a fabricated/invalid price onto any deployed tradeable path) named `CalibrationBucketStrategy` as the lone consumer missing the active-gate → shipped as #102. **Honest maximal selection under a mature engine (engine_pct 73→74) + an egress-blocked binding constraint:** rejected ~20 scout candidates as padding / false-positive (a kelly seed_hash "bug" that's actually the documented strategy-fn exclusion) / dead-unwired (paper_simulator) / already-fixed (scan-guard #96) / wrong-direction (loosening a loss cap) / already-deferred (SELL-path held-to-resolution no-op) / sensitive-staged (F7 lint ratchet). **All egress (HuggingFace + Polymarket + Kalshi) is 403 in-env this run** — confirming OA-11/OA-15/OA-16 are owner-scope, not a loop wall. No DoD/floor box ticked — hardening, not a validated edge; binding constraint unchanged, so no harness proposal warranted.

### Earlier

**2026-06-30 (16th datapoint — research run, 3rd of the day) — `improving`, Polymarket-v1 HuggingFace dataset identified as a bypass for the primary data blocker; EXP-003 proposed on domain-calibrated political miscalibration.**
Academic synthesis across five 2026 papers identified three actionable findings: (1) **Polymarket-v1** (arxiv 2606.04217) — 1.3M resolved markets on HuggingFace under CC-BY-4.0 with market metadata + outcomes in the `daily_aligned/` Parquet layer; no Polymarket API egress required; proposed as **OA-16** (the preferred path to bypass OA-11). (2) **Le 2026** (292M trades) confirms domain-specific calibration: political markets are PERSISTENTLY underconfident at all horizons (bilateral partisan cancellation compresses prices toward 50%); proposed **EXP-003** (domain-calibrated political strategy, same mechanism as the already-built CalibrationBucketStrategy). (3) **Prediction Arena + PolyBench**: autonomous LLM trading on Kalshi loses money (-16% to -30.8%); Gemini-3-Flash achieves +6.2% CWR on Polymarket — this REFINES B4 (targeted Gemini research tool for specific domains, not autonomous trader). Correctly classified insider-signal copying as out-of-scope; proposed an in-scope defensive adverse selection filter. No code PRs this run (research-only). No harness proposal warranted — the data blocker now has two owner paths (OA-11 OR new OA-16), so the loop has forward motion without a rule change.

### Earlier

**2026-06-30 (15th datapoint — factory run, 2nd of the day) — `improving`, the adversarial gate killed a fail-safe that was DEAD CODE in prod, and a stale-base hazard was caught before it shipped.**
An 8-Haiku scout sweep across tracks A–G surfaced the maximal file-disjoint, value-bar-clearing set; shipped **3
code PRs + this bookkeeping**, all ship-critical-dimension hardening: (#96) **API security** — guard the lone
unguarded state-mutating route `/prediction-markets/scan`, bound user inputs, and bounds-validate `risk/config` so a
non-positive daily-loss cap (which would DISABLE loss protection) is rejected 422; (#95) **side-effect integrity** —
stop fabricating a phantom fill (empty token_id) for multi-leg `outcome_idx == -1` arbitrage baskets, skipping them
honestly until per-leg execution (B1) exists; (#94) **executor fail-closed** — a durable-store rehydrate failure now
trips the kill switch instead of silently resuming a halted bot. **The gate earned its keep twice:** (1) a fresh Opus
live-safety auditor returned **NOT-SAFE** on #94 — the new fail-closed branch only fired if `load()` raised, but the
production `ExecutorStateStore.load()` swallowed every error and returned `None`, so it was **dead code against the
only store that ships** (a DB-down restart would still resume un-halted); fixed by making `load()` distinguish ABSENT
(None) from UNREADABLE (raise) + a REAL-store fail-closed test + a defense-in-depth empty-token reject, and a fresh
**re-audit returned FIX-HOLDS**. (2) A **stale local default-branch ref** (lagging origin by ~25 commits, pre-auth)
nearly based two PRs on old code — caught when a security scout's "/scan is the only unguarded route" contradicted the
session-start read (which showed every route guarded); recovered by fetching origin, resetting the ref, and rebasing,
which in turn surfaced a false-green test the stale base had hidden. **No DoD/floor box ticked** — hardening across
security/§12, run-risk-readiness (D3/D4), and side-effect integrity (B1); engine_pct 72→73. Binding constraint
unchanged: the 7-day-lead OOS corpus + a real alpha (OA-11/OA-15, owner/egress-scope), so no harness proposal
warranted. unmet=[].

### Earlier

**2026-06-30 (14th datapoint — factory run) — `improving`, the adversarial gate caught TWO real defects the tests passed over.**
An 8-Haiku scout sweep across tracks A–G surfaced the maximal file-disjoint, value-bar-clearing set; shipped **2
code PRs + this bookkeeping**: (#92) ROADMAP **A3 — a second-venue Kalshi DATA adapter** (`kalshi_client.py` +
`kalshi_history_fetcher.py`) behind the SAME `Market`/`Outcome`/`HistoricalMarket` interface, with the same
structural anti-leakage guarantee as the Polymarket fetcher, fully offline fixture-tested, no new credential; and
(#91) a **deep-audit hardening pass** (live-only control-auth boot-guard; category-cap under-count fix; risk-score
div-by-zero guards; MTM client reuse; API exception-detail leak sanitization). **The gate earned its keep twice:**
(1) a fresh Opus **parsing auditor returned BROKEN** on the Kalshi adapter — the offline fixtures had encoded
Kalshi's *request-side filter* words (`"open"`/`"finalized"`) as if they were *live response* values, so the
adapter would have dropped **every live market** (a BUILDS≠WORKS: 45 green tests proving nothing about real
behavior); fixed to the documented response contract (`active`/`settled`/`determined`, `settled` discovery filter,
one-sided-book honesty, `p=0` tick fix) + an honest "documented-but-unverified-live" disclosure + a loud
warning-on-unknown-status net, and a **re-audit returned FIX-HOLDS**; (2) an Opus **live-safety auditor** found the
category-cap fix used the wrong cap field (`RiskConfig.max_single_position_usd` $50 vs the executor's real
`max_position_usd` ~$5) → a ~10x over-reservation, corrected to read the executor's actual cap. Both fixed in ONE
cycle each (≤2-cycle brake), merged on green required checks. **Anti-scarcity + anti-padding both held:** deferred
B6 strategy-control + D6 reconciler (genuinely buildable but collide with #91 on `orchestrator.py` — the disjoint
rule, not scarcity), F5 Playwright (real exec risk + can't CI-gate; a focused run suits it better), and F7 lint
(low value / risky on the trading path); a deep-audit scout found NO real defect beyond the audit findings, so none
was invented. No DoD/floor box ticked — venue infra + hardening, not a validated edge; binding constraint stays the
7-day-lead OOS corpus (OA-11 Polymarket, new OA-15 Kalshi — owner/egress-scope), so no harness proposal warranted.

### Earlier

**2026-06-29 (13th datapoint — factory run) — `improving`, the adversarial gate caught a real BUILDS≠WORKS the tests missed.**
Shipped 3 file-disjoint PRs from an 8-scout sweep, all driving named QUALITY_SCORECARD top_gaps: (A) control-path
hardening — durable kill-switch + realized-PnL persistence so a restart can't un-trip the halt or reset the loss
budget (run-risk-readiness top_gap), REST venue-fill validation (side-effect integrity, D1), and a degrade-safe
shared-secret on the 12 state-mutating backend routes (security top_gap, OA-14); (B) frontend design-taste — deleted
the dead `Math.random()` `equity-chart.tsx` and fixed the WeeklyMetricsCard P&L axis to always include $0; (C) this
bookkeeping. **The headline win — an Opus live-safety auditor proved a BUILDS≠WORKS the unit tests passed over:** the
durable audit-log/registry/executor tables were never created at startup (`init_db`'s `create_all` ran *before* their
lazy import), so the "durable" persistence silently no-op'd in prod. Root-caused (import the table modules in `init_db`
before `create_all`) and pinned with a cold-start subprocess regression test. **The gate earned its keep again:** 2
Sonnet reviewers + 3 Opus auditors (auth REAL+SOUND, side-effect SOUND, live-safety SAFE) flagged 2 MUST-FIX (auth
fail-open log→CRITICAL; deactivate-persist race) + several hardening nits — all fixed in ONE consolidated cycle (≤2-cycle
brake), then re-verified green. **Anti-scarcity + anti-padding both held:** dropped D2-SELL-path (a no-op in the current
held-to-resolution flow — would be a fake control) and the alpha/egress-blocked items (B1/E7/B3-derivation/C2) on the
value+disjoint rules, not invented. No DoD/floor box ticked — hardening, not a validated edge; binding constraint stays
OA-11 (7-day OOS corpus, owner/egress-scope), so no harness proposal warranted.

### Earlier

**2026-06-29 (11th datapoint) — `improving`, the loop can now mechanically prove it validates the app.**
Added a **self-validation coverage gate** (`docs/ci/SELF_VALIDATION.md` manifest +
`scripts/check_self_validation.py`, blocking preflight step 9d): every *active* capability must be
really `validated`/`gated_off`/`degrades_safely`, and every credential the code reads must be
declared — a **new, undeclared** credential **surfaces + blocks every PR** (proven end-to-end with a
simulated `KALSHI_API_KEY`). By design the gate needs zero keys to validate the active app; keys are
only for *activation* (live = human-core) or *enhancement* (Gemini = optional). The factory routine
now maintains the manifest as part of shipping any capability. 8 regression tests; seeded green.

### Earlier

**2026-06-29 (10th datapoint — factory run) — `improving`, the binding constraint now has a BUILT mechanism, and disjoint discipline held under contention.**
Shipped 3 file-disjoint code PRs + 1 bookkeeping from an 8-scout sweep: the FIRST `model_prob != crowd`
alpha mechanism (`CalibrationBucketStrategy` — per-bucket empirical calibration, leakage-safe, abstaining,
3-Opus-auditor-clean), the E5/E2 learning engines WIRED into the resolved stream + read-only endpoints
(honest insufficient-data/degenerate paths), and a frontend metrics dashboard rendering every `/metrics/*`
endpoint with honest empty/degenerate states. **Disjoint discipline under contention:** 3 genuinely-buildable
items (B6, per-leg arb, A4) all wanted `orchestrator.py`, which the E5/E2 PR already owned — correctly deferred
to a later run (the disjoint rule, NOT scarcity); Kalshi A3 + lint F7 were dropped on the value bar (premature /
cosmetic). **Anti-padding both ways:** a deep-audit scout found NO real defect, so no defect-PR was invented.
**The adversarial gate earned its keep:** both Sonnet reviewers caught a shared-mutable-model-in-closure bug
(fresh-model-per-call fix + a re-fit test) and an Opus auditor named an idealized-test honesty gap (added a
cost-band-suppression test) — all fixed in ONE cycle, shipped on mechanical verification (≤2-cycle brake).
No DoD/floor box ticked — B4a is the mechanism for an edge, not a validated edge; the highest-EV unlock stays
OA-11 (the 7-day OOS corpus, owner/egress-scope), so no harness proposal is warranted.

### Earlier

**2026-06-29 (9th datapoint — research run) — `steady`, EXP-002 proposed with zero code waste.**
Research-only run. Fixture calibration audit (54 records) + academic synthesis (Le 2026 Kalshi
calibration decomposition, PolyBench LLM-ensemble results, 3%-of-traders price-discovery study) converged
on EXP-002: the 54-record corpus is pinned at 48h and cannot test any calibration hypothesis. The
fetch_polymarket_history.py script already accepts `--decision-lead-days` (no code change needed); re-running
OA-11 with 7-day lead is the single highest-EV owner action to unlock all calibration alphas. Correctly
classified a fixture calibration anomaly (near-certainty-NO bucket: stated 0.8%, empirical 5.9%, p≈0.029)
as "insufficient data" — N=34 with ~2 YES outcomes, in-sample, biased sample; not an edge claim.
No code PRs; 1 bookkeeping PR (RESEARCH_MEMORY + GROWTH_STATUS + LOOP_HEALTH).

### Earlier

**2026-06-29 (7th datapoint — factory run) — `improving`, the model/strategy layer got better AND the adversarial
gate earned its keep again.** Shipped 4 file-disjoint PRs (#63–#66) from an 8-scout sweep: hardened the
cross-market keyword relatedness screen (B5), made the calibration gate's multiple-comparison correction
code-enforced (B2 Bonferroni), and built the first concrete learning-loop engines — an alpha lifecycle
registry with a fail-loud integrity gate (B3) and a per-strategy realized-PnL attribution primitive (E6).
**Anti-padding worked:** an 8th scout's alleged cost_model "extreme-price" bug did not survive scrutiny
(the floor is conservative, the safe direction), so it was dropped pre-build rather than shipped as busywork.
**The two-gate discipline caught real defects across two fix cycles:** a fresh Opus auditor broke the first
B5 hardening cut (entity-gating still admitted venue/nationality-shared pairs AND dropped acronym subjects)
→ simplified to a broad-stopword content screen; Sonnet/Opus reviewers caught a naive-timestamp round-trip
that broke determinism on non-UTC hosts and a frozen-dataclass-with-mutable-dict — all fixed within the
≤2-cycle brake, then merged on a green required check (no 3rd audit on a strictly-more-conservative change).
Gate strengthened 176→~290 enforced tests. No DoD/floor box ticked — these are engine/integrity pieces; the
binding constraint stays loop-buildable (a real alpha + wiring the new engines), so no harness proposal is
warranted.

### Earlier

**2026-06-29 (6th datapoint) — `improving`, closed the data-access gap hands-off.** Staged the
real-data refresh automation (OA-13): the fetcher now `--merge`s to ACCUMULATE a growing OOS corpus,
and a scheduled GitHub Action (or the env egress allowlist) keeps it fresh without a human — the
loop's egress wall stops being a recurring manual residual. Honest scope: the permanent toggle is
owner-irreducible (platform/`.github/` settings), so it's staged + tracked, not faked.

### Earlier

**2026-06-29 (5th datapoint) — `improving`, the adversarial gate earned its keep.** Shipped 5
file-disjoint PRs (#56–#60) from an 8-scout sweep: C5 metrics wired end-to-end, a venue-layer
fail-closed live gate, a real-data reproduction canary, a forensic strategy-audit harness, and
enforced LLM timeout + spend cap. **0 abandoned, 0 reverts.** The two-gate discipline caught real
defects pre-merge: 2 Sonnet reviewers flagged precision bugs in the metrics aggregator (iterator
double-consume; float-equality degenerate check) and — most importantly — a fresh Opus honesty
auditor **broke** the strategy-audit claim ("0 signals on the real sample" was FALSE: the harness's
own boilerplate question text produced ~98 phantom signals). All were fixed in ONE consolidated
cycle and are now guarded by loud regression tests; the blocking gate was extended from 99 to 176
enforced tests so the new safety/metrics/canary/audit checks bind every future change. The binding
constraint stays loop-buildable (a real decision-time alpha producing model_prob != crowd), not an
environmental wall — so no harness proposal is warranted.

### Earlier

**2026-06-28 (4th datapoint) — `improving`, the required check now has teeth.** Hardened the
gate enforcement so it actually binds the loop: `enforce_admins=true` (an `--admin` merge can no
longer bypass), `strict=false` (parallel file-disjoint PRs still auto-merge), repo
`allow_auto_merge=true`, and the merge protocol switched to `gh pr merge --squash --auto` in
ROADMAP "Shipping protocol" **and in all three PR-merging routine prompts** (factory / research /
auditor) — so every future autonomous run waits for CI instead of force-merging. Also shipped a
prod boot-guard: `E2E_DISABLE_RATE_LIMIT` can never be active with `LIVE_TRADING_ENABLED`
(`enforced_in_ci: true`). No open proposals.

### Earlier

**2026-06-28 (3rd datapoint) — `improving`, first harness proposal raised AND resolved.** Staged
the required-check + lint-at-zero work (`docs/ci/PROPOSED_CI.md`), raised harness issue **#51**
for the one piece the loop can't self-apply (branch protection = admin scope) — and the owner
authorized it the same day, so it was applied: the branch is now protected requiring
`code + safety gate (blocking)`, so a change that regresses the live gate / kill switch /
paper-pipeline reproduction **can no longer auto-merge** (OA-12 done, `harness_proposals_open`
back to 0). Held lint-at-zero *off* (166 ruff findings in trading code) rather than red-block the
now-required gate — exactly "verify green before requiring" (ratchet tracked as ROADMAP F7). The
META channel did its full job: raise → action → close, not a silent wall and not a hanging issue.

### Earlier

**2026-06-28 (2nd datapoint) — `improving`.** Throughput is healthy (**43 merged / 0 reverts /
0 abandoned** over 7 days), and the wall that loomed last run got knocked down: the **Polymarket
egress block** (403 at the env proxy) that made real-data OOS validation impossible was resolved
*for data access* by running the leakage-safe fetcher from a network-permitted host (54 real
records, pipeline reproduces — see `OA11_REAL_DATA_VALIDATION.md`). It did NOT recur as a
convergence wall, so it is **not** trending toward `stuck`; the residual is only *periodic
refresh scheduling* (OA-11, `blocked_owner`). Crucially the binding constraint **moved** from
data-access to "need a real alpha model" — which is **loop-buildable** (track B), i.e. forward
motion, not a dead-end. Per FACTORY_STANDARD §10b, had that same wall blocked a second run with
no progress, the rule would have flipped the signal to `stuck` and required one
`loop: harness improvement proposal`. It didn't — so none is opened, honestly.
