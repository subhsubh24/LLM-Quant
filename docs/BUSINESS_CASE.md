# BUSINESS CASE — LLM-Quant (the profit case)

This is the **profit case** for a personal prediction-markets bot, not a product
revenue model. "Revenue" = **net trading profit** in validated out-of-sample paper
trading, with realistic costs. Numbers are honest: at baseline there is **no
validated edge yet**, so the weekly floor is **not met**.

## Honest current state (as of bootstrap)

The prediction-markets engine exists and runs in **paper / dry-run** mode (scanner,
strategies, Kelly sizing, paper simulator, kill switch). What does **not** yet exist
is a **validated, reproducible, out-of-sample weekly-PnL series with realistic costs
and sufficient sample** — i.e. proof of edge. Until that exists, all profit figures
below are **planning placeholders set to the honest floor of 0 / null**, not claims.

The binding constraints to reach the floor (from ROADMAP):
1. Leakage-free, cost-realistic, walk-forward **out-of-sample** backtest that
   reproduces deterministically (C1–C3).
2. **Calibration** layer with a passing eval (B2).
3. Realistic **cost model** applied (C2).
4. End-to-end runtime harness proving real PnL (F3).

<!-- BUSINESS_CASE_SUMMARY
currency: USD
arr_year1:
  conservative: 0
  base: 0
  optimistic: 0
planning_case: 0
floor_usd: 104000
floor_met_year1: false
time_to_floor: unknown
as_of: 2026-06-27
-->

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
