# VISION — LLM-Quant

> North star for a **personal** prediction-markets trading bot.
> Not a product. Not marketed. No users. Its only job is to make the **owner** money,
> honestly, with an edge that compounds as the model improves.

## What this is

LLM-Quant is a personal autonomous trading system for **prediction markets**
(Polymarket / Kalshi / similar venues, within venue ToS and the owner's jurisdiction).
It ingests markets, estimates probabilities, computes edge/EV, sizes positions,
and trades — by default with **fake money (paper)**. The model continuously improves
its **calibration, accuracy, and edge** through backtesting, paper trading,
training/retraining, and self-directed research that generates new alphas.

It is explicitly **NOT**:
- a sellable or marketed product;
- a multi-user SaaS;
- a stock or crypto trading app (those paths are being retired — see ROADMAP item A).

The TypeScript frontend is a **private monitoring/control panel** for the owner
(paper + live PnL, strategies, calibration, the kill switch) — not a product surface.

## Why prediction markets — the edge thesis (this directs WHAT we build)

Prediction markets are a **level playing field**: every participant sees the same
public information (the market, the question, the resolution source). There is no
private data feed that confers a durable edge. That is *precisely why* this is the
right domain — and it dictates **where the edge comes from**:

- **Better calibration than the crowd** — systematic miscalibration (especially near
  0/1, in low-liquidity or under-followed markets), measured against realized outcomes.
- **Better reasoning on the same facts** — LLM + quantitative synthesis; **logical
  consistency** across related/implied/mutually-exclusive markets that violate
  probability axioms (net of fees).
- **Faster, cheaper execution** — reacting to resolution-relevant public news;
  spread/liquidity capture; minimizing fees/slippage/market-impact.
- **Discipline** — fractional-Kelly sizing, hard risk limits, no tilt.

The edge is **NEVER "data other people don't have."** Chasing secret/alternative
signals is the **stock/crypto trap this project deliberately rejects** — in those
markets you need non-public information to win; here you do not, and you must not rely
on it. **Any proposed alpha that depends on non-public data is out of scope.** The
research agent and the factory optimize calibration, reasoning, logical consistency,
speed/cost, and discipline — not signal acquisition.

## The learning loop — how the edge improves (this IS the operating principle)

Yes: the bot is meant to **run, observe its own realized results, learn from them,
change, and re-test — forever.** Made rigorous so it improves on real evidence and
never fools itself:

1. **Propose** a change, grounded in the current binding constraint (poor
   calibration? a losing strategy? a cost/latency issue?).
2. **Backtest first** (leakage-free, walk-forward, out-of-sample, realistic costs).
   It only graduates to paper if it beats the current config in backtest — never burn
   an evaluation window on something that already fails offline.
3. **Run a fixed evaluation window** in paper: hold the strategy config **stable** for
   ~**1 week, or until sufficient sample size (N)** — whichever is longer. Changing the
   config mid-window contaminates the evidence, so strategy changes apply at window
   **boundaries**; infrastructure/bug fixes may ship anytime.
4. **At window close, measure + attribute:** realized PnL, calibration (Brier /
   reliability), hit-rate, drawdown — and **attribute** them (which strategies,
   markets, and conditions made or lost money, and *why*).
5. **Reconcile realized vs backtest-expected.** If paper diverges materially from what
   the backtest predicted, the **backtest is overfit/leaky** — that gap is itself a
   top-priority learning signal; fix the backtest before trusting the strategy.
6. **Learn → next targeted change** (or retire a decayed alpha). Log it to
   `docs/growth/RESEARCH_MEMORY.md`. Then repeat.

**The one thing to get right (or you'll fool yourself):** one week of PnL is a
**noisy** signal. Do not over-update on variance. Weight learning by **statistical
significance**, not raw weekly profit — and note that **calibration accumulates
reliable evidence faster than PnL does**, so it is often the better thing to learn
from week to week. Prefer "insufficient data" over chasing noise. This is honest,
evidence-driven improvement — not curve-fitting to last week's luck.

## The bar (definition of "working")

Success is **consistent, VALIDATED, out-of-sample net profit** — never a pretty
in-sample backtest.

- **Go-live-eligible floor:** ≥ **$2,000–3,000 / week** net, in validated
  out-of-sample paper trading, with realistic fees/slippage/liquidity/market-impact
  and a sufficient sample. Annualized floor: **$104,000/yr** (≈ $2,000/wk × 52).
- After eligibility, the target **climbs** ($4K → $5K → $6K/wk). The system
  **never fully converges** — it perpetually improves accuracy and edge.
- The owner — not the loop — decides to fund the account and flip to live.

## Honesty is load-bearing

A backtest that looks great but is **overfit, leaky (look-ahead),
survivorship/selection-biased, p-hacked, cost-ignorant, or run on too small a sample
is WORTHLESS** — a failure, and worse than a modest honest result. Non-negotiables:

- out-of-sample + walk-forward validation;
- realistic fees, slippage, liquidity, market impact;
- sufficient sample size (N) and calibration (Brier / reliability);
- deterministic, reproducible results;
- **never fabricate a metric, a PnL, or an "edge."**

## Standing engineering bar

- **Monitoring UI:** clear, real-data-only, no slop, no stub/error screens. Every
  number on screen is a real number from a real run, or it is explicitly absent.
- **Research/strategy code:** rigorous, reproducible, no magic numbers, no
  look-ahead, hypotheses falsifiable, costs always modeled.
- **Safety first:** real money is gated behind an explicit owner-only switch, hard
  loss caps, and a kill switch — all in code, default off.

## The boundary that never moves (HUMAN-CORE)

The autonomous loop **builds, backtests, and paper-trades**. It also **builds the
complete live/real-money path** — but it **never**:
- places a real-money trade,
- funds or deposits,
- flips paper → live,
- raises a loss cap,
- makes the legal/jurisdiction/eligibility call.

Those are the **owner's** actions, documented exactly in
[`docs/growth/LIVE_RUNBOOK.md`](docs/growth/LIVE_RUNBOOK.md).

See [`ROADMAP.md`](ROADMAP.md) for the convergence anchor, standing standards,
and the Definition of Done.
