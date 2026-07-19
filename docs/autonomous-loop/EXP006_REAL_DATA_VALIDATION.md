# EXP-006 fade-the-spike — REAL-DATA validation (2026-07-19)

> **Verdict: EDGE-NOT-PROVEN.** The EXP-006 fade-the-spike engine
> (`prediction_markets.spike_reversal_backtest`, built + audited-sound #385/#387) was run
> for the FIRST time on a real, point-in-time, non-survivorship intraday-tick Polymarket
> Politics corpus (N=108 trades, above the pre-registered 100-event floor). It is **NOT a
> validated edge** and reaches **no revenue field** — the honest null the last three runs'
> named next-step was blocked on (egress). This closes the "instrument built but untested"
> gap: EXP-006 fade-the-spike now joins the bucket-calibration family as **refuted on real
> data at the pre-registered default config**.

This mirrors `OA11_REAL_DATA_VALIDATION.md` — a committed, reproducible record of a real
egress-gated run, so the finding is durable and re-checkable without re-fetching.

## What ran

- **Corpus builder:** `scripts/fetch_spike_corpus.py` — reuses the audited, leakage-safe
  `PolymarketHistoryFetcher` verbatim; adds only (a) chunked hourly fetch (the CLOB caps
  `fidelity=60` at ~360 ticks / 15 days per request — verified live) and (b) truncation
  strictly before `resolution_time − leakage_margin` so no fade exit can read a settlement pin.
- **Engine:** `scripts/run_spike_reversal.py --data data/spike_corpus_politics.json.gz
  --category-data data/spike_corpus_politics_cats.json` — the unmodified
  `backtest_fade_the_spike`, **pre-registered DEFAULT config** (threshold 0.10, window 1h,
  horizon 24h, `max_trades_per_market=1`, $100/trade). Run ONCE, reported honestly — not swept
  and cherry-picked.
- **Corpus (committed, reproducible offline):** `data/spike_corpus_politics.json.gz` (255
  markets, 496,056 hourly ticks), `..._cats.json`, `..._meta.json` (full provenance).

## Universe (pre-registered, decision-time-observable)

Resolved binary Politics markets (Gamma `tag_id=2` = "Politics", verified live), ranked by
`order=volumeNum`, `max_pages=3` → 300 fetched, 255 kept (45 dropped as <24 pre-settlement
ticks). Each market's tick series is the final ≤120 days before resolution, hourly, truncated
24h before settlement. Selection never consults a spike's forward behavior — the engine detects
spikes causally inside each series.

**Disclosed biases (all pre-registered, all OVERSTATE fade-ability — none is leakage):**
liquidity-selection (`volumeNum`), settled-only survivorship, final-window sampling
(`window_cap_days`), and cross-market same-event correlation is NOT removed (several top-volume
markets are the same event; `max_trades_per_market=1` + F10's single-market check bound
per-market concentration only).

## Result (N=108, deterministic — identical on re-run)

| metric | value |
|---|---|
| markets scanned | 255 |
| spikes detected | 348 (2 unlabelable/dropped) |
| trades / markets | 108 / 108 |
| total PnL | **+$285.44** |
| hit rate | 58.3% |
| **F11 significance** | **indistinguishable_from_zero** (total 95% CI **[−527.30, +1090.61]**) |
| **F10 fragility** | **FRAGILE** — confidence-band 168% + category 107% (both > the 70% gate); leave-one-out: removing the top category leaves **−$19.99 ≤ 0**. (Top-market share is 49.7%, *below* the 70% gate, so single-market is NOT itself a binding failure.) |
| **is_validated_edge** | **False** |

### The magnitude strata confirm Run 21's caution on real data at scale

| \|move\| band | N | net PnL | hit | mean reversion |
|---|---|---|---|---|
| 0.00–0.15 | 30 | +$443.11 | 83% | +0.83 |
| 0.15–0.25 | 35 | +$499.68 | 69% | +0.54 |
| 0.25–0.40 | 24 | −$82.07 | 42% | −0.04 |
| **≥0.40** | **19** | **−$575.28** | **21%** | **−0.09 (COMPOUND)** |

Small spikes partially revert; **the largest spikes (≥0.25, N=43) LOSE −$657 (33% hit) and
compound rather than fade** — the literal Run 21 N=1 caution, now confirmed on N=43 real
large-spike events.

## Why this is EDGE-NOT-PROVEN (three independent reasons, any one sufficient)

1. **Not significant.** The F11 bootstrap CI on total PnL spans zero widely
   ([−$527, +$1,091]) — the +$285 is indistinguishable from noise.
2. **Fragile / concentrated.** F10 fails on the binding informative axes — confidence-band
   (168%) and category (107%), both above the 70% gate — and leave-one-out shows the entire
   positive aggregate lives in ONE category (remove it → −$19.99). (The top-market share,
   49.7%, is below the 70% gate, so single-market concentration is not itself binding here.)
3. **No legitimate carve-out.** The apparent small-spike profit is NOT a tradeable strategy: a
   spike's magnitude band is **not knowable at decision time** (the peak can extend past the
   entry — see `MagnitudeStratum` docstring), so "fade only small spikes" is look-ahead. The
   pre-registered strategy fades ALL confirmed spikes, and that aggregate is the null above.

## Reproduce

```
# offline, from the committed corpus (no egress):
python3 scripts/run_spike_reversal.py \
    --data data/spike_corpus_politics.json.gz \
    --category-data data/spike_corpus_politics_cats.json
# regenerate the corpus from live public data (egress required, deterministic — resolved
# CLOB history is immutable; volumeNum universe is stable over a short window):
python3 scripts/fetch_spike_corpus.py --out /tmp/c.json --cats-out /tmp/cats.json \
    --meta-out /tmp/meta.json --max-pages 3 --window-cap-days 120 --stamp <utc-date>
```

## Binding constraint

**Unchanged: `business_case_strength = B`, no validated real-money OOS edge on any tested
mechanism.** EXP-006 fade-the-spike is now tested on real data and refuted at the default
config. Both real-money mechanisms tested to date (bucket-calibration, fade-the-spike) are
refuted; the play-money Manifold crowd (A8) remains a method-validation target, not real money.

### Next buildable steps (to be filed to ROADMAP / RESEARCH_MEMORY in the companion bookkeeping PR)

1. A pre-registered threshold/window/horizon **robustness surface** on this SAME committed
   corpus (report ALL cells, select none) — does the null hold across the config family, or is
   it default-specific? Cheap, offline, no new data.
2. The large-spike **persistence** direction is the more interesting real signal here (≥0.40
   spikes compound, hit 21%): a *momentum* (ride-the-spike) hypothesis is the inverse of the
   refuted fade — but it must clear the SAME F10/F11 gate and the same not-knowable-at-decision
   caveat, and N=19 is far below the floor. File as EXP-007 candidate, do not claim.
3. B8 dual-venue coherence: Kalshi's `status=settled` feed is 100% high-frequency sports
   (1200 scanned, 0 political); political markets are reachable via `/events?status=settled`
   (carries category) and `/series?category=Politics` (2089 series) — the co-listed universe
   needs an events-by-category → markets-by-event query path added to `KalshiHistoryFetcher`
   plus a common-instant leakage-safe snapshot, before any coherence backtest.
