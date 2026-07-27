# Capacity analysis — the first real measurement of what this bot's own order costs

Closes the `backtest_integrity` residual (b) the Quality Scorecard has carried for several
cycles: *"`DEFAULT_IMPACT_COEFF=0.5` remains an uncalibrated placeholder AND the
market-impact path is inert on every committed artifact, so market-impact and capacity are
untested on real data and no capacity curve exists."*

Two findings, one of which corrects the scorecard's own proposed fix.

---

## Finding 1 — the `liquidity: null` on every OOS record is NOT a fetcher bug

The scorecard, and a scout survey this run, both read the situation as "the fetcher parses
Polymarket's `liquidity` field and drops it before building `HistoricalMarket`" — i.e. a
threading bug with a one-line fix. **That is wrong**, and shipping that "fix" would have
threaded a look-ahead value into the backtest.

Verified live against the public API on 2026-07-26:

| probe | result |
|---|---|
| Gamma `/markets?closed=true`, 5 highest-volume resolved Politics markets (ids 253591, 253597, 511754, 253642, 601697) | `liquidity`, `liquidityNum`, `liquidityClob` — **all null** |
| CLOB `/book?token_id=…` on a resolved market's token | **HTTP 404** |
| Gamma `/markets?closed=false`, open markets | `liquidity` populated (e.g. 883,678.27) |
| CLOB `/book` on an open market's token | real ladder, 19 bid / 104 ask levels |

**The venue does not retain depth for settled markets.** Depth at a past decision instant is
unobtainable after the fact, so no amount of fetcher plumbing recovers it — and Gamma's
`liquidity` on a *resolved* market would in any case be a post-resolution value, i.e. exactly
the look-ahead the leakage guard exists to prevent.

Consequence: retrospective capacity testing on the committed corpora is **impossible**, not
merely unbuilt. The buildable path is forward capture — record depth at decision time from
now on — which `scripts/capacity_probe.py` is the first half of.

---

## Finding 2 — `DEFAULT_IMPACT_COEFF = 0.5` is wrong in *both* directions, and no single value is right

Since depth *is* observable on open markets, the coefficient is calibratable **now**. New
`capacity.walk_book()` fills an order against a real captured ask ladder and reports what it
truly cost — **no model parameter involved**. `implied_impact_coeff()` then inverts
`impact = coeff · √(size/depth)` against that measurement.

Run over the **62** ask ladders in the committed artifact
(`data/depth_probe_polymarket.json`, captured 2026-07-26). Every number in this document is
recomputed from that committed file:

| order | n | books exhausted | realized impact: median | p90 | implied coeff: median | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| $100 | 62 | 0 | **0.000%** | 11.1% | **0.0000** | 0.2763 | 3.37 |
| $1,000 | 58 | 4 | **0.000%** | 52.2% | **0.0000** | 0.5045 | 17.61 |
| $10,000 | 42 | 20 | 0.161% | 7.9% | 0.0044 | 0.0314 | 13.15 |

**The median book absorbs a $1,000 order entirely at the touch — zero impact.** The shipped
coefficient of 0.5 therefore *massively over-charges* the typical liquid market. But the tail
implies coefficients up to 17.6, so 0.5 simultaneously *under-charges* the thin books.

Impact on this venue is close to bimodal — absorbed at the touch, or a deep walk — and a
single global coefficient in a smooth √ model cannot represent that. **The honest conclusion
is not "the coefficient should be X" but "the parametric form is the wrong shape; walk the
real book."** `walk_book()` is that replacement and needs no calibration.

### The tail number depends on the denominator — disclosed, not hidden

`implied_impact_coeff` inverts `impact = coeff·√(size/depth)`, and **"depth" is a choice**.
The table above uses executable depth within 2 cents. An adversarial reviewer correctly
pressed on this, so here is the same $1,000 walk against every depth field in the artifact:

| denominator | median | p90 | max |
|---|---:|---:|---:|
| `depth_at_touch_contracts` | 0.0000 | 0.0744 | **0.93** |
| `depth_within_2c_contracts` (used above) | 0.0000 | 0.5045 | **17.61** |
| `depth_within_5c_contracts` | 0.0000 | 0.6776 | 19.01 |
| `total_ask_contracts` | 0.0000 | 2.1978 | 137.03 |

The realized-impact numerator is identical in all four rows; only the denominator moves the
tail by two orders of magnitude. **So "the tail implies 17.6" is not a robust number** — under
touch-depth the tail max is 0.93, within 2x of the shipped 0.5.

What *is* robust across every denominator is the **median: 0.0000**. The over-charging of the
typical book is not a denominator artifact. The under-charging of the tail is
denominator-dependent and is stated here as such rather than quoted as a finding.

### The tail is a longshot artifact — stated precisely

The eye-catching percentages (441% at $100) are **fractional** measures on penny-priced
markets, and they overstate the economic damage. In absolute price terms:

| order | median move | p90 | max |
|---|---:|---:|---:|
| $100 | **0.000c** | 0.278c | 3.09c |
| $1,000 | **0.000c** | 1.666c | 35.85c |

The worst $100 case is a touch of 0.0070 filling at 0.0379 — a 441% *fraction*, but a 3.1
**cent** move. Both framings are true; quoting only the first would be alarmist and quoting
only the second would hide that a longshot position is being entered at 5x the quoted price.

### This lands directly on EXP-006b

EXP-006b's threshold-0.15 cell concentrates its PnL in the **lowest entry-price band** — the
longshot region where fractional impact is by far the worst. (That concentration figure is
reported by the EXP-006b run in `EXP006B_RESULT.md`; it is not derived from this artifact.) So the F10 confidence-band
concentration flag on that cell is not only a robustness concern; it points at exactly the
price region where these measurements say own-order impact bites hardest. Any future attempt
to size that signal must walk the book rather than trust a flat cost.

---

## The capacity numbers, at the measured depth distribution

Measured executable depth within 2 cents of the touch (**62 tokens**, from the committed
artifact): p25 **18,851** / median **71,688** / p75 **558,072** contracts. Median spread
**0.3c**.

Max per-trade stake keeping modelled drag within tolerance, at price 0.50 **using the shipped
`impact_coeff=0.5`**:

| depth | ≤2% drag | ≤5% drag |
|---|---:|---:|
| p25 (thin) | $15 | $97 |
| median | $59 | $367 |
| p75 (deep) | $458 | $2,860 |

**Do not quote these as the bot's capacity** (and see the denominator caveat above before
quoting the 17.6 either). Finding 2 shows the coefficient over-charges the
median book by a wide margin, so these are a *lower bound distorted by a bad parameter*. They
are reported to make the distortion visible, not to be used. The `walk_book` measurements
above are the trustworthy numbers, and they say a $1,000 order is free on the median book and
ruinous on the thin tail.

## What this does NOT establish

- **No revenue or $/week claim follows.** There is still no validated positive edge to size,
  and `floor_feasibility()` refuses to solve for a stake when the edge is non-positive — the
  project's actual state. That refusal is a guard for the CURRENT state, **not** a structural
  guarantee: fed a positive edge the function will happily print a $/week figure, and an
  adversarial reviewer showed it could print a fabricated one in the saturated-impact regime
  (now detected and refused explicitly). Do not treat this module as incapable of producing a
  revenue number; treat it as one that has none to produce.
- The probe is **open markets at one instant**, volume-ordered — the liquid end. It bounds a
  sweep; it does not measure the resolved corpora's depth (which is unobtainable).
- Bid-side depth is not analysed; the fade strategy's exit leg would need the same treatment.

## Named next steps

1. ~~**Forward depth capture at decision time.**~~ **BUILT 2026-07-27 (ROADMAP E11, PR #444).**
   The orchestrator now records the pre-trade book alongside every executed paper decision, on
   a nullable `book_json` column, bounded to the same 40 ask levels this probe uses so forward
   rows and probe rows feed the same capacity code. Observation-only — proven not to alter any
   decision, size or order. Two things still gate a real curve: it accrues only going forward
   (past depth remains unrecoverable, which is the whole reason this was the named step), and
   on the already-deployed database an owner `ALTER TABLE` is needed before capture can persist
   at all (PENDING_OPS OA-20) — until then the writer degrades and records rows without it.
2. **Replace the parametric impact path with `walk_book` where a ladder is available**, and
   keep the √ model only as a fallback where it is not — with the coefficient documented as
   the crude bound it is.
3. Bid-side (exit-leg) depth analysis before any fade-strategy sizing claim. **Still open, and
   E11 does not close it:** the capture stores the ASK ladder plus the bid touch, mirroring
   this probe's artifact, so a SELL-side capacity question cannot be answered from those rows
   either. That matters most for the one family that exits rather than holding to resolution.

## Reproduction

```bash
python scripts/capacity_probe.py --out data/depth_probe_polymarket.json --limit 60 --stamp <UTC date>
python -m pytest backend/tests/test_capacity.py
```

The probe hits live open markets, so its numbers move; the committed artifact is the 
2026-07-26 snapshot the tables above were computed from.
