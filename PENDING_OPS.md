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
    status: pending
    why: "The loop must not edit .github/; CI wiring is owner/maintainer scope."
    how: "Add a workflow calling scripts/preflight.sh on PRs. See LIVE_RUNBOOK §7."
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
| OA-7 | Paper→live + raise target (owner-only) | 🟡 medium | pending |
| OA-8 | Wire gate into CI (workflow scope) | 🟡 medium | pending |

**The loop paper-trades only. It never funds, never flips live, never raises a cap.**
