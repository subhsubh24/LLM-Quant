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

## 2026-06-28 — EXP-001 code blocker CLEARED (history fetcher built); real-data run is now EGRESS-blocked
- Hypothesis (falsifiable): unchanged — EXP-001 (NO Position Scanner / crowd-miscalibration
  on resolved binary markets) still needs a real OOS run before it can pass or be retired.
- Min sample N: unchanged (100 resolved markets; ≥50/category for category claims).
- OOS result: **still insufficient data — but the blocker moved from CODE to ENVIRONMENT.**
  Built `polymarket_history_fetcher.py` (leakage-safe ingest of real resolved markets + a
  PRE-resolution price snapshot) using Polymarket's OWN public Gamma `closed=true` + CLOB
  `prices-history` endpoints — so no third-party archive / key is needed (PMData/PolyHistorical
  not required). The fetcher is the named blocking dependency for ALL OOS validation, and it
  is now done + fixture-tested + 3-Opus-auditor-clean. **HOWEVER:** the autonomous build env's
  network egress policy BLOCKS Polymarket (403 at the proxy for gamma-api.polymarket.com /
  clob.polymarket.com), so the loop cannot actually pull real history here. Real-data OOS is
  now PENDING_OPS OA-11 (owner runs the fetcher where Polymarket is reachable, or widens egress).
- Calibration (Brier / reliability): not measured — still no real data to run B2 on.
- Costs modeled: yes + IMPROVED — added a conservative sqrt market-impact / order-book-depth
  model (`cost_model.effective_buy_price_with_impact`) applied size-aware inside the
  walk-forward backtest, so a large order in a thin "near-certainty NO" book now pays realistic
  impact (the prior audit's "illiquid NO book erases the edge" concern). Still a non-calibrated
  toy until real OrderBook depth is wired.
- Verdict: **proposed (unchanged)** — EXP-001 cannot pass/retire until the real fetch runs.
- Why / next: the binding constraint is now ENVIRONMENTAL, not a missing capability. The
  cheapest path to a first honest OOS measurement is OA-11: run the (already-built) fetcher
  against live Polymarket public data, feed `scripts/run_walk_forward.py` + the B2 eval, and
  report OOS Brier + PnL with the bootstrap CI. ADVERSARIAL PRE-MORTEM addition: the fetcher's
  "unambiguously settled" filter EXCLUDES contested/re-resolved/UMA-disputed markets, biasing
  the sample toward clean crowd-friendly outcomes — any first eval MUST disclose this so it
  doesn't silently overstate crowd calibration (now documented in the fetcher itself).

## 2026-06-29 — Forensic audit of existing cross-market alphas + metrics wired e2e (no new edge)
- Hypothesis (falsifiable): the existing cross-market logical-consistency alphas
  (`CrossMarketArbitrageStrategy`, `LogicalImplicationDetector`) actually fire and find
  real, exploitable mispricing on real-shaped resolved data.
- Min sample N: 54 real resolved records (the committed leakage-safe fixture).
- OOS result: **0 signals fired** on the real sample. The records carry NO real question
  text and NO related-market grouping, which both alphas require to fire. So they are
  effectively dormant on this individual-record, near-resolution, high-liquidity sample.
- Calibration (Brier / reliability): crowd baseline Brier ≈ 0.0933 (re-confirmed,
  reproducible, no look-ahead — `scripts/validate_real_history.py`); no model edge measured
  (model_prob == crowd → degenerate, honestly reported, NOT a fake pass).
- Costs modeled: yes (cost_model; the audit is forensic, no fitting on the sample).
- Verdict: **edge-not-proven** (forensic groundwork only). Built a reusable, deterministic
  audit harness (`strategy_audit.py`) + wired weekly-metrics + calibration end-to-end into
  the paper run + API (#56), so the moment a real alpha exists it is measured honestly.
- **Adversarial-audit finding (a real strategy weakness, recorded for B-track):** a first
  cut of the audit loader injected IDENTICAL boilerplate question text ("Market {id} (real
  sample)") into all 54 records; the `CrossMarketArbitrageStrategy` keyword screen fires on
  "3+ shared non-trivial words", so it spuriously paired completely unrelated markets and
  produced ~98 PHANTOM signals (forensically "scored" at a 64% hit rate) while the prose
  claimed 0. An Opus honesty auditor broke the claim. Fixed in the harness (unique opaque
  placeholders → genuine 0 signals, enforced by a loud regression test). **The deeper lesson:
  the strategy's keyword screen is too weak — filler/boilerplate words pass the "shared
  words" test. A future B-track fix must require shared CONTENT words (stop-word list /
  entity overlap) before pairing markets, with tests. The strategy itself was left untouched
  this run (behavior change needs its own deliberate work).**
- Why / next: the binding constraint is unchanged and loop-buildable — a real decision-time
  alpha that forms `model_prob != crowd` on LESS-PINNED markets (sampled earlier in market
  life). The measurement apparatus (metrics e2e, calibration honesty, reproduction canary,
  audit harness) is now in place to evaluate it the moment it exists. No DoD/floor box ticked.

## 2026-06-29 — B5 keyword-screen hardened + B2 anti-p-hacking + B3/E6 learning-loop engines (4-PR run)
- Hypothesis (falsifiable): the cross-market keyword relatedness screen can be made to
  reject unrelated markets (boilerplate-shared AND same-template/different-subject) WITHOUT
  losing genuinely-related pairs — closing the phantom-signal weakness logged 2026-06-29.
- Min sample N: n/a (deterministic strategy-quality + infra change, not an alpha eval).
- OOS result: n/a — no edge claimed. This run hardens the SCREEN + builds learning-loop
  engines (lifecycle registry, per-strategy attribution) + strengthens the calibration gate.
- Calibration (Brier / reliability): unchanged; the B2 module now ENFORCES a Bonferroni
  multiple-comparison correction (`evaluate_calibration(strategies_screened=K)` →
  `effective_alpha=alpha/K`) so screening K strategies can no longer p-hack a pass. Verified
  the correction only ever TIGHTENS (monotone, 0 False→True flips across thousands of datasets,
  2 independent Opus auditors).
- Costs modeled: n/a for these changes.
- Verdict: promoted (strategy-quality + integrity + learning-loop infra; 4 file-disjoint PRs
  #63/#64/#65/#66 merged, gate green, 2 fix cycles vs 5 reviewers/auditors).
- **THE adversarial lesson (the keyword screen is a heuristic — entity-gating was whack-a-mole):**
  A first hardening cut required ≥3 shared content tokens AND ≥1 shared "entity" (capitalized
  proper noun). A fresh Opus auditor BROKE it both ways: it still paired same-template pairs that
  share a capitalized VENUE/NATIONALITY/ROLE word (Apple-vs-Tesla "on the Nasdaq", "Chinese mfg"
  vs "Chinese spending"), AND it wrongly REJECTED real pairs whose only entity was a <4-char
  acronym dropped by the length floor (NBA, Fed). The robust fix was SIMPLER, not more clever:
  drop entity detection entirely and rely on a COMPREHENSIVE stopword set — once the template
  words (approval/rating/exceed/percent/December/stock/dollars/nasdaq/chinese/…) are filler,
  same-template/different-subject questions share ZERO content tokens and reject naturally.
  **Lesson: a relatedness heuristic on free text is inherently leaky; chasing perfect entity
  detection is whack-a-mole. The honest, robust move is a broad stopword list + an explicit
  "this is a conservative SECONDARY screen, not an exact classifier" disclosure, accepting
  conservative false negatives (the SAFE direction) over fabricated cross-market signals.**
- **Learning-loop engines (B3/E6) — built PURE, not wired:** strategy_registry.py (lifecycle
  state machine, fail-loud integrity gate: promotion impossible without recorded backtest+OOS+
  calibration evidence) + per_strategy_metrics.py (per-strategy realized-PnL attribution; no
  fabricated rows; reconciles to total). The integrity gate operationalizes "no alpha ships while
  integrity is weak" as code. Auditors could not bypass promotion or find fabricated attribution.
  **Remaining: wire both into the orchestrator's resolved-trade stream (a follow-up) + drive a
  real alpha through them once one exists.**
- Why / next: the binding constraint is unchanged and loop-buildable — a real decision-time alpha
  forming model_prob != crowd on LESS-PINNED markets. The measurement + governance apparatus is
  now stronger (hardened screen, p-hack-resistant calibration gate, lifecycle registry, per-strategy
  attribution). Next run: WIRE the engines + start the alpha. No DoD/floor box ticked.

## 2026-06-29 — WIRED the learning-loop engines + honest cost-arb + E5/E2 engines (5-PR run)
- Hypothesis (falsifiable): (a) per-strategy attribution (E6) + the alpha-lifecycle registry (B3) can be
  wired into the orchestrator + persisted without breaking determinism or the gate; (b) the only true
  logical-arbitrage strategy (SameMarketArbitrage) can be made HONEST by costing the basket through the
  canonical cost model; (c) two new pure learning-loop engines (E5 window engine, E2 drift detector) can
  be built deterministic + significance-honest offline.
- Min sample N: n/a (wiring + infra + correctness; no alpha eval). E2's significance gate measured at a
  false-positive rate of 1.3–3.7% on same-distribution noise (vs 46.7% for a raw point comparison).
- OOS result: n/a — no edge claimed. No DoD/floor box ticked. The binding constraint (a real
  model_prob != crowd alpha on less-pinned markets) is UNCHANGED.
- Costs modeled: yes — the SameMarketArbitrage edge is now `1.0 - Σ effective_buy_price(outcome)` (the
  same multiplicative slippage+fee execution.py charges), replacing an optimistic flat `discount - 0.02`.
- Verdict: promoted (wiring + correctness + learning-loop infra; 4 file-disjoint code PRs + bookkeeping;
  2 Sonnet reviewers + 3 fresh Opus auditors; one consolidated fix cycle).
- **THE adversarial lesson (an Opus auditor BROKE the cost-arb "guaranteed edge" claim):** the
  SameMarketArbitrage "buy all outcomes → guaranteed $1" is NOT a locked arbitrage as wired: (1) the
  multi-outcome branch had no MECE check, so it could fire on a non-exhaustive candidate list where
  "exactly one pays $1" is false — FIXED by gating the multi-outcome branch on `market.neg_risk` (binary
  markets are MECE by construction); (2) `outcome.price` is the CLOB MIDPOINT, not the ask you'd pay, and
  the flat 0.5% slippage ≠ the real half-spread, so a fired signal is a candidate to verify against live
  depth, not locked profit — now disclosed honestly; (3) the orchestrator's `outcome_idx=-1` path records
  ONE phantom fill (empty token_id) instead of placing a real per-leg order each — a PRE-EXISTING execution
  defect, logged as the named B-track follow-up (per-leg ask-priced execution). **Lesson: a "guaranteed
  arbitrage" is only real if (a) the outcomes are provably MECE, (b) you price the ASK with real book
  depth, and (c) you actually place + confirm each leg separately. Costing the basket honestly is necessary
  but NOT sufficient; disclose the midpoint/MECE/execution gaps rather than ship a half-true "guaranteed".**
- **Honesty fix #2 (B3 promotion gate):** the registry gates on the PRESENCE of caller-supplied
  backtest/OOS/calibration booleans — it is an audit trail, NOT an authenticity verifier. An auditor showed
  a 4-call walk could reach PROMOTED with fabricated evidence via the planned POST endpoint. FIXED by NOT
  exposing a public write endpoint this run (GET read only); real transitions are recorded only by trusted
  in-process code once it DERIVES evidence from the actual E5/E2 gate results (named follow-up). DECISION
  COROLLARY: don't expose a control whose authenticity-backing isn't built.
- **BUILDS≠WORKS catch (reviewer):** the B3 registry seeding was a silent no-op in the normal API path
  (the orchestrator is constructed with scanner=None, so it seeded empty and never re-seeded). FIXED with
  an idempotent `sync_registry_with_scanner()` called after the scanner attaches (verified it now seeds the
  deployed strategies as PROPOSED — the honest "no alpha has passed the gate" state).
- Why / next: the governance + measurement loop is now WIRED (attribution endpoint, persisted lifecycle
  registry, drawdown-on-resolution risk fix) and two new learning engines (window + drift) exist pure.
  Next: derive real B3 evidence from E5/E2 + per-leg arb execution + the real alpha. Binding constraint
  unchanged; egress (OA-11) remains owner-scope.

## 2026-06-29 — Research Run 8: EXP-002 proposed (Horizon-Effect Calibration Bias); fixture calibration audit; academic synthesis

- Hypothesis (falsifiable): Binary Polymarket markets with YES probability 65–90% at 7 days to
  resolution are systematically UNDERPRICED vs their empirical resolution rate — the crowd
  UNDER-ASSIGNS probability to favorites at early horizons (calibration slope > 1.0) — and this
  gap survives realistic costs (2% fee + 0.5% slippage). A `CalibrationBucketStrategy` that
  replaces crowd_prob with empirically fitted per-bucket resolution rates (trained on the oldest
  60% of a 7-day-lead corpus) produces a positive net Brier improvement on the OOS 40%.
- Min sample N: 100 resolved markets with YES ∈ [0.65, 0.90] at 7-day decision_lead; ≥30 per
  bucket for any bucket-level claim. Total corpus ≥200 records across all price ranges.
- OOS result: **insufficient data** — the committed 54-record fixture was built with a 2-day
  decision_lead (all records at 48h), so ~70% of markets were already price-pinned at decision
  time. Walk-forward still makes 0 trades (model_prob == crowd by construction — the fetcher
  seeds model_prob to the crowd price; no independent model exists yet). The 7-day-lead corpus
  needed for EXP-002 requires re-running OA-11 with `--decision-lead-days 7` (the script's
  default — NO code changes needed; it already accepts this flag).
- Calibration (Brier / reliability): Fixture-level audit of the 54 records revealed: the crowd
  UNDERPRICES YES in ALL price buckets at 48h. Most striking: 34 near-certainty-NO markets
  (price < 0.10) had avg_price=0.008 vs yes_rate=0.059 (crowd said 0.8%, empirical 5.9%).
  Binomial p-value ≈ 0.029 under null (crowd correct). **Treated as a HYPOTHESIS, not an edge:**
  N=34 with ~2 YES resolutions is too small; in-sample look; sample is biased toward high-volume
  political/election markets. "Insufficient data" — needs OOS validation with ≥100 records in
  this bucket. This direction (near-certainty-NO markets resolving YES) is the INVERSE of EXP-001
  (which tested near-certainty-YES markets over-pricing YES). Both hypotheses need empirical
  calibration before any edge claim.
- Costs modeled: 2% fee + 0.5% slippage (cost_model.py). At near-zero prices (< 0.01), the
  payoff structure is highly asymmetric — a fill at 0.8¢ theoretically gets a 124x payout on a
  YES, but real bid-ask spread + market-impact on illiquid near-zero tokens may be 5-10% of face
  value, erasing the edge entirely.
- Verdict: **proposed** (EXP-002; see GROWTH_STATUS experiments[])
- Why / next: research (external sources, Le 2026 calibration decomposition on 210K+ Kalshi
  contracts; PolyBench LLM-ensemble benchmarks 2025-2026; 3%-of-traders price-discovery study
  2026) + fixture analysis converge on the same conclusion: **the current 54-record corpus is
  too near-resolution and too volume-biased to test any calibration hypothesis**. The existing
  infrastructure is complete (fetcher already has `--decision-lead-days` flag, B2 eval exists,
  walk_forward exists, CalibrationBucketStrategy is unbuilt but trivial once data arrives). The
  single highest-EV owner action is re-running OA-11 with 7-day decision_lead to unlock all
  calibration alphas at once.

### Academic + empirical findings this run (DATA; none are claimed edges)
- **Le 2026 (Kalshi, 210K+ contracts):** calibration slope rises from 0.99 (< 1h to resolution)
  to 1.32 (> 1 month). A market at 70¢ one month out reflects ~75% true probability → favorites
  systematically UNDERPRICED far from resolution. Consistent with the 54-record data (crowd
  underprices YES at all price levels at 48h). **Cannot directly extrapolate to Polymarket** —
  market microstructure and liquidity profiles differ. Needs Polymarket-specific validation.
- **3%-of-traders study (CoinDesk 2026):** only ~3% of Polymarket traders drive price discovery.
  Implication: in LOW-VOLUME markets, those 3% may not have traded yet → wider miscalibration
  window than in large markets. Consistent with the "volume proxy for informed trading" hypothesis.
  **How it could be wrong:** the 3% may include market makers (price-neutral), not alpha-bearing
  informed traders; survivorship bias in the analysis.
- **PolyBench / Prophet Arena (2025-2026):** LLM ensembles match human market accuracy with
  realized returns, edge coming from "losing less when wrong." **Supports B4 (LLM-assessed
  probability) as a viable alpha direction.** But B4 remains formally gated on B2 producing a
  PASSING eval on real resolved-market probabilities.
- **Liquidity ≠ Calibration (3,587 markets, 2025):** spread compression 43% from institutional
  entry, but calibration does NOT improve. Liquidity affects execution cost, not forecast
  accuracy. Illiquid markets are not necessarily less efficient — they may just be harder to
  predict, not miscalibrated. CONSERVATIVE implication: don't assume low-volume = mispriced.

### How EXP-002 could be wrong (adversarial pre-mortem)
1. At 7 days to resolution on high-volume markets, the crowd already incorporates 99% of public
   information → calibration slope near 1.0 even at 7 days (not 1.32). Only the VERY early
   (<30 day) low-volume markets show the bias.
2. The Le 2026 effect is KALSHI-specific: Kalshi's regulated, US-focused user base has different
   calibration patterns than Polymarket's crypto-native international user base.
3. Slippage at 7 days is materially higher than at 2 days (wider spreads, less depth) → the 0.5%
   slippage model underestimates costs, erasing the edge.
4. Per-bucket calibration fitting on the training set may overfit with N < 50/bucket — the OOS
   rates will revert toward the crowd's prices.
5. The horizon effect is priced in by sophisticated arbitrageurs who exploit it continuously →
   by the time we see the opportunity, the edge is gone.

### Candidate alphas NOT proposed this run (reasons)
- **Near-certainty-NO longshot reversal:** The fixture hint (0.8% stated vs 5.9% empirical) is
  intriguing but in-sample on N=34 with ~2 YES outcomes. "Insufficient data." Revisit once OA-11
  delivers a purpose-sampled near-certainty-NO corpus (target: 100+ records with price < 0.10).
- **Per-market LLM research (B4):** Gated on B2 producing a passing eval first — per ROADMAP.
  Also, cost per market ($0.30-0.50) must clear the EV bar per trade. Revisit after EXP-002
  delivers the first calibration baseline.
- **Cross-platform arb (Polymarket/Kalshi):** Still speed-dominated (tightest gaps close within
  seconds per 2026 reports). Insufficient data on whether the bot can execute fast enough.

## 2026-06-29 — EXP-002 mechanism BUILT: CalibrationBucketStrategy (first model_prob != crowd alpha) + E5/E2 wired + dashboard
- Hypothesis (falsifiable): a per-price-bucket empirical-calibration model — fit per-bucket
  YES-rates on a leakage-safe training set, replace the crowd price with the bucket's empirical
  rate, abstain below a min-sample floor — can (a) RECOVER a real OOS calibration edge when the
  crowd is genuinely miscalibrated AND (b) trade ~nothing / lose-to-costs when the crowd is
  well-calibrated (no fabricated edge). This is the EXP-002 mechanism.
- Min sample N: `min_bucket_n` default 30 resolved training markets PER BUCKET (below that the
  bucket is uncalibrated and the strategy abstains — never hardcodes a rate).
- OOS result: **insufficient data (real corpus) — the MECHANISM is built + proven on synthetic.**
  On synthetic data with an INJECTED bucket miscalibration (crowd 0.65, true rate 0.85) the
  walk-forward recovers the edge and makes positive OOS PnL; on a faithfully well-calibrated
  crowd it makes 0 trades / $0; a sub-threshold (1-cent) miscalibration is suppressed by the
  cost band. No real edge is claimed — proving one needs the 7-day-lead OOS corpus (OA-11).
- Calibration (Brier / reliability): not measured on real data (still no non-degenerate
  resolved predictions). The strategy is the first that WOULD produce model_prob != crowd to run
  the B2 eval against.
- Costs modeled: yes — sizing + the no-trade band use `cost_model` net edge (same fees+slippage
  the executor charges), so a few-cent miscalibration is correctly eaten by costs.
- Verdict: **proposed → mechanism built (edge-not-proven).** 24 deterministic tests; 2 Sonnet
  reviewers + 3 fresh Opus auditors CANNOT-BREAK (leakage structural via walk_forward, no
  fabricated edge, no overclaim — docstring states "a mechanism, not a validated edge").
- **THE adversarial lessons this run (the gate earned its keep again):**
  - **Shared mutable state in a StrategyFn closure (2 reviewers caught it):** the first cut built
    ONE CalibrationBucketModel in `make_calibration_bucket_strategy` and re-`fit()` it on every
    call. Harmless under walk_forward's serial expanding-window use, but a latent bug: re-using the
    same closure on a different corpus would silently carry stale stats, and an empty training set
    would RAISE and crash the backtest. **Fix: a FRESH model per call + an empty-training abstain
    guard; added `test_strategy_fn_refits_on_each_call`. Lesson: a closure that holds a mutable
    model is not "pure" — build the model inside the call or document a serial-only contract;
    prove re-use with a test, and make "no data" abstain, never raise on a hot path.**
  - **An auditor named the idealized-test trap (honesty depth):** the "0 trades on a well-calibrated
    crowd" test gets EXACTLY 0 only because the synthetic empirical rate lands on the penny. A real
    finite-sample well-calibrated crowd jitters off the penny and WOULD place noise trades — which
    LOSE to costs on average (the auditor measured negative mean PnL over 20 seeds). **The honest
    move: annotate the idealized test + add `test_cost_band_suppresses_subthreshold_miscalibration`
    (the real load-bearing mechanism — the ~3.7-cent cost band eats sub-threshold miscalibration),
    and defer the empirical noise-trading question to a real OOS run in the docstring. Lesson: a
    clean synthetic test can be honest about the mechanism while OVER-cleanly suggesting real-world
    behaviour — name the idealization and test the load-bearing assumption directly.**
- Why / next: the binding constraint is UNCHANGED but the mechanism for it now EXISTS — a real
  decision-time alpha producing model_prob != crowd. The single highest-EV unlock is still OA-11
  (the 7-day-lead corpus); once it lands, fit the bucket model on the training 60%, run the 60/40
  OOS test through walk_forward + the B2 gate, and report Brier improvement + net PnL with the
  bootstrap CI. Loop-buildable next (no data): a research/owner fit entry point + B3 promotion once
  a model passes. E5 (windows) + E2 (drift) are now wired so the moment real trades flow they are
  measured + monitored honestly. No DoD/floor box ticked.

## 2026-06-30 — Research Run 10: Academic synthesis + EXP-003 proposed; Polymarket-v1 HuggingFace dataset identified as OA-11 bypass

- Hypothesis (falsifiable): **EXP-003 (Domain-Calibrated Political Strategy):** Binary
  Polymarket markets categorised as "politics" or "elections" are systematically more
  underconfident than other categories at ALL decision horizons — the crowd compresses
  prices toward 50% via partisan bilateral cancellation. A `CalibrationBucketStrategy`
  fitted exclusively on political-category resolved markets (using the EXISTING
  mechanism in `calibration_bucket_strategy.py`) produces positive net Brier improvement
  AND positive net PnL on the OOS 40%, controlling for the general horizon effect.
- Min sample N: 100 resolved political/elections markets; ≥30 per price bucket for
  bucket-level claims. Political markets need a longer sampling window than general
  markets (fewer per month on Polymarket), so the full Polymarket-v1 HuggingFace corpus
  (1.3M markets) is the preferred data source; alternatively, OA-11 with an explicit
  `--categories politics,elections` filter.
- OOS result: **insufficient data** — no real resolved political-category corpus yet.
  The EXP-002 mechanism (CalibrationBucketStrategy) is already built; only the domain-
  filtered corpus is missing. No OOS edge claimed.
- Calibration (Brier / reliability): not measured — no real resolved predictions yet.
- Costs modeled: 2% fee + 0.5% slippage (cost_model.py). Political markets at 65–90%
  YES trade at moderate liquidity; impact model applies.
- Verdict: **proposed** (EXP-003; see GROWTH_STATUS experiments[])
- Why: Multiple independent 2026 sources converge on domain-specific political
  miscalibration as the strongest structural edge hypothesis:
  (1) **Le 2026 (arxiv 2602.19520, 292M trades, Kalshi + Polymarket):** calibration
  decomposes into four components explaining 87.3% of variance. The DOMINANT component
  is political underconfidence: prices chronically compressed toward 50% at ALL horizons
  via bilateral partisan cancellation. Favorites underpriced, longshots overpriced —
  the calibration slope is > 1.0 for political favorites across all time-to-resolution
  windows. The Polymarket political user base shows less large-trade amplification than
  Kalshi, but the structural bias is present on both.
  (2) **Prediction Arena (arxiv 2604.07355, live Kalshi trading Jan–Mar 2026):** 6
  frontier LLMs ALL lost money on Kalshi (-16% to -30.8% over 57 days). On Polymarket,
  average loss was only -1.1%, with grok-4-20-checkpoint at 71.4% settlement win rate.
  Key finding: LLMs are not calibrated enough to profitably trade autonomously — but
  the Polymarket vs Kalshi gap suggests Polymarket is structurally more amenable.
  (3) **PolyBench (arxiv 2604.14199, 36,165 predictions on 38,666 markets, Feb 2026):**
  only 2 of 7 LLMs achieve positive CWR: MiMo-V2-Flash (+17.6%) and Gemini-3-Flash
  (+6.2%). Gemini models consistently show positive calibration. This REFINES B4
  (per-market LLM research): if built, use GEMINI (we already have the API key) and
  target domains where it has documented positive calibration. A B4 design using
  autonomous LLM trading is NOT the right pattern (Prediction Arena proves it loses
  money); a targeted "LLM as a research tool for specific domains" design is better.
  (4) **Insider trading on Polymarket (arxiv 2605.02286, 2605.00459; Bloomberg 2026):**
  ~25% of large longshot bets ($2500+, <35%, near-resolution) resolve YES vs 14%
  baseline — a 1.8× lift. On-chain observable; commercial tools already track it.
  Implication: a DEFENSIVE adverse selection filter (skip markets with recent large
  longshot activity) is in-scope and improves risk-adjusted returns without requiring
  insider knowledge. It is NOT the primary alpha.

### MAJOR DATA FINDING: Polymarket-v1 HuggingFace Database (arxiv 2606.04217, June 2026)
  The complete on-chain trade archive of Polymarket's CTF Exchange (2022-11-21 to
  2026-04-28): 1.20 billion trade records, 1.30 million markets, $61B nominal volume,
  CC-BY-4.0 license, available at HuggingFace (TimeSeventeen/Polymarket-v1). Three
  layers: `OrderFilled/` (raw trades), `daily_aligned/` (cleaned + market metadata +
  event-normalized fields including resolution outcome), `CTF/` (lifecycle events including
  resolutions). Parquet format, no Polymarket API egress required.
  **Critical implication:** if the owner can access HuggingFace (a separate domain from
  gamma-api.polymarket.com), the `daily_aligned/` layer provides pre-resolution price
  history + outcomes for 1.3M markets — a superset of what OA-11 retrieves from the
  live API. This could **bypass OA-11 entirely** for historical research. Proposed as
  OA-16 (new owner action). A `polymarket_v1_hf_fetcher.py` that reads the Parquet
  `daily_aligned/` layer and assembles leakage-safe `HistoricalMarket` records is
  loop-buildable once the owner confirms HuggingFace egress is accessible.

### How EXP-003 could be wrong (adversarial pre-mortem)
1. Polymarket's international / crypto-native political user base may not show the same
   partisan bilateral cancellation as Kalshi's US-regulated user base → the Le 2026
   effect may be Kalshi-specific; Polymarket political markets may already be better
   calibrated.
2. The political compression bias may be strongest at >30 days (when partisan uncertainty
   is highest) and near-zero at 7 days (when outcomes are nearly certain for most
   markets) → same 70%-pinned-near-resolution problem as the 2-day corpus.
3. With only ~10–30 active political markets per month on Polymarket, accumulating
   100+ resolved political markets takes 4–6 months → N is slow to accumulate.
4. The Polymarket-v1 HuggingFace data covers 2022–2026 elections; the calibration
   pattern may be different in current (post-2026-election-cycle) markets.
5. Bucket overfitting: with only ~100 political markets, the 65–90% bucket may have
   fewer than 30 records → CalibrationBucketStrategy abstains → strategy produces no
   signal.

### Candidate alphas NOT proposed this run (reasons)
- **Insider-signal copying (following large longshot bets):** Ethically and legally
  gray; and the commercial tools (Polysights) already exploit it, so the edge is
  competed away. Auto-reject as private-data inference under the playbook. The
  DEFENSIVE version (adverse selection filter) stays in scope and is noted above.
- **LLM autonomous trading (full B4):** Prediction Arena proves 5/6 models lose money
  at the current state of the art. The right B4 design is targeted LLM research as a
  TOOL, not an autonomous trader. Gated on B2 producing a PASSING eval — correct.
- **Manifold Markets as proxy test bed:** Public API, resolved questions, calibration
  data. HOWEVER: Manifold is play-money / low-stakes / different user base. A positive
  Manifold calibration result does NOT transfer to Polymarket (different incentive
  structures). Useful for apparatus testing but NOT for edge validation.
- **Cross-venue Kalshi/Polymarket arb:** Still bot-dominated ($40M captured by bots
  2024–2025). Kalshi now exceeds Polymarket in volume ($14.8B vs $9B April 2026).
  Confirmed as out of scope for a non-speed bot.
- **Maker (limit order) strategy:** The GWU/UCD 2026 paper studies maker-taker dynamics
  on Kalshi. Makers may profit vs takers. However, building a market-making strategy
  requires bid-ask inventory management, hedging, and real-time depth data — a
  significantly more complex engine than the current taker-only design. Defer until
  current alpha paths are validated.

### Self-validation (data sources this run)
- Le 2026 (arxiv 2602.19520): preprint, 292M trades, Kalshi + Polymarket. Credible but
  not peer-reviewed yet. Cannot reproduce on our data (egress blocked).
- Prediction Arena (arxiv 2604.07355): preprint, live Kalshi/Polymarket trading. Cannot
  reproduce.
- PolyBench (arxiv 2604.14199): preprint, 38K markets, Feb 2026. Cannot reproduce.
- Polymarket-v1 (arxiv 2606.04217): confirmed on arxiv + HuggingFace page. Dataset
  existence confirmed; format confirmed (daily_aligned Parquet with metadata). HuggingFace
  accessibility from our env: NOT YET TESTED (proposed OA-16 for owner to verify).
- Insider trading research (arxiv 2605.02286, 2605.00459): preprints. Bloomberg corroboration.
- All findings above are DATA, not claims. NONE may be reported as an edge without OOS
  + significance + calibration validation on our own real corpus.

## 2026-07-01 — Research Run 11: HF/Data-API egress CONFIRMED blocked from this env; comparative Polymarket-vs-Kalshi calibration nuance; URGENT integrity finding (untracked whale/weather strategies live with a fabricated whale-seed)

- Hypothesis (falsifiable): n/a — this run is research + a self-validation/audit pass, not
  a new alpha test. Binding constraint UNCHANGED: no real OOS corpus exists; EXP-001/002/003
  remain proposed, blocked on the same data dependency (OA-11 / OA-16).
- Min sample N: n/a.
- OOS result: n/a — no edge claimed or tested this run.
- Calibration (Brier / reliability): not measured this run.
- Costs modeled: n/a.
- Verdict: **edge-not-proven** (research + integrity audit only).
- Why:

### (1) Self-validation: HuggingFace AND the Polymarket Data API are ALSO egress-blocked from this environment (new confirmed fact, not assumed)
  OA-16 proposed HuggingFace (`huggingface.co`) as a bypass for the egress-blocked Gamma/CLOB
  APIs (OA-11), on the theory that it is "a separate domain" that might be reachable. This run
  tested that theory directly from the autonomous env's own proxy: `curl https://huggingface.co/...`
  → **403 CONNECT reject** (`gateway answered 403 to CONNECT`, confirmed via the proxy's own
  `/__agentproxy/status` diagnostic, not just an app-level error). `data-api.polymarket.com`
  (the public, no-auth Data API that `whale_feed.py` depends on for `/holders`/`/trades`) was
  independently tested and is **also 403-blocked** the same way. **Conclusion: this specific
  autonomous env blocks egress by policy at a broad scope (Polymarket + HuggingFace + at least
  one more independent domain), not a narrow Polymarket-only allowlist gap.** OA-16 step 1
  ("verify HuggingFace egress is accessible") must be run from the OWNER's own network/host —
  it cannot be self-verified by the loop, and a future research run should not re-attempt it
  from this env expecting a different result. This narrows, not widens, the near-term paths to
  real data: OA-11 (owner host) and OA-16 (owner host) are the ONLY two live options; a loop-only
  bypass does not exist.

### (2) New research this run: Polymarket may already be BETTER calibrated than Kalshi (nuances EXP-002/EXP-003 confidence DOWN, not up)
  A secondary analysis (Medium, citing Calibration City — 671,732 markets — and brier.fyi — 971
  markets linked identically across both platforms by outcome) reports Polymarket showing
  **better** Brier-score calibration than Kalshi both at market close and time-averaged, with
  Kalshi calibration "deteriorating" more toward close. This is the OPPOSITE direction implied
  by treating Le 2026 (Kalshi-anchored, 292M trades across both venues) as if its magnitude
  transfers 1:1 to Polymarket for EXP-002 (horizon effect) and EXP-003 (political
  underconfidence) — both of which already carry "may be Kalshi-specific" as adversarial
  pre-mortem item #1/#2. A second, contradicting secondary source claims the reverse on raw
  accuracy (Polymarket 67% "right" vs Kalshi 78% vs PredictIt 93%) — but accuracy and
  calibration are different measures, and both sources are non-peer-reviewed aggregator
  write-ups, not reproducible by us (all direct fetches of the primary comparison articles
  403'd; only search-result summaries were obtainable). **Treated as DATA, not a claim:** this
  is not proof the Polymarket effect is smaller — it is a second, independent secondary source
  pointing the same direction as our own pre-mortem concern, which should raise (not lower) the
  bar for treating a Kalshi-shaped finding as automatically applicable to Polymarket. Added to
  EXP-002/EXP-003 `how_it_could_be_wrong` in GROWTH_STATUS.
  Two more academic papers surfaced (SSRN: "Statistical Arbitrage in Binary Prediction Markets"
  — Nunes; "From Forecasting Tool to Financial Asset: Evidence of Persistent Arbitrage in
  Prediction Markets" — Krause) that are directionally supportive of the already-built
  `SameMarketArbitrageStrategy` (arbitrage persists, is not fully competed away). Full text was
  unreachable (SSRN delivery links 403'd) — **cannot verify sample/methodology, so this is
  logged as an existence-only DATA point, not evidence for anything.**

### (3) URGENT integrity finding: two entire strategies (whale copy-trading, weather arbitrage) are wired LIVE into the default scanner, untracked in ROADMAP/RESEARCH_MEMORY, and one has a FABRICATED data seed
  While diagnosing the binding constraint ("a losing/unvalidated strategy to retire?" per the
  playbook), I checked what strategies are actually live vs. what is documented. Two files exist
  and are unconditionally wired into `orchestrator._build_default_scanner()` —
  `WhaleCopyTradingStrategy` (`strategies.py`) backed by `whale_feed.py`, and
  `WeatherArbitrageStrategy` backed by `noaa_weather.py` — **neither of which is mentioned
  anywhere in ROADMAP.md or has ever been logged as "proposed" in this file.** The 2026-06-28
  entry above explicitly logged whale copy-trading as **NOT proposed** ("auto-rejects under
  private data exclusion if wallet identities are non-public") and weather arb as "interesting
  but niche... needs validation before any edge claim" — yet both are live in the paper scan
  loop today, with zero backtest, zero B3 registry entry, zero tests (`find backend -iname
  '*whale*test*'` → nothing), and zero ROADMAP tracking. This is a documentation/BUILDS≠WORKS
  gap: the loop is running strategies nobody validated or even recorded as attempted.
  **Worse, and independently confirmed (not assumed): `whale_feed.py`'s `KNOWN_WHALES` hardcoded
  seed list pairs real trader names with WRONG on-chain addresses.** The real "Theo4" wallet
  (per Polymarket's own public profile, cross-checked via web search) is
  `0x56687bf447db6ffa42ffe2204a05edaa20f55839`; the code hardcodes `0xf0a3ceb5db0a53c12e1e52e61a8e8e5b4e2e3fc9`
  for the same name — a completely different address. The third seed entry,
  `0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0` ("SeriouslySirius"), is a **sequential hex
  placeholder pattern** (a1-b2-c3-d4…) — self-evidently not a real wallet, no external lookup
  needed. This is a fabricated-legitimacy risk: a named, specific-looking "known profitable
  whale" with an invented address gives false confidence that the strategy is using real public
  on-chain signal when it structurally cannot be for at least these seeds. It compounds with
  finding (1): the dynamic `/holders` discovery this feed also uses to self-correct is *itself*
  unreachable from this env (`data-api.polymarket.com` 403), so in THIS env the feed runs on
  the fabricated seed ALONE, silently (try/except at `strategies.py:1483` logs a warning and
  continues — "strategies still run"), inflating the scanner's reported strategy count with a
  strategy contributing no real signal.
  **This is a bug-fix / governance finding, not a validated edge — I am not proposing it as an
  alpha and am not touching the code (out of research-agent scope; the factory owns strategy
  code).** Recommended for the factory (logged to GROWTH_STATUS `next_actions`, loop-buildable,
  no owner action needed): (a) fix or delete the fabricated `KNOWN_WHALES` seed — replace with
  addresses sourced verifiably from Polymarket's own public leaderboard/API at build time, or
  drop the hardcoded seed entirely and rely solely on dynamic `/holders` discovery; (b) gate
  both `WhaleCopyTradingStrategy` and `WeatherArbitrageStrategy` out of the unconditional default
  scanner until each has a B3 registry entry (`PROPOSED`) and at least a forensic audit
  (`strategy_audit.py`, the same harness already built for the cross-market alphas) proving they
  fire on real-shaped data before being wired; (c) add a ROADMAP line item for each so the
  factory's own "evidence-based done" discipline applies retroactively.

### Candidate alphas NOT proposed this run (reasons)
- **Whale copy-trading (EXP-004, deferred):** now CODE-EXISTS (unlike prior runs where it was a
  pure hypothesis) but cannot be evaluated honestly until (a) the fabricated seed is fixed/removed
  and (b) `data-api.polymarket.com` is reachable from wherever the validation runs (owner/host
  scope, same class of blocker as OA-11/OA-16). Until then this stays "insufficient data" and is
  NOT promoted to a numbered EXP with a min-N/OOS plan — proposing a formal experiment on top of
  a known-fabricated input would itself be a leakage/integrity failure.

---

## 2026-07-02 — WhaleCopyTradingStrategy: consensus dilution (factory-surfaced, NOT a research run)
- Context: a factory deep-audit scout (correctness lens) found that `WhaleCopyTradingStrategy.scan`
  computes `buy_consensus = len(buy_wallets) / n_tracked`, but `buy_wallets` can include wallets
  NOT in `self.tracked_wallets`: `record_trade` adds ANY wallet's trade to `_recent_whale_trades`
  (strategies.py ~1104) while only appending to the tracked list if the wallet is tracked (~1109),
  so `scan`'s last-hour filter can populate `buy_wallets` with untracked whales.
- Effect (if wired): dilutes the "proven-wallet" consensus signal with unproven wallets — weakens
  whatever alpha tracking high-performers was supposed to give. Suggested fix: filter to
  `t["wallet"].lower() in self.tracked_wallets` when building `buy_wallets`.
- Verdict: edge-not-proven — NOT fixed standalone. WhaleCopyTradingStrategy is GATED OFF (B7,
  `ENABLE_UNVALIDATED_STRATEGIES`) and B7 mandates a B3 `PROPOSED` entry → `strategy_audit.py`
  forensic pass → OOS `walk_forward` validation before re-enabling. Polishing gated-off code fails
  the value bar (2026-07-01 anti-padding lesson); this correctness fix belongs INSIDE that B7
  re-validation, where the strategy's whole logic is re-derived — recorded here so it isn't lost.
- Why: still additionally blocked on `data-api.polymarket.com` reachability (egress) to feed real
  wallets at all — same owner/host class as OA-11/OA-15/OA-16.

## 2026-07-02 — Research Run 12: URGENT — the live forward-paper track record (OA-17) is being silently corrupted by a Postgres FK bug in an UNPATCHED write path; the D2 category cap has become a de facto global freeze; first live fires of `logical_implication`/`adaptive_threshold` on real question text (insufficient data)

- Hypothesis (falsifiable): n/a — this run is a self-validation / production-forensics pass, not a
  new alpha test. Per the playbook's step 3 ("diagnose the binding constraint... a data/latency/cost
  issue?"), I audited the now-live `live-validation.yml` GitHub Actions workflow (runs every 6h on a
  network-permitted GH-hosted runner, confirmed reaching real Gemini + real Polymarket + a Neon
  Postgres `DATABASE_URL` secret since OA-17 was applied) to see whether the forward paper track
  record it was built to produce is actually accumulating usable evidence. It is not — for a
  structural, currently-active reason, not a data-availability one.
- Min sample N: n/a.
- OOS result: n/a — no edge claimed or tested this run.
- Calibration (Brier / reliability): not measured this run.
- Costs modeled: n/a.
- Verdict: **edge-not-proven** (production-integrity audit; a real, currently-active bug, not an
  alpha finding). Findings below are DATA, self-validated by directly reading GitHub Actions job
  logs (run IDs + timestamps cited) and cross-referencing the exact code paths — not speculation.

### (1) URGENT — every order the live forward-paper loop executes fails to persist (Postgres FK violation), confirmed live today, despite two prior "fixes" landing before this run
  `scripts/run_paper_cycle.py` → `orchestrator.scan_and_execute()` → `orchestrator._persist_order()`
  (`backend/app/prediction_markets/orchestrator.py:1034-1104`) builds `PredictionOrder(portfolio_id=1,
  ...)` and `PredictionPosition(portfolio_id=1, ...)` directly and calls `session.add(...)` with NO
  call to `_ensure_default_portfolio()` — the guard added in PR #139 that seeds the parent
  `PredictionPortfolio(id=1)` row before insert. That guard lives ONLY in
  `prediction_markets/persistence.py`'s `save_order`/`save_position` — functions the live forward
  loop never calls (verified: zero call sites for `persistence.save_order`/`save_position` outside
  `persistence.py` and its own tests). A SECOND, broader fix (PR #140, "Seed the default portfolio in
  init_db — real fix, covers ALL order writers") added a best-effort seed of `PredictionPortfolio(id=1)`
  inside `init_db()` (`backend/app/db/database.py:106-117`), which `run_paper_cycle.py` does call
  before scanning. **Despite both fixes being present in the exact commit these runs used
  (`af7c730`, confirmed via `git show af7c730:...`), the FK violation is happening live, today:**
  workflow run [28563250362](https://github.com/subhsubh24/LLM-Quant/actions/runs/28563250362)
  (2026-07-02T03:28–03:31 UTC) logged **6 consecutive** identical failures —
  `psycopg2.errors.ForeignKeyViolation: insert or update on table "prediction_orders" violates
  foreign key constraint "prediction_orders_portfolio_id_fkey" — Key (portfolio_id)=(1) is not
  present in table "prediction_portfolios"` — for every one of that scan's 8 "executed" orders
  (strategies `logical_implication` and `adaptive_threshold`, real markets: Fed rate decision,
  LeBron James team markets, Strait of Hormuz, Argentina/Cabo Verde, Croatia). Each failure is caught
  by a bare `except Exception as e: logger.error(...)` in `_persist_order` and the loop continues
  silently — so `run_paper_cycle.py --json`'s own reported `"executed": 8` count and the `"executions"`
  list are **NOT a lie about what was decided, but ARE a lie about what got durably recorded** — none
  of those 8 fills exist in the Neon DB after the process exits. No "init_db: default-portfolio seed
  skipped" warning appears in the surrounding log (I fetched the full step output, not just a tail),
  so the seed's own try/except did not visibly fire — the exact mechanism (a session/transaction
  visibility gap, a swallowed warning at a suppressed log level, or something else) is **unconfirmed
  and needs fresh RCA**, but the OBSERVED FACT — every execution in this run failed to persist,
  in the exact commit both "fixes" were supposed to cover — is confirmed directly from raw logs, not
  inferred.
  **Why this matters:** OA-17 (owner-authorized, Neon `DATABASE_URL` secret set this week) exists
  specifically to build a durable forward paper track record across restarts. If `_persist_order`
  silently fails on every fill, **the accumulated evidence this mechanism was built to produce may
  not exist at all** — GROWTH_STATUS's `total_trades: 0` / `weekly_pnl_paper: null` could remain
  accurate not because no signal fires (it does — see finding 3) but because the fills that DO fire
  are being silently discarded before they reach durable storage.
  **A related, structural gap this exposes:** the whole bug class here is "SQLite doesn't enforce FK
  constraints by default; Postgres does" — meaning the blocking CI gate, which runs exclusively
  against SQLite, **cannot catch this class of bug by construction**. This is the SECOND time this
  exact class of bug has needed a fix (#139, then #140 "covers ALL order writers") and it is STILL
  live in the one code path that matters (the orchestrator's own `_persist_order`, never touched by
  either fix). A cheap, durable closure: a test that runs the real order-persist path against a
  SQLite engine with `PRAGMA foreign_keys=ON` (SQLite supports enforcing FKs per-connection; off by
  default) — or a Postgres-backed CI job — so this class of regression fails the gate instead of
  failing silently in production. (Independently confirmed via a 2026 web search: SQLite-vs-Postgres
  FK-enforcement parity gaps in CI are a well-documented, common failure class — this is not a novel
  problem, and the standard fix is exactly the PRAGMA/Postgres-parity test named above.)
  **Recommended for the factory (loop-buildable, no data/egress/owner action needed):** (a) make
  `orchestrator._persist_order` call `persistence.save_order`/`save_position` (or `_ensure_default_portfolio`
  directly) instead of maintaining a third, parallel, unguarded write implementation — one persist path,
  not three; (b) add the FK-pragma-enforced SQLite (or Postgres) regression test named above to the
  blocking gate so this class of bug cannot silently ship again; (c) once fixed, treat all
  forward-paper data collected before the fix lands as **unreliable / do not read edge into it** (the
  same caution ROADMAP D8 already states for the pre-D8 era, now extended for a different reason).

### (2) The D2 per-category exposure cap has become a de facto GLOBAL cap, freezing the forward loop
  `risk_manager.py:157` computes `category = opportunity.market.category or "General"`, but
  `polymarket_client.py:799` parses `category=raw.get("category", "")` — Polymarket's Gamma API market
  objects do not reliably populate a plain `category` field (confirmed empirically: real markets ingested
  live today — Bitcoin price, all 2026 FIFA World Cup winner candidates, Fed rate decisions, LeBron
  James team markets, a Brazilian presidential election market — were ALL bucketed as `"General"` in
  today's live logs, despite spanning crypto/sports/macro/politics). Compounding this, `_market_categories`
  (the map `_get_category_exposure` uses to bucket EXISTING `executor.positions`, including ones
  rehydrated from the DB per D8) is a plain in-memory dict re-initialized empty on every fresh process
  — and the GH Actions forward-paper cycle IS a fresh process every 6h. So rehydrated positions ALSO
  default to `"General"` (as ROADMAP D8 already flagged as an "accuracy note"), stacking with the
  above to mean essentially ALL exposure, from ALL markets, in ALL runs, is counted against the single
  `$200` `"General"` bucket (`risk_manager.py:43`). **Confirmed effect, live, today:** by workflow run
  [28580282836](https://github.com/subhsubh24/LLM-Quant/actions/runs/28580282836) (2026-07-02T09:36,
  the most recent scheduled run), `"General"` exposure sat at `$164.18`, and **every one of that run's
  98 scanned opportunities was skipped** with reason `"Category 'General' exposure: $164.18 + $50.00 >
  $200.0"` — 0 executed, 0 evidence added. Since open positions don't decay until resolution (most of
  the fired markets — FIFA World Cup winner, Fed decision, elections — resolve weeks to months out),
  this is not a one-run blip: **the loop will likely keep finding real opportunities and skipping
  100% of them until either a position resolves or the categorization bug is fixed.** This is a
  DIFFERENT, deeper bug than the one D8's proof already named (D8 only flagged rehydrated positions
  defaulting to General; this finding shows FRESHLY-SCANNED markets do too, because the upstream
  `Market.category` field is unpopulated by the venue data itself) — the per-category diversification
  design (D2) is not just inaccurate post-rehydration, it is **structurally non-functional on real
  Polymarket data** and now the single active bottleneck starving the forward-paper track record of
  new evidence. **Recommended for the factory:** derive `category` from a real signal Polymarket does
  populate for most markets (e.g. `raw.get("tags")`, event/series grouping, or a keyword-based
  fallback classifier) rather than a field that is empty in practice; and/or persist `_market_categories`
  (or the category on the `PredictionPosition` row itself, which IS in the schema per `orchestrator.py:1091`
  — already stored, just not READ back on rehydration) so cross-process category exposure is accurate,
  not reset to "General" every restart.

### (3) First live fires of `logical_implication` and `adaptive_threshold` on real question text — a genuine mechanism confirmation, still "insufficient data" for any edge claim
  The 2026-06-29 forensic audit (`strategy_audit.py`) found `LogicalImplicationDetector` fired **0**
  signals on the committed 54-record sterile fixture (no real question text/grouping). Today, on LIVE
  Polymarket markets with real question text, it fires repeatedly and plausibly: e.g. `"Will LeBron
  James play for the Los Angeles Lakers/Miami Heat/Golden State Warriors in 2026-27"` (a genuinely
  mutually-exclusive candidate set) and the 2026 FIFA World Cup winner candidates (also MECE) — a
  believable real-world use of the B5-hardened content-token relatedness screen, not an obvious
  repeat of the boilerplate-phantom-signal bug from 2026-06-29 (these are substantively different,
  content-rich questions, not template text). **This is NOT an edge claim** — no resolutions exist yet
  (all fired positions are still open), N is under 10 real fills across the runs inspected, there is no
  OOS split, and per finding (1) most of these fills likely never even reached durable storage. A
  second, notable risk flag: every fired `logical_implication` trade seen today bought a **near-zero
  price longshot** (`$0.0025`–`$0.0165`, i.e. 0.25¢–1.65¢) with a large reported edge (21%–35%) — this
  is exactly the "near-certainty-NO / deep longshot" regime EXP-002's pre-mortem already flagged as
  having the highest real-slippage risk (thin book depth on far-OTM contracts; the modeled 0.5%
  slippage may be a significant underestimate there). **Treated as "insufficient data," per playbook
  discipline** — worth watching once (1) and (2) are fixed and a real accumulating track record exists,
  but not worth a formal EXP-00N proposal yet (no resolutions, no OOS, and the underlying persistence
  is currently broken so the "track record" isn't really accumulating).

### (4) Confirmed (not just theorized): GitHub Actions runners have working Polymarket + Gemini egress — de-risks OA-13 Option B
  `live-validation.yml`'s `live_integration_smoke.py` step reports `[OK] polymarket: parsed 3 real
  resolved markets` on every run inspected, and `run_paper_cycle.py` successfully scans real live
  Polymarket markets each time. This is DIRECT, repeated, operational proof (not a one-off test) that
  GitHub-hosted runners are NOT subject to the autonomous loop's own egress block (confirmed
  Polymarket/HuggingFace/Data-API 403 in Research Run 11, 2026-07-01). This resolves the network-side
  uncertainty in OA-13 Option B (a scheduled `refresh-polymarket-data.yml` data-refresh workflow,
  staged in `docs/ci/PROPOSED_DATA_REFRESH.md` but never applied) in the affirmative — the egress
  works, proven by every `live-validation.yml` run since #143. The only remaining step is the owner
  applying the staged workflow file (the loop cannot write `.github/`).

### Self-validation (sources this run)
- All findings (1)-(2)-(4) are from directly reading GitHub Actions job logs via the `github` MCP
  tool for `subhsubh24/llm-quant` `live-validation.yml` runs
  [28562734388](https://github.com/subhsubh24/LLM-Quant/actions/runs/28562734388),
  [28563250362](https://github.com/subhsubh24/LLM-Quant/actions/runs/28563250362),
  [28563706937](https://github.com/subhsubh24/LLM-Quant/actions/runs/28563706937),
  [28580282836](https://github.com/subhsubh24/LLM-Quant/actions/runs/28580282836) (2026-07-02), cross
  referenced against the exact code at `orchestrator.py:1034-1104`, `persistence.py:37-64`,
  `database.py:106-117`, `risk_manager.py:43,157-160,294-298`, `polymarket_client.py:799`, and `git
  show`/`git log` to confirm which fixes were/weren't present in the commit those runs executed.
  Nothing here is inferred without a log line or a code line backing it.
- Finding (3)'s "logical_implication fired 0 on the sterile fixture" baseline is the existing
  2026-06-29 RESEARCH_MEMORY entry (re-cited, not re-verified this run).
- External web search this run (generic Polymarket-strategy blog content, 2026) added no
  evidence-grade findings beyond what's already in this file — SEO/marketing-tier sources, not
  academic. Not cited as data. One useful corroboration: independent 2026 sources confirm the
  SQLite-vs-Postgres FK-enforcement CI gap is a well-known failure class with a standard fix
  (PRAGMA-enforced SQLite or Postgres-parity tests in CI) — supports the recommendation in (1).

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. This run's highest-EV action is fixing (1) and (2) so the existing
  EXP-002/EXP-003 mechanism (`CalibrationBucketStrategy`) AND the newly-observed `logical_implication`/
  `adaptive_threshold` live fires (finding 3) can actually accumulate a real, durable, evaluable
  forward track record — proposing a new numbered experiment on top of a currently-broken persistence
  layer would itself be an integrity failure (the same discipline applied to the 2026-07-01
  whale-seed finding).
