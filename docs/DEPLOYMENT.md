# DEPLOYMENT — LLM-Quant

How to deploy the monitoring panel + backend. Three pieces:
**Supabase** (DB) → **backend host** (FastAPI) → **Vercel** (frontend).

---

## Architecture decision: the backend is NOT serverless

**The FastAPI backend must run on a persistent host (Railway / Render / Fly / a VM).
It cannot run on Vercel/Netlify functions**, and we are deliberately not porting it
there. Why:

- **Continuous scan loop** — the orchestrator runs `scan → size → execute` every
  120s as a background asyncio task. Serverless has no background loop; a function
  runs only while handling a request, then dies.
- **Persistent WebSockets** — live Polymarket + crypto price feeds hold open
  connections. Serverless can't keep a socket open between invocations.
- **In-memory state** — open positions, the risk manager's daily-PnL /
  circuit-breaker state, and the activity log live in memory and are shared across
  the loop. Serverless gives each invocation a cold, isolated memory.

Forcing it serverless would mean a large, risky refactor (cron triggers, dropping
live feeds for REST polling, pushing all state to Postgres) **and a worse bot** — for
a system whose job is to watch markets continuously. Not worth it to save a few
dollars a month. **The factory must not chase this** (recorded in `loop-memory.md`).

The **frontend** is a Next.js app and is perfect for Vercel. If you want a single
platform, run **both** the frontend and backend on Railway/Render instead of
splitting Vercel + Railway — same code, no serverless refactor.

### "But Vercel supports FastAPI now" — yes, and it still doesn't fit (yet)

Vercel can deploy FastAPI, but [their docs](https://vercel.com/docs/frameworks/backend/fastapi)
are explicit that the app **"becomes a single Vercel Function"** (serverless), and
two of their stated limits disqualify *this* app today:

1. **500MB function bundle limit** — `torch` alone is ~400MB installed; with
   `pandas`/`scipy`/`scikit-learn`/`xgboost`/`lightgbm` the bundle is ~1GB. `routes.py`
   imports `..models` (`ModelTrainer`, `EnsembleRanker`) at module load, so the ML
   stack can't simply be left uninstalled. **Hard stop regardless of architecture.**
2. **Serverless execution model** — the continuous 120s scan loop, the persistent
   Polymarket/crypto WebSocket feeds, and in-memory positions/risk/activity state
   cannot survive in a request-scoped function. "Fluid compute" keeps instances warm
   and concurrent but is **not a persistent daemon**; the 500ms shutdown cap +
   function timeouts confirm it's request-scoped.

**Future path (not now):** if the bot is trimmed to prediction-markets-only (drops
torch/xgboost → fits 500MB) AND refactored to be stateless (state in Supabase,
scanning via Vercel Cron, no WebSocket-server feeds), the request-serving API could
live on Vercel — but you'd still need a persistent worker for the scan loop, so it
adds a moving part rather than removing one. Until then: persistent host.

---

## 1. Supabase (database)

1. Create a project; set a strong DB password.
2. **Project Settings → Database → Connection string → Session pooler** (port 5432,
   IPv4-friendly). It looks like:
   ```
   postgresql://postgres.[REF]:[PASSWORD]@aws-[REGION].pooler.supabase.com:5432/postgres
   ```
   (Use the **Direct** string only if your backend host has IPv6.)
3. Lock down the Data API **after** the backend's first boot — see §4.

---

## 2. Backend host

The repo ships one-click configs for the two easiest hosts. The backend runs from
`backend/` and uses `backend/requirements.txt`.

> **Heads-up on size:** the backend bundles heavy ML deps (torch/xgboost/lightgbm)
> for the stock/crypto side, so it needs **~1GB+ RAM** — free tiers will OOM. Use a
> small paid instance (~$7/mo) until those deps are trimmed for a
> prediction-markets-only build (ROADMAP A1).

### Option A — Render (blueprint: `render.yaml`)
Render → **New → Blueprint** → point at this repo. The blueprint builds the backend
(`rootDir: backend`, binds `$PORT`, health check `/health`, `plan: starter`). Then set
the secret env vars (below) in the dashboard.

### Option B — Railway (`backend/railway.json`)
Railway → **New Project → Deploy from repo**. In the service settings set
**Root Directory = `backend`** — Railway then uses `backend/Dockerfile` +
`backend/railway.json` (binds `$PORT`, health check `/health`). Set the env vars below.

### Option C — Fly / any Docker host
`backend/Dockerfile` binds `${PORT:-8000}`. Build with **context = `backend/`**.

### Backend env vars
| Var | Value |
|---|---|
| `DATABASE_URL` | Supabase session-pooler string from §1 |
| `CORS_ALLOW_ORIGINS` | your Vercel origin, e.g. `https://llm-quant.vercel.app` (exact: scheme+host, no trailing slash; set after §3) |
| `LIVE_TRADING_ENABLED` | leave **`false`** (owner-only; never enable at deploy) |
| `DEMO_MODE` | `true` |
| `AUTO_CONNECT_BROKERS` | `false` |
| `ANTHROPIC_API_KEY` | optional (LLM features) |
| `FRED_API_KEY` | optional (market data) |
| `ALPACA_*` / `BINANCE_*` | optional (paper defaults) |

Deploy, then grab the backend's public URL (e.g. `https://llm-quant-api.onrender.com`).
Tables auto-create on first boot.

---

## 3. Vercel (frontend)

1. Import the repo → **Root Directory = `frontend`**.
2. Env vars:
   | Var | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | the backend URL from §2 |
   | `APP_PASSWORD` | your login password |
   | `AUTH_SECRET` | `openssl rand -hex 32` |
3. Deploy → you get `https://your-app.vercel.app`.
4. **Back on the backend host**, set `CORS_ALLOW_ORIGINS=https://your-app.vercel.app`
   and redeploy. (Chicken-and-egg: backend needs the Vercel URL, Vercel needs the
   backend URL — so the backend gets one redeploy.)

---

## 4. Lock down the Supabase Data API (OA-9 — sensitive data)

After the backend's first boot (so the tables exist), run this in the **Supabase SQL
Editor**. The backend connects as a privileged user and **bypasses RLS**, so the app
keeps working — this only blocks the public anon / Data API from reading your money
data:

```sql
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security;', r.tablename);
  end loop;
end $$;
```

Re-run it if the backend adds new tables later. **Never** put the Supabase
`service_role` key in the frontend.

---

## 5. Verify

- Visit `https://your-app.vercel.app` → you should hit the **password screen**.
- Log in → Dashboard / Predictions / Bot load with live data (the sidebar API dot
  turns green).
- Backend health: `https://your-backend/health` → `{"status":"healthy"}`.
- "API offline" on pages → check `NEXT_PUBLIC_API_URL` is correct and
  `CORS_ALLOW_ORIGINS` contains your **exact** Vercel origin.

Everything stays **paper-only** until you follow `docs/growth/LIVE_RUNBOOK.md`.
