# LOOP MEMORY — LLM-Quant

Cross-run lessons for the autonomous factory loop. Append; read before each run.

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
