# EXP-006b result — EDGE-NOT-PROVEN (F10 category concentration), on the first F11-positive OOS the project has produced

**Verdict: EDGE-NOT-PROVEN.** Both pre-registered cells return `is_validated_edge = false`.
Per the pre-registration's committed rule, that is a **null**, no revenue field moves, no DoD
box ticks, and `business_case_strength` stays **B**.

That said, this null is not the same shape as the previous ones, and the write-up would be
dishonest in the other direction if it buried that. Read the caveats before reading the
numbers.

Pre-registration: [`EXP006B_PREREGISTRATION.md`](EXP006B_PREREGISTRATION.md), committed
before the corpus was fetched.

## The corpus

| | EXP-006 (prior) | **EXP-006b (this run)** |
|---|---|---|
| markets | 255 | **439** |
| ticks | 496,056 | **713,348** |
| universe | Politics `tag_id=2`, `order=volumeNum`, pages 1–3 | Politics `tag_id=2`, `order=volumeNum`, pages 1–8 |
| exclusion | — | the 255 EXP-006 markets, dropped before any tick was fetched |
| **overlap with EXP-006** | — | **0 markets** (verified: set intersection is empty) |

800 fetched → 255 excluded → 545 candidates → 106 dropped as too thin (<24 ticks) → **439
kept**. Committed: `data/spike_corpus_politics_b.json.gz` + `_cats.json` + `_meta.json`.

Category mix: Politics 306, General 119, Economics 12, Crypto 1, Sports 1.

## Results — both cells, neither selected

| | threshold 0.15 | threshold 0.20 |
|---|---:|---:|
| spikes detected | 277 | 159 |
| **trades (N)** | **152** | **109** |
| net PnL | **+$4,268.79** | **+$4,875.27** |
| hit rate | 57.2% | 57.8% |
| **F11 verdict** | **`significant_positive`** | **`significant_positive`** |
| F11 95% CI (total) | [+$512.68, +$9,763.10] | [+$1,043.04, +$10,015.33] |
| **F10** | **FRAGILE** | **FRAGILE** |
| size-robustness screen | passed (large spikes not significantly negative) | passed |
| **`is_validated_edge`** | **false** | **false** |

Both cells clear N ≥ 100, both clear hit-rate > 50%, and both have a bootstrap CI on total PnL
that **excludes zero on the positive side**. Under the pre-registered rule that is still a
null, because F10 fails.

## Why it fails — the blocker is concentration, and it is the same blocker in both cells

| cell | F10 fragility reasons |
|---|---|
| 0.15 | category: **94%** of net PnL from `Politics` (>70%); confidence: 78% from the `0-10%` band (>70%); horizon: 100% `<=1d` |
| 0.20 | category: **89%** of net PnL from `Politics` (>70%); horizon: 100% `<=1d` |

- The **horizon** reason is structural and is correctly excluded by the engine's own gate: a
  single-horizon strategy trivially puts 100% of PnL in one horizon bucket. It is not
  evidence of fragility.
- The **category** reason is the real blocker in both cells, and it is not a technicality: on
  a corpus that is 70% Politics by market count, ~90%+ of the PnL coming from Politics means
  this is a *political-markets* effect, not a demonstrated general one.
- The **confidence-band** reason at 0.15 is the one that should worry us most. 78% of the PnL
  sits in the `0-10%` entry-price band — the longshot region where the entire
  bucket-calibration family (EXP-002/003/005/011) previously died. An effect concentrated
  there deserves more suspicion than an effect spread across the price range, not less.

## The magnitude structure, which cuts both ways

| band | 0.15 cell: N / PnL / hit | 0.20 cell: N / PnL / hit |
|---|---|---|
| 0.15–0.25 | 48 / +$3,158.61 / 83.3% | 16 / +$2,631.54 / 87.5% |
| 0.25–0.40 | 59 / +$1,397.98 / 54.2% | 46 / +$2,019.53 / 65.2% |
| **≥0.40** | **45 / −$287.80 / 33.3%** | **47 / +$224.20 / 40.4%** |

The very largest spikes still **degrade** — hit rate falls to 33–40% and mean reversal
fraction goes **negative** (−0.37 / −0.10), i.e. the biggest moves keep trending rather than
reverting. That is Research Run 21's N=1 caution ("the biggest 2024 political spike did NOT
revert") reproducing as a real gradient across ~90 trades. The profit is concentrated in the
*moderate* 0.15–0.25 band.

Note what this does **not** license: carving out the 0.15–0.25 band post hoc. Magnitude is
knowable at decision time, so unlike the EXP-006 small-spike carve-out it would at least be
*implementable* — but it was not pre-registered here, and selecting it now after seeing the
strata is exactly the p-hack this project has refused three times. If it is worth testing it
must be pre-registered and run on a *third* disjoint corpus.

## Why this differs from EXP-006, honestly

EXP-006 on the top-255 corpus: 0 of 60 config cells validated, 18 significantly **negative**.
EXP-006b on the disjoint next-545: both pre-registered cells F11 significantly **positive**.

Two candidate explanations, and I cannot distinguish them with this run:

1. **The high-threshold corner is real** and EXP-006's default (0.10) diluted it with
   unprofitable small spikes. The robustness surface did flag 0.15–0.20 as the
   underpowered-positive corner, which is why it was the pre-registered follow-up. This would
   be a genuine finding.
2. **The stratum changed.** This corpus is pages 4–8 by volume — a materially
   **lower-liquidity** population than EXP-006's top-255. Fade effects plausibly survive
   longer in less-liquid markets precisely because fewer participants arbitrage them away.
   If so, the effect may be real but **uncapturable at size** — which is a capacity question
   this run cannot answer (see below).

Explanation 2 was pre-registered as a caveat before the fetch, and it is not a
rationalization added after the fact.

## What this run cannot establish, even taken at face value

- **Capacity.** The fade engine prices at flat cost and the corpus carries no depth. Depth at
  a past decision instant is unobtainable from this venue (Gamma serves `liquidity: null` on
  resolved markets; CLOB `/book` 404s on a settled token — both verified live 2026-07-26). So
  **no $/week claim follows from these numbers at all**, and the lower-liquidity-stratum
  hypothesis above makes capacity the *first* thing that would have to be answered.
- **Same-event correlation.** 439 top-volume political markets contain many restatements of
  one underlying event. `max_trades_per_market=1` caps per *market*, and F10's single-market
  check passed — but nothing here caps per *event*. If the 152 trades span far fewer distinct
  events, the effective N is smaller than reported and the CI is too narrow. **This is the
  single most likely way the result is wrong**, and it is not currently measured.
- **Survivorship.** Resolved-only, clean-settlement-only.

## Named next steps (in priority order)

1. **Event-level de-correlation.** Cluster the corpus by underlying event (the B5
   `market_text.content_tokens` / cross-venue matcher machinery already does most of this) and
   re-run with one trade per *event*. If the result survives at event-level N, it gets much
   more interesting; if N collapses, this null is explained and the family stays refuted.
   Buildable now, offline, on the committed corpus.
2. **A non-political corpus.** The category-concentration blocker is only answerable by
   testing whether the effect exists outside Politics. `--tag-id` now exists for exactly this.
3. **Capacity.** Only after 1 and 2, and only with the forward depth-capture path, since
   retrospective depth is unobtainable.

Until at least 1 and 2 clear, this is a **candidate mechanism with a positive OOS signal and
an unresolved concentration problem** — not an edge, and not go-live evidence.

## Reproduction

```bash
python scripts/run_spike_reversal.py \
  --data data/spike_corpus_politics_b.json.gz \
  --category-data data/spike_corpus_politics_b_cats.json \
  --threshold 0.15 --json
# and again with --threshold 0.20
```

Committed raw results: `EXP006B_RESULT_th015.json`, `EXP006B_RESULT_th020.json`.
