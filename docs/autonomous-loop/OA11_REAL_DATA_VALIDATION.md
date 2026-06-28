# OA-11 — real-data OOS validation: what running the fetcher actually showed

**Date:** 2026-06-28 · **Status:** egress-from-permitted-host PROVEN; pipeline validated on
REAL data; the floor box stays blocked — but the binding constraint has MOVED.

## What OA-11 asked

The autonomous build env blocks outbound HTTPS to Polymarket (403 at the proxy), so the
leakage-safe history fetcher could never run against real data *there*. OA-11: run it where
Polymarket is reachable and feed real resolved-market history into the walk-forward + the
calibration eval, so a real out-of-sample result can exist.

## What was done (real run, from a network-permitted host)

1. **Confirmed reachability.** `gamma-api.polymarket.com` + `clob.polymarket.com` return
   HTTP 200 from a permitted host. The egress block is environment-specific (the cloud
   routine), not universal.
2. **Built a reusable driver** — `scripts/fetch_polymarket_history.py` — so any
   network-permitted run (owner, or a permitted CI job) can refresh the dataset.
3. **Fixed a real fetcher defect found only by running it.** `fetch_resolved_markets`
   defaulted to `order=endDate`, which surfaces **never-traded junk** — markets closed early
   with a far-future `endDate` and an EMPTY CLOB price history (every one skipped by the
   anti-leakage guard for lack of a pre-decision tick → **0 records**). Added an `order`
   param; `order=volumeNum` harvests markets that actually traded. With it: **54 real
   leakage-safe records** from 100 candidates (46 correctly skipped — no honest pre-decision
   tick). Disclosed the new liquidity-selection bias this introduces.
4. **Ran the pipeline on the real data — it reproduces deterministically** (seed 42 →
   `seed_hash 8dc358439ffb5746`). Committed the snapshot at
   `data/polymarket_history_sample.json`.

## The headline finding (this is the value, not a PnL number)

On the **most-liquid recently-resolved** Polymarket markets, sampling the decision **2 days
before resolution**:

| metric | value | meaning |
|---|---|---|
| records | 54 | real, leakage-safe |
| crowd Brier | **0.093** | the crowd is **very sharp** (0 = perfect, 0.25 = coin-flip) |
| price-pinned (<0.05 / >0.95) | **70%** | most markets had already near-resolved 2 days out |
| YES base rate | 0.26 | — |
| walk-forward trades | **0** | `model_prob == crowd` → no edge → no bet (correct) |

Raising the decision lead to 5 and 7 days kept the **same ~54 markets still ~70% pinned** —
these liquid markets pinned to near-certainty *early*. At 14 days, zero qualified (no trading
that far out).

## Why the floor box still does NOT tick — and what the real blocker now is

Unblocking egress was necessary but **not sufficient**. The data shows two things:

1. **The crowd is well-calibrated where the easy data lives.** On liquid markets near
   resolution there is little decision-time uncertainty to exploit. An edge cannot come from
   *these* points — by the time they have deep CLOB history, they have pinned.
2. **There is no model yet.** `model_prob` is the crowd baseline by construction, so PnL is
   structurally 0. A validated edge needs a real model (ROADMAP **track B**) that forms an
   *independent* decision-time probability, evaluated on markets sampled while **still
   uncertain** (earlier in life / a broader universe than "top-volume, near-resolution").

**So the binding constraint moved from "can't reach the data" → "need (a) a market universe
sampled before it pins + (b) a real alpha model."** That is genuine convergence: a vague
"egress-blocked" wall is now a concrete, prioritized B/A-track problem with real tooling and
a real dataset behind it. No box is ticked because no edge was demonstrated — and inventing
one (e.g. fitting `model_prob` on this same sample) would be leakage/overfitting, which the
honesty bar forbids.

## Residual owner action

The autonomous env still can't refresh this dataset (egress-blocked). To accumulate a real
OOS corpus over time, the fetcher should run on a **network-permitted host** on a schedule
(the backend host, or a permitted CI job). See PENDING_OPS **OA-11**.
