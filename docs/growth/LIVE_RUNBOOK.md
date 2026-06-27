# LIVE RUNBOOK — going to real money (OWNER-ONLY)

> **Read this end-to-end before doing anything.** Every step here is **HUMAN-CORE** —
> the autonomous loop will never perform any of it. The loop builds and validates the
> entire live path in **paper/mock** mode; **you** fund, set live keys, and flip the
> switch.
>
> **Default state is safe:** `LIVE_TRADING_ENABLED=false`. With it false, no real
> order can be placed regardless of any other setting.

This runbook is exact about **env var names** and **order of operations**. Where it
references a venue portal or legal point, **verify the current details yourself** —
URLs, ToS, and eligibility change, and this document cannot be authoritative on law.

---

## §1. Confirm venue ToS + jurisdiction eligibility  (OA-2 — do this FIRST)

Real-money prediction-market trading is **legally restricted in some jurisdictions**
and some venues prohibit automated trading. Before anything:

1. Read the current Terms of Service for your venue(s):
   - Polymarket: https://polymarket.com (review ToS + any automated-access policy)
   - Kalshi: https://kalshi.com (review ToS; Kalshi is a US-regulated exchange)
2. Confirm **your jurisdiction** permits you to trade on the venue. If unsure, get
   advice. **Do not work around venue geo/eligibility rules.**
3. Write down your decision (date, venue, jurisdiction conclusion). If the answer is
   "not eligible," **stop here** — the bot stays paper-only.

> This is a legal/eligibility judgment reserved entirely to you. The loop will flag it
> but will never make this call.

---

## §2. Create / verify the venue account + KYC  (OA-3)

1. Create the account on your chosen venue.
2. Complete KYC/identity verification as required.
3. Confirm the account is in good standing and permitted to trade.

---

## §3. Deposit / transfer real funds  (OA-4)

1. Fund the account per the venue's supported method (e.g. USDC for Polymarket;
   USD for Kalshi). Follow the venue's official deposit flow.
2. **Start small** — fund only what you are willing to lose while validating live.
3. Record the starting bankroll; you will set caps relative to it in §4.

---

## §4. Set the HARD caps + verify the kill switch  (OA-1 — before any live capability)

Set these **server-side env vars** (never commit them). Defaults in code are
conservative; you set the real ceilings:

| Env var | Meaning | Suggested start |
|---------|---------|-----------------|
| `MAX_PER_TRADE_USD` | Hard cap on any single order | small (e.g. 1–2% of bankroll) |
| `MAX_DAILY_LOSS_USD` | Auto-trip kill switch if daily net loss exceeds this | small |
| `MAX_TOTAL_LOSS_USD` | Auto-trip kill switch if cumulative net loss exceeds this | small |
| `LLM_SPEND_CAP_USD` | Cap on model/provider spend (research + factory) | your budget |

Then **verify the kill switch actually halts trading**:
- Run the kill-switch / loss-cap test (see `scripts/preflight.sh` and the runtime
  harness). Confirm that when a cap is tripped, **no further orders are placed**.
- Confirm the manual kill switch (`activate_kill_switch`) blocks orders immediately.

**Do not proceed to live keys until the caps + kill switch are verified.**

---

## §5. Set venue LIVE API keys in server env  (OA-5)

1. Generate **live** API credentials on the venue.
2. Set them **server-side only**, never in git:
   - Polymarket (example names — confirm against the client in
     `backend/app/prediction_markets/polymarket_client.py`): `POLYMARKET_API_KEY`,
     `POLYMARKET_API_SECRET`, `POLYMARKET_PASSPHRASE`, `POLYMARKET_WALLET_*` as
     applicable.
   - Kalshi (if used): the venue's live key/secret env vars.
3. Confirm `.env` is gitignored (it is) and that keys are not echoed into logs.

---

## §6. Flip `LIVE_TRADING_ENABLED` on  (OA-6 — the master gate)

Only after §1–§5 are done and the bot has been **validated in paper**:

```bash
# server-side env, never committed
export LIVE_TRADING_ENABLED=true
```

With the gate on **and** `dry_run=false`, the **same code paths** that ran in paper
now place real orders, subject to the §4 caps and the kill switch. Start with the
smallest size. Watch the monitoring panel.

To go back to safe mode at any time: set `LIVE_TRADING_ENABLED=false` (or hit the
kill switch). This blocks all real orders immediately.

---

## §7. Monitoring, scaling, stopping  (ongoing)

- **Monitor:** the TypeScript panel shows paper + live PnL, open positions,
  calibration, and the kill switch. Every number is real or absent — never a stub.
- **Scale up slowly:** raise caps only after live results match paper expectations
  over a meaningful sample. **Raising caps is owner-only.**
- **Stop / withdraw:** hit the kill switch or set `LIVE_TRADING_ENABLED=false`, then
  withdraw funds via the venue's official flow.

### CI wiring (OA-8, maintainer scope)
Add a workflow that runs `scripts/preflight.sh` on PRs so the gate stays green. The
loop will not edit `.github/`; this is your action.

---

## The boundary (restated)

The loop **builds and paper-validates** this entire path. **You** do §1–§7. The loop
never funds, never sets live keys, never flips `LIVE_TRADING_ENABLED`, never raises a
cap, and never makes the legal call.
