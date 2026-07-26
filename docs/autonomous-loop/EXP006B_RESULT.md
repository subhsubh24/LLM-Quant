# EXP-006b result — NULL. Fade-the-spike stays REFUTED, and the run found two real defects.

**Verdict: EDGE-NOT-PROVEN.** Neither pre-registered cell validates. No revenue field moves,
no DoD box ticks, `business_case_strength` stays **B**. The fade-the-spike family remains
refuted.

The more useful output of this run is not the verdict but the two defects the adversarial
gate found, both of which affected *every* corpus this project has built:

1. **A settlement-anchor leakage bug** in the resolved-market fetcher. 22% of markets had a
   leakage guard that did nothing, and trades were exiting on venue settlement pins.
2. **A missing horizon-coverage check** in reversal labeling, which let a spike near
   end-of-data exit at whatever the last tick was — typically that same settlement-adjacent
   price.

An earlier draft of this document reported this run as *"the first F11-significant-positive
OOS the project has produced."* **That claim was wrong and has been retracted.** It is
recorded here rather than quietly deleted, because the mechanism that produced it is the
finding.

---

## What the adversarial gate found

Three fresh Opus auditors were run with the mandate *"prove the edge is not real."* Two
returned **BROKEN**.

### Defect 1 — `resolution_time` anchored on `endDate`, not actual settlement

`polymarket_history_fetcher._parse_resolved` resolved `resolution_time` as
`endDate or closedTime`. `endDate` is the **scheduled** end; `closedTime` / `umaEndDate` are
when the market **actually** settled. A market that resolves early keeps its later `endDate`.

Because the CLOB stops emitting ticks at the *actual* close, every downstream guard anchored
on `resolution_time` — including the corpus fetcher's "truncate 24h before resolution" —
became a **no-op** for those markets.

Measured on this corpus: **98 of 439 markets (22.3%)** had series violating the claimed 24h
margin against true settlement. Verified independently against Gamma:

```
market 673598  "Will the government shutdown end November 13?"
  endDate    2025-11-21T00:00:00Z     <- what the fetcher used
  closedTime 2025-11-13T14:37:32Z     <- when it actually settled (8 days earlier)
  corpus last tick: 2025-11-13 14:00  p = 0.9995   (the settlement pin)
  trade: entry 0.045 -> exit 0.9995, +$2,012.77 = 47% of the whole cell
```

That single trade's "reversion" was the market settling 37 minutes later. Six such trades
carried **43.9%** of the reported net PnL.

**Fixed**: `resolution_time` is now `min(closedTime, umaEndDate, endDate)`. `min` is the
conservative choice — it can only move a cutoff *earlier*, never later, so it can never admit
a tick the old behaviour excluded.

### Defect 2 — reversal labeling did not require the horizon to be covered

`label_reversal` returned `None` only when there was *no* later tick at all. It never checked
that the forward horizon was actually **covered**, so a spike near end-of-data was labelled
against whatever the final tick happened to be — a 2-hour hold silently scored as a 24-hour
trade, at a price adjacent to settlement. Seven trades exited on the series' final tick,
carrying 39% of the raw PnL.

**Fixed**: `require_full_horizon=True` (default). If the data does not extend to
`confirm_time + horizon` (within one hour of tolerance), the label is **refused**. This costs
sample size; a fabricated holding period costs correctness.

### Defect 3 (not fixed — it is a property of the data) — the corpus prices are MIDPOINTS

The third auditor established that CLOB `/prices-history` returns the book **midpoint**, not a
traded price — confirmed live (`/prices-history` 0.1965 == `/midpoint` 0.1965, book 0.196 /
0.197) and corroborated by the corpus itself (42.7% of ticks carry 4 decimals, the signature
of a half-tick mid; only 12.6% sit on the 0.01 grid).

So the engine buys and sells at the mid and never pays a spread. Its entire crossing cost is
`DEFAULT_SLIPPAGE_RATE = 0.005`. Measured against 747 live political books, the real
half-spread as a fraction of price is:

| best ask | median half-spread / price | engine assumes |
|---|---:|---:|
| < 0.01 | **16.7%** | 0.5% |
| 0.01–0.02 | 4.5% | 0.5% |
| 0.02–0.05 | 2.5% | 0.5% |
| 0.05–0.10 | 5.8% | 0.5% |
| 0.10–0.30 | 3.1% | 0.5% |

A **5x–33x** understatement, worst precisely in the low-price band that carries most of the
PnL. Breakeven cost multiple is 5.93x (th=0.15) and 8.33x (th=0.20); **F11 significance is
lost at 1.7x and 2.9x**. Under every realistic execution model the auditor built — including
measured VWAP against real books for the engine's own order sizes — **the 0.15 cell is not
significant**.

This is not fixed here because it is not a code bug: it is what the only available historical
price series *is*. It is a hard limit on what any backtest built on this data can claim.

---

## The corrected numbers

Corpus after re-truncation at true settlement: **438 markets, 711,086 ticks**, spanning
2024-03-14 to 2026-07-13. Zero overlap with the EXP-006 corpus (verified). Removing the
leaked ticks removed **0.32% of the data** — and 43% of the result.

| | th=0.15 before | **th=0.15 after** | th=0.20 before | **th=0.20 after** |
|---|---:|---:|---:|---:|
| N | 152 | **141** | 109 | **99** |
| net PnL | $4,268.79 | **$2,441.03** | $4,875.27 | **$2,855.43** |
| hit rate | 57.2% | 58.2% | 57.8% | 57.6% |
| F11 | significant_positive | significant_positive | significant_positive | **insufficient_data** |
| F11 CI | [+513, +9763] | [+365, +4736] | [+1043, +10015] | — |
| F10 | FRAGILE (cat 94%) | FRAGILE (cat 82%) | FRAGILE (cat 89%) | FRAGILE |
| **validated** | false | **false** | false | **false** |

- **th=0.20 now falls below the pre-registered N≥100 floor** (99 trades) → `insufficient_data`.
  Under-powered is neither positive nor negative; it is reported as under-powered.
- **th=0.15 remains F10-fragile** (82% of net PnL in one category) — and, per Defect 3, is not
  significant under any realistic execution model.
- Dropping the **two largest trades** takes th=0.15 to `indistinguishable_from_zero`
  (measured on the corrected corpus: drop-1 is still `significant_positive` but with a CI
  floor of just **+$21.28**; drop-2 gives CI [−289.60, +2955.27]). An earlier draft said
  "the single largest trade" — that was carried over from an auditor's measurement on the
  PRE-fix corpus and is corrected here to the post-fix number.

The "after" column applies **both** fixes (settlement anchor + horizon coverage). Applying
only the anchor fix — which is what two auditors independently measured — gives N=148 /
+$2,423 and N=104 / +$3,078; the horizon guard accounts for the remaining difference. Both
corrections are real and both are shipped, so the joint figures are the ones that stand.

### The scale, which the earlier draft omitted

The corpus spans **121.7 weeks**. $2,441.03 over that period is **$20.06 per week**, against
a floor of **$2,000/week**. That is **1% of the floor**. Quoting `+$2,441` without the
timespan made a two-year trickle read like a result; the auditor was right to call that out.

Reaching the floor would need ~100x the size. At $5,000/trade in the 0.02–0.05 price band,
measured round-trip friction against real books is **330%–1144% of entry price**. There is no
size at which this is a business.

## Other audit findings worth recording

Several of these correct claims **I** made. They are listed as corrections, not as
observations I happened to agree with.

- **"Both cells" was ~one test, not two.** On the corrected corpus, **83 of the 0.15 cell's
  141 trades are identical in the 0.20 cell** (same market, same confirm instant, same PnL to
  1e-9), carrying **96.0%** of the 0.15 total. (An earlier draft said "90 trades / 99.8%",
  measured on the PRE-fix corpus; corrected to the post-fix figures.) The pre-registration's "if both cells validate → CANDIDATE" rule implicitly treated
  them as independent confirmations. They are one result reported twice, and any future
  pre-registration in this family must pick non-nested cells.
- **There is no "high-threshold corner."** A threshold sweep on this corpus returns
  `significant_positive` at 0.10, 0.12, 0.13, 0.14, 0.16, 0.17, 0.18 and 0.19 — including
  the 0.10 default that was *refuted* on the old corpus. (0.22 is **`insufficient_data`**,
  N=93 — an earlier draft listed it as significant_positive, measured pre-fix; corrected.) So the pre-registered mechanism
  (that the high-threshold corner is special) is **not** what is going on; whatever differs,
  differs at the corpus level.
- **Single-observation dominance is the real statistical fragility — not event correlation.**
  I had named same-event correlation as "the single most likely way this result is wrong."
  Measured, that was **wrong**: 152 trades span 110–113 event clusters, but the design effect
  is only 1.11–1.15 and *every* clustering (event, week, month, quarter) keeps the CI above
  zero, because the dominant PnL sits in singleton clusters. What actually breaks it is
  concentration in a handful of trades: on the corrected corpus, **dropping the single
  largest trade** moves the 0.15 cell to indistinguishable, and the top 10 trades of ~150
  carry the entire result in both cells.
- **The lower-liquidity-stratum hypothesis is REFUTED.** I offered it as one of two
  explanations. PnL by volume quintile is non-monotone and the *least* liquid quintile earns
  ~zero/negative in both cells. Removed as an explanation rather than left standing.
- **The F10 single-market gate passed by 2.8 points** (`top_market_pnl_share` 0.4715 vs a 0.50
  threshold) — and it passed *because of* a leaked trade. A gate that clears by that margin
  on contaminated data is not evidence of robustness.
- Spike detection itself is **causal and unbroken**: re-running detection on the prefix
  `t <= confirm_time` for all 277 spikes disagreed on zero. It also survived an
  entry-price-matched random-trading placebo and a direction-randomization test.
- The shipped F11 percentile bootstrap is **conservative, not anti-conservative**, on this
  payoff shape: a 600-replication placebo calibration returned `significant_positive` 0.0–0.2%
  of the time against a 2.5% nominal. The method is sound; the data was not.
- Pre-registration integrity verified independently from git timestamps: the prereg was
  committed ~11 minutes before the corpus existed, and no engine or gate code changed between
  prereg and result.
- Disjointness holds: zero market overlap; no N inflation from duplicate series.

**One pre-registration promise unmet:** the prereg said any of EXP-006's 45 thin-dropped
markets that survived this fetch would be disclosed. The exclusion list was the 255 *kept*
markets, so the 45 were not tracked and this cannot be recovered from the committed
artifacts. Recorded as unmet rather than quietly dropped.

## What ships from this run

- The two fixes above, with regression tests.
- A fetch-time assertion so a corpus that violates its own leakage margin **fails loud**
  instead of being committed with a false disclosure.
- The re-truncated corpus + a `close_times` sidecar recording the true settlement instant used
  for every market, so the truncation is auditable without a re-fetch.

## Effect on prior results

The `endDate` anchor bug affected **every** corpus this fetcher built, including EXP-006's and
the frozen real-OOS corpus. Both of those concluded **negative/refuted**, and leakage of this
shape (exits on settlement pins) inflates PnL *upward* — so it can only have made those
results look **better** than they were. Their refutations therefore stand a fortiori. No
published negative conclusion is overturned by this fix, and I have not re-run them.

## Named next steps

Ordered by measured importance, which is **not** the order I first guessed.

1. **A spread-aware cost model — the binding methodological constraint.** Every backtest in
   this repo prices at the CLOB midpoint and pays a flat 0.5% for crossing, against real
   half-spreads of 2.5–16.7% at the prices that carry the PnL. Until entry and exit pay a
   measured half-spread at the traded price level, no result in this family means much. This
   ranks ahead of any new alpha.
2. **A concentration gate on single-observation dominance.** F10 has no axis that catches
   "one trade of 148 carries the result." Drop-top-k or a winsorized-PnL check would have
   flagged both cells immediately, and would have flagged EXP-006 too.
3. **Re-run EXP-006 on the original corpus with both fixes**, to confirm the refutation is
   unchanged rather than assume it.
4. Cap trades per *event cluster* rather than per market — worth doing for correctness, but
   **demoted**: the measured design effect is only 1.11–1.15, so this was not the problem.

## Reproduction

```bash
python scripts/run_spike_reversal.py \
  --data data/spike_corpus_politics_b.json.gz \
  --category-data data/spike_corpus_politics_b_cats.json \
  --threshold 0.15 --json     # and again with --threshold 0.20
```

Committed raw results: `EXP006B_RESULT_th015.json`, `EXP006B_RESULT_th020.json`
(corrected run). Pre-registration: `EXP006B_PREREGISTRATION.md`, committed before the fetch.
