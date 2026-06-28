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

## 2026-06-28 — Backtest + calibration APPARATUS built (C1/C3 engine, B2 eval) — no alpha tested
- Hypothesis (falsifiable): n/a — this run built the MEASUREMENT apparatus the binding
  constraint requires, not an alpha. The prior entries correctly named the constraint as
  "no leakage-free cost-realistic OOS backtest + no calibration eval"; this run builds both.
- Min sample N: the B2 eval now ENFORCES significance — `passes` requires a paired-bootstrap
  CI on the per-market Brier difference to exclude 0 (default 95% CI, ≥30 samples). A raw
  Brier point comparison was measured to pass ~21% of pure-noise strategies at N=30; the
  bootstrap gate collapses that to ≤1.2%. **No alpha may be promoted on a sub-significance
  Brier win.** Multiple-comparison correction (tighten alpha) is required when screening >1.
- OOS result: none. The walk_forward engine runs on SYNTHETIC data only — it proves the
  engine is leakage-free (structural: the decision can't see the outcome), reproduces
  deterministically, recovers a known injected edge, and reports ~0 on a no-edge market. It
  does NOT prove a real edge. No real resolved-Polymarket history is wired yet.
- Calibration (Brier / reliability): the eval EXISTS (Brier + reliability curve + ECE +
  significance gate) but has not been run on real resolved markets / live strategy
  probabilities — so there is no passing calibration result to report yet.
- Costs modeled: yes — the walk_forward engine prices every fill through `cost_model`
  (same source as the executor; C2 unify makes execution.py import those rates too).
- Verdict: edge-not-proven (apparatus only) — the gate to test the FIRST real alpha is now
  built and adversarially hardened.
- Why / next: the binding constraint is unchanged — a VALIDATED out-of-sample weekly-PnL
  series on REAL resolved markets + a passing calibration eval on live strategy probabilities.
  Next research run: wire real resolved-Polymarket history into `walk_forward` + run B2 on
  the strategies' historical probabilities; only then can the first alpha be proposed →
  backtested → significance-tested. Until then, every candidate below stays a hypothesis.

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

## 2026-06-28 — Research Run 3: Real-data pipeline gap identified; EXP-001 proposed

- Hypothesis (falsifiable): The NO Position Scanner generates positive net EV —
  Brier improvement vs crowd baseline AND positive net PnL after realistic costs —
  on resolved Polymarket binary markets where YES > 90¢, across ≥100 resolved
  markets spanning ≥3 market categories. Category-specific reversal base rates
  (politics 2%, economics 3%, crypto 8%, sports 5%) are empirically calibrated to
  real resolution history, not hardcoded fiction.
- Min sample N: 100 resolved markets total; ≥50 per category for any
  category-level significance claim.
- OOS result: **insufficient data** — no real resolved Polymarket history in the
  system yet. `polymarket_client.py` has no method to batch-fetch historical
  resolved markets. Third-party APIs (PMData: pmdata.dev; PolyHistorical:
  polyhistorical.com; PolymarketData: polymarketdata.co) offer 13K–200K+ resolved
  markets suitable for populating `HistoricalMarket` records. This is the blocking
  dependency for ALL OOS validation.
- Calibration (Brier / reliability): not measured — no real data. The eval (B2
  calibration.py) exists and is significance-gated; it has never run on real
  resolved-market probabilities.
- Costs modeled: yes (cost_model.py: 2% fee + 0.5% slippage). No
  liquidity/market-impact model yet — near-certainty NO positions may have
  near-zero book depth on the NO side, making slippage estimates conservative.
- Verdict: **proposed** (EXP-001; see GROWTH_STATUS experiments[])
- Why: Research confirmed (a) third-party resolved-market data sources exist and
  are credible; (b) all 11 existing strategies are untested hypotheses; (c) the NO
  Position Scanner is the most tractable first OOS test — a single calibration
  question (are the reversal rates real?). Cross-market arb (Polymarket/Kalshi) is
  a real structural edge ($40M captured 2024-2025) but bot-speed-dominated —
  unlikely to be our first competitive advantage. Academic evidence (Le 2026,
  210K+ Kalshi contracts) confirms domain-specific calibration differences persist
  but spreads are compressing 43% as market volume grows — the efficiency window
  is closing. The "horizon effect" (long-dated markets underpriced vs near-term)
  has academic backing but limited near-resolution actionability.

### How EXP-001 could be wrong (adversarial pre-mortem)
1. Reversal rates empirically near-zero across all categories → strategy dead on
   arrival; current parameters over-trade relative to the real base rate.
2. Near-certainty NO books are illiquid → real slippage far exceeds the modeled
   0.5%, erasing the edge.
3. Survivorship bias in third-party archives: contested/re-resolved/cancelled
   markets may be excluded, making the dataset unrepresentative of real outcomes.
4. N per category < 50 even with 100+ total → cannot make category-level
   statistical claims; must report "insufficient data" per category.
5. Market efficiency has increased since early Polymarket data — historical
   calibration edge may be gone in recent months.

### Candidate alphas NOT proposed this run (reasons)
- **Cross-market arb (Polymarket/Kalshi):** Real but execution-speed-dominated;
  "insufficient data" on whether paper-simulator latency can capture it.
- **Whale copy-trading:** Depends on on-chain wallet tracking — data availability
  unconfirmed; auto-rejects under "private data" exclusion if wallet identities
  are non-public.
- **Weather Arb:** Interesting but niche; NOAA integration needs validation before
  any edge claim.
- **Horizon effect (long-dated miscalibration):** Academic evidence for Kalshi
  (2021-2025); no Polymarket-specific confirmation; propose after EXP-001 gives
  baseline calibration measurement.
