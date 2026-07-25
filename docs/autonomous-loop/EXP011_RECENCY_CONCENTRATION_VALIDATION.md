# EXP-011 — concentration-capped / recency-weighted bucket redesign: REAL-DATA validation (2026-07-25)

> **Verdict: EDGE-NOT-PROVEN. The Run 21 recommendation is REFUTED on this corpus.**
> The recency-weighted bucket alpha (`prediction_markets.recency_weighted_bucket_strategy`,
> built and pre-registered but **never once run on real data**) was run for the first time
> against the committed frozen Polymarket OOS corpus, alone and under both per-category
> concentration caps. **0 of 6 cells produce a positive edge; 0 of 6 are
> `significant_positive`.** The recency mechanism — hypothesized specifically to *fix*
> EXP-002's lagging all-time average — does not rescue the family. It loses **more** money
> than the static alpha it was meant to improve on.

This is the owner-steer priority #1 experiment: *"the concentration-capped / recency-weighted
CalibrationBucketStrategy REDESIGN — the RESEARCH_MEMORY Run 21 recommendation, testable
directly on the existing corpora."* It required no new data access and no new pipeline.

## Why this was worth running even though the family was already refuted

Run 21's diagnosis was that EXP-002 failed for a *specific, addressable* reason, not because
no calibration edge exists: EXP-002 replaces the crowd price with a bucket's **all-time**
empirical YES-rate, and the true bucket rate appears **time-varying** (the `[0, 0.1)` bucket
resolved YES at 1.0% in the 2024-01→2026-01 training slice but 7.59% in the 2026-01→2026-06
OOS slice). An all-time average is therefore a *lagging* estimate — it replaces the crowd's
live price with a staler number.

Two candidate fixes were named: **recency-weighting** the training set, and **capping
concentration**. Both were built. Neither had ever been tested together on real data. That is
a genuine gap between "mechanism exists" and "mechanism works," and closing it is the point.

## Anti-p-hacking: the parameters were fixed BEFORE this run

`half_life_days = 60` and `min_effective_n = 30` were chosen from first principles and
committed in the module docstring **before any real-data run of this module**, explicitly to
prevent post-hoc tuning. **Nothing was tuned for this run.** The bucket edges, `min_edge`, and
`kelly_fraction` are deliberately identical to EXP-002 so any difference is attributable to
the recency mechanism *alone*.

Only one new degree of freedom (`half_life_days`) exists, and it was fixed in advance. Had
this run come back positive and then been re-tuned, that would be the exact p-hacking
EXP-002's refutation warns against.

## What ran

```
python scripts/validate_real_oos.py \
    --from-corpus data/real_oos_corpus_polymarket.json \
    --decision-lead-days 7 \
    --category-exposure-cap 0.10 \
    --cumulative-category-budget-cap 0.30 --json
```

Fully offline — replays committed bytes, no venue fetch, no egress, no credentials, never
trades. **Deterministic:** two consecutive runs produced byte-identical output
(sha256 `13624a65fc1290b1…`).

Corpus: 187 records, uniform 7.0-day decision lead, YES base rate 0.246, median price 0.037,
~58% pinned. Leakage-safety and biases are documented in
`data/real_oos_corpus_polymarket_meta.json`.

## Results — every cell, none selected

| family | lane | trades | net PnL | F11 verdict | significant edge? |
|---|---|---:|---:|---|---|
| static calibration (EXP-002) | uncapped | 39 | **−$3,228.02** | `significant_negative` | no |
| static calibration | concurrent cap 0.10 | 39 | **−$3,228.02** | `significant_negative` | no |
| static calibration | cumulative cap 0.30 | 27 | **−$1,684.13** | `insufficient_data` | no |
| **recency-weighted (EXP-011)** | uncapped | 21 | **−$3,443.79** | `insufficient_data` | no |
| **recency-weighted** | concurrent cap 0.10 | 21 | **−$2,855.05** | `insufficient_data` | no |
| **recency-weighted** | cumulative cap 0.30 | 3 | **−$142.69** | `insufficient_data` | no |

**Report-all, select-none.** Every cell is listed; no cell is promoted.

## Reading these numbers honestly

**The headline finding.** Recency-weighting makes the result **worse**, not better. Uncapped,
it loses $3,443.79 across 21 trades (−$164/trade) where the static alpha loses $3,228.02
across 39 (−$83/trade) — roughly **twice the loss per trade** while being more selective. The
hypothesis that a staler estimate was the problem is not supported: making the estimate
fresher did not help.

**Do NOT read the −$142.69 cell as "nearly break-even."** It is **3 trades**. F11's floor is
`min_trades = 30`, so it returns `insufficient_data` regardless of the point estimate — that
verdict means *no information*, not *a small loss*. Reading a 3-trade cell as encouraging is
precisely the error the F11 gate exists to prevent. The cumulative cap simply starved the
strategy of trades; it did not improve it.

**Caps are risk controls, not alpha — and this run demonstrates it structurally.** A
per-category cap can only reduce or reallocate exposure; it cannot manufacture PnL. On a
net-negative signal, capping mechanically shrinks the loss, and that shrinkage is *not*
evidence of edge. Both capped lanes lose less in absolute terms while remaining negative.

**The cap test is vacuous on this corpus, by construction.** A concentration cap can only
change a *verdict* where the signal is net-POSITIVE but F10-fragile — i.e. where a real
aggregate edge turns out to be concentrated in one correlated cluster. Here the aggregate is
negative before any cap is applied, so F10 reports `no positive edge to assess for
concentration` and the non-fragile result is explicitly flagged
`f10_nonfragile_is_vacuous: true`. This is a genuine limit on what this run can establish,
and it is the specific gap the next step must close.

## Scope limits

- **One corpus, N=187**, longshot-heavy and single-venue. This refutes the redesign *on this
  corpus*; it does not prove no recency-weighted calibration edge exists anywhere.
- Trade counts are small (21 and 3 in the recency lanes), so most cells cannot reach F11
  significance in either direction. The uncapped static lane (39 trades) is the only cell
  with enough N for a significant verdict — and it is significantly **negative**.
- `seed_hash` is shared across strategies by the `walk_forward` contract (it fingerprints
  data + numeric config, not `strategy_fn`), so **compare trades and PnL across families,
  never hashes.** The capped hashes here (`1aac3013e6f30eff`, `a02c5d2d1fdbe32a`) are the
  post-category-fingerprint values; the cap-free `79a4cca4b966138f` is unchanged.

## Status change

The bucket-calibration family was already refuted under a flat cost model (EXP-002/003/005),
then re-confirmed under Polymarket's real per-category fee (EXP-010). It is now additionally
refuted under its **two named remediation mechanisms**, tested together. The family is closed
absent a materially different corpus or mechanism.

## NEXT — pre-registered, do NOT p-hack

1. **The one buildable thing that would make the cap test non-vacuous:** a corpus on which
   the bucket signal is net-POSITIVE but F10-fragile. Only there can a concentration cap
   change a verdict rather than merely shrink a loss. Until such a corpus exists, further cap
   variants on negative-signal corpora are uninformative by construction and must not be run
   as if they were tests.
2. **EXP-009 step 0** (unchanged, still the filed next econ step): the Kalshi employment
   **reliability decomposition** on a frozen corpus — a raw Brier cannot distinguish crowd
   miscalibration from irreducible outcome noise, so there is no point building a predictor
   until that is settled.
3. **B8 step (ii)** (unchanged): the egress-gated HISTORICAL co-listed BTC/ETH corpus plus a
   common-instant dual-venue snapshot, then the dual-venue OOS coherence harness with
   `require_mechanic_confirmed=True`.

**Do not** re-tune `half_life_days` and re-run against this corpus. That would convert a
clean pre-registered null into a p-hacked positive, and it is explicitly out of bounds.
