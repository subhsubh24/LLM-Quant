# PENDING OPS — LLM-Quant (Owner Actions / Human-Core)

These are the **HUMAN-CORE** steps the autonomous loop will **never** perform. The
loop builds and validates everything in paper; **only the owner** funds, sets live
keys, flips the switch, and raises caps. Full step-by-step detail lives in
[`docs/growth/LIVE_RUNBOOK.md`](docs/growth/LIVE_RUNBOOK.md).

> **Do I need to wire up API keys to run it?** For **paper trading (the default):
> NO venue keys are required.** The bot reads Polymarket's *public* market data and
> simulates fills — zero credentials. `GEMINI_API_KEY` is **optional** (LLM analysis;
> falls back to templates without it). The venue credentials below (OA-5) are needed
> **only when you choose to go live.** As the factory adds a new venue (e.g. Kalshi),
> it will append a new owner-action here naming exactly what to set (FACTORY_STANDARD
> §13), and the dashboard surfaces these via `OWNER_ACTIONS` + `GROWTH_STATUS`
> (`venues_connected` / `awaiting_connect`).

```yaml
OWNER_ACTIONS:
  items:
    - id: OA-1
      title: "Set HARD loss caps + kill switch + provider/LLM spend caps before ANY live capability"
      priority: critical
      status: open
      why: "Real money at stake. No live path may be reachable without enforced ceilings + a working kill switch."
      how: "Set MAX_DAILY_LOSS_USD, MAX_TOTAL_LOSS_USD, MAX_PER_TRADE_USD in env; verify kill-switch auto-trip test passes. See LIVE_RUNBOOK §4."
    - id: OA-2
      title: "Confirm venue ToS + jurisdiction eligibility"
      priority: critical
      status: open
      why: "Trading prediction markets may be restricted in the owner's jurisdiction; venue ToS must permit automated trading."
      how: "Review Polymarket/Kalshi ToS + local law; document the decision. See LIVE_RUNBOOK §1."
    - id: OA-3
      title: "Create/verify venue account + KYC"
      priority: high
      status: open
      why: "Required before funding or live keys."
      how: "Complete venue signup + KYC. See LIVE_RUNBOOK §2."
    - id: OA-4
      title: "Deposit/transfer real funds"
      priority: high
      status: open
      why: "Bankroll for live trading. Owner-only."
      how: "Transfer funds per LIVE_RUNBOOK §3. Start small."
    - id: OA-5
      title: "Set venue LIVE API keys in server env (prediction markets) — LIVE-ONLY, not needed for paper"
      priority: high
      status: open
      why: "Paper needs NO venue keys (public data + simulated fills). Live order placement on Polymarket requires authenticated venue creds + a funded Polygon wallet, server-side only, never committed."
      how: "Set on the backend host (Railway), never in git: POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY (Polygon wallet key), POLYMARKET_FUNDER (funder address). Kalshi (only once that adapter exists): the venue's live key/secret. See LIVE_RUNBOOK §5."
    - id: OA-6
      title: "Flip LIVE_TRADING_ENABLED on (owner-only)"
      priority: high
      status: open
      why: "Master gate that allows real orders. Default false; only the owner flips it after OA-1..OA-5."
      how: "Set LIVE_TRADING_ENABLED=true in env once validated in paper. See LIVE_RUNBOOK §6."
    - id: OA-7
      title: "Paper -> live decision + raising the weekly target are owner-only"
      priority: medium
      status: open
      why: "Go-live and target escalation are judgment calls reserved to the owner."
      how: "Decide after go-live-eligible criteria met (validated >= $2-3K/wk OOS + 3 auditors + safe-by-default live path)."
    - id: OA-8
      title: "Wire the gate harness into CI (workflow scope)"
      priority: medium
      status: done
      why: "The loop must not edit .github/; CI wiring is owner/maintainer scope."
      how: "DONE — .github/workflows/preflight.yml runs scripts/preflight.sh (blocking code scope + informational full gate) on PRs + pushes."
    - id: OA-9
      title: "Keep the Neon DATABASE_URL private (no Data API lockdown needed)"
      priority: medium
      status: open
      why: "DB is Neon Postgres. Neon has NO public Data API (no PostgREST / anon key), so the Supabase-style world-readable-tables risk does not exist — the DB is reachable only with the connection string. The remaining risk is simply leaking that string."
      how: "Keep DATABASE_URL server-side only (backend host env); never commit it or put it in any NEXT_PUBLIC_* var. If it leaks, rotate the password in the Neon Console. No RLS / Data API step is required on Neon."
    - id: OA-10
      title: "Persistent prediction-markets audit log — BUILT; only the hosting choice is owner-scope"
      priority: low
      status: in_progress
      why: "ROADMAP G3 is now DONE in code: prediction_markets/audit_log.py adds a durable PredictionAuditLog SQLModel table + best-effort AuditLogger, wired as an observer into the scan loop, recording every signal/risk/kelly decision + every (would-be) order on the ORM DB (no raw sqlite). The only remaining owner action is the DB hosting choice."
      how: "Confirm the backend host's DATABASE_URL points at the durable Neon Postgres (not an ephemeral container SQLite) so audit rows survive restarts. No code change needed."
    - id: OA-11
      title: "Run the resolved-history fetcher where Polymarket egress is permitted (unblocks real-data OOS validation)"
      priority: high
      status: open
      why: "The binding constraint for go-live is a VALIDATED out-of-sample edge on REAL resolved-Polymarket data. The leakage-safe fetcher (prediction_markets/polymarket_history_fetcher.py) is built + tested, but the autonomous build environment's egress policy BLOCKS outbound HTTPS to gamma-api.polymarket.com / clob.polymarket.com (403 at the proxy), so the loop cannot pull real history itself. Until the fetcher runs against real data, walk_forward + the calibration eval have only synthetic/fixture data and no DoD/floor box can tick."
      how: "Run scripts (or a small driver around PolymarketHistoryFetcher.fetch_resolved_markets + build_historical_markets) in an environment where Polymarket's public Gamma + CLOB APIs are reachable — e.g. the backend host, or widen the autonomous env's egress allowlist to include gamma-api.polymarket.com and clob.polymarket.com. Feed the resulting HistoricalMarket records into scripts/run_walk_forward.py + the B2 calibration eval. No credentials are needed (public read-only data)."
```

## Quick reference

| ID | Action | Priority | Status |
|----|--------|----------|--------|
| OA-1 | Hard loss caps + kill switch + spend caps | 🔴 critical | pending |
| OA-2 | Confirm venue ToS + jurisdiction | 🔴 critical | pending |
| OA-3 | Venue account + KYC | 🟠 high | pending |
| OA-4 | Deposit/transfer real funds | 🟠 high | pending |
| OA-5 | Set Polymarket LIVE API keys (LIVE-only; paper needs none) | 🟠 high | pending |
| OA-6 | Flip `LIVE_TRADING_ENABLED` | 🟠 high | pending |
| OA-9 | Keep Neon `DATABASE_URL` private (no Data API lockdown needed) | 🟡 medium | pending |
| OA-10 | Audit log BUILT (G3); confirm `DATABASE_URL` is durable Neon | ⚪ low | in progress |
| OA-11 | Run history fetcher where Polymarket egress is permitted (real-data OOS) | 🟠 high | pending |
| OA-7 | Paper→live + raise target (owner-only) | 🟡 medium | pending |
| OA-8 | Wire gate into CI (workflow scope) | 🟡 medium | pending |

**The loop paper-trades only. It never funds, never flips live, never raises a cap.**
