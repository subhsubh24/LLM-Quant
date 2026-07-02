# PROPOSED — the "real" (live) self-validation tier (non-blocking, scheduled)

> The required `code + safety gate` is deterministic / mocked / no-secrets **on purpose** — a
> Gemini rate-limit or a Polymarket outage must never freeze the loop's merges. This stages the
> SEPARATE, **non-blocking** tier that exercises the REAL integrations + a **forward paper-trading
> cycle on live markets**. The loop can't write `.github/` headlessly, so the owner applies one
> workflow file. Nothing here can place a real trade or blocks a merge.

## What runs (both already built + tested; runnable now on any network-permitted host)

- **`scripts/live_integration_smoke.py`** — real Gemini call (if `GEMINI_API_KEY` set) + real public
  Polymarket read. Exit 1 only on a genuine *code* break; external unavailability (no key / egress)
  is reported, never a red. → validates `llm_analysis` + `polymarket_market_data` for real.
- **`scripts/run_paper_cycle.py`** — one FORWARD paper cycle: `scan_and_execute()` on real open
  markets → record AS-IF filled (cost-aware, **no venue call**) → `check_resolutions()` books realized
  PnL when markets settle. Doubly gated: refuses to run if `LIVE_TRADING_ENABLED` is true, and uses
  the dry-run executor. → validates `paper_trading_forward` (the "live validation with paper money").

## Owner steps (one-time)

1. Add the workflow below as `.github/workflows/live-validation.yml`.
2. (For a **durable** forward track record) add `DATABASE_URL` (your Neon connection string) as a repo
   **Actions secret** so the paper cycle persists to Neon across runs. *This is the DB string, NOT a
   trading key.* Without it the cycle still runs but writes to an ephemeral SQLite that resets each run.
   **Never add Polymarket trading keys (`POLYMARKET_*`) — real orders are human-core, never in CI.**
3. `GEMINI_API_KEY` (already in secrets) is consumed here for the real Gemini smoke.

### Staged workflow (copy verbatim)
```yaml
name: live-validation          # NON-BLOCKING — never a required check; external outages must not freeze merges
on:
  schedule:
    - cron: "23 */6 * * *"     # every 6h — accumulate a forward paper track record
  workflow_dispatch:
jobs:
  live-smoke-and-paper:
    runs-on: ubuntu-latest      # GitHub runners have open internet -> reach Gemini + Polymarket
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r backend/requirements.txt   # full runtime (not the light CI gate set)
      - name: Live integration smoke (real Gemini + real Polymarket)
        run: python scripts/live_integration_smoke.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      - name: Forward paper cycle on REAL markets (paper fills only; never places a real order)
        run: python scripts/run_paper_cycle.py --json
        env:
          LIVE_TRADING_ENABLED: "false"          # belt-and-suspenders; the runner also refuses if true
          DATABASE_URL: ${{ secrets.DATABASE_URL }}   # optional; durable Neon persistence for the forward record
```

Notes:
- **Non-blocking by design:** this workflow is NOT added to `required_status_checks`. The required gate
  stays the deterministic `code + safety gate (blocking)`. So a Polymarket/Gemini outage reports here
  but never blocks a merge.
- **Fuller alternative:** the deployed backend (Railway) running the orchestrator loop continuously is
  the always-on version of the paper cycle (it has `DATABASE_URL` + internet). This scheduled job is the
  no-always-on-deploy path; both are honest. (Deploy status is owner-scope — see OA-10.)
- **Safety recap:** public data needs no creds; the paper cycle can't place a real order (dry-run + the
  `LIVE_TRADING_ENABLED` gate + a runner-level refusal, all enforced); PnL is only booked on real
  resolution (no fabricated numbers).
```
