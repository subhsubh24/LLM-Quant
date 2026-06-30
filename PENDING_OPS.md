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
      title: "Schedule the resolved-history fetcher on a network-permitted host (accumulate a real OOS corpus)"
      priority: medium
      status: in_progress
      why: "PARTLY DONE (2026-06-28): the fetcher was run from a network-permitted host and the pipeline is VALIDATED on REAL data — 54 leakage-safe records (data/polymarket_history_sample.json), walk-forward reproduces deterministically (seed_hash 8dc358439ffb5746). Findings in docs/autonomous-loop/OA11_REAL_DATA_VALIDATION.md: the crowd is very sharp on liquid near-resolution markets (Brier ~0.09, ~70% already price-pinned 2 days out), so NO edge exists at those points and the floor box correctly stays unticked. The binding constraint has MOVED from 'can't reach data' to 'need (a) markets sampled before they pin + (b) a real alpha model (ROADMAP track B)' — not an egress problem anymore. The autonomous build env STILL can't refresh the dataset (egress 403 at the proxy), so periodic real-data refresh remains owner/host scope."
      how: "Run scripts/fetch_polymarket_history.py (--order volumeNum) on a schedule where Polymarket's public Gamma + CLOB APIs are reachable — the backend host (a cron/worker) or a network-permitted CI job — to grow a real OOS corpus over time, OR widen the autonomous env's egress allowlist to gamma-api.polymarket.com + clob.polymarket.com so the loop can refresh it itself. No credentials needed (public read-only data). The EDGE work (a real model; sampling earlier-life markets) is loop-buildable and tracked under ROADMAP track B — it is NOT an owner action. AUTOMATION STAGED — see OA-13."
    - id: OA-13
      title: "Automate the real-data refresh (pick ONE): env egress allowlist OR a scheduled GitHub Action"
      priority: high
      status: open
      why: "Makes OA-11 hands-off: instead of a human re-running the fetcher, the corpus refreshes itself. The loop can't do this (its env blocks Polymarket egress) and can't write .github/, so one one-time owner step is irreducible. The fetcher now supports --merge (accumulate by market_id, never overwrite), so a scheduled refresh GROWS the corpus over time."
      how: "OPTION A (simplest, no files): add gamma-api.polymarket.com + clob.polymarket.com to the FactoryDashboard env (env_01LdppMwowGrstp5M55vgJXv) egress allowlist — then the loop fetches real data itself, zero new files/secrets. OPTION B (no egress change): add the staged workflow .github/workflows/refresh-polymarket-data.yml + a DATA_REFRESH_PAT secret (fine-grained PAT, contents+pull-requests write) — GitHub runners CAN reach Polymarket and open an auto-merging data-only PR. Full detail + exact YAML + the GITHUB_TOKEN-recursion caveat: docs/ci/PROPOSED_DATA_REFRESH.md. No credentials needed to READ Polymarket (public data); the PAT only opens the PR."
    - id: OA-14
      title: "Set BACKEND_API_TOKEN (+ frontend server-side proxy) to protect the backend control routes on a public deploy"
      priority: medium
      status: open
      why: "BUILT this run (security top_gap): the backend's state-mutating routes (kill-switch, risk config, execute, portfolio reset, bot start/stop/scan) now accept a shared-secret bearer token, enforced server-side (backend/app/api/auth.py, decision in backend/app/auth_core.py). It DEGRADES SAFELY: with BACKEND_API_TOKEN unset (the default) auth is disabled and paper/dev is unchanged, so nothing is required for paper. The control surface is only credential-protected once the owner sets the token on a public deploy. The browser must never hold the secret, so the frontend has to attach it via a SERVER-SIDE proxy (Next.js route handler / server action reading a non-NEXT_PUBLIC env var), not a NEXT_PUBLIC var."
      how: "On a public/internet-exposed deploy: (1) set BACKEND_API_TOKEN=<random-secret> in the backend host env (server-side only, never committed, never NEXT_PUBLIC); (2) add a server-side proxy in the frontend that injects `Authorization: Bearer <token>` from a server-only env var on the state-mutating calls (so the secret stays off the browser); (3) verify a tokenless direct POST to /prediction-markets/kill-switch/activate now returns 401. Not needed for local/paper (default-off). The autonomous loop never sets this token."
    - id: OA-12
      title: "Make the blocking CI gate a REQUIRED check (branch protection) so broken changes can't auto-merge"
      priority: high
      status: done
      why: "DONE (2026-06-28, owner-authorized): branch protection enabled on claude/llm-stock-trading-app-fXupf requiring ONLY 'code + safety gate (blocking)', strict=true (must be up to date), enforce_admins=false (manual override retained). The green gate is now REQUIRED — a change that regresses the live gate / kill switch / paper-pipeline reproduction can no longer auto-merge. Applied via the gh-api call in docs/ci/PROPOSED_CI.md §A3 (a repo-settings API action, not a .github/ file edit); harness issue #51 closed."
      how: "Already applied. To adjust later: re-run / edit the branch-protection command in docs/ci/PROPOSED_CI.md §A3. When lint-at-zero (ROADMAP F7) is green, ruff rides inside this same job — the required-checks list does NOT change."
    - id: OA-15
      title: "Run the Kalshi resolved-history fetcher on a network-permitted host (accumulate a real Kalshi OOS corpus) — the Kalshi analog of OA-11"
      priority: medium
      status: open
      why: "BUILT this run (ROADMAP A3, #92): a leakage-safe Kalshi market-data adapter + resolved-history fetcher, fully offline-validated. Public Kalshi market data needs NO credentials. The autonomous build env blocks Kalshi egress (403 at the proxy), so the loop cannot pull real Kalshi history itself. A second venue with a different liquidity/lifetime profile is a real way to widen the edge search beyond Polymarket's most-liquid (≈70%-pinned-2-days-out) markets. NOTE: the Kalshi status/price field CONTRACT is encoded per Kalshi's DOCUMENTED API but is NOT yet confirmed against a live response — the first real fetch must verify it (an unrecognized status is logged LOUDLY, never silently dropped)."
      how: "Run `python scripts/fetch_kalshi_history.py --out data/kalshi_history_sample.json --decision-lead-days 7` on a host where Kalshi's public trade-API v2 is reachable (the backend host / a network-permitted CI job), OR widen the autonomous env's egress allowlist to api.elections.kalshi.com (mirrors OA-13 Option A for Kalshi). No credentials needed (public read-only data). On the first run, CONFIRM the status/price contract (watch the logs for any 'unrecognized status' warnings) and report back so the offline mapping can be reconciled with live. The EDGE work (a real model; multi-venue routing; the live executor) is loop-buildable under ROADMAP track B/A3 — it is NOT an owner action."
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
| OA-11 | Real-data run DONE (pipeline validated); schedule periodic fetch on a permitted host | 🟡 medium | in progress |
| OA-12 | Make `code + safety gate (blocking)` a REQUIRED check (branch protection) | 🟠 high | ✅ done |
| OA-13 | Automate real-data refresh: env egress allowlist OR scheduled GitHub Action | 🟠 high | pending |
| OA-14 | Set `BACKEND_API_TOKEN` (+ frontend proxy) to protect control routes on a public deploy (default-off; not needed for paper) | 🟡 medium | pending |
| OA-15 | Run the Kalshi history fetcher on a network-permitted host (real Kalshi OOS corpus; verify the live status/price contract) | 🟡 medium | pending |
| OA-7 | Paper→live + raise target (owner-only) | 🟡 medium | pending |
| OA-8 | Wire gate into CI (workflow scope) | 🟡 medium | pending |

**The loop paper-trades only. It never funds, never flips live, never raises a cap.**
