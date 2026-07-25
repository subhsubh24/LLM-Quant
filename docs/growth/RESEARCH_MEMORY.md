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

## 2026-07-05 (3rd probe) — B8 cross-venue coherence: structured-strike + quote-SOURCE probe (one level deeper than the 2nd probe)
- **Context:** the 2nd probe found Kalshi HAS 254 crypto series with strikes in structured `cap_strike`/`floor_strike` fields but concluded "multi-run data-eng." This probe went one level deeper — directly hit the Kalshi crypto series with their structured fields to pin the exact remaining data path (egress open, HTTP 200 all venues).
- **Method (reproducible):** `curl`/`httpx` against `api.elections.kalshi.com/trade-api/v2`: `GET /series?category=Crypto` (→ 254 series); `GET /markets?series_ticker=KXBTCD&status=open` etc. (inspect `floor_strike`/`cap_strike`/`strike_type`/`yes_bid`/`yes_ask`/`volume`); `GET /markets/{ticker}/orderbook` for the flagship year-end BTC market; `GET /series/{s}/markets/{t}/candlesticks`.
- **Findings:**
  1. **Structured strikes are clean + directly parseable** — every crypto market carries `floor_strike`/`cap_strike` + `strike_type ∈ {greater, less, between}` (e.g. `KXBTCD-26JUL06-T72249.99` floor=72249.99 "greater" → daily terminal; `KXBTC` "between" range markets; `KXBTCMAXY-26DEC31-109999.99` floor=109999.99 "greater" → year-end barrier). So the structured-strike parser (blocker i from the 2nd probe) is concretely buildable against real fixtures.
  2. **DECISIVE quote-source correction (the deeper finding):** the `/markets` LIST feed returns NO quotes/volume even per-series — **0 of 254** crypto markets carry `yes_bid`/`yes_ask`/`volume`. BUT the quotes DO EXIST in the **`/markets/{ticker}/orderbook`** endpoint: `KXBTCMAXY-26DEC31-109999.99` returned a real, deep YES/NO orderbook (`no_dollars` [[0.01,8531.08],[0.02,10870.00],…], a full book). So the prior runs' blocker "Kalshi has no quotes" is more precisely **"the client reads the wrong endpoint — live quotes live in the per-market orderbook, not the list feed."**
  3. Settled year-end series are empty (2026 bets settle 2027 → no resolved candlestick history yet on those); the candlesticks endpoint requires a `start_ts` query param.
- **Conclusion:** UNCHANGED (B8 is a multi-run data-eng effort, NOT built this run — no validated co-listed universe to exercise infra against → speculative per DECISION COROLLARY), but the remaining path is now PINNED: per-series discovery → structured-strike parser → **per-market orderbook-quote assembly** → touch/barrier/terminal semantic classification → curated co-listed BTC/ETH universe → dual-venue OOS harness (candlesticks w/ `start_ts`).
- **Lesson (mirror, one level deeper):** each run's real-data probe should go ONE level past the prior finding — "no quotes on the list feed" becomes "quotes live in the orderbook endpoint" only by actually hitting the orderbook. The probe keeps converting a vague blocker into a precise, buildable one without faking a result or building speculative unwired infra.
- **NOT proposed as a numbered EXP** (no OOS run — a data-path feasibility probe, not an alpha test; the honest "not runnable yet + the exact next data step").

---

## 2026-07-05 — B8 cross-venue coherence (Polymarket ⟷ Kalshi): real-data feasibility probe
- Hypothesis (falsifiable): the built B8 event-matcher (`cross_venue_matcher.find_cross_venue_matches`, #179) can find enough GENUINE same-event pairs across live Polymarket + Kalshi markets to run a cost-net coherence OOS backtest — a structurally different edge from the refuted bucket-calibration family (it trades venue DISAGREEMENT, not out-calibrating a sharp crowd).
- Min sample N: needed ≥ a handful of tradeable matches (coherence ≥ 0.5) to justify building the full resolved-pair OOS harness.
- OOS result: **NOT RUNNABLE this run — 0 tradeable matches.** Fetched 547 Polymarket + 200 Kalshi binary markets (egress open). `find_cross_venue_matches` → 33 candidate pairings, ALL false (sports/player-name token overlap, no numeric threshold) and ALL below the 0.5 trade bar (max coherence 0.375). The matcher's conservatism correctly refuses the false pairs → zero would trade. **ROOT BLOCKER: the Kalshi `/markets` LIST endpoint returns NO usable quotes** — all 200 open markets parsed `active=False` with a uniform 0.500 placeholder price (0 with a real quote) and garbled multi-outcome concatenated question text (multi-leg sports events, not clean single-event binaries). So the Kalshi live-list feed is unusable for B8 as-is.
- Calibration (Brier / reliability): n/a (no trades).
- Costs modeled: n/a (no trades). The matcher/backtest already model both venues' fees+slippage (`coherence_edge`).
- Verdict: **edge-not-proven (not runnable yet)** — B8 does NOT validate this run.
- Why + NEXT (pre-registered, do NOT p-hack): B8 needs (a) a Kalshi QUOTE source with real prices — a per-market quote fetch OR the resolved-history candlesticks path (#170) — plus clean single-event binary question text; and (b) a targeted NUMERIC-THRESHOLD universe (BTC/Fed/econ) co-listed on BOTH venues (a random universe is sports-dominated, which the matcher rightly won't pair without matching strikes). Build the real dual-venue OOS harness (fetch RESOLVED markets + pre-resolution snapshots from both venues, match on numeric-threshold events, run `evaluate_cross_venue_pairs`), then require an OOS edge ≥ floor that ≥3 auditors cannot break. The probe surfaced + shipped a real fix (#232): `_yes_price` now gates on `market.active` so an untradeable market's 0.500 placeholder can't feed a fabricated cross-venue disagreement (the #101/#102/#193 fake-price class). LESSON: probe real-data feasibility BEFORE building the full harness — it turned a speculative spec-build into a decisive finding + a real fix, and it is honest about B8 being a multi-run data-engineering effort, not a one-run validation.

## 2026-07-05 (2nd probe) — B8 cross-venue coherence: RESOLVED-history feasibility (deeper than the live-list probe above)
- Hypothesis (falsifiable): the actual B8 backtest path (RESOLVED markets + pre-resolution snapshots, candlesticks #170 fixed) — not the live-list feed the 1st probe found quoteless — has enough co-listed numeric-threshold RESOLVED events across Polymarket + Kalshi to run `evaluate_cross_venue_pairs` this run.
- Min sample N: needed a handful of co-listed numeric-threshold RESOLVED pairs to justify building the dual-venue OOS harness.
- OOS result: **NOT RUNNABLE this run.** PROBE (read-only, real data, egress open): 500 resolved Polymarket markets by volume → **15** carry a confident numeric threshold via `extract_threshold` (BTC/ETH price; TOUCH semantics — "reach $150k by <month>"). 3000 settled Kalshi markets via the general `/markets` list → **0** clean single numeric-threshold binaries: the settled list is dominated by `KXMVECROSSCATEGORY` multi-leg concatenated combos ("no Target Price: $X,no Target Price: $Y") that correctly yield >1 candidate → `None` (the matcher refuses to guess). Kalshi HAS **254** crypto series (KXBTCD/KXBTCMAXY/ETHATH/…) so the numeric universe EXISTS, but reachable ONLY via per-series/per-event targeted fetching, with strikes in STRUCTURED `cap_strike`/`floor_strike` fields the matcher's title-text `extract_threshold` cannot parse.
- Calibration / Costs: n/a (no pairs).
- Verdict: **edge-not-proven (not runnable yet)** — reconfirms + DEEPENS the 1st probe.
- NEW, deeper finding (a SEMANTIC mismatch the 1st probe didn't surface): even the co-listed BTC/ETH universe resolves on DIFFERENT mechanics per venue/series — Kalshi `KXBTCMAXY`="BTC MAX reaches $X this year" (barrier), `KXBTCD`="BTC price at daily close ≥ $X" (terminal), Polymarket="BTC reach $X by <date>" (touch). Same asset, different resolution criteria → a generic numeric-strike text match would pair markets that are NOT the same event. The matcher would need per-series touch/barrier-vs-terminal semantic classification, not just strike matching.
- NEXT (pre-registered, do NOT p-hack): the B8 build is a multi-run data-eng effort — (a) per-series Kalshi discovery + a STRUCTURED-strike parser (`cap_strike`/`floor_strike`, not title text); (b) per-series semantic classification (touch/barrier vs terminal) so only truly-same-event pairs match; (c) a curated co-listed numeric universe (BTC/ETH/Fed). Building matcher infra now (unwired, no validated universe) = speculative per DECISION COROLLARY → NOT built this run. LESSON (mirror of the 1st probe + last run): a pre-registered candidate that needs real data gets a data-feasibility PROBE before a harness build; the probe here converted a would-be spec-build into a decisive, deeper finding (the structured-strike + semantic-mismatch blockers) without faking a result.

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

## 2026-07-03 — EXP-004 (proposed): Cross-VENUE coherence edge (Polymarket ⟷ Kalshi) — matcher + backtest BUILT (factory run, ROADMAP B8)
- Hypothesis (falsifiable): when the SAME real-world event is priced differently on Polymarket vs.
  Kalshi, the disagreement beyond BOTH venues' round-trip costs is a tradeable, positive-EV
  logical-consistency edge — one that does NOT require out-calibrating the crowd (unlike EXP-002/003 /
  B4a, which lost −$639 OOS against a sharp crowd). Crowds can be individually well-calibrated yet
  INCONSISTENT across venues, so this may be the more ROBUST alpha.
- Min sample N: TBD on real data (needs enough genuinely-matched cross-venue pairs; venue overlap may
  be small — a real risk to N, disclosed).
- OOS result: **NONE YET — edge-not-proven.** This run built the MECHANISM (the matcher + cost-net
  coherence primitive + a resolved-pair backtest), not a validated edge. No real dual-venue corpus has
  been run (owner/egress-blocked, same OA-11/OA-15/OA-16 dependency as every other alpha).
- Calibration: n/a (this is a consistency/arbitrage edge, not a calibration edge).
- Costs modeled: YES — the cost-net `coherence_edge` charges BOTH venues' fees+slippage via the shared
  `cost_model`; it is NEGATIVE when the venues agree (the double round-trip fee dominates) → no
  fabricated edge on an efficient cross-venue market (verified, the analog of B4a's "0 trades on a
  well-calibrated crowd").
- Verdict: proposed / mechanism-built. `prediction_markets/cross_venue_matcher.py` (#179): an
  adversarially-hardened event-matcher (content-overlap via the B5 `market_text` screen + numeric-STRIKE
  consistency incl. comparator direction + resolution-timeframe overlap; a boolean MATCH separated from a
  bounded `coherence_score`, and the TRADE gate rides the score) + the backtest that honestly models the
  resolution-DIVERGENCE downside of a wrong match. NO orchestrator/executor wiring (DECISION COROLLARY).
- How it could be wrong (pre-mortem):
  - Venue overlap is small → too few genuinely-matched pairs for significance (the N risk).
  - The event-MATCHER is the whole game: a FALSE pairing on markets that resolve on DIFFERENT criteria
    (different resolution source / settlement time / wording) manufactures a fake disagreement, and if
    the two legs resolve OPPOSITELY the position loses the whole stake. The matcher is deliberately
    CONSERVATIVE (rejects on any unconfirmed strike/direction/timeframe); still, resolution-source
    divergence on a genuinely-"same" event is the residual risk.
  - Prices are venue MIDPOINTS, not executable asks — a fired match is a candidate to verify against
    live depth, not locked profit; per-venue liquidity/impact is not yet modeled.
  - Cross-venue arb is known bot-dominated (Research Run 10) — the gap may be gone by the time we route.
- The adversarial gate broke the matcher 4× across 3 fix cycles (adjacent-strike tolerance; a
  no-threshold pair reaching the trade bar; word-form + contraction + cross-clause negation
  mis-parsing). The negation rabbit hole was ended by ELIMINATING the fragile inversion heuristic: a
  negated comparator VOIDS the strike (tightening-only — can only reject, never fabricate a match). 2
  Sonnet reviewers + 4 Opus adversarial audits (final: tightening-only holds, no tradeable false match).
- Next action (loop-buildable is DONE; the rest is owner/egress + gated): once a real Polymarket ⟷
  Kalshi corpus exists (OA-11/15/16), run the matcher over it, report the cost-net OOS coherence PnL +
  the matched-pair count, and only if it clears the floor over sufficient N with ≥3 auditors unable to
  break it does B8 become go-live-eligible (live routing far downstream, human-core).

## 2026-07-03 — Research Run 13: OA-17 freeze fix CONFIRMED live (self-validation); new candidate data source (Dune Analytics) found + confirmed egress-blocked from this env like every prior candidate; secondary favorite-longshot-bias sources are internally contradictory — no new EXP proposed

- Hypothesis (falsifiable): n/a — this run is a self-validation follow-up on Research Run 12's two
  URGENT findings + a research sweep for alternative real-data paths. No new alpha tested.
- Min sample N: n/a.
- OOS result: n/a — no edge claimed or tested this run.
- Calibration (Brier / reliability): not measured this run — still no resolved trades in the forward
  paper track record (see finding 1).
- Costs modeled: n/a.
- Verdict: **edge-not-proven** (self-validation + research only).
- Why:

### (1) SELF-VALIDATION: both Research Run 12 URGENT findings are CONFIRMED FIXED, live, on real data
  Directly inspected `live-validation.yml` job logs (not the factory's own claim) for runs spanning
  2026-07-02T09:36 through 2026-07-03T09:37 (run IDs 28580282836, 28598027672, 28617675741,
  28637890271, 28652046234). **The de-facto-global category-exposure freeze (finding 2, 2026-07-02) is
  FIXED and stayed fixed:** the 09:36 and 14:31 runs were still fully frozen (98/98 and 154/154
  skipped, `Category 'General' exposure: $164.18 + $50.00 > $200.0`), but the 19:55 run onward executed
  real trades (10/94, then 6/57, then 6/108 opportunities) across genuinely diverse categories (FIFA
  World Cup, Fed rate decision, MLB, esports, geopolitics, NVIDIA) — the fix landed same-day between
  14:31 and 19:55 on 2026-07-02, earlier than the commit-message framing suggested. **The Postgres
  FK-persist failure (finding 1, 2026-07-02) shows NO recurrence:** grepped the full log content (not
  just the tail) of all 5 runs for `ForeignKeyViolation`/exception tracebacks — none found. Both fixes
  hold up under direct evidence, not self-report — this is exactly what OA-17 was built to produce: a
  real forward-paper track record that isn't silently broken.
- **New, smaller finding this run (not urgent, logged for completeness):** `gemini: client not
  constructed (google-genai missing or key rejected at init)` appears in the smoke-test step of every
  one of the 5 inspected runs. LLM analysis is documented as optional / degrades-safely and is not on
  the scan-decision critical path (per the standing G2 hard rule), so this does not block anything —
  but it means B4 (LLM-as-research-tool, gated on B2 anyway) currently has no live Gemini connectivity
  to build against in this environment; worth a factory RCA if/when B4 work starts.
- **Diagnosis (binding constraint, still evolving honestly):** `bankroll_remaining` fell monotonically
  across the 3 live runs (335.82 → 206.22 → 153.89) as `bankroll = max_portfolio_usd($500) -
  total_exposure` (`risk_manager.py:812`, confirmed by direct code read) and this run's cycles opened
  new positions but **zero positions have resolved yet** (`"resolutions": null` in all 5 inspected
  runs). This is expected and not a new bug: several fired markets are short-dated (this week's Elon
  tweet-count window, an esports map, a within-2-weeks Iran deadline) so resolutions should start
  arriving within days; others (FIFA World Cup winner) are months out and will sit as long-dated open
  exposure. **The forward-loop's near-term binding constraint is no longer the category-cap bug — it is
  simply elapsed real time** for enough of these paper positions to resolve and produce the first real
  Brier/PnL evidence. No action needed; note it so a future run doesn't mistake "still 0 resolutions" a
  few days from now for a new bug rather than the expected wait.

### (2) NEW candidate real-data source found: Dune Analytics unified Polymarket+Kalshi resolved-market dataset — tested and CONFIRMED egress-blocked from this env (same broad policy as gamma-api/CLOB/HuggingFace/Data-API)
  Web research (2026, Crowdfund Insider + Dune's own docs) found Dune Analytics ships a **unified,
  free-tier, no-account-required** prediction-markets dataset combining Polymarket (from Nov 2022) and
  Kalshi (from Jun 2021) — 5 public tables (trades, market details, hourly candlestick prices, 2 Kalshi
  aggregates), with **every resolved market carrying its final outcome** and hourly probability paths
  from open to settlement for major Kalshi series (Fed decisions, inflation prints). This would be
  materially easier to consume than the OA-16 HuggingFace parquet-streaming path (no `datasets` library,
  a normal SQL/REST query) AND — uniquely among all data sources considered so far — natively spans
  **both** venues in one schema, which is exactly what EXP-004 (cross-venue coherence, proposed today by
  the factory, #179) needs and none of OA-11/15/16 individually provide.
  **Self-validation (tested directly, not assumed):** `curl` from this autonomous env's own proxy to
  `dune.com`, `api.dune.com`, and `docs.dune.com` all returned **403 CONNECT reject**
  (`gateway answered 403 to CONNECT (policy denial or upstream failure)`, confirmed via the proxy's own
  `/__agentproxy/status` diagnostic, not an app-level error) — the exact same failure signature as
  gamma-api/clob.polymarket.com, huggingface.co, and data-api.polymarket.com (Research Run 11,
  2026-07-01). **This is now the FOURTH independent domain blocked the same way, which further
  reinforces (does not newly establish) that this is a broad-scope egress ALLOWLIST policy, not a
  per-domain blocklist gap** — no future research run should expect a different domain to be a
  loop-side bypass; any new-data-source idea will hit the same wall and must be tested from the OWNER's
  own network or a network-permitted CI runner (the pattern OA-11/15/16 and OA-17 already established).
  **Caveat, disclosed honestly (not verified this run):** Dune's programmatic API requires a free
  `DUNE_API_KEY` (confirmed via Dune's own FAQ/pricing docs — the API is not fully keyless even on the
  free tier, unlike the Gamma/CLOB/HuggingFace-anonymous paths), so this is a new, distinct owner-action
  class (create a free Dune account + API key) rather than something that rides for free on an existing
  credential. Whether GitHub Actions runners (already confirmed to reach Polymarket + Gemini,
  2026-07-02 finding 4) can reach `dune.com` is **not tested this run** — plausible (mainstream SaaS,
  not typically egress-restricted) but unconfirmed; a factory build attempt on a live-validation-style
  runner would confirm it directly.
  **Not proposed as an OA / not built as a fetcher this run** — the research-agent scope is to surface
  the finding; whether to build `dune_fetcher.py` and file it as a new owner action (mirroring exactly
  how OA-16 originated: research finds the source, factory builds + fixture-tests the fetcher, THEN
  files the owner step) is a factory/ROADMAP decision, logged to `next_actions` below, not something
  this run treats as urgent (no existing capability is broken; it is a strictly-better opportunity on
  top of two already-open, already-tracked data blockers).

### (3) Secondary favorite-longshot-bias sources for Polymarket are directionally CONTRADICTORY within the same search sweep — treated as noise, not evidence, for the near-zero-price positions the live loop is currently taking
  Searched specifically because the live forward loop (finding 1) is repeatedly buying **near-zero-price
  longshots** via `logical_implication` (e.g. $0.0005–$0.0045, the same regime EXP-002's pre-mortem
  already flagged as highest real-slippage-risk). Two non-academic secondary aggregator sites
  (tradetheoutcome.com, fensory.com) surfaced in the same search sweep make **opposite-direction**
  claims about the same phenomenon: one states "retail traders overpay for lottery-ticket payouts on the
  low end" (classic favorite-longshot bias — cheap contracts are OVER-priced relative to true
  probability, i.e. bad to buy) while a companion snippet from the same sweep states "outcomes below 10%
  implied probability occur 14% of the time" (the OPPOSITE — cheap contracts are UNDER-priced, i.e. good
  to buy). Neither source is peer-reviewed, neither states its sample/methodology, and this run could not
  fetch either primary page directly (search-summary only, unreproducible by us — same discipline applied
  to the 2026-07-01 secondary-source findings). **Treated as pure noise, not directional evidence, per
  playbook discipline ("prefer insufficient data over reading noise").** This neither strengthens nor
  weakens EXP-001/002; it is logged so a future run does not treat either claim as corroboration without
  first checking whether it can be reproduced on our own real-resolution data.

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. This run is self-validation (confirming two prior URGENT fixes actually hold
  on real data) + one new data-source lead (Dune, itself blocked here) + a noise-vs-evidence check on a
  live-observed pattern. Proposing a new numbered experiment on a forward-paper track record that has
  ZERO resolved trades yet (finding 1) would be premature — the honest next step is to let real time
  pass and let resolutions accumulate, not manufacture a new hypothesis to fill the run.

### Self-validation (sources this run)
- Findings (1) are from directly reading `live-validation.yml` job logs via the `github` MCP tool for
  runs 28580282836/28598027672/28617675741/28637890271/28652046234, cross-referenced against
  `risk_manager.py:812` (`bankroll = max_portfolio_usd - total_exposure`) and `risk_manager.py:39`
  (`max_portfolio_exposure_usd = 500.0`) read directly from the current tree.
- Finding (2)'s egress test is a direct `curl` from this environment's own proxy against `dune.com`,
  `api.dune.com`, `docs.dune.com`, confirmed via `/__agentproxy/status` (not an app-level guess).
  Dune's dataset existence/schema/API-key requirement is WebSearch-sourced (Crowdfund Insider, Dune's
  own docs/pricing/FAQ pages) — treated as DATA about a candidate source, not a validated result.
- Finding (3)'s sources (tradetheoutcome.com, fensory.com) are explicitly flagged low-credibility /
  unreproduced and NOT treated as evidence for or against any hypothesis.

## 2026-07-04 — Research Run 14: MAJOR — this environment's egress to Polymarket/HuggingFace is OPEN (unlike the autonomous build env); first REAL OOS test of EXP-002 run end-to-end — REFUTED (not "insufficient data") on N=510; EXP-001 hypothesis independently strengthened on a fresh N=79 OOS slice; EXP-003 confirmed still blocked by the SAME empty-category bug on resolved-market data

- Hypothesis (falsifiable): EXP-002 (unchanged from 2026-06-29) — a `CalibrationBucketStrategy`
  fitted on the oldest 60% of a 7-day-decision-lead resolved-Polymarket corpus produces a
  significant positive net Brier improvement + positive net OOS PnL on the newest 40%, surviving
  realistic costs. This run is the first time this exact falsifiable claim has been tested on REAL
  data with N above the pre-registered floor (100) — every prior mention was "insufficient data."
- Min sample N: 100 (pre-registered in the 2026-06-29 EXP-002 proposal). This run's corpus: N=510.
- OOS result: **TESTED AND REFUTED** — two independent methodologies, same real corpus, both negative:
  (a) full expanding-window walk-forward (`scripts/validate_real_oos.py`, unmodified factory harness,
  cost-net Kelly sizing): the alpha took 46 trades, **net PnL = −$2,938.70** OOS vs. the crowd
  baseline's 0 trades / $0 (seed_hash `40951c0bd2da1ad7`, deterministic); F10 regime-slice reports
  `has_positive_edge: false`, not fragile (there is no positive edge to be concentrated). (b) a static
  chronological 60/40 split (research-agent analysis script, not a factory artifact, code below) run
  through the B2 `evaluate_calibration` significance gate: n_train=306 / n_test=204 (79 active,
  non-abstaining predictions after the model's own `min_bucket_n=30` abstention rule), improvement
  = **−0.00266** (the strategy is WORSE, not better), 95%-CI at Bonferroni `strategies_screened=2`
  (pre-registered jointly with EXP-003) = **[−0.00585, −0.00016]** — entirely below zero, i.e.
  *statistically significantly worse* than the crowd, `passes=False`. Crowd Brier on the full 510
  corpus: 0.1063 (same order of magnitude as the 2026-06-28 54-record 2-day-lead sample's 0.0933).
- Calibration (Brier / reliability): see (b) above — this IS the calibration eval EXP-002 named as
  its own gate; it ran, on real data, for the first time, and failed.
- Costs modeled: yes, unmodified `cost_model.py` (2% fee + 0.5% slippage) via the factory's own
  `walk_forward`/`cost_model` code — no cost parameters were touched for this run.
- Verdict: **edge-not-proven — REFUTED for the tested mechanism/corpus combination** (see caveats
  below before generalizing). This is qualitatively different from every EXP-002 entry so far, which
  all said "insufficient data." Recorded here as `mechanism-tested-failed`, not `retired` outright —
  see the pre-mortem below for exactly what is and is not refuted.
- Why / how this became possible this run (read before repeating "OA-11/13/16 need owner action"):

### (1) MAJOR — self-validated: THIS environment's egress to Polymarket's Gamma/CLOB/Data APIs and to HuggingFace is OPEN, unlike every prior research run's autonomous-build-env finding
  Every prior research run (2026-07-01 Run 11, 2026-07-02 Run 12, 2026-07-03 Run 13) directly tested
  and confirmed `gamma-api.polymarket.com`, `clob.polymarket.com`, `data-api.polymarket.com`,
  `huggingface.co`, and `dune.com` were ALL 403-blocked at this proxy's own `/__agentproxy/status`
  diagnostic, and concluded this was a broad-scope policy that "no future research run should expect
  a different domain to be a loop-side bypass." That conclusion is now PARTIALLY OVERTURNED by direct
  re-test, not assumption: this run's own `curl` against all five domains returned real HTTP responses
  with real content, not block pages —
  `gamma-api.polymarket.com/markets` returned a real 2020 Biden-COVID market;
  `clob.polymarket.com/markets` returned a real 2023 NCAAB market with full CLOB metadata;
  `data-api.polymarket.com/trades` returned LIVE trades from minutes before this run (an "Ethereum
  above $1,770 on July 4" market); `huggingface.co/datasets/TimeSeventeen/Polymarket-v1` served the
  real dataset page. Only `dune.com` remained 403 (4/5, not 5/5, open). This is **not** evidence the
  autonomous FACTORY build-loop's egress has changed — that is a different environment/session type
  and was not tested here — but it is direct proof that **the research-agent's own environment is not
  subject to the same block**, so "insufficient data — egress-blocked" is no longer an accurate reason
  for THIS agent to defer EXP-001/002/003 to the owner. **Recommended for the factory (loop-buildable,
  cheap, high-value): re-probe the SAME five domains from the autonomous build env on its next run**
  (the exact `curl .../markets` calls above, not just a bare domain GET) before continuing to treat
  OA-11/OA-13/OA-16 as blocked; if the factory's own env is also now open, those three owner actions
  can close without any owner step at all. This does not change PENDING_OPS by itself (that requires
  the factory's OWN confirmation, not this agent's), but it is now flagged there (below) as a live,
  falsifiable, one-`curl`-away question rather than a settled "blocked" fact.

### (2) Ran the ALREADY-BUILT, ALREADY-TESTED OA-11 pipeline for real, for the first time in a research run: 510 leakage-safe real 7-day-lead resolved-Polymarket records
  Ran `scripts/fetch_polymarket_history.py --limit 100 --max-pages 10 --order volumeNum
  --decision-lead-days 7 --min-volume 1000 --merge` (exact factory-committed script, zero code
  changes) directly from this session: **510 leakage-safe `HistoricalMarket` records**, far above
  the 100-record EXP-002 floor and the largest real corpus this project has ever evaluated (prior
  best: 54 records at a 2-day lead). Price-pinned fraction at 7-day lead: 53.9% (vs. ~70% at the
  2-day lead in the 2026-06-28 sample) — this specific, previously-untested part of EXP-002's own
  hypothesis (longer lead → less pinning → more edge headroom) is CONFIRMED directionally, even
  though the downstream edge itself failed (see above). Corpus: `yes_base_rate=0.2725`,
  `price_median=0.053`, `crowd_brier=0.1063`, spanning `decision_time` 2024-01-08 to 2026-06-24
  (the `--order volumeNum` selection surfaces the platform's all-time-highest-volume markets in
  descending order, which is why the span reaches back to 2024 rather than being a recent slice —
  disclosed as a bias below, not hidden).
  **A genuine, small, factory-actionable bug found while doing this (not an alpha finding):**
  `PolymarketHistoryFetcher.fetch_resolved_markets` (`polymarket_history_fetcher.py:181-208`) pages
  Gamma with `offset = page * limit`, and stops paging when `len(page) < limit` — the standard
  "short page = end of data" heuristic. But Gamma's `/markets` endpoint **silently caps its response
  at 100 rows regardless of the requested `limit`** (verified directly: `limit=500` still returns
  exactly 100 rows). So passing `--limit 200` or `--limit 500` — which is what EVERY existing
  documented OA-11/EXP-002/EXP-003 command in GROWTH_STATUS/PENDING_OPS recommends, including the
  script's own `--help` example — causes the loop to fetch page 1 (100 real rows, looks full) then
  incorrectly conclude "short page, no more data" and STOP, silently under-sampling by however many
  pages were requested. This run only got a real 510-record corpus by explicitly passing
  `--limit 100` (matching Gamma's real cap) with `--max-pages 10` so the offsets land correctly
  (0, 100, 200, ...). **Recommended for the factory (loop-buildable, no data/egress/owner action
  needed): either cap `limit` to 100 inside the fetcher before computing `offset`, or change the
  stop condition to compare against `min(limit, 100)` — and fix the CLI help text / every
  documented command in GROWTH_STATUS/PENDING_OPS that currently says `--limit 250` or `--limit 500`
  believing it fetches that many rows per page.** This is why every real corpus committed or
  fetched before this run topped out in the tens of records even though nothing was stopping a
  larger pull except this pagination bug plus (until today) the egress block.

### (3) EXP-002 verdict, with the adversarial pre-mortem applied to my OWN result (per playbook — hunt overfitting in your own findings)
  Both eval methods used **pre-registered, unmodified parameters**: `decision_lead_days=7` (EXP-002's
  own pre-registered value from 2026-06-29), `min_bucket_n=30` (`CalibrationBucketStrategy`'s own
  shipped default, not tuned), `order=volumeNum` (the existing documented convention), a single
  60/40 chronological split (no re-splitting after seeing results), `strategies_screened=2`
  (Bonferroni, pre-declared for EXP-002+EXP-003 jointly, per the existing GROWTH_STATUS
  `significance_threshold` text — never loosened after seeing the result). No parameter was searched
  or retried after seeing a number — each config was run exactly once. That both independent
  methodologies (full walk-forward PnL and static-split Brier-significance) point the SAME direction
  (negative) on the SAME corpus is reassuring cross-validation, not double-counting evidence, since
  they measure different things (realized cost-net PnL vs. calibration Brier).
  **What is NOT refuted (read before over-generalizing this into "no calibration edge exists"):**
  (a) **Sampling composition**: `order=volumeNum` selects the platform's all-time-highest-volume
  markets — by construction the markets that have attracted the MOST sophisticated trading interest
  over their lifetime, which plausibly explains why the crowd here is unusually hard to beat (this is
  the SAME liquidity-selection bias every fetcher run has disclosed since 2026-06-28, now shown to
  bite specifically at the mechanism level, not just as a caveat). A random or recency-weighted
  sample of ALL resolved markets (most far smaller/less liquid) might show a different result — this
  run does not test that. (b) **Mechanism specificity**: only the shipped 10-equal-width-bucket,
  historical-average-replacement design was tested. The specific reason it underperformed is
  diagnosable, not just "no edge": in the dominant `[0, 0.1)` bucket, the TRAINING-period empirical
  YES-rate was 1.0% (n=202, 2024-01 to 2026-01), but the OOS TEST-period actual rate was 7.59% (6/79,
  2026-01 to 2026-06) — the true near-zero resolution rate appears TIME-VARYING (see finding 4), so
  a lagging historical-average replaces the crowd's own live (and, it turns out, LESS wrong) price
  with a STALER number. The mechanism's flaw is "static bucket average" specifically, not
  necessarily "crowd miscalibration doesn't exist." (c) This is one corpus / one lead / one bucket
  scheme — re-testing with different parameters now, after seeing this result, would be p-hacking;
  any follow-up must pre-register new parameters before looking.
  **Recommendation:** mark EXP-002 (as specifically built: fixed-decile static bucket average,
  7-day lead, volume-selected corpus) `mechanism-tested-failed` in GROWTH_STATUS — not "retired"
  (the underlying miscalibration hypothesis is not dead, see (4) below) but the specific tested
  design should not be re-run on this same corpus/config expecting a different answer, and should
  not be promoted. A revised design worth a FRESH pre-registered test (not tried this run, flagged
  as a candidate only): a bucket model that re-weights recent training data more heavily (e.g. a
  rolling window instead of an all-time average) to track a time-varying true rate — this is a new,
  falsifiable, not-yet-tested hypothesis, explicitly NOT claimed as validated here.

### (4) EXP-001 hypothesis (near-certainty-NO longshot reversal) independently strengthened by a SECOND real sample — still NOT validated (data reuse + small N + no dedicated pre-registration this run)
  While inspecting the OOS test split for finding (3), the `[0, 0.1)` bucket showed: n=79,
  avg_price=0.0185 (crowd prices these at ~1.85% YES), actual outcome: **6/79 resolved YES = 7.59%**
  — over 4x the crowd's average price. A one-sided exact binomial test against the null
  "true rate = crowd's own average price" gives **p ≈ 0.0035** (computed directly, `scipy` unavailable
  in this environment so done via the closed-form binomial sum: `sum(comb(79,i)*0.0185**i*(1-0.0185)**(79-i)
  for i in range(6,80))` — reproducible from the same corpus). This is the SAME direction, and a similar magnitude, as the
  2026-06-29 fixture-level finding (0.8% priced vs 5.9% actual, N=34, explicitly logged then as
  "insufficient data" and in-sample). This run's N=79 is a genuinely different, larger, and
  chronologically OOS sample (2026-01 to 2026-06) — a real second data point in the same direction.
  **Why this is NOT promoted to a validated result this run (the honest catch on my own finding):**
  (a) this bucket was inspected AFTER already using the same 40%-test split for EXP-002's evaluation
  — testing a second, different hypothesis on data already spent is a multiple-comparison /
  data-snooping risk that was not pre-registered or Bonferroni-corrected for THIS specific comparison
  (only EXP-002-vs-EXP-003 was pre-declared); (b) N=79 with only 6 YES events is still a small-count
  regime where a handful of markets can swing the rate a lot; (c) the same liquidity-selection /
  all-time-top-volume bias applies; (d) realistic slippage on a ~1.85¢ contract may be materially
  worse than the flat 0.5% model assumes (thin far-OTM books), a risk EXP-001's own pre-mortem
  already named. **Correct next step (not done this run, named for the factory/a future research
  run): a FRESH, pre-registered EXP-001 test — ideally on a corpus slice not already used for
  EXP-002 (e.g., a different `--order` or a later `--merge` batch), with its own declared
  significance threshold and multiple-comparison correction against EXP-002/003 — before any
  promotion claim.** This entry exists to make sure that future run doesn't have to rediscover the
  hypothesis from scratch, and to make honest the fact that two independent samples now agree in
  direction even though neither alone clears the bar.

### (5) EXP-003 (political-category calibration) confirmed still blocked — and now confirmed on RESOLVED-market data too, not just the live scan path
  Separately queried `PolymarketHistoryFetcher.fetch_resolved_markets` (pre-leakage-filter, category
  field only) with the same parameters: of 1,000 raw resolved candidates, **996 had an empty
  `category` field**; only 4 carried a non-empty value (`"US-current-affairs"`). This is the exact
  same empty-`category` defect the factory already found and fixed for the LIVE scan path
  (`market_category.py`, #156, 2026-07-02) — but that fix was never threaded into
  `polymarket_history_fetcher.py`'s `ResolvedMarket.category` parsing (`polymarket_history_fetcher.py:248`,
  still `raw.get("category", "")`), so the `--categories politics,elections` filter every EXP-003
  command in GROWTH_STATUS documents would silently return ~0 records even with egress open. This is
  NOT a new blocker — EXP-003 was already logged as blocked on the corpus — but it upgrades the
  reason from "no corpus fetched yet" to "the corpus mechanism itself needs the same tag/keyword
  category classifier the live path already has, or it will always return empty." **Recommended for
  the factory (loop-buildable, no owner/egress action needed given egress is open from at least this
  environment): port `market_category.py`'s tag/keyword classifier into
  `polymarket_history_fetcher._parse_resolved` (or a wrapper) so `ResolvedMarket.category` reflects
  the same real signal the live scanner now uses, unblocking EXP-003's category filter.**

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N number assigned. This run tested existing EXP-002 (result: failed) and gathered
  descriptive evidence relevant to existing EXP-001 (strengthened, not validated) and EXP-003
  (blocked, cause now more specific) — extending three already-open experiments with real evidence
  is more valuable and less p-hacking-prone than opening a fourth on the same corpus in the same run.
- The revised "rolling-window calibration bucket" idea (finding 3) and the "fresh pre-registered
  EXP-001 re-test" (finding 4) are named as candidates for a FUTURE run, explicitly not started here.

### Self-validation (sources this run)
- Egress test (finding 1): direct `curl` from this session's own proxy against all five domains,
  inspecting actual response bodies (not just status codes) to rule out a captive-portal false
  positive — each returned real, parseable Polymarket/HuggingFace content matching the live/current
  date (the Data API trade timestamp corresponds to minutes before this run).
- The 510-record corpus (findings 2-4): fetched live, this run, via the unmodified
  `scripts/fetch_polymarket_history.py` and `scripts/validate_real_oos.py` (both pre-existing,
  previously offline-tested-only factory artifacts) — zero code changes made to produce these
  numbers. `seed_hash 40951c0bd2da1ad7` is reproducible by re-running the same command (subject to
  Polymarket's resolved-market set only growing, not shrinking, over time — a re-fetch today should
  reproduce a superset with the same historical rows unchanged).
  The corpus itself is NOT committed to the repo (this is research-agent scratch analysis, not a
  factory data commit) — it is fully reproducible from the exact command above, subject to the
  growing-not-shrinking caveat just noted. The static-split B2 eval (60/40 chronological split,
  `CalibrationBucketModel(min_bucket_n=30).fit(train)`, then `evaluate_calibration(preds,
  strategies_screened=2)` over `ResolvedPrediction` records built from the fitted model's
  per-market predictions on the test set) is a straightforward, short script against the factory's
  own `calibration_bucket_strategy.py` + `calibration.py` APIs — no new logic, only new plumbing to
  drive them on the fetched corpus with a fixed 60/40 split instead of `walk_forward`'s expanding
  window, so it is independently re-derivable by anyone re-running the same fetch + the same
  ~40-line driver against those two unmodified modules.
- The pagination-cap finding (finding 2) is a direct, repeated observation (`limit=500` returning
  exactly 100 rows twice, then `limit=100` correctly paging further) plus a direct read of
  `polymarket_history_fetcher.py:181-208`, not an inference.
- The category-emptiness finding (finding 5) is a direct field count over 1,000 freshly-fetched raw
  resolved markets, cross-referenced against `polymarket_history_fetcher.py:248` and the existing
  `market_category.py`/#156 fix already documented in RESEARCH_MEMORY 2026-07-02/07-03.

## 2026-07-04 — Factory Run (3rd of the day): recency-weighted bucket alpha (B4a-revised, EXP-002's named successor) — TESTED ONCE ON REAL DATA (n=799), REFUTED; static B4a sign-FLIPPED across corpora (not a robust edge); factory-env egress now OPEN
- Hypothesis (falsifiable, PRE-REGISTERED before the run): a per-price-bucket calibration model
  that weights RECENT resolved training markets more heavily (exponential recency decay on each
  training market's `resolution_time` relative to the decision time) tracks a TIME-VARYING true
  rate better than EXP-002's all-time average — the diagnosed cause of EXP-002's Run-14 refutation
  (the [0,0.1) bucket resolved YES at 1.0% in the training slice vs 7.59% OOS) — and so produces a
  better-calibrated, cost-net-positive decision-time probability vs the crowd. Params fixed from
  FIRST PRINCIPLES / shipped defaults BEFORE looking: half_life_days=60, min_effective_n=30 (Kish
  effective sample size), 10 equal-width buckets, min_edge=0.02, kelly_fraction=0.25, seed=42;
  fetch order=volumeNum, decision_lead_days=7, min_volume≥1000. Run ONCE, no tweak-and-retry.
- Min sample N: 100 (EXP-002's pre-registered floor). This run's corpus: **n=799** (the largest real
  leakage-safe corpus this project has evaluated — enabled by the #220 Gamma-pagination fix +
  `--limit 100 --max-pages 15`; prior best 510).
- OOS result: **TESTED AND REFUTED for the recency mechanism, and the static B4a shown NON-ROBUST.**
  On the same n=799 corpus (crowd_brier=0.1108, pinned=49.6%, yes_base_rate=0.274, deterministic —
  recency hash reproduced bit-for-bit):
    * crowd baseline: 0 trades / $0 (model_prob==crowd tautology).
    * **static B4a (EXP-002): 154 trades, +$3,330.32.**
    * **recency B4a-revised: 108 trades, −$914.27** — the recency model LOST money OOS and was
      WORSE than the static variant. `regime_slice.has_positive_edge=False` (no positive edge to
      assess for concentration). The recency hypothesis (recency-weighting beats the static average)
      is **refuted on this corpus**.
  CRITICAL integrity read on the static +$3,330: Research Run 14 measured the SAME static B4a at
  **−$2,938 on n=510** (a smaller, different-page corpus). A result whose SIGN FLIPS between two
  honest OOS corpora (+$3,330 vs −$2,938) is the textbook signature of a **non-robust,
  selection/regime-dependent** result — NOT a validated edge. The larger n=799 corpus reaches deeper
  into the volumeNum ordering (lower-volume markets on later pages) where the bucket averages differ;
  the positive aggregate is not evidence of edge without independent-corpus replication + regime
  slicing + a passing calibration gate. **So neither bucket mechanism (static OR recency) has a
  robust OOS edge**; the binding constraint (no validated OOS edge) STANDS.
- Calibration (Brier / reliability): not separately re-run through the B2 significance gate this run
  (the walk-forward PnL is the primary read; the static sign-flip already refutes robustness). A B2
  Bonferroni calibration eval on a FRESH pre-registered corpus is the next rigorous step, not a
  re-eval of the corpus just seen (that would be p-hacking).
- Costs modeled: yes — the unmodified `cost_model.py` (2% fee + 0.5% slippage) via the factory's own
  `walk_forward`, identical sizing for static and recency (recency reuses EXP-002's `_net_edge_decision`
  → apples-to-apples; any PnL delta is the recency mechanism alone).
- Verdict: **edge-not-proven — recency mechanism REFUTED on this corpus; static B4a shown NON-ROBUST
  (sign-flip).** Both remain UNWIRED. Do NOT re-run either on this same corpus expecting a different
  answer, and do NOT tune half_life on it (p-hacking).
- Why / next (pre-registered candidates, tested only AFTER pre-registering on a FRESH corpus):
  (a) REPLICATE the static B4a on an independent corpus (different `order` / a disjoint time slice) —
  if the sign flips again it is confirmed noise; if it holds AND regime_slice is non-fragile it becomes
  a candidate for ≥3 adversarial auditors. (b) A rolling-WINDOW (fixed-N most-recent) bucket variant,
  distinct from exponential decay. (c) B4/B8 reasoning alphas (deep-research / cross-venue coherence)
  are structurally different bets that don't depend on out-calibrating a sharp crowd.
- MAJOR ENABLER (self-validated this run, per FACTORY_STANDARD §28 "re-probe env-gated deps every run"):
  the autonomous FACTORY BUILD ENV's own egress to `gamma-api`/`clob`/`data-api.polymarket.com`,
  `api.elections.kalshi.com`, and `huggingface.co` is **OPEN** (direct `curl` HTTP 200 to all five +
  a real 799-record fetch through the committed pipeline). This OVERTURNS the "egress-blocked,
  confirmed by prior runs" conclusion that gated OA-11/13/16 — the loop can now fetch real corpora
  itself (no owner egress step needed for gamma/clob; OA-16 HuggingFace + OA-15 Kalshi are now
  loop-runnable too). Re-probe every run; do not infer "still blocked" from a stale prior. (This also
  triggered #222 — data-api reachability made the ungated fabricated-edge `wallet_divergence` a live
  risk, gated OFF per OA-13.)
- Reproducibility: live-fetch (not committed — same limitation as Run 14); re-runnable by anyone via
  the exact command above on a permitted host. The recency + static walk-forwards are deterministic
  (same corpus+config → same PnL); the corpus itself drifts as new markets resolve.

## 2026-07-04 (4th run) — static B4a replication (pre-registered #1) + FIRST HuggingFace 1.3M-archive OOS run → bucket-calibration family CONFIRMED non-robust
- Hypothesis (falsifiable, pre-registered by the 3rd run): (1) the +$3,330 static B4a on n=799 was
  either a real edge or noise — replicate on an INDEPENDENT corpus; a sign-flip = confirmed noise,
  a hold + non-fragile = a candidate for ≥3 auditors. (2) The HuggingFace `Polymarket-v1` archive
  (1.3M markets, a genuinely different, platform-wide sample) is the strongest independent test.
- Min sample N: 100-floor; corpora this run n=621 (Gamma) + n=375 (HF binary markets).
- OOS result: **static B4a is NON-ROBUST across FOUR corpora — CONFIRMED noise, not an edge.**
  Static B4a (EXP-002), 7-day lead, all via the unmodified `walk_forward` + `cost_model` (2% fee +
  0.5% slippage), deterministic:
    * Run 14 (Gamma volumeNum, n=510):   **−$2,938**
    * 3rd run (Gamma volumeNum, n=799):   **+$3,330**
    * THIS run (Gamma volumeNum, n=621, fresh same-day fetch, seed_hash df25f5c48a5ab34b): **−$2,947 / 70tr**
    * THIS run (HuggingFace archive, n=375, INDEPENDENT platform-wide sample, seed_hash 792a492cb9152c6a):
      **+$534.88 / 30tr but FRAGILE** — F10 regime-slice flags 100% of net PnL in ONE horizon bucket
      ('3-7d') AND 122% in the extreme-confidence bucket ('90-100%'), i.e. the "positive" result is
      entirely a crowd-pinned-market artifact, not a broad edge.
  The Gamma sign now flips −/+/− across three same-config fetches (the two near-nested corpora give
  OPPOSITE signs), and the ONE genuinely-independent corpus (HF) is positive-but-fragile-concentrated.
  Four corpora, no robust positive: the bucket-calibration family (static AND the already-refuted
  recency variant) has **no robust OOS edge**. This resolves pre-registered question #1: the +$3,330
  was noise.
- Calibration (Brier / reliability): crowd Brier 0.106 (Gamma) / 0.085 (HF) — the crowd is sharp,
  especially on the pinned markets where B4a's apparent HF edge lives (hence FRAGILE). No B2
  Bonferroni pass; not re-run on a seen corpus (p-hacking).
- Costs modeled: yes — unmodified `cost_model.py` via `walk_forward`; same sizing across variants.
- Verdict: **edge-not-proven — the ENTIRE price-bucket-calibration family (static + recency) is
  refuted / non-robust.** STOP building more bucket variants (a rolling-WINDOW variant would iterate
  on a refuted family — dropped as padding). Both bucket strategies remain UNWIRED.
- MAJOR ENABLER shipped this run (#226, ROADMAP A6 / OA-16): the HuggingFace `daily_aligned` schema
  was streamed + CONFIRMED for the first time (egress open) and the fetcher remapped to it. The layer
  is per-TRADE/per-OUTCOME; the leakage-safe mapping is market←`condition_id`, tick←`block_timestamp`,
  **P[YES]←`p_event`** (already YES-normalized; raw `price` is the traded-leg price and is EXCLUDED so
  a 'No' row can't invert), resolution←`close_at` (`resolved_at` null), outcome←`winning_outcome_label`
  (team-name → skipped → categorical markets excluded). Real run: 375 leakage-safe binary markets
  assembled from the 1.3M archive (contested/no-tick/categorical correctly skipped). The 1.3M-market
  corpus is now loop-runnable — the volume half of the binding-constraint unblock.
- Pivot / next (pre-registered, do NOT p-hack): the binding constraint is now clearly "no
  structurally-different alpha," not "no data." Prioritize the alphas that do NOT depend on
  out-calibrating a sharp crowd: **B8 cross-venue coherence** (matcher built #179 — now runnable on
  real Polymarket⟷Kalshi corpora, egress open) and **B4 per-market deep research**. Also worth: run
  the HF lane at EARLIER-life leads / larger N to test whether ANY calibration edge exists off the
  pinned regime — but as a diagnostic, not a rescue of the refuted bucket family.
- Reproducibility: live-fetch (corpus drifts as markets resolve; not committed — same limitation as
  Run 14). Commands: `python scripts/validate_real_oos.py --venues polymarket --max-pages 12
  --decision-lead-days 7 --json` and `--venues polymarket_v1_hf --max-pages 800 --decision-lead-days 7`.
  Walk-forwards deterministic (same corpus+config → same seed_hash/PnL).

## 2026-07-05 — Research Run 15: forward-paper loop confirmed STILL at zero resolutions (bankroll deployed + Sports-category cap now binding, not a bug); Kalshi's public quote gap reconfirmed at 5x the sample size (n=1000); NEW candidate hypothesis — "Yes Bias" in low-liquidity narrative/mention markets (unverified secondary source); no new EXP-00N tested

- Hypothesis (falsifiable): n/a for this run's self-validation portions — no new alpha tested on
  our own data. One NEW hypothesis is surfaced from external research (below) and logged as a
  candidate, not tested.
- Min sample N: n/a (self-validation) / n/a yet for the new candidate (no corpus, no classifier).
- OOS result: n/a — no edge tested this run.
- Calibration (Brier / reliability): not measured this run — still zero resolved trades in the
  forward paper track record (see finding 1).
- Costs modeled: n/a.
- Verdict: **edge-not-proven** (self-validation + research only, consistent with the playbook's
  "insufficient data over reading noise").
- Why:

### (1) SELF-VALIDATION: the forward-paper track record (OA-17) is STILL at zero resolutions two days later — diagnosis updated, and it is NOT the same bug class as before
  Directly inspected 6 `live-validation.yml` job logs spanning 2026-07-03T04:12 through
  2026-07-05T09:24 UTC (today's most recent run), via the `github` MCP tool (run IDs 28637890271,
  28680739763, 28701334039, 28717474808, 28729577988, 28736147254). **`"resolutions": null` and
  `"executions": []` in EVERY one of the 6 runs** — zero new paper fills, zero resolved positions,
  across the entire window. Grepped full log content for `ForeignKeyViolation`/tracebacks in all 6:
  none found — the 2026-07-02 persistence bug (Research Run 12) remains fixed, no recurrence.
  **This is a real diagnosis update, not a repeat of the prior finding:** unlike 2026-07-02 (where
  every real market defaulted to the empty `"General"` bucket due to a parsing bug), these 6 runs
  show categories being derived CORRECTLY (`Sports`, `General`, a named Bitcoin-price market) — the
  #156 category fix is holding. The freeze this time has a different, more mundane cause: bankroll
  fell from $500 to $102.87 by 2026-07-04 and has sat flat since (no new capital committed in the
  latest 3 runs), and the live logs show the `Sports` category's $200 sub-cap is now genuinely
  SATURATED by real concentration — the open FIFA World Cup position set (multiple correlated
  outright/exact-score/top-scorer markets on the same tournament, opened 2026-07-02/07-03) consumes
  it, so new Sports opportunities are correctly skipped as "Category 'Sports' exposure ... > $200.0"
  while the handful of non-Sports opportunities scanned each run hit `Kelly size = 0` (no edge, not
  a bug — the expected honest outcome on a well-calibrated market). **This is the per-category
  diversification cap (D2) doing its designed job under a small, mostly-deployed $500 bankroll, not
  a defect** — a materially different, and less alarming, situation than Research Run 12's freeze.
  The near-term binding constraint for real calibration/PnL evidence, first named in Research Run 13
  (2026-07-03) as "simply elapsed real time," STILL holds two days later, now with a concrete added
  factor: **capital is recycled only when open positions resolve** (the FIFA World Cup outright
  market itself is months out; other 2026-07-02/03 fires — Fed decision, MLB, esports, an Elon
  tweet-count window, a within-2-weeks Iran deadline — should resolve sooner). No action recommended
  this run: this is expected behavior, not a bug to fix. A future research run should keep checking
  whether resolutions arrive as those shorter-dated positions mature, and should flag it as a genuine
  problem only if the Sports cap stays saturated for weeks with no rotation into other categories
  despite bankroll freeing up.
  One benign defensive log line worth noting (not an error): `"[POLYMARKET] Order book for <token> is
  empty or one-sided after validation (bids=56, asks=0) — no real spread; returning None (no
  fabricated 0/1 quote)"` — correct behavior (refusing to fabricate a quote), not a new anomaly.

### (2) Kalshi's public `/markets` LIST endpoint quote gap RECONFIRMED directly, at 5x the sample size of the factory's original B8 probe
  The 2026-07-05 factory B8 probe (logged above, same date) fetched 200 open Kalshi markets and
  found ALL 200 parsed with `active=False` + a uniform 0.500 placeholder price. This run
  independently re-tested the SAME endpoint directly from this session (not reusing the factory's
  numbers): `curl "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1000&status=open"` →
  **1000 open markets returned, 0 of them (0/1000) carry a non-null `yes_bid`, `yes_ask`, OR
  `last_price`** — every single field is `null` for every market in the sample, a 5x-larger
  reconfirmation of the same structural gap (not a small-sample fluke). Sampled tickers were
  overwhelmingly multi-leg combo/parlay-style series (`KXMVESPORTSMULTIGAMEEXTENDED-...`, concatenated
  multi-outcome titles — "yes Reg Time: Brazil,yes Reg Time: England,yes Over..." in one `title`
  field), consistent with the factory's "garbled multi-outcome concatenated question text" finding.
  **Implication for B8 (cross-venue coherence): the public bulk `/markets` LIST endpoint is
  structurally unsuited for live quote-matching — this is now confirmed at meaningful N, not a
  one-off** — B8 needs a PER-MARKET quote call (the orderbook endpoint) or the already-fixed
  candlestick history path (OA-15, #170 — built for RESOLVED-history ingest, not live quotes) rather
  than iterating the list endpoint and hoping for populated fields. This doesn't change B8's status
  (still edge-not-proven / not-runnable), but it upgrades the diagnosis from "the sampled 200 markets
  happened to be bad" to "the list endpoint itself does not carry quotes for this market class" —
  worth stating precisely so a future run doesn't re-probe the same endpoint expecting different luck.

### (3) NEW candidate hypothesis (external research, UNVERIFIED — secondary source, no magnitude/N): a "Yes Bias" in low-liquidity narrative "mention markets" near resolution
  Web research surfaced "How Wise is the Crowd? Bias and Edge in Prediction Markets" (Deleep, Lee,
  Bai, Suresh, Dhawan; SSRN, ~March 2026; tick-level order flow + wallet histories + user commentary
  across Polymarket AND Kalshi). **Could not fetch the primary SSRN paper directly (403 Forbidden,
  same access pattern as prior SSRN/Dune sources) — relying on a QuantPedia research-review summary
  only, which itself discloses no sample size, date range, or magnitude numbers.** Per that summary,
  the paper's headline claim is structurally DIFFERENT from every hypothesis this project has tested
  so far: (a) the classic favorite-longshot bias "evaporates" once the authors control for contract
  lifecycle timing via multivariate spline regressions — the SAME price-level-based framing our own
  refuted bucket-calibration family (EXP-002/B4a) used; (b) what remains is a **"Yes Bias" specific to
  "Mention Markets"** (narrative/commentary contracts, e.g. "Will [person] say [X] on [show]?") —
  concentrated in **low-liquidity, near-resolution** stages, where traders "systematically overpay for
  the Yes outcome" driven by "narrative conviction and temporal volatility spikes," not a price-level
  effect; (c) whales underperform small-order traders via adverse selection (not actionable for us —
  this project already rejected whale-copy-trading on private-data/integrity grounds, 2026-07-01); (d)
  comment/sentiment intensity does NOT correlate with informational edge (a negative result — rules out
  a "trade on loud commentary" idea before anyone tries it). **Why this is a genuinely new candidate,
  not a rehash:** it targets a market TYPE + lifecycle stage (mention/narrative markets, near
  resolution) rather than a price bucket, so a null result on the price-bucket family does not
  predict a null result here — it survives the "am I just re-testing a refuted mechanism" check. **Why
  it is NOT proposed as a numbered EXP with a min-N/OOS plan this run (same discipline as the
  2026-07-01 whale-seed finding — don't formalize on top of an unverified input):** (i) the primary
  paper is unreachable, so the magnitude, N, and statistical significance are completely unknown —
  this could be a strong effect or a curve-fit that doesn't replicate; (ii) our own market taxonomy
  (`market_category.py`) has no "mention/narrative market" classifier — this data doesn't exist in our
  pipeline yet; (iii) "low-liquidity near-resolution" narrows the tradeable universe considerably, and
  Polymarket's mention-market volume/count is unknown to us. **Logged as a candidate for a FUTURE run:**
  if a mention-market classifier is built (loop-buildable, no data/egress dependency — a keyword/tag
  heuristic similar to the existing category classifier, e.g. question patterns like "will X say/tweet/
  mention Y", combined with a low-liquidity + near-resolution filter), this becomes a testable EXP with
  its own pre-registered min-N and significance threshold — explicitly NOT started this run.
  A companion search for Polymarket order-book microstructure (Dubach 2026, arXiv:2604.24366v2 — a
  working paper, tick-level order-book + on-chain trade archive) was checked for concrete
  slippage-by-price-level numbers relevant to the recurring "near-zero-price longshot slippage risk"
  pre-mortem item (present in EXP-001/002/004's own caveats) — the reachable extract did not surface
  usable quantitative figures (spread/depth-by-price tables were not present in the fetched text).
  **Inconclusive, not used as evidence either way** — flagged so a future run knows this specific paper
  was checked and came up empty, rather than re-searching for the same thing.

### (4) Egress RE-CONFIRMED open from this environment (consistent with 2026-07-04, not a new fact)
  Direct `curl` from this session: `gamma-api.polymarket.com` (301 redirect to real content, `/markets`
  returns real live markets), `clob.polymarket.com` (200), `data-api.polymarket.com` (200),
  `huggingface.co` (200) all reachable with real content; `dune.com` still 403 (unchanged since
  2026-07-03). `api.elections.kalshi.com` is reachable (200, real live data) but see finding (2) for
  why its LIST endpoint doesn't help B8. This reconfirms, not newly establishes, the 2026-07-04
  finding — logged per the standing "re-probe env-gated deps every run" discipline, not as new news.

### Candidate alphas NOT proposed this run (reasons)
- **"Yes Bias" in mention markets:** unverified secondary source (no N/magnitude, primary paper
  unreachable) + no classifier exists yet in our pipeline. Logged as a future candidate (see finding
  3), not proposed as a numbered EXP this run — proposing one on an unreachable paper's uncontrolled
  claim would violate the "never fabricate an edge" rule by proxy (formalizing an unverifiable input).
- No re-test of the refuted bucket-calibration family (static or recency) — already confirmed
  non-robust across 4 corpora (2026-07-04); re-running it again would not produce new information.

### Self-validation (sources this run)
- Finding (1): direct `github` MCP reads of `live-validation.yml` job logs for run IDs 28637890271,
  28680739763, 28701334039, 28717474808, 28729577988, 28736147254 (2026-07-03T04:12 through
  2026-07-05T09:24 UTC) — grepped full log content, not just tails, for `resolutions`, `executions`,
  `ForeignKeyViolation`, and tracebacks.
- Finding (2): direct `curl` from this session against `api.elections.kalshi.com/trade-api/v2/markets`
  with `limit=1000&status=open`, parsed with a small Python script counting non-null
  `yes_bid`/`yes_ask`/`last_price` fields across all 1000 returned markets (0/1000 populated).
  Reproducible by re-running the same call (subject to Kalshi's live market set changing over time).
- Finding (3): WebSearch + WebFetch of the QuantPedia review page (quantpedia.com) and a direct SSRN
  fetch attempt (403, could not reproduce the primary source — disclosed, not hidden). The Dubach
  microstructure paper was fetched from arXiv (arxiv.org/pdf/2604.24366) but yielded no usable
  quantitative figures in the reachable extract.
- Finding (4): direct `curl` from this session's own network path against all 6 previously-tracked
  domains, same method as 2026-07-01/07-03/07-04 research runs.

---

## 2026-07-07 — Factory run: A8 Manifold (softer PLAY crowd) + B9 per-category map — two real diagnostic findings on the pivoted binding constraint ("where is a crowd beatable?")

Egress OPEN from the factory build env (gamma/manifold/kalshi all HTTP 200). This run BUILT +
RAN two diagnostics that directly attack the pivoted binding constraint. NEITHER is a validated
edge; both are honest SEARCH maps (no DoD/floor box ticked).

### Finding A — A8: the Manifold PLAY-money crowd IS materially softer (a real METHOD-validation target)
- **Hypothesis (falsifiable):** a play-money crowd is less calibrated than the sharp real-money
  crowds (Polymarket/Kalshi Brier ~0.08–0.09), so a calibration/reasoning method would show an
  edge there FIRST.
- **Real run (2026-07-07, `scripts/manifold_research_probe.py`, 7-day decision lead):** 4031 resolved
  binary markets fetched → **2147 leakage-safe records** (1884 skipped by the leakage guard — no
  pre-decision bet / lead predates creation, honest). Crowd **Brier 0.144, ECE 0.027, only 18.5%
  pinned** (base rate 40.9% YES, median price 0.41). An independent auditor's own live run (549
  records) gave Brier 0.154 — same order, drift-only.
- **Interpretation (BOUNDED — not overclaimed):** the higher Brier is PARTLY genuine softness
  (ECE 0.027 > the real-money crowds') and PARTLY just LESS PINNING (18.5% vs Polymarket's ~70% —
  more balanced markets carry a higher Brier at equal calibration). So "softer, less pinned crowd"
  is the honest claim; "beatable by us" is NOT proven (we have no Manifold-specific model, and a
  play-money edge NEVER transfers to real money — the research-only guardrail).
- **Verdict: research venue built + informative finding; edge-not-proven.** Manifold is now a
  reusable method-validation corpus (`manifold_market_data` capability, no creds, research_only).
  Next: run a real calibration/reasoning method (B4-lite) against this softer crowd and see if the
  METHOD produces a B2-passing, F10-non-fragile, F11-significant calibration gain — a METHOD result,
  never a real-money edge. (PR #252.)

### Finding B — B9: per-category crowd calibration on a 1099-market real Polymarket corpus
- **Hypothesis:** the aggregate crowd Brier hides category heterogeneity; some category is less
  efficient (higher ECE) and a better place to aim a future alpha.
- **Real run (`scripts/per_category_edge_search.py`, 7-day lead, volumeNum, n=1099, agg Brier 0.115,
  Bonferroni α=0.01 for K=5 assessed categories):**
  | category | n | crowd Brier | crowd ECE | base | pinned% |
  |---|---|---|---|---|---|
  | **Sports** (most_beatable) | 133 | 0.199 | **0.091** | 0.35 | 16% |
  | General | 425 | 0.150 | 0.057 | 0.35 | 36% |
  | Economics | 68 | 0.020 | 0.053 | 0.24 | 79% |
  | Crypto | 105 | 0.055 | 0.045 | 0.10 | 70% |
  | Politics (sharpest) | 335 | 0.082 | **0.030** | 0.21 | 61% |
- **Interpretation (honest):** by ECE the crowd looks LEAST calibrated on **Sports** and most
  calibrated on **Politics** — consistent with political markets being efficient. BUT this is a
  DIAGNOSTIC map, not an edge: (a) "Sports miscalibrated at 7-day lead" is unsurprising (games not
  played) and beating it needs a real sports model we don't have; (b) any per-category "edge" must
  still survive the Bonferroni α=0.01, a real alpha beating the crowd OOS, B2, F10, and F11; (c) the
  corpus is liquidity-selected (volumeNum) — a known bias. The map SEARCHES; it does not prove.
- **Verdict: diagnostic built + informative map; edge-not-proven.** Feeds a future targeted alpha
  (aim at a soft category, not the aggregate). (PR #251.)

### Also shipped this run (integrity infra gating any future edge claim)
- **F11 (#249):** bootstrap significance CI on the TRADEABLE OOS PnL/hit-rate — a green backtest
  total is only an edge when the total-PnL CI EXCLUDES zero (the money analog of B2). Now every
  `validate_real_oos` run carries the F11 verdict; a lucky-longshot positive total is called
  `indistinguishable_from_zero`.
- **D2 (#253):** the SELL/partial-reduce path now feeds the per-strategy drawdown circuit (closed a
  named QUALITY_SCORECARD correctness A→A+ gap).
- **A3/§14 (#254):** an UNRECOGNIZED Kalshi settlement result is now logged LOUDLY (was DEBUG),
  making the SELF_VALIDATION "logged LOUDLY" claim honest.

**Binding constraint STANDS:** no validated real-money OOS edge. The pivot ("where is a crowd
beatable?") now has two real SEARCH maps (Manifold = a softer crowd exists; Sports = the least-sharp
Polymarket category) + the F11/F10/B2 significance net to keep any future claim honest. Next: a real
method (B4-lite calibration/reasoning) aimed at the soft targets, run through the full net.

---

## 2026-07-08 — Factory run: honesty correction on the Manifold finding + integrity-hardening (no new edge attempted)

Egress OPEN. A hardening + honesty-reconcile run (8-Haiku scout sweep incl. 4 deep-audit lenses).
No new alpha was attempted — the binding constraint (no validated real-money OOS edge) is a
research problem the last 4 corpora refuted for the bucket family, and this run's genuine
value-bar-clearing work was integrity + honesty, not a speculative edge attempt.

### Honesty correction — the 2026-07-07 Manifold "materially softer crowd" framing is REVISED
The 2026-07-07 A8 finding (Finding A) recorded Manifold as "a materially softer, less-pinned
crowd" and read "PARTLY genuine softness (ECE 0.027 > the real-money crowds')". An adversarial
artifact-honesty audit this run flags that as an OVERCLAIM: **ECE 0.027 is LOW in absolute terms
(a well-calibrated crowd)**, and the Brier 0.144-vs-~0.09 gap is driven by the PINNING confound
(18.5% vs ~70% pinned) + a longer 7-day lead (a less-pinned market carries a higher Brier at
EQUAL calibration), NOT by worse calibration. **Corrected claim:** Manifold is a LESS-PINNED,
longer-horizon research corpus — NOT a proven "softer/beatable" crowd. A method must still be run
and beat it OOS before any softness claim holds. (SELF_VALIDATION already carried this bounded
framing; ROADMAP A8, loop-memory, and LOOP_HEALTH did not — corrected in this run's bookkeeping.)
Implication for the pivot: "aim a method at the soft Manifold crowd" is NOT a de-risked lead —
Manifold being well-calibrated (ECE 0.027) means a method has to beat a genuinely-calibrated
play crowd, not an obviously-soft one.

### Deep-audit triage (8 scouts; anti-padding — most candidates were NOT genuine, recorded so we don't re-raise)
- **STRUCTURAL research-only guardrail (#259):** the named A8 follow-up — a `research_only` tag on
  HistoricalMarket the real-money floor lane REFUSES. Closes the play-money-into-the-floor hole
  (was convention-only). REAL value (protects floor integrity), shipped.
- **Significance-net CI gating + per_category NaN→None (#258):** the F11/B9/A8 test suites that
  VETO false edge claims were passing but UNGATED in CI; now registered. + a confirmed RFC-8259
  JSON hole fixed. REAL value (§26), shipped.
- **Legacy-short quarantine (#260):** D4 named follow-up — a BUY on a legacy `side="short"` row
  scaled it recording $0 PnL; now rejected + warned. Gated-live defense-in-depth, shipped.
- **NOT genuine (triaged out, recorded):** calibration.py/calibration_drift.py NaN→JSON = MOOT
  (API path sanitizes via `_safe_float`/`to_dict`); orchestrator `entry_price<=0` sizing mismatch
  = UNREACHABLE (DQV rejects out-of-range prices; the `else 0.50` is a dead defensive branch —
  guarding it is an impossible-case test); EXP-003 fetcher-category = STALE (post-#231 the fetcher
  derives category); DEPLOYMENT.md sklearn/cvxpy "stale" = FALSE POSITIVE (both ARE imported).
- **B8 Kalshi orderbook-quote fetcher + structured-strike parser (GO-rated by the B8 scout):**
  DEFERRED AGAIN per DECISION COROLLARY — genuine pinned next-steps, but unwired data-layer infra
  with NO co-listed universe to exercise end-to-end this run (consistent with the 3 prior B8 probes).
  The binding constraint is a robust ALPHA, not this data step; building it now is speculative.

**Binding constraint STANDS:** no validated real-money OOS edge (business_case_strength B). Manifold
is now known to be well-calibrated (not obviously soft), so the "where is a crowd beatable?" search
has one fewer easy target than the 2026-07-07 framing implied — an honest narrowing, not a setback.

---

## 2026-07-08 — Research Run 16: URGENT — the forward-paper track record's resolution reporting is DEAD CODE (cannot tell, from any existing signal, whether a single position has ever resolved); EXP-005 (Sports-category calibration bucket) run — insufficient data; egress reconfirmed; one external-research lead caught as a WebFetch over-summarization before it entered the record

- Hypothesis (falsifiable): **EXP-005** — a `CalibrationBucketStrategy` fit EXCLUSIVELY on the
  Sports-category slice of a real leakage-safe resolved-Polymarket corpus (7-day decision lead)
  produces a positive, non-fragile (F10), F11-significant net OOS PnL — motivated by the
  2026-07-07 B9 diagnostic finding that Sports carries the Polymarket crowd's WORST per-category
  ECE (0.091 of 5 assessed categories), i.e. plausibly the most-beatable slice. This is a new,
  not-previously-tested corpus slice (distinct from EXP-002 "all categories" and EXP-003
  "politics"). The self-validation / production-forensics portion of this run (below) is not an
  alpha test.
- Min sample N: 100 Sports-category markets (this project's standing floor), pre-registered
  before running.
- OOS result: **insufficient data — the mechanism correctly ABSTAINED, not refuted.** Fetched
  1,095 real leakage-safe 7-day-lead records (`max_pages=20`, unmodified
  `polymarket_history_fetcher` + `validate_real_oos.evaluate()`, seed=42, single run, no retry) →
  **134 Sports-category markets** (crowd_brier=0.1988, base_rate=0.343, 15.7% pinned — closely
  reproduces B9's 133-market Sports slice from two days earlier, same order of magnitude Brier
  0.199, cross-run consistency). `CalibrationBucketStrategy` made **0 trades** — F11
  `verdict: insufficient_data`, not a measured negative. Diagnosis (arithmetic, not a guess): the
  model's 10 equal-width price buckets need `min_bucket_n=30` training resolutions each to ever
  activate; 134 total markets average 13.4/bucket even using the FULL corpus as training, and
  `walk_forward`'s expanding window means every real decision sees an even SMALLER training slice
  than that — so no bucket could plausibly ever clear the floor at this N. This is the abstain
  mechanism working exactly as designed (no fabricated edge, matching the 2026-06-29 B4a build's
  own tested guarantee) — it is NOT evidence the Sports hypothesis is wrong, only that N=134 is
  structurally too small to test it.
- Calibration (Brier / reliability): not measured beyond the crowd-only corpus stats above (0
  active predictions to score — B2 requires non-abstaining predictions).
- Costs modeled: yes (unmodified `cost_model.py` via `walk_forward`); moot here (0 trades).
- Verdict: **insufficient data (EXP-005, not tested — mechanism abstained on sub-floor N).** Do
  **not** read this as "Sports is not beatable" — it is "134 Sports markets is not enough to ask
  the bucket model the question." A first attempt at `max_pages=40` (~4,000 raw markets, aiming
  for ~400+ Sports records) hit Gamma's own pagination ceiling (a 422 at offset≈2100) AND a
  280s wall-clock budget before finishing — so a future run should budget more wall-clock time (or
  fetch across `--merge`-accumulated multiple runs) rather than assume a bigger `max_pages` alone
  will complete. Not proposing a retry within this run (that would just be re-running the same
  under-powered config expecting a different answer — the honest fix is more N, not a re-roll).
- Why this run's SELF-VALIDATION took priority over chasing a bigger EXP-005 corpus (the real
  headline finding):

### (1) URGENT — `MarkToMarketEngine.check_resolutions()` never returns a value, and NOTHING in this codebase configures Python logging — so the forward-paper JSON's `"resolutions"` field, and every `[MTM] Position resolved` log line, are STRUCTURALLY INCAPABLE of ever showing a resolution happened, independent of whether one actually did
  Every research run since 2026-07-02 (Runs 12/13/15) has read `"resolutions": null` in
  `run_paper_cycle.py --json` output across 32 `live-validation.yml` runs and diagnosed the
  binding constraint as "elapsed real time" (positions haven't matured yet). This run traced the
  ACTUAL code path (not just the log field) and found two independent, currently-active defects
  that make that field meaningless as a signal, verified by direct code read (not inference):
  1. **`scripts/run_paper_cycle.py:86-93`** sets `settled = mtm.check_resolutions()` and reports
     it verbatim as `"resolutions": settled` in the JSON (`run_paper_cycle.py:100`).
     **`MarkToMarketEngine.check_resolutions()`** (`orchestrator.py:322-485`) builds a local
     `resolved` list, persists/realizes PnL/removes each settled position from
     `self.executor.positions` as a SIDE EFFECT — but the function has **no `return` statement
     anywhere in its body**; it falls off the end and implicitly returns `None`. So `settled` is
     **always `None`**, whether 0 or 50 positions resolved and were correctly processed inside
     the call. The JSON field's `null` is a constant of the code, not evidence about the world.
  2. **`grep -rn basicConfig backend/ scripts/` returns ZERO matches** — no module anywhere in
     this codebase ever configures the Python `logging` module. With no handler attached, the
     root logger falls back to `logging.lastResort`, which only emits records at **WARNING
     severity or above**; INFO-level calls are silently discarded, never reaching stdout/stderr
     at all. `orchestrator.py:475`'s `logger.info(f"[MTM] Position resolved: ...")` — the ONE
     log line that would prove a resolution fired — is INFO level, so it can **never** appear in
     a captured GitHub Actions job log regardless of whether it fires. Independently confirmed
     both directions: `logger.warning("rehydrated a LEGACY short position ...")`
     (`persistence.py:256`, a real WARNING call) DOES appear in every inspected log (matching
     `lastResort`'s WARNING-only behavior); zero `"[MTM]"` info-level lines appear in ANY of 9+
     inspected runs spanning 2026-07-02→07-08 — consistent with "these lines are structurally
     invisible," not with "this line never executes."
  **What this does NOT mean:** the underlying settlement side effects (DB persist, PnL
  realization, position removal, kill-switch/drawdown feed) are UNTOUCHED by either bug — both
  bugs are purely in REPORTING, not in the settlement logic itself (verified: the background
  `_mtm_loop`, `orchestrator.py:1249`, also calls `check_resolutions()` and also ignores its
  return value — so its behavior was never gated on this return value in the first place).
  Positions genuinely MAY be resolving correctly right now, silently. **What this DOES mean:**
  every prior "still zero resolutions, this is expected, keep waiting" diagnosis (Research Runs
  12/13/15) rests on a signal that could not have shown otherwise even if resolutions WERE
  accumulating — it is **unverifiable, not necessarily wrong**. Per the fail-closed instruction,
  I am not reporting "the forward-paper track record has zero resolutions" as a fact this run —
  that metric is currently **unavailable**, not zero. Several short-dated positions opened
  2026-07-02/03 (an MLB game, a Wimbledon ATP match, an esports match, a within-2-weeks Iran
  deadline, an Elon tweet-count window) should plausibly have resolved by 2026-07-08 in the real
  world; whether the system's own records reflect that is currently impossible to confirm from
  any existing log or JSON signal — only a direct DB query (outside this research agent's access)
  could confirm it, and I did not fabricate one.
  **Recommended for the factory (loop-buildable, no data/egress/owner action needed):** (a) make
  `check_resolutions()` `return` a summary (e.g. `{"resolved_count": len(resolved),
  "net_pnl": ...}`) so `run_paper_cycle.py`'s `"resolutions"` field carries real information
  instead of a permanent `null`; (b) add a `logging.basicConfig(level=logging.INFO, ...)` call at
  the entrypoint of `run_paper_cycle.py` (and/or wherever the backend server boots) so INFO-level
  events — the resolution log line, and any other INFO-level signal in the whole system — are
  actually captured instead of silently discarded; this is a systemic gap (grep found zero
  `basicConfig` calls anywhere), not specific to MTM. Until fixed, treat the forward-paper
  track record's resolution count as **unknown**, not **zero** — a materially different, more
  urgent framing than the prior three research runs used.

### (2) Egress RE-CONFIRMED (routine re-probe, consistent with 2026-07-04/05, not new news)
  Direct `curl` from this session: `gamma-api.polymarket.com` (301→real content),
  `clob.polymarket.com` (200), `data-api.polymarket.com` (200), `huggingface.co` (200) all
  reachable; `dune.com` still 403 (unchanged since 2026-07-03). `api.elections.kalshi.com`'s bare
  root path 404s (expected — no path given; the `/trade-api/v2/...` paths used elsewhere in this
  project work, per B8/B9's own runs).

### (3) A caught WebFetch over-summarization on the "mention markets Yes Bias" candidate (Research Run 15) — logged as a methodology caution, NOT a new finding either way
  Followed up on the 2026-07-05 unverified "Yes Bias in low-liquidity mention markets" SSRN lead
  (primary paper still 403's) by searching for corroborating academic work. Found and fetched (via
  WebFetch, directly reachable, unlike the SSRN source) **arxiv 2602.21229, "Forecasting Future
  Language: Context Design for Mention Markets"** (Kim, Kwon, Kim, Kagan, Khatchadourian, Ahn,
  Lopez-Lira, Lee, Hwang, Levy, Lee, Choi; submitted 2026-02-04). A FIRST WebFetch pass summarizing
  the PDF reported specific numbers — "a Yes bias, ~10 percentage-point overpricing, N=1,447
  mention contracts, on Polymarket" — that looked like exactly the corroboration Run 15 needed.
  **A second, independent WebFetch directly against the arxiv abstract page returned the ACTUAL
  abstract, which describes a DIFFERENT paper than the first summary implied:** this paper builds
  an LLM forecasting method (Market-Conditioned Prompting / MixMCP) for **earnings-call
  keyword-mention markets** specifically, and reports that "MixMCP outperforms the market
  baseline" via LLM+market-signal blending — it does **not** state a standalone empirical
  Yes-bias magnitude, an N=1,447 contract count, or a 10-point overpricing figure anywhere in the
  verified abstract. **Treated as: the first WebFetch pass over-summarized/conflated content into
  numbers not supported by the paper's own abstract — a caution, not a finding.** The 2026-07-05
  "Yes Bias" hypothesis therefore remains exactly where Run 15 left it: **unverified, no reachable
  primary source with real magnitude/N, not newly confirmed nor refuted.** Logged so a future run
  does not cite the fabricated-sounding "10pp / N=1,447" figures as if verified, and as a standing
  reminder to this agent's own practice: cross-check any WebFetch-summarized QUANTITATIVE claim
  against a second, independent fetch before it enters the record (done here; caught the
  discrepancy before it was reported as data).
  Separately (lower-value, logged for completeness): a Vanderbilt study (Clinton & Huang, via
  DL News/Yahoo Finance coverage) claims Polymarket is LESS accurate / less reactive to new
  information than Kalshi — the OPPOSITE direction of the 2026-07-01 "Calibration City" secondary
  source (which found Polymarket BETTER calibrated than Kalshi). Two non-reproduced secondary
  sources now point opposite directions on the same cross-venue question — reinforces the
  standing "treat contradictory non-academic secondary sources as noise, not evidence" discipline,
  not new information either way.

### Candidate alphas NOT proposed this run (reasons)
- EXP-005 stays open/insufficient-data (see above) — not retried this run (more N, not a re-roll,
  is the honest next step).
- No other new EXP-00N proposed. The URGENT self-validation finding (1) is the highest-value
  output of this run and is a reporting/observability defect, not an alpha — flagged for the
  factory, not built (research-agent scope).

### Self-validation (sources this run)
- Finding (1): direct `Read`/`Grep` of `scripts/run_paper_cycle.py` and
  `backend/app/prediction_markets/orchestrator.py` in this session's own checkout (commit
  `3a59cbc`), plus a repo-wide `grep -rn basicConfig backend/ scripts/` (zero matches) and a
  cross-check of `persistence.py:256`'s `logger.warning` call against 9 previously-inspected
  `live-validation.yml` job logs (2026-07-02→07-08) that DO show that WARNING line but never show
  the sibling `[MTM]` INFO line — not asserted from a single log, cross-referenced across the
  full previously-gathered sample.
- Finding EXP-005: live-fetched this run via the unmodified `polymarket_history_fetcher` +
  `validate_real_oos.evaluate()` (same harness B9/EXP-002/B4a use), seed=42, single run, script
  is research-agent scratch (not a factory commit) — independently re-derivable by anyone running
  the same fetch (subject to the corpus drifting as markets resolve, same caveat as every prior
  live-fetch research run).
- Finding (3): WebFetch of `arxiv.org/pdf/2602.21229` (first pass, later found to over-summarize)
  and `arxiv.org/abs/2602.21229` (second pass, the verified abstract) — both directly fetched,
  cross-checked against each other, not against an external claim.
- Egress (2): direct `curl` from this session, same method as every prior run.

**Binding constraint STANDS:** no validated real-money OOS edge. But this run changes WHAT is
known about the forward-paper validation loop itself: its own resolution telemetry cannot
currently be trusted one way or the other (finding 1) — a more urgent, more precise framing than
"just wait for elapsed time," and squarely loop-buildable (no owner/egress action needed).

---

## 2026-07-09 — Research Run 17: SELF-VALIDATION — the #267 resolution-telemetry fix is CONFIRMED live and trustworthy (real zero, not dead code); EXP-005 Sports re-attempt REPLICATES N~135 and sharpens the diagnosis (the volumeNum sampling axis is near-static, not under-fetched); external "Yes Bias" lead remains unverifiable; no new EXP-00N

- Hypothesis (falsifiable): **EXP-005 continuation** (unchanged from 2026-07-08) — a
  `CalibrationBucketStrategy` fit exclusively on Polymarket's Sports-category resolved markets
  (7-day decision lead) produces a positive, non-fragile (F10), F11-significant net OOS PnL, once
  N is large enough to clear `min_bucket_n=30` per bucket. The self-validation portion of this run
  (the resolution-telemetry check) is not an alpha test.
- Min sample N: 100 (EXP-005's pre-registered floor), pre-registered before this run.
- OOS result: **still insufficient data — REPLICATED, not refuted, with a sharpened diagnosis.**
  Re-ran the identical pre-registered config from Research Run 16 (seed=42, decision_lead_days=7,
  order=volumeNum, max_pages=20, unmodified `polymarket_history_fetcher` +
  `validate_real_oos.evaluate()`) one calendar day later: 2,000 raw resolved markets fetched in
  7.1s → 1,095 leakage-safe `HistoricalMarket` records (identical count to Run 16) → **Sports
  n=135** (vs. Run 16's 134, vs. B9's independent 133 two days before that — three pulls across
  three separate days land within ±2 markets of each other). `CalibrationBucketStrategy` again
  made 0 trades; F11 `verdict: insufficient_data` (not a measured negative). Aggregate corpus
  stats also replicated near-exactly: `aggregate_crowd_brier=0.1153` (vs. B9's 0.115), 5 categories
  assessed (Sports/General/Economics/Crypto/Politics, plus 2 sub-floor ScienceTech/Entertainment).
- Calibration (Brier / reliability): Sports crowd_brier=0.198, ECE not separately recomputed this
  run (matches Run 16/B9's ~0.199/0.091 order of magnitude); 0 active predictions to score beyond
  the corpus-level stats (min_bucket_n abstention, as designed).
- Costs modeled: yes (unmodified `cost_model.py` via `walk_forward`); moot at 0 trades.
- Verdict: **insufficient data (EXP-005 unchanged) — but the REASON is now precisely diagnosed,
  superseding Run 16's "budget more wall-clock" framing.** `order=volumeNum` ranks Gamma's
  `/markets?closed=true` results by ALL-TIME cumulative volume, so the top-2,000-by-volume
  resolved set is dominated by long-settled, high-profile historical markets that barely change
  week to week. Re-fetching the SAME order/limit/max-pages combination re-discovers almost the
  SAME markets rather than surfacing new ones — this is a **sampling-axis ceiling**, not merely an
  under-fetch. It is compounded by, but mechanistically distinct from, Gamma's separate pagination
  ceiling (a 422 past roughly offset 2100, first found in Run 16, not re-tested this run since
  max_pages stayed at the already-known-safe 20). **Concretely: even an unlimited wall-clock
  budget on this exact fetch configuration would not grow Sports N materially** — the honest
  next step is a different sampling axis (recency-ordered, or a dedicated per-category/per-series
  paginator), which is a fetcher-DESIGN change, not a bigger `--max-pages` parameter. This is
  factory-build scope; logged to `next_actions`, not re-attempted again this run (a third identical
  pull would only reconfirm the same ceiling, not add information).
- Why / self-validation methodology: `python3` scratch script (research-agent scratch, not a
  factory commit; not committed to the repo) imported the unmodified
  `polymarket_history_fetcher.PolymarketHistoryFetcher`, `per_category_diagnostics`, and
  `scripts/validate_real_oos.evaluate()` directly — zero code changes to any factory module.
  387.5s wall-clock for the full fetch+assemble+evaluate pipeline (dominated by
  `build_historical_markets`'s per-market CLOB price-history call, independently timed this run at
  ~0.2s/market — the actual bottleneck Run 16's "280s timeout" hit, now measured precisely rather
  than just observed). Reproducible by re-running the same command on any host with open
  Polymarket egress (subject to the corpus drifting by resolution date, same caveat as every prior
  live-fetch research run).

### Self-validation: the #267 resolution-telemetry fix is CONFIRMED live, not just merged
  Research Run 16 (2026-07-08) found `MarkToMarketEngine.check_resolutions()` never returned a
  value, making `run_paper_cycle.py`'s `"resolutions"` JSON field a structural `null` regardless of
  whether any position had actually settled — and recommended the factory fix it. The factory
  shipped that fix same-day (commit `0ae20a1`, 2026-07-08T17:00, "check_resolutions() returns the
  settled count — revive dead forward-paper telemetry", #267). This run independently verified the
  fix HOLDS on real production data (not just that the PR merged): directly read the
  `live-validation.yml` job logs for the two `live-smoke-and-paper` runs scheduled AFTER the fix
  landed — 2026-07-09T04:16 (run 28993644145, commit `bd9654c`) and 2026-07-09T09:59 (run
  29010084415, commit `f9f34af`) — both report **`"resolutions": 0`** as a real JSON integer, not
  the constant `null` every pre-fix run showed (independently reconfirmed on the run immediately
  BEFORE the fix, 2026-07-08T19:57 / run 28971595902 / commit `3e73313`, which still shows
  `"resolutions": null` — the fix boundary is precisely where expected, between commits `3e73313`
  and `bd9654c`). **This upgrades Run 16's "resolution count is UNKNOWN" finding to "CONFIRMED real
  zero" — a materially more precise, more trustworthy state than either "assume it's fine" or
  "distrust everything."** Still genuinely ZERO settled positions after 11+ days of OA-17
  operation (the workflow's first run was 2026-06-28 per prior memory entries). Secondary
  observations from the same two logs (not new bugs, logged for trend continuity): bankroll
  continued its slow decline ($102.87 on 2026-07-05 → $72.83 on 2026-07-09) as capital remains
  locked in unresolved positions; `Sports` ($152.75) and, newly, `General` ($211.00 — itself now
  ABOVE its own $200 cap, most plausibly unrealized MTM appreciation of open near-zero-price
  longshot positions rather than a bug, since the cap is enforced at entry, not continuously) both
  saturate and skip most scanned opportunities each cycle (`Kelly size = 0` accounts for the rest)
  — the same D2-cap-working-as-designed diagnosis Research Run 15 made on 2026-07-05, now resting
  on a trustworthy signal instead of an assumption that the field even reflected reality. **No
  action recommended** — this is not a new bug; the correct next step is simply to keep checking
  whether the now-reliable `resolutions` field turns non-zero as this week's shorter-dated
  positions (an Iran deadline, in-progress FIFA World Cup group matches) mature.

### External research this run (checked, not new evidence either way)
- Re-searched the 2026-07-05/07-08 "Yes Bias in low-liquidity mention markets" lead (Deleep, Lee,
  Bai, Suresh, Dhawan, SSRN, ~Feb/March 2026). The primary SSRN page (abstract_id=6322678) is still
  **403 Forbidden** on direct WebFetch — unchanged from every prior attempt. Checked two NEW
  secondary sources not previously read (`advancedinvesting.org`'s summary + a fresh QuantPedia
  pull): neither disc loses a sample size, date range, or magnitude for the "Yes Bias" claim —
  `advancedinvesting.org` was directly asked for exactly these figures and confirmed it has none,
  only the qualitative claim ("traders systematically overpay for the affirmative outcome" in
  mention markets once contract-lifecycle timing is controlled for). **Status unchanged from Run
  15/16: unverified, no reachable primary source with real N/magnitude, not newly confirmed nor
  refuted.** Not escalated to a numbered EXP (same discipline as before — formalizing on an
  unverifiable input would violate the never-fabricate-an-edge rule by proxy).
- New this run: checked Goto (2026), "Forecast Sports Outcomes under Efficient Market Hypothesis"
  (arXiv 2604.17194, April 2026) — a Favourite-Longshot-Bias-Adjusted Generalised Linear Model
  (FL-GLM) fit on **90,014 football matches across five bookmakers**. Verified abstract directly
  (reachable, unlike SSRN). **Ruled out as inapplicable to EXP-005**, not merely low-value: this is
  a fixed-odds BOOKMAKER dataset (traditional sportsbooks pricing with a built-in vig), not a
  prediction-market CROWD price — different microstructure, different incentive structure, and the
  abstract discloses no transferable bias-magnitude figure anyway. Logged so a future run does not
  re-check this specific paper expecting Polymarket-Sports relevance.
- Egress RE-CONFIRMED open (routine re-probe, consistent with every run since 2026-07-04, not new
  news): `gamma-api.polymarket.com`/`clob.polymarket.com` HTTP 200 (direct `curl`, real content);
  `dune.com` still 403.

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. EXP-005 stays `insufficient-data` (see above) — the corpus-growth path
  attempted this run (bigger fetch, same order) is now confirmed exhausted; re-attempting it again
  identically would not produce new information. The honest next step is a factory-side fetcher
  redesign (recency-ordered or per-category pagination), logged to `next_actions`, not a research-
  agent re-run.
- The "Yes Bias" mention-market hypothesis remains un-formalizable (no reachable primary source);
  not proposed as EXP-006.

### Self-validation (sources this run)
- Resolution-telemetry finding: direct `github` MCP reads of `live-validation.yml` job logs for
  run IDs 28971595902 (2026-07-08T19:57, pre-fix), 28993644145 (2026-07-09T04:16, post-fix),
  29010084415 (2026-07-09T09:59, post-fix), cross-referenced against `git log` commit timestamps
  to confirm the fix boundary (`3e73313` pre-fix → `0ae20a1`/`edf082c` fix commits, 2026-07-08
  17:00-17:05 → `bd9654c` first post-fix scheduled run).
- EXP-005 re-attempt: live-fetched this run via the unmodified `polymarket_history_fetcher.py` +
  `scripts/validate_real_oos.evaluate()` (same harness as Run 16/B9), seed=42, single run, script
  is research-agent scratch (not a factory commit) — independently re-derivable by anyone running
  the same fetch (subject to the corpus drifting as markets resolve).
- External research: WebSearch + WebFetch of `papers.ssrn.com/sol3/papers.cfm?abstract_id=6322678`
  (403, unreachable — confirmed directly, not assumed), `advancedinvesting.org`'s summary page
  (fetched directly, confirmed no N/magnitude present), and `arxiv.org/abs/2604.17194` (fetched
  directly, abstract verified).
- Egress: direct `curl` from this session against the same domain set as every prior run.

**Binding constraint STANDS:** no validated real-money OOS edge. This run's real contribution is
epistemic hygiene on two fronts: the forward-paper telemetry is now KNOWN-trustworthy (and known
to be genuinely zero, not unknown), and EXP-005's stalled corpus growth has a precise, actionable
diagnosis instead of a vague "try harder" — both are more useful to the next run than a forced,
premature EXP-006.

---

## 2026-07-10 — Research Run 18: EXP-005's Sports-corpus ceiling FALSIFIED — an existing, untried fetcher parameter (`order="volume24hr"`) grows Sports N 135→253 in one fetch; still insufficient data (mechanism correctly abstains); Le 2026's exact per-horizon table tempers the expected edge size; external leads corroborated, none new

- Hypothesis (falsifiable): **EXP-005 continuation** (unchanged since 2026-07-08) — a
  `CalibrationBucketStrategy` fit exclusively on Polymarket's Sports-category resolved markets
  (7-day decision lead) produces a positive, non-fragile (F10), F11-significant net OOS PnL, once
  N is large enough to clear `min_bucket_n=30` per bucket. This run's real contribution is a
  sampling-axis probe, not a completed alpha test.
- Min sample N: 100 (EXP-005's pre-registered floor, unchanged).
- OOS result: **still insufficient data — but the "no lever left" diagnosis from Research Run 17
  is FALSIFIED.** Run 17 (2026-07-09) concluded the `order=volumeNum` sampling axis was
  near-exhausted for Sports (133→134→135 across 3 independent same-config pulls on
  07-07/07-08/07-09) and that growing N required "a fetcher-DESIGN change... factory-build scope,
  not a research-agent re-run." This run re-read `PolymarketHistoryFetcher.fetch_resolved_markets`
  (`backend/app/prediction_markets/polymarket_history_fetcher.py:159-227`) and found it already
  accepts an `order` parameter with several Gamma-supported sort fields; every script in this repo
  (`scripts/fetch_polymarket_history.py`, `scripts/validate_real_oos.py`, `scripts/per_category_edge_search.py`)
  hardcodes or defaults to `order="volumeNum"`, and the fetcher's own docstring already documents
  trying (and rejecting) `order="endDate"` ("surfaces never-traded junk... EMPTY CLOB price
  history"). Neither script had ever tried Gamma's `order="volume24hr"` (trailing-24h volume rank)
  — a live `curl` against `gamma-api.polymarket.com/markets?closed=true&order=volume24hr` showed it
  returns currently-hot, recently-resolved markets (today's FIFA World Cup matches at the time of
  this run) with real trade activity, a plausibly different, not-yet-exhausted slice from the
  all-time top-volume list. A research-agent scratch run (unmodified `PolymarketHistoryFetcher` +
  `validate_real_oos.evaluate()`, no repo code changes, not committed; seed=42,
  decision_lead_days=7, limit=100, max_pages=20, single run, no retry after seeing the number;
  383s wall-clock) confirmed it: **1,998 raw resolved markets → 347 leakage-safe records → Sports
  n=253** (vs. 133/134/135 on the volumeNum axis) — an **87% increase in Sports N from the SAME
  fetch budget**, via a parameter no one had tried, not a code build. `CalibrationBucketStrategy`
  still made **0 trades**; F11 `verdict: insufficient_data` (unchanged — 253 records / 10 buckets
  averages 25.3/bucket even using the FULL corpus as training, still under `min_bucket_n=30` before
  `walk_forward`'s expanding window shrinks the effective training slice further for any individual
  decision). So EXP-005 remains **untested**, not refuted — but the specific "there is no cheap
  lever left" framing from Run 17 was wrong, and is corrected here rather than carried forward.
- Calibration (Brier / reliability): Sports crowd_brier=0.2227, ECE=0.0745, base_rate=0.435 on this
  axis's 253 records (vs. B9/Run16/17's volumeNum-axis Sports crowd_brier≈0.198-0.199, ECE≈0.091,
  base_rate≈0.343-0.345) — a genuinely DIFFERENT, not directly comparable sample: only 0.8% of this
  corpus is price-pinned (<0.05 or >0.95) vs. volumeNum's ~16%, consistent with `volume24hr`
  surfacing currently-live/near-even-money game markets rather than long-settled historical ones.
  Full-corpus (all categories, n=347) per-category diagnostic (`per_category_diagnostics.per_category_calibration`,
  min_category_n=30, Bonferroni α=0.025 for 2 categories assessed): General n=85
  brier=0.2059/ECE=0.1052; Sports n=253 brier=0.2227/ECE=0.0745 — General now ranks as
  MORE-beatable-by-ECE than Sports on this specific axis (opposite of B9's volumeNum-axis
  ranking), a DIAGNOSTIC-only observation (this module never trades or fits a model), reported
  honestly as sample-composition-dependent, not a stable finding.
- Costs modeled: yes (unmodified `cost_model.py` via `walk_forward`); moot at 0 trades.
- Verdict: **insufficient data (EXP-005 unchanged, still not tested)** — but the corpus-growth
  path is now KNOWN-tractable via an existing flag, correcting Run 17's "needs a fetcher rebuild"
  framing. NOT a like-for-like replacement for the volumeNum corpus: the two axes are near-disjoint
  in category composition — this pull's leakage-safe set carried **zero** Crypto/Economics/Politics
  records of any size despite 1,089 raw Crypto markets in the fetch (all skipped by the leakage
  guard for the same reason as `order=endDate` — recently-hot markets are often too new to have a
  tick 7 days before eventual resolution), vs. volumeNum's 5-category spread. The honest next step
  is **merging** both axes (dedupe by `market_id`, which the fetcher's existing `--merge` CLI flag
  already does) toward the pre-registered ≥300-400 Sports-only floor, not replacing one axis with
  the other.
- Why / self-validation methodology: `python3` scratch scripts (research-agent scratch, not
  committed to the repo) imported the unmodified `PolymarketHistoryFetcher`,
  `per_category_diagnostics.per_category_calibration`, `walk_forward`, `calibration_bucket_strategy`,
  and `scripts/validate_real_oos.evaluate()` directly — zero code changes to any factory module. Two
  separate live fetches this run (~383s and ~378s wall-clock respectively, both `order=volume24hr`):
  the first characterized the raw+leakage-safe category breakdown only (1,998→346 records, Sports
  252); the second (1,998→347, Sports 253) additionally ran the full `evaluate()` OOS harness on the
  Sports-filtered subset. The 1-record day-to-day difference (252 vs. 253, 346 vs. 347) is ordinary
  drift from Gamma's live result set changing between the two calls minutes apart — not a
  discrepancy, consistent with this project's prior cross-run drift observations. Reproducible by
  re-running the same fetcher call on any host with open Polymarket egress (subject to the corpus
  drifting further as more markets resolve).

### External research this run (checked, cross-verified, none new EXP-worthy)
- **Le 2026 (arxiv 2602.19520) exact sports-calibration-by-horizon table, verified via 2 independent
  WebFetch passes** against the paper's own text (not a single-pass summary, per this project's
  standing over-summarization caution): Table 3 reports sports calibration SLOPE by horizon bucket
  (Kalshi-primary, 55,637 markets/43.2M trades; Polymarket cross-validation, 25,340 markets/49.1M
  trades) — 0-1h:1.10, 1-3h:0.96, 3-6h:0.90, 6-12h:1.01, 12-24h:1.05, 24-48h:1.08, **2d-1w:1.04**,
  1w-1mo:1.24, 1mo+:1.74. The bucket closest to this project's 7-day `decision_lead` (2d-1w) shows a
  MILD slope (1.04, near-perfect calibration), far below the 1.74 seen only beyond 1 month. Also:
  large-position-trader compression, which the paper finds POLITICS-dominant (intercept +0.53,
  95% CI [0.29,0.75] on Kalshi), shows NO significant sports analog (+0.07, 95% CI [-0.07,0.26] —
  "in sports markets, no such gap exists"). **Implication for EXP-005 (a tempering caution, not a
  refutation):** if this Kalshi-anchored, Polymarket-cross-validated magnitude transfers to our
  specific 7-day-lead Polymarket-only slice, the a priori expected sports miscalibration there is
  SMALL — B9/this-run's raw ECE (0.091/0.0745) may reflect sample noise or an ECE-vs-slope
  divergence rather than a large, exploitable, persistent bias. Added to EXP-005
  `how_it_could_be_wrong` in GROWTH_STATUS. Standard caveat unchanged: cross-platform transfer is
  unconfirmed, not disproven — this is DATA, not a claim either way.
- **CEPR DP20631 / GWU working paper 2026-001 ("Makers and Takers: The Economics of the Kalshi
  Prediction Market")** — confirmed via 2 independent sources (a WebSearch summary + a direct
  `ideas.repec.org` abstract fetch; the CEPR page itself 403's, paywalled) as the SAME paper already
  logged 2026-06-30 as "the GWU/UCD 2026 paper" (a deferred maker-strategy candidate). Now
  QUANTIFIED, not newly discovered: Kalshi-only, 300K+ contracts since 2021; confirms a
  favorite-longshot pattern for BOTH makers and takers, with makers earning materially higher
  average returns (a specific magnitude — "~1.9% avg positive return above 50¢ after fees" per the
  WebSearch summary — was NOT independently re-verified against the paper's own text this run, so
  is reported as a secondary-source figure, not a verified one). No new EXP; still deferred
  (building a market-making strategy needs bid-ask inventory management this project does not have
  — the 2026-06-30 decision stands unchanged).
- **Cross-venue Polymarket/Kalshi arbitrage** — reconfirmed (public 2026 sources, not independently
  reproduced) bot/speed-dominated: cited ~25ms dual-leg execution, 30-second opportunity windows,
  1-5% typical edge before competition. Consistent with, not new information beyond, this project's
  standing "out of scope for a non-speed bot" conclusion (2026-06-30 and earlier).
- **Generic "paper trading realism" industry caution** (2026 Polymarket-bot-building guides, not
  academic): a cited example of a momentum strategy profiting in paper mode using Gamma bid prices
  but failing live on CLOB ask prices. Checked against this project's own architecture:
  `outcome.price` is sourced from the CLOB **midpoint** (`polymarket_client.get_midpoint`), and
  `cost_model.py` applies fee+slippage on top of it as an approximation of the real bid/ask spread —
  this is the SAME gap already disclosed in the 2026-06-29 SameMarketArbitrage entry ("prices are
  CLOB midpoints not asks... flat 0.5% slippage ≠ the real half-spread"). This external source
  CORROBORATES an already-logged, already-disclosed caveat; it does not surface anything new.
- Egress RE-CONFIRMED open from this environment (routine re-probe, consistent with every prior
  run since 2026-07-04): direct `curl` — `gamma-api.polymarket.com` (301→real content),
  `clob.polymarket.com` (200), `data-api.polymarket.com` (200), `huggingface.co` (200);
  `dune.com` still 403 (unchanged since 2026-07-03); `api.elections.kalshi.com` root path 404s
  (expected — no path given, same as prior runs' finding).

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. EXP-005 stays `insufficient-data` — the corpus now has a known,
  cheap, tractable growth path (merge the volumeNum + volume24hr axes via the existing `--merge`
  flag) rather than a vague "needs more N" or a mis-diagnosed "needs a fetcher rebuild"; the merge
  itself is a mechanical CLI operation this run did not execute (time-bounded to one new-axis probe
  + its OOS test this run, per the standing "one pre-registered test, no retry" discipline — running
  the merge AND a fresh eval in the same run would blur which config produced which result).
- The "Yes Bias" mention-market hypothesis (Deleep et al., SSRN) was not re-checked this run (no
  new secondary source found; the primary SSRN page is still 403, reconfirmed by a direct `curl`
  this run) — status unchanged from Run 15/16/17.

### Self-validation (sources this run)
- EXP-005 volume24hr finding: two live-fetched research-agent scratch runs this run via the
  unmodified `polymarket_history_fetcher.py` + `per_category_diagnostics.py` +
  `scripts/validate_real_oos.evaluate()` (same harness as Run 16/17/B9), seed=42, single run each,
  scripts are research-agent scratch (not committed) — independently re-derivable by anyone running
  the same fetch (subject to the corpus drifting as markets resolve). Direct code read of
  `polymarket_history_fetcher.py:159-227` and the 3 scripts' `order=` call sites confirmed
  `volume24hr` had never been passed anywhere in the repo before this run.
- Le 2026 Table 3: two independent WebFetch passes against `arxiv.org/html/2602.19520v1`, each
  asking a different, specific question (general sports-vs-politics comparison, then the exact
  per-horizon table + platform breakdown) — cross-checked against each other for consistency
  (both reported the same 2d-1w=1.04 / 1mo+=1.74 figures), not taken from a single pass.
- GWU/CEPR paper: WebSearch + a direct WebFetch of `ideas.repec.org/p/gwc/wpaper/2026-001.html`
  (reachable, plain abstract text); the CEPR page itself (`cepr.org/publications/dp20631`) returned
  HTTP 403 (paywalled, disclosed, not hidden) and the raw GWU-hosted PDF did not extract cleanly via
  WebFetch (binary/compressed stream, disclosed) — the "~1.9%"/"~32%" figures come from the
  WebSearch summary only and are flagged above as unverified against the paper's own text.
- Egress: direct `curl` from this session against the same domain set as every prior run.

**Binding constraint STANDS:** no validated real-money OOS edge. This run's real contribution is
correcting an over-pessimistic diagnosis from the prior run (EXP-005's Sports corpus was NOT
structurally stuck — an existing, untried parameter grew it 87% in one fetch) while adding an
external, cross-checked caution (Le 2026's exact horizon table) that tempers how large an edge to
expect even once N is sufficient — both more useful to the next run than either a forced EXP-006 or
an uncritical re-statement of Run 17's "needs a rebuild" framing.

## 2026-07-11 — Research Run 19: EXP-005 finally TESTED (N=814, real trades) — FRAGILE + statistically insignificant, not a validated edge; a much stronger sampling lever found (`tag_id=1`, Gamma's real "Sports" tag, supersedes the Run 18 merge recommendation); UMA dispute-rate DATA point logged as a growing selection-bias caveat

- Hypothesis (falsifiable): **EXP-005**, unchanged since 2026-07-08 — a `CalibrationBucketStrategy`
  fit exclusively on Polymarket Sports-category resolved markets (7-day decision lead) produces a
  positive, non-fragile (F10), F11-significant net OOS PnL, once N clears `min_bucket_n=30` per
  bucket. Prior runs (16/17/18) could never reach that floor (Sports N stuck at 134→135→253 across
  three different sampling axes). This run's contribution: found and used a stronger axis, which
  finally let the mechanism trade — and the result answers the hypothesis for the first time.
- Min sample N: 100 (EXP-005's pre-registered floor) / ≥300-400 (the floor needed for the 10-bucket
  model to reliably clear `min_bucket_n=30` per bucket, per Run 18).
- OOS result: **TESTED — not insufficient data anymore. NOT a validated edge (fragile + statistically
  insignificant).** Method: re-read `PolymarketHistoryFetcher`/`validate_real_oos.py` and found
  `validate_real_oos.py` already exposes a `--tag-id` CLI flag (ROADMAP A7/#285/#295, landed
  2026-07-10, apparently not yet exercised by a research run against the correct id). Prior runs
  (17/18) had only tried `tag_id=100639` ("Games", the example id named in the #285 commit message) —
  this run first resolved the CORRECT id via Gamma's own tag API: `GET
  gamma-api.polymarket.com/tags/slug/sports` → `id=1`, `label="Sports"` (a real Gamma tag, `forceHide:
  true` on the consumer site's nav, but still server-side filterable via `/markets?tag_id=1`; verified
  with a 5-record live curl before committing to the run — top hits were the Kings/Raptors NBA-Finals
  and Egypt/Morocco/USA World-Cup markets, i.e. genuinely Sports). PRE-REGISTERED
  (before running, not tuned after seeing PnL): `python scripts/validate_real_oos.py --tag-id 1
  --decision-lead-days 7 --seed 42 --max-pages 20 --limit 100 --json`, single run, ~9 minutes
  wall-clock, unmodified repo code (research-agent scratch invocation only). Result: **814
  leakage-safe Polymarket Sports records** — by far the largest single-run Sports-tagged corpus this
  project has ever assembled (vs. 134/135/253 on the three prior axes; exceeds the ≥300-400 floor in
  one fetch, no merge needed) — crowd_brier=0.2072, base_rate=0.4189, 9.3% pinned.
  `CalibrationBucketStrategy` FINALLY traded: **268 trades, net +$16,993.97 OOS.** But:
  - **F11 significance: `indistinguishable_from_zero`.** 95% bootstrap CI on total OOS PnL =
    `[-17164.66, 49793.75]` — spans zero by a wide margin. `is_significant_edge: false`. Hit rate
    49.25% (95% CI [43.3%, 55.2%]) — at or below a coin flip; the positive total PnL comes from
    payoff asymmetry (Kelly-sized wins on underpriced favorites), not from picking more winners than
    losers, which is exactly the profile the significance gate exists to catch.
  - **F10 regime-slice: FRAGILE (concentrated), same failure mode as every prior positive
    bucket-calibration result on this project.** 125% of net PnL from a single category bucket
    (`General`) — over 100% because the other 2 categories in this corpus were net NEGATIVE; 100% of
    net PnL from a single horizon bucket (`3-7d`); 112% from a single confidence bucket (`25-50%`);
    leave-one-out on the top category flips the total to **-$4,319.43** — remove the one bucket
    carrying the "edge" and the whole result goes negative. This is textbook overfitting/curve-fit
    concentration, not a real, generalizable edge.
  - **A genuine labeling mismatch, surfaced honestly (not asserted as a code bug, no fix attempted —
    research-agent scope ends at the finding):** the corpus was fetched via Gamma's own `tag_id=1`
    ("Sports") filter — every raw market IS Sports by Polymarket's own tagging. Yet the regime-slice's
    INTERNAL category breakdown (this repo's `market_category.py` keyword-based deriver, a different,
    independent classifier from Gamma's tag) buckets the overwhelming majority of these same markets
    as `"General"`, not `"Sports"` (only 3 categories appear at all in the slice, and `General` alone
    exceeds 100% of PnL). So "EXP-005: Sports-category CalibrationBucketStrategy" as originally
    specified (which relies on the INTERNAL deriver's `category=="Sports"` label, per the
    `oos_plan` in GROWTH_STATUS) and this run's Gamma-tag-driven corpus are not quite the same
    population — most of these Gamma-tagged-Sports markets' question text apparently doesn't match
    `market_category.py`'s Sports keyword list closely enough to be internally re-labeled Sports. Not
    re-tested with the internal filter applied on top (would be a second, un-pre-registered look at
    the same corpus — deferred to a fresh run with its own pre-registration if the factory wants to
    close this gap).
- Calibration (Brier / reliability): reported above (crowd_brier=0.2072 on this corpus); the alpha's
  own calibration was not separately re-run (F11/F10 are the load-bearing gates here, per the existing
  `validate_real_oos.py` harness — unchanged from prior runs' methodology).
- Costs modeled: yes, unmodified `cost_model.py` via `walk_forward` (same as every prior EXP-002/003/005
  run) — the reported PnL is already net of fees + slippage.
- Verdict: **tested — fragile + not significant (edge-not-proven).** This is the FIRST time EXP-005 has
  produced a real trading result (not an abstention), which resolves the "insufficient data" status
  that has stood since 2026-07-08 — but the answer is negative: the bucket-calibration mechanism does
  NOT produce a robust Sports edge on this corpus, joining EXP-002 (2026-07-04, clean negative) and the
  4th-run HuggingFace/recency-alpha tests (2026-07-04, sign-unstable/fragile) as the Nth independent
  corpus on which this strategy FAMILY fails to clear both the significance bar AND the
  concentration/robustness bar. Per the standing "bucket-calibration family confirmed non-robust"
  finding (2026-07-04, 4th run), this is corroboration, not a new discovery — but it is the first
  Sports-specific data point, closing that gap.
- Why / self-validation methodology: direct code read of `scripts/validate_real_oos.py --help` (already
  supports `--tag-id`, landed by the factory 2026-07-10 per ROADMAP A7 #295 — this run is the first to
  actually invoke it against a correctly-resolved Sports id); `curl` against
  `gamma-api.polymarket.com/tags/slug/sports` + a 5-record live spot-check of `/markets?tag_id=1` BEFORE
  committing to the pre-registered run (to confirm the id resolves to real sports markets, not to tune
  the run after seeing a result); one single `validate_real_oos.py` invocation, no retry after seeing
  the number (per the standing "pre-registered, no p-hacking" discipline); raw JSON output saved to a
  research-agent scratch path (not committed — reproducible by any host with open Polymarket egress,
  subject to the live corpus drifting as more Sports markets resolve). Egress re-confirmed open
  (gamma-api/clob/data-api.polymarket.com, huggingface.co all 200; dune.com still 403 — unchanged
  since 2026-07-03).
- **CORRECTS Run 18's `next_actions` recommendation:** Run 18 recommended merging the `volumeNum` +
  `volume24hr` axes via `--merge` to push Sports N toward 300-400. That recommendation is now
  SUPERSEDED, not merely completed differently — `tag_id=1` alone reached N=814 (more than double the
  floor) in one run, zero merge operation, zero code change, using a flag the factory had ALREADY
  shipped (#295) for exactly this purpose but that no run (research or factory) had yet pointed at the
  correct id. Any future per-category corpus growth (for EXP-003 politics, or other categories) should
  reach first for `--tag-id` with the id resolved via `GET /tags/slug/<name>`, not the `order=` sort-field
  workarounds explored in Runs 17/18 — `tag_id` is a genuine server-side category filter; `order` is
  only a re-sort of a fixed top-N window.

### External research this run (checked, none new-EXP-worthy; one operational data-integrity caveat added)
- **Cross-venue arbitrage compression, reconfirmed with a sharper number:** multiple 2026 industry
  sources (non-academic, consistent with each other and with this project's standing conclusion) now
  describe cross-venue Polymarket/Kalshi arbitrage windows compressing from "~5 minutes in 2024" to
  "~30 seconds in 2026" as bot competition intensifies, alongside a separate claim that AI agents now
  run 30%+ of Polymarket wallets and account for 14 of the top 20 most profitable accounts. Treated as
  DATA (marketing/industry blog sourcing, not academic, not independently reproduced) that reinforces —
  does not newly justify — the existing "cross-venue arb is bot/speed-dominated, out of scope for a
  non-speed bot" conclusion (standing since 2026-06-30). No change to B8's status.
- **UMA oracle dispute rate rising sharply in 2026 (Wall Street Journal investigation, cited via
  secondary industry sources, not independently fetched — the primary WSJ piece is paywalled):**
  Polymarket has logged 1,150+ disputed markets in 2026 already, surpassing all of 2025; more than half
  of UMA votes in disputed markets reportedly come from the platform's ten largest wallets, and roughly
  1-in-5 disputes reportedly involve a voter with a financial stake in the outcome being judged. **Not a
  new alpha candidate** (governance-quality issues on a third-party oracle are not an in-scope
  calibration/logical-consistency edge per the PLAYBOOK's edge thesis), but a legitimate DATA-INTEGRITY
  caveat worth carrying forward: this project's resolved-history fetchers already exclude
  contested/disputed markets by design (disclosed selection bias, logged since 2026-06-28). If dispute
  rates are structurally rising, that exclusion increasingly filters out a growing, not-necessarily-random
  slice of "hard" markets — a reason to treat the calibration numbers this project measures (crowd Brier
  ~0.08-0.21 across various corpora) as representative of "cleanly-resolved" Polymarket, not "all of
  Polymarket," and to re-state that caveat more prominently as time passes. No EXP proposed; logged for
  future disclosure language only.
- **Market-making / maker-taker research reconfirmed, still deferred:** the already-logged GWU/CEPR
  Kalshi maker-taker paper was joined by a second, consistent 2026 preprint (Palumbo, "A Microstructure
  Perspective on Prediction Markets") finding NFL-market liquidity providers on Kalshi profit (~$29M
  aggregate over one season) by deliberately NOT flattening inventory to zero — managing directional
  imbalance rather than eliminating it, unlike a classical market maker. Corroborates, does not change,
  the 2026-06-30 decision to defer market-making (this project has no bid-ask inventory/depth
  infrastructure).
- Egress RE-CONFIRMED open (routine re-probe, same domain set as every prior run since 2026-07-04):
  `gamma-api.polymarket.com` 200, `clob.polymarket.com` 200, `data-api.polymarket.com` 200,
  `huggingface.co` 200; `dune.com` still 403.

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. EXP-005 moves from `insufficient-data` to a tested, negative
  (fragile + insignificant) result — see GROWTH_STATUS. The internal-vs-Gamma category-label mismatch
  surfaced above is a data-quality observation for a future factory run, not a new alpha hypothesis.
- The "Yes Bias" mention-market hypothesis (Deleep et al., SSRN) was re-checked this run: the primary
  SSRN page (`papers.ssrn.com/sol3/papers.cfm?abstract_id=6322678`) is directly identified now (prior
  runs only had it via a QuantPedia summary) but still returns HTTP 403 to a direct fetch from this
  environment — unchanged, still unverifiable against the paper's own text/N/magnitude.

### Self-validation (sources this run)
- EXP-005 tag_id=1 finding: one live-fetched, pre-registered `validate_real_oos.py --tag-id 1` run this
  session (seed=42, decision_lead_days=7, max_pages=20, limit=100), unmodified repo code, output saved
  to a research-agent scratch path (not committed) — independently re-derivable by anyone running the
  same command (subject to the corpus drifting as more Sports markets resolve, and to Gamma's own
  `tag_id=1` assignment changing). Gamma tag resolution (`id=1`↔"Sports") independently confirmed via
  `GET /tags/slug/sports` and a 5-record `GET /markets?tag_id=1` spot-check before the pre-registered run.
- UMA dispute-rate figures: secondary industry-source summaries only (WSJ primary piece paywalled, not
  independently fetched) — flagged above as unverified-primary, DATA not a claim.
- Cross-venue arb / AI-agent-wallet-share figures: non-academic industry/marketing blog sourcing, not
  independently reproduced — DATA, consistent with the standing conclusion, not new evidence for it.
- Palumbo maker-taker paper: identified via WebSearch summary only, not independently fetched against
  its own text this run (mirrors the existing GWU/CEPR paper's verification level).

**Binding constraint STANDS:** no validated real-money OOS edge. This run's real contribution is
answering EXP-005 for the first time (tested, not insufficient-data; result is fragile + insignificant,
not an edge) and finding a materially better per-category sampling lever (`tag_id`, resolved via
`GET /tags/slug/<name>`) that should replace the `order=`-sort-field workarounds in future per-category
corpus-growth attempts (EXP-003 politics is the next direct beneficiary — same `--tag-id` mechanism,
different id).

---

## 2026-07-12 — Research Run 20: EXP-003 (Politics, tag_id=2) TESTED — N=1,369, 472 trades, +$28,815.49
OOS, but F11 indistinguishable-from-zero + F10 fragile — same failure pattern as EXP-005; the
bucket-calibration family is now non-robust on 3 independent real per-category corpora (general,
Sports, Politics); a genuinely different mechanism (political-market price-reversal after hype spikes)
surfaced from a new named academic source, logged as candidate EXP-006 (not tested this run)

- Hypothesis (falsifiable): **EXP-003**, unchanged since 2026-06-30 — a `CalibrationBucketStrategy`
  fit exclusively on Polymarket political-category resolved markets (7-day decision lead) produces a
  positive, non-fragile (F10), F11-significant net OOS PnL — motivated by Le 2026's political
  bilateral-partisan-cancellation finding. This run applies the `tag_id`-resolution lever Research
  Run 19 (2026-07-11) found for EXP-005/Sports to EXP-003/Politics, per that run's own `next_actions`
  recommendation.
- Min sample N: 100 (EXP-003's pre-registered floor) / ~300-400 (the floor needed for the 10-bucket
  model to reliably clear `min_bucket_n=30` per bucket, per the EXP-005 precedent).
- OOS result: **TESTED — not insufficient data. NOT a validated edge (fragile + statistically
  insignificant), joining EXP-002 and EXP-005.** Method: resolved the real Gamma tag ids for both
  candidate labels named in the EXP-003 hypothesis text (`"politics" or "elections"`) via
  `GET gamma-api.polymarket.com/tags/slug/politics` → `id=2` and `.../tags/slug/elections` → `id=144`;
  spot-checked both with a live 5-record `GET /markets?tag_id=<id>&closed=true` BEFORE committing to
  the run (both returned genuine 2024 presidential-nomination markets — Trump/DeSantis/Haley/Biden/
  Harris — confirming both ids are real and on-topic). The two tags overlap heavily on this sample
  (near-identical top hits), so testing both would not be an independent second look; PRE-REGISTERED
  `tag_id=2` ("Politics", the broader parent label matching the hypothesis's primary wording) as the
  single run, not both. Command (unmodified repo code, no retry after seeing the number):
  `python3 scripts/validate_real_oos.py --tag-id 2 --decision-lead-days 7 --seed 42 --max-pages 20
  --limit 100 --json`. Result: **1,369 leakage-safe Polymarket Politics records** (more than 3x the
  ~300-400 floor in one fetch, no merge, no code change — same `tag_id` mechanism Run 19 validated on
  Sports) — crowd_brier=0.0886, base_rate=0.2001, 60.7% pinned (a much MORE pinned corpus than
  EXP-005's Sports pull (9.3% pinned) — political tag markets skew toward long-settled, heavily-arbed
  presidential-nomination contracts). `CalibrationBucketStrategy` traded: **472 trades, net
  +$28,815.49 OOS** — a larger nominal PnL than EXP-005's Sports result. But:
  - **F11 significance: `indistinguishable_from_zero`.** 95% bootstrap CI on total OOS PnL =
    `[-36648.21, 105232.67]` — spans zero by an even wider margin than EXP-005's CI. `is_significant_edge:
    false`. Hit rate **25.64%** (95% CI [21.6%, 29.7%]) — starkly below a coin flip (lower than
    EXP-005's already-poor 49.25%), confirming the positive total PnL is pure payoff-asymmetry from a
    small number of large wins on deep longshots, not genuine predictive skill.
  - **F10 regime-slice: FRAGILE (concentrated), the identical failure mode as EXP-005 and every prior
    positive bucket-calibration result on this project.** 134% of net PnL from a single category
    bucket (`General`, 51.6% of budget) — over 100% because other categories net negative; 100% from a
    single horizon bucket (`3-7d`); 109% from a single confidence bucket (`10-25%`); leave-one-out on
    the top category flips the total to **-$9,665.99**; and (new this run, a sharper concentration flag
    than EXP-005 surfaced) **57% of net PnL from ONE single market** — over half the "edge" is one
    trade. Textbook overfitting/concentration, not a generalizable edge.
  - **The internal-vs-Gamma category-label mismatch Research Run 19 surfaced on Sports is CONFIRMED on
    a second corpus, not a one-off:** the corpus was fetched via Gamma's own `tag_id=2` ("Politics")
    filter — every raw market IS Politics by Polymarket's own tagging. Yet this repo's independent,
    keyword-based `market_category.py` deriver buckets the majority of the SAME markets as `"General"`,
    not `"Politics"` (the top fragile-reason bucket, 51.6% of budget). Same taxonomy gap as EXP-005,
    now observed on a second, disjoint category — raises this from "a labeling gap for a future run"
    to a **recurring, systematic limitation of the internal keyword-based classifier** relative to
    Polymarket's own tag taxonomy. Not fixed this run (research-agent scope ends at the finding).
- Calibration (Brier / reliability): crowd_brier=0.0886 on this corpus (a SHARPER/more-calibrated
  crowd than EXP-005's Sports corpus, crowd_brier 0.2072 — consistent with the much higher pinned
  fraction here); the alpha's own calibration was not separately re-run (F11/F10 are the load-bearing
  gates, unchanged methodology from every prior EXP-002/003/005 run).
- Costs modeled: yes, unmodified `cost_model.py` via `walk_forward` (same as every prior run) — the
  reported PnL is already net of fees + slippage.
- Verdict: **tested — fragile + not significant (edge-not-proven).** This is the FIRST time EXP-003
  has produced a real trading result (prior status: `proposed`, blocked on corpus size since
  2026-06-30) — resolves the corpus-size blocker exactly as Run 19 predicted, but the answer is
  negative, the SAME shape as EXP-005: large nominal PnL driven by a low hit rate and extreme
  single-bucket/single-market concentration, failing both the significance and robustness bars.
- Why / self-validation methodology: direct `curl` resolution of both candidate tag ids
  (`/tags/slug/politics` → 2, `/tags/slug/elections` → 144) + a live 5-record spot-check of each via
  `GET /markets?tag_id=<id>&closed=true&limit=5` BEFORE committing to the pre-registered run (to
  confirm the ids resolve to real political markets, not to tune after seeing a result); one single
  `validate_real_oos.py` invocation, no retry after seeing the number; raw JSON output saved to a
  research-agent scratch path (not committed — reproducible by any host with open Polymarket egress,
  subject to the live corpus drifting as more markets resolve). Egress re-confirmed open this run
  (gamma-api/clob/data-api.polymarket.com, huggingface.co all 200; dune.com still 403 — unchanged
  since 2026-07-03).
- **Operational finding (new, not previously logged): Kalshi's candlestick endpoint rate-limits
  heavily under this script's default batch fetch.** The run's default `--venues` includes Kalshi
  alongside Polymarket (the `--tag-id` flag is Polymarket-only per the script's own `--help` text,
  correctly ignored for Kalshi); this run's Kalshi lane logged **854 HTTP 429 (Too Many Requests)**
  responses from `api.elections.kalshi.com/.../candlesticks` and consequently skipped **1,200** Kalshi
  markets for "no leakage-safe price" — the fetcher's honest, no-fabrication behavior (never invents a
  decision price when the API rate-limits it away), so the Kalshi lane correctly reported `N/A — 0
  leakage-safe records` rather than a corrupted result. Not a correctness bug and not blocking (the
  Polymarket lane, which `--tag-id` targets, was unaffected) — logged as a DATA point for a future run
  that specifically wants a real Kalshi OOS corpus: at this batch size, Kalshi's public candlesticks
  endpoint needs throttling/backoff to yield usable N, a fetcher-hardening item, not investigated
  further this run (out of scope for a Polymarket-tag_id-focused test).

### THE headline finding this run: the static bucket-calibration family is now non-robust on 3
### independent real per-category corpora — re-testing more categories with the SAME mechanism is
### low-value; a genuinely different mechanism is needed
  Combining this run with the prior two real per-category/all-category tests of
  `CalibrationBucketStrategy` on real Polymarket data:
  - EXP-002 (all categories, 7-day lead, N=510, 2026-07-04): walk-forward PnL **-$2,938.70**/46
    trades (net NEGATIVE); static 60/40 split B2 gate also negative and significant the WRONG way.
  - EXP-005 (Sports, `tag_id=1`, N=814, 2026-07-11): **+$16,993.97**/268 trades nominal, but F11
    indistinguishable-from-zero (hit rate 49.25%) + F10 fragile (125% of PnL in one category bucket,
    leave-one-out flips to -$4,319.43).
  - EXP-003 (Politics, `tag_id=2`, N=1,369, this run): **+$28,815.49**/472 trades nominal, but F11
    indistinguishable-from-zero (hit rate 25.64%, even further below a coin flip) + F10 fragile (134%
    of PnL in one category bucket, leave-one-out flips to -$9,665.99, 57% from ONE market).
  Every one of the three real-corpus results that actually traded (Sports, Politics) shows the SAME
  shape: a large nominal positive headline PnL that a naive read could mistake for a strong edge,
  produced by a hit rate at-or-below chance and extreme concentration in a handful of longshot bets —
  caught only because F10/F11 exist. This is not three independent coin flips landing the same way by
  chance; it is a **structural property of the mechanism**: a static per-price-bucket empirical
  calibration model, sized with cost-net Kelly, systematically finds a small number of very-low-price
  ("longshot") markets where the fitted bucket rate exceeds the crowd price by more than the cost
  band, bets big on them via Kelly's convexity at low prices, and the resulting PnL is dominated by
  whichever few of those bets happen to resolve YES in the OOS window — a payoff-lottery, not a
  calibration edge. **Recommendation (RECOMMEND-only, not a ROADMAP steer — this is a negative,
  not a high-confidence positive finding): a fourth category-only re-run of the SAME static
  bucket-calibration mechanism (e.g. Economics/Crypto via their own `tag_id`) is low expected
  information value — the mechanism itself, not the category, is now the suspect. Future OOS-testing
  effort is better spent on a mechanism that does NOT concentrate on illiquid longshot convexity by
  construction:** e.g. a rolling/recency-weighted bucket fit (raised as a candidate in EXP-002's
  2026-07-04 entry, never built), a bucket model with an explicit per-trade concentration/liquidity
  cap, or a structurally different edge source (B8 cross-venue coherence; a genuine reversal/momentum
  strategy — see EXP-006 below).

### New candidate this run (from external research, NOT tested — proposed as EXP-006)
- **Political-market price-reversal after hype-driven spikes (Clinton & Huang, Vanderbilt, 2025/2026,
  OSF preprint `ideas.repec.org/p/osf/socarx/d5yx2_v1.html`, also covered by DL News/Yahoo
  Finance/financialcontent.com secondary reporting):** N>2,500 political prediction markets across
  Polymarket/Kalshi/PredictIt/Iowa Electronic Markets, final 5 weeks of the 2024 U.S. presidential
  election, $2B+ in transactions. The paper's OWN abstract text (fetched directly, not just a
  secondary summary) states daily price changes were "weakly correlated or negatively autocorrelated"
  — i.e., a price spike tends to partially reverse, not persist, consistent with herd/hype-driven
  overreaction rather than durable information arrival. **CAVEAT (methodology discipline applied):**
  the specific "58% of Polymarket's national presidential markets showed negative serial correlation"
  figure appears ONLY in secondary reporting (DL News, financialcontent.com), not verified against the
  primary abstract's own text this run (the abstract only gives the qualitative direction, no
  percentage) — flagged as an unverified-primary secondary-source figure, not a confirmed one, per this
  project's standing WebFetch-over-summarization discipline. Structurally DIFFERENT from the refuted
  bucket-calibration family: this is a **resolution-timing / overreaction edge** (fade a price spike
  after unusually large short-window moves), not a static price-level calibration bucket — a null
  result on one family does not predict a null result on the other, and it is squarely in-scope per
  the PLAYBOOK edge thesis (resolution-timing / news-reaction speed; crowd overreaction is a form of
  miscalibration in TIME, not just in price level).
  - **Falsifiable hypothesis (if built as EXP-006):** Polymarket political-market YES prices that move
    by more than a threshold Δ within a short window (e.g. 1-3 days) exhibit negative serial
    correlation over the following 1-3 days — i.e., a large short-window price move partially reverses
    — and a strategy that fades such spikes (buys the opposite side after an outsized move, sized via
    cost-net Kelly, capped per-market to avoid the single-market-concentration failure mode surfaced
    above) produces a positive, F11-significant, F10-non-fragile net OOS PnL after realistic costs.
  - **Min sample N (proposed):** at least 100 qualifying spike events (a Δ-threshold crossing), spanning
    ≥3 distinct election cycles/news events to avoid a single-event concentration failure (the SAME
    failure mode that just sank EXP-003 here) — a single election cycle (e.g. only 2024 U.S.
    presidential) would risk the identical single-market-dominance problem.
  - **OOS plan (proposed, not yet built):** requires a NEW data capability this repo does not have —
    a short-interval (sub-daily) price-history puller keyed to political-tag markets (the existing
    `HistoricalMarket` fetchers capture ONE pre-decision snapshot per market, not an intraday price
    series), plus a spike-detection + reversal-labeling pipeline. This is genuinely NEW factory-build
    scope, not a parameter tweak on existing code — logged to `next_actions`, not built this run.
  - **Cost assumptions:** 2% fee + 0.5% slippage baseline (cost_model.py) PLUS an explicit
    per-trade/per-market notional cap (the single-market-57%-of-PnL failure mode above shows an
    uncapped mechanism will over-concentrate regardless of the underlying signal's quality) — a NEW
    requirement this project's existing strategies do not yet enforce.
  - **How EXP-006 could be wrong (adversarial pre-mortem, applied to a proposal not yet tested):**
    (1) the reversal effect may be specific to the extreme volume/attention of a presidential election
    ($2B+ over 5 weeks) and not generalize to the much lower-volume political markets available for a
    fresh OOS test today (2026 is not an election year); (2) "negative serial correlation" in DAILY
    price changes does not automatically imply a profitable TRADEABLE reversal once bid-ask
    spread/slippage on the reversal trade itself is charged — the QuantPedia "mean-reversion on
    Polymarket" backtest (checked this run, see below) is a direct cautionary example of exactly this
    gap; (3) a spike-detection threshold is a NEW free parameter with real overfitting risk (which Δ,
    which window) — must be pre-registered before any real data is seen, not tuned post-hoc; (4) the
    single-market-concentration failure mode that just sank EXP-003 is a live risk here too if
    reversal opportunities cluster around a small number of high-profile events (e.g. one election
    night) — the proposed per-market notional cap is a mitigation, not a guarantee.
  - **NOT proposed as ready-to-test:** genuinely new fetcher-build scope (intraday price series +
    spike labeling), not a re-run of an existing script — the honest "insufficient infrastructure",
    not "insufficient data".

### Adversarial cross-check this run: a "mean-reversion on Polymarket" backtest exists and is a
### cautionary example, not independent corroboration
  Found via the same search thread: QuantPedia's "Exploiting Mean-Reversion in Decentralized
  Prediction Markets: Evidence from Polymarket Binary Contracts" (Cyril Dujava, Quantpedia — original
  research, not a peer-reviewed academic source; fetched directly, not just a summary). Checked in
  detail because it sounds like independent corroboration of the EXP-006 direction above — **it is
  NOT**, and is logged here specifically so a future run does not mistake it for supporting evidence:
  - **N=3 contracts only** ("Jesus Christ return in 2025", "China invade Taiwan in 2025", "US confirm
    aliens exist in 2025") — novelty/meme markets, not a representative political or economic universe.
  - **12 strategy variants tested per contract** (lookback ∈ {5,10,20} days × holding ∈ {1,2,3,5} days)
    — a 3-asset × 12-variant search is a severe multiple-comparisons/curve-fit setup with no
    correction disclosed.
  - **Cost-fragile:** the BEST zero-spread variant on the "Jesus" contract (+7.95% CAR, Sharpe +2.97)
    FLIPS NEGATIVE at a realistic 10bps/trade cost (-7.83% CAR, Sharpe -2.60) — the theoretical edge
    does not survive modest realistic friction, the exact failure mode this project's cost_model
    discipline exists to catch. Only one of the ~36 tested combinations (China contract, 20-day
    lookback/5-day hold) survives cost-adjustment (+18.91% CAR, Sharpe +1.96) — one surviving cell out
    of 36 on 3 idiosyncratic assets is consistent with noise, not evidence of a real, generalizable
    reversal edge.
  - **Conclusion:** this is a textbook illustration of the SAME p-hacking/small-N/cost-fragility risks
    named in EXP-006's own pre-mortem above, not independent support for it. Logged so a future run
    citing "mean-reversion on Polymarket has been shown to work" catches itself — it has not been shown
    to work by this source; if anything it is evidence FOR treating EXP-006 cautiously and building it
    only with a pre-registered, uncherry-picked design.

### Candidate alphas NOT proposed as ready-to-test this run (reasons)
- EXP-006 (political price-reversal) is logged as a candidate hypothesis with a falsifiable spec, not
  a ready-to-run EXP — it needs new fetcher infrastructure (intraday price series) this repo does not
  have. Not proposed as `proposed` status in GROWTH_STATUS experiments[] this run (that status is
  reserved for experiments with a runnable OOS plan against EXISTING infra, per this project's own
  convention for EXP-001 through EXP-005); logged here in RESEARCH_MEMORY + `next_actions` instead, so
  a future run/factory build can pick it up once the infra question is resolved.
- A fourth static-bucket-calibration category re-run (Economics/Crypto via their own `tag_id`) was
  considered and explicitly NOT run this run — see "the headline finding" above: the mechanism, not
  the category, is now the suspect, so another same-mechanism data pull is low expected value relative
  to the "one pre-registered test per run" discipline already spent on EXP-003 above.

### Self-validation (sources this run)
- EXP-003 tag_id=2 finding: one live-fetched, pre-registered `validate_real_oos.py --tag-id 2` run
  this session (seed=42, decision_lead_days=7, max_pages=20, limit=100), unmodified repo code, output
  saved to a research-agent scratch path (not committed) — independently re-derivable by anyone
  running the same command (subject to the corpus drifting as more Politics markets resolve, and to
  Gamma's own `tag_id=2` assignment changing). Gamma tag resolution (`id=2`↔"Politics", `id=144`↔
  "Elections") independently confirmed via `GET /tags/slug/politics` + `GET /tags/slug/elections` and a
  5-record spot-check of each before the pre-registered run.
- Clinton & Huang (Vanderbilt): primary abstract fetched directly from `ideas.repec.org` (a plain
  abstract-hosting page, reachable unlike SSRN); the specific "58%" serial-correlation figure is
  secondary-source-only (DL News, financialcontent.com), flagged as such, not independently verified
  against the primary text.
- QuantPedia mean-reversion backtest: fetched directly (quantpedia.com, reachable); all figures
  (CAR/Sharpe by variant, cost-fragility) taken from the page's own reported numbers, not a
  third-party summary.
- Egress: direct `curl` from this session against the same domain set as every prior run
  (gamma/clob/data-api.polymarket.com, huggingface.co 200; dune.com still 403).

**Binding constraint STANDS:** no validated real-money OOS edge. This run's real contribution is
completing the `tag_id`-lever rollout Research Run 19 recommended (EXP-003 now tested, not
insufficient-data) and — more importantly — recognizing the PATTERN across three real-corpus tests
(EXP-002/003/005) as a property of the bucket-calibration MECHANISM, not of any one category, which
should redirect future OOS-testing effort away from a fourth same-mechanism category re-run and toward
either a differently-shaped mechanism (a concentration-capped/recency-weighted bucket model, or the
genuinely different EXP-006 price-reversal candidate surfaced this run) or the still-open B8
cross-venue coherence direction. EXP-006 is a hypothesis with a real, checked academic anchor and an
honest adversarial cross-check (the QuantPedia cautionary example) — not yet an EXP with a runnable OOS
plan, logged for a future run/factory-build cycle.

---

## 2026-07-13 — Research Run 21: EXP-006's claimed infra gap is OVERSTATED (the intraday price primitive
already exists, live-verified at 1-minute fidelity); a real single-case caveat found (the July 2024
assassination-attempt spike did NOT reverse); a WebSearch-synthesis fabrication caught + corrected before
being logged as data; no new EXP proposed, concentration-capped bucket redesign recommended as the
lower-cost next factory step

- Hypothesis (falsifiable): n/a — this run is a scoping + self-validation pass on EXP-006 (political
  price-reversal after hype spikes, surfaced 2026-07-12/Run 20) plus a routine research sweep, not a new
  alpha test. Binding constraint UNCHANGED: no validated real-money OOS edge exists; the bucket-calibration
  family (EXP-002/003/005) remains non-robust on 3 independent real per-category corpora.
- Min sample N: n/a this run (a feasibility probe, N=1 illustrative case only — explicitly not a test).
- OOS result: n/a — no edge tested or claimed this run.
- Calibration (Brier / reliability): not measured this run.
- Costs modeled: n/a.
- Verdict: **edge-not-proven** (scoping + self-validation + methodology-integrity catch only).
- Why:

### (1) EXP-006's stated blocker ("needs a NEW intraday/sub-daily price-history fetcher") is OVERSTATED —
### the raw data primitive already exists and already supports 1-minute granularity, LIVE-VERIFIED
  Run 20 logged EXP-006's OOS plan as needing "a genuine factory-build item... the existing
  `HistoricalMarket` fetchers capture ONE pre-decision snapshot per market, not an intraday price series."
  That is true of the ASSEMBLED `HistoricalMarket` records, but a direct code read of
  `polymarket_history_fetcher.py:317-339` shows `PolymarketHistoryFetcher.fetch_price_history(token_id,
  start_ts, end_ts, fidelity)` already calls CLOB `/prices-history` and returns the FULL raw tick list
  (`[{"t":..., "p":...}, ...]`) for the requested window — every `to_historical_market*` method just
  throws away all but the single last-pre-decision tick via `_last_pre_decision_price`. The raw series was
  already being fetched and discarded, not absent. **LIVE-VERIFIED this run** (egress open, direct `curl`
  against `clob.polymarket.com/prices-history`, not just a code read): fetched the real Trump-2024
  election YES token (`21742633...8836455`, the single largest Polymarket market ever, $1.53B volume, real
  `clobTokenIds` resolved via `GET gamma-api.polymarket.com/markets?tag_id=2&closed=true&order=volumeNum`)
  with `fidelity=1` over a real 4-day window (2024-07-12 to 2024-07-16 UTC, spanning the July 13
  assassination attempt) — returned **5,760 real ticks at EXACTLY 60-second spacing** (median spacing
  computed directly from the response, not assumed). So `fidelity=1` (1-minute bars) genuinely works
  end-to-end against the live CLOB API today, no code change. **Revised scope estimate for EXP-006:** what
  is actually missing is (a) a spike-DETECTION function over an already-fetchable tick series (threshold-Δ
  crossing within a window) and (b) a reversal-labeling + backtest harness — smaller, more tractable build
  scope than "a new fetcher," though still genuine factory-build work (a research-agent scratch probe does
  not build strategy code), and still needs the per-market notional concentration cap Run 20 already
  flagged as a hard requirement (see finding 2 below for why that requirement is not hypothetical).
- **Self-validation methodology:** unmodified repo code read (`polymarket_history_fetcher.py`, no changes);
  the live probe used only direct `curl` against public, no-auth Gamma/CLOB endpoints + a `python3` scratch
  script (not committed) to parse timestamps/spacing — reproducible by anyone with open Polymarket egress,
  subject to the CLOB history for this specific window not changing (it is fully historical/settled, so it
  should not drift). Egress reconfirmed open this run: `clob.polymarket.com` prices-history 200,
  `gamma-api.polymarket.com` 200, `data-api.polymarket.com` 200 (routine re-probe, consistent with every
  run since 2026-07-04).

### (2) A real, honest single-case illustration: the highest-salience political price spike of the entire
### 2024 cycle did NOT reverse — it kept trending in the SAME direction (a live caution for EXP-006's core
### premise, not a test of it)
  Using the same live-fetched 1-minute tick series: the YES price was flat at **0.595** for the hour before
  the July 13, 2024 assassination attempt (~22:11 UTC), then rose to **0.685 by +24h** and **0.705 by +48h**
  (near the end of the fetched window) — a sustained, monotonic-in-direction move, not a spike-then-fade.
  **Explicitly flagged as N=1 and NOT a test of EXP-006** — a single anecdote proves nothing statistically
  and is not offered as one. But it is a directly relevant, verifiable illustration of an ALREADY-LOGGED
  EXP-006 pre-mortem concern (Run 20, item 1): Clinton & Huang's headline finding is about AGGREGATE daily
  serial correlation across 2,500+ markets, most of which are far smaller/less newsworthy than "an
  assassination attempt on a presidential nominee" — a finding that a typical/small spike weakly reverts on
  average is fully compatible with the LARGEST, most information-laden spikes persisting or even
  compounding (a real regime shift, not overreaction). If EXP-006 is ever built, this is a concrete reason
  to (a) stratify spike events by size/salience rather than pooling all Δ-threshold crossings into one test,
  and (b) treat the per-trade concentration cap Run 20 already specified as load-bearing from day one, not
  optional — an uncapped mechanism that fades a handful of huge, high-conviction spikes could take a small
  number of catastrophic opposite-direction losses, the mirror image of the single-market-dominates-PnL
  failure mode that already sank EXP-003 (57% of nominal PnL from one market) and EXP-005 (125% from one
  category) via the OPPOSITE mechanism (concentration in wins, not losses) two runs in a row.

### (3) Methodology-integrity catch: a WebSearch synthesis this run invented a precisely-quantified example
### that its own cited source does NOT contain — caught before being logged as data, not after
  A `WebSearch` for Polymarket price-spike/reversal research returned a synthesized answer citing a
  specific, superficially very citable example: "the Iran Ceasefire market ($280M volume, April 2026):
  prices spiked from 35% to 68% in eight minutes on a ceasefire rumor... settled at 58% before gradually
  reverting over the following day," attributing it (by proximity/context) to the DL News article in the
  same result set. Per this project's standing "WebFetch-over-summarization" discipline, that DL News URL
  was fetched DIRECTLY (not re-summarized) before logging the example as data — **the article's actual text
  contains no mention of an Iran Ceasefire market, no 35%/68%/8-minute/90-minute/58% figures, and no
  reversal example of any kind.** A follow-up targeted `WebSearch` confirmed a REAL "Iran Ceasefire"
  Polymarket market exists (real event, $170M+ reported volume, a real reported drone-rumor
  spike-then-recovery) but the SPECIFIC numbers from the first search's synthesis could not be corroborated
  against any fetchable primary source (the one candidate primary source, a Bloomberg piece, 403'd —
  paywalled, disclosed not hidden). **Conclusion: the "$280M / 35%→68% / 8min / 90min-window / 58%" figures
  are UNVERIFIED and are explicitly NOT logged as data anywhere in this entry or in GROWTH_STATUS.** This
  extends the project's existing WebFetch-over-summarization rule one level further: it is not just that a
  secondary ARTICLE can over-summarize a primary paper — a search tool's own auto-generated synthesis can
  apparently invent specific, precise-sounding statistics not present in ANY of its own listed sources. A
  suspiciously precise number is not by itself evidence of anything; every specific quantified claim
  intended for RESEARCH_MEMORY must be chased to a direct fetch of its actual cited source before being
  treated as data, no matter how confident or well-formatted the synthesis reads. Filed as a
  process-hardening note for every future run's self-validation step, not a one-off.
- The already-logged "58% of Polymarket's national presidential markets showed negative serial
  correlation" DL News figure (flagged unverified-primary since Run 20) was independently re-fetched this
  run (direct WebFetch of the same DL News URL): the figure is repeated verbatim but the article STILL
  attaches no N, methodology, or citation beyond naming "Joshua Clinton and TzuFeng Huang at Vanderbilt
  University" and "2,500 markets with $2.5 billion in volume" — consistent with, not resolving, Run 20's
  standing "secondary-source-only, unverified against the primary text" flag. The primary OSF preprint
  abstract (`ideas.repec.org/p/osf/socarx/d5yx2_v1.html`, re-fetched directly this run) confirms the
  qualitative direction only ("daily price changes were weakly correlated or negatively autocorrelated")
  and the N/venue/date-range details already logged Run 20 — no percentage figure appears in the abstract
  itself, unchanged from Run 20's finding.

### Candidate alphas NOT proposed this run (reasons)
- No new EXP-00N proposed. EXP-006 remains a scoped-but-not-ready-to-test candidate (the detection +
  labeling pipeline is still unbuilt; the underlying data primitive is now confirmed cheaper to build on
  than previously estimated, not confirmed away as a blocker entirely).
- The "Iran Ceasefire spike/reversal" example is explicitly NOT proposed as supporting evidence for
  anything — see finding (3) above; it is logged as a caught methodology risk, not a data point.

### Recommendation (RECOMMEND-only — no high-confidence validated edge exists; NOT a ROADMAP steer)
  Given (a) the concentration-capped/recency-weighted `CalibrationBucketStrategy` redesign (Run 20 option
  a) can be built and OOS-tested entirely against the THREE corpora already fetched and characterized this
  project (EXP-002/003/005 — no new data-access work, no new pipeline) while (b) EXP-006 still needs a new
  detection+labeling pipeline built and validated on top of the now-confirmed-cheaper-but-still-unbuilt
  intraday primitive, the concentration-capped redesign is the LOWER-cost, HIGHER-certainty next factory
  step; EXP-006 remains the higher-upside but higher-build-cost candidate for a subsequent run once the
  redesign result is in. Both remain open, in that priority order.

### Self-validation (sources this run)
- `polymarket_history_fetcher.py` code read (unmodified, no changes made).
- Live CLOB/Gamma probes: direct `curl` against `clob.polymarket.com/prices-history` (fidelity=1, real
  4-day window, 5,760 ticks, 60s median spacing, independently computed) and
  `gamma-api.polymarket.com/markets` (real Trump-2024 token resolution) — reproducible by anyone with open
  Polymarket egress against this same fully-historical/settled window.
- DL News article (`dlnews.com/articles/markets/polymarket-kalshi-prediction-markets-not-so-reliable...`):
  fetched directly this run, twice (once for the Iran-Ceasefire-example check, once for the 58%-figure
  re-check) — both direct fetches, not re-summarized from the WebSearch snippet.
- `ideas.repec.org/p/osf/socarx/d5yx2_v1.html` (Clinton & Huang OSF preprint abstract): re-fetched directly.
- Bloomberg Iran-bets article: attempted fetch, HTTP 403 (paywalled) — disclosed, not treated as
  corroboration or refutation of anything.
- Egress: direct `curl` from this session against `clob.polymarket.com`, `gamma-api.polymarket.com`,
  `data-api.polymarket.com` — all 200, consistent with every run since 2026-07-04.

**Binding constraint STANDS:** no validated real-money OOS edge. This run's contribution is narrowing
EXP-006's build-cost estimate with a live-verified fact (not just a code read), surfacing a concrete,
honest illustration of why an uncapped fade-the-spike mechanism is dangerous on the largest events, catching
a specific search-synthesis fabrication before it could contaminate RESEARCH_MEMORY as data, and giving the
next run/factory cycle a clear, evidence-based priority order between the two open non-bucket-family
candidates (concentration-capped redesign first, EXP-006 second).

---

## 2026-07-14 — Research Run 22: tested Run 21's own recommended next step (concentration-capped /
favorite-band-restricted bucket redesign) against the real EXP-003 Politics corpus — NEITHER mitigation
produces a validated edge; a per-trade notional cap is a NO-OP (0 trades capped at any tested threshold,
because concentration comes from many small correlated trades, not one oversized bet); new academic
corroboration (Whelan, N=300k+ Kalshi contracts, directly verified) for the favorite-longshot-bias
mechanism behind the family's persistent low hit rates

- Hypothesis (falsifiable): Research Run 21 (2026-07-13) recommended, as the lower-cost next step (no
  new data-access work, testable on the existing EXP-003 corpus), that the factory build a
  "concentration-capped/recency-weighted `CalibrationBucketStrategy` redesign." This run tests the
  TWO concrete, cheaply-testable variants of that idea directly against the already-fetched real
  Politics corpus, using ONLY the existing, already-shipped `make_calibration_bucket_strategy(edges=...)`
  parameter (no new strategy code) plus a post-hoc analysis of the already-existing `BacktestTrade`
  fields (no new strategy code): (a) restrict the bucket model's price RANGE to exclude longshots
  (motivated by favorite-longshot-bias literature — see below); (b) cap each trade's `budget_usd`
  post-hoc at a fraction of total deployed capital, to see whether the F10 single-market/leave-one-out
  concentration is caused by a few oversized bets that a notional cap would blunt.
- Min sample N: reuses EXP-003's own pre-registered floor context (100 min / ~300-400 for reliable
  bucket coverage); the favorites-only variant fell short of F11's own `min_trades=30` significance
  floor (N=18), reported honestly as `insufficient_data`, not a refutation. The drop-extremes variant
  (N=135) and the concentration-cap variants (N=472, unchanged) both cleared the floor.
- OOS result: **TESTED — neither mitigation rescues the mechanism into a validated edge.** Method: one
  pre-registered re-fetch of the identical Run 20/21 corpus definition (`tag_id=2` Politics,
  `decision_lead_days=7`, `seed=42`, `max_pages=20`, `limit=100`, unmodified fetcher/backtest/regime-
  slice/significance code) — 1,369 leakage-safe records, byte-identical in count to Run 20's pull two
  days earlier (a useful determinism/stability check: the resolved-Politics-tag universe at this decision
  lead has not meaningfully drifted in 48h). Three strategy-fitting variants + a post-hoc sizing variant,
  all run through the SAME unmodified `walk_forward_backtest` + `analyze_regime_slices` (F10) +
  `bootstrap_oos_significance` (F11) pipeline `validate_real_oos.py` already uses:
  1. **BASELINE (all 10 default buckets)** — exactly reproduces Run 20: 472 trades, net **+$28,815.49**,
     F10 fragile (single-market 57%, single-category 134%, leave-one-out flips to -$9,665.99), F11
     `indistinguishable_from_zero` (hit rate 25.64%). Confirms determinism before testing variants.
  2. **FAVORITES-ONLY** (`edges=(0.5,0.6,0.7,0.8,0.9,1.0)`, i.e. the model is fit + trades ONLY inside the
     favorite half of the price range, matching EXP-002's ORIGINAL 2026-06-29 hypothesis band):
     **18 trades, net -$841.11** (negative). Hit rate 83.3% (15/18) — high, as expected once longshot
     convexity is removed — but the wins are individually small (favorites near 0.5-1.0 pay a small
     spread even when right) while enough losses land large enough to net negative. F10 correctly reports
     "no positive edge to assess" (an honest degenerate case, not a fabricated non-fragile pass). F11:
     `insufficient_data` (N=18 < the 30-trade significance floor) — **this is NOT a refutation, it is
     "no edge, and too little data to say more."** Directionally, restricting to favorites does NOT
     recover a positive result either — the mechanism finds no exploitable edge at ANY price level on
     this corpus, not just in the longshot buckets.
  3. **DROP-EXTREMES** (`edges=(0.1,...,0.9)`, i.e. exclude only price<0.10 and price>0.90, keep the
     broad middle including moderate longshots): **135 trades, net +$13,584.50** — smaller than baseline
     but still positive nominally. Still **F10 fragile** (horizon: 100% from '3-7d'; confidence: 151% from
     the '10-25%' bucket — note this is `regime_slice`'s OWN fixed confidence-bucketing, independent of
     the fitting edges, and it still concentrates in a low-but-not-extreme band) and still **F11
     `indistinguishable_from_zero`** (CI [-8112.25, 38869.24], hit rate 24.44% — statistically
     indistinguishable from the baseline's 25.64%). **Conclusion: excluding only the most extreme deciles
     does NOT fix the failure mode — it persists broadly across the sub-0.5 price range, not just in the
     <10%/>90% tails.**
  4. **Per-trade notional concentration cap** (post-hoc: cap each `BacktestTrade.budget_usd` at 10%/5%/2%
     of the $186,813.83 total capital deployed across baseline's 472 trades, scale `pnl_usd`/`payout_usd`
     proportionally — CAVEAT disclosed: this linear scaling ignores that a smaller real order would ALSO
     pay less market-impact cost, so it likely UNDERSTATES any real benefit of capping, a conservative
     approximation, not a re-run of the actual sizing engine): **at EVERY tested threshold, 0 of 472
     trades exceeded the cap** — the largest single trade's `budget_usd` is already well under 2% of
     total deployed capital (~$395.79 mean trade size vs. a $3,736.28 2%-cap floor). **A per-trade
     notional cap is a complete NO-OP on this corpus.** This is the headline negative finding of this
     run: the single-market-57%/category-134% concentration Run 20/21 flagged is NOT caused by one or a
     few oversized individual bets — it is caused by MANY separate, modestly-sized trades that are all
     effectively betting on the SAME underlying correlated event/entity cluster (e.g. multiple
     candidate-outcome markets within one election, or repeated same-topic contracts). **A per-trade cap
     cannot fix cross-trade correlation; only a per-cluster/per-entity or per-category EXPOSURE cap
     (limiting total capital across all trades that share an underlying correlated driver) could address
     it** — a materially harder design problem than "cap the position size," and NOT the same lever Run 21
     characterized as the "lower-cost, higher-certainty next step." This raises, not lowers, the cost
     estimate for that recommended redesign.
- Calibration (Brier / reliability): crowd_brier=0.0886 on this corpus (identical to Run 20 — same
  corpus). No separate alpha calibration re-run; F10/F11 are the load-bearing gates, unchanged
  methodology from every prior EXP-002/003/005 run.
- Costs modeled: yes, unmodified `cost_model.py` via `walk_forward` for variants 1-3 (already net of
  fees+slippage); variant 4's linear pnl-scaling is a post-hoc approximation on top of already-cost-net
  per-trade PnL (see caveat above — conservative, not a re-run of sizing).
- Verdict: **tested — neither candidate mitigation produces a validated edge; a new, more precise
  redesign requirement surfaces (cross-trade correlation exposure cap, not a per-trade notional cap).**
- Why / new external research this run (verified, not just WebSearch-synthesized): searched for recent
  favorite-longshot-bias literature to understand WHY the bucket-calibration family keeps finding
  "edge" concentrated in low-price buckets with a hit rate far below 50%. Found and **directly verified**
  (via `WebFetch` of `ideas.repec.org/p/pra/mprapa/126350.html`, the primary abstract page — reachable,
  unlike SSRN which 403'd again this run, consistent with every prior run) Karl Whelan's "Makers and
  Takers: The Economics of the Kalshi Prediction Market" (2026 working paper, **N > 300,000 real Kalshi
  contracts**, transaction-level data): **"low-price contracts win far less often than required to break
  even, while high-price contracts win more often and yield small positive returns"** — a clean, primary-
  verified statement of classical favorite-longshot bias (crowd systematically OVERPRICES longshots,
  slightly UNDERPRICES favorites). This is Kalshi-only (the abstract explicitly contains no Polymarket
  discussion, confirmed via a second direct fetch) — **NOT verified as transferring to Polymarket**, and
  a WebSearch-synthesized claim that "on Polymarket specifically, low-probability outcomes are overpriced"
  could NOT be traced to any specific primary source this run (treated as unverified synthesis, per this
  project's standing WebFetch-over-summarization discipline — the exact failure mode Run 21 caught and
  named a process risk). **If this mechanism DOES transfer to Polymarket even partially, it plausibly
  EXPLAINS (not proves) the bucket-calibration family's specific failure shape across all 3 real-corpus
  tests to date:** a static empirical-rate model fit on a longshot price bucket is measuring a FEW
  in-sample YES resolutions against a crowd price that (per Whelan) is already the RIGHT side of a real,
  replicated structural bias (longshots overpriced/less likely to pay than their price implies) — so an
  apparent "the fitted rate exceeds the crowd price" signal in that bucket is more likely in-sample noise
  reverting OOS than a real inefficiency, consistent with the observed sub-50% (often far-sub-50%) hit
  rates. This is offered as a plausible CAUSAL MECHANISM for an already-observed empirical pattern, not
  new proof of anything — the favorites-only test above (finding 2) shows that simply flipping to the
  favorite side does NOT recover a positive/significant result either (at least not at N=18), so if a
  favorite-side edge exists on Polymarket specifically, this project has not yet found it.
- How this run's findings could be wrong (adversarial pre-mortem on THIS run's own conclusions):
  1. The favorites-only N=18 result is far too small to conclude "no edge in favorites" — it is
     `insufficient_data`, not a refutation; a materially larger favorites-only corpus (a dedicated
     favorite-band fetch across more categories/time, not just Politics) could still show a real,
     significant, Whelan-consistent edge that this small sample simply can't detect.
  2. The linear pnl-scaling approximation in the concentration-cap test could be wrong in either
     direction: it ignores reduced market-impact cost at smaller size (biases toward UNDERSTATING the cap's
     benefit) but also ignores that Kelly's own optimal-size logic would have picked DIFFERENT trades
     entirely under a binding cap from decision time forward (a true re-run with the cap wired INTO the
     sizing engine, not applied post-hoc, could behave differently in either direction) — this is a
     sensitivity analysis, not a faithful re-simulation.
  3. This run only tested the Politics corpus (reusing Run 20's exact pull for a clean apples-to-apples
     comparison); the "many small correlated trades, not one big bet" finding about WHY a per-trade cap is
     a no-op has not been confirmed on the Sports (EXP-005) or all-category (EXP-002) corpora — it could be
     Politics-specific (e.g. many correlated same-election candidate markets), not a general property of
     the mechanism.
  4. Whelan's paper is Kalshi-only; treating it as an explanatory mechanism for a Polymarket-only empirical
     result (this project trades no real Kalshi corpus yet) is an analogy, not a same-venue confirmation —
     flagged explicitly, not silently assumed.
- Self-validation (sources this run):
  - Corpus + backtest results: one live-fetched, pre-registered run this session (unmodified repo code —
    `polymarket_history_fetcher.py`, `walk_forward.py`, `calibration_bucket_strategy.py`,
    `regime_slice.py`, `bootstrap_oos_significance.py` — same modules `validate_real_oos.py` imports, just
    invoked directly + parameterized via the EXISTING `edges=` keyword, no new strategy code written or
    committed); raw HistoricalMarket corpus cached to a research-agent scratch path (not committed) for
    reproducibility within this session. Output not committed as raw data (per this project's established
    pattern — RESEARCH_MEMORY entries summarize, not embed, raw research-agent script output).
  - Whelan paper: `WebFetch` of `ideas.repec.org/p/pra/mprapa/126350.html` (primary abstract page),
    fetched twice (once for the core claim, once to confirm the absence of a Polymarket discussion and
    check for a quantitative magnitude/cost-survival claim — neither present in the abstract; the full PDF
    at `mpra.ub.uni-muenchen.de` was not fetched this run). SSRN (the Krause CPI-market favorite-longshot
    paper found earlier in this same search sweep) remains 403-blocked, consistent with every prior run —
    not used as a source, logged only as an unverifiable lead.
  - Egress: direct `curl`/fetch from this session against gamma-api/clob/data-api.polymarket.com (all 200,
    consistent with every run since 2026-07-04); dune.com not re-tested this run (no new lead needed it).
- Verdict: **edge-not-proven** (mitigation-testing + research; RECOMMEND-only, no ROADMAP steer — no
  high-confidence validated edge exists to justify one).

### Recommendation (RECOMMEND-only — not a ROADMAP steer)
  The two concrete, cheap variants of Run 21's "concentration-capped/recency-weighted redesign"
  suggestion have now been tested and neither rescues the mechanism: a price-range restriction either
  kills the PnL (favorites-only) or fails to fix the significance/fragility gates (drop-extremes), and a
  PER-TRADE notional cap is a structural no-op because the concentration is cross-trade/correlated, not
  single-bet. The highest-value next step for this family, if pursued further, is narrower and harder
  than "cap the trade size": a per-CLUSTER (correlated-entity/event-group) exposure cap, which needs a
  way to detect that multiple traded markets share an underlying driver (e.g. same election, same
  underlying asset) — a genuine factory-build item, not a parameter tweak, and NOT yet recommended here
  as ready-to-build (no falsifiable spec, no min-N, no OOS plan drafted this run). Absent that, the two
  open non-bucket-family candidates from Run 20/21 remain the better use of future OOS-testing effort:
  EXP-006 (political price-reversal, now cheaper to build per Run 21's finding) and the still-untested B8
  cross-venue coherence direction (matcher + backtest built #179, never run against a real dual-venue
  corpus). Binding constraint STANDS: no validated real-money OOS edge exists on any tested mechanism to
  date.

---

## 2026-07-15 — Research Run 23: first real, self-verified PILOT of EXP-006 (political price-reversal) —
N=16 diverse markets, mean hourly lag-1 price-change autocorrelation -0.102, 95% bootstrap CI excludes
zero (PRELIMINARY, not a validated edge — N far below the 100-event floor); discovered a hard ~15-day
max-interval cap on CLOB `/prices-history` (revises Run 21's build-cost estimate upward); EXP-006 formally
proposed in GROWTH_STATUS experiments[]; external web sweep found only redundant SEO-grade sources

- Hypothesis (falsifiable): this run tests, for the first time on this project's own data (not just cited
  literature), the core statistic behind EXP-006 (Research Run 20, 2026-07-12; refined Run 21,
  2026-07-13): do Polymarket political-market YES prices show NEGATIVE lag-1 serial correlation in
  short-window price CHANGES in the run-up to resolution (Clinton & Huang, Vanderbilt/OSF preprint,
  N>2,500 political markets/$2B+ volume, final 5 weeks of the 2024 US election: "daily price changes were
  weakly correlated or negatively autocorrelated")? This is explicitly a PILOT of the underlying
  PHENOMENON, not a formal EXP-006 test (no strategy code, no cost model, no F10/F11 gate) and not a
  refutation/confirmation of Clinton & Huang's own much larger result.
- Min sample N: EXP-006's own pre-registered floor (min_sample_n, now written into GROWTH_STATUS
  experiments[]) is 100 qualifying spike/move events across >=3 distinct election cycles/news events, for
  a REAL strategy backtest. This pilot's N=16 is explicitly, honestly far below that floor — reported as
  a preliminary signal, not a test result.
- OOS result: **PILOT TESTED (not insufficient-data, not a validated edge) — a real, reproducible,
  PRELIMINARY corroboration.** Method (pre-registered before any data was fetched, written to a scratch
  file first): universe = Polymarket resolved Politics markets (`tag_id=2`, `order=volumeNum`, `limit=100,
  max_pages=1`, the SAME axis already characterized for EXP-003 in Runs 20/22, reused to avoid a new
  selection-bias surface); inclusion = market life >= 14 days when `start_date` is known; sample = first 40
  qualifying markets in list order (not cherry-picked); window = the LAST 14 DAYS before `resolution_time`
  (mirrors Clinton & Huang's own "final weeks" focus, and is the largest window that fits ONE CLOB call —
  see the infra finding below); series = hourly-fidelity (`fidelity=60`) YES-token CLOB price history over
  that window; trim = drop the final 24h before resolution (settlement noise) and any hourly point outside
  `[0.03, 0.97]` (avoid a near-certain tail trivially dominating the correlation); statistic = per-market
  Pearson correlation of hourly `delta_t` vs `delta_{t-1}` (lag-1 autocorrelation of price CHANGES — the
  exact quantity Clinton & Huang's finding is about); aggregation = equal-weight mean across markets (no
  single long-lived market dominates) + a market-level bootstrap 95% CI (resample markets with
  replacement, 2000 draws, `seed=42`). Unmodified `PolymarketHistoryFetcher` (`fetch_resolved_markets` +
  `fetch_price_history`), a research-agent scratch script (not committed), run ONCE, not retried after
  seeing the number. **Result: 16 of 40 candidates survived** (24 dropped: 2 `HTTP 500` server errors on
  `/prices-history`, the rest below the `>=24`-hourly-point floor after trimming — honest attrition, not
  cherry-picked, though it is itself a liquidity/recency-selection caveat, since sparser-history markets
  were silently excluded — see pre-mortem). **Mean per-market lag-1 autocorrelation = -0.102**, 95%
  bootstrap CI **[-0.1515, -0.0467]** — excludes zero. **14 of 16 markets individually negative** (87.5%).
  The 16-market sample spans **11 distinct events/topics**, not a single election cycle: 2024
  Trump/Harris/Pennsylvania-popular-vote, two separate US-Iran peace-deal contracts, the 2025 NYC mayoral
  race (Mamdani), Khamenei-out-as-Supreme-Leader, a US government-shutdown market, two Fed-rate-decision
  contracts, Netanyahu-out, a Trump-Epstein-files market, two South-Korea presidential-election contracts,
  and a Russia-Ukraine ceasefire market — directly addressing the "single-event-dominated sample" pre-
  mortem concern both Research Run 20 (proposing EXP-006) and Run 21 (scoping it) flagged as a live risk.
- **A second, independent, more durable finding this run (infra, not alpha): CLOB `/prices-history`
  enforces a hard ~15-DAY MAX INTERVAL per call, independent of fidelity.** Live-verified via direct
  binary search against the same real Trump-2024 YES token Research Run 21 used: at `fidelity=1440`
  (daily bars), a 12-day window returns `HTTP 200`, a 16-day window returns `HTTP 400`
  (`"invalid filters: 'startTs' and 'endTs' interval is too long"`); at `fidelity=60` (hourly bars), 15
  days succeeds, 16 days fails with the identical error; a 20-day window fails at EVERY fidelity tested
  (1, 5, 15, 30, 60, 180, 360, 720, 1440). **This REVISES Research Run 21's "the intraday primitive
  already exists, cheap to build on" cost estimate upward:** Run 21's live verification only exercised a
  SINGLE 4-day call (5,760 one-minute ticks) and did not test a longer window, so it did not discover this
  cap. A general-purpose spike detector that needs a market's FULL lifetime series (not just its final
  14 days) will need CHUNKED/paginated fetching — multiple `<=15`-day calls per market, stitched together
  — a real, previously-uncosted piece of build scope. This pilot sidestepped the cap entirely by
  pre-registering a single last-14-days window per market (one call, no chunking), which is why it could
  run this session without new fetcher code.
- Calibration (Brier / reliability): n/a — this pilot measures raw price-CHANGE serial correlation, not a
  probability-calibration statistic; no model probabilities are involved.
- Costs modeled: **none** — this is explicitly a PHENOMENON probe (does the raw price series show negative
  serial correlation), not a tradeable-strategy backtest. The already-logged QuantPedia "mean-reversion on
  Polymarket" cautionary example (Research Run 20, 2026-07-12: best zero-spread variant flips from +7.95%
  CAR to -7.83% CAR at a realistic 10bps cost) is a direct, already-verified reminder that a negative raw
  autocorrelation does NOT by itself imply a profitable trade after fees/slippage/spread.
- **A methodologically important caveat this run's own statistic does NOT resolve: it is computed WITH
  HINDSIGHT over the whole 14-day window** (the same way an academic paper would characterize a
  phenomenon), **not a causal/leakage-safe live decision rule** the way `walk_forward` requires for an
  actual backtest. Building the real EXP-006 strategy still requires a rolling/causal spike-detection rule
  (decide to fade a move using only information available AT that moment, not the whole window in
  hindsight) integrated into `walk_forward` — this pilot is evidence the PHENOMENON is worth that build
  effort, not a substitute for building it.
- Verdict: **proposed** (EXP-006 formally added to `GROWTH_STATUS` `experiments[]` this run, status
  `proposed`, NOT `tested` — the pilot is preliminary supporting evidence for building it, not itself a
  pass/fail test of a strategy). Full falsifiable spec (hypothesis, `min_sample_n=100` across `>=3`
  distinct cycles, OOS plan, cost assumptions including Research Run 22's per-CLUSTER exposure-cap
  requirement, and a 6-item adversarial pre-mortem) is now in `GROWTH_STATUS` rather than only sketched in
  `RESEARCH_MEMORY` as in Runs 20/21.
- Why / adversarial pre-mortem on THIS run's own pilot (not a repeat of Run 20's pre-mortem on the
  underlying idea, which stands unchanged):
  1. The 16-market survivor set is itself liquidity/recency-selected — markets with sparse hourly history
     in their specific last-14-days window were silently dropped (not fabricated), which could bias the
     surviving sample toward more actively-traded markets with different reversal dynamics than the
     broader universe.
  2. N=16 is an order of magnitude below the 100-event floor a real test needs; a materially larger,
     differently-sampled pilot (more categories, more time windows, `order=volume24hr` per Run 18's
     lever) could show a smaller, larger, or even sign-reversed mean correlation.
  3. This pilot only tested Politics-tag markets in a SINGLE 14-day pre-resolution window per market — it
     says nothing about whether the effect holds earlier in a market's life, in other categories, or over
     different window lengths (7 days? 30 days, chunked?).
  4. The July 2024 assassination-attempt spike (N=1, Research Run 21, 2026-07-13) did NOT reverse — it
     persisted/compounded (0.595→0.685→0.705 over +24h/+48h) — a live illustration that the LARGEST,
     most information-laden spikes may behave oppositely from the many smaller moves likely dominating
     this run's aggregate statistic; a real detector needs to stratify by move size/salience, not pool
     everything into one test.
  5. A per-CLUSTER exposure cap (the mitigation Research Run 22 found a working bucket-family redesign
     needs, since a per-TRADE cap was proven a structural no-op against cross-trade correlation) has NO
     existing implementation in this repo — it is new, unbuilt risk-engine scope for EXP-006 too, not a
     parameter a probe can just pass in.
  6. The negative correlation could reflect microstructure/bid-ask bounce (a known artifact in any
     transaction-price series, distinct from genuine information-driven overreaction) rather than a real
     behavioral reversal effect — this pilot cannot distinguish the two; only a cost-net backtest can show
     whether the effect survives realistic spread/slippage.
- External research this run (WebSearch sweep, DATA only): searched for prediction-market calibration
  edge research, Polymarket/Kalshi arbitrage research, and favorite-longshot-bias/correlated-exposure-cap
  literature dated around this run. Results were overwhelmingly non-academic SEO/marketing content
  (`tech-insider.org`, `predictionmarketsworld.com`, `laikalabs.ai`, `ahasignals.com`, and similar
  "2026 guide" blog pages) restating, without new N/methodology/magnitude, findings this project has
  ALREADY independently verified against primary sources in prior runs: favorite-longshot bias
  (2-12% actual win rate vs 5-20% implied price on low-price contracts — consistent with, not additive to,
  the directly-fetched Whelan N>300k Kalshi finding logged 2026-07-14); cross-venue arb window compression
  (~30s in 2026 vs ~5min in 2024 — consistent with, not additive to, the already-logged bot-speed-
  dominance conclusion); a cited "IMDEA Networks $40M arbitrage 2024-2025, 86M bets" figure that matches
  a source already logged in this project's memory (2026-06-30/07-10 entries). **No new primary source,
  no new N, no new magnitude — logged as DATA confirming no course correction is needed, not as new
  evidence for anything.** Per this project's standing WebFetch-over-summarization discipline, none of
  these secondary/SEO sources were treated as citable primary evidence.
- Self-validation (sources this run):
  - EXP-006 pilot: one live-fetched, pre-registered scratch-script run this session (unmodified
    `PolymarketHistoryFetcher.fetch_resolved_markets`/`fetch_price_history`, `seed=42`, run once, not
    retried), raw JSON output saved to a research-agent scratch path (not committed) — independently
    re-derivable by anyone with open Polymarket egress (subject to the live corpus/price-history drifting
    as time passes; the specific 16-market survivor set is NOT guaranteed to reproduce byte-for-byte on a
    re-run the way a fully-historical/settled fixture would, since some sampled markets are still open —
    e.g. the Iran peace-deal and Fed-rate contracts have future resolution dates as of this run).
  - CLOB 15-day interval cap: live binary search this session (direct `curl` against
    `clob.polymarket.com/prices-history`, varying `startTs`/`endTs`/`fidelity` against the same real
    Trump-2024 YES token Research Run 21 used) — fully reproducible by anyone with open Polymarket egress
    against this historical, settled token.
  - Egress: direct `curl` from this session — `gamma-api.polymarket.com` 301 (routine http→https
    redirect, not a block), `clob.polymarket.com` 200, `data-api.polymarket.com` 200, `huggingface.co`
    200, `dune.com` still 403, `api.elections.kalshi.com` root 404 (expected — root path only, not the
    real API path; consistent with every prior run's finding).
  - WebSearch sweep sources: all secondary/SEO-grade, explicitly NOT treated as primary evidence — see
    above.

**Binding constraint STANDS:** no validated real-money OOS edge. This run's contribution is the FIRST
real, self-verified (not just cited) preliminary corroboration of EXP-006's core statistical premise on
this project's own data (N=16, CI excludes 0), a genuine infra finding that raises the honest build-cost
estimate for a general-purpose version of it (the 15-day CLOB interval cap), a formally specified EXP-006
entry in `GROWTH_STATUS` `experiments[]` (hypothesis / min-N / OOS plan / costs / pre-mortem, status
`proposed`), and confirmation that this run's external web sweep surfaced no new primary evidence beyond
what prior runs already verified. RECOMMEND-only — no ROADMAP steer (no high-confidence validated edge
exists to justify one).
---

## 2026-07-15 — Factory build (NOT a research run): the EXP-006 spike-detection + reversal-labeling primitive is now BUILT (unblocks the test; NO edge claimed)
- Hypothesis (falsifiable): n/a — this is a FACTORY capability build, not an alpha test. It builds the exact two missing pieces Run 21 named, so a future research run can actually test EXP-006 on a real corpus. It claims NO edge and reaches NO revenue field.
- Min sample N: n/a (no OOS run this event).
- OOS result (or "insufficient data"): n/a — nothing was backtested; a detector + labeler is not an edge.
- Calibration (Brier / reliability): n/a.
- Costs modeled: n/a (no trades simulated).
- Verdict: **edge-not-proven** (infrastructure build; the binding constraint STANDS).
- Why / what shipped:
  - Run 20 named EXP-006's blocker as "(a) a spike-DETECTION function over an already-fetchable
    tick series (threshold-Δ crossing within a window) and (b) a reversal-labeling harness"; Run 21
    confirmed the raw tick primitive already exists (`PolymarketHistoryFetcher.fetch_price_history`
    returns the full `[{"t","p"}]` series at 1-min fidelity, live-verified). This event builds (a)+(b)
    as a pure, deterministic, stdlib-only module: `backend/app/prediction_markets/spike_detection.py`
    (`detect_spikes` + `label_reversal`/`label_reversals` + `clean_ticks`; frozen `SpikeEvent` /
    `ReversalOutcome`), with 25 fixture tests registered in the blocking gate
    (`backend/tests/test_spike_detection.py`, `preflight.sh`).
  - LEAKAGE-SAFE BY CONSTRUCTION (the load-bearing property): detection is causal — a spike is
    CONFIRMED at the FIRST tick whose trailing-window move crosses the threshold, so `confirm_time` is
    the only causally-knowable decision instant; reversal labeling reads ONLY strictly-later ticks and
    returns `None` (never fabricates) when the forward horizon has no qualifying tick. A sustained ramp
    is ONE event (peak-extension), a genuine reverse is a SEPARATE event.
  - Deliberately NOT built this event (honest scope): the strategy wrapper, the walk-forward closure,
    the per-cluster concentration cap Run 20/21 flagged as load-bearing, and the actual OOS test on a
    real Politics corpus. Those belong to a RESEARCH run (maker≠checker: the factory builds the
    capability; the research routine runs the test + F10/F11 gates and decides edge/no-edge). Building
    the detector does NOT move `business_case_strength`.
  - Adversarial review (2 Sonnet + independent checks): no edge implied, no look-ahead, imported by
    nothing but its test, no creds/network/nondeterminism; 25/25 tests non-tautological (the causal +
    strictly-later-tick assertions FAIL if the guards are removed).
- Self-validation: the primitive is a pure offline library (no credential, no I/O, no trading-path
  wiring), validated entirely by in-gate deterministic unit tests — so it adds NO SELF_VALIDATION
  capability and NO new credential (`check_self_validation.py --readiness` stays green, unmet=[]).
- What EXP-006 still needs before a real test: a spike→reversal walk-forward harness on a real
  intraday Politics corpus (fetchable via the existing `fetch_price_history`), the per-cluster
  concentration cap, and spike-size/salience stratification (Run 21's N=1 caution: the LARGEST
  spikes may persist, not fade). Logged so a future research run picks this up ready-to-wire, not
  ready-to-claim.

---

## 2026-07-16 — Research Run 24: grew Run 23's EXP-006 pilot 4x (N=16 -> N=67) via the SAME
pre-registered method + a wider candidate pool; the negative lag-1 autocorrelation held (mean
-0.1198, 95% CI [-0.1508,-0.0886], 80.6% of markets individually negative) and — the key new
test — SURVIVED a per-CLUSTER robustness check (22 distinct event-clusters, cluster-level mean
-0.0953, 95% CI [-0.1455,-0.0495], excludes zero) that directly answers Run 20-22's standing
"single-event/cluster concentration" pre-mortem; STILL below the pre-registered 100-event floor,
STILL a raw hindsight price-behavior statistic, NOT a cost-net tradeable backtest — RECOMMEND-only,
no ROADMAP steer; external web sweep found no new primary source since Run 23

- Hypothesis (falsifiable): this run tests whether Research Run 23's preliminary N=16 pilot result
  (Polymarket political-market hourly YES-price changes show negative lag-1 serial correlation in
  the last 14 days before resolution) holds, strengthens, weakens, or reverses when the SAME
  pre-registered method is applied to a materially larger, differently-composed candidate pool —
  and, new this run, whether the effect survives when re-aggregated at the CLUSTER level (one value
  per correlated event-group) rather than the per-market level, since Research Run 22 already
  proved a per-TRADE exposure cap is a no-op against cross-trade/cross-market correlation and named
  cluster-level concentration as the load-bearing open risk for any future EXP-006 build.
- Min sample N: EXP-006's own pre-registered floor (`min_sample_n=100` across `>=3` distinct
  cycles, GROWTH_STATUS `experiments[]`) is unchanged and NOT yet met — this run's N=67 raw
  survivors is a real, honest step toward it (4.2x Run 23's N=16), not a claim of having reached it.
- OOS result: **PILOT EXTENDED (not insufficient-data, not a validated edge, not yet at the floor)
  — a materially stronger preliminary corroboration than Run 23, now cluster-robustness-checked.**
  Method (pre-registered BEFORE fetching — written to a scratch file first, unmodified repo code,
  no changes): SAME universe as Run 23 (Polymarket resolved Politics, `tag_id=2`, `order=volumeNum`,
  unmodified `PolymarketHistoryFetcher.fetch_resolved_markets`/`fetch_price_history`), but the
  candidate pool widened from Run 23's "first 40 in list order" to "first 200"
  (`limit=100, max_pages=2`) — the SAME fetcher call shape, just a larger pre-registered slice, no
  code change. Same inclusion (market life >= 14 days when `start_date` known), same window (last
  14 days before `resolution_time`, one CLOB call, under the Run-23-discovered ~15-day interval
  cap), same trims (drop final 24h before resolution; drop hourly points outside [0.03, 0.97]),
  same statistic (per-market Pearson lag-1 autocorrelation of hourly price CHANGES), same survivor
  floor (`>=24` hourly points post-trim), same aggregation (equal-weight mean + market-level
  bootstrap 95% CI, 2000 resamples, `seed=42`). Run ONCE, not retried after seeing the number.
  **Result: 186 candidates had a known `start_date` + life>=14d; 67 survived the fetch+point-floor
  (119 dropped: 36 HTTP/empty-history failures, 83 below the 24-point floor after trim — honest
  attrition, itself a liquidity-selection caveat, same class Run 23 already flagged). Mean per-market
  lag-1 autocorrelation = -0.1198** (vs Run 23's -0.102 on N=16 — the SIGN held and the MAGNITUDE
  was, if anything, slightly larger, not attenuated by the larger sample), **95% bootstrap CI
  [-0.1508, -0.0886]** (excludes zero, and is materially TIGHTER than Run 23's
  [-0.1515,-0.0467] — expected from 4x the N), **54 of 67 markets individually negative (80.6%,**
  close to Run 23's 87.5%).
- **The new, more decisive test this run (not run in Run 23): a per-CLUSTER robustness check,
  directly answering the standing Run 20/21/22 "single-event/cluster concentration" pre-mortem.**
  The 67 survivors were manually grouped into 22 distinct event-clusters by topic (e.g. all "Fed
  rate decision" contracts across different meeting dates = one cluster; all "US x Iran
  peace-deal/ceasefire" contracts = one cluster; all 2024-election popular-vote/state-margin/
  closest-state contracts = one cluster; every genuinely single-event market is its own
  singleton cluster) — a real, honest concern, since the survivor set turned out to be
  Fed-rate-heavy (18/67, 27%) and Iran-heavy (12/67, 18%), exactly the kind of correlated cluster
  that could make a per-market mean look more significant than it truly is if one cluster's
  internal correlation dominates. Computing ONE value per cluster (the within-cluster mean) and
  then re-aggregating equal-weight ACROSS THE 22 CLUSTERS (not the 67 markets): **cluster-level
  mean = -0.0953**, **95% bootstrap CI (resampling CLUSTERS, not markets, `seed=42`, 2000 draws)
  = [-0.1455, -0.0495]** — still excludes zero — **18 of 22 clusters individually negative
  (81.8%).** So the effect is NOT an artifact of the Fed/Iran clusters dominating a per-market
  count; it survives being collapsed to one vote per correlated event-group. This is exactly the
  kind of check Run 22 said any EXP-006 (or bucket-family) redesign needs before trusting a
  per-market aggregate, applied here for the first time to this pilot's own data.
- Calibration (Brier / reliability): n/a — unchanged from Run 23, this measures raw price-CHANGE
  serial correlation, not a probability-calibration statistic.
- Costs modeled: **none** — still explicitly a PHENOMENON probe, not a tradeable-strategy backtest.
  The already-logged QuantPedia mean-reversion cautionary example (best zero-spread variant flips
  from positive to negative at a realistic 10bps cost) remains the standing reminder that a negative
  raw autocorrelation does not by itself imply a profitable fade after realistic spread/slippage —
  re-confirmed present in a fresh WebSearch/WebFetch this run (see below), unchanged.
- Verdict: **proposed (unchanged status in `experiments[]`) — pilot_probe field updated with the
  extended N=67 result + the new cluster-robustness check.** Still NOT `tested` — no strategy code,
  no cost model, no F10/F11 gate, and N=67 is still below the pre-registered `min_sample_n=100`
  floor. This run raises confidence in the underlying PHENOMENON (now survived a 4x larger, more
  diverse sample AND a cluster-concentration check it had never been run against) without claiming
  it has cleared the bar for a real backtest.
- Why / adversarial pre-mortem on THIS run's own extension (not a repeat of Run 20-23's pre-mortem
  on the underlying idea, which stands unchanged and still applies in full):
  1. The cluster taxonomy above is a post-hoc, manual topic grouping (keyword-based: "fed" / "iran" /
     election-margin phrases / etc.), not a principled or previously-validated classifier — a
     different, equally reasonable clustering (e.g. splitting "Iran ceasefire" from "Iran peace
     deal" from "Iran military action" as 3 clusters instead of 1) could shift the cluster-level
     CI's exact bounds, though the DIRECTION (negative, CI excluding 0) is unlikely to flip given
     18/22 clusters independently negative.
  2. N=67 (or 22 clusters) remains well below the 100-event/`>=3`-distinct-cycles floor a real
     EXP-006 test needs; this is a stronger preliminary signal, not a passed test.
  3. The 119 candidates dropped (36 HTTP/empty-history, 83 below the point floor) are, as in Run 23,
     a liquidity/recency-selection filter, not a random sample — the true population effect (across
     ALL Politics markets, including the ones too illiquid to fetch a usable series) is unmeasured
     and could differ.
  4. This run only widened the SAME `tag_id=2`/`order=volumeNum`/last-14-days/hourly configuration
     Run 23 used — it did not test a different category, a different window length, or a different
     point in a market's life; a materially different sampling axis (e.g. `order=volume24hr`, or a
     30-day window chunked across two CLOB calls) could still show a different magnitude or even
     sign, unverified until tried.
  5. All of Run 20-23's standing cautions still apply unchanged and are NOT re-litigated as resolved
     by this run: the July 2024 assassination-attempt spike (N=1) did NOT reverse; the raw
     autocorrelation is a hindsight statistic, not a causal/leakage-safe live decision rule; a
     per-cluster EXPOSURE cap (as opposed to this run's post-hoc per-cluster STATISTICAL
     robustness check) has no existing implementation in this repo — this run tests whether the
     PHENOMENON survives clustering, it does not build the risk-engine primitive that would let a
     real strategy trade it safely.
- External research this run (WebSearch + targeted WebFetch, DATA only, per the WebFetch-over-
  summarization discipline standing since Run 21): searched for Polymarket price-reversal/
  serial-correlation research and prediction-market calibration-edge research dated around this
  run. All results were sources ALREADY logged in this project's memory (Clinton & Huang OSF
  preprint; the QuantPedia Polymarket mean-reversion backtest, re-confirmed via search snippet to
  still report degraded/negative performance under realistic execution costs; Le 2026 arxiv
  2602.19520; Prediction Arena arxiv 2604.07355) — no new primary source, no new N, no new
  magnitude. One previously-unlogged QuantPedia page ("Systematic Edges in Prediction Markets") was
  directly WebFetched (not summarized from the search snippet) and confirmed to be **a summary
  article of OTHER researchers' already-cited work** (inter/intra-exchange arbitrage — same
  bot-speed-dominance conclusion already logged; classical football-betting favorite-longshot bias,
  a DIFFERENT asset class from this project's own Whelan-Kalshi finding, not additive evidence) —
  logged as confirming no course correction is needed, not as new evidence for anything. Two other
  search hits (arxiv 2606.16852 "Ghosts of Polymarket," an on-chain order-matching/revert
  microstructure paper, and arxiv 2605.10400 on perpetual-futures risk design) were scanned by
  title/abstract only and judged NOT relevant to a calibration/timing alpha (settlement-layer
  mechanics and a derivatives-wrapper proposal, respectively, not a crowd-mispricing or price-
  behavior finding) — not fetched further, logged so a future run doesn't re-scan them expecting
  alpha content.
- Self-validation (sources this run):
  - EXP-006 pilot extension: one live-fetched, pre-registered scratch-script run this session
    (unmodified `PolymarketHistoryFetcher.fetch_resolved_markets`/`fetch_price_history`, `seed=42`,
    run once, not retried after seeing the number); the 67-market question-text mapping was
    independently re-derived via a second, cheap (`fetch_resolved_markets`-only, no price-history)
    call and manually inspected for topic diversity/clustering — both scripts + their raw output
    live in a research-agent scratch path, not committed (per this project's established pattern:
    RESEARCH_MEMORY summarizes, does not embed, raw research-agent script output).
  - Egress: direct `curl` from this session against `gamma-api.polymarket.com`,
    `clob.polymarket.com`, `data-api.polymarket.com` — all 200, consistent with every run since
    2026-07-04.
  - QuantPedia "Systematic Edges in Prediction Markets": direct `WebFetch` this run (not
    re-summarized from the WebSearch snippet).
  - WebSearch sweep sources: all previously-logged, cross-checked against RESEARCH_MEMORY before
    being marked "no new evidence" rather than assumed.

**Binding constraint STANDS:** no validated real-money OOS edge on any tested mechanism to date.
This run's contribution is a genuine, reproducible strengthening of EXP-006's preliminary evidence
base (N=16→67, a tighter CI, and — new — a cluster-level robustness check that directly answers the
project's own standing concentration concern), while explicitly NOT claiming the pre-registered
100-event floor is met or that this is now a tradeable backtest. RECOMMEND-only — no ROADMAP steer.
The next highest-value step (unchanged in kind from Run 23's recommendation, now on firmer
preliminary footing): either keep growing N cheaply (a different sampling axis, e.g.
`order=volume24hr` or a non-Politics category) to approach the 100-event floor before any factory
build, or — if the factory independently prioritizes it — build the detector + per-CLUSTER exposure
cap together from day one (a per-trade-only cap is already proven a no-op, Run 22).

---

## 2026-07-17 — Research Run 25: tested Run 24's own recommended next step (a DIFFERENT sampling
axis, not the same axis widened again) — `order="volume24hr"` on the same tag_id=2 Politics /
last-14-days-hourly pilot method found N=14 additional survivors on markets from a DIFFERENT era
(2023-2024) with zero apparent overlap with Run 24's mostly-2026 survivor set; mean lag-1
autocorrelation -0.1154, 95% CI [-0.2017,-0.0308] excludes zero; a 3rd
independent corroboration of the negative-reversal direction, cluster-robust (8/8 clusters
negative) but flagged with an honest small-N concentration caution (one cluster = 35.7% of the
survivor set); still well below the pre-registered 100-event floor and STILL a hindsight
phenomenon statistic, not a cost-net tradeable backtest — RECOMMEND-only, no ROADMAP steer;
external web sweep re-fetched the QuantPedia mean-reversion paper directly and found the standing
"10bps cost collapses it" citation had compressed away a turnover-dependent nuance, plus verified
a new, more rigorous primary source for the "informed ~3% of traders" thesis

- Hypothesis (falsifiable, pre-registered BEFORE fetching — written to a scratch file first,
  unmodified repo code, no changes): if Research Runs 23-24's negative lag-1 hourly
  price-change-autocorrelation finding is a genuine phenomenon in Polymarket Politics markets
  (not an artifact of the `order=volumeNum` sampling axis specifically), then a MATERIALLY
  DIFFERENT sampling axis (`order=volume24hr`, trailing-24h volume rank, vs. `volumeNum`'s
  all-time volume rank) applied to the SAME `tag_id=2`/last-14-days/hourly/trim/statistic method
  should ALSO show a negative mean lag-1 autocorrelation with a 95% CI excluding zero. A
  positive result, or a CI spanning zero, would be evidence the Run 23-24 finding is
  axis-specific — reported honestly either way, not cherry-picked. This mirrors Research Run
  18's discovery that `volume24hr` surfaces a materially different, less-overlapping slice of
  the market universe than `volumeNum` for Sports; this run tests whether the same holds for
  Politics, and whether the reversal effect survives on that different slice.
- Min sample N: EXP-006's own pre-registered floor (`min_sample_n=100` across `>=3` distinct
  cycles) is unchanged and NOT yet met by this run alone (N=14) or even by an assumed-additive
  combination with Run 24's N=67 (~81, still short of 100) — and that combination is itself
  UNVERIFIED (see below).
- OOS result: **A 3rd independent corroboration at small N — not a validated edge, not a passed
  test.** Method (pre-registered before fetching, unmodified `PolymarketHistoryFetcher`
  imported directly from the repo, no code changes, `seed=42`, run once, not retried after
  seeing the number): `fetch_resolved_markets(limit=100, max_pages=2, order="volume24hr",
  tag_id=2)` — the SAME call shape as Run 24 (`limit=100, max_pages=2, tag_id=2`), only `order`
  changed from `"volumeNum"` to `"volume24hr"`. Same inclusion (market life >= 14 days when
  `start_date` known), same window (hourly ticks, last 14 days before `resolution_time`, one
  CLOB call per market, under the ~15-day-per-call cap), same trims (drop final 24h before
  resolution; drop hourly points outside [0.03, 0.97]), same statistic (per-market Pearson
  lag-1 autocorrelation of hourly price CHANGES), same survivor floor (`>=24` hourly points
  post-trim), same aggregation (equal-weight mean + market-level bootstrap 95% CI, 2000
  resamples, `seed=42`).
  **Result: 199 raw candidates returned; only 64 had a known `start_date` AND life>=14 days**
  (vs. Run 24's 186/200 on `volumeNum` — a genuine, previously-unmeasured axis property: markets
  ranked by TRAILING-24h volume among the RESOLVED set skew toward recently-active/
  recently-resolved names that more often lack a captured `start_date` in this corpus, so this
  axis is inherently lower-yield for the life-filter, not just differently-composed). **14 of 64
  survived the fetch+point-floor filter** (37 HTTP failures, 13 below the 24-point floor after
  trim — honest attrition, the same liquidity-selection caveat already logged for the other
  axis). **Mean per-market lag-1 autocorrelation = -0.1154**, **95% bootstrap CI
  [-0.2017, -0.0308]** (excludes zero, though visibly wider than Run 24's [-0.1508,-0.0886] —
  expected from N=14 vs N=67), **12 of 14 markets individually negative (85.7%,** close to Run
  23's 87.5% and higher than Run 24's 80.6%).
- **Cluster check (same method as Run 24):** the 14 survivors group into **8 distinct
  event-clusters** by topic: Hamas leadership/hostages (Sinwar, Deif, 3x hostage-release
  deadlines — 5 markets, 35.7%), 2024 GOP primary (Trump SC margin, Haley drop-out, Haley-vs-
  DeSantis Iowa — 3 markets), and 6 singletons (UK PM appointment, Taiwan presidential election,
  "another nation declares war" in the Israel-Hamas conflict, Sweden NATO accession, Abbas/PA
  presidency, Biden 538 approval rating). Cluster-level mean = **-0.1689**, 95% bootstrap CI
  (resampling CLUSTERS, `seed=42`, 2000 draws) = **[-0.2666, -0.0812]** — excludes zero, **8 of 8
  clusters (100%) individually negative.** Honest caution, stated plainly rather than glossed
  over: at N=14, the largest cluster (Hamas leadership/hostages) is over a third of the whole
  survivor set — a single cluster still has real leverage over the aggregate at this sample
  size, unlike Run 24's N=67/22-cluster check where the top cluster was only 27%. This does not
  invalidate the corroboration (all 8 clusters, including 7 outside the dominant one, are
  independently negative), but it means this run's result is weaker evidence per-market than
  Run 24's, not stronger, despite pointing the same direction.
- **The material new finding this run (not previously measured): axis disjointness on
  POLITICS, not just Sports.** All 14 `volume24hr` survivors are markets that resolved in
  **2023–2024** (Taiwan's January 2024 presidential election, the November 2023–March 2024
  Israel-Hamas hostage/leadership window, the January–February 2024 GOP primary, a February
  2024 Sweden NATO vote, a January 2024 Biden approval snapshot, a July 2026 UK PM item) — by
  question-text inspection, there is **zero topical overlap** with Run 24's mostly-2026
  survivor set (Fed-rate-decision meetings, US-Iran peace-deal/ceasefire, 2024-election
  popular-vote/margin contracts — Run 24's own list, re-read for this comparison, names no
  Taiwan/GOP-primary/Hamas-hostage/Sweden-NATO markets). This is consistent with genuine
  additivity (a combined survivor count approaching 67+14=81) and mirrors Research Run 18's
  Sports finding (near-zero category overlap between the two axes) — but it is **NOT formally
  verified**: no `market_id` diff was run against Run 24's raw list, because that list was
  never committed (per this project's established pattern that RESEARCH_MEMORY summarizes,
  never embeds, raw research-agent script output). The combined-N claim should be read as
  directional, not confirmed, until a future run does the actual set diff — logged as the
  concrete next step in GROWTH_STATUS `factory_next_action` rather than asserted here.
- Calibration (Brier / reliability): n/a — unchanged from Runs 23-24, this measures raw
  price-CHANGE serial correlation, not a probability-calibration statistic.
- Costs modeled: **none** — still explicitly a PHENOMENON probe, not a tradeable-strategy
  backtest. See the QuantPedia re-read below for a refinement of the standing cost caution.
- Verdict: **proposed (unchanged status in `experiments[]`) — pilot_probe field updated with
  the Run 25 volume24hr-axis result.** Still NOT `tested` — no strategy code, no cost model,
  no F10/F11 gate, and even an assumed-additive N (~81) is still below the pre-registered
  `min_sample_n=100` floor. This run adds a 3rd independent corroboration on a genuinely
  different historical slice of the market universe, with an honest small-N concentration
  caveat, without claiming the bar for a real backtest is cleared.
- Why / adversarial pre-mortem on THIS run's own extension:
  1. N=14 is smaller than either prior pilot run (16, then 67) — the WIDER bootstrap CI
     reflects that honestly; this is the weakest single-run corroboration by sample size even
     though the point estimate and cluster-negativity rate are both in the same range as Runs
     23-24.
  2. The dominant cluster (Hamas leadership/hostages, 35.7% of N=14) means roughly a third of
     this run's evidence traces to one underlying real-world situation (the Gaza war's late-2023
     acute phase) — a different unfolding of that same situation could plausibly have shown a
     different correlation sign, and this run has no way to test that counterfactual.
  3. The combined-axis "~81" figure is an inference from question-text non-overlap, not a
     verified market_id set diff — if the true overlap turns out to be non-zero (e.g. a market
     both axes independently surfaced), the real combined N is smaller than 81.
  4. This axis's much lower start_date+life-filter yield (64/199 vs. 186/200 for volumeNum) is
     itself a new, uncharacterized selection effect — the population of markets `volume24hr`
     surfaces skews toward ones this project CAN'T even attempt to test (no captured start
     date), which may differ systematically from the ones it can.
  5. All of Runs 20-24's standing cautions still apply unchanged: the July 2024
     assassination-attempt N=1 non-reversal; the raw autocorrelation is a hindsight statistic,
     not a causal/leakage-safe live decision rule; no per-cluster exposure cap exists in this
     repo yet for either axis's data.
- External research this run (WebSearch + 2 direct WebFetch passes on primary sources, not
  summarized from search snippets, per the standing WebFetch-over-summarization discipline):
  - **QuantPedia "Exploiting Mean-Reversion in Decentralized Prediction Markets" — re-fetched
    directly (previously cited only from a search snippet).** Confirms the already-logged
    top-line (N=3 novelty contracts — "Jesus returns," "China invades Taiwan," "aliens
    confirmed" — 10-minute price intervals over ~1 year, 12 lookback/hold-period variants,
    zero-spread vs. 10bps-friction scenarios) but surfaces a nuance the prior citation had
    compressed to "flips negative at a realistic 10bps cost": that collapse is
    **turnover-dependent, not universal**. The low-volatility "Jesus" contract's best
    zero-spread variant (5-day lookback, 1-day hold, Sharpe +2.97) does flip to Sharpe -2.60
    under 10bps friction, but on the two higher-volatility novelty contracts, PATIENT variants
    (20-day lookback, 5-day hold) remained viable after the SAME friction — only the
    high-turnover/short-hold variants died. This does not resolve the paper's own severe
    multiple-comparisons risk (N=3 contracts x 12 variants) and is a DAILY-cadence design, not
    directly transferable to EXP-006's hourly cadence — but it is a genuine, previously-
    uncaptured design input for any eventual EXP-006 strategy build: the right shape is a
    threshold-triggered fade (only outsized Delta crossings), not fading every hourly wiggle,
    consistent with EXP-006's own hypothesis text, not a change to it.
  - **New primary source, directly WebFetched (not previously logged with this detail):**
    Gomez-Cram, Guo, Jensen & Kung (London Business School / Yale; SSRN working paper 6617059,
    April 2026) — 1.72 million Polymarket accounts, $13.76B trading volume, 2023-2025. Finds
    ~3% of traders drive most price discovery, using a LUCK-ADJUSTED methodology (10,000
    coin-flip-direction simulations per trader to separate skill from luck): only 12% of top
    winners by raw profit clear that luck benchmark, and ~60% of "lucky winners" become losers
    when tested on a separate, held-out sample of events. This independently corroborates (via
    a different, more rigorously-described methodology than the secondhand "Le 2026" citation
    this project has used since Run 19) the standing "informed minority dominates price
    discovery" characterization of Polymarket — reinforces, does not change, the project's
    edge-source reasoning (any beatable inefficiency here must live where the informed ~3%
    aren't already arbing: thin, early-life, or off-radar corners of the market) — not a new
    EXP trigger, logged as strengthened context.
  - Two other search hits (a Medium "guide for traders" piece and a QuantDecoded blog post,
    both SEO-grade non-academic mean-reversion explainers) were scanned and confirmed to
    contain no new data/N/magnitude beyond what is already logged — not fetched further.
- Self-validation (sources this run):
  - EXP-006 pilot extension (volume24hr axis): one live-fetched, pre-registered scratch-script
    run this session, importing the UNMODIFIED
    `backend.app.prediction_markets.polymarket_history_fetcher.PolymarketHistoryFetcher`
    directly from the repo (not a reimplementation) — `fetch_resolved_markets` and
    `fetch_price_history` called exactly as the repo ships them; only the surrounding
    correlation/bootstrap/cluster arithmetic (pure Python, no numpy/scipy available in this
    environment) was written for this scratch analysis. `seed=42`, run once, not retried after
    seeing the number. The script + its raw survivor output live in a research-agent scratch
    path, not committed (per this project's established pattern).
  - Egress: direct `curl` + the fetcher's own `requests` session against
    `gamma-api.polymarket.com`, `clob.polymarket.com`, `data-api.polymarket.com` (all 200/expected)
    and `huggingface.co` (200) from this research-agent session — consistent with every run
    since 2026-07-04.
  - QuantPedia mean-reversion paper + the Gomez-Cram/Guo/Jensen/Kung SSRN paper: both direct
    `WebFetch` this run (not re-summarized from a WebSearch snippet).

**Binding constraint STANDS:** no validated real-money OOS edge on any tested mechanism to date.
This run's contribution is a 3rd independent corroboration of EXP-006's core statistic on a
genuinely different, disjoint slice of Polymarket Politics history, plus two refined/new pieces
of external context (the QuantPedia turnover nuance; the Gomez-Cram et al. primary source) —
while explicitly NOT claiming the pre-registered 100-event floor is met, NOT claiming the
combined-axis N is a verified number, and NOT claiming this is a tradeable backtest. RECOMMEND-
only — no ROADMAP steer. The next highest-value, cheap, research-agent-scope step (named in
GROWTH_STATUS `factory_next_action`): formally diff the volumeNum (Run 24) and volume24hr (Run
25) survivor sets by `market_id` to get a real combined N and re-run the cluster check on the
union before deciding whether a 3rd sampling axis is needed to reach the 100-event floor.

---

## 2026-07-18 — Research Run 26: executed Research Run 25's own recommended next step — formally
diffed the volumeNum (Run 24 shape) and volume24hr (Run 25 shape) EXP-006 pilot survivor sets by
`market_id`, on a FRESH pull of both axes (raw survivor lists from prior runs were never
committed, per this project's standing pattern). `volumeNum` reproduced Run 24 EXACTLY (N=67,
byte-identical stats — a genuine determinism check). `volume24hr` did **not** reproduce Run 25
(N=28 today vs N=14 two days earlier) — a new finding: this axis ranks by trailing-24h volume, so
its candidate set genuinely churns day to day, unlike `volumeNum`'s stable all-time ranking. A
direct `market_id` set diff on the fresh pull found **ZERO overlap**, confirming (not just
corroborating) the prior runs' inferred disjointness. **Union N=95** — close to, but still short
of, the pre-registered 100-event floor. Per-market mean lag-1 autocorrelation = -0.1193, 95% CI
[-0.1491,-0.0901] excludes zero, 79/95 (83.2%) individually negative. Cluster check (26 clusters):
mean -0.1104, CI [-0.1639,-0.0628] excludes zero, 22/26 (84.6%) negative, largest cluster only
18.9% of the union — less concentrated than any prior single-axis run. RECOMMEND-only, no ROADMAP
steer — still short of the pre-registered floor and still a hindsight statistic, not a cost-net
backtest.

- Hypothesis (falsifiable, pre-registered before fetching, written to a scratch file first,
  unmodified repo code, no changes): if Research Runs 24 and 25's separately-measured volumeNum
  (N=67) and volume24hr (N=14) EXP-006 pilot survivor sets are genuinely disjoint populations (as
  inferred from question-text/era non-overlap in Run 25, never formally confirmed), then a FRESH,
  pre-registered pull of both axes on the SAME day, with `market_id` recorded per survivor this
  time, should find (a) the `volumeNum` axis reproduces Run 24's result closely (it draws from a
  stable all-time-volume ranking that should not have moved materially in 2 days), (b) the
  `volume24hr` axis may or may not reproduce Run 25's exact N (it draws from a time-varying
  trailing-24h-volume ranking, so some drift is plausible and would itself be informative), and
  (c) a direct `market_id` set diff between the two fresh survivor sets should show little-to-no
  overlap, consistent with Run 25's question-text-based inference. A non-trivial overlap, or a
  materially different `volumeNum` result, would be evidence the prior runs' inferred combined-N
  reasoning was unsound.
- Min sample N: EXP-006's own pre-registered floor (`min_sample_n=100` across `>=3` distinct
  cycles) is unchanged. This run's formally-verified union (N=95) is the closest this project has
  come to the floor, but it is NOT yet met.
- OOS result: **the diff Run 25 called for, executed — a real, formally-verified union close to,
  but still short of, the floor.** Method (pre-registered before fetching, unmodified
  `PolymarketHistoryFetcher` imported directly from the repo, no code changes, `seed=42`, each
  axis run once, not retried after seeing the number; the ONLY methodological addition vs. Runs
  24-25 is recording `market_id` alongside each survivor's autocorrelation, so a real set diff is
  possible): for each of `order="volumeNum"` and `order="volume24hr"`,
  `fetch_resolved_markets(limit=100, max_pages=2, tag_id=2, order=<axis>)` (first ~200
  candidates), same inclusion (market life >= 14 days when `start_date` known), same window
  (hourly ticks, last 14 days before `resolution_time`, one CLOB call per market), same trims
  (drop final 24h before resolution; drop hourly points outside [0.03, 0.97]), same statistic
  (per-market Pearson lag-1 autocorrelation of hourly price CHANGES), same survivor floor (`>=24`
  hourly points post-trim).
  **`volumeNum` result: 200 raw candidates, 186 with a known `start_date` + life>=14d, 67
  survived the point-count filter — every one of these three numbers, and the resulting mean
  (-0.1198) and 95% bootstrap CI ([-0.1508,-0.0886], market-level, `seed=42`, 2000 resamples), and
  the negative-market count (54/67, 80.6%), are IDENTICAL to Run 24's result two days earlier.**
  This is a strong, previously-untested determinism/stability check on the `volumeNum` axis: the
  set of "top ~200 resolved Politics markets by all-time volume, that also have a captured
  `start_date` and >=14 days of life" is essentially FIXED over a 2-day window (Gamma's resolved
  set for this slice does not churn meaningfully day to day), so re-running this exact axis is not
  discovering new evidence — it is confirming the same evidence is stable.
  **`volume24hr` result: 199 raw candidates (same count as Run 25 — Gamma's top-199-by-trailing-
  24h-volume list itself is roughly stable in SIZE), but only 57 had a known `start_date` +
  life>=14d this run (Run 25: 64) — a 7-candidate drop — and only 28 survived the point-count
  filter (Run 25: 14 — a 2x INCREASE, not a repeat).** This is the run's most material new
  finding: unlike `volumeNum`, this axis's *composition* is NOT stable day to day, even though its
  raw *count* is. `order=volume24hr` ranks resolved markets by their trailing-24-hour trading
  volume AS OF the fetch time — a resolved market's trailing-24h volume today is a different
  quantity than its trailing-24h volume two days ago (trading in a resolved market can still occur
  briefly around settlement, or the "top 199 by this metric among all resolved markets" simply
  shifts as new markets resolve and old ones age out of a 24h lookback window). Practical
  consequence: any prior or future reference to "the volume24hr survivor set" must specify WHEN it
  was pulled — it is a snapshot, not a fixed corpus, and cannot be silently reused across runs the
  way `volumeNum`'s can.
  **The formal diff (the actual point of this run): a direct `market_id` set intersection between
  the 67 fresh `volumeNum` survivors and the 28 fresh `volume24hr` survivors returned ZERO
  overlapping ids.** This confirms — with an actual set operation, not question-text/era
  inspection — Runs 24-25's inferred disjointness. **Union (dedup by `market_id`): N=95.**
  Per-market: mean lag-1 autocorrelation across the 95-market union = **-0.1193**, 95% bootstrap
  CI (market-level resampling, `seed=42`, 2000 draws) = **[-0.1491,-0.0901]** (excludes zero, and
  is TIGHTER than either single-axis run alone — expected from the larger, still-representative
  N), **79/95 (83.2%) markets individually negative**. Every one of these figures sits squarely
  within the range of all three prior pilot runs (Run 23: -0.102 N=16; Run 24: -0.1198 N=67; Run
  25: -0.1154 N=14) — no sign flip, no magnitude collapse, across four independent measurements
  now.
- **Cluster check on the union (same manual keyword/topic-grouping method as Runs 24-25, applied
  fresh to all 95 markets — full list inspected, not sampled):** the 95 survivors group into **26
  distinct event-clusters**. The largest: Fed rate-decision contracts across 9 different FOMC
  meeting dates from Sept 2024 through Jan 2026 (18 markets, 18.9% of the union — e.g. "Fed
  decreases interest rates by 25 bps after October 2025 meeting?" and its "No change" counterpart
  for the same meeting are each counted as separate markets but the same cluster). Next: US/
  Israel-Iran tension broadly construed (ceasefire/peace-deal/military-strikes/diplomatic-meeting/
  Khamenei-succession/regime-fall contracts spanning mid-2025 through mid-2026, 16 markets, 16.8%).
  Then 2024 US presidential election popular-vote/state-margin contracts (10 markets, 10.5%), the
  2024 GOP primary (Trump South Carolina margin, Haley drop-out, Haley-vs-DeSantis Iowa — 7
  markets, 7.4%), Israel-Hamas hostage/leadership/Netanyahu contracts (7 markets, 7.4%), a single
  2026 UK Norfolk Police and Crime Commissioner by-election (6 different candidate-win markets for
  ONE election — 6 markets, 6.3%), South Korea presidential contracts (3 markets), and 18 smaller
  clusters of 1-2 markets each (Poland president, Canada PM, Peru president, Hungary PM, NYC mayor
  2025, US government shutdown, Russia-Ukraine ceasefire/war-end, Venezuela/Maduro, the Epstein
  files, and nine genuine singletons: Israel-Iraq military action, Abbas/Palestine presidency,
  Taiwan's presidential election, a US anti-cartel operation in Mexico, QatarEnergy LNG, Sweden
  NATO accession, a Trump Bitcoin-reserve pledge, Serbia's Vučić, Portugal's presidential election,
  and Biden's 538 approval rating). **Cluster-level mean = -0.1104**, 95% bootstrap CI (resampling
  the 26 CLUSTERS, `seed=42`, 2000 draws) = **[-0.1639,-0.0628]** — excludes zero, **22 of 26
  clusters (84.6%) individually negative**. **The largest cluster (Fed, 18.9%) is materially LESS
  dominant than in either prior single-axis cluster check** (Run 24: top cluster 27% of N=67; Run
  25: top cluster 35.7% of N=14) — a genuine, not merely asserted, robustness improvement: the
  effect is now spread across more, smaller clusters than when it was measured on either axis
  alone, exactly the direction Run 22's standing concentration concern would want to see before
  trusting a per-market or per-cluster aggregate more.
- Calibration (Brier / reliability): n/a — unchanged from Runs 23-25, this measures raw
  price-CHANGE serial correlation, not a probability-calibration statistic.
- Costs modeled: **none** — still explicitly a PHENOMENON probe, not a tradeable-strategy backtest.
  No new cost-model evidence this run (the QuantPedia turnover-dependent nuance Run 25 surfaced
  stands unchanged).
- Verdict: **proposed (unchanged status in `experiments[]`) — pilot_probe field updated with the
  Run 26 formally-verified union result.** Still NOT `tested` — no strategy code, no cost model,
  no F10/F11 gate, and N=95 is still (barely) below the pre-registered `min_sample_n=100` floor.
  This run's contribution is methodological rigor (a real set diff replacing an inferred one) and
  a materially improved cluster-robustness picture, not a new phenomenon or a passed test.
- Why / adversarial pre-mortem on THIS run's own extension:
  1. N=95 is still short of the pre-registered 100-event floor — this is not, and must not be
     read as, a passed test. The temptation to round 95 up to "effectively 100" must be resisted;
     the next run should actually cross the floor before any claim of a met precondition.
  2. The cluster taxonomy remains a post-hoc, manual, keyword-based grouping (the same
     methodological caveat every prior run's cluster check has carried) — a different clustering
     choice (e.g. splitting the broad "US/Israel-Iran tension" cluster into narrower
     ceasefire-specific vs. military-action-specific sub-clusters) could shift the cluster-level
     CI's exact bounds, though 22/26 independently-negative clusters makes a sign flip from
     re-clustering alone implausible.
  3. The `volume24hr` axis's newly-confirmed day-to-day instability cuts both ways: it is
     reassuring that a materially different daily sample (N=28 vs N=14) still shows the same
     sign and a similar magnitude (independent evidence against the effect being a fluke of one
     day's specific sample), but it also means the "N=95 union" reported here is itself only a
     snapshot — a future run pulling volume24hr on a different day and re-diffing could land on a
     different total (very likely still disjoint from `volumeNum`, per two independent zero-
     overlap checks now, but not necessarily exactly 95).
  4. All of Runs 20-25's standing cautions still apply unchanged and are not re-litigated as
     resolved by this run: the July 2024 assassination-attempt spike (N=1) did NOT reverse; the
     raw autocorrelation is a hindsight statistic, not a causal/leakage-safe live decision rule;
     no per-cluster EXPOSURE cap exists in this repo for any axis's data; the QuantPedia
     turnover-dependent friction-collapse caution stands.
  5. This run only re-ran the SAME two axes at the SAME tag_id/window/trim/statistic
     configuration Runs 24-25 already used — it did not test a 3rd sampling axis, a different
     category, or a different window length. The recommended next step (widen `volumeNum`'s pool,
     or re-pull `volume24hr` fresh) stays within this same configuration family; a genuinely new
     axis is not yet warranted given how close N=95 already is to the floor.
- External research this run (2 WebSearch sweeps, DATA only, no WebFetch needed since nothing
  surfaced warranted a primary-source deep-read beyond what is already logged):
  - "Polymarket price reversal serial correlation overreaction research 2026" — surfaced only
    already-logged sources (Clinton & Huang via DL News secondary coverage, including the "58%"
    figure already flagged since 2026-07-15 as an unverified secondary-source number not present
    in the primary abstract; the QuantPedia mean-reversion backtest; several arxiv papers already
    scanned and judged not relevant — "Ghosts of Polymarket" settlement mechanics, the perpetual-
    futures risk-design paper — plus one new-to-search-results-but-not-new-in-substance item, an
    NBA-market arbitrage-analysis arxiv paper (2605.00864), scanned by title/abstract only and
    judged not relevant to a calibration/timing alpha — a market-microstructure arbitrage study,
    not a crowd-mispricing or price-behavior finding; not fetched further).
  - "prediction market calibration edge crowd wisdom 2026 study" — surfaced only already-logged
    primary sources (Le 2026 Decomposing Crowd Wisdom; Gomez-Cram/Guo/Jensen/Kung) with no new
    detail beyond what Runs 20-25 already captured directly from these papers.
  - "Polymarket Kalshi cross-market arbitrage logical consistency mutually exclusive contracts
    2026" (a B8-adjacent sweep, since cross-venue/cross-market coherence is a standing open
    ROADMAP direction distinct from EXP-006): returned exclusively SEO/marketing-grade "how
    arbitrage bots work" guide sites (laikalabs.ai, clawarbs.com, launchpoly.com, tradingvps.io,
    botforkalshi.com, a dev.to post, a HackerNoon listicle) — no academic source, no N, no
    magnitude, no primary data. Not fetched further, not logged as evidence for or against
    anything; logged only so a future run does not re-spend a search budget expecting alpha
    content from this exact query shape.
- Self-validation (sources this run):
  - EXP-006 pilot diff: two live-fetched, pre-registered scratch-script runs this session
    (unmodified `backend.app.prediction_markets.polymarket_history_fetcher.PolymarketHistoryFetcher`
    imported directly from the repo, not a reimplementation — `fetch_resolved_markets` and
    `fetch_price_history` called exactly as the repo ships them; only the surrounding
    correlation/bootstrap/cluster/set-diff arithmetic, pure Python stdlib only, was written for
    this scratch analysis). `seed=42`, each axis run once, not retried after seeing the number.
    The script + its raw per-market-id output (the actual basis for the set diff reported above)
    live in a research-agent scratch path, not committed (per this project's established pattern).
  - Egress: direct `curl` (200 on `gamma-api.polymarket.com`, `clob.polymarket.com`,
    `data-api.polymarket.com`) plus the fetcher's own `requests` session for the real pulls — all
    consistent with every run since 2026-07-04.
  - WebSearch sweep sources: all previously-logged sources cross-checked against RESEARCH_MEMORY
    before being marked "no new evidence"; the handful of not-previously-logged items (the NBA
    arbitrage arxiv paper, the SEO arbitrage-guide sites) were scanned and judged not to contain
    new primary data, not fetched further, and not logged as evidence.

**Binding constraint STANDS:** no validated real-money OOS edge on any tested mechanism to date.
This run's contribution is methodological, not phenomenological: it replaced Runs 24-25's inferred
axis-disjointness with a formally-verified one (a real `market_id` set diff, zero overlap), pushed
the pilot's honestly-countable N from two separate sub-floor numbers to a single formally-unioned
N=95 (closer to the pre-registered 100-event floor than any prior run), and materially improved the
cluster-concentration picture (largest cluster now 18.9%, down from 27%/35.7% on either axis
alone) — while explicitly NOT claiming the floor is met or that this is a tradeable backtest.
RECOMMEND-only — no ROADMAP steer. The next research-agent step (pre-registered before fetching):
either widen the now-confirmed-stable `volumeNum` axis's candidate pool (e.g. `max_pages=3`) or
re-pull the now-confirmed-unstable `volume24hr` axis fresh on a later date and re-diff — either is
expected to cross the 100-event floor without needing a 3rd sampling axis.

## 2026-07-19 — Factory build (NOT a research run): EXP-006 fade-the-spike FULL BACKTEST LAYER built (strategy + cost model + F10/F11 gate + per-trade concentration cap) — the pilot→strategy graduation the Quality Auditor named; NO edge claimed

- **What was built (#385):** `backend/app/prediction_markets/spike_reversal_backtest.py` — the cost-net,
  leakage-safe, F10/F11-gated PnL layer on top of the existing `spike_detection.py` primitive. It fades
  each causally-confirmed spike (UP → buy NO, DOWN → buy YES), enters at the spike's `confirm_time` (the
  earliest knowable instant), exits at the forward-horizon price from `label_reversal` (strictly forward),
  and prices BOTH legs through the single-source-of-truth cost model — the new
  `cost_model.effective_sell_price()` is the symmetric exit friction, so a round-trip at an unchanged price
  honestly books the two-way cost as the hurdle the reversion must clear. This delivers exactly the
  "spike→reversal walk-forward harness + per-trade concentration cap" that E3's prior note (post-#350) and
  the QUALITY_SCORECARD's business_case_strength gap both named as the missing step to graduate EXP-006
  from a raw-autocorrelation pilot to a testable strategy.
- **The Run 21 concentration cap, shipped from day one — TWO ways:** EQUAL-WEIGHT sizing (a fixed dollar
  budget per trade, so no market can dominate by BETTING BIGGER) + a hard `max_trades_per_market` cap
  (default 1, so a market that spikes repeatedly cannot flood the sample with correlated same-market bets).
  This is the STRUCTURALLY-CORRECT response to Run 22's key finding — that the bucket family's concentration
  came from **many small CORRELATED trades, not one oversized bet** (a per-trade notional cap was a no-op
  there). A per-MARKET trade cap addresses correlation; a notional cap did not.
- **Honest 4-criterion validated-edge gate (never the point estimate alone):** `is_validated_edge` is the
  AND of (1) N ≥ 100 (the pre-registered floor), (2) F11 `significant_positive` (bootstrap CI on total PnL
  excludes zero), (3) F10 non-fragile, and (4) hit-rate > 50% — matching every criterion the QUALITY_SCORECARD's
  validated-edge bar names. F10 for this SINGLE-horizon strategy excludes the (structurally single-valued)
  horizon axis while the horizon stays ≤ 1 day — the same no-information reasoning `regime_slice` already
  uses to exclude unlabeled category — and RE-ENGAGES the horizon check if the horizon is swept above a day.
  The load-bearing single-market / confidence-band / extreme-confidence / time-window / category checks are
  all retained.
- **NO EDGE IS CLAIMED.** This is a measurement engine, exactly like `walk_forward`: it recovers a real
  cost-net reversion edge on a mean-reverting synthetic corpus (labeled NOT a real edge) and reports
  EDGE-NOT-PROVEN on momentum / small-N. It reaches NO revenue field: `weekly_pnl_paper` stays null,
  `total_trades` 0, `engine_pct` 74. `business_case_strength` stays **B** — this unblocks the honest EXP-006
  test, it is not that test.
- **Two-gate readiness passed.** (1) `scripts/preflight.sh code` GREEN (15 new offline tests registered in
  the gate; ruff correctness-clean; runtime harness PASSED). (2) 3 FRESH adversarial Opus auditors, each told
  to break the engine: leakage → CANNOT-BREAK across all 5 surfaces (entry uses `confirm_price` not
  `peak_price`, exit strictly forward and horizon-bounded, selection outcome-independent, deterministic under
  varied `PYTHONHASHSEED`); cost/PnL → ACCOUNTING-SOUND (PnL identity `payout−budget==pnl` verified numerically,
  no cost double-count); gate logic → GATE-SOUND (horizon-exclusion legitimate, single-market check load-bearing,
  never claims edge from a point estimate, never reaches go-live). The gate-gaming auditor surfaced one material
  honest gap — the missing hit-rate>50% criterion — which was ADDED before merge, plus 3 cheap hardenings
  (horizon-guard, extreme-band check restored, F11-independence caveat documented).
- **Reconciliation with the OWNER STEER (honest):** the steer's priority #1 (concentration-capped bucket
  REDESIGN) was DEPRIORITIZED this run — it was already TESTED and refuted in Research Run 22 (2026-07-14,
  on the real EXP-003 N=1,369 corpus: neither the notional cap nor the favorites-only variant rescues the
  mechanism), and the QUALITY_SCORECARD calls the bucket-calibration family "exhausted — NOT another
  parameterization." Per the steer's own "an honest null STILL clears the value bar; do NOT p-hack an edge
  to satisfy the steer," effort went to priority #2 (EXP-006), which is a structurally-different, non-exhausted
  mechanism both the steer and the auditor endorse.
- **Residual / next_actions (the SPECIFIC buildable steps):**
  1. **The real test needs a real corpus (owner/egress-gated, no credential — public data):** fetch a
     point-in-time, NON-survivorship Politics intraday-tick corpus (`PolymarketHistoryFetcher.fetch_price_history`
     per market) reaching N ≥ 100 spikes, run `backtest_fade_the_spike`, and record the honest F10/F11 verdict.
     Survivorship discipline is critical — sample the spike universe by a decision-time criterion, not by which
     markets happen to have long tick histories.
  2. **Spike-size / salience stratification** (Run 21's N=1 caution — the LARGEST spikes may persist, not
     fade): stratify the labeled events by magnitude and report per-stratum reversion, so the engine does not
     average a fade-able small-spike regime with a persist-y large-spike regime.
  3. **Market impact on the fade legs:** the fade currently prices the flat `effective_buy/sell_price` (no
     depth), so it is mildly cost-OPTIMISTIC at scale — wire `depth_contracts` into the legs before any
     capacity/live claim (needs per-market book depth, egress-gated).
- **Verdict:** engine BUILT + audited-sound; **edge NOT proven** (no real-data run yet — the honest state).
  Binding constraint unchanged: `business_case_strength = B`, no validated real-money OOS edge on any tested
  mechanism to date.

## 2026-07-19b — Factory build (NOT a research run): EXP-006 size-robustness (spike-size / salience) gate + walk_forward per-CATEGORY exposure cap — TWO file-disjoint code PRs, both HONEST NULLs / instrument-hardening, NO edge claimed

**PR #387 — EXP-006 size-robustness (spike-size / salience) gate.** RESEARCH_MEMORY's own named
next-step for EXP-006 (Run 21's LOAD-BEARING N=1 caution: *the biggest 2024 political spike did
NOT revert — it kept trending*). Built on top of the #385 fade engine as a per-magnitude-band
`strata` report plus a size-robustness SCREEN operationalizing that caution: the largest-spike
cohort is judged against the SAME F11 bootstrap the aggregate is, and flagged whenever it is
`significant_negative`, so a positive aggregate that is only a small-spike artifact is BLOCKED from
VALIDATED-CANDIDATE.
- **Four successive fresh Opus adversarial audits, each breaking a version of the gate** (maker≠checker):
  the first cut was edges-gameable (a caller-controlled report-band edge could collapse magnitudes
  into one bin and silently disable the gate); the second was rank-count-dilutable; the third was
  range-fraction-outlier-sensitive. The design converged on a FIXED ABSOLUTE magnitude cut
  (large-spike set = `|move| >= 0.25`) — config-independent, not-diluted, outlier-insensitive —
  judged by bootstrap significance (N ≥ 20 trades) or net-PnL sign when underpowered. Every
  reproduced counterexample from all four attack rounds (losing tails sized 1-40; a mid-tier-loss
  hiding under a winning larger tier) now blocks a green VALIDATED-CANDIDATE, verified directly
  across the full attack surface. 24 tests pass.
- **Honestly disclosed limitation:** this is a SCREEN, not an adversarially-complete proof — a
  losing mid tier beneath a larger winning tier can still dilute within the pool. The per-band
  `strata` report exists for manual review; no single automated cohort test is robust (four audits
  confirmed this). **No real corpus has been run through the engine yet — NO edge claimed.**

**PR #388 — walk_forward per-CATEGORY exposure cap (Run 20-22's named-but-never-built concentration
fix).** Built as `walk_forward_backtest(category_exposure_cap=...)` (concurrent committed-basis cap,
`cap=None` byte-identical to before, pinned hashes hold) + a `--category-exposure-cap` OOS variant
on both the static-calibration and recency-weighted bucket alphas.
- **HONEST RESULT (frozen 187-record corpus, cap=0.20): the bucket-calibration family STAYS
  REFUTED.** calibration-capped = `significant_negative` **−$3,228**; recency-capped =
  `insufficient_data` **−$3,444**.
- Two findings sharpened by review, both now disclosed in code + JSON:
  1. The cap is a CONCURRENT-exposure control; F10's `top_category_budget_share` is a CUMULATIVE
     measure, so the cap does not bind that metric — and on this temporally-spread corpus it did
     not bind at all (`cap_bound: false`).
  2. The aggregate is net-NEGATIVE, so an F10 non-fragile pass would be VACUOUS anyway — **no
     concentration control can manufacture an edge from a losing signal.**
- 2 Opus auditors + 2 Sonnet reviewers (1 requested-changes, addressed via honest reframing +
  machine-readable disclosure of `cap_bound` + a dust-trade guard).

**Verdict: NO validated out-of-sample real-money edge on any mechanism.** Bucket-calibration family
REFUTED (EXP-002/003/005 + this run's cap variant). EXP-006 now has the instrument (fade engine +
size-robustness screen) but NO real intraday-tick corpus has been run through it (egress-blocked).
Binding constraint stays `business_case_strength = B`, unchanged. `engine_pct` stays 74. Both PRs
harden the honest test apparatus; neither reaches a revenue field.

**NEXT buildable steps (filed to ROADMAP):**
1. EXP-006 real test: a point-in-time, non-survivorship intraday-tick Politics corpus, N ≥ 100
   spikes, run through the now-size-robustness-gated `backtest_fade_the_spike` (egress-gated,
   public data, no credential).
2. A faithful bucket de-concentration test needs BOTH a CUMULATIVE per-category deployment cap (the
   concurrent cap does not bound F10's cumulative share) AND a net-positive-but-fragile corpus
   (concentration is moot on a losing aggregate). Egress-gated.
3. B8 dual-venue OOS harness: blocked on Kalshi orderbook wiring + a curated co-listed universe
   (egress + owner); no speculative skeleton until real data exists (DECISION COROLLARY).
4. (from PR #387's audits) A robust multi-band/windowed size-robustness gate, or a documented manual-
   review step — no single automated cohort test is adversarially complete for "do the biggest
   spikes revert."

## 2026-07-19c — FIRST real-data EXP-006 fade-the-spike OOS run: EDGE-NOT-PROVEN (N=108) — the egress-gated next-step the last three runs filed, now RUN. Plus a live-safety ingest fix. Binding constraint unchanged.

**This is the run that closes the "EXP-006 instrument built but untested on real data" gap.**
The fade engine (`spike_reversal_backtest.py`, #385/#387) had never touched a real corpus; every
prior run filed "needs a real point-in-time non-survivorship intraday-tick corpus" as
egress-gated. Egress was open this run, so it was RUN — and the honest verdict is EDGE-NOT-PROVEN.

- **What ran (#390):** new `scripts/fetch_spike_corpus.py` builds a leakage-safe intraday-tick
  corpus REUSING the audited `PolymarketHistoryFetcher` verbatim (only-new logic: chunk the hourly
  CLOB fetch into <=15-day windows — the CLOB caps `fidelity=60` at ~360 ticks/15d, verified live;
  truncate each series strictly before `resolution_time - 24h` so no fade exit can read a
  settlement pin). Pre-registered universe: resolved binary Politics (Gamma `tag_id=2`, verified
  live), `order=volumeNum`, `max_pages=3` → 300 fetched, 255 kept (496,056 hourly ticks). Committed
  gzipped (`data/spike_corpus_politics.json.gz`, ~2 MB) for offline reproducibility;
  `run_spike_reversal.py` gained transparent `.gz` support. Result in
  `docs/autonomous-loop/EXP006_REAL_DATA_VALIDATION.md`.
- **Result (pre-registered DEFAULT config, run ONCE, deterministic — reproduces bit-for-bit):**
  N=108 trades (above the 100 floor), net **+$285.44**, hit 58.3% — but **F11
  indistinguishable_from_zero** (total 95% CI **[−527.30, +1090.61]**) and **F10 FRAGILE**
  (confidence-band 168% + category 107%, both > the 70% gate; leave-one-out removes the top
  category → −$19.99; top-market share 49.7% is BELOW the gate so single-market is not itself
  binding). `is_validated_edge=False`. No revenue field reached.
- **The magnitude strata confirm Run 21's N=1 caution on real data AT SCALE:** small spikes
  partially revert (0–0.15: +$443, 83% hit; 0.15–0.25: +$500, 69%) but the **largest spikes
  (>=0.25, N=43) LOSE −$657 (33% hit) and COMPOUND** (mean reversion −0.09). The apparent
  small-spike profit is NOT a tradeable carve-out: the magnitude band is unknowable at decision
  time (the peak can extend past entry — `MagnitudeStratum` docstring), so conditioning on it is
  look-ahead. The pre-registered strategy fades ALL confirmed spikes, and that aggregate is the null.
- **Two-gate readiness PASSED.** (1) preflight code stages GREEN (config import, curated tests incl.
  the new `test_fetch_spike_corpus.py` leakage-truncation test, lint, E2E runtime harness);
  deterministic re-run + offline `.gz` reproduce identically. (2) **3 FRESH adversarial Opus
  auditors, each told to break it:** leakage → **CANNOT-BREAK-LEAKAGE** (the 18 near-pin exits
  LOSE −$802, ruling out pin-inflation; deterministic under shuffled input; truncation +
  CLOB-only tick sourcing structurally airtight); p-hacking → **SOUND-NULL** (defaults untouched,
  run once, the discarded small-spike edge is genuinely look-ahead); survivorship/cost/stats →
  **SOUND-NULL** (re-ran at zero costs → +$853 but STILL indistinguishable_from_zero, so not a
  cost artifact; every disclosed bias makes the null conservative; event-correlation only widens
  the CI). 2 Sonnet reviewers/PR APPROVE. Auditors caught 2 honesty imprecisions in the writeup
  (the 49.7% single-market framing; "filed to" vs "to be filed") + 2 reviewer nits (dead import,
  a fail-loud guard on a non-positive leakage margin) — all fixed before merge.
- **Live-safety ingest fix (#391, file-disjoint):** the Gamma `outcomePrices` parser did a bare
  `float(p)` that raised an UNCAUGHT `ValueError` on a malformed price at the single-market fetch
  sites (`get_market_by_id` — on the live resolution/MTM path), BYPASSING the existing honesty
  guard and dropping the whole market instead of marking it untradeable. Fixed with a tolerant
  `_coerce_outcome_price()` (→ None, never raises) routing into the existing guard. Both reviewers
  reproduced the pre-fix crash; regression tests pin it.
- **B8 data-engineering finding (live-probed, sharpens the ROADMAP; no code shipped — DECISION
  COROLLARY):** egress to BOTH venues is open, but the Kalshi `status=settled` feed is **100%
  high-frequency sports** (1200 markets scanned, 0 political). Political markets ARE reachable via
  `/events?status=settled` (carries category — 14/40 Politics/Elections in a probe) and
  `/series?category=Politics` (2089 series). So the B8 co-listed universe blocker is now specific:
  `KalshiHistoryFetcher` needs an events-by-category → markets-by-event query path (the settled
  feed alone never reaches political markets), plus a COMMON-INSTANT leakage-safe dual-venue
  snapshot (both legs priced at the same real pre-resolution instant — else the "disagreement" is
  temporal, not arbitrage). Building the backtest now would find ~0 matches = a shaky skeleton, so
  it stays a filed next-step, not a speculative build.

**Binding constraint STANDS: `business_case_strength = B`, no validated real-money OOS edge on any
tested mechanism.** BOTH real-money mechanisms tested to date are now refuted on real data:
bucket-calibration (EXP-002/003/005 + the #388 cap variant) AND EXP-006 fade-the-spike (this run,
default config). `engine_pct` stays 74. An honest null with the specific next step filed IS a
value-bar-clearing success (steer + §2), not a failure.

**NEXT buildable steps (filed):**
1. A pre-registered threshold/window/horizon **robustness surface** on the SAME committed corpus
   (report ALL cells, select none) — is the null default-specific or config-family-wide? Offline,
   no new data.
2. A **momentum / ride-the-spike EXP-007 candidate** (the inverse of the refuted fade — the ≥0.40
   spikes COMPOUND, hit 21%) — but N=19 is far below the floor and the same not-knowable-at-decision
   caveat applies; file, do NOT claim.
3. B8: add the events-by-category → markets-by-event Kalshi query path + the common-instant
   leakage-safe snapshot, THEN the coherence backtest (egress open; the consumer + fetcher path
   should ship together as one focused unit).

## 2026-07-20 — EXP-006 pre-registered CONFIG ROBUSTNESS SURFACE: FAMILY-NULL-STRONG (0/60) + B8 cross-venue live-probe finding. NO edge. Binding constraint unchanged.

**The run that answers #390's open question.** The first real-data EXP-006 fade-the-spike run
(#390) reported EDGE-NOT-PROVEN at the DEFAULT config (N=108, +$285.44, F11 indistinguishable,
F10 fragile) and filed as its #1 next step: *is that null a fluke of the default knobs, or
config-family-wide?* This run built + ran the pre-registered robustness surface that answers it.

**PR — EXP-006 config robustness surface** (new pure/deterministic `spike_robustness_surface.py`
+ CLI `run_spike_robustness_surface.py` + 14 offline tests registered in the gate +
`exp006_robustness_surface` SELF_VALIDATION capability + result doc
`EXP006_ROBUSTNESS_SURFACE.md`). A sweep of the leakage-safe, cost-net, F10/F11-gated fade
engine over a FIXED 5×4×3 = 60-cell grid (threshold ∈ {0.05,0.08,0.10,0.15,0.20} × window ∈
{30m,1h,2h,6h} × horizon ∈ {6h,12h,24h}, bracketing the default) on the SAME committed corpus.
Report-all-cells, select-none.

- **RESULT: `FAMILY-NULL-STRONG` — 0 of 60 cells validate.** 0 F11 significant_positive; **18
  significant_NEGATIVE**; 15 indistinguishable; 27 insufficient_data (N<100). Net-PnL range
  −$2,257 … +$1,198, median −$64. **Every powered cell (N≥100) is indistinguishable-from-zero or
  significantly negative; and every one of the 14 positive-PnL cells is ALSO F10-gate-fragile (0
  broad)** — the positive region (high-threshold / 1h corner, N=56–96) is doubly disqualified
  (underpowered/indistinguishable AND concentrated). **The default's EDGE-NOT-PROVEN is
  config-family-wide, not a default artifact** — a strictly stronger refutation than #390's
  single cell. EXP-006 fade-the-spike now joins the bucket-calibration family as REFUTED on real
  data.
- **HONEST BY CONSTRUCTION.** In-sample (one committed corpus) ⇒ no cell can be a validated edge,
  however green; selection is refused as p-hacking in code (family verdict never sets a
  validated-edge flag, never reaches a revenue field; conservative chance-green expectation
  ≈K·α/2 = 1.5, moot at 0 green). Horizons ≤24h so the engine's horizon-axis F10 exclusion is
  fair per cell; categories passed through so the F10 category axis engages (stricter than #390).
  Default cell reproduces #390 bit-for-bit.
- **Two-gate readiness PASSED.** (1) `scripts/preflight.sh code` GREEN (14 surface tests +
  engine tests in the curated gate; ruff correctness-clean; runtime harness PASSED;
  self-validation 15 caps, unmet=[]); deterministic re-run reproduces identically. (2) 3 FRESH
  adversarial Opus auditors + 2 Sonnet reviewers. The honesty/p-hacking auditor + a Sonnet
  reviewer independently caught a real defect — the displayed F10 column copied the RAW
  horizon-INCLUSIVE `regime.fragile`, not the horizon-EXCLUDED GATE F10 that `is_validated_edge`
  uses (a false "copied verbatim" self-description; conservative bias, could not manufacture an
  edge). FIXED before merge: the engine now exposes `f10_gate_ok`/`f10_gate_reasons` and the
  surface tabulates that (tri-stated; a validated cell can never read fragile). A correctness
  auditor + a Sonnet reviewer caught wrong doc summary counts (12/30 → 15/27) and a false "Filed
  to ROADMAP" claim — both FIXED. A 4th FRESH Opus confirmation auditor verified the fixes are
  sound with no new inconsistency. The scorecard/safety-reconcile auditor returned SOUND (no
  ship-critical gap; maker≠checker preserved; no revenue field; no go-live tick).

**B8 cross-venue live-probe finding (egress open; NO code shipped — DECISION COROLLARY).** The
`/markets?status=settled` feed is 100% sports; `/events?status=settled` DOES carry `category`
and reaches political markets (135/200 settled events on page 1 are Politics/Elections). BUT
per-event settled-MARKET retrieval is thin + concentrated: of 40 sampled settled political
events, only 11 yielded ≥1 reachable market via `/markets?event_ticker=…` (87 markets total, one
event `KXTRUMPPARDONS` contributing 52). So the events-by-category discovery path is necessary
but NOT sufficient; the binding unknown for B8 is the co-listed Polymarket↔Kalshi MATCH count
(differing ticker/strike semantics), not the raw Kalshi count. Building the fetcher + coherence
backtest now would reach a tiny, mostly-unmatched universe = the speculative skeleton the ROADMAP
+ DECISION COROLLARY forbid. **Sharpened next step:** a cross-venue MATCH probe — pull the
reachable settled political Kalshi markets (full pagination+dedup) + resolved Polymarket
political markets, run the EXISTING `cross_venue_matcher.match_markets`, and COUNT true co-listed
pairs; only a usable N unblocks the common-instant snapshot + coherence backtest.

**Binding constraint STANDS: `business_case_strength = B`, no validated real-money OOS edge on
any tested mechanism.** engine_pct unchanged. An honest config-family-wide null with the specific
next step filed IS a value-bar-clearing result (steer + §2), not a failure.

**NEXT buildable steps (filed):**
1. EXP-006b: a FRESH pre-registered OOS of the high-threshold (0.15–0.20) fade variant on
   new/larger political data — the only underpowered-positive corner (the threshold is a
   decision-time knob, so it is legitimately pre-registrable, unlike the post-hoc magnitude
   carve-out). Pre-register threshold+N before fetching; do NOT reuse the committed corpus.
2. EXP-007 momentum (ride-the-spike): still N=19 on #390's ≥0.40 band — below floor; file, don't build.
3. B8 cross-venue MATCH probe (above) — the co-listed match count gates any further B8 build.

## 2026-07-20 — Research Run 27: external-research synthesis surfaces a genuinely new, untested in-scope mechanism (EXP-008). RECOMMEND-only, no code/backtest run. EXP-006 status corrected in GROWTH_STATUS.

**Orientation.** Read RESEARCH_PLAYBOOK.md, this file (tail), ROADMAP.md, VISION.md,
`docs/BUSINESS_CASE.md`, GROWTH_STATUS.md. Confirmed via `git log` that the factory's own
2026-07-20 run (#393/#394, same calendar day, ahead of this research run) landed the EXP-006
config robustness surface: **FAMILY-NULL-STRONG, 0/60 cells validate** — EXP-006 fade-the-spike
now joins the bucket-calibration family (EXP-002/003/005) as REFUTED on real data. **Both
real-money mechanisms this project has fully tested to date are now refuted.** This is the
binding constraint this run reasons from: re-parameterizing either refuted family (a 4th
category-only bucket-calibration re-run, or another EXP-006 threshold/window cell) is now
established in this project's own memory as low expected value — the mechanism is the suspect,
not the knobs. The higher-EV move is to find a mechanism this project has NOT yet tested.

**A staleness catch (dashboard-honesty, not a research finding, but load-bearing for §7 —
REPORT = the dashboard):** GROWTH_STATUS.md's `experiments[].EXP-006.status` was still
`proposed` despite the mechanism being refuted twice over (07-19c and 07-20) — the
`real_oos_result` narrative lived only in `as_of`/this file, never synced back into the
experiment's own status field. Also, `as_of` itself had regressed: HEAD (`git show HEAD`)
is commit `d614135` (PR #393, the robustness-surface CODE), which merged 16 seconds AFTER the
bookkeeping commit `3124704` (PR #394) that should have prepended the 07-20 summary to `as_of`
— but #393's tree did not carry #394's `as_of` edit, so the working file's `as_of` head was
still the 07-19c text, silently dropping the 07-20 factory summary from the dashboard's most-
recent-first log. Fixed both this run: `EXP-006.status` → `refuted` with a `real_oos_result`
covering both real tests; `as_of` restored the dropped 07-20 factory summary (condensed from
this file's own 2026-07-20 entry above, which was NOT affected by the merge-ordering issue) as
a `PRIOR` segment, ahead of this run's own summary. This is a docs-only integrity fix, not a
new backtest — no metric was touched, no status other than EXP-006's was changed.

**External research (2 WebSearch sweeps, 2 direct WebFetch passes on primary sources — not
snippet-only per this project's standing discipline).**

1. `"Polymarket multi-outcome market arbitrage mispricing sum probabilities 2026 research"` —
   surfaced arXiv:2508.03474 ("Unravelling the Probabilistic Forest: Arbitrage in Prediction
   Markets") and arXiv:2605.00864 ("Arbitrage Analysis in Polymarket NBA Markets"). The FIRST is
   not new to this project's search history in substance (a broad Polymarket-wide arbitrage
   census, "Market Rebalancing" (single-market) vs. "Combinatorial" (cross-market) arbitrage,
   ~$40M realized profit extracted across BOTH types combined per its abstract — WebFetched
   the abstract directly; it does not break the $40M down by type, does not state the sample
   period precisely, and does not state whether fees/slippage are netted from that figure, so
   it is logged as a directional magnitude only, not a number this project relies on for any
   claim). The SECOND is the one with new, concrete, decision-relevant numbers (below) — Research
   Run 26 (2026-07-18) had already surfaced this exact paper by title/abstract in a DIFFERENT
   search (an EXP-006-focused sweep) and explicitly judged it "not relevant to a
   calibration/timing alpha — a market-microstructure arbitrage study, not fetched further."
   That judgment was correct FOR EXP-006 (timing/reversal) but this run's WebFetch of the actual
   abstract text found it measures the exact mechanism behind this repo's own **untested**
   `SameMarketArbitrageStrategy` (`backend/app/prediction_markets/strategies.py`, ROADMAP B1) —
   a connection Run 26 had no reason to make since it was not looking for a same-market-arb
   angle. Read directly (WebFetch, targeted extraction prompt, not a generic summarize):
   - Methodology: 75 million limit-order-book snapshots across 173 Polymarket NBA game markets
     (continuous order-book reconstruction, not just trade prints).
   - Single-market ("rebalancing") arbitrage: **only 7 executable in-game episodes** found in
     the entire sample. **Median persistence: 3.6 seconds** before the mispricing closed.
   - Combinatorial (cross-market) arbitrage: **290 active episodes** — more numerous, but
     **76.9% were constrained to an average executable size of only ~14.8 shares** (severe
     liquidity/depth limits — a real position could not be sized meaningfully even where the
     signal was genuine).
   - The abstract did not state whether fees were netted into the "executable" classification,
     nor give a persistence duration for the combinatorial type specifically — logged as an
     open gap, not assumed favorably or unfavorably.
2. `"prediction market calibration crowd wisdom research paper 2026"` — re-surfaced only
   already-logged primary sources (Le 2026 "Decomposing Crowd Wisdom"; Gomez-Cram/Guo/Jensen/Kung
   "Prediction Market Accuracy: Crowd Wisdom or Informed Minority?", SSRN 6617059) with no new
   detail beyond what prior runs already extracted directly from these papers. No course
   correction.
3. `"Kalshi Polymarket arbitrage same event different venue price discrepancy 2026"` (B8-adjacent)
   — same result as Runs 18/26's identical-shape query: exclusively SEO/marketing-grade "how
   arbitrage bots work" guide sites (polyburg.com, clawarbs.com, launchpoly.com, newspoly.net,
   tradoxvps.com, laikalabs.ai, dropstab.com, tokenmetrics.com, eventarb.com, fightmatrix.com) —
   no academic source, no verifiable N, no primary data. One recurring unverified claim across
   several of these sites ("World Cup 2026 outright winners traded 1.3pp apart on France between
   Kalshi/Polymarket as of 2026-05-04, sustained 5–8 cent gaps on individual team contracts") is
   logged here ONLY as a reason a future B8 run might look at that specific market/date range —
   NOT as evidence of anything, per this project's standing rule against treating SEO-site
   numbers as data (same treatment Runs 18/26 gave this exact query shape).

**Cross-referencing external finding (1) against this repo's OWN code (not just the paper):**
`SameMarketArbitrageStrategy`'s own docstring already discloses, honestly, that it fires on CLOB
**midpoints** (not the ask a real fill would pay) and that the orchestrator does not yet do
confirmed per-leg execution — so a fired signal is explicitly described in-repo as "a candidate
to verify against live depth, not a locked-in profit." The NBA paper's numbers put a concrete,
sobering magnitude on exactly that gap: if same-market mispricings on Polymarket generally behave
like the NBA sample (rare, and gone in a median of 3.6 seconds), then `orchestrator.py`'s
`scan_interval_sec` default of **120 seconds** — confirmed by reading the code, not assumed —
is roughly **two orders of magnitude slower** than the measured opportunity lifespan. A backtest
that fired this strategy against END-OF-SCAN snapshot prices without accounting for this gap
would systematically overstate capturable edge (the classic "the opportunity existed in the data
but was gone before a polling bot could act" failure mode) — exactly the kind of self-inflicted
overfitting this project's own hunt-your-own-leakage discipline exists to catch, applied here
BEFORE any backtest is built rather than after one produces a too-good number.

**Recommendation — EXP-008 (new, written to GROWTH_STATUS.md `experiments[]`, full spec
there):** a same-market logical-consistency arbitrage poll-latency executability PILOT. Not a
backtest — a bounded, read-only, pre-registered LIVE measurement using the EXISTING
`PolymarketClient` + `SameMarketArbitrageStrategy` UNMODIFIED: poll the live neg_risk universe at
the real 120s cadence, log every cost-net-positive fired signal, and measure what fraction
survive to the NEXT poll at EXECUTABLE order-book depth (not just midpoint — the 76.9%-at-~14.8-
shares finding means midpoint survival alone would overstate the real number). This is the
CHEAPEST experiment currently on the table by data-access cost (no new fetcher, no new corpus,
no egress dependency beyond what already works for live scanning) — but it is a genuinely NEW,
untested mechanism (logical-consistency arb, not price-level calibration or price-timing), so a
null result here would be a THIRD independently-diagnosed binding constraint (this time
INFRASTRUCTURE/latency, not forecasting skill), and a non-null result would open a real new
avenue. Falsifiable, pre-registered, minimum N, cost assumptions, and a 5-item
how-it-could-be-wrong pre-mortem (incl. that the NBA-specific numbers may not transfer to
slower-moving political/economics categories — the whole reason to MEASURE on this repo's own
universe rather than assume the NBA number applies) are all in the GROWTH_STATUS.md entry.

**RECOMMEND-only. No ROADMAP steer** — EXP-008 is a proposal grounded in external literature +
this repo's own code, not a reproduced OOS result; it does not clear the high bar §6 sets for
touching ROADMAP.md/BUSINESS_CASE.md. **Binding constraint unchanged:** no validated real-money
OOS edge on any tested mechanism to date. `engine_pct` unchanged (74); `business_case_strength`
stays B; no revenue field touched; no code changed this run (docs-only: GROWTH_STATUS.md +
this file).

**NEXT buildable steps (filed, priority order):**
1. EXP-008: build the small time-boxed live-polling harness (factory-build scope, not a
   research-agent turn — it requires real wall-clock time to run) and report the raw survival
   rate with no selection.
2. EXP-006b: the sole still-open high-threshold fade corner, fresh data, if a future research
   run wants one more pre-registered look before fully closing the EXP-006 family.
3. EXP-007 momentum: still N=19, below floor — file, don't build.
4. B8 cross-venue MATCH probe — gates any further B8 build.

## 2026-07-20b — Factory build (model/strategy factory, NOT a research run): B8 quote path UNBLOCKED — Kalshi live API moved quotes to `*_dollars`; ingest fix + cross-venue MATCH probe pins the ONE remaining blocker. NO edge claimed.
- Hypothesis (falsifiable): n/a — a B8 DATA-ENGINEERING advance + a feasibility MATCH probe (owner-steer priority #3), not an alpha test. Claims NO edge, reaches NO revenue field.
- Context: the last five B8 probes (2026-07-05 ×3, 2026-07-19c, 2026-07-20) pinned the path as "per-series discovery → structured-strike parser → per-market ORDERBOOK quote assembly → semantic classifier → co-listed universe → OOS harness," with the standing blocker recorded as **"Kalshi has no quotes on the list feed; they live in `/markets/{ticker}/orderbook`."**
- **DECISIVE CORRECTION (live-probed this run, egress open HTTP 200):** the prior "no quotes" reading is STALE. Kalshi's live elections API changed schema — the integer-cents fields (`yes_bid`/`yes_ask`/`last_price`/`volume`) the client read are now **always `null`** (0/200 sampled), and the real quote lives in **dollar-string fields on the SAME list feed** (`yes_bid_dollars`/`yes_ask_dollars`/`last_price_dollars`, each already an implied YES prob in [0,1]; `volume_fp`). So the client did not read the *wrong endpoint* — it read the *stale field names*, and marked **100% of live Kalshi markets untradeable**. NO orderbook call is needed for a quote.
- **SHIPPED #397 (code):** `kalshi_client._yes_probability_from_quotes` reads whichever schema yields a usable strictly-positive quote (cents first for back-compat, then dollars), never fabricating a midpoint from a one-sided/zero/out-of-range book (#101 honesty preserved: a `"0.0000"` dollar quote stays untradeable); `volume_fp` fallback; optional `series_ticker` filter for per-series discovery. **Live-verified:** `KXBTCMAXY` 7/7 markets untradeable pre-fix → 7/7 tradeable post-fix (YES 0.035–0.145, real volume). 11 new fixture tests; 2 Sonnet reviewers APPROVE (both mutation-tested the new tests non-tautological).
- **MATCH PROBE (feasibility, the pinned next step — NOT p-hackable, counts pairs, no PnL):** with the fixed client, pulled the Kalshi crypto numeric universe per-series (`KXBTCMAXY`/`KXBTCD`/`KXETHMAXY`/`KXETHD` → **415 tradeable** markets, was 0) + 94 active Polymarket markets, ran the EXISTING `cross_venue_matcher.find_cross_venue_matches` → **0 candidate matches**.
- **ROOT of the 0 (evidenced), = the ONE remaining blocker:** Kalshi crypto market **titles are generic** ("Bitcoin price on Jul 20, 2026?") so `extract_threshold` (title-text) returns `None`, while the real strike lives ONLY in the structured `floor_strike` field. Polymarket titles DO carry a parseable strike ("Will Bitcoin be above $68,000…" → Threshold(68000,currency,up)). The matcher's specificity gate then rejects (exactly one side strike-defined). So the quote blocker is GONE; the binding blocker is now, precisely, the **structured-strike parser** (`floor_strike`/`cap_strike`/`strike_type` → `Threshold`) + a **targeted Polymarket crypto universe** (only 8/94 default markets are crypto) + the touch/barrier/terminal semantic classifier.
- Verdict: **edge-not-proven (B8 data-eng advance, not runnable yet)** — a real, verified UNBLOCK (quote path) + a measured feasibility null (0 matches) with the exact next buildable step now evidenced.
- NEXT (pre-registered, do NOT p-hack): (1) a Kalshi structured-strike parser feeding `Threshold` into `match_markets` (pure, fixture-testable against real `floor_strike` payloads); (2) a targeted co-listed BTC/ETH universe (Polymarket crypto tag + the Kalshi per-series fetch this run added); (3) semantic touch/barrier/terminal classification so only same-mechanic pairs match; THEN re-run the match probe — only a usable co-listed N unblocks the common-instant snapshot + `evaluate_cross_venue_pairs` OOS harness. Per DECISION COROLLARY, (1)–(3) ship as one focused unit once (2) confirms a non-trivial N — not speculatively before.
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge.

## 2026-07-20c — Factory build (model/strategy factory): B8 structured-strike parser SHIPPED — blocker moves OFF the parser onto co-listed-universe availability. NO edge.
- Hypothesis (falsifiable): n/a — a B8 data-engineering advance (owner-steer priority #3): build blocker (i), the structured-strike parser, and re-run the MATCH probe. Claims NO edge, reaches NO revenue field.
- Context: 2026-07-20b (#397) fixed the Kalshi quote path and pinned the ONE remaining blocker as the structured-strike parser (Kalshi crypto titles are generic → `extract_threshold(title)`=None while the strike lives in structured `floor_strike`).
- SHIPPED #400 (code): `Market` +`floor_strike`/`cap_strike`/`strike_type` (optional, Kalshi-only, default None); `kalshi_client._parse_market` captures them (finite-coerced, garbage/absent→None, never fabricated; `strike_type` normalized); `cross_venue_matcher.extract_threshold_from_structured_strike` (greater/greater_or_equal+floor→up; less/less_or_equal+cap→down; between/unknown/functional/bound-less→None — refuse to guess); unit inferred ONLY from an explicit currency/percent cue in the market's OWN text and a unit-less **"plain" strike is REFUSED** (returns None) so a bare-number magnitude coincidence can never license a false pairing; `match_markets` reads `_threshold_for()` = title-first-else-structured (IDENTICAL for any market without structured fields). Offline deterministic tests incl. the specificity-gate UNBLOCK + a plain-vs-plain collision-refused regression + refuse-to-guess. preflight code GREEN; a committed live probe `scripts/b8_match_probe.py` backs the figures.
- ADVERSARIAL REVIEW (maker≠checker, caught a real bug): reviewer 1 found that a "plain"-unit structured strike could license a magnitude-only FALSE pairing between two unrelated same-token markets (Kalshi "hashrate 95000" ↔ Polymarket "forum members > 95000", coherence 0.74 > the 0.5 trade bar — the cardinal sin); fixed by refusing unit=="plain" (loses no target coverage — crypto markets carry a "price"/"$" cue → currency; live probe unchanged). Reviewer 2's disclosure asks addressed: the touch/barrier/terminal semantic-mechanic classifier (step iii) is disclosed IN CODE as an outstanding gate; the 1 candidate is labeled UNCLASSIFIED. A same-STRIKE candidate is NOT a same-event match until step iii gates it.
- LIVE PROBE (egress open; reproducible; NOT p-hackable — counts pairs, no PnL): fetched Kalshi crypto per-series (KXBTCD/KXBTC/KXETHD/KXETH/KXBTCMAXY/… → **823 tradeable**) + Polymarket (default get_markets + crypto search). Of the 823, **408 are STRUCTURED-ONLY** (title parse fails, this parser succeeds) vs **23** title-strike → the parser makes a dense real BTC/ETH strike ladder ($72,999.99/$73,249.99/… "greater") matchable for the FIRST time. Ran `find_cross_venue_matches` title-only(old) vs with-structured(new): **both = 1** candidate pair (BTC $55k: Polymarket "dip to $55,000 by Dec 31" ↔ Kalshi "below $55000.00 by Jan 1", coherence 0.74) → structured marginal Δ on MATCHES = **0** this snapshot. ROOT (evidenced): the standing Polymarket crypto universe is genuinely thin — a crypto search returns only ~5 active binary crypto markets (0 ethereum) — a MARKET-STRUCTURE reality, not a fetch gap (a targeted crypto-tag/search fetch was tried, does not surface more). Kalshi lists a dense ladder; Polymarket lists few standing crypto price-ladder markets.
- Verdict: **edge-not-proven** (B8 data-eng advance — blocker (i) DONE, no runnable OOS harness yet). A real, tested unblock + a measured feasibility null with the blocker precisely re-pinned.
- Why: the structured parser works on 408 real markets (verified) but produces no NEW live matches because the co-listed LIVE universe barely overlaps at any instant. The binding B8 blocker has MOVED from the strike parser (DONE) to co-listed-universe availability. A LIVE snapshot is the wrong instrument; the right instrument is a HISTORICAL co-listed corpus.
- NEXT (pre-registered, do NOT p-hack): (1) a HISTORICAL co-listed BTC/ETH corpus — fetch RESOLVED past Kalshi crypto markets (structured strikes, this run's parser) + resolved Polymarket crypto markets over the SAME dates, match on strike+window, count true co-listed pairs over time; only a usable historical N unblocks the common-instant snapshot + `evaluate_cross_venue_pairs` OOS harness. (2) touch/barrier/terminal semantic classifier so only same-mechanic pairs match (Kalshi KXBTCMAXY barrier vs KXBTCD terminal vs Polymarket touch). Per DECISION COROLLARY, (1)–(2) ship as one unit once (1) confirms a non-trivial historical co-listed N.
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge; engine_pct unchanged.

---

## 2026-07-22 — Research Run 28: external-literature sweep + a live Kalshi data-access probe surfaces a real historical-data unblock (feeds B8) + a genuinely new venue/category calibration candidate (EXP-009). RECOMMEND-only, no code/backtest run, no ROADMAP steer.

**Orientation.** Read RESEARCH_PLAYBOOK.md, RESEARCH_MEMORY.md (tail), ROADMAP.md, VISION.md,
`docs/BUSINESS_CASE.md`, GROWTH_STATUS.md first. Confirmed via `git log` that HEAD (`fd5b93a`,
#402) is an owner-raised ROADMAP edit (A9, Robinhood Predict — double-gated, not active work),
not new alpha work — so the binding constraint is unchanged since the last research/factory
entry (2026-07-20c): both real-money mechanisms fully tested to date (bucket-calibration family
EXP-002/003/005 across 4 corpora; EXP-006 fade-the-spike, FAMILY-NULL-STRONG 0/60 cells) stay
REFUTED; B8 cross-venue coherence stays blocked on co-listed-universe availability (structured-
strike parser DONE, #400); EXP-008 (same-market poll-latency pilot) stays proposed/unbuilt
(factory-build scope, needs real wall-clock time). This run reasons from that constraint: do
NOT re-parameterize a refuted family; look for a genuinely new mechanism, venue, or category, or
a data-access unblock that changes what's testable.

**External research (3 WebSearch sweeps + 5 WebFetch/live-probe passes, not snippet-only).**

1. `"prediction market calibration mispricing research paper 2026 favorite longshot bias"` —
   re-surfaced Le 2026 ("Decomposing Crowd Wisdom") with a sharper quote than previously logged:
   "a 70% Polymarket price in a political market at a 1-week horizon reflects approximately 83%
   true probability" — a favorite-underpricing / calibration-slope-above-1 claim. This is the
   SAME mechanism this project has already tested 4 times on real Polymarket data (static bucket
   EXP-002, N=510/621/799; recency-weighted bucket, N=799; HuggingFace-archive independent
   corpus, N=375) — every test refuted (sign-flips across corpora, or fragile/concentrated).
   Logged as reconfirmation ONLY — explicitly not a re-build trigger; re-testing an already-
   refuted family on a fifth Polymarket pull would be low-EV pattern-matching against noise, not
   new evidence.
2. `"Polymarket Kalshi order book imbalance microstructure edge research 2026"` — surfaced
   arXiv:2604.24366 ("The Anatomy of a Decentralized Prediction Market: Microstructure Evidence
   from the Polymarket Order Book", Dubach — 30B order-book events over 52 days, a
   stratified 600-market panel; WebFetched the abstract directly). Reports a "longshot spread
   premium" (effective spreads widen near 0/1, no exact magnitude given in the abstract) and,
   separately, that trade direction inferred from Polymarket's PUBLIC order-book feed agrees with
   the ON-CHAIN ground truth on only **~59%** of buckets (vs. ~80% typical CLOB accuracy) — a
   data-quality caution logged for any FUTURE Polymarket microstructure work this project might
   do (nothing in the current codebase infers trade direction from the WS feed today, so this is
   not acted on, just filed). Also surfaced (WebSearch synthesis only, not independently
   verified): "~86% of Polymarket 5-minute-window crypto taker volume is from bot-like wallets" —
   consistent with, and reinforcing, EXP-008's own concern that a 120s poll cadence cannot
   compete in the fastest-moving market segments; not a new mechanism, corroborating context only.
3. `"2026 US midterm election prediction market mispricing Polymarket Kalshi"` — mostly
   marketing/news-aggregator content ($197M midterm volume, current odds levels). One item is a
   genuine IN-SCOPE-BOUNDARY reminder rather than an alpha lead: reporting that Kalshi fined/
   suspended congressional candidates and staffers for trading their own races on non-public
   information — logged as a reinforcement of this project's standing OUT-OF-SCOPE rule (never
   chase non-public-information edges), not as a lead to follow.

**The one new, decision-relevant primary source (WebSearch + 2 WebFetch attempts, partially
fail-closed).** NBER working paper **w34702, "Kalshi and the Rise of Macro Markets"** (Diercks,
Katz, Wright — Federal Reserve Board researchers; also posted as a Fed FEDS working paper and on
SSRN). Uses 2,668 settled Kalshi macro contracts, July 2021–June 2026, across three categories
(Fed/rate decisions, inflation, employment/labor), evaluated via Brier scores, calibration
curves, and favorite-longshot-bias tests at a 7-day-pre-settlement horizon. Per the WebSearch
synthesis of the abstract/summary: **Fed/rate markets are near-perfectly calibrated with no
significant favorite-longshot bias; inflation markets show moderate calibration; EMPLOYMENT/
labor markets show the WEAKEST forecasting performance and "significant systematic mispricing,"
with unemployment-rate contracts carrying the LARGEST calibration errors** of any category
tested. **Attempted to verify the exact numbers against the primary source directly** — WebFetch
of the Fed FEDS PDF (`federalreserve.gov/econres/feds/files/2026010pap.pdf`) returned only
encoded/compressed PDF binary streams, not extractable text; the NBER abstract page
(`nber.org/papers/w34702`) carries only the top-level abstract, no category-level breakdown. Per
this project's FAIL-CLOSED discipline: **no exact Brier score, calibration-error magnitude, or
favorite-longshot-bias coefficient is reported here as a number this project relies on** — only
the directional claim, sourced to a named, Fed-affiliated, non-SEO working paper (materially more
credible than the marketing-site "arbitrage" leads this project has repeatedly logged-but-not-
used in prior runs), logged as a MOTIVATION for a new candidate, not as a measured result.

**Why this is a genuinely new candidate, not a re-parameterization.** Every bucket-calibration
test this project has run to date (EXP-002/003/005, 4 corpora) was on **Polymarket** data only.
This project has never run ANY alpha mechanism against Kalshi's OWN economics/employment-category
markets — the Kalshi work to date is either data-adapter infra (A3) or the B8 cross-venue
matcher (a structurally different, disagreement-based mechanism). A different venue (CFTC-
regulated Kalshi vs. Polymarket) with a different crowd composition, on a category an independent
academic source specifically flags as the WEAKEST-calibrated segment of that venue, is a
legitimately distinct hypothesis — not the same mechanism restated with new knobs.

**Live feasibility probe (read-only, public Kalshi REST API, no auth, no orders — squarely
research-agent scope). Egress open, HTTP 200 throughout.** Two findings:

1. **Kalshi's economics/employment universe is real and large.** `GET /series?category=Economics`
   (limit=200) returned **599** Economics-category series (of 621 total series on that page).
   Filtering for employment/labor keywords surfaced ~30 relevant series, including `KXU3`/
   `KXECONSTATU3` (monthly unemployment rate), `KXPAYROLLS`/`KXUSNFP` (nonfarm payrolls),
   `KXJOBLESS` (weekly initial jobless claims), `KXECONSTATCPICORE`/`CPIYOY` (inflation), and
   `KXFEDHIKE` (Fed decisions) — confirming the NBER paper's three named categories all have a
   live, public, structured-strike Kalshi market universe today.
2. **DECISIVE: Kalshi's live REST API only serves a rolling ~3-month window, and a separate,
   documented, public `/historical/*` endpoint tier exists that this project's
   `KalshiHistoryFetcher` does NOT yet query.** `GET /historical/cutoff` (live-verified, HTTP 200)
   returned `{"market_settled_ts": "2026-05-23T00:00:00Z", ...}` — the live `/markets?status=
   settled` feed's effective floor. Confirmed against the official docs
   (`docs.kalshi.com/getting_started/historical_data`, WebFetched): Kalshi partitions markets/
   candlesticks/trades/orders into a live tier (recent only) and a historical tier (`GET
   /historical/markets`, `GET /historical/markets/{ticker}`, `GET /historical/markets/{ticker}/
   candlesticks`, etc.), same cursor-pagination contract as the live endpoints, **no
   authentication documented or required** (verified: public 200 responses with no credentials
   supplied). **Live-verified this run:** `GET /historical/markets?series_ticker=KXECONSTATU3`
   returned a genuine finalized April-2026 unemployment-rate market
   (`KXECONSTATU3-26APR-T5.5`, `status: "finalized"`, `result: "no"`) that the live
   `/markets?status=settled` endpoint no longer serves (it predates the May-23 cutoff). This is
   the reason the prior 07-19c/07-20/07-20c B8 probes kept finding the LIVE settled feed thin —
   they were never wrong about what the live feed returns, but there is a whole second, public,
   deeper tier the fetcher has never queried. **Depth-probed 4 employment/economics series via
   `/historical/markets` (single unauthenticated GET each, `limit=200`, no pagination beyond one
   page attempted for the shallower series):** `KXECONSTATU3` → 115 markets / **5** distinct
   monthly release-events, back to **Dec 2025**; `KXPAYROLLS` → 200 markets (page-capped, likely
   more available uncounted) / **22** distinct monthly events, back to **Nov 2024**;
   `KXECONSTATCPICORE` → 55 markets / **5** events, back to Dec 2025; and — the deepest —
   `KXJOBLESS` (weekly initial jobless claims, one clean market per release, NOT a correlated
   multi-strike ladder like the monthly series) → 74 markets / **69** distinct WEEKLY release-
   events, back to **Aug 2021** (`JOBLESS-21AUG07`). Real, live-verified, multi-year depth on at
   least one employment-category series.

**Two disclosed, evidenced caveats (not glossed over).**
- The monthly-report series (`KXECONSTATU3`/`KXPAYROLLS`/`KXECONSTATCPICORE`) are
  **strike-ladder markets**: one macro release generates ~10–20 simultaneously-settling threshold
  markets that are NOT independent observations of crowd calibration — they are highly
  correlated draws on the same underlying number, structurally identical to the Fed-rate-decision
  clustering problem this project's memory has already flagged (a prior run found Fed-decision
  contracts were 18.9%–27% of a Politics-corpus union by themselves). A future EXP-009 build must
  count **independent release-events**, not raw market rows, when assessing N — by that count,
  the deepest single series (`KXJOBLESS`) gives **69** independent weekly observations, comfortably
  above this project's standing 100-min-N-ish bar only once combined across a couple of series/
  years; the monthly series individually (5–22 events) do not clear it alone.
- This is a **feasibility + literature finding, not a backtest.** No PnL, no Brier score, no
  calibration curve, and no cost model were computed against this data this run — the probe
  counted reachable market rows and distinct events only, exactly the same discipline as every
  prior B8 feasibility probe in this file. **No edge is claimed.**

**Bonus finding (incidental to the probe, not chased further this run): a second, uncovered
Kalshi structured-strike schema.** Several of these economics/employment markets carry
`"custom_strike": {"Value": "5.5"}` + `"strike_type": "custom"` (a single-point "exactly X%"
market) — distinct from the `floor_strike`/`cap_strike`/`strike_type ∈ {greater, less, between}`
scheme the just-shipped (#400) B8 structured-strike parser handles. `extract_threshold_from_
structured_strike` correctly returns `None` on a `strike_type == "custom"` market today (the
existing refuse-to-guess default, verified by reading the code — not a bug, no false-pairing
risk), so this is filed as a scope gap for a future extension, not a defect.

**Why the `/historical/markets` finding matters beyond EXP-009.** B8's own 2026-07-20c entry
(above) pinned its NEXT step as "a HISTORICAL co-listed BTC/ETH corpus — fetch RESOLVED past
Kalshi crypto markets." The same `/historical/*` tier applies to Kalshi's crypto series
(`KXBTCD`/`KXBTCMAXY`/etc.), not just economics — this run's finding is a general Kalshi
data-access unblock that directly serves BOTH the already-filed B8 next step AND the new EXP-009
candidate, from one underlying fetcher change (`KalshiHistoryFetcher.fetch_resolved_markets`
extending its query to fall back to `/historical/markets` once the live tier's cutoff is passed).

### Recommendation — EXP-009 (new, written to GROWTH_STATUS.md `experiments[]`, full spec there)

A Kalshi employment/labor-category calibration-bucket test: reuse the EXISTING, already-built
`CalibrationBucketStrategy`/`RecencyWeightedBucketModel` mechanisms (never rebuilt — the refuted
Polymarket tests already proved the MECHANISM code works and abstains/raises honestly) against a
NEW corpus — Kalshi employment/labor-category markets pulled via `KalshiHistoryFetcher` EXTENDED
to also query `/historical/markets` — falsifiable hypothesis, minimum N (counted in independent
release-events, not raw market rows, given the ladder-correlation caveat above), OOS plan,
significance threshold, cost assumptions, and a 5-item how-it-could-be-wrong pre-mortem are all
in the GROWTH_STATUS.md entry. **RECOMMEND-only — no ROADMAP steer.** This is a feasibility
probe + an external directional literature claim, not a reproduced OOS result with a causal
mechanism at sufficient N; it does not clear the high bar §6 sets for touching ROADMAP.md/
BUSINESS_CASE.md. Binding constraint unchanged: no validated real-money OOS edge on any tested
mechanism to date. `engine_pct` unchanged (74); `business_case_strength` stays B; no revenue
field touched; no code changed this run (docs-only: GROWTH_STATUS.md + this file; all data
fetched this run was read-only public market data via existing/no new endpoints, no capital, no
orders, no live-trading surface touched).

**NEXT buildable steps (filed, priority order):**
1. Extend `KalshiHistoryFetcher.fetch_resolved_markets` to fall back to `GET /historical/markets`
   (same schema family, cursor-paginated, no new credential) once the live tier's `/historical/
   cutoff` is passed — a general capability, not EXP-009-specific. Offline-fixture-testable
   against the field shapes this run observed live (incl. the `custom_strike` variant).
2. Once (1) ships: run the EXP-009 pilot (Kalshi employment/labor calibration-bucket, pre-
   registered per the GROWTH_STATUS.md spec) AND re-attempt the B8 historical co-listed BTC/ETH
   corpus (2026-07-20c's own pinned next step) — both consumers of the same fetcher extension,
   per this project's DECISION COROLLARY (ship the capability once, use it for both filed needs).
3. Extend `extract_threshold_from_structured_strike` to handle `strike_type == "custom"`
   (single-point strikes) if/when a same-event cross-venue match against a custom-strike market
   is ever needed — not urgent, no current consumer blocked on it.
4. EXP-008 same-market poll-latency pilot — still the filed, cheapest, build-first next step from
   Research Run 27 (2026-07-20b), unchanged priority.
5. EXP-006b / EXP-007 — both still filed, both still below-floor or fully refuted; no change.

Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any
tested mechanism; engine_pct unchanged.

## 2026-07-22 — Factory build (model/strategy factory): the CUMULATIVE per-category budget-share cap SHIPPED (the faithful de-concentration control Runs 20-22 named but never built) + B8 resolved-Kalshi structured-strike capture. NO edge — honest NULL on the committed corpus.
- Hypothesis (falsifiable): n/a — two data/tooling advances on the owner-steer priorities (#1 concentration-capped bucket redesign; #3 B8 cross-venue data-engineering). Claims NO edge, reaches NO revenue field.
- **Owner steer priority #1 — CUMULATIVE per-category budget-share cap (#404).** The prior `category_exposure_cap` (#388) bounds CONCURRENT open exposure; because positions settle and free room, a category cycles unbounded CUMULATIVE volume, so it does NOT bound F10's `top_category_budget_share` (Σ per-cat budget ÷ Σ total budget) — the exact quantity F10 gates on. `walk_forward_backtest` now takes `cumulative_category_budget_cap`: each trade is sized DOWN so the running post-trade per-category share never exceeds the cap (`room=(cap·ΣT−Σcat)/(1−cap)`; the first deployed trade is bootstrap-exempt because its share is 1.0 by definition, its fixed budget diluted as turnover grows — the residual slack ≤ first_trade/total is DISCLOSED, not hidden). It is a NO-OP below 2 distinct categories (a share cap has nowhere to reallocate on a single-category / all-`__uncategorized__` book — mirrors F10's own categories-known exclusion) and for cap≥1; the EFFECTIVE cap drives both sizing and seed_hash, so a no-op / `None` hashes byte-identically to no cap. Threaded into `validate_real_oos`'s `concentration_capped_variant` (calibration + recency, concurrent + cumulative) + `--cumulative-category-budget-cap`.
- **Result on the committed frozen N=187 corpus (deterministic, reproducible — identical sha256 across runs):** the cumulative cap BINDS where the concurrent cap does not — recency-weighted top-cat share **0.554→0.40**, calibration **0.382→0.31** — faithfully bounding F10's own metric. BUT both alphas are net-NEGATIVE (calibration −$3,228 F11 `significant_negative`; recency −$3,444), so **no concentration control can manufacture an edge from a losing signal** — the bucket-calibration family STAYS REFUTED. **Honest NULL.** The one remaining ingredient the faithful de-concentration test needs — a net-positive-but-fragile per-category corpus — stays egress-gated and filed.
- **Adversarial gate earned its keep (maker≠checker, caught 3 real issues before merge):** (1) Opus auditor found the variant verdict HARD-CODED "the aggregate is net-NEGATIVE … Honest NULL" whenever no variant validated — which fires on an F10-FRAGILE (horizon/confidence) result REGARDLESS of PnL sign, so a net-POSITIVE, F11-significant, merely-fragile corpus was reported as a net-negative null (and a new test locked it). Rewrote the verdict as a pure `_concentration_verdict` that reads the ACTUAL state (net-negative vs F11-insignificant-noise vs F11-significant-but-F10-fragile-on-a-non-category-dimension, which a CATEGORY cap cannot fix) and never claims a sign it did not observe. (2) Both Sonnet reviewers: the verdict narrated BOTH caps even when only one was requested → now gated per requested cap. (3) Opus auditor found a mono-category / all-`__uncategorized__` book collapsed to 1 trade then falsely flagged its 100% share as a breach → fixed by the <2-category no-op above. Also: the faithful-share check now includes the disclosed bootstrap-slack term and is asserted only where the cap ENGAGED. This is direct evidence the adversarial-audit requirement catches real honesty defects on research-instrument PRs, not just execution-path PRs.
- **Owner steer priority #3 — B8 resolved-Kalshi structured-strike capture (#405).** The live client captured Kalshi structured strikes (#400) but the RESOLVED-history fetcher — the one a HISTORICAL co-listed corpus (B8 step ii) is assembled from — did not, so every resolved Kalshi crypto record was strike-BLIND (generic title → no title-text strike). `KalshiResolvedMarket` now carries `floor_strike`/`cap_strike`/`strike_type` (finite-coerced via `_finite_float`, garbage/absent→None, never fabricated); `cross_venue_matcher._infer_structured_unit` duck-types over `.question`(live)/`.title`(resolved) so `extract_threshold_from_structured_strike` yields the SAME `Threshold` on both paths — a captured resolved strike is directly matcher-usable where the generic title is not (proven by test; a "between" range still refuses to guess). Both Opus auditors COULD-NOT-BREAK (no fabrication, no leakage, no live-`Market` regression). The B8 historical-corpus blocker moves OFF strike-blindness; the resolved→`Market` price bridge + the egress-gated corpus fetch remain the filed next unit (DECISION COROLLARY — no speculative skeleton).
- Verdict: **edge-not-proven** on both — a real, tested tooling/data-eng advance on each owner-steer priority, each with an honest measured null / no-edge-claimed, and the SPECIFIC next buildable step filed. Per the value bar (and the active owner steer), an honest null reported AS a null WITH the next step filed clears the bar and IS success.
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any tested mechanism; engine_pct unchanged. Real-money brake untouched (no order, no gate flip, no cap change).

## 2026-07-23 — Research Run 29: external-literature re-sweep (mostly reconfirmation) + one genuinely new primary source (NBA/Kalshi underreaction, corroborates EXP-008) + a verified Polymarket/Kalshi official-fee-formula finding. NEW EXP-010 filed. RECOMMEND-only, no code/backtest run, no ROADMAP steer.

**Orientation.** Read RESEARCH_PLAYBOOK.md, RESEARCH_MEMORY.md (tail), ROADMAP.md, VISION.md,
`docs/BUSINESS_CASE.md`, GROWTH_STATUS.md first. Confirmed via `git log` that HEAD (`8e91eac`) is
the 2026-07-22 factory bookkeeping commit for #404/#405/#406 (CUMULATIVE per-category cap + B8
resolved-Kalshi structured-strike capture) — no commits landed since Research Run 28 (yesterday),
so neither of Run 28's two filed factory-build items (the `KalshiHistoryFetcher` `/historical/
markets` extension feeding B8+EXP-009, and EXP-008's live-polling harness) has shipped yet.
Binding constraint unchanged: both real-money mechanisms fully tested to date (bucket-calibration
EXP-002/003/005 across 4 corpora; EXP-006 fade-the-spike, FAMILY-NULL-STRONG 0/60 cells) stay
REFUTED; EXP-008/EXP-009 stay proposed/unbuilt.

**Reconfirmation only (WebSearch, no new evidence, not re-logged as findings).** Le 2026
(favorite-underpricing/calibration-slope), NBER w34702 (Kalshi macro-market calibration by
category), Prediction Arena (arxiv 2604.07355, 6 frontier LLMs autonomously trading Kalshi/
Polymarket, all lost money), and PolyBench all resurfaced with no new numbers beyond what this
file already logs — not re-reported as evidence, per the standing "don't re-parameterize/re-cite
an already-logged finding" discipline. Robinhood MCP re-checked directly (`techcrunch.com`,
`robinhood.com/us/en/support/articles/agentic-trading-overview/`, 2 more sources): the agentic-
trading beta is confirmed STILL stocks-only; "options, crypto, event contracts, futures, and
prediction markets" are explicitly named as planned-not-shipped. A9's gate 1 (availability)
stays unmet — reconfirms, does not change, the existing double-gated ROADMAP entry.

**One genuinely new primary source: arXiv:2606.07811, "When Do Markets Fully Process Public
Information? Evidence from Real-Time Prediction Markets" (Angelini & De Angelis, University of
Bologna).** Verified directly (WebFetch of the arxiv abs page returned the full verbatim
abstract, not a snippet). Studies **1,438 NBA games, 2,876 team-level Kalshi contracts, 409,512
contract-minute observations**, April 2025–May 2026, benchmarked against an out-of-sample logit
win-probability model (score margin/time-remaining/recent-scoring, 5-fold cross-fitted at the
game level). Finding: a 10-percentage-point one-minute move in the benchmark probability produces
only **~6.4pp of contemporaneous Kalshi price movement**; the missing ~3.6pp predicts **several
more minutes of same-direction price DRIFT** (a genuine underreaction/momentum effect — the
OPPOSITE mechanism from the mean-reversion this project's own EXP-006 tested and refuted, so it
is not a re-parameterization of that refuted family). Underreaction is worse in low-liquidity
markets. **Decisive caveat, stated by the paper's own authors, not inferred by us: "executable
returns accounting for bid-ask spreads remain negative even for large gaps."** So this is a real,
academically-documented statistical anomaly that the source paper itself shows does NOT survive
realistic execution costs. This is logged as **corroboration, not a new alpha to build** — it is
a second independent academic primary source (after arXiv:2605.00864's 3.6-second NBA same-market
arbitrage-persistence finding, which already informs EXP-008) reaching the same
execution-infeasibility conclusion on a different Kalshi/NBA dataset via a different mechanism
(underreaction/momentum vs. dutch-book arbitrage). It reinforces EXP-008's standing hypothesis
that this project's 120-second poll cadence structurally cannot compete in fast-moving,
thin-liquidity same-market segments — one more reason EXP-008's pilot (once built) should treat a
low survival rate as the expected, not surprising, result.

**Substantive new finding this run — verified official fee-schedule mismatch (motivates EXP-010).**
`docs/BUSINESS_CASE.md`/VISION.md both name "realistic fees/slippage" as non-negotiable, and
`cost_model.py` documents `DEFAULT_FEE_RATE = 0.02` (a flat 2% of price, applied multiplicatively:
`c_eff = price*(1+slippage)*(1+fee_rate)`) as "Polymarket-style." Directly WebFetched
`docs.polymarket.com`'s fee page (readable text returned, not a PDF/binary failure) — Polymarket's
ACTUAL documented taker-fee formula is **price-dependent and per-category**: `fee = contracts x
feeRate x p x (1-p)` in USDC, with `feeRate` = Politics 0.04, Sports/Economics 0.05, Crypto 0.07,
Geopolitical/world-events 0 (makers pay nothing). This is a fundamentally different SHAPE than
this project's flat multiplicative assumption: it is an ADDITIVE per-contract dollar fee that
peaks at p=0.5 (where, for Sports/Economics/Crypto, it is HIGHER than the flat 2% assumption) and
shrinks toward the price extremes (where it is materially LOWER than 2%) — and the price extremes
are exactly where this project's refuted bucket-calibration family concentrated its signal (the
near-0/1 and extreme-confidence buckets repeatedly named as the concentration risk in EXP-002/003/
005's F10 fragility reports). Kalshi's own fee formula was independently cross-checked (NOT
self-verified against the primary CFTC filing — that PDF failed text extraction, the same
fail-closed issue Run 28 hit on the NBER FEDS PDF) via 3 mutually-consistent secondary sources,
all quoting `fee = round_up(0.07 x contracts x p x (1-p))` — the identical functional shape, a
single flat 0.07 `feeRate` across categories (no per-category variation like Polymarket's).

**Why this could matter, and why it is NOT re-parameterizing a refuted family.** Every prior
refutation (EXP-002/003/005/006) was run under the SAME flat 2%-of-price cost assumption. If that
assumption is, in the specific price region where these strategies traded, more punitive than
Polymarket's real fee, some already-collected, already-refuted results could in principle look
different under the real formula (or could not — the diagnosed problem was signal quality/
concentration, not cost, so a null result here is the more likely honest expectation). This is a
COST-MODEL-REALISM question, not an alpha-mechanism question — VISION's own bar requires realistic
costs, and cost_model.py's docstring explicitly invites updating the rates "when the real venue
fee schedule... is wired." Testing it requires NO new data fetch (the already-committed corpora
from EXP-002/003/005/the concentration-cap runs can be re-scored under a corrected cost model) and
NO egress dependency — the cheapest, most immediately buildable experiment currently on the table
(cheaper than EXP-008's live-wall-clock polling harness or EXP-009's new-fetcher-plus-fresh-corpus
need). Filed as **EXP-010** in GROWTH_STATUS.md `experiments[]` (full spec there).

### Self-validation (data sources this run)
- Le 2026 / NBER w34702 / Prediction Arena / PolyBench: already-logged preprints, re-surfaced via
  WebSearch with no new numbers — not re-cited as new evidence.
- Robinhood agentic-trading status: confirmed directly via `techcrunch.com` (2026-05-27),
  `robinhood.com/us/en/support/articles/agentic-trading-overview/`, and 2 corroborating sources —
  consistent, non-SEO, credible.
- arXiv:2606.07811 (Angelini & De Angelis): WebFetched the arxiv abs page directly — full verbatim
  abstract retrieved, not a summarized snippet. Preprint, not yet peer-reviewed; cannot reproduce
  on our own data (Kalshi in-game NBA tick data is not currently ingested by this project).
- Polymarket fee schedule: WebFetched `docs.polymarket.com` directly — official first-party
  documentation, readable text, formula + a worked numeric example extracted verbatim. High
  confidence.
- Kalshi fee schedule: NOT self-verified against the primary CFTC filing (PDF text-extraction
  failed, fail-closed — no number from that source is relied on). The `0.07 x p x (1-p)` formula
  is reported here only because 3 independent secondary sources converge on the identical formula;
  flagged as secondary-sourced, not primary-verified, and excluded from EXP-010's initial scope
  (EXP-010 targets Polymarket, where the source is primary-verified; a Kalshi analog is a
  follow-on, gated on independently confirming the CFTC filing once it can be read).
- No metric, PnL, or edge is reported from any of the above as a result this project relies on —
  all are DATA motivating a proposed experiment, not a validated outcome.

Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any
tested mechanism; engine_pct unchanged (74). Real-money brake untouched (no order, no gate flip,
no cap change, no code shipped this run — docs-only: this file + GROWTH_STATUS.md).

## 2026-07-23 — Factory build (model/strategy factory): Kalshi `/historical/*` deep-tier fetcher UNBLOCKED (the Run 28 data-access finding, now BUILT + live-validated) + the dollar candlestick-schema fix. First EXP-009 feasibility read: a markedly LESS-calibrated Kalshi employment crowd — a CANDIDATE with headroom, NOT a validated edge. NO edge claimed.

- Hypothesis (falsifiable): n/a — a B8/EXP-009 DATA-ACCESS unblock (owner-steer priority #3) + a leakage-safe crowd-calibration DIAGNOSTIC feasibility read. Claims NO edge, reaches NO revenue field.
- **Context.** Research Run 28 (2026-07-22, RECOMMEND-only) surfaced that Kalshi partitions markets into a rolling ~3-month LIVE tier and a SEPARATE public, unauthenticated `/historical/*` tier that `KalshiHistoryFetcher` did not query — the reason every prior B8/Kalshi probe (07-19c/07-20/07-20c) found the live `status=settled` feed thin (100% recent sports; the deep economics/employment + crypto history is only in the historical tier). Run 28 explicitly filed as a `how_it_could_be_wrong` risk: *"the `/historical/markets` endpoint schema has only been spot-checked … field-level compatibility with the existing `KalshiHistoryFetcher` parser is NOT yet confirmed; a factory build must verify this before trusting any parsed record."* This run BUILT the extension and RESOLVED that risk.
- **SHIPPED #408 (code) — the historical-tier fetcher + a real correctness fix (all live-confirmed via HTTP 200 probes this run, egress open):**
  1. `fetch_resolved_markets(historical=True, series_ticker=…)` pages `/historical/markets` (no `status` filter — that tier serves only resolved markets; passing one returned 0). Live path byte-unchanged.
  2. `fetch_price_history(historical=True)` → `/historical/markets/{ticker}/candlesticks` (the live `/series/.../candlesticks` path **404s** past the cutoff, live-verified on a resolved 2022 `JOBLESS` market), threaded through `to_historical_market`/`build_historical_markets`. Leakage-safety unchanged (a tick is used only when `t ≤ decision` AND `t < resolution`; RAISES rather than fabricating).
  3. **CANDLE DOLLAR-SCHEMA FIX (the Run 28 parser-compatibility risk, now confirmed + closed).** The nested `price`/`yes_ask`/`yes_bid` candle objects carry **dollars** in [0,1] — explicit `*_dollars` keys on the LIVE feed (`{"close_dollars":"0.2200"}`) and bare decimal STRINGS on the HISTORICAL feed (`{"close":"0.6700"}`) — the same `*_dollars` migration #397 first saw on the list feed. The shipped `_candle_price` assumed nested objects are integer cents and divided by 100 unconditionally (encoded against an EMPTY candle list, OA-15 — never real data), so it would have FABRICATED `0.0067` from a real `$0.67` crowd price. Now: an explicit `*_dollars` key is dollars as-is; a bare value `>1.0` is cents/100; a bare value `≤1.0` is dollars if a decimal STRING, cents/100 if a NUMBER — the one signal that keeps a 1¢ legacy tick (number `1`→0.01) distinct from a `$1.00` dollar tick (string `"1.0000"`→1.0). All legacy numeric-cents fixtures preserved; 8 new tests. `volume_fp` fallback (historical serves `volume:null`).
  4. `fetch_kalshi_history.py`: `--historical`/`--series-ticker` flags + `category` in output rows (for B9/EXP-009 per-category diagnostics).
- **BUILDS≠WORKS — end-to-end live validation on REAL data.** Ran the historical fetcher against `KXJOBLESS` (weekly initial-jobless-claims — the Run 28 pre-registered deepest single series, one clean market per release, NOT a correlated strike-ladder): **74 resolved markets fetched** (0 were reachable via the live feed), and leakage-safe `HistoricalMarket` records assembled through the full pipeline. So the parser IS field-compatible with the historical tier (Run 28 risk closed) and the whole leakage-safe assembly works on real multi-year Kalshi history for the first time.
- **First EXP-009 crowd-calibration DIAGNOSTIC read (honest, no fit/PnL — same non-p-hackable class as B9 `per_category_diagnostics`):** at a 2–5 day decision lead, **N≈29–71** (candlestick availability varies), crowd **Brier ≈ 0.18–0.26**, **~6–9% pinned**, prices well-dispersed (sd≈0.25, span 0.10–1.00). On one run (N=29): crowd Brier 0.238 vs base-rate(0.517) Brier 0.250 (the crowd BARELY beats always-guessing the base rate); directional hit-rate 65.5%. This is a **higher-Brier, much-less-pinned** Kalshi employment segment — which is where the NBER paper flags employment mispricing.
- **Why this is NOT an edge, and why a high Brier does NOT even establish miscalibration (the load-bearing honesty — an adversarial auditor's correct catch).** A raw Brier CONFLATES calibration with irreducible outcome uncertainty (Brier = reliability − resolution + uncertainty): a weekly-jobless-claims threshold at a 2–5 day lead with only ~6–9% pinned is an intrinsically near-50/50 outcome, so a Brier near 0.25 (= the always-say-0.5 uninformative baseline) is largely what that base-rate uncertainty FORCES — it does NOT by itself evidence miscalibration or "headroom," and comparing it to Polymarket's ~70%-pinned political markets (many lopsided, low-uncertainty events) is apples-to-oranges. Establishing miscalibration needs a RELIABILITY DECOMPOSITION / calibration curve, NOT run here. And even genuine miscalibration is only exploitable if a MODEL predicts the outcome better than the crowd's ~65% — **untested this run** (no model, no PnL, no B2/F10/F11 gate ran). Two further disclosed fidelity caveats: (a) on illiquid one-sided-book candles (`yes_bid`=0, common on these thin markets) the recorded crowd price falls back to the ASK, biased HIGH — an upper-lean on crowd confidence, not a clean mid (an auditor break, disclosed in-code, not silently changed); (b) the 7-day-lead N collapses to ~2 because these weekly markets open only ~1 week before close, so the usable decision window is 2–5 days. The live corpus is NOT frozen (N/Brier vary run-to-run — the standing "corpora not committed, real numbers taken on documented faith" caveat). Single pre-registered series (KXJOBLESS, named in Run 28's EXP-009 spec BEFORE this measurement — not cherry-picked post-hoc; and this run runs NO fit/PnL/gated test, so there is no select-on-outcome surface).
- **Two-gate readiness:** preflight code GREEN; 46 offline tests (8 new); self-validation green (15 caps, `unmet=[]`); 2 Sonnet reviewers + 3 fresh Opus adversarial auditors (leakage/fabrication, honesty/overclaim, regression/back-compat lenses).
- Verdict: **edge-not-proven** — a real, tested, live-validated data-access unblock + a correctness fix, with an honest measured CANDIDATE (less-efficient crowd) and NO edge claimed. Per the value bar + the active owner steer, an honest null/candidate reported AS such WITH the next step filed clears the bar and IS success.
- **NEXT (pre-registered, do NOT p-hack):** (0) FIRST a RELIABILITY DECOMPOSITION / calibration curve (reliability vs resolution vs uncertainty) on a frozen Kalshi employment corpus, to establish whether the higher Brier reflects genuine crowd MISCALIBRATION or merely irreducible outcome noise — a raw Brier cannot tell them apart, and there is no point building a predictor against a crowd that is uncertain-but-well-calibrated. (1) only if (0) shows real miscalibration, build a genuinely-independent decision-time predictor for weekly initial jobless claims (consensus economist forecast anchor / a simple base-rate-plus-recent-trend model) and run it through B2 + `walk_forward` + F10/F11 against this crowd on a FROZEN corpus, sufficient N (combine KXJOBLESS years + siblings to clear ≥100 independent events), with the concentration cap — only a positive, F11-significant, F10-non-fragile, cost-net result over the floor is an edge. (2) The same `/historical/*` tier now unblocks B8's own filed HISTORICAL co-listed BTC/ETH corpus (Kalshi crypto series via `historical=True`), pairing with the resolved-strike capture (#405) — still one focused unit once a non-trivial co-listed N is confirmed (DECISION COROLLARY). (3) `extract_threshold_from_structured_strike` custom-strike (`strike_type="custom"`) support only if/when a same-event cross-venue match needs it.
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any tested mechanism; engine_pct 74 unchanged. Real-money brake untouched (no order, no gate flip, no cap change).

## 2026-07-24 — Factory build (model/strategy factory): EXP-010 cost-model realism (honest NULL, refutation reinforced) + B8 step iii touch/barrier/terminal semantic classifier. NO edge claimed.

- Hypothesis (falsifiable, pre-registered NULL): EXP-010 — re-scoring the committed leakage-safe OOS corpus (`data/real_oos_corpus_polymarket.json`, N=187) under Polymarket's REAL price-dependent per-category taker fee (`feeRate·p·(1-p)`) instead of the flat 2% will NOT flip the already-refuted CalibrationBucketStrategy verdict to a validated edge (the diagnosed problem was signal quality/concentration, not cost). B8 step iii — a resolution-mechanic classifier + hard-reject gate makes the cross-venue matcher reject same-strike touch-vs-terminal pairs (which can resolve oppositely) without losing genuine matches.
- **EXP-010 RESULT — the predicted NULL, and the refutation is REINFORCED not rescued.** Two cost models on the SAME corpus + SAME strategy + SAME F10/F11 gates, changing ONLY the fee input: flat 2% → 39 trades, net −$3,228.02, F11 significant_NEGATIVE; real Polymarket fee → 42 trades, net −$3,502.27, F11 significant_NEGATIVE. `flip_to_validated_edge=False`. The real fee admits 3 MORE marginal trades (lower fees ABOVE the per-category crossover) yet loses MORE money. Precise arithmetic (correcting the Run 29 shorthand "lower near the extremes"): as a fraction of notional the real fee = `feeRate·(1-p)`, cheaper than the flat 0.02 ONLY above `p > 1 − 0.02/feeRate` (Politics 0.50, Sports/Econ 0.60, Crypto 0.71) and MORE expensive below it — and the committed corpus is longshot-heavy (median price ~0.04), so the real formula is on balance MORE punitive. So the bucket-calibration family is now cost-model-ROBUST refuted, not just refuted under one flat assumption.
- **Why EXP-010 is NOT p-hacking / re-parameterizing a refuted family (the honesty crux, all 3 Opus auditors CANNOT-BREAK).** It changes a COST INPUT that VISION independently requires to be realistic (and `cost_model.py`'s docstring pre-invited wiring the real schedule) — no new strategy config, threshold, or mining. The prediction was pre-registered NULL. A `flip_to_validated_edge=True` would NOT be an edge: the harness surfaces it as a CANDIDATE requiring ≥3 fresh adversarial auditors, and `main()` never auto-promotes it. The unmapped-category fallback rate is the HIGHEST documented (0.07) — conservative (over-states cost), so it can only make an edge HARDER to claim; the fee map is reported transparently (General 57/187 + ScienceTech 3/187 flagged `[FALLBACK]`).
- **What EXP-010 hardens.** Cost realism for every future backtest (the real per-category price-dependent fee is now wired as an opt-in `PolymarketFeeSchedule` on `CostModel`, default None = flat 2% BYTE-IDENTICAL — the pinned walk-forward reproduction hash `b3a8d5e0e9579853` / PnL 910,880.71 is unchanged). A reviewer MUST-FIX (the new `fee_schedule` was missing from `_seed_hash`, so flat vs. real shared a hash despite differing PnL) was caught and fixed through the gate (added-only-when-set; default hash still unchanged; `test_seed_hash_covers_fee_schedule` pins it). New self-validation capability `exp010_cost_realism_rescore` (committed_artifact, no credential, ci_validatable; readiness 15→16). #410.
- **B8 step iii RESULT.** `classify_resolution_mechanic(market)` → `touch|terminal|unknown` from the question text (unconditional path words ever/touch/intraday/at-any-point; colloquial reach/hit/max/min/peak gated to CURRENCY-unit underlyings only — an adversarial-auditor finding that "unemployment hit 5%" is terminal-only and was falsely flipped to touch; terminal cues close/settle/expiry/end-of) PLUS a Kalshi MAX/MIN **ticker** hint (new optional `Market.ticker`, populated by `KalshiClient._parse_market` — the generic-title barrier series KXBTCMAXY/KXBTCMINY carry the mechanic in the ticker, not the title). `match_markets` HARD-REJECTS only a CONFIDENT touch-vs-terminal conflict (tightening-only; unknown on either side is admitted, both-cues-present → unknown never a guess); every match carries `mechanic_confirmed`, and `evaluate_cross_venue_pairs(require_mechanic_confirmed=True)` is the honest edge-claim gate (default off = byte-unchanged). All 42 prior matcher tests pass (+14 new). #411. Moves the B8 blocker fully off semantics onto step (ii): the egress-gated HISTORICAL co-listed BTC/ETH corpus + a common-instant dual-venue snapshot, THEN the dual-venue OOS harness.
- **Two-gate readiness (both PRs, maker≠checker).** preflight code/test/safety GREEN + deterministic reproduction; #410 — 3 fresh Opus adversarial auditors (leakage/determinism/bit-identical; p-hacking/edge-honesty; cost-accounting/live-safety/scorecard) ALL CANNOT-BREAK, 2 Sonnet reviewers (one caught the real `_seed_hash` MUST-FIX, fixed + re-validated ≤1 cycle); #411 — 2 Opus auditors (classifier false-rejection finding + regression/live-safety) + 2 Sonnet reviewers, the false-rejection fixed + re-validated ≤1 cycle.
- Verdict: **edge-not-proven.** EXP-010 is an honest null that hardens cost realism and confirms the bucket family is cost-model-robust refuted; B8 step iii is infrastructure (no edge claim) that unblocks the dual-venue harness. Per the value bar + the active owner steer, an honest null reported AS such WITH the specific next buildable step filed clears the bar and IS success.
- **NEXT (pre-registered, do NOT p-hack):** (1) B8 step (ii) — the egress-gated HISTORICAL co-listed BTC/ETH corpus (Kalshi crypto via `historical=True` #408 + resolved-strike capture #405) + a common-instant leakage-safe dual-venue snapshot; only a non-trivial co-listed N (DECISION COROLLARY) unblocks the dual-venue OOS coherence harness with `require_mechanic_confirmed=True`. (2) EXP-009 step 0 — the Kalshi employment reliability decomposition (still the filed next econ step). (3) A Kalshi analog of EXP-010 only after the CFTC fee filing is primary-verified (secondary-sourced this run, excluded).
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any tested mechanism; engine_pct 74 unchanged. Real-money brake untouched (no order, no gate flip, no cap change).

## 2026-07-25 — Factory build (model/strategy factory): EXP-011 — a SECOND cap parameterization of the recency-weighted bucket grid (honest NULL, reconfirms #388/#404) + 7 ship-critical quality fixes. NO edge claimed.

- Hypothesis (falsifiable, PRE-REGISTERED before any real-data run of this module): EXP-011 — a
  recency-weighted bucket model (`half_life_days=60`, `min_effective_n=30`) tracks a time-varying
  true bucket rate better than EXP-002's all-time average, and combined with the per-category
  concentration caps produces a better-calibrated decision-time probability than the crowd. This
  is the owner-steer **priority #1** item and the RESEARCH_MEMORY **Run 21** recommendation.
- **CORRECTION — what this run is, and what an earlier draft of this entry wrongly claimed.** An
  adversarial auditor proved two framing claims FALSE, and they are corrected here rather than
  quietly dropped. (a) This is **NOT** the first real-data run of the recency-weighted alpha. It is
  the **THIRD**, and all three priors are recorded in THIS file: 2026-07-04 (n=799, "TESTED ONCE ON
  REAL DATA, REFUTED", 108 trades −$914.27); PR #388 (2026-07-19, this SAME 187-corpus, recency
  −$3,444); PR #404 (2026-07-22, the IDENTICAL 6-cell grid). A scout reported "never run on a real
  corpus" and I did not cross-check this file, which answers it three times. (b) "Nothing was
  tuned" was FALSE: #404 ran caps **0.20/0.40**, this run uses **0.10/0.30** — an undisclosed
  researcher degree of freedom. It manufactures no positive (every cell is negative in both
  parameterizations), but the claim as written was untrue.
- **What this run therefore actually is:** a SECOND cap parameterization of an already-run grid —
  a modest, incremental contribution whose value is the negative evidence that **halving both caps
  does not rescue the family either**. #404 cumulative-capped: calibration 35 tr/−$3,040.12,
  recency 3 tr/−$194.22. This run: 27 tr/−$1,684.13 and 3 tr/−$142.69.
- **RESULT — the redesign is REFUTED. 0 of 6 cells positive, 0 of 6 F11 `significant_positive`.**

  | family | lane | trades | net PnL | F11 |
  |---|---|---:|---:|---|
  | static (EXP-002) | uncapped | 39 | −$3,228.02 | significant_negative |
  | static | concurrent cap 0.10 | 39 | −$3,228.02 | significant_negative |
  | static | cumulative cap 0.30 | 27 | −$1,684.13 | insufficient_data |
  | **recency-weighted** | uncapped | 21 | **−$3,443.79** | insufficient_data |
  | **recency-weighted** | concurrent cap 0.10 | 21 | −$2,855.05 | insufficient_data |
  | **recency-weighted** | cumulative cap 0.30 | 3 | −$142.69 | insufficient_data |

- **The headline: recency-weighting makes it WORSE.** ~$164 lost per trade vs the static alpha's
  ~$83 — roughly double, while being *more* selective. Run 21's "the estimate is too stale"
  diagnosis is not supported; making it fresher did not help.
- **Three honesty points, all load-bearing.** (a) The −$142.69 cell is **3 trades**; F11's floor is
  `min_trades=30` so it is `insufficient_data` — that means NO INFORMATION, not "nearly
  break-even". The cap starved the strategy, it did not improve it. (b) Caps are risk controls,
  not alpha: on a net-negative signal capping mechanically shrinks the loss, and that shrinkage is
  not evidence. (c) **The cap test is VACUOUS on this corpus by construction** — a concentration
  cap can only change a verdict where the signal is net-POSITIVE but F10-fragile; here the
  aggregate is negative before any cap applies and the engine itself reports
  `f10_nonfragile_is_vacuous: true`.
- **Anti-p-hacking — what held and what did not.** HELD: `half_life_days=60` /
  `min_effective_n=30` were genuinely never tuned — the auditor verified the module hashes
  IDENTICALLY at every commit that ever touched it, so those constants have not changed since
  2026-07-04. DID NOT HOLD: the **cap values** were changed from #404's 0.20/0.40 without
  disclosure (see the correction above). The p-hacking surface here was the caps, not the decay
  constant. Both are now recorded as out of bounds for re-tuning against this corpus.
- Fully offline + deterministic: replays committed bytes, two consecutive runs byte-identical
  (sha256 `782319e340be80c6…`, committed as `docs/autonomous-loop/EXP011_RESULT.json` so the
  finding does not depend on shell history). An earlier draft quoted a hash the branch could NOT
  reproduce — the run had executed in a shared checkout carrying an unmerged `walk_forward.py`.
  No egress, no credentials, no order.
- **Also shipped this run — 7 file-disjoint quality PRs, all driven by the independent Quality
  Auditor's sub-A ship-critical dimensions** (the one category the owner steer exempts from
  deprioritization): the `_seed_hash`/category reproducibility hole (a same-count category relabel
  shared a hash across a **3.3× PnL divergence**; cap-free hashes byte-identical); the simulation
  pricer's fabricated `vol=0.3`/`T=30/365` override that silently inflated real bets **+37.5%** on
  a path **no test covered**; two timezone-naive parse holes (one a permanent silent scan
  blackout); the entire Metrics tab 404'ing since 2026-07-17; an O(n²) hot loop (**>26×** faster,
  byte-identical output); the frozen corpus's missing provenance sidecar + a misreported
  `decision_lead_days`; and a credential accepted on argv.
- **Two-gate readiness:** preflight code GREEN + runtime harness PASSED + deterministic
  reproduction; 2 Sonnet reviewers + a fresh Opus adversarial auditor. Reviewers caught **four real
  defects** — a fabricated `ROADMAP B2` citation, a vacuous duplicate-timestamp test fixture
  neutralized by `clean_ticks`, cap-active regression tests that produced **zero trades** (so they
  pinned the fix without demonstrating the defect), and a wrong path in a skip message — all fixed
  and re-validated within the ≤2-cycle bound.
- Verdict: **edge-not-proven.** An honest null on the owner's priority-#1 experiment, reported as
  such with the specific next buildable step filed. Per the value bar + the active owner steer,
  this clears the bar and IS success.
- **NEXT (pre-registered, do NOT p-hack):** (1) STOP running cap variants on this corpus — two
  parameterizations now agree and a third would be pure researcher degrees of freedom. The ONE
  thing that would make the cap test informative is a corpus on which the bucket signal is
  net-POSITIVE but F10-fragile. Until such a
  corpus exists, further cap variants on negative-signal corpora are uninformative by construction
  and must not be run as if they were tests. (2) EXP-009 step 0 — the Kalshi employment
  RELIABILITY DECOMPOSITION on a frozen corpus (a raw Brier cannot separate miscalibration from
  irreducible noise). (3) B8 step (ii) — the egress-gated HISTORICAL co-listed BTC/ETH corpus +
  a common-instant dual-venue snapshot, then the dual-venue OOS harness with
  `require_mechanic_confirmed=True`. (4) Market impact/capacity remains untested on real data
  (all 187 frozen records `liquidity: null`).
- Binding constraint UNCHANGED: business_case_strength B, no validated real-money OOS edge on any
  tested mechanism. Real-money brake untouched (no order, no gate flip, no cap change).
