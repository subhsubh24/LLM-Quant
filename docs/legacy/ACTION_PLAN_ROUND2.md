# ⚠️ ACTION PLAN - ROUND 2

## Summary of Issues Found

From the backtest output at 25% completion:

| Issue | Status | Severity |
|-------|--------|----------|
| Only ~120 trades at 25% | 🔴 CRITICAL | P0 |
| All trades are SHORTS | 🔴 CRITICAL | P0 |
| Capital loss -1.8% | 🔴 CRITICAL | P0 |
| 80% of signals filtered | 🔴 CRITICAL | P0 |
| Position sizing wrong | ✅ FIXED | - |
| Speed slow | ⚠️ PARTIAL | P2 |

---

## IMMEDIATE ACTIONS (Do These Now)

### ACTION 1: Apply New Confidence Thresholds ✅ DONE
**Status**: Committed and pushed
**Changes**: Lines 1335-1337 in backtester.py
```python
"confidence_4x4_models": 0.30,    # was 0.45
"confidence_3x4_models": 0.20,    # was 0.35
"confidence_fallback": 0.10,      # was 0.25
```
**Expected**: 3-5x more signals (480 → 1500+)

### ACTION 2: Re-Run Backtest
```bash
# Install latest code
git pull origin claude/check-project-status-YBHJ6

# Run backtest (save full output this time!)
python run_backtest.py 2>&1 | tee backtest_round2.log
```

### ACTION 3: Analyze Filter Funnel
**Look for this section in the log**:
```
📊 SIGNAL FILTER PIPELINE ANALYSIS:
  Stage 1 - Total predictions: ???
  Stage 2 - Not HOLD: ???
  Stage 3 - Meets confidence: ???
  ✅ POSITIONS ACTUALLY OPENED: ???
```

**Expected results**:
- Stage 1: 500,000+ predictions
- Stage 2: 250,000+ not-hold signals
- Stage 3: Should be higher % than before
- Final: 500-1000+ trades (was 480)

### ACTION 4: Check Signal Type Distribution
**Look for this section**:
```
Signal Analysis by Type:
  LONG trades: ??? (should be ~250-500)
  SHORT trades: ??? (should be ~250-500)
  Ratio: ??? (should be ~50/50, currently 0/100)
```

If still 100% shorts, there's a selection bias in the model.

---

## INVESTIGATION: SHORT BIAS

If after ACTION 2 you STILL see all shorts:

### ROOT CAUSE #1: Models Trained on Bear Data
**How to check**:
1. Look at training logs (in backtest output)
2. Check if model accuracy is consistently high for SHORTS
3. Compare to LONG accuracy

**Fix**:
- Retrain models on balanced data
- Add loss weighting to prefer LONG when in bull market

### ROOT CAUSE #2: Regime Detection Wrong
**How to check**:
1. Search log for "Final Macro Regime"
2. Search for "Regime=bull/bear/sideways" counts
3. Look at BTC/ETH prices during backtest

**If regime is detected as BEAR but prices rising**:
- Regime threshold too conservative (trend > 0.02 is 2% only)
- Need wider threshold (e.g., > 0.005 = 0.5%)

**Fix**:
```python
# Lines 1102-1107 in backtester.py (detect_market_regime)
# CURRENT:
if trend > 0.02 and volatility > 0.01:  # 2% threshold
    return 'bull'

# SUGGESTED:
if trend > 0.005 and volatility > 0.01:  # 0.5% threshold (more sensitive)
    return 'bull'
```

### ROOT CAUSE #3: Voting Bias in Ensemble
**How to check**:
1. Look at individual model predictions in logs
2. Do all 4 models predict shorts?
3. Or do some predict long but get outvoted?

**Fix**:
- Check `predict_regime_aware()` function (line 3538)
- Verify voting logic doesn't favor shorts
- Check if softmax is producing correct probabilities

### ROOT CAUSE #4: Confidence Calculation Biases Shorts
**How to check**:
1. Add debug logging to `predict_regime_aware()`
2. Print q_values, action_probs for each model
3. Check if SHORTS naturally get higher confidence

**Fix**:
- Change confidence calculation to be unbiased
- Ensure all actions (SHORT/HOLD/LONG) get similar score distributions

---

## IF TRADES STILL < 500

This means confidence thresholds are STILL too high or another filter is blocking.

### Investigation Steps:

1. **Find which stage is filtering most**:
   ```
   Stage 3: 250,000 → 125,000 (50% drop at confidence check)
   Stage 4: 125,000 → 100,000 (20% drop at liquidity)
   Stage 5: 100,000 → 50,000 (50% drop at consensus)
   → Consensus is the main bottleneck!
   ```

2. **Lower the minimum model agreement**:
   ```python
   # Line 1342 in backtester.py
   # CURRENT:
   "min_model_agreement": 2,  # Minimum 2/4 models

   # SUGGESTED:
   "min_model_agreement": 1,  # Minimum 1/4 models
   ```

3. **Or lower weighted agreement threshold**:
   ```python
   # Line 1343 in backtester.py
   # CURRENT:
   "weighted_agreement_threshold": 0.50,  # 50% weighted agreement

   # SUGGESTED:
   "weighted_agreement_threshold": 0.25,  # 25% weighted agreement
   ```

---

## IF CAPITAL STILL NEGATIVE

This means the SIGNALS are wrong, not the quantity.

### Investigation Steps:

1. **Check win rate** (look for in log):
   ```
   Win Rate: ???% (should be >50%)
   Profit Factor: ???  (should be >1.0)
   Avg Win: $???
   Avg Loss: $???
   ```

2. **Check if shorts are losing**:
   ```
   LONG trades: ??? win rate
   SHORT trades: ??? win rate (likely <50%)
   ```

3. **If shorts losing consistently**:
   - Stop taking shorts (just take longs)
   - Or fix regime detection
   - Or retrain models

**Quick fix** (temporary):
```python
# Line 2297 in backtester.py
# CURRENT:
if (prediction["action"] != 1 and ...):  # Allow 0=SHORT and 2=LONG

# TEMPORARY (longs only):
if (prediction["action"] == 2 and ...):  # Only allow 2=LONG
```

This will test if shorts are the problem.

---

## TIMELINE

```
Round 2 (Next 30 mins):
  ✅ Apply new thresholds (0.30/0.20/0.10)
  ⏳ Run backtest
  ⏳ Analyze filter funnel
  ⏳ Check signal type distribution

Round 2 Results:
  IF trades > 500:
    ✓ Signal quantity problem SOLVED
    ✓ Focus on signal quality (why -1.8% loss)

  IF trades < 500:
    → Further lower thresholds (0.20/0.10/0.05)
    → OR reduce min_model_agreement to 1
    → OR check which stage is filtering most

  IF 100% shorts still:
    → Check regime detection
    → Check model bias in predictions
    → Consider longs-only fix temporarily
```

---

## FILES TO MONITOR

**Main backtest file**:
- `/home/user/LLM-Quant/backend/app/trading/backtester.py`
  - Lines 1334-1343: Confidence thresholds & min agreement
  - Lines 1075-1107: Regime detection
  - Lines 3538+: predict_regime_aware (voting logic)

**Documentation**:
- `AUDIT_FINDINGS.md` - Root cause analysis
- `RESULTS_AUDIT.md` - Analysis of backtest results
- `ACTION_PLAN_ROUND2.md` - This document

---

## GIT COMMITS

Latest commit (just pushed):
```
1a04105 - CRITICAL FIX: Further lower confidence thresholds (0.30/0.20/0.10)
```

After you run the next backtest and implement fixes, create a new commit:
```bash
git add -A
git commit -m "ROUND 2 FIX: [description of what you fixed]"
git push origin claude/check-project-status-YBHJ6
```

---

## SUCCESS CRITERIA FOR ROUND 2

✅ **Success**:
- Trades: 500-1000 (was 480)
- Win Rate: >50%
- Profit Factor: >1.0
- LONG trades: >0 (was 0)
- Capital: Positive (was -$180)

🟡 **Partial Success**:
- Trades: 300-500 (improved but not 10x)
- → Continue with threshold reductions

🔴 **Failure**:
- Trades: <300 (getting worse)
- Win Rate: <40%
- 100% shorts still
- → Root problem is in model ensemble, not filters

---

## NEXT STEPS

1. **Run backtest** with new thresholds
2. **Capture FULL output** to file
3. **Search for these sections** in log:
   - "SIGNAL FILTER PIPELINE ANALYSIS" (filter funnel)
   - "LONG/SHORT breakdown"
   - "Final Macro Regime"
   - "Win Rate"
4. **Share results** with me
5. **I'll provide** next round of fixes based on actual data

The key insight is: **We need to see the filter funnel breakdown** to know which stage is actually bottlenecking us.

Good luck! 🚀
