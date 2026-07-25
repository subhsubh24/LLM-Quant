# BUSINESS CASE — LLM-Quant (the profit case)

This is the **profit case** for a personal prediction-markets bot, not a product
revenue model. "Revenue" = **net trading profit** in validated out-of-sample paper
trading, with realistic costs. Numbers are honest: at baseline there is **no
validated edge yet**, so the weekly floor is **not met**.

## Honest current state (refreshed 2026-07-25)

The prediction-markets engine exists and runs in **paper / dry-run** mode (scanner,
strategies, Kelly sizing, paper simulator, kill switch). What does **not** yet exist
is a **validated, reproducible, out-of-sample weekly-PnL series with realistic costs
and sufficient sample** — i.e. proof of edge. Until that exists, all profit figures
below are **planning placeholders set to the honest floor of 0 / null**, not claims.

**The binding constraint is ALPHA, and it has moved in the negative direction.** This
section previously listed *infrastructure* items as the blockers. That framing is now
stale and was optimistic by omission: the infrastructure it named is substantially built,
and the honest blocker is that **every mechanism family tested to date has been REFUTED on
real out-of-sample data** — not merely "unproven".

| family | status | evidence |
|---|---|---|
| bucket calibration (EXP-002/003/005) | **REFUTED** | real OOS N=187: 39 trades, **−$3,228.02**, F11 `significant_negative` |
| …re-tested under the venue's REAL fee (EXP-010) | **refutation REINFORCED** | 42 trades, **−$3,502.27** — the real fee made it worse, not better |
| …re-tested with recency-weighting + concentration caps (EXP-011) | **REFUTED** | 0 of 6 cells positive; recency-weighting loses ~2× per trade |
| fade-the-spike (EXP-006) | **REFUTED** | 60-cell pre-registered surface: **0/60** validate, 18 significantly negative |

The only committed real-money OOS result this project has is **significantly negative**.
That is an honest, reproducible finding rather than a failure of process — but it means
the floor is not close, and no date should be inferred.

Remaining infrastructure constraints (real, but no longer the binding ones):
1. Leakage-free, cost-realistic, walk-forward **out-of-sample** backtest that
   reproduces deterministically (C1–C3) — **built and reproducing sha256-identical**
   from committed bytes.
2. **Calibration** layer with a passing eval (B2) — built; still needs a *passing* eval
   on real live strategy probabilities.
3. Realistic **cost model** applied (C2) — built, and hardened with the venue's real
   price-dependent per-category fee schedule.
4. End-to-end runtime harness proving real PnL (F3) — passing.

The untested surface that remains is **market impact and capacity**: all 187 frozen
records carry `liquidity: null`, so the impact path is inert on every committed artifact
and `DEFAULT_IMPACT_COEFF` is an uncalibrated placeholder.

```yaml
# BUSINESS_CASE_SUMMARY (machine-readable; the profit case — net trading profit, not product revenue)
# arr_year1 = annualized NET profit from validated paper performance with realistic costs.
# All 0 because no validated out-of-sample edge exists yet (honest baseline). Raise ONLY on reproduced numbers.
currency: USD
arr_year1:
  conservative: 0
  base: 0
  optimistic: 0
planning_case: base
floor_usd: 104000
floor_met_year1: false
time_to_floor: unknown
as_of: 2026-07-25
```

### Field notes (honesty)
- `arr_year1.*` = **annualized net profit** from validated paper performance with
  realistic costs. Set to `0` because no validated out-of-sample edge exists yet.
  These will be raised **only** when a reproducible OOS weekly-PnL series exists.
- `floor_usd: 104000` = $2,000/wk × 52 — the go-live-eligible annualized bar.
- `floor_met_year1: false` — honest: the floor is not met; there is no proven edge.
- `time_to_floor: unknown` — depends on building B2/C1–C3/F3 and finding a real edge;
  it may never be reached, and that is an acceptable honest outcome.

Update this block **only** with reproduced, cost-realistic, out-of-sample numbers.
Never invent edge.
