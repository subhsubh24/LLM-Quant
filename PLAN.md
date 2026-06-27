# Plan: Fix Risk/Reward Asymmetry (Profit Factor 0.71 → 1.0+)

## Problem Statement
54% win rate but -10.56% return. Average win $3.84 vs average loss $6.42.
The system is **right more than half the time** but **loses more when wrong**.

## Root Causes (in order of impact)

### 1. Trailing stop turns winners into losers (HIGHEST IMPACT)
**Lines 2495-2513.** The 5% trailing stop fires on ANY position above entry.
Traced example: entry $100, price peaks at $104, trailing stop = $104 * 0.95 = $98.80.
Exit at $98.80 = **-1.2% loss** on a trade that was +4% profitable.

The trailing stop can only produce a profit when peak > entry * 1.053 (+5.3%).
But it's checked FIRST in the exit order (before pyramid targets), so it preempts
Target 1 (5-15%) on most trades. This is the #1 drag on average win.

### 2. Counter-trend stops widen by 15% (MEDIUM IMPACT)
**Lines 2469-2478.** Shorts in bull markets and longs in bear markets get
`base_stop *= 1.15` — 15% wider stops. These trades are already riskier
(fighting the trend), and wider stops mean bigger losses when they fail.
The higher confidence requirement at entry (+0.10, line 3168-3175) already
filters weak counter-trend signals — the stops shouldn't also be loosened.

### 3. No R:R safety net at entry (LOW IMPACT)
The implicit R:R from ATR-based targets is already 4:1 (Target 1 = 5x ATR,
Stop = 1.2x ATR). But at the clipping boundaries (stop max 3.5%, target min 5%),
R:R drops to 1.43 — below break-even for a 54% win rate.

## Proposed Changes

### Change 1: Only activate trailing stop after pyramid 1 hits
**File:** `backtester.py`, lines 2495-2513
**What:** Add a guard: `if pos.get("pyramided_1", False)` before the trailing stop logic.
Before Target 1, the ATR-based stop-loss (lines 2428-2486) handles downside protection.
After Target 1 (30% position sold at +5-15%), the trailing stop protects remaining 70%.

**Why this works:** After pyramid 1, the position is already profitable and the stop
is at breakeven (line 2439-2440: `base_stop = 0.002`). The trailing stop then serves
its intended purpose — locking in gains on the runner — instead of prematurely
killing trades that haven't reached their first target.

**Before:**
```python
# Trailing stop fires on ANY winning position (even +0.5%)
trailing_stop_pct = 0.05
if side == "long" and pos.get("highest_price", entry_price) > entry_price:
    if low_price < pos["highest_price"] * (1 - trailing_stop_pct):
        should_exit = True
```

**After:**
```python
# Trailing stop only fires AFTER pyramid 1 (position already banked 30% at target)
trailing_stop_pct = 0.05
if pos.get("pyramided_1", False):
    if side == "long" and pos.get("highest_price", entry_price) > entry_price:
        if low_price < pos["highest_price"] * (1 - trailing_stop_pct):
            should_exit = True
```

### Change 2: Tighten counter-trend stops instead of widening
**File:** `backtester.py`, lines 2469-2478
**What:** Swap the multipliers — counter-trend trades get `*= 0.85` (tighter),
with-trend trades get `*= 1.15` (more room).

**Before:**
```python
if regime == 'bull':
    if side == "long":  base_stop *= 0.85  # With trend: tighter
    else:               base_stop *= 1.15  # Against trend: WIDER (bad)
```

**After:**
```python
if regime == 'bull':
    if side == "long":  base_stop *= 1.15  # With trend: more room to breathe
    else:               base_stop *= 0.85  # Against trend: cut fast if wrong
```

### Change 3: Add R:R ratio safety net at entry
**File:** `backtester.py`, after line 3579 (where effective_stop_distance is computed)
**What:** Before opening a position, verify:
```python
rr_ratio = pyramid_target_1 / effective_stop_distance
if rr_ratio < 2.0:
    continue  # Skip — reward doesn't justify the risk
```
This rejects trades where clipping boundaries compress the natural 4:1 R:R below 2:1.

## Files Modified
- `backend/app/trading/backtester.py` (all 3 changes in one file)

## Expected Outcome
- Average win increases significantly (trailing stop no longer clips early winners)
- Average loss decreases (counter-trend stops tightened)
- Profit factor rises from 0.71 toward 1.0+ (break-even or better)
- Trade count may drop (R:R gate + tighter counter-trend stops filter marginals)
- Win rate may drop slightly but EV per trade improves

## What This Does NOT Change
- Model training (40-50% per-model accuracy is a separate problem)
- Feature engineering
- Ensemble voting logic
- Position sizing (Kelly criterion)
- Continuous learning (remains disabled for backtest speed)
- Hold times (30-day loser cut is already reasonable)
