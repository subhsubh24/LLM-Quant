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
      how: "Run scripts/fetch_polymarket_history.py (--order volumeNum) on a schedule where Polymarket's public Gamma + CLOB APIs are reachable — the backend host (a cron/worker) or a network-permitted CI job — to grow a real OOS corpus over time, OR widen the autonomous env's egress allowlist to gamma-api.polymarket.com + clob.polymarket.com so the loop can refresh it itself. No credentials needed (public read-only data). The EDGE work (a real model; sampling earlier-life markets) is loop-buildable and tracked under ROADMAP track B — it is NOT an owner action. AUTOMATION STAGED — see OA-13. UPDATE (2026-07-04, Research Run 14): a research-agent session this run reached gamma-api.polymarket.com/clob.polymarket.com directly (real market data returned, not a block page) and used it to pull 510 real leakage-safe 7-day-lead records + run the first real OOS test of EXP-002 (result: failed — see ROADMAP B4a / RESEARCH_MEMORY 2026-07-04). This is NOT yet confirmed for the autonomous FACTORY build-loop specifically (a different session/environment) — the factory should re-probe the same domains itself (a simple curl, no code change) before assuming OA-11/13 still require an owner step. Also note: the CLI examples above pass --limit 250/500, which under-fetches to a single ~100-row page due to a pagination cap bug in fetch_resolved_markets (Gamma silently caps each page at 100 rows regardless of the requested limit) — use --limit 100 with a larger --max-pages instead until that is fixed. UPDATE (2026-07-04, 3rd factory run — CONFIRMED FROM THE FACTORY BUILD ENV ITSELF): the factory re-probed as recommended — direct curl HTTP 200 to gamma-api/clob/data-api.polymarket.com, api.elections.kalshi.com, AND huggingface.co, plus a real 799-record leakage-safe fetch through the committed pipeline. So the factory build env's OWN egress is now OPEN: the loop can refresh the corpus + run OA-11/OA-15/OA-16 validations ITSELF, no owner egress step required for the build-loop. (Owner step may still matter for the SCHEDULED workflows' env, which is separate — confirm there before closing OA-13.) The pagination cap bug is FIXED (#220): the fetcher now caps its per-page stride to 100 and pages correctly, so --limit is capped internally; grow the corpus via --max-pages. Real-data result of the first factory-env run: recency-alpha OOS test on n=799 REFUTED (−$914), static B4a non-robust (sign-flipped +$3,330 vs −$2,938 Run 14) — see RESEARCH_MEMORY 2026-07-04."
    - id: OA-13
      title: "Automate the real-data refresh (pick ONE): env egress allowlist OR a scheduled GitHub Action"
      priority: high
      status: open
      why: "Makes OA-11 hands-off: instead of a human re-running the fetcher, the corpus refreshes itself. The loop can't do this (its env blocks Polymarket egress) and can't write .github/, so one one-time owner step is irreducible. The fetcher now supports --merge (accumulate by market_id, never overwrite), so a scheduled refresh GROWS the corpus over time."
      how: "OPTION A (simplest, no files): add gamma-api.polymarket.com + clob.polymarket.com to the FactoryDashboard env (env_01LdppMwowGrstp5M55vgJXv) egress allowlist — then the loop fetches real data itself, zero new files/secrets. OPTION B (no egress change): add the staged workflow .github/workflows/refresh-polymarket-data.yml + a DATA_REFRESH_PAT secret (fine-grained PAT, contents+pull-requests write) — GitHub runners CAN reach Polymarket and open an auto-merging data-only PR. Full detail + exact YAML + the GITHUB_TOKEN-recursion caveat: docs/ci/PROPOSED_DATA_REFRESH.md. No credentials needed to READ Polymarket (public data); the PAT only opens the PR."
      caveat: "SAFETY — REMEDIATED 2026-07-04 (3rd run, #222): `WalletBehaviorDivergence` (sizes on a FABRICATED edge `abs(price-0.5)*0.2`) was wired UNGATED into both default scanners and safe-by-ACCIDENT only while data-api was egress-blocked. This run a DIRECT PROBE from the factory build env confirmed `data-api.polymarket.com/trades` returns HTTP 200 (reachable) — the trigger this caveat pre-registered. So #222 EXECUTED the pre-registered remediation: `wallet_divergence` is now gated behind ENABLE_UNVALIDATED_STRATEGIES (default off) like its siblings, and the gating test moved it into the unvalidated set. The default paper scan no longer runs it. To re-enable it, it must first be B3-validated. ORIGINAL FINDING (kept for history): enabling data-api egress would FEED this UNVALIDATED strategy (no B3 registry evidence, no OOS proof), left deployed by the #116 run (which gated only WhaleCopy/Weather); it produced 0 signals only because the feed was unreachable, an operational accident, not a design guarantee. THIS RISK IS CLOSER THAN IT LOOKED, THOUGH NOT YET OBSERVED FIRING (2026-07-04, Research Run 14): a research-agent session this run found data-api.polymarket.com directly reachable (real live trade data returned) from at least that environment, so this is no longer purely a future OPTION A/B scenario — it may already be one environment change away. Self-validation: spot-checked the `executions` list of 2 real executed live-validation.yml runs (2026-07-02T19:55, 10 trades; 2026-07-03T04:12, 6 trades) — every fired trade was `adaptive_threshold` or `logical_implication`; `wallet_divergence` did NOT appear in either, so it has not been observed firing in production as of this run (does not by itself prove data-api is unreachable from GH Actions — only that no signal has fired there yet, if it is reachable). Re-probing egress (per the OA-11 update above) and re-checking whether this strategy has started firing should happen together, not sequentially."
    - id: OA-14
      title: "Set BACKEND_API_TOKEN (+ frontend server-side proxy) to protect the backend control routes on a public deploy"
      priority: medium
      status: open
      why: "BUILT (security top_gap): the backend's state-mutating routes (kill-switch, risk config, execute, portfolio reset, bot start/stop/scan, AND the legacy /prediction-markets/scan — guarded 2026-06-30 #96) accept a shared-secret bearer token, enforced server-side (backend/app/api/auth.py, decision in backend/app/auth_core.py). #96 also bounds the user inputs and bounds-validates risk/config so a non-positive daily-loss cap (which would disable loss protection) is rejected 422. **DEFAULT-CLOSED as of 2026-07-01 (#129):** the mutating routes now DENY (401) when NO token is set, so a public paper deploy that forgets the token is no longer silently unauthenticated. Two ways to run: set BACKEND_API_TOKEN (public deploys) OR set BACKEND_AUTH_DISABLED=1 (a trusted single-user LOCAL/dev host — this opt-out can NEVER be active with LIVE_TRADING_ENABLED; config refuses to boot). The browser must never hold the secret, so the frontend attaches it via a SERVER-SIDE proxy (Next.js route handler / server action reading a non-NEXT_PUBLIC env var), not a NEXT_PUBLIC var."
      how: "On a public/internet-exposed deploy: (1) set BACKEND_API_TOKEN=<random-secret> in the backend host env (server-side only, never committed, never NEXT_PUBLIC); (2) add a server-side proxy in the frontend that injects `Authorization: Bearer <token>` from a server-only env var on the state-mutating calls (so the secret stays off the browser); (3) verify a tokenless direct POST to /prediction-markets/kill-switch/activate returns 401. For LOCAL/paper on a trusted host with NO token, set BACKEND_AUTH_DISABLED=1 to run the control routes open (they are now default-CLOSED). The autonomous loop never sets the token or the opt-out."
    - id: OA-12
      title: "Make the blocking CI gate a REQUIRED check (branch protection) so broken changes can't auto-merge"
      priority: high
      status: done
      why: "DONE (2026-06-28, owner-authorized): branch protection enabled on claude/llm-stock-trading-app-fXupf requiring ONLY 'code + safety gate (blocking)', strict=true (must be up to date), enforce_admins=false (manual override retained). The green gate is now REQUIRED — a change that regresses the live gate / kill switch / paper-pipeline reproduction can no longer auto-merge. Applied via the gh-api call in docs/ci/PROPOSED_CI.md §A3 (a repo-settings API action, not a .github/ file edit); harness issue #51 closed."
      how: "Already applied. To adjust later: re-run / edit the branch-protection command in docs/ci/PROPOSED_CI.md §A3. When lint-at-zero (ROADMAP F7) is green, ruff rides inside this same job — the required-checks list does NOT change."
    - id: OA-15
      title: "Kalshi price-history 404 FIXED (loop, #170); optional owner egress if you want the loop to fetch Kalshi itself"
      priority: low
      status: in_progress
      why: "FIXED (2026-07-02, #170 — loop-buildable half DONE): the live-verified 404 (`/trade-api/v2/markets/{ticker}/history` does not exist) is corrected to `/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks` (verified HTTP 200 live), deriving `series_ticker` from the ticker prefix + the required `period_interval` + a unit-aware nested-cents `_candle_price` (an auditor caught + fixed a 1¢→1.0 fabrication) + the shared NaN-timestamp guard. 2 Sonnet APPROVE + 1 Opus auditor FIX-HOLDS. So the real Kalshi OOS run now yields records on a permitted host (was N/A). PRIOR CONTEXT: VERIFIED (via the real-oos-validation lane on a permitted host — GitHub runner + local): Kalshi DISCOVERY worked but the per-market price fetch 404'd; that live-contract confirmation was exactly what OA-15 existed for. No credentials needed (public data)."
      how: "FIX (loop-buildable, factory two-gate — leakage-safe data code): the correct Kalshi price-history endpoint is `/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks` (VERIFIED HTTP 200 live; `/markets/{ticker}/history` = 404). Derive `series_ticker` from the market (the prefix before the first `-` of the ticker / event_ticker); call with `start_ts`/`end_ts`/`period_interval` (minutes). Then update `kalshi_history_fetcher` to parse the `candlesticks[]` schema (verify field names — yes-price mean/open/close, `end_period_ts` — on a market that actually HAS candlesticks; the first probe market returned an empty list) and extract the leakage-safe pre-resolution YES tick with the SAME guarantee as today (strictly-before-resolution). Add offline fixtures for the candlestick schema + an adversarial leakage audit, then the real-oos lane will pick up Kalshi automatically. OWNER: nothing required (public data, no keys). Only if you want the loop to fetch Kalshi ITSELF (vs. via the GitHub lane): add api.elections.kalshi.com to the env egress allowlist (mirrors OA-13 Option A)."
    - id: OA-16
      title: "Download Polymarket-v1 HuggingFace dataset (the FETCHER is now BUILT, #168) — run it on a permitted host"
      priority: high
      status: in_progress
      why: "DONE FROM THE BUILD ENV (2026-07-04, 4th run, #226): egress is open, so the factory streamed the real `daily_aligned` layer, CONFIRMED its schema (per-trade/per-outcome), remapped `HFFieldSpec` to it (P[YES]←`p_event` not raw `price`; resolution←`close_at`; outcome←`winning_outcome_label`; categorical markets skipped), and ran it end-to-end — 375 leakage-safe binary markets assembled from the 1.3M archive. So BOTH the code AND the download are done in the loop; this OA no longer needs an owner step for the build env (the scheduled-workflow env may differ — confirm there if you want the cron to run it too). Static B4a on this corpus = +$534.88 but FRAGILE (not an edge). PRIOR: FETCHER BUILT (2026-07-02, #168): `prediction_markets/polymarket_v1_hf_fetcher.py` streams the `daily_aligned` layer + assembles leakage-safe records (lazy `datasets` import, pure fixture-tested assembly, 40 tests, 3 Opus auditors FIX-HOLDS), wired as the OPT-IN `validate_real_oos.py --venues polymarket_v1_hf` (needs `pip install datasets` on a permitted host). So the CODE half is done — only the owner-side DOWNLOAD (HuggingFace egress) remains. The exact `daily_aligned` field names + units are VERIFIED on the first real download (the fetcher logs the columns + RAISES on an absent required column or a whole-corpus parse wipeout; auto-detects ms-epoch timestamps) — adjust `HFFieldSpec` if they differ. IDENTIFIED (research run, 2026-06-30): Polymarket-v1 Database (arxiv 2606.04217, June 2026) is the complete on-chain trade archive of Polymarket's CTF Exchange (2022-11-21 to 2026-04-28) — 1.20 billion trade records across 1.30 million markets, $61B nominal volume, available on HuggingFace (TimeSeventeen/Polymarket-v1) under CC-BY-4.0. The daily_aligned/ Parquet layer includes cleaned market metadata + event-normalized fields including resolution outcomes and price history. This could provide a MUCH LARGER research corpus than OA-11 (54 records → 1.3 million markets) WITHOUT requiring live Polymarket API egress (HuggingFace is a separate domain from gamma-api.polymarket.com). This is the preferred path to unlock EXP-002 + EXP-003. CONFIRMED-BLOCKED FROM THE AUTONOMOUS ENV (2026-07-01, research run): a direct test (curl through the loop's own proxy) shows huggingface.co returns a 403 CONNECT reject — the SAME class of block as gamma-api/clob.polymarket.com, and data-api.polymarket.com is independently 403-blocked too. This is a broad-scope egress policy, not a narrow Polymarket-only gap, so step 1 below can ONLY be verified from the owner's own network/host — the loop will not get a different result by retrying from this env."
      how: >
        Step 1 (verify egress): confirm HuggingFace is reachable from your environment:
          curl -s https://huggingface.co/datasets/TimeSeventeen/Polymarket-v1 | head -200
        If accessible: Step 2 (download a sample): install huggingface_hub and stream the
        daily_aligned/ Parquet layer:
          pip install huggingface_hub datasets
          python -c "from datasets import load_dataset; ds = load_dataset('TimeSeventeen/Polymarket-v1', 'daily_aligned', streaming=True); [print(r) for _, r in zip(range(5), ds['train'])]"
        Step 3: Once confirmed, run the loop-buildable polymarket_v1_hf_fetcher.py (to be
        built by the factory) which assembles leakage-safe HistoricalMarket records from the
        daily_aligned fields (market_id, outcome, price timestamps, resolution). The factory
        will build this fetcher once OA-16 step 1 confirms HuggingFace egress. No Polymarket
        API credentials needed (CC-BY-4.0 public dataset). NOTE: the daily_aligned/ layer has
        market metadata joined in but the exact field names for resolution outcome, pre-resolution
        price, and category must be verified on the first download — the factory will build the
        parser once the schema is confirmed.
    - id: OA-17
      title: "Live-validation workflow APPLIED; optional: add Neon DATABASE_URL secret for durable forward persistence"
      priority: medium
      status: in_progress
      why: "The 'real' self-validation tier (mock -> real). scripts/live_integration_smoke.py + scripts/run_paper_cycle.py are built + tested; they exercise the REAL Gemini + real public Polymarket + a FORWARD paper-trading cycle on live markets (paper fills only, never a real order). They can't run in the deterministic required gate (live data is non-deterministic; an outage must not freeze merges) or in the egress-blocked cloud loop — they need a network-permitted runner. The loop can't write .github/ headlessly."
      how: >
        DONE (workflow applied, owner-authorized): .github/workflows/live-validation.yml is live — a
        NON-BLOCKING scheduled job (every 6h + manual dispatch) on GitHub runners; it consumes the existing
        GEMINI_API_KEY secret and is NOT a required check. REMAINING (optional, owner-only — the value must
        never pass through chat/logs): for a DURABLE forward paper track record across runs, add your Neon
        connection string as an Actions secret from your own terminal:
          gh secret set DATABASE_URL --repo subhsubh24/LLM-Quant   # then paste the Neon URL at the prompt
        This is the DB connection string, NOT a trading key. WITHOUT it the cycle still runs but persists to
        an ephemeral SQLite that resets each run. NEVER add POLYMARKET_* trading keys (real orders are
        human-core). Fuller always-on alternative: the deployed Railway backend running the orchestrator
        loop (OA-10). Trigger a first run now: `gh workflow run live-validation.yml`.
    - id: OA-18
      title: "Next.js major bump 14 → 15+ (14.x line is EOL for security backports) — DECISION + migration"
      priority: medium
      status: pending
      why: >
        Surfaced during G5 (2026-07-12c, #313). The public prod trading UI is now on the vendor-patched
        next@14.2.35 (G5 cleared the specifically-warned Dec-11-2025 RSC DoS, CVE-2025-55184/67779). BUT the
        live npm/GHSA advisory DB now flags ~15 OTHER Next.js advisories against even 14.2.35 — SSRF via
        WebSocket upgrades, XSS via CSP nonces, cache poisoning in RSC responses, HTTP request smuggling in
        rewrites, image-optimizer DoS, middleware/proxy bypass — whose fixes land ONLY in 15.5.16+ / 16.x
        (NO 14.x backport; the 14.x line no longer receives security patches). Most are lower-severity /
        config-dependent for this small 4-route auth-gated app, but a full `npm audit` clear requires a
        major bump. This is HUMAN-CORE because it is a §21-class major-version commitment on a LIVE surface
        AND it forces React 18 → 19 (Next 15's App Router requires React 19), a second coupled major bump —
        NOT the narrow frontend-one-liner G5 was.
      how: >
        OWNER decides whether/when to take the 14 → 15+ (and coupled React 18 → 19) migration. It is NOT a
        real-money/live-trading action (frontend only), so once the owner authorizes it the LOOP can build it
        through the two gates: bump next to the latest patched 15.x (or 16.x), bump react/react-dom to 19,
        adopt the async request APIs (cookies/headers/params) + review caching-default changes, then
        re-validate EVERY route (`/`, `/login`, `/predictions`, `/api/auth/*`) + middleware/auth end-to-end
        (`npm run build` green + the flows still wire). No new secret, no backend change, independent of the
        alpha tracks. Until taken, the app runs on 14.2.35 with the residual advisories DOCUMENTED here +
        ROADMAP G6, not silently ignored. No credentials needed.
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
| OA-14 | Set `BACKEND_API_TOKEN` (+ frontend proxy) to protect control routes on a public deploy — routes are now default-CLOSED (#129); local/paper with no token needs `BACKEND_AUTH_DISABLED=1` | 🟡 medium | pending |
| OA-15 | Kalshi price-history 404 FIXED (#170); only optional owner egress remains | ⚪ low | in progress |
| OA-16 | Polymarket-v1 HF schema CONFIRMED + remapped + ran from the build env (#226); no owner step for the loop | 🟢 low | in progress |
| OA-17 | Live-validation workflow APPLIED (#PR); optional Neon `DATABASE_URL` secret for durable persistence | 🟡 medium | in progress |
| OA-18 | Next.js major bump 14→15+ (14.x EOL for security; forces React 18→19) — owner decision, then loop builds it (G5 #313 shipped the safe 14.2.35 patch) | 🟡 medium | pending |
| OA-7 | Paper→live + raise target (owner-only) | 🟡 medium | pending |
| OA-8 | Wire gate into CI (workflow scope) | 🟡 medium | pending |

**The loop paper-trades only. It never funds, never flips live, never raises a cap.**
