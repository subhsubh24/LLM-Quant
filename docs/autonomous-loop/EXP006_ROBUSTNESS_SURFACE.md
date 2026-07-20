# EXP-006 fade-the-spike — pre-registered config ROBUSTNESS SURFACE (2026-07-20)

> **Verdict: `FAMILY-NULL-STRONG` — 0 of 60 pre-registered cells validate.** The first
> real-data EXP-006 run (#390) reported EDGE-NOT-PROVEN at the DEFAULT config; this surface
> answers the next filed question — *is that null a fluke of the default knobs, or
> config-family-wide?* — and the answer is **config-family-wide, leaning negative.** Wherever
> the fade has enough trades to be testable (N ≥ 100) it is at best indistinguishable from
> zero and is more often **significantly NEGATIVE**; the only positive point estimates are
> **underpowered** (N < 100). **No edge is claimed and none exists here.**

## What this is (and what it is NOT)

A pre-registered sweep of the leakage-safe, cost-net, F10/F11-gated `backtest_fade_the_spike`
engine over a fixed **60-cell grid** (threshold × window × horizon), run on the SAME committed
corpus (`data/spike_corpus_politics.json.gz`, 255 markets / 496,056 hourly ticks). Every cell
is reported; none is selected.

- **IN-SAMPLE by construction.** It reuses the single committed corpus, so it is a
  *within-sample config-sensitivity map*, **not** an out-of-sample test. **No cell can be a
  validated edge, however green** — an in-sample sweep that finds a green cell has, by
  definition, searched for it. Selecting the greenest cell and calling it an edge is p-hacking
  and is refused by the tool.
- Its only legitimate conclusions: (a) whether the default's EDGE-NOT-PROVEN is config-fragile
  or config-family-wide (answered: **family-wide**), and (b) whether any region merits a FRESH
  pre-registered OOS on genuinely NEW data (one underpowered candidate flagged below).
- It reaches **no revenue field** and sets **no validated-edge flag** at the family level.

## Pre-registered grid (bracketing the default 0.10 / 1h / 24h; not tuned on any result)

- **threshold** ∈ {0.05, 0.08, 0.10\*, 0.15, 0.20}  (absolute probability move to trigger)
- **window** ∈ {30m, 1h\*, 2h, 6h}  (spike-detection window)
- **horizon** ∈ {6h, 12h, 24h\*}  (reversal horizon; **all ≤ the 24h default** so the engine's
  horizon-axis F10 exclusion — legitimate only while the horizon is structurally single-valued,
  ≤ 1 day — applies fairly to every cell)

`max_trades_per_market = 1` (the honest per-market concentration cap) and `$100`/trade fixed
for every cell. Category labels (`data/spike_corpus_politics_cats.json`) are passed through, so
the F10 **category** axis engages — a *stricter* fragility check than the headline #390 run,
which omitted categories. (\* = the pre-registered DEFAULT cell.)

Reproduce (deterministic — seeded engine, sorted iteration; same corpus + grid ⇒ identical):

```
python3 scripts/run_spike_robustness_surface.py \
  --data data/spike_corpus_politics.json.gz \
  --category-data data/spike_corpus_politics_cats.json
```

## Family summary

| metric | value |
|---|---|
| cells | 60 |
| **cells validating `is_validated_edge`** | **0** |
| F11 `significant_positive` | **0** |
| F11 `significant_negative` | **18** |
| F11 `indistinguishable_from_zero` | 12 |
| F11 `insufficient_data` (N < 100 floor) | 30 |
| cells with positive net PnL | 14 |
| cells with N ≥ 100 (powered) | 33 |
| net-PnL range across cells | **−$2,257 … +$1,198** (median −$64) |
| chance-green expectation (≈ K·α/2, conservative) | 1.5 |
| **family verdict** | **`FAMILY-NULL-STRONG`** |

**The load-bearing pattern:** every one of the 14 positive-PnL cells is either underpowered
(N < 100 → F11 `insufficient_data`) **or** F10-fragile; **no powered cell (N ≥ 100) is F11
significant-positive**, while **18 powered cells are significant-NEGATIVE**. The positive
region is entirely the high-threshold / 1h-window corner where the fade takes too few trades to
clear the pre-registered 100-event floor. Widening the window (2h/6h) recruits more spikes, but
they do not revert — the two-way cost hurdle then drives the total significantly negative.

## Full surface (all 60 cells — report-all, select-none)

| thr | win | hor | N | net PnL | hit | F11 | F10 fragile | valid |
|-----|-----|-----|---|---------|-----|-----|-------------|-------|
| 0.05 | 30m | 6h | 0 | 0 | – | insufficient | – | False |
| 0.05 | 30m | 12h | 0 | 0 | – | insufficient | – | False |
| 0.05 | 30m | 24h | 0 | 0 | – | insufficient | – | False |
| 0.05 | 1h | 6h | 152 | −1,296 | 0.33 | significant_neg | False | False |
| 0.05 | 1h | 12h | 152 | −1,080 | 0.37 | significant_neg | False | False |
| 0.05 | 1h | 24h | 152 | −1,355 | 0.38 | significant_neg | False | False |
| 0.05 | 2h | 6h | 169 | −1,690 | 0.36 | significant_neg | False | False |
| 0.05 | 2h | 12h | 169 | −2,004 | 0.34 | significant_neg | False | False |
| 0.05 | 2h | 24h | 169 | −1,687 | 0.37 | significant_neg | False | False |
| 0.05 | 6h | 6h | 177 | −1,907 | 0.29 | significant_neg | False | False |
| 0.05 | 6h | 12h | 177 | −2,257 | 0.27 | significant_neg | False | False |
| 0.05 | 6h | 24h | 177 | −1,959 | 0.32 | significant_neg | False | False |
| 0.08 | 30m | 6h | 0 | 0 | – | insufficient | – | False |
| 0.08 | 30m | 12h | 0 | 0 | – | insufficient | – | False |
| 0.08 | 30m | 24h | 0 | 0 | – | insufficient | – | False |
| 0.08 | 1h | 6h | 121 | −93 | 0.45 | indistinguishable | False | False |
| 0.08 | 1h | 12h | 122 | −109 | 0.49 | indistinguishable | False | False |
| 0.08 | 1h | 24h | 122 | −69 | 0.52 | indistinguishable | False | False |
| 0.08 | 2h | 6h | 142 | −1,305 | 0.39 | significant_neg | False | False |
| 0.08 | 2h | 12h | 143 | −1,631 | 0.38 | significant_neg | False | False |
| 0.08 | 2h | 24h | 143 | −1,462 | 0.37 | significant_neg | False | False |
| 0.08 | 6h | 6h | 153 | −1,346 | 0.37 | significant_neg | False | False |
| 0.08 | 6h | 12h | 154 | −1,725 | 0.35 | significant_neg | False | False |
| 0.08 | 6h | 24h | 154 | −1,550 | 0.36 | significant_neg | False | False |
| 0.10 | 30m | 6h | 0 | 0 | – | insufficient | – | False |
| 0.10 | 30m | 12h | 0 | 0 | – | insufficient | – | False |
| 0.10 | 30m | 24h | 0 | 0 | – | insufficient | – | False |
| 0.10 | 1h | 6h | 107 | 331 | 0.53 | indistinguishable | **True** | False |
| 0.10 | 1h | 12h | 108 | 454 | 0.55 | indistinguishable | **True** | False |
| **0.10\*** | **1h** | **24h** | **108** | **285** | **0.58** | **indistinguishable** | **True** | **False** |
| 0.10 | 2h | 6h | 128 | −624 | 0.47 | indistinguishable | False | False |
| 0.10 | 2h | 12h | 129 | −847 | 0.46 | indistinguishable | False | False |
| 0.10 | 2h | 24h | 129 | −825 | 0.46 | indistinguishable | False | False |
| 0.10 | 6h | 6h | 141 | −816 | 0.47 | significant_neg | False | False |
| 0.10 | 6h | 12h | 142 | −1,181 | 0.44 | significant_neg | False | False |
| 0.10 | 6h | 24h | 142 | −1,263 | 0.37 | significant_neg | False | False |
| 0.15 | 30m | 6h | 0 | 0 | – | insufficient | – | False |
| 0.15 | 30m | 12h | 0 | 0 | – | insufficient | – | False |
| 0.15 | 30m | 24h | 0 | 0 | – | insufficient | – | False |
| 0.15 | 1h | 6h | 78 | 518 | 0.58 | insufficient | **True** | False |
| 0.15 | 1h | 12h | 79 | 843 | 0.58 | insufficient | **True** | False |
| 0.15 | 1h | 24h | 79 | **1,198** | 0.59 | insufficient | **True** | False |
| 0.15 | 2h | 6h | 104 | −381 | 0.54 | indistinguishable | False | False |
| 0.15 | 2h | 12h | 105 | −236 | 0.50 | indistinguishable | False | False |
| 0.15 | 2h | 24h | 105 | −208 | 0.50 | indistinguishable | False | False |
| 0.15 | 6h | 6h | 117 | −543 | 0.50 | indistinguishable | False | False |
| 0.15 | 6h | 12h | 118 | −227 | 0.54 | indistinguishable | False | False |
| 0.15 | 6h | 24h | 118 | −257 | 0.51 | indistinguishable | False | False |
| 0.20 | 30m | 6h | 0 | 0 | – | insufficient | – | False |
| 0.20 | 30m | 12h | 0 | 0 | – | insufficient | – | False |
| 0.20 | 30m | 24h | 0 | 0 | – | insufficient | – | False |
| 0.20 | 1h | 6h | 56 | 859 | 0.55 | insufficient | **True** | False |
| 0.20 | 1h | 12h | 57 | 785 | 0.56 | insufficient | **True** | False |
| 0.20 | 1h | 24h | 57 | −64 | 0.47 | insufficient | False | False |
| 0.20 | 2h | 6h | 83 | 218 | 0.52 | insufficient | **True** | False |
| 0.20 | 2h | 12h | 84 | 448 | 0.49 | insufficient | **True** | False |
| 0.20 | 2h | 24h | 84 | 377 | 0.51 | insufficient | **True** | False |
| 0.20 | 6h | 6h | 95 | 16 | 0.47 | insufficient | **True** | False |
| 0.20 | 6h | 12h | 96 | 130 | 0.52 | insufficient | **True** | False |
| 0.20 | 6h | 24h | 96 | 275 | 0.56 | insufficient | **True** | False |

## Honest reading

1. **The fade-the-spike mechanism is refuted across the config family, not just at the
   default.** This is a strictly stronger statement than #390's single-cell null: the default
   sits in the small indistinguishable-from-zero band, and moving in any powered direction only
   makes it worse (significantly negative). EXP-006 joins the bucket-calibration family as
   **refuted on real data** — now config-family-wide.

2. **One underpowered hypothesis, flagged NOT claimed.** The high-threshold / 1h-window corner
   (thr 0.15–0.20) shows positive point estimates at ~0.55–0.59 hit. Unlike the earlier
   *magnitude-stratum* carve-out (post-hoc — `|peak−baseline|` is not knowable at decision
   time), the **detection threshold IS a decision-time parameter**, so "fade only spikes ≥ a
   high threshold" is a legitimately pre-registrable variant. **But on this corpus it is
   underpowered** (N = 56–96, all below the 100-event floor → F11 `insufficient_data`) and
   several such cells are also F10-fragile. It is therefore **a candidate for a FRESH,
   pre-registered OOS on new/larger data — NOT an edge, and not tradeable on this evidence.**
   Filed to ROADMAP as an EXP-006b candidate, distinct from the EXP-007 momentum idea.

3. **No selection, no revenue field.** The surface computes a conservative chance-green
   expectation (≈1.5 cells green by luck at K=60), but that guard is moot here — zero cells
   validate. Nothing here reaches `weekly_pnl_paper` / `total_trades`; `business_case_strength`
   stays **B**; `engine_pct` unchanged.

## Binding constraint

**Unchanged: `business_case_strength = B`, no validated real-money OOS edge on any tested
mechanism.** Both real-money mechanisms tested to date are refuted on real data —
bucket-calibration (EXP-002/003/005 + the #388 cap variant) and now EXP-006 fade-the-spike
(config-family-wide). An honest config-family-wide null with the specific next step filed IS a
value-bar-clearing result, not a failure.
