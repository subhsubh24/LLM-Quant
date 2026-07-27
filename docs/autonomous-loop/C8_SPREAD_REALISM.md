# C8 — What the backtests owe the spread

**Date:** 2026-07-27 · **Status:** run, reproducible offline · **Edge claimed:** none

## The question

Polymarket's CLOB `/prices-history` returns the book **midpoint**, not a traded price. Every
backtest in this repo is built on that series, so every backtest has been entering and exiting
at a price no order could actually get, paying only `DEFAULT_SLIPPAGE_RATE = 0.005` to cross.
The EXP-006b audit filed this as C8 and put it ahead of any new alpha, for a specific reason:
the breakeven cost multiple on that experiment was 5.93x (th=0.15) and 8.33x (th=0.20), and F11
significance was lost at only **1.7x and 2.9x**. A 5x understatement of crossing cost is
therefore not a rounding error on those results — it is the entire verdict.

This run answers the question the filing asked: *when entry and exit pay a measured half-spread,
what survives?*

## What was measured

Two independent live measurements of the real half-spread, both already in the repo:

| source | books | coverage | committed? |
|---|---:|---|---|
| 747 live political books (`EXP006B_RESULT.md`, 2026-07-26) | 747 | prices < 0.30 only | table only |
| depth probe (`data/depth_probe_polymarket.json`, 2026-07-26) | 62 | full [0, 1] | **raw bytes** |

`half_spread.py` carries both as band tables, plus a third `conservative` model that takes the
per-band maximum. `derive_bands_from_depth_probe()` regenerates the depth-probe table from the
committed artifact and a gate test asserts the two agree exactly, so the hand-written table
cannot drift from the bytes it claims to summarize.

Half-spread as a fraction of price, by price band:

| band | 747-book | depth probe (n) | conservative |
|---|---:|---:|---:|
| < 0.01 | 0.167 | 0.1270 (12) | 0.167 |
| 0.01–0.02 | 0.045 | 0.1304 (3) | 0.1304 |
| 0.02–0.05 | 0.025 | 0.1352 (2) | 0.1352 |
| 0.05–0.10 | 0.058 | 0.0667 (3) | 0.0667 |
| 0.10–0.30 | 0.031 | 0.0323 (7) | 0.0323 |
| 0.30–0.70 | — | 0.0100 (8) | 0.0100 |
| 0.70–0.90 | — | 0.0058 (7) | 0.0058 |
| 0.90–0.98 | — | 0.0055 (5) | 0.0055 |
| ≥ 0.98 | — | 0.0005 (15) | 0.0005 |

Against the engine's flat 0.005. Three of the depth-probe bands rest on n=2 or n=3; every band
carries its own `n` so that weakness is visible in the artifact rather than buried in a median.
The 747-book source published only an aggregate sample size, so its bands carry `n: null` — an
invented per-band count would have been the exact fabrication this work exists to remove.

## The result

`python scripts/rescore_with_spread.py` — offline, deterministic, no egress.

### FADE family — EXP-006b, the only nominally positive result this project owns

| cost model | th | N | net PnL | hit | F11 | F11 CI |
|---|---:|---:|---:|---:|---|---|
| flat | 0.15 | 141 | **+$2,441.03** | 58.2% | **significant_positive** | [+364.93, +4736.05] |
| 747book | 0.15 | 141 | +$1,735.96 | 56.0% | indistinguishable_from_zero | [−208.98, +3842.14] |
| depth_probe | 0.15 | 141 | +$1,590.99 | 54.6% | indistinguishable_from_zero | [−349.46, +3707.53] |
| conservative | 0.15 | 141 | +$1,553.14 | 54.6% | indistinguishable_from_zero | [−375.28, +3676.50] |
| flat | 0.20 | 99 | +$2,855.43 | 57.6% | insufficient_data | — |
| 747book | 0.20 | 99 | +$2,263.37 | 56.6% | insufficient_data | — |
| depth_probe | 0.20 | 99 | +$2,125.19 | 54.5% | insufficient_data | — |
| conservative | 0.20 | 99 | +$2,086.54 | 54.5% | insufficient_data | — |

**The th=0.15 cell does not survive.** Its significance goes under the *least* punitive of the
two measurements, not merely the conservative one — the 747-book model alone pushes the CI
across zero. The cell was already F10-fragile (82% of net PnL from one category, 100% from one
horizon bucket); it now fails F11 as well. Hit rate falls from 58.2% to 54.6%, which is the
honest shape of the effect: paying a real spread does not just subtract a constant, it turns
marginal winners into losers.

### BUCKET family — the frozen 187-record OOS corpus

| cost model | N | net PnL | deployed | contracts | wins | F11 | seed_hash |
|---|---:|---:|---:|---:|---:|---|---|
| flat | 39 | −$3,228.02 | $5,691.17 | 1,909,621 | 5 | significant_negative | `77ce67d0eacc552e` |
| 747book | 39 | −$3,204.42 | $5,668.90 | 1,640,241 | 5 | significant_negative | `da0afc9be685b2f4` |
| depth_probe | 39 | −$3,197.83 | $5,661.67 | 1,698,917 | 5 | significant_negative | `d7085adf18b00c39` |
| conservative | 39 | −$3,192.62 | $5,657.10 | 1,639,640 | 5 | significant_negative | `4e973dcce4a4b42b` |

Still refuted under every model, and the flat lane still reproduces the pinned C6 headline
`77ce67d0eacc552e` / −$3,228.02 exactly.

**The loss gets slightly SMALLER under a higher cost, and that is not a bug.** This family holds
to resolution, so a costlier entry does not simply subtract: it shrinks the cost-net edge, which
shrinks the Kelly fraction, which shrinks the position. Same 39 trades, same 5 winners, $34 less
capital deployed and 270,000 fewer contracts held. On a net-losing signal, anything that shrinks
the position shrinks the loss — the same effect ROADMAP E8 already records for the per-category
caps. The harness emits `budget_deployed_usd` and `contracts_held` on every cell so the mechanism
is visible in the artifact rather than left to a reader's charity.

## A defect this run caught in itself

The first version of `CostModel.half_spread_model` was PnL-determining but **not fingerprinted**:
all four bucket cells published `seed_hash 77ce67d0eacc552e` while booking four different PnLs.
That is exactly the collision class the repo fixed for `category` (C6) and `fee_schedule` (#413),
about to ship a third time. `_seed_hash` now covers the model's name and full band table under
the existing added-only-when-set discipline, so every pinned pre-C8 hash stays byte-identical
while the four lanes above separate. Both regression tests were proven to fail on the pre-fix
engine with a genuine same-hash/different-PnL collision (13,129.34 vs 12,975.41).

## What this does and does not establish

It **does** establish that the last nominally significant result in this project does not
survive a measured crossing cost, and that the two families' refutations are cost-model-robust
in the spread dimension as EXP-010 showed they were in the fee dimension.

It **does not** establish an upper bound on the correction. Both measurements are drawn from
open, volume-ordered — i.e. liquid — markets, so they understate a random market's spread. Every
model here is a **lower bound** on real crossing cost. A cell that dies under a lower bound is
dead; a cell that had survived would have needed a fresh adversarial audit before anyone called
it an edge.

Nor does it fix the underlying data problem. The corpus prices are still midpoints. A backtest
that pays a *modelled* half-spread on a *midpoint* series is better than one that pays neither,
but it is still not a series of prices anyone traded at. The real fix is forward capture — record
the book alongside every paper decision (ROADMAP E11) — and that remains the only route to a
corpus where entry and exit are observed rather than estimated.

## Reproduce

```
python scripts/rescore_with_spread.py            # human-readable
python scripts/rescore_with_spread.py --json     # machine-readable, with the band tables
python -m pytest backend/tests/test_half_spread.py
```

No network, no credentials, no money. The verdict line is `EDGE-NOT-PROVEN`, 12 cells scored,
zero survivors under any measured spread model.
