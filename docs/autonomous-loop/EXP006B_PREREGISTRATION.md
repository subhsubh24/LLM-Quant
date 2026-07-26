# EXP-006b — pre-registration (written and committed BEFORE the corpus was fetched)

**Status at time of writing: no data fetched, no result seen.** This file exists so the
config cannot be chosen after the fact. If the run below produces a null, this document is
the evidence that the null was not a discarded first attempt.

## Where this comes from

EXP-006 (fade-the-spike) is **REFUTED family-wide** on the committed corpus
(`data/spike_corpus_politics.json.gz`, 255 markets / 496k ticks): the default config gave
N=108, +$285.44 nominal but F11 `indistinguishable_from_zero` and F10 FRAGILE, and the full
pre-registered 5x4x3 config surface returned **0 of 60 cells validated**, with 18
significantly NEGATIVE.

The robustness-surface run named exactly one legitimate follow-up, and this is it:

> **EXP-006b** — a FRESH pre-registered OOS of the high-threshold (0.15–0.20) fade variant on
> NEW/larger political data (the only underpowered-positive corner; the detection threshold is
> decision-time-knowable so legitimately pre-registrable, unlike the post-hoc magnitude
> carve-out) — do NOT reuse the committed corpus.

Two things make this a legitimate test rather than p-hacking:

1. **The threshold is decision-time-knowable.** A trader can commit to "only fade moves
   >= 0.15" in advance. This is unlike the post-hoc *magnitude* carve-out (small spikes were
   profitable in EXP-006), which is unknowable at decision time and was correctly refused.
2. **The data is disjoint.** The prior corpus's markets are excluded from the universe before
   any tick is fetched, so this is genuinely out-of-sample and not a re-score.

## Hypothesis (falsifiable)

> On political prediction markets NOT used in EXP-006, fading confirmed intraday price spikes
> of magnitude >= 0.15 produces a cost-net positive edge that is statistically significant
> (F11) and non-fragile (F10) at N >= 100.

## Pre-registered corpus

| parameter | value |
|---|---|
| venue | Polymarket (Gamma universe + CLOB ticks, public, no credentials) |
| universe | resolved **binary** markets, Gamma `tag_id=2` (Politics) |
| ordering | `order=volumeNum` (all-time volume) — identical to EXP-006 |
| pages | `--max-pages 8` (EXP-006 used 3) |
| **exclusion** | every market id in `data/spike_corpus_politics_cats.json` (the 255 markets EXP-006 tested), dropped from the universe **before** any tick is fetched |
| tick fidelity | hourly (`fidelity=60`), 15-day chunks |
| window cap | 120 days before resolution |
| leakage margin | 24h — ticks truncated strictly before `resolution_time - 24h` |
| min ticks | 24 |

**Disjointness caveat, stated up front:** the exclusion list is the 255 markets EXP-006
*kept*. EXP-006 fetched 300 and dropped 45 as too thin (<24 ticks) before any spike was
detected. Those 45 are not in the exclusion list, are likely to be dropped again by the same
thin-series filter, and contributed **zero** trades to the EXP-006 result — so their possible
reappearance is not a re-test of tested data. Any that survive this time will be disclosed in
the result.

**Selection-bias caveat:** excluding the top-volume 255 means this corpus is drawn from a
**lower-liquidity stratum** than EXP-006's. That is a real difference between the two samples,
not a neutral resample. It cuts against a naive "EXP-006 replicated/failed to replicate"
reading and must be stated in any conclusion.

## Pre-registered engine config

The **unmodified** `backtest_fade_the_spike` engine at its shipped defaults, varying exactly
one parameter:

| parameter | value |
|---|---|
| `threshold` | **0.15 and 0.20** — the two cells named by the robustness surface. Both reported. |
| `window_seconds` | 3600 (default) |
| `horizon_seconds` | 86400 (default) |
| `budget_per_trade_usd` | 100.0 (default, equal-weight) |
| `max_trades_per_market` | 1 (default — the per-trade concentration cap) |
| `min_trades_for_edge` | 100 (default) |
| `bootstrap_n` / `bootstrap_seed` | 2000 / 12345 (default) |
| cost model | `DEFAULT_COST_MODEL` (default) |

Nothing else is tuned. No parameter is chosen after seeing a number.

## Pre-registered verdict rule

A cell counts as a **validated edge** only if `is_validated_edge` is true, i.e. the AND of:

- N >= 100 trades
- F11 verdict == `significant_positive` (bootstrap 95% CI on total PnL excludes zero, above)
- F10 non-fragile (no concentration flag; includes the large-spike size-robustness screen)
- hit rate > 50%

**Both cells are reported. Neither is selected.** Committed in advance:

- If **neither** cell validates → **EDGE-NOT-PROVEN**, EXP-006b is a null, and the
  fade-the-spike family stays refuted. No revenue field moves, no DoD box ticks.
- If **one** cell validates and the other does not → **EDGE-NOT-PROVEN**. One of two
  neighbouring cells passing is what noise looks like; reporting it as an edge would be
  selecting on the test set.
- If **both** cells validate → a **CANDIDATE**, not an edge. It would then need a further
  independent corpus and >=3 fresh adversarial auditors before any claim, and capacity /
  market impact would still be untested.
- N < 100 in a cell → `insufficient_data` for that cell. Underpowered is not negative and is
  not positive; it is reported as underpowered.

## What this run cannot establish even if it passes

- **Capacity.** The impact path is inert here (the fade engine prices at flat cost and the
  corpus carries no depth), so no capacity or $/week claim can follow from it.
- **Same-event correlation.** Top-volume political markets frequently restate one underlying
  event. `max_trades_per_market=1` caps per market, not per event.
- **Survivorship.** Resolved-only, clean-settlement-only.

Any of these alone blocks a floor claim. This run is a mechanism test, not a profit estimate.
