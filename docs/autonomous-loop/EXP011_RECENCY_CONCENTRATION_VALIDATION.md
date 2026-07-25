# EXP-011 — recency-weighted + concentration-capped bucket redesign at a TIGHTER cap parameterization (2026-07-25)

> **Verdict: EDGE-NOT-PROVEN. 0 of 6 cells positive, 0 of 6 F11 `significant_positive`.**
> This is the **third** real-data run of the recency-weighted bucket alpha and the **second**
> cap parameterization of the same 6-cell grid. It **reconfirms** PR #388 and PR #404 at a
> tighter cap setting; it is **not** a first run and **not** a new experiment.

## Read this correction first

An earlier version of this document claimed EXP-011 was the first-ever real-data run of
`recency_weighted_bucket_strategy` and that "nothing was tuned". **A fresh adversarial auditor
proved both claims false**, and they are corrected here rather than quietly dropped:

1. **The strategy had already been run on real data three times**, all recorded in this repo's
   own `RESEARCH_MEMORY.md`:
   - 2026-07-04 (n=799): *"TESTED ONCE ON REAL DATA, REFUTED"* — 108 trades, **−$914.27**
   - PR #388 (2026-07-19), on **this same** frozen 187-market corpus: recency-capped
     `insufficient_data`, **−$3,444**
   - PR #404 (2026-07-22): the **identical 6-cell grid** (both families × uncapped / concurrent
     / cumulative) on this corpus, reaching the same honest-NULL conclusion
2. **Something WAS changed: the cap values.** PR #404 ran `0.20 / 0.40`; this run uses
   `0.10 / 0.30`. That is a researcher degree of freedom and it was not disclosed. It is
   disclosed now. (It does not manufacture a positive — every cell stays negative in both
   parameterizations — but the claim as written was untrue.)

The measured result was never in question; the framing around it was. The numbers below all
reproduce.

## What this run actually adds

A tighter cap parameterization of an already-run grid. That is a modest, incremental
contribution, and it is stated as such. Its real value is negative evidence: **halving both
caps does not rescue the family either.**

| | PR #404 (0.20 / 0.40) | this run (0.10 / 0.30) |
|---|---|---|
| calibration, cumulative-capped | 35 trades, −$3,040.12 | 27 trades, −$1,684.13 |
| recency-weighted, cumulative-capped | 3 trades, −$194.22 | 3 trades, −$142.69 |

## Results — every cell, none selected

```
python3 scripts/validate_real_oos.py \
    --from-corpus data/real_oos_corpus_polymarket.json \
    --decision-lead-days 7 \
    --category-exposure-cap 0.10 \
    --cumulative-category-budget-cap 0.30 --json
```

| family | lane | trades | net PnL | F11 verdict | seed_hash |
|---|---|---:|---:|---|---|
| static calibration (EXP-002) | uncapped | 39 | −$3,228.02 | `significant_negative` | `79a4cca4b966138f` |
| static calibration | concurrent cap 0.10 | 39 | −$3,228.02 | `significant_negative` | `001fa784479fce74` |
| static calibration | cumulative cap 0.30 | 27 | −$1,684.13 | `insufficient_data` | `2e4380ec2cd1f9c6` |
| recency-weighted | uncapped | 21 | −$3,443.79 | `insufficient_data` | `79a4cca4b966138f` |
| recency-weighted | concurrent cap 0.10 | 21 | −$2,855.05 | `insufficient_data` | `001fa784479fce74` |
| recency-weighted | cumulative cap 0.30 | 3 | −$142.69 | `insufficient_data` | `2e4380ec2cd1f9c6` |

Report-all, select-none. The full output is committed alongside this doc as
`EXP011_RESULT.json` (sha256 `782319e340be80c66580d041b247a47fbc825760dacedd2253a42c218e80f536`),
so the artifact is self-reproducible from this branch rather than depending on my shell history.

**Hash caveat, stated because it bit this document once already.** These `seed_hash` values are
the ones this branch produces *today*. The capped hashes (`001fa784479fce74`, `2e4380ec2cd1f9c6`)
**will change** once the `_seed_hash` category-fingerprint fix lands, because that fix makes a
capped hash depend on the category assignment — which is the entire point of it. Trades and PnL
are unaffected: `seed_hash` is a fingerprint, not an RNG seed. An earlier draft of this doc quoted
post-fix hashes it could not reproduce, because the run happened in a checkout carrying that
unmerged branch. Also note `seed_hash` excludes `strategy_fn` by the `walk_forward` contract, so
the two families share a hash per lane — **compare trades and PnL across families, never hashes.**

## Reading these numbers honestly

**Recency-weighting makes it worse.** −$163.99/trade vs the static alpha's −$82.77/trade — a
factor of **1.98**, while being *more* selective. Run 21's diagnosis (that EXP-002's all-time
bucket average is a LAGGING estimate of a time-varying rate) predicted the opposite. Making the
estimate fresher did not help. The per-trade detail is worse than the aggregate suggests: the
recency lane hits **1 of 21** (4.8%) with a median trade of −$225.01, against the static alpha's
5 of 39 (12.8%) and −$76.92.

**Do NOT read the −$142.69 cell as "nearly break-even."** It is **3 trades**. F11's floor is
`min_trades = 30` (`bootstrap_oos_significance.py:96`), so it returns `insufficient_data`
regardless of the point estimate — that verdict means *no information*, not *a small loss*. The
cumulative cap starved the strategy of trades; it did not improve it.

**The concurrent cap did not bind on the static family at all.** `cap_bound: false`, and the PnL
is byte-identical to uncapped at −$3,228.02. So of the two capped lanes only the recency one
loses less, and that is because the cap removed trades — not because capping improved anything.
(An earlier draft said "both capped lanes lose less in absolute terms"; that was wrong for the
static family.)

**Caps are risk controls, not alpha.** On a net-negative signal, capping mechanically shrinks the
loss, and that shrinkage is not evidence of edge.

**The cap test remains vacuous on this corpus, by construction.** A concentration cap can only
change a *verdict* where the signal is net-POSITIVE but F10-fragile. Here the aggregate is
negative before any cap applies, and the engine itself flags `f10_nonfragile_is_vacuous: true` on
all six cells (`validate_real_oos.py:200`: `(not reg.fragile) and total_pnl_usd <= 0.0`).

## What the auditor could NOT break

- **Every cell reproduces to the cent**, and two consecutive runs are byte-identical.
- **No leakage.** `walk_forward.py:490` filters training to `resolution_time < w_start` strictly;
  `MarketView` carries no `outcome`; the recency weight anchors on `view.decision_time` against
  training `resolution_time`, all strictly past.
- **`half_life_days=60` / `min_effective_n=30` were genuinely never tuned.** The module hashes
  **identically at every commit that ever touched it** — those constants have never changed since
  2026-07-04. The p-hacking risk here was the cap values, not the decay constant.
- **Nothing positive is buried.** If anything the null is understated.

## Scope limits

- One corpus, N=187, longshot-heavy (median price 0.037, ~58% pinned), single venue, single
  7.0-day decision lead. This refutes the redesign *on this corpus*; it does not prove no
  recency-weighted calibration edge exists anywhere.
- Trade counts are small (21 and 3 in the recency lanes), so most cells cannot reach F11
  significance in either direction. The two 39-trade static lanes are the only cells with enough
  N for a significant verdict — and both are significantly **negative**.

## NEXT — pre-registered, do NOT p-hack

1. **Stop running cap variants on this corpus.** Two parameterizations now agree, and the test is
   vacuous by construction on a negative signal. The ONE thing that would make it informative is
   a corpus where the bucket signal is net-POSITIVE but F10-fragile (filed as ROADMAP **E8**).
   Further cap sweeps here are uninformative *by construction* and must not be run as if they
   were tests — a third parameterization would be pure researcher degrees of freedom.
2. **EXP-009 step 0** — the Kalshi employment reliability decomposition on a frozen corpus.
3. **B8 step (ii)** — the egress-gated HISTORICAL co-listed BTC/ETH corpus + a common-instant
   dual-venue snapshot, then the dual-venue OOS harness with `require_mechanic_confirmed=True`.

**Do not** re-tune `half_life_days` against this corpus, and **do not** re-sweep the caps. Either
would convert a clean null into a p-hacked positive.
