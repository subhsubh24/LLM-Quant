# PENDING OPS — LLM-Quant (Owner Actions / Human-Core)

These are the **HUMAN-CORE** steps the autonomous loop will **never** perform. The
loop builds and validates everything in paper; **only the owner** funds, sets live
keys, flips the switch, and raises caps. Full step-by-step detail lives in
[`docs/growth/LIVE_RUNBOOK.md`](docs/growth/LIVE_RUNBOOK.md).

<!-- OWNER_ACTIONS
items:
  - id: OA-1
    title: "Set HARD loss caps + kill switch + provider/LLM spend caps before ANY live capability"
    priority: critical
    status: pending
    why: "Real money at stake. No live path may be reachable without enforced ceilings + a working kill switch."
    how: "Set MAX_DAILY_LOSS_USD, MAX_TOTAL_LOSS_USD, MAX_PER_TRADE_USD in env; verify kill-switch auto-trip test passes. See LIVE_RUNBOOK §4."
  - id: OA-2
    title: "Confirm venue ToS + jurisdiction eligibility"
    priority: critical
    status: pending
    why: "Trading prediction markets may be restricted in the owner's jurisdiction; venue ToS must permit automated trading."
    how: "Review Polymarket/Kalshi ToS + local law; document the decision. See LIVE_RUNBOOK §1."
  - id: OA-3
    title: "Create/verify venue account + KYC"
    priority: high
    status: pending
    why: "Required before funding or live keys."
    how: "Complete venue signup + KYC. See LIVE_RUNBOOK §2."
  - id: OA-4
    title: "Deposit/transfer real funds"
    priority: high
    status: pending
    why: "Bankroll for live trading. Owner-only."
    how: "Transfer funds per LIVE_RUNBOOK §3. Start small."
  - id: OA-5
    title: "Set venue LIVE API keys in server env"
    priority: high
    status: pending
    why: "Live order placement requires authenticated venue keys, server-side only, never committed."
    how: "Set venue live keys in env (never in git). See LIVE_RUNBOOK §5."
  - id: OA-6
    title: "Flip LIVE_TRADING_ENABLED on (owner-only)"
    priority: high
    status: pending
    why: "Master gate that allows real orders. Default false; only the owner flips it after OA-1..OA-5."
    how: "Set LIVE_TRADING_ENABLED=true in env once validated in paper. See LIVE_RUNBOOK §6."
  - id: OA-7
    title: "Paper -> live decision + raising the weekly target are owner-only"
    priority: medium
    status: pending
    why: "Go-live and target escalation are judgment calls reserved to the owner."
    how: "Decide after go-live-eligible criteria met (validated >= $2-3K/wk OOS + 3 auditors + safe-by-default live path)."
  - id: OA-8
    title: "Wire the gate harness into CI (workflow scope)"
    priority: medium
    status: done
    why: "The loop must not edit .github/; CI wiring is owner/maintainer scope."
    how: "DONE — .github/workflows/preflight.yml runs scripts/preflight.sh (blocking code scope + informational full gate) on PRs + pushes."
  - id: OA-9
    title: "Lock down Supabase Data API exposure for the backend tables"
    priority: high
    status: pending
    why: "The backend connects to Supabase as a privileged DB user (SQLAlchemy), NOT via the Data API. But tables it creates in the public schema can be reachable through the Supabase Data API (PostgREST) with the anon/publishable key. This is sensitive financial data, so it must not be world-readable."
    how: "In Supabase: either disable the Data API for these tables / use a non-exposed schema, OR enable RLS on every public table with deny-by-default (no anon/authenticated policies). The backend's privileged connection bypasses RLS, so this does not affect the app. Never put the Supabase service_role key in the frontend."
  - id: OA-10
    title: "Decide whether the raw-sqlite audit trail should move to Postgres"
    priority: low
    status: pending
    why: "backend/app/trading/audit_store.py uses raw sqlite3 (a separate local file, not SQLAlchemy). On an ephemeral host it would lose the audit log; on a persistent-disk host it is fine. The main ORM DB now uses Supabase, but this audit log does not."
    how: "If the backend runs on persistent disk, leave as-is. To centralize in Supabase, rewrite audit_store.py onto SQLModel/Postgres (tracked as ROADMAP G3 audit-log work)."
-->

## Quick reference

| ID | Action | Priority | Status |
|----|--------|----------|--------|
| OA-1 | Hard loss caps + kill switch + spend caps | 🔴 critical | pending |
| OA-2 | Confirm venue ToS + jurisdiction | 🔴 critical | pending |
| OA-3 | Venue account + KYC | 🟠 high | pending |
| OA-4 | Deposit/transfer real funds | 🟠 high | pending |
| OA-5 | Set venue LIVE API keys | 🟠 high | pending |
| OA-6 | Flip `LIVE_TRADING_ENABLED` | 🟠 high | pending |
| OA-9 | Lock down Supabase Data API exposure (RLS / unexposed schema) | 🟠 high | pending |
| OA-10 | Move raw-sqlite audit log to Postgres (optional) | ⚪ low | pending |
| OA-7 | Paper→live + raise target (owner-only) | 🟡 medium | pending |
| OA-8 | Wire gate into CI (workflow scope) | 🟡 medium | pending |

**The loop paper-trades only. It never funds, never flips live, never raises a cap.**
