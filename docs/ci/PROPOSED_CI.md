# PROPOSED CI — required-check + deploy automation (owner apply)

> The loop **cannot edit `.github/`** (a headless workflow-scope edit hangs the run), so the
> CI itself is built and STAGED here for a one-time workflow-scope human apply. Everything on
> the *product* side (the gate script, its tests, lint config) ships through the normal
> branch→PR→gate→merge path; only the **branch-protection toggle** and any **`.github/`
> change** are the irreducible human steps.

Status legend: ✅ done by the loop (already merged) · 🔶 owner one-time step · ⏸️ staged, not
yet enabled (precondition pending).

---

## Part A — make the quality gate a REQUIRED check

**Goal:** a change that *builds* but is broken-for-a-user — or is lint-dirty — must NOT
auto-merge.

### A1. Functional gate — ✅ ALREADY BUILT + GREEN

LLM-Quant has **no UI journey suite** (it's a personal trading bot with a thin monitoring
panel — F5 is deliberately deferred). Per the directive, its functional gate is the
**deterministic paper/backtest reproduction harness**, which already runs as the blocking CI
job today:

- Workflow: `.github/workflows/preflight.yml` → job **`code + safety gate (blocking)`** →
  `bash scripts/preflight.sh code`.
- What it asserts (outcome-asserting, self-seeding, in-process — no external services):
  - import smoke (config + `api.main` import clean);
  - prediction-market + scorecard tests pass (`pytest`);
  - **runtime harness** (`scripts/runtime_harness.py`): the live gate blocks real orders, the
    kill switch halts trading, position/loss caps reject, **a paper order really fills and the
    paper pipeline reproduces bit-for-bit** (seed → identical PnL + `seed_hash`);
  - secret scan, fenced-YAML-block parse, GO-signal integrity.
- This is the "backtest/paper-reproduces-deterministically gate" the directive specifies for
  LLM-Quant. **It is already green on every PR.** It just isn't *required* yet (see A3).

### A2. Lint-at-zero — ⏸️ STAGED, not yet enforceable (precondition: clean the tree)

`scripts/preflight.sh` step 3 already runs `ruff check backend/app` **and fails the gate**
(`die`) on any finding — **but only `if command -v ruff`**, and `ruff` is **not** in
`backend/requirements-ci.txt`, so in CI lint is silently skipped today.

**Why it is not flipped on yet:** the tree currently has **166 ruff findings** (116 unused
imports, 16 unused locals, 16 module-imports-not-at-top, 7 empty f-strings, …) — and many sit
in **runtime-sensitive trading code**. Per the directive's rule *"VERIFY GREEN BEFORE
REQUIRING — never make a flaky/red check required"*, adding `ruff` to the CI deps now would
turn the **blocking** gate red and **block all auto-merges**. Bulk `ruff --fix` across the
trading path is also unsafe (removing an "unused" import on a `table=True` SQLModel or a
strategy-registry entry can silently break registration — we hit a SQLModel double-registration
incident recently).

**Path to enable (tracked as ROADMAP F7 — ratchet to zero):**
1. `ruff.toml` is committed (pins the standard; ignores `E402` only in `scripts/` where
   `sys.path` setup legitimately precedes imports).
2. Drive findings to **0** module-by-module, verifying the gate + prediction-market tests green
   after each (NOT one blind bulk autofix over the trading code).
3. Once `ruff check backend/app` is clean, add `ruff` to `backend/requirements-ci.txt`. That
   **alone** turns on lint-at-zero in the existing blocking gate — **no `.github/` edit
   needed**.

### A3. Branch protection — 🔶 OWNER ONE-TIME (the actual "required check" toggle)

The branch `claude/llm-stock-trading-app-fXupf` is **not protected** today, so the blocking
gate is advisory — a red gate does not actually stop a merge. Make it required:

```bash
# Requires admin on the repo. Enable branch protection requiring the blocking gate.
gh api -X PUT repos/subhsubh24/LLM-Quant/branches/claude%2Fllm-stock-trading-app-fXupf/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=code + safety gate (blocking)' \
  -F 'enforce_admins=false' \
  -F 'required_pull_request_reviews=null' \
  -F 'restrictions=null'
```

- **Require ONLY** `code + safety gate (blocking)`. Do **NOT** require
  `go-live readiness (informational)` — it is intentionally honest-red until a validated edge
  exists; requiring it would block every merge forever.
- Leave `enforce_admins=false` so the owner retains a manual override.
- Once lint-at-zero is green (A2) the required-checks list is unchanged — lint runs *inside*
  the same `code + safety gate` job.

**Required-checks list to set:** `code + safety gate (blocking)` — and nothing else.

### A4. Gotchas — what does NOT apply here (and why)

The directive's standard gotchas are about UI products that self-seed over HTTP. LLM-Quant's
gate is **in-process** (no server is started, no inbound HTTP), so:

- **Rate-limit bypass (`E2E_RATE_LIMIT_BYPASS`): N/A.** The app has **no inbound rate
  limiter** (only CORS middleware); the gate never makes inbound requests, so nothing can trip.
  Adding an env-gated bypass wired to no limiter would be an **unwired fake control** (forbidden
  by our DECISION COROLLARY). *If* a future gate ever starts the server and drives HTTP
  journeys against a real limiter, add `E2E_RATE_LIMIT_BYPASS` wired into that limiter **then**.
- **Trusted-host / base-URL env (`AUTH_TRUST_HOST`/`AUTH_URL`/`PLAYWRIGHT_BASE_URL`): N/A.** No
  server is started in the gate, and the frontend auth is a **custom HMAC password gate**, not
  next-auth — there is no trusted-host check to satisfy.

---

## Part B — auto-migrate-on-deploy — ⏭️ SKIP (no migration framework)

LLM-Quant has a DB (Neon Postgres in prod, SQLite in dev) but **no migration tooling** — no
Alembic, no Drizzle. Schema is created by **`SQLModel.metadata.create_all(engine)`**
(`backend/app/db/database.py`), which is **idempotent + forward-only** and already runs at app
startup — so the "migration" already self-applies on every deploy with **no manual step**.
Part B's goal is therefore already met for the create-all model; there is nothing to stage.

**Caveat / when to revisit:** `create_all` adds **new tables** but does **not ALTER existing
ones** (no column adds/drops/type changes). The day the loop needs a real schema *change* to a
live table, introduce Alembic and *then* stage a forward-only migrate job here:

```yaml
# FUTURE — only once Alembic exists. Runs on default-branch pushes, after the gate, forward-only.
migrate:
  needs: [gate]
  if: github.event_name == 'push' && github.ref == 'refs/heads/claude/llm-stock-trading-app-fXupf'
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.11" }
    - run: pip install alembic sqlmodel psycopg2-binary
    - run: alembic upgrade head        # forward-only; NEVER `downgrade`/`reset`
      env: { DATABASE_URL: ${{ secrets.DATABASE_URL }} }
```

Safety rails to bake in *at that time*: migrations still pass the 2-reviewer + security gate
**before** merge; the job is default-branch + post-gate only; forward-only. **Owner enables
Neon PITR / daily backups FIRST** (the recoverability net) — auto-apply removes the human schema
checkpoint, so it must be a conscious tradeoff.

---

## Summary of owner steps (one-time, workflow/admin scope)

| Step | Scope | Status |
|------|-------|--------|
| Enable branch protection requiring `code + safety gate (blocking)` (A3 command) | admin | 🔶 OA-12 |
| (After lint hits zero) nothing — lint rides inside the same required job | — | ⏸️ ROADMAP F7 |
| Part B migrate job | — | ⏭️ skipped (no migrations) |

After A3, a broken-for-a-user change (paper pipeline doesn't reproduce, kill switch/live gate
regressed, tests fail) **cannot auto-merge**. That is the recurring-work reduction this buys.
