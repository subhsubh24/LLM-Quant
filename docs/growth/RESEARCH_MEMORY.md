# RESEARCH MEMORY — LLM-Quant

A dated log of alphas/strategies tried, what worked, what **decayed**, and **why**.
Cross-run learning. **Read this first** each research run. Append; never rewrite
history.

Format per entry:
```
## YYYY-MM-DD — <alpha/strategy name>
- Hypothesis (falsifiable):
- Min sample N:
- OOS result (or "insufficient data"):
- Calibration (Brier / reliability):
- Costs modeled:
- Verdict: proposed | backtesting | paper | promoted | retired | edge-not-proven
- Why:
```

---

## 2026-06-27 — Bootstrap (no alphas tested yet)
- Hypothesis (falsifiable): n/a — apparatus bootstrap only.
- Min sample N: n/a
- OOS result: none. No validated out-of-sample edge exists yet.
- Calibration: not yet measured.
- Costs modeled: cost model not yet asserted in backtest (ROADMAP C2 open).
- Verdict: edge-not-proven (baseline)
- Why: This run installed the factory apparatus and the gated live path; it did not
  test any alpha. The first research run should diagnose the binding constraint
  (likely: no leakage-free cost-realistic OOS backtest yet) and propose the first
  falsifiable experiment with a stated minimum sample size.

## 2026-06-28 — Cost-aware sizing (C2): gross-edge Kelly was systematically over-betting
- Hypothesis (falsifiable): the orchestrator's Kelly sized on GROSS edge
  (`win_probability - market_price`), ignoring the executor's fees (2% of notional) +
  market-order slippage (0.5%). Claim: this both over-bets (full-Kelly on inflated odds)
  and over-trades (takes positions whose gross edge is positive but net edge ≤ 0).
- Min sample N: n/a (deterministic correctness fix, not an alpha).
- OOS result: n/a — no edge claimed. This LOWERS expected turnover/sizing (honestly).
- Costs modeled: NOW yes — `cost_model.py` is the single source of truth
  (effective_buy_price = price·(1+slip)·(1+fee); net_edge; contracts_for_budget). Verified
  end-to-end that net cash deployed == intended budget (no double-counting) and that a 1%
  gross edge at price 0.50 is now correctly REJECTED (net edge negative).
- Verdict: promoted (correctness fix; 10 tests + 3 adversarial auditors SOUND).
- Why / next: this is a prerequisite for honest realized-vs-backtest reconciliation —
  EV must subtract the same costs realized fills do. REMAINING: model liquidity/market
  impact; apply the cost model inside the walk-forward backtest (C1/C3); unify
  `execution.py` to import the cost_model rates (currently duplicated literals + a drift
  test). Until the cost model also covers depth/impact, capacity claims stay conservative.

### Candidate alpha directions to investigate (not yet tested — hypotheses only)
- **Calibration arbitrage:** crowd probabilities on low-liquidity markets may be
  systematically mis-calibrated near 0/1; test reliability vs realized outcomes with
  sufficient N before claiming anything.
- **Cross-market logical constraints:** mutually exclusive / implied markets that
  violate probability axioms (sum > 1 net of fees). Already partially present
  (`logical_implication`); needs OOS validation + cost realism.
- **Resolution-timing edges:** price drift as resolution approaches; must rule out
  look-ahead and liquidity traps.
All of the above are **hypotheses**, not edges. None may be promoted without OOS +
calibration + cost-realistic validation surviving the adversarial auditors.
