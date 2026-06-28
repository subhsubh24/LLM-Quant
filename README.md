# LLM-Quant

**A personal, autonomous prediction-markets trading bot.** Not a product, not
marketed, no users — its only job is to make the owner money, honestly, with an edge
that compounds as the model improves.

> **Status: paper trading only.** It runs on simulated money by default. The full
> real-money path is built but **gated off** behind an owner-only switch
> (`LIVE_TRADING_ENABLED`, default false) + hard loss caps + a kill switch. There is
> **no validated edge yet** — see the honest status below. Nothing here is financial
> advice.

---

## What it is

LLM-Quant scans prediction markets (Polymarket today; Kalshi/others planned), estimates
probabilities, computes edge/EV, sizes positions with fractional Kelly, and trades —
by default with **fake money (paper)**. It improves its **calibration, accuracy, and
edge** over time through backtesting, paper trading, and self-directed research.

A small **Next.js monitoring/control panel** (the only UI) shows paper/live PnL,
strategies, calibration, the GO signal, and the kill switch.

> It is being pivoted to **prediction-markets-only**; the legacy stock/crypto trading
> paths are being retired (see [`ROADMAP.md`](ROADMAP.md) A1) while the asset-agnostic
> infra (backtest, validation, metrics, risk, execution) is kept.

## Why prediction markets — the edge thesis

Prediction markets are a **level playing field**: everyone sees the same public data,
so there's no secret data feed that wins. The edge therefore comes from being
**better-calibrated, better-reasoned, more logically consistent, faster/cheaper to
execute, and more disciplined** than the crowd — never from "data other people don't
have." Any alpha that depends on non-public data is out of scope. (Full rationale in
[`VISION.md`](VISION.md).)

## Honest status

- **No validated out-of-sample edge yet.** The engine runs in paper/dry-run, but
  there is no reproducible, cost-realistic, OOS weekly-PnL series. The profit floor
  (≥ $2,000/wk validated) is **not met**; all PnL/calibration metrics are `0`/`null`.
- The **GO signal** (`docs/growth/GROWTH_STATUS.md` → `go_live`) is `not_ready`. It is
  **derived, never hand-set** — `scripts/preflight.sh` fails if "eligible" is declared
  without the real proof, so a "GO" can't be faked.
- This is by design: an honest "not ready" beats a fake "great backtest."

## How it's built — the autonomous factory

LLM-Quant runs on the same autonomous "factory" process as the owner's other projects:

- [`FACTORY_STANDARD.md`](FACTORY_STANDARD.md) — the shared, product-agnostic operating
  discipline (the loop, two-gate readiness, BUILDS≠WORKS + visual verification, the
  independent quality scorecard, the value bar, the brakes). Byte-identical across
  factories; changes only by canonical sync.
- [`ROADMAP.md`](ROADMAP.md) — the convergence anchor: tracks A–G, the Definition of
  Done (= the go-live bar), and the standing standards.
- [`VISION.md`](VISION.md) — the north star, the edge thesis, and the learning loop.
- `scripts/preflight.sh` — the mechanical gate (code+safety scope is CI-blocking; the
  full gate adds the profit-floor + DoD + quality + GO checks, honest-red until proven).

Cloud routines drive it: a **model/strategy factory** (every 6h), a **research + alpha
agent** (daily), and a **daily digest** — all paper-only; none ever moves real money.

## Architecture

```
LLM-Quant/
├── backend/                       # FastAPI — the trading engine (persistent service)
│   └── app/
│       ├── api/                   # routes + app entrypoint (app.api.main:app)
│       ├── prediction_markets/    # the core: scanner, strategies, orchestrator,
│       │                          #   Kelly sizing, paper simulator, risk manager,
│       │                          #   execution (kill switch + LIVE gate), feeds
│       ├── backtest/ + simulation/ + portfolio/  # asset-agnostic quant infra (kept)
│       ├── trading/               # legacy stock/crypto engine (being retired — A1)
│       ├── llm/                   # Google Gemini analysis (optional)
│       ├── config.py              # settings (env-driven)
│       └── db/                    # SQLModel — SQLite (dev) / Neon Postgres (prod)
│
└── frontend/                      # Next.js monitoring/control panel (the only UI)
    └── app/  dashboard · predictions · bot · login   # password-gated
```

- **DB:** SQLite locally; **Neon Postgres** in production (`DATABASE_URL`).
- **LLM:** Google **Gemini** (`GEMINI_API_KEY`, optional; falls back to templates).
- The backend is a **stateful, always-on service** (continuous scan loop, live
  WebSocket feeds, in-memory positions/risk) — it runs on a persistent host, **not**
  serverless. The frontend is a static Next.js app for Vercel.

## Run it locally

**Backend** (paper mode; no venue keys needed):
```bash
cd backend
pip install -r requirements.txt
uvicorn app.api.main:app --reload --port 8000     # http://localhost:8000  (/docs for API)
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev                                       # http://localhost:3000
```

Set `APP_PASSWORD` + `AUTH_SECRET` to use the password gate locally; otherwise the
panel redirects to `/login`.

## Deploy

Frontend → **Vercel**, backend → **Railway/Render** (persistent), DB → **Neon**. Full
step-by-step (env vars, the GO/CORS gotchas, the security notes) is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Going live (owner-only)

The loop builds and paper-validates the entire live path but **never** funds, sets
live keys, flips `LIVE_TRADING_ENABLED`, or raises a cap. Those are **HUMAN-CORE**,
tracked in [`PENDING_OPS.md`](PENDING_OPS.md) with exact steps in
[`docs/growth/LIVE_RUNBOOK.md`](docs/growth/LIVE_RUNBOOK.md). Paper needs **zero** venue
keys; the Polymarket live credentials are required only when *you* decide to go live.

## Tests & gate

```bash
bash scripts/preflight.sh code      # CI-blocking correctness + safety gate
bash scripts/preflight.sh           # full gate (honest-red until go-live-eligible)
python3 scripts/runtime_harness.py  # BUILDS != WORKS: live gate, kill switch, paper PnL
```

---

*Honest by design: real money stays off until the bot proves a validated, reproducible,
cost-realistic edge — and even then, going live is the owner's decision.*
