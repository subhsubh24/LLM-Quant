# GROWTH STATUS — LLM-Quant (model / performance)

Re-mapped from the cross-project "growth" shape to a **profit/model** status. Phase
maps: research/backtest → `pre_launch`, paper → `launching`, live → `post_launch`.

**Contract:** the research + alpha method this status is produced under is defined in
[`RESEARCH_PLAYBOOK.md`](RESEARCH_PLAYBOOK.md). Cross-run learning is logged in
[`RESEARCH_MEMORY.md`](RESEARCH_MEMORY.md) — **read it first** each run.

`engine_pct` is pinned to real anchor files; `engine_built == (engine_pct == 100)`.
All metric fields are **real numbers or 0/null — never invented.**

> **YAML quoting contract (F9.1).** Free-text scalar fields — above all `as_of`, and any
> `next_actions[]`/prose item — MUST be **single-quoted** whenever the value contains a
> `: ` (colon-space), a leading `[`/`{`/`&`/`*`/`?`/`!`, or an apostrophe (double it as `''`
> inside single quotes). An unquoted `: ` parses as a nested mapping and the GTM gate fails
> closed — `scripts/validate_gtm.py` now names the exact field/line/hint, but quoting up
> front avoids the stall entirely.

```yaml
GROWTH_STATUS:
  project: llm-quant
  as_of: '2026-07-15 (Research Run 23 -- ran the first-ever real, self-verified PILOT of EXP-006 (political price-reversal after hype spikes): on a diverse, real 16-market sample of Polymarket Politics markets (11 distinct events/topics, not 2024-election-dominated), hourly lag-1 autocorrelation of YES-price changes in the last 14 days before resolution = -0.102, 95% bootstrap CI [-0.1515,-0.0467] EXCLUDES zero, 14/16 markets individually negative -- a real, reproducible, PRELIMINARY corroboration of the reversal/overreaction hypothesis on this project''s OWN data (not just cited literature), but N=16 is far below the 100-event pre-registered floor and this is a raw price-behavior statistic, not a cost-net tradeable backtest. Also discovered (live binary-search, revises Run 21''s cost estimate upward) that CLOB /prices-history enforces a hard ~15-day max interval per call independent of fidelity -- a full-lifetime intraday series needs chunked fetching, not the single call Run 21 spot-checked; this pilot avoided the problem via a single last-14-days call per market. EXP-006 is now formally proposed in experiments[] (status=proposed, not tested) with a full hypothesis/min-N/OOS-plan/costs/pre-mortem, including Run 22''s per-cluster-exposure-cap requirement (a per-trade cap was already proven a no-op). RECOMMEND-only, no ROADMAP steer -- no high-confidence validated edge. Binding constraint unchanged: no validated real-money OOS edge on any tested mechanism to date.)'
  phase: pre_launch
  engine_built: false
  engine_pct: 74   # unchanged (2026-07-04 2nd run, #215/#216/#217): a SAFETY + coverage + artifact run — #215 closed a REACHABLE loss-cap bypass (a bare SELL fabricated a `side="short"` position via the unconditional paper fill; a BUY 'to close' scaled it up recording $0 PnL → the D3/D4 kill switch never saw the loss; reachable via CrossMarketArbitrage's executable SELL in the default scanner); #216 gated the LIVE Monte-Carlo pricing tests (previously ungated); #217 removed the last stock-era render.yaml residue (FRED_API_KEY). Safety/correctness/coverage/artifact convergence, NOT new completeness or a validated edge, so engine_pct does not move. 2 Sonnet/PR + a fresh Opus live-safety auditor SAFE on #215 (2 non-blocking residual caveats: the 1e-9 boundary + legacy short-row remediation — filed for a dedicated follow-up). Prior (2026-07-03 2nd run, #187/#188/#189/#190): a mature-engine HARDENING sweep — WS price_change staleness-honesty guard (#187) + §12 path-param bounds (#188) + F7 api/main.py import hygiene (#189) + §10 dead-code removal (#190). Correctness/security/hygiene/tech-debt convergence, NOT new completeness or a validated edge, so engine_pct does not move. (DEFERRED with a recorded note: the loss-cap-net-of-fees safety fix — verified real at both call sites, awaiting a dedicated run + fresh Opus live-safety audit.) Prior (2026-07-03, #179/#180/#182): the B8 cross-venue coherence matcher + backtest (a CANDIDATE edge, gated off, not validated) + F10 regime-slice wiring into the real-OOS lane + a blocking-gate coverage registration. New alpha-candidate INFRA + anti-overfitting integrity + test coverage — not a validated edge, so engine_pct does not move. Prior (2026-07-01, #116/#117): an INTEGRITY fix (removed a fabricated whale seed + gated two UNVALIDATED strategies out of the default scan behind ENABLE_UNVALIDATED_STRATEGIES, default off) + an A1 stock-era DEAD-CODE removal (legacy db.models stack + yfinance strategy_tester — also kills the stock_prices dual-registration fragility). Both are correctness/honesty/tech-debt work, not new completeness, so engine_pct does not move. No new edge. Prior context (#104): settlement side-effect-integrity fix; (#99-#102): ingest-honesty + §12 hardening.
  venues_connected:
    - polymarket_paper
  awaiting_connect:
    - kalshi
    - polymarket_live
  metrics:
    weekly_pnl_paper: null          # most recent completed eval window, NET USD (realistic costs); dashboard trends this over snapshots
    weekly_pnl_live: null
    weekly_pnl_target_usd: 2000     # the go-live floor ($2K/wk)
    weeks_validated_above_floor: 0  # consecutive OOS paper weeks >= floor (SUSTAINED — not one lucky week)
    hit_rate: null
    brier_calibration: null         # lower is better; must beat the naive crowd baseline
    sharpe: null
    max_drawdown_pct: null
    total_trades: 0
    live_enabled: false
  # The GO signal — when it is safe + proven enough to risk REAL money. DERIVED from
  # the gates, NEVER hand-set: scripts/preflight.sh FAILS if status=eligible without
  # the real proof, so this can't be faked. Even at 'eligible', the OWNER makes the
  # final call (human-core). 'confidence: high' only when ALL criteria hold.
  go_live:
    status: not_ready               # not_ready | eligible
    confidence: none                # none | building | high
    criteria:                       # every one must be true for status=eligible
      validated_weekly_pnl_ge_floor: false        # OOS paper >= floor, realistic costs
      sustained_track_record: false               # >= several consecutive validated weeks (not one lucky week)
      sufficient_sample_size: false               # enough N for significance / tight CI above floor
      calibration_passes: false                   # Brier/reliability eval holds vs crowd
      backtest_reproduces_deterministically: false # same seed -> same PnL
      adversarial_auditors_passed: false          # >= 3 fresh Opus auditors each FAILED to break the edge
      live_path_safe_by_default: false            # caps + kill switch + LIVE_TRADING_ENABLED default off, proven
      runbook_complete: false                     # docs/growth/LIVE_RUNBOOK.md complete
      quality_ship_critical_all_A: false          # every ship-critical quality dim A/A+
      preflight_full_gate_green: false            # scripts/preflight.sh (full) exits 0
    blocking:                       # honest: what's stopping GO right now
      - "No validated out-of-sample edge yet — build the leakage-free, cost-realistic walk-forward backtest + calibration eval (ROADMAP C1-C3, B2)."
    owner_decision_required: true   # even at 'eligible', the human makes the final real-money GO call
  experiments:
    - id: EXP-001
      name: "Real-Data Pipeline + NO Position Scanner OOS Validation"
      status: proposed
      proposed_date: 2026-06-28
      edge_source: "crowd-miscalibration (in-scope per PLAYBOOK)"
      hypothesis: >
        The NO Position Scanner generates positive net EV — Brier improvement vs
        crowd baseline AND positive net PnL after costs — on resolved Polymarket
        binary markets where YES > 90c, on >= 100 resolved markets across >= 3
        categories. Category reversal base rates (politics 2%, economics 3%,
        crypto 8%, sports 5%) are empirically calibrated, not hardcoded fiction.
      min_sample_n: 100
      oos_plan: >
        Chronological 60/40 split: earliest 60% to empirically calibrate reversal
        base rates per category; most recent 40% as true held-out OOS. Significance
        gate: paired bootstrap CI on per-market Brier difference must exclude 0
        (calibration.py B2 gate). Net PnL must be positive after cost_model costs.
      cost_assumptions: "2% fee + 0.5% slippage (cost_model.py); no liquidity model — conservative capacity"
      significance_threshold: "95% CI excluding 0 on paired-bootstrap Brier improvement; Bonferroni correction if testing multiple categories"
      how_it_could_be_wrong:
        - "Reversal rates empirically near-zero -> strategy dead on arrival"
        - "Near-certainty NO books illiquid -> real slippage erases edge"
        - "Survivorship bias in third-party archive excludes contested/re-resolved markets"
        - "N per category < 50 even with 100+ total -> no category-level significance claims"
        - "Market efficiency increasing (43% spread compression) -> historical edge gone in recent months"
      blocking_dependency: "RESOLVED IN CODE: polymarket_history_fetcher.py is built + leakage-safe + fixture-tested (uses Polymarket's OWN public Gamma closed=true + CLOB prices-history — no third-party key needed). REMAINING BLOCKER is now ENVIRONMENTAL: outbound HTTPS to gamma-api.polymarket.com / clob.polymarket.com is egress-blocked (403) in the autonomous build env, so the fetcher can't pull real history here. Run it where Polymarket is reachable (PENDING_OPS OA-11) to populate real HistoricalMarket records."
      factory_next_action: >
        Build polymarket_history_fetcher.py; pull >= 200 resolved markets from
        PMData or PolyHistorical APIs; feed into walk_forward.py; run B2
        calibration eval; report OOS Brier + PnL with bootstrap CI. Only then
        can EXP-001 be declared passing or retired.
    - id: EXP-002
      name: "Horizon-Effect Calibration Bias (7-day decision_lead corpus)"
      status: mechanism-tested-failed
      proposed_date: 2026-06-29
      tested_date: 2026-07-04
      real_oos_result: >
        TESTED on N=510 real leakage-safe 7-day-lead resolved Polymarket records (research
        Run 14, egress open from the research-agent's own environment — see RESEARCH_MEMORY
        2026-07-04). Two independent methods, both negative: (a) full walk-forward PnL:
        46 trades, net -$2,938.70 OOS (seed_hash 40951c0bd2da1ad7), vs crowd baseline
        0 trades/$0; (b) static 60/40 split B2 significance gate: n_test=204 (79 active),
        improvement=-0.00266 (WORSE than crowd), 95% Bonferroni CI (strategies_screened=2)
        = [-0.00585,-0.00016] (entirely negative), passes=False. NOT generalized to "no
        calibration edge exists" -- diagnosed cause: the static bucket average is a LAGGING
        estimate of a possibly time-varying true rate (train-period near-zero-bucket yes_rate
        1.0% vs test-period actual 7.59%), and the volumeNum-selected corpus is biased toward
        the platform's most-arbed all-time-top-volume markets. Full detail + adversarial
        pre-mortem on this result: RESEARCH_MEMORY 2026-07-04.
      edge_source: "crowd-miscalibration + resolution-timing edge (in-scope per PLAYBOOK)"
      hypothesis: >
        Binary Polymarket markets with YES probability 65-90% at 7 days to resolution
        are systematically underpriced vs their empirical resolution rate — the crowd
        under-assigns probability to favorites at early horizons (calibration slope > 1.0,
        per Le 2026 on Kalshi; only ~3% of traders drive price discovery in illiquid
        early-life markets). A CalibrationBucketStrategy that replaces crowd_prob with
        per-bucket empirical resolution rates (fitted from the oldest 60% of a 7-day-lead
        corpus) produces a positive net Brier improvement on the OOS 40%, surviving
        realistic costs (2% fee + 0.5% slippage).
      min_sample_n: 100
      oos_plan: >
        Run fetch_polymarket_history.py with --decision-lead-days 7 (the script default —
        NO code changes needed). Target >= 200 resolved markets. Chronological 60/40 split:
        oldest 60% to fit per-bucket empirical resolution rates; newest 40% as held-out OOS.
        Significance gate: paired bootstrap CI on per-market Brier difference excludes 0
        (B2 calibration.py, Bonferroni if testing multiple buckets). Net PnL positive after
        cost_model costs on the OOS set. Min 30 records per bucket for any bucket-level claim.
      cost_assumptions: >
        2% fee + 0.5% slippage (cost_model.py). At 7-day decision_lead, spreads are wider
        than near-resolution — assume 1-2% additional effective slippage for conservative
        capacity. Target only markets with volume >= $2K at decision time (reduce impact).
      significance_threshold: "95% CI excluding 0 on paired-bootstrap Brier improvement (B2 gate); Bonferroni correction across tested price buckets"
      how_it_could_be_wrong:
        - "Calibration slope effect is Kalshi-specific; Polymarket may already price this in via institutional arbs"
        - "At 7 days, even high-volume markets are mostly pinned on large events — same 70% pinning problem as the 2-day corpus"
        - "Slippage at 7 days materially higher than the 0.5% model — illiquid early-life markets"
        - "Per-bucket fitting overfits with < 50 records per bucket — OOS rates revert to crowd"
        - "The Le 2026 slope=1.32 is at > 1 month, not at 7 days — the slope may be near 1.0 at a 7-day horizon"
        - "Research Run 11 (2026-07-01): a secondary comparative analysis (Calibration City 671K markets + brier.fyi 971 cross-linked markets) reports Polymarket calibration BEATING Kalshi's at close and time-averaged -- the opposite direction needed for a Kalshi-anchored (Le 2026) effect to transfer 1:1 to Polymarket. Non-peer-reviewed and unreproduced by us, but it independently reinforces this pre-mortem item rather than contradicting it -- raises the bar before trusting a Kalshi-shaped finding on Polymarket data."
      blocking_dependency: >
        RESOLVED (2026-07-04, research Run 14) for the research-agent's own environment:
        egress to gamma-api/clob.polymarket.com is OPEN there (unlike the autonomous
        factory build-loop, untested in this run). NOTE: the documented command below
        UNDER-FETCHES -- Gamma's /markets endpoint silently caps each page at 100 rows
        regardless of the requested --limit, so --limit 500 only ever returns page 1's
        100 rows before the fetcher's "short page" heuristic stops paging. Use
        --limit 100 --max-pages N instead (verified: --limit 100 --max-pages 10 yielded
        510 real leakage-safe records). Loop-buildable fix: cap limit to 100 (or compare
        against min(limit,100)) inside fetch_resolved_markets. See RESEARCH_MEMORY
        2026-07-04 finding (2).
      factory_next_action: >
        DONE (research-agent, not the factory): the real 7-day-lead OOS test ran (N=510,
        both methodologies negative -- see real_oos_result above). Do NOT re-run the
        identical config expecting a different answer (that would be p-hacking against the
        same corpus). Candidate NEXT test (not yet run, would need fresh pre-registration):
        a rolling-window (recency-weighted) calibration bucket model instead of an all-time
        static average, to track the apparent time-varying near-zero-price resolution rate
        named in RESEARCH_MEMORY 2026-07-04 finding (3). Also: re-probe the SAME five
        domains (gamma-api/clob/data-api.polymarket.com, huggingface.co, dune.com) from the
        autonomous factory build-loop itself before continuing to treat OA-11/13/16 as
        environment-blocked -- this research run's environment is not egress-blocked, but
        that has not been re-confirmed for the factory's own loop.
    - id: EXP-003
      name: "Domain-Calibrated Political Strategy (Partisan Underconfidence)"
      status: tested-fragile-not-significant
      proposed_date: 2026-06-30
      tested_date: 2026-07-12
      real_oos_result: >
        Research Run 20 (2026-07-12): applied the `tag_id`-resolution lever Research Run 19 validated
        on EXP-005/Sports to EXP-003/Politics, per Run 19's own next_actions recommendation. Resolved
        Gamma's real tag ids for both labels named in the hypothesis ("politics" -> GET
        /tags/slug/politics -> tag_id=2; "elections" -> GET /tags/slug/elections -> tag_id=144),
        live-spot-checked both (5-record GET /markets?tag_id=<id>&closed=true -> genuine 2024
        presidential-nomination markets, Trump/DeSantis/Haley/Biden/Harris) BEFORE the pre-registered
        run. The two tags overlap heavily on this sample, so PRE-REGISTERED tag_id=2 ("Politics", the
        broader parent label) as the single run: `python3 scripts/validate_real_oos.py --tag-id 2
        --decision-lead-days 7 --seed 42 --max-pages 20 --limit 100 --json`, unmodified code, no retry
        after seeing the number. Result: **1,369 leakage-safe Polymarket Politics records** (>3x the
        ~300-400 floor in one fetch, no merge, no code change) -- crowd_brier=0.0886, base_rate=0.2001,
        60.7% pinned (far more pinned than EXP-005's Sports pull, 9.3%). `CalibrationBucketStrategy`
        traded: **472 trades, net +$28,815.49 OOS** (a larger nominal PnL than EXP-005). But **F11
        verdict=indistinguishable_from_zero** (95% CI [-36648.21, 105232.67], spans 0; hit_rate 25.64%
        [21.6%,29.7%], starkly below a coin flip -- worse than EXP-005's already-poor 49.25%) and **F10
        fragile**: 134% of net PnL from one category bucket ('General', 51.6% of budget), 100% from one
        horizon bucket ('3-7d'), 109% from one confidence bucket ('10-25%'), leave-one-out on the top
        category flips the total to -$9,665.99, and 57% of net PnL from ONE single market. EXP-003 is
        now genuinely TESTED (not proposed/blocked-on-corpus-size) and the answer is negative: fragile
        + statistically insignificant, the SAME shape as EXP-005 (large nominal PnL from a sub-50%
        hit rate + extreme concentration). The internal-vs-Gamma category-label mismatch Run 19
        surfaced on Sports is CONFIRMED on this second, disjoint corpus (100% Gamma-tag-Politics, but
        `market_category.py`'s keyword deriver buckets the majority as 'General') -- now a recurring
        classifier limitation, not a one-off. HEADLINE FINDING: combining this result with EXP-002
        (all-categories, N=510, net NEGATIVE) and EXP-005 (Sports, N=814, fragile+insignificant), the
        static bucket-calibration mechanism is now non-robust on 3 independent real per-category
        corpora -- every real-corpus result that traded shows a sub-50% (often far sub-50%) hit rate
        with PnL concentrated in one category/confidence/horizon bucket and often one single market.
        This is a structural property of the MECHANISM (cost-net Kelly sizing on a static per-bucket
        rate systematically finds a few illiquid longshots where the fitted rate exceeds the crowd
        price, bets big via Kelly's low-price convexity, and OOS PnL is dominated by whichever few
        happen to resolve YES) -- not a category-specific finding. A NEW candidate surfaced from
        external research this run (Clinton & Huang, Vanderbilt, N>2,500 political markets / $2B+
        volume, 2024 election: Polymarket political prices show negative daily serial correlation,
        i.e. spikes partially reverse) is structurally DIFFERENT (a timing/overreaction edge, not a
        static price-level bucket) and is logged as candidate EXP-006 -- not yet runnable (needs new
        intraday-price-history infra this repo does not have), not tested this run. Full detail:
        RESEARCH_MEMORY 2026-07-12 (Research Run 20).
      edge_source: "crowd-miscalibration (domain-specific; in-scope per PLAYBOOK)"
      hypothesis: >
        Binary Polymarket markets categorised as "politics" or "elections" are
        systematically MORE underconfident than other categories at ALL decision horizons
        — crowd prices chronically compressed toward 50% via bilateral partisan
        cancellation (Le 2026: dominant calibration component, explains a large fraction
        of the 87.3% calibration variance across 292M trades on Kalshi + Polymarket).
        A CalibrationBucketStrategy fitted EXCLUSIVELY on political-category resolved
        markets produces a positive net Brier improvement on the OOS 40%, with the
        miscalibration robust across decision horizons (unlike the general horizon effect,
        which primarily manifests at >30 days).
      min_sample_n: 100
      oos_plan: >
        (A) PREFERRED — Polymarket-v1 HuggingFace (OA-16): extract daily_aligned Parquet,
        filter to "politics"/"elections" category, reconstruct pre-resolution price
        snapshots at desired decision_lead. (B) ALTERNATIVE — OA-11 with filter (Gamma
        caps each page at 100 rows regardless of --limit, fixed #220; grow via --max-pages):
        python3 scripts/fetch_polymarket_history.py --decision-lead-days 7 --limit 100
        --max-pages 15 --categories "politics,elections" --merge
        --out data/polymarket_history_politics.json
        Chronological 60/40 split. CalibrationBucketStrategy (already built) fitted on
        oldest 60%. B2 significance gate: bootstrap CI excludes 0. Bonferroni correction
        across tested price buckets.
      cost_assumptions: >
        2% fee + 0.5% slippage (cost_model.py). Political markets at 60-90% YES have
        moderate book depth; conservative 1% additional effective slippage assumed.
        Focus on markets with volume >= $2K at decision time to reduce impact.
      significance_threshold: >
        95% CI excluding 0 on paired-bootstrap Brier improvement (B2 gate, strategies_screened=3
        for Bonferroni across EXP-001/EXP-002/EXP-003). Net PnL positive after costs on OOS set.
        Min 30 records per price bucket for any bucket-level claim.
      how_it_could_be_wrong:
        - "Polymarket political user base (international/crypto-native) may not show the same partisan bilateral cancellation as Kalshi's US-regulated base — the Le 2026 effect may be Kalshi-specific"
        - "Only ~10-30 active political Polymarket markets per month — accumulating 100+ resolved markets takes 4-6 months; N is slow"
        - "Political miscalibration may concentrate at >30 days (peak partisan uncertainty) and be near-zero at 7-day horizon (late pinning)"
        - "With <100 political markets, per-bucket N < 30 threshold triggers abstain — strategy produces zero signals"
        - "Le 2026 covers the 2020-2024 US election super-cycle; post-cycle calibration pattern may differ in non-election-year markets"
        - "Research Run 11 (2026-07-01): same cross-platform calibration nuance as EXP-002 -- a secondary source (Calibration City/brier.fyi) reports Polymarket generally BETTER calibrated than Kalshi, which would work against (not for) a Kalshi-anchored political-underconfidence effect transferring cleanly to Polymarket. Unreproduced by us; logged as a reason for caution, not a refutation."
        - "CONFIRMED, not just theorized (Research Run 20, 2026-07-12): at N=1,369 (tag_id=2 Politics, the largest Politics corpus tested), the mechanism produced a large positive headline OOS PnL (+$28,815.49) that a naive read could mistake for a strong edge -- exactly the failure mode this pre-mortem item warned about, and the same shape EXP-005 showed on Sports. F10/F11 caught it: statistically indistinguishable from zero (CI spans 0 by a WIDER margin than EXP-005's) AND a hit rate of 25.64% -- starkly below chance, worse than EXP-005's 49.25% -- AND fragile (134% of PnL from one category, 57% from ONE market, leave-one-out goes to -$9,665.99). Direct evidence the concentration/payoff-lottery risk is real, load-bearing, and now confirmed on 2 of 2 real per-category corpora that reached a tradeable N."
      blocking_dependency: >
        RESOLVED as a data-access question, CLOSED as an edge question (Research Run 20, 2026-07-12):
        `tag_id=2` (Gamma's real "Politics" tag, resolved via `GET /tags/slug/politics`) reached
        N=1,369 in one pre-registered run -- more than 3x the ~300-400 floor, no merge, no code change,
        same mechanism Run 19 validated for EXP-005/Sports. With N no longer the constraint, the
        CalibrationBucketStrategy mechanism was tested and produced a fragile, statistically
        insignificant result (see real_oos_result above) -- so the remaining blocker for EXP-003 is
        no longer DATA, it is that this specific mechanism (static per-price-bucket empirical
        calibration) does not survive F10/F11 on a real Politics corpus either, joining EXP-002 and
        EXP-005 as the same family's 3rd non-robust real-corpus result.
      factory_next_action: >
        No further data-access work needed for EXP-003 specifically (N=1,369 already exceeds the
        pre-registered floor and produced a real, non-fragile-gate-failing result). Per the
        cross-EXP headline finding logged in RESEARCH_MEMORY 2026-07-12 (Research Run 20): a 4th
        category-only re-run of the SAME static bucket-calibration mechanism (e.g. Economics/Crypto
        via their own `tag_id`) is now low expected value -- the mechanism (cost-net Kelly sizing on
        a static per-bucket rate, which systematically concentrates on a handful of illiquid
        longshots) is the suspect, not the category. Higher-value next steps: (a) a
        concentration-capped or recency-weighted redesign of CalibrationBucketStrategy itself; (b) the
        structurally-different EXP-006 candidate (political price-reversal after hype-driven price
        spikes, Clinton & Huang 2025/2026) -- needs new intraday-price-history fetcher infra this repo
        does not have (a genuine factory-build item, not a parameter tweak); (c) the still-open B8
        cross-venue coherence direction. Full detail: RESEARCH_MEMORY 2026-07-12 (Research Run 20).
    - id: EXP-005
      name: "Sports-Category Calibration Bucket (targeting the worst-ECE Polymarket category)"
      status: tested-fragile-not-significant
      proposed_date: 2026-07-08
      tested_date: 2026-07-11
      real_oos_result: >
        Research Run 16 (2026-07-08): fetched 1,095 real leakage-safe 7-day-lead Polymarket
        records (max_pages=20, unmodified polymarket_history_fetcher + validate_real_oos.evaluate(),
        seed=42) -> 134 Sports-category markets (crowd_brier=0.1988, base_rate=0.343, 15.7%
        pinned -- closely reproduces B9's independent 133-market Sports slice from two days
        earlier). CalibrationBucketStrategy made 0 trades; F11 verdict=insufficient_data (NOT a
        measured negative).
        Research Run 17 (2026-07-09): re-ran the IDENTICAL pre-registered config one calendar day
        later (same seed=42, decision_lead_days=7, order=volumeNum, max_pages=20; 387.5s
        wall-clock, no --merge). Result: 2,000 raw resolved markets -> 1,095 leakage-safe (same
        count to the market) -> Sports n=135 (vs 134 the day before, vs B9's 133 two days before
        that) -- three independent same-day-of-week pulls land within +/-2 markets of each other.
        Still 0 trades, F11 insufficient_data (unchanged). DIAGNOSIS SHARPENED (why "fetch more"
        does not fix this, superseding Run 16's "budget more wall-clock" framing): order=volumeNum
        ranks by ALL-TIME cumulative volume, so the top-2,000-by-volume resolved set is dominated
        by long-settled, high-profile historical markets that barely change week to week --
        re-fetching the same order/limit/max-pages re-discovers almost the SAME markets, not new
        ones. This is compounded by, but distinct from, Gamma's pagination ceiling (~offset 2100
        before a 422, unchanged since Run 16) -- even with an unlimited page budget, this
        particular sampling axis is close to exhausted for Sports. CONCLUSION: EXP-005 cannot be
        advanced by re-running the existing single-order fetch with a bigger --max-pages or more
        wall-clock -- that lever is already near-saturated (confirmed empirically, not assumed).
        Growing Sports N requires a DIFFERENT sampling axis (e.g. paginate by recency/createdAt
        instead of volumeNum, or a dedicated per-category/per-series targeted fetch) -- a
        fetcher-design change, not a parameter tweak; this is factory-build scope, not a research-
        agent re-run.
        Research Run 18 (2026-07-10): the "different sampling axis" Run 17 called for turned out to
        be an EXISTING, already-supported `PolymarketHistoryFetcher.fetch_resolved_markets(order=...)`
        value that no script in this repo has ever passed: `order="volume24hr"` (Gamma's trailing-24h
        volume rank) instead of the universally-used `order="volumeNum"` (all-time volume) or the
        fetcher's own already-tried, already-rejected `order="endDate"` default (documented in the
        fetcher's own docstring as surfacing "never-traded junk" with no pre-decision CLOB tick).
        Research-agent scratch run (unmodified `PolymarketHistoryFetcher` + `validate_real_oos.evaluate()`,
        no repo code changes, seed=42, decision_lead_days=7, limit=100, max_pages=20, single run, not
        retried after seeing the number): 1,998 raw resolved markets -> 347 leakage-safe records (a
        LOWER yield than volumeNum's ~1,095/2,000 -- most `volume24hr`-ranked markets are currently
        red-hot/actively-trading and too recently created to have a tick 7 days before their eventual
        resolution, so the leakage guard correctly discards most of them) but a MATERIALLY BETTER
        Sports yield specifically: **Sports n=253** (vs. the volumeNum axis's 133/134/135 across 3
        independent same-config pulls on 07-07/07-08/07-09) -- an 87% N increase from the SAME 20-page
        fetch budget, using an existing CLI-exposed parameter, no fetcher code change. Crowd stats on
        this axis: Sports crowd_brier=0.2227, ECE=0.0745, base_rate=0.435, only 0.8% pinned (far LESS
        pinned than volumeNum's ~16% -- this axis samples currently-live/near-even-money game markets,
        a genuinely different, not-yet-exhausted slice of the market universe). CalibrationBucketStrategy
        STILL made 0 trades on this N=253 corpus; F11 verdict=insufficient_data (unchanged, NOT a
        measured negative) -- 253/10 buckets averages 25.3/bucket even using the full corpus as
        training, still under the min_bucket_n=30 floor for most buckets once walk_forward's expanding
        window shrinks the effective training slice further. So EXP-005 remains untested, but the
        binding sub-constraint (no sampling axis left to grow Sports N) is now FALSIFIED: N materially
        grew in one run via an existing flag, not a new fetcher build. NOT a like-for-like replacement
        for the volumeNum corpus -- the two axes have almost no category overlap in what survives the
        leakage filter (this pull's leakage-safe set had ZERO Crypto/Economics/Politics records of any
        size despite 1,089 raw Crypto markets, vs. volumeNum's 5-category spread), so the honest next
        step is MERGING both axes (dedupe by market_id via the fetcher's existing `--merge` flag), not
        replacing one with the other.
        Research Run 19 (2026-07-11): SUPERSEDES the Run 18 merge recommendation -- found a stronger
        lever instead of executing the merge. `validate_real_oos.py` already ships a `--tag-id`
        server-side Gamma category filter (ROADMAP A7/#295, landed 2026-07-10) but no run had yet
        pointed it at the correct id (Run 17/18 only tried `tag_id=100639`, "Games"). Resolved the
        real id via `GET gamma-api.polymarket.com/tags/slug/sports` -> `tag_id=1` ("Sports"),
        live-spot-checked (5-record `GET /markets?tag_id=1` -> Kings/Raptors NBA-Finals,
        Egypt/Morocco/USA World-Cup -- genuinely Sports) BEFORE the pre-registered run. Single run:
        `validate_real_oos.py --tag-id 1 --decision-lead-days 7 --seed 42 --max-pages 20 --limit 100
        --json`, unmodified code, ~9 min wall-clock, no retry after seeing the number. Result: **814
        leakage-safe Sports records** -- more than double the ~300-400 floor in ONE fetch, no merge,
        no code change (vs. 134/135/253 on the three prior axes). `CalibrationBucketStrategy` FINALLY
        traded: 268 trades, net +$16,993.97 OOS -- but **F11 verdict=indistinguishable_from_zero**
        (95% CI [-17164.66, 49793.75], spans 0; hit_rate 49.25%, at/below a coin flip) and **F10
        fragile**: 125% of net PnL from one category bucket ('General'), 100% from one horizon bucket
        ('3-7d'), 112% from one confidence bucket ('25-50%'), leave-one-out on the top category flips
        the total to -$4,319.43. EXP-005 is now genuinely TESTED (not insufficient-data) and the
        answer is negative: fragile + statistically insignificant, joining EXP-002 and the 4th-run
        HuggingFace/recency-alpha test as another corpus on which the bucket-calibration family fails
        both the significance and concentration bars. Also surfaced (not fixed, not asserted as a
        bug): despite the corpus being 100% Gamma-tag-Sports, this repo's OWN keyword-based
        `market_category.py` deriver labels most of it 'General', not 'Sports' -- the regime-slice's
        category buckets and Gamma's own tag disagree, a labeling-taxonomy gap for a future run.
        Full detail: RESEARCH_MEMORY 2026-07-11 (Research Run 19).
      edge_source: "crowd-miscalibration, category-targeted (in-scope per PLAYBOOK)"
      hypothesis: >
        A CalibrationBucketStrategy fit EXCLUSIVELY on Polymarket's Sports-category resolved
        markets (7-day decision lead) produces a positive, non-fragile (F10), F11-significant
        net OOS PnL -- motivated by B9 (2026-07-07): Sports carries the worst per-category ECE
        (0.091) of 5 Polymarket categories assessed, i.e. the crowd looks least-calibrated there.
        A new, not-previously-tested slice (distinct from EXP-002 "all categories" / EXP-003
        "politics").
      min_sample_n: 100
      oos_plan: >
        Fetch a Sports-only leakage-safe corpus (filter HistoricalMarket.category=="Sports" from
        the existing polymarket_history_fetcher + market_category derivation), pre-registered
        seed + decision_lead_days=7, single run through the unmodified
        validate_real_oos.evaluate() harness (same F10/F11 machinery as EXP-002/B4a). NEXT
        ATTEMPT needs a materially larger Sports-only N (>=300-400, so the dominant price
        buckets can plausibly clear min_bucket_n=30 even inside walk_forward's expanding
        window) -- budget more wall-clock time or accumulate via --merge across multiple runs
        rather than a single large max_pages call (which timed out this run).
      cost_assumptions: "2% fee + 0.5% slippage (cost_model.py); unmodified, moot at 0 trades."
      significance_threshold: "F11 bootstrap CI on total OOS PnL must exclude 0; F10 non-fragile; B2 Bonferroni if screened jointly with EXP-002/003."
      how_it_could_be_wrong:
        - "Sports' high ECE (B9) may be driven by genuinely unpredictable in-game variance (injuries, upsets), not a systematic PRICE-LEVEL miscalibration a bucket model can exploit -- 'least calibrated' does not imply 'beatable by this mechanism.'"
        - "The bucket-calibration family (static + recency) is already CONFIRMED non-robust across 4 general corpora (2026-07-04) -- a Sports-only slice of the SAME mechanism could show the identical sign-instability once N is large enough to trade at all."
        - "Sports markets resolve on short horizons (game-day) -- at a 7-day lead many are still pre-season/early, so the 'least calibrated' signal from B9 (also 7-day lead) may itself reflect thin early-life liquidity rather than a persistent crowd bias worth trading."
        - "Liquidity-selection bias (volumeNum order) still applies -- popular (heavily-arbed) Sports markets dominate the sample."
        - "Research Run 18 (2026-07-10), external corroboration -- Le 2026 (arxiv 2602.19520) Table 3 reports Kalshi-primary (Polymarket cross-validated) sports calibration SLOPE by exact horizon bucket: 0.90-1.10 from 0-48h, 1.04 at 2d-1w (closest bucket to this project's 7-day decision_lead), rising to 1.24 at 1w-1mo and 1.74 only beyond 1 month. Verified via 2 independent WebFetch passes against the paper's own text/table (cross-checked per this project's WebFetch-over-summarization discipline, not taken from a single pass). If this Kalshi-anchored, Polymarket-cross-validated magnitude transfers, sports markets AT ~7 DAYS specifically should be only mildly underconfident (slope~1.04, near 1.0) -- NOT the badly-miscalibrated regime B9's raw Polymarket-only ECE (0.091, later 0.0745 on this run's corpus) suggested. This tempers (does not refute) EXP-005's prior: even with sufficient N, the a priori expected edge magnitude at exactly this horizon may be small. Standard caveat applies: cross-platform/cross-methodology (slope vs. ECE) transfer is unconfirmed, not disproven."
        - "CONFIRMED, not just theorized (Research Run 19, 2026-07-11): at N=814 (tag_id=1 Sports, the largest Sports corpus tested), the bucket-calibration mechanism DID produce a positive headline OOS PnL (+$16,993.97) that a naive read could mistake for an edge -- exactly the failure mode this pre-mortem item warned about. The F10/F11 gates caught it: statistically indistinguishable from zero (CI spans 0, hit_rate below 50%) AND fragile (125% of PnL from one category, leave-one-out goes negative). This is direct evidence the concentration risk named above is real and load-bearing, not hypothetical."
      blocking_dependency: >
        RESOLVED as a data-access question, CLOSED as an edge question (Research Run 19, 2026-07-11):
        `tag_id=1` (Gamma's real "Sports" tag, resolved via `GET /tags/slug/sports`) reached N=814 in
        one pre-registered run -- more than double the ~300-400 floor, no merge, no code change,
        superseding Run 18's "merge volumeNum+volume24hr" plan. With N no longer the constraint, the
        CalibrationBucketStrategy mechanism was tested and produced a fragile, statistically
        insignificant result (see real_oos_result above) -- so the remaining blocker for EXP-005 is
        no longer DATA, it is that this specific mechanism (static per-price-bucket empirical
        calibration) does not survive F10/F11 on a real Sports corpus, joining EXP-002 and the 4th-run
        HuggingFace test as the same family's Nth non-robust result. A different mechanism (not a
        bigger Sports corpus) would be needed to revisit this category.
      factory_next_action: >
        No further data-access work needed for EXP-005 specifically (N=814 already exceeds the
        pre-registered floor and produced a real, non-fragile-gate-failing result). If a future run
        wants to explore Sports further, it should test a DIFFERENT mechanism (not another
        parameterization of the same static bucket-calibration family, which is now confirmed
        non-robust on 3+ independent real corpora incl. this one) or investigate the surfaced
        category-labeling mismatch (Gamma tag_id=1 vs. this repo's `market_category.py` keyword
        deriver disagreeing on what counts as "Sports") if a clean internally-labeled Sports slice is
        wanted for a future EXP. Neither is loop-buildable-and-cheap the way the tag_id fetch was --
        both are genuine design questions, not CLI-flag discoveries. The reusable, higher-value
        takeaway for OTHER categories (e.g. EXP-003 politics): resolve the real `tag_id` via
        `GET /tags/slug/<name>` FIRST, then pass `--tag-id` to `validate_real_oos.py` directly --
        this is now the preferred per-category sampling lever project-wide, ahead of the `order=`
        sort-field workarounds tried in Runs 17/18.
    - id: EXP-006
      name: "Political Price-Reversal After Hype Spikes (resolution-timing / overreaction)"
      status: proposed
      proposed_date: 2026-07-15
      edge_source: "resolution-timing / news-reaction overreaction (in-scope per PLAYBOOK)"
      hypothesis: >
        Polymarket political-market YES prices exhibit negative lag-1 serial correlation in
        SHORT-WINDOW (hourly) price CHANGES during the run-up to resolution -- i.e. a price
        move partially reverses rather than persisting, consistent with herd/hype-driven
        overreaction (Clinton & Huang, Vanderbilt/OSF preprint, N>2,500 political markets /
        $2B+ volume, final 5 weeks of the 2024 US election). A strategy that FADES an
        outsized short-window move (buys the opposite side after a Delta-threshold crossing,
        sized via cost-net Kelly, CAPPED per correlated event-cluster from day one -- see
        how_it_could_be_wrong) produces a positive, F11-significant, F10-non-fragile net OOS
        PnL after realistic costs. Structurally DIFFERENT from the refuted static
        bucket-calibration family (EXP-002/003/005): this is a TIMING edge (does a price
        change predict the NEXT price change), not a price-LEVEL edge (does the crowd
        misprice a price bucket) -- a null result on one family does not predict a null
        result on the other.
      min_sample_n: >
        100 qualifying spike/move events for a real strategy backtest, spanning >=3 distinct
        election cycles/news events (a single-event-dominated sample risks the identical
        single-market/single-cluster concentration failure that sank EXP-003/EXP-005, per
        Research Run 22's per-cluster-exposure-cap finding). The PILOT this run (see
        pilot_probe) used N=16 -- an order of magnitude below this floor; NOT a validated
        test.
      pilot_probe: >
        Research Run 23 (2026-07-15): a pre-registered, read-only PILOT (NOT a formal
        EXP-006 test -- no strategy code, no cost model, no F10/F11 gate) measured the raw
        statistic Clinton & Huang's hypothesis is actually about: lag-1 Pearson correlation
        of HOURLY YES-price changes in the last 14 days before resolution, on a real,
        diverse (not single-election) sample of Polymarket Politics markets (tag_id=2,
        order=volumeNum, first 40 in list order, unmodified `PolymarketHistoryFetcher`,
        seed=42, run once, not retried after seeing the number). Trimmed the final 24h
        before resolution (settlement noise) and any hourly point outside [0.03,0.97]
        (avoid a near-certain tail dominating the correlation). RESULT: 16 of 40 candidate
        markets survived the >=24-point-and-fetch-success filter (24 dropped: 2 HTTP 500s,
        the rest below the point-count floor -- an honest, not cherry-picked, attrition,
        itself a liquidity-selection caveat -- see how_it_could_be_wrong). Mean per-market
        lag-1 autocorrelation = -0.102, 95% market-level bootstrap CI [-0.1515, -0.0467]
        (EXCLUDES zero), 14/16 markets individually negative. Sample spans 11 DISTINCT
        events/topics (2024 Trump/Harris/PA popular-vote, US-Iran peace deal x2, NYC mayor,
        Khamenei, government shutdown, Fed rates x2, Netanyahu, Epstein files, 2x South
        Korea president, Russia-Ukraine ceasefire) -- NOT dominated by the 2024 election
        alone, directly addressing the single-event-concentration pre-mortem flagged in
        Research Runs 20-21. This is the FIRST time this project has measured Clinton &
        Huang's own statistic on ITS OWN real data rather than citing the paper -- a real,
        reproducible, PRELIMINARY corroboration, not a validated edge (N=16 << the 100-event
        floor above; a raw price-behavior statistic, not a cost-net tradeable backtest; the
        QuantPedia mean-reversion cautionary example already logged 2026-07-12 is a direct
        reminder that raw serial-correlation is not automatically profitable after realistic
        transaction costs). ALSO surfaced this run (a genuine, previously-untested infra
        finding that REVISES Research Run 21's "cheap to build on" cost estimate): CLOB
        `/prices-history` enforces a hard ~15-DAY MAX INTERVAL per call, independent of
        fidelity (live-verified via binary search: 12-15 days succeeds, 16+ days fails with
        "startTs/endTs interval is too long" at fidelity 60 AND 1440) -- Run 21's spot-check
        only exercised a single 4-day call, so it missed this cap. A full-market-lifetime
        intraday series (needed for a general spike-detector, not just a last-14-days
        design) therefore needs CHUNKED/paginated fetching (multiple calls per market
        stitched together), raising the real build cost for a general-purpose EXP-006
        detector; this pilot avoided the problem entirely by using a single last-14-days
        call per market (mirroring Clinton & Huang's own "final weeks" focus), which fits
        under the cap in one call.
      oos_plan: >
        NOT YET BUILT (genuine factory-build scope, not a research-agent probe): a
        spike/move-detection function over the (now cap-aware, single-call-per-market or
        chunked) fetchable tick series, a reversal-labeling pipeline, a per-cluster
        (correlated-entity/event-group) notional exposure cap wired in from day one (per
        Research Run 22's finding that a per-TRADE cap is a structural no-op against
        cross-trade correlation), and a walk_forward-integrated causal/rolling backtest
        (this run's pilot statistic is NOT causal/leakage-safe in the trading sense -- it is
        computed with hindsight over the whole window to characterize the PHENOMENON, the
        way an academic paper would, not to simulate a live decision rule). Once built:
        pre-registered spike Delta-threshold + window, >=100 events across >=3 distinct
        cycles, chronological split, F10 regime-slice + F11 bootstrap-significance gates
        (same machinery as EXP-002/003/005), Bonferroni correction if screened jointly.
      cost_assumptions: >
        2% fee + 0.5% slippage baseline (cost_model.py) PLUS a per-CLUSTER (not per-trade)
        notional exposure cap -- Research Run 22 proved a per-trade cap is a no-op when
        concentration comes from many small correlated trades on the same underlying driver,
        which is a live risk here too (multiple markets tied to one news event/spike).
      significance_threshold: "F11 bootstrap CI on total OOS PnL excludes 0; F10 non-fragile (incl. per-cluster, not just per-category/market); Bonferroni if screened jointly with EXP-002/003/005."
      how_it_could_be_wrong:
        - "The pilot's 16-market survivor set is itself liquidity/recency-selected (markets with sparse hourly history in their last 14 days were silently dropped, not fabricated -- but this shifts the sample toward MORE actively-traded markets, which may have different reversal dynamics than the broader universe)."
        - "N=16 is far too small to generalize; a materially larger, differently-sampled pilot could show a smaller or even reversed mean correlation -- this is a preliminary signal, not evidence of a tradeable edge."
        - "Negative RAW price-change autocorrelation does not imply a profitable TRADEABLE reversal once bid-ask spread/slippage on the fade trade itself is charged -- the QuantPedia 'mean-reversion on Polymarket' backtest (logged 2026-07-12) is a direct cautionary example of exactly this gap (best zero-spread variant flips negative at a realistic 10bps cost)."
        - "The July 2024 assassination-attempt spike (N=1 illustration, Research Run 21, 2026-07-13) did NOT reverse -- it persisted/compounded -- showing the largest, most information-laden spikes may behave oppositely from the aggregate weak-reversal statistic; a real detector needs to stratify by spike size/salience, not pool all moves into one test."
        - "This pilot's 14-day-before-resolution window structurally excludes very-early-life price discovery (which may have different dynamics) and markets with <14 days of total life; a full EXP-006 build must decide whether to stay scoped to 'final weeks' (mirroring the primary source) or generalize."
        - "A per-cluster exposure cap (the mitigation Research Run 22 said a working redesign needs) has no existing implementation in this repo to reuse -- it is a genuinely new, unbuilt risk-engine primitive, not a parameter tweak, for BOTH EXP-006 and any future bucket-calibration redesign."
      blocking_dependency: >
        Not a data-access blocker (the pilot proves the raw primitive is usable, with the
        newly-discovered 15-day-per-call cap now characterized). The blocker is BUILD SCOPE:
        a spike-detector + reversal-labeler + per-cluster exposure cap + causal walk_forward
        integration, none of which exist in the repo today -- genuine factory-build work, not
        a research-agent re-run.
      factory_next_action: >
        If prioritized: build the spike-detection + reversal-labeling pipeline against the
        now-cap-aware fetch pattern (single call per market when the pre-registered window
        is <=15 days, else chunked calls), wire a per-cluster exposure cap (correlated
        event-group detection, e.g. same election/same underlying entity) from day one (not
        added post-hoc, per Run 22's no-op finding), and integrate into walk_forward for a
        real causal/leakage-safe OOS test against a pre-registered >=100-event, >=3-cycle
        sample. RECOMMEND-only (this run) -- no ROADMAP steer; the pilot is preliminary,
        not a validated edge.
  learnings:
    - "Research Run 23 (2026-07-15): ran a pre-registered, read-only PILOT of EXP-006 (political
      price-reversal after hype spikes) -- the first time this project measured Clinton & Huang's
      own statistic (lag-1 serial correlation of price CHANGES) on its own real data instead of just
      citing the paper. Universe: Polymarket Politics (tag_id=2, order=volumeNum, first 40 candidates
      in list order, unmodified fetcher, seed=42, run once). Window: hourly YES-price ticks in the
      LAST 14 DAYS before resolution (trimmed final 24h + any point outside [0.03,0.97]). 16 of 40
      candidates survived (24 dropped: 2 HTTP 500s, rest below the 24-point floor -- honest
      attrition, itself a liquidity-selection caveat) spanning 11 DISTINCT events (not just the 2024
      election): mean per-market lag-1 autocorrelation = -0.102, 95% market-level bootstrap CI
      [-0.1515,-0.0467] (excludes zero), 14/16 markets individually negative. A real, reproducible,
      PRELIMINARY corroboration of the reversal hypothesis -- explicitly NOT a validated edge: N=16
      is far below the 100-event floor this run also pre-registers for a real EXP-006 test, and this
      is a raw price-behavior statistic (computed with hindsight over the whole window, NOT a
      causal/leakage-safe trading rule), not a cost-net tradeable backtest. SEPARATE, more durable
      infra finding this run: live binary-search discovered CLOB `/prices-history` enforces a hard
      ~15-DAY MAX INTERVAL per call, independent of fidelity (12-15 days succeeds, 16+ fails with
      'interval is too long' at fidelity 60 AND 1440) -- Research Run 21's 'the intraday primitive is
      cheap to build on' claim only spot-checked a single 4-day call and missed this cap; a
      full-market-lifetime spike detector needs CHUNKED/paginated fetching, raising the real EXP-006
      build cost. This pilot sidestepped the cap by using one single-call last-14-days window per
      market (mirroring Clinton & Huang's own 'final weeks' focus). EXP-006 is now formally added to
      experiments[] as status=proposed (NOT tested) with a full falsifiable spec (hypothesis, N=100
      floor across >=3 distinct cycles, OOS plan, cost assumptions incl. Run 22's per-CLUSTER
      exposure-cap requirement, and a 6-item adversarial pre-mortem incl. the QuantPedia
      cost-fragility cautionary example and the July-2024-assassination-attempt N=1 non-reversal
      counter-illustration). External web research this run (favorite-longshot bias magnitude,
      cross-venue arb compression, calibration benchmarks) surfaced only non-academic/SEO-grade
      sources restating findings already verified against primary sources in prior runs (Whelan,
      Le 2026, arb-speed-dominance) -- logged as redundant DATA, not new evidence, no new claim.
      RECOMMEND-only, no ROADMAP steer (no high-confidence validated edge). Binding constraint (no
      validated real-money OOS edge) STANDS. Full detail: RESEARCH_MEMORY 2026-07-15 (Research Run 23)."
    - "Research Run 20 (2026-07-12): EXP-003 TESTED for the first time (was proposed/corpus-blocked
      since 2026-06-30) — applied the SAME `tag_id`-resolution lever Run 19 validated on Sports
      (resolved Gamma's real \"Politics\" tag id, `tag_id=2`, via `GET /tags/slug/politics`, per Run
      19's own next_actions recommendation) in one pre-registered run: N=1,369 leakage-safe Politics
      records (>3x the ~300-400 floor, no merge, no code change). `CalibrationBucketStrategy` traded
      (472 trades, net +$28,815.49 OOS) but F11 significance=indistinguishable_from_zero (95% CI
      [-36648.21, 105232.67], hit_rate 25.64% — starkly below chance, worse than EXP-005's 49.25%)
      AND F10=fragile (134% of PnL from one category bucket ['General' — the internal
      market_category.py-vs-Gamma-tag label mismatch Run 19 found on Sports is now CONFIRMED on this
      second corpus too], 57% of PnL from ONE market, leave-one-out flips the total to -$9,665.99) —
      NOT a validated edge, joining EXP-002 and EXP-005 as a 3rd real-corpus test the bucket-
      calibration family fails. HEADLINE FINDING: across all 3 real-corpus tests that reached a
      tradeable N (EXP-002 all-categories N=510 net negative; EXP-005 Sports N=814 fragile;
      EXP-003 Politics N=1,369 fragile), the mechanism itself — not the category — is now the
      suspect: cost-net Kelly sizing on a static per-price-bucket rate systematically concentrates on
      a handful of illiquid longshots, producing a large-looking nominal PnL from a sub-50% hit rate
      that F10/F11 correctly reject every time. Recommendation (RECOMMEND-only — a negative finding,
      no ROADMAP steer warranted): further category-only re-runs of this exact mechanism are low
      expected value; higher-value next steps are a concentration-capped/recency-weighted redesign,
      the newly-surfaced EXP-006 candidate below, or B8 cross-venue coherence. External research this
      run (checked directly, not just summarized): Clinton & Huang (Vanderbilt, OSF preprint,
      N>2,500 political markets/$2B+ volume, 2024 election) reports Polymarket political prices show
      negative daily serial correlation (price spikes partially reverse) — a structurally DIFFERENT,
      in-scope (resolution-timing/overreaction) candidate, logged as EXP-006 (not yet runnable — needs
      new intraday-price-history fetcher infra this repo does not have, a genuine factory-build item).
      Adversarially cross-checked a QuantPedia \"Polymarket mean-reversion\" backtest that superficially
      looks like corroboration for EXP-006 — it is NOT: N=3 novelty markets, a 12-variant-per-asset
      search (severe multiple-comparisons risk), and the best zero-spread result FLIPS NEGATIVE at a
      realistic 10bps cost — logged as a cautionary example for EXP-006's own build, not supporting
      evidence. Also this run: a new operational finding (not a correctness bug) — Kalshi's
      candlesticks endpoint rate-limited heavily under this run's batch fetch (854x HTTP 429, 1,200
      Kalshi markets honestly skipped rather than fabricated) — logged for a future Kalshi-OOS-focused
      run, out of scope here (the `--tag-id` flag is Polymarket-only; the Politics result is
      unaffected). Egress reconfirmed open (gamma/clob/data-api.polymarket.com, huggingface.co 200;
      dune.com still 403). Binding constraint (no validated real-money OOS edge) STANDS. Full detail:
      RESEARCH_MEMORY 2026-07-12 (Research Run 20)."
    - "Research Run 19 (2026-07-11): EXP-005 TESTED for the first time (was insufficient-data since
      2026-07-08) — resolved Gamma's real \"Sports\" tag id (`tag_id=1`, via `GET
      /tags/slug/sports`; prior runs had only tried `tag_id=100639` \"Games\") and ran the ALREADY-
      SHIPPED `validate_real_oos.py --tag-id` flag (#295, landed 2026-07-10 but not yet exercised
      against the correct id) in one pre-registered run: N=814 leakage-safe Sports records (more
      than double the ~300-400 floor, no merge, no code change — supersedes Run 18's \"merge
      volumeNum+volume24hr\" plan). `CalibrationBucketStrategy` finally traded (268 trades, net
      +$16,993.97 OOS) but F11 significance=indistinguishable_from_zero (95% CI spans 0, hit_rate
      49.25%) AND F10=fragile (125% of PnL from one category bucket, leave-one-out flips the total
      negative to -$4,319.43) — NOT a validated edge, joining EXP-002 and the 4th-run
      HuggingFace/recency-alpha test as another corpus on which the bucket-calibration family fails
      both bars. Also surfaced (not fixed): this repo's internal `market_category.py` keyword
      deriver disagrees with Gamma's own Sports tag on most of this corpus (labels it 'General'),
      a taxonomy gap for a future run, not asserted as a bug. Reusable project-wide takeaway: resolve
      a category's real Gamma `tag_id` via `GET /tags/slug/<name>` and pass `--tag-id` directly —
      now the preferred per-category sampling lever, ahead of the `order=` sort-field workarounds
      tried in Runs 17/18 (directly applicable to EXP-003 politics next). External research this
      run (DATA only, no new EXP): cross-venue arb windows reported compressing to ~30s in 2026
      (vs ~5min in 2024, non-academic industry sourcing) — reinforces, does not change, the standing
      out-of-scope conclusion; UMA oracle dispute rates reported rising sharply in 2026 (1,150+
      disputes, WSJ-sourced via secondary reporting, not independently fetched) — logged as a
      growing selection-bias caveat on this project's \"cleanly-resolved-only\" corpora, not a new
      alpha; a second maker-taker paper (Palumbo 2026, Kalshi NFL orderbook, ~$29M/season to LPs who
      DON'T flatten inventory) corroborates, does not change, the standing market-making deferral.
      Binding constraint (no validated real-money OOS edge) STANDS. Full detail: RESEARCH_MEMORY
      2026-07-11 (Research Run 19)."
    - "Research Run 18 (2026-07-10): EXP-005 sampling-axis fix found + tested — `order=\"volume24hr\"`
      (an existing, already-supported PolymarketHistoryFetcher parameter no script in this repo had
      ever passed) grew the leakage-safe Sports-category corpus from N=135 (the volumeNum axis,
      confirmed exhausted across 3 independent same-config pulls on 07-07/07-08/07-09) to N=253 in a
      single fetch — an 87% increase, zero fetcher code changes, reproducible via
      `fetcher.fetch_resolved_markets(order=\"volume24hr\")` (research-agent scratch script, not
      committed; the unmodified `PolymarketHistoryFetcher` + `validate_real_oos.evaluate()`, seed=42,
      decision_lead_days=7, limit=100, max_pages=20, single run, not retried after seeing the number).
      This REVISES Run 17's diagnosis that closing this gap needed a fetcher-DESIGN change — it needed
      only a parameter no one had tried. CalibrationBucketStrategy still made 0 trades at N=253 (F11
      insufficient_data, not a measured negative — 25.3 avg records/bucket is still below the
      min_bucket_n=30 floor before walk_forward's expanding window shrinks it further), so EXP-005
      remains untested, not refuted. The volume24hr and volumeNum axes are near-disjoint in category
      composition (this pull surfaced 0 leakage-safe Crypto/Economics/Politics records despite 1,089
      raw Crypto markets, vs. volumeNum's 5-category spread) — recommended next step (loop-buildable,
      no code change) is MERGING both axes via the fetcher's existing `--merge` CLI flag to push
      Sports N toward the ~300-400 floor. Separately, cross-checked (2 independent WebFetch passes)
      Le 2026's (arxiv 2602.19520) exact per-horizon sports calibration table: slope is only 1.04 at
      the \"2d-1w\" bucket closest to this project's 7-day decision_lead (vs. 1.74 beyond 1 month) —
      external, Kalshi-primary/Polymarket-cross-validated evidence that TEMPERS (does not refute)
      EXP-005's expected edge magnitude even once N is sufficient. Also this run: confirmed (2
      independent sources) the already-logged \"GWU/UCD 2026\" maker-taker lead is CEPR DP20631 /
      GWU working paper 2026-001 (Kalshi-only, 300K+ contracts) — quantifies (does not newly discover)
      makers earning higher average returns than takers with both showing a favorite-longshot pattern;
      no new EXP, still deferred (market-making complexity, out of current scope) per the 2026-06-30
      decision. Cross-venue Polymarket/Kalshi arb reconfirmed bot/speed-dominated (public sources cite
      ~25ms execution, 30s windows) — no change to the standing out-of-scope conclusion. Egress
      reconfirmed open (gamma/clob/data-api.polymarket.com, huggingface.co 200; dune.com still 403;
      api.elections.kalshi.com root 404 as expected, unauthenticated path not probed this run). No new
      EXP-00N proposed; binding constraint (no validated real-money OOS edge) STANDS. Full detail:
      RESEARCH_MEMORY 2026-07-10 (Research Run 18)."
    - "Research Run 17 (2026-07-09): SELF-VALIDATION — the factory's #267 fix (`check_resolutions()`
      now returns a settled-count summary instead of falling off the end) is CONFIRMED live and
      trustworthy, not just merged: directly read 2 post-fix `live-validation.yml` job logs
      (2026-07-09T04:16 run 28993644145, 2026-07-09T09:59 run 29010084415), both report
      `\"resolutions\": 0` as a real integer (not the structural `null` Research Run 16 diagnosed
      as dead code). This upgrades Run 16's \"resolution count is UNKNOWN\" back to \"CONFIRMED
      real zero\" — a materially more precise, more trustworthy state than either extreme. Still
      genuinely ZERO settled positions after 11+ days of OA-17 operation; bankroll continued
      shrinking ($102.87 on 07-05 → $72.83 on 07-09) as capital sits in unresolved positions.
      Sports ($152.75) and General ($211.00 — itself now over its own $200 cap, plausibly MTM
      appreciation of open longshot positions rather than a bug) categories remain saturated,
      freezing new deployment — same D2-cap-working-as-designed diagnosis as Run 15 (2026-07-05),
      now resting on a trustworthy signal instead of an assumption. No action recommended (not a
      bug); keep watching for the first real resolution now that the telemetry can actually show
      one. Also this run: EXP-005 (Sports-category CalibrationBucketStrategy) re-tested with the
      identical pre-registered config one day after Run 16 — Sports N replicated at 135 (vs 134,
      vs B9's 133) — and the diagnosis was SHARPENED: the volumeNum sampling axis is near-static
      week-to-week (re-fetching re-draws almost the same all-time top-volume set), so \"budget more
      wall-clock / bigger --max-pages\" (Run 16's framing) will NOT grow Sports N — a genuinely
      different sampling axis (recency-ordered fetch, or a per-category paginator) is needed, which
      is a factory-build task, not a research-agent re-run. Egress reconfirmed open (gamma/clob 200,
      dune.com still 403). The \"Yes Bias in mention markets\" SSRN lead (Deleep et al.) remains
      unverifiable — 2 more secondary sources checked (advancedinvesting.org, QuantPedia), neither
      discloses N/magnitude; a tangential sports-forecasting paper (Goto 2026, arXiv 2604.17194,
      FL-GLM on 90,014 bookmaker-odds football matches) was checked and ruled out — different asset
      class (fixed-odds bookmakers, not prediction-market crowd prices), no transferable magnitude.
      No new EXP-00N proposed; binding constraint (no validated real-money OOS edge) STANDS. Full
      detail: RESEARCH_MEMORY 2026-07-09 (Research Run 17)."
    - "Research Run 16 (2026-07-08): URGENT — `MarkToMarketEngine.check_resolutions()`
      (orchestrator.py:322-485) has NO return statement (always implicitly returns None), so
      `run_paper_cycle.py`'s `\"resolutions\"` JSON field has been structurally incapable of
      ever showing non-null since OA-17 went live — independent of whether positions actually
      resolved. Compounding: `grep -rn basicConfig backend/ scripts/` = ZERO matches anywhere in
      this codebase, so the root logger has no handler and Python's `logging.lastResort` silently
      discards every INFO-level log (incl. the one `[MTM] Position resolved` line that would
      prove a resolution fired) — confirmed by cross-referencing 9+ live-validation.yml logs
      (2026-07-02→07-08): a sibling WARNING-level line (`persistence.py:256`, legacy-short
      rehydration) DOES appear in every log; the INFO-level MTM line appears in NONE. Both bugs
      are REPORTING-only (the underlying persist/PnL/position-removal side effects are untouched
      by either) but together they mean Research Runs 12/13/15's \"still zero resolutions, just
      elapsed time\" diagnosis was reading a signal that could never have shown otherwise even if
      resolutions WERE accumulating. Reclassify the forward-paper resolution count as UNKNOWN,
      not ZERO, until fixed (loop-buildable: (a) `check_resolutions()` should return a summary;
      (b) add `logging.basicConfig(level=logging.INFO)` at the `run_paper_cycle.py` entrypoint).
      Also this run: EXP-005 (Sports-category CalibrationBucketStrategy, targeting B9's
      worst-ECE category) — insufficient data at N=134 (mechanism correctly abstained, every
      price bucket below min_bucket_n=30; needs a much larger Sports-only fetch next attempt,
      budgeted for more wall-clock time). Egress reconfirmed 5/6 open (dune.com still 403). A
      WebFetch-summarized \"Yes Bias mention-market, 10pp overpricing, N=1447\" claim was
      CROSS-CHECKED against the paper's real abstract and found to be an over-summarization, not
      a verified figure — logged as a methodology caution, not a new finding. Full detail:
      RESEARCH_MEMORY 2026-07-08 (Research Run 16)."
    - "Factory run (2026-07-05, 2nd): B8 cross-venue coherence RESOLVED-history feasibility PROBE (deeper than the 1st run's live-list probe; egress open). 500 resolved Polymarket markets by volume → 15 numeric-threshold (BTC/ETH TOUCH); 3000 settled Kalshi markets via the general /markets list → 0 clean single numeric-threshold binaries (dominated by KXMVECROSSCATEGORY multi-leg concatenated combos → matcher correctly refuses). Kalshi HAS 254 crypto series but reachable ONLY per-series with strikes in STRUCTURED cap_strike/floor_strike fields (not the title text extract_threshold parses), AND a SEMANTIC mismatch: Kalshi KXBTCMAXY=barrier / KXBTCD=terminal vs Polymarket=touch → same asset, different resolution mechanics. So B8 is a multi-run data-eng effort (per-series discovery + structured-strike parser + touch/barrier-vs-terminal classification + curated numeric universe), NOT runnable this run; NOT built (speculative infra per DECISION COROLLARY). Binding constraint (no robust alpha) STANDS. Probe reproduced/deepened the 1st run's finding — no fake result."
    - "Factory run (2026-07-05, 2nd): #238 (A2/A5) — volume/liquidity finiteness guard. A malformed 'nan'/'inf' volume coerces through float() but NaN<min_volume is False, so a no-real-volume market PASSED the strategy BUY-gate filter (Market.volume_below() returns False on NaN) — the same invented-data-into-the-decision class the Quality Auditor graded ship-critical for fabricated volume=10000 (#165). Prices were already math.isfinite-guarded; this closed the volume/liquidity asymmetry (polymarket_client._parse_market never assigns a non-finite; kalshi_client._to_float rejects non-finite). 6 regression tests proven fail-pre-fix in the already-gated suites. 2 Sonnet reviewers first-pass APPROVE (both reverted the source to confirm the decision-flip). Ingest honesty on the live scan path; no DoD/floor box (not a validated edge). QUALITY-GRADE-RECONCILE: the scorecard's functional_reality=B (#165, strategies.py:1451-1457) is ALREADY FIXED in code (#203, _volume_unavailable guard) — the scorecard is stale, not open; sole ship-critical gap is business_case_strength=B (no validated OOS edge = the binding constraint)."
    - "Research Run 15 (2026-07-05): the forward-paper track record (OA-17) is STILL at zero
      resolutions two days after Research Run 13's diagnosis — confirmed directly via 6
      live-validation.yml job logs spanning 2026-07-03T04:12 to 2026-07-05T09:24 UTC (all
      'resolutions': null, 'executions': []; FK persistence bug NOT recurred). Diagnosis updated:
      this is NOT the 2026-07-02 empty-category bug (categories now derive correctly — Sports,
      General, a named Bitcoin market) — bankroll fell to $102.87 and sits flat because the Sports
      category's $200 sub-cap is genuinely SATURATED by real FIFA World Cup position concentration,
      while non-Sports opportunities scanned each run hit Kelly size=0 (no edge, honest). This is
      the D2 diversification cap working as designed under a mostly-deployed small bankroll, not a
      bug — no fix recommended. The binding constraint for real evidence remains simply elapsed
      time until shorter-dated 2026-07-02/03 positions (Fed decision, MLB, esports, an Elon
      tweet-count window, a within-2-weeks Iran deadline) resolve and free capital. SEPARATELY:
      reconfirmed, at 5x the sample size (n=1000 vs the same-day factory B8 probe's n=200), that
      Kalshi's public /markets LIST endpoint returns ZERO markets with any populated yes_bid/
      yes_ask/last_price field — this is a structural gap in the bulk list endpoint (not
      small-sample bad luck), sharpening B8's next-step diagnosis toward a per-market quote/
      orderbook call or the already-fixed candlestick path (OA-15), not further list-endpoint
      iteration. NEW CANDIDATE (unverified, no EXP number assigned): 'How Wise is the Crowd? Bias
      and Edge in Prediction Markets' (Deleep et al., SSRN ~March 2026, via a QuantPedia
      review — primary paper 403'd, no N/magnitude disclosed) proposes a 'Yes Bias' concentrated in
      low-liquidity, near-resolution 'mention markets' (narrative/commentary contracts), driven by
      narrative conviction rather than price level — structurally different from the refuted
      price-bucket family, so a null result there doesn't predict a null result here. Needs a
      mention-market classifier (doesn't exist yet) before it is testable; logged as a future
      candidate only, per the 'don't formalize on an unreachable source' discipline. Full detail:
      RESEARCH_MEMORY 2026-07-05 (Research Run 15)."
    - "Factory run (2026-07-05): B8 cross-venue coherence — the pre-registered #1 next candidate — was PROBED on real live data (547 Polymarket + 200 Kalshi binary markets) and does NOT validate this run. find_cross_venue_matches produced 33 candidate pairings, ALL false (sports/player-name token overlap, no numeric threshold) + ALL below the 0.5 trade bar (max coherence 0.375) → ZERO tradeable matches (the matcher's conservatism correctly refuses false pairs). ROOT BLOCKER: the Kalshi /markets LIST endpoint returns NO usable quotes — all 200 open markets parsed active=False with a uniform 0.500 placeholder + garbled multi-outcome concatenated question text (multi-leg sports, not clean binaries). B8 next needs (a) a Kalshi quote source with real prices (per-market quote fetch OR the #170 candlesticks path) + clean single-event questions, and (b) a targeted NUMERIC-THRESHOLD universe (BTC/Fed/econ) co-listed on both venues — a multi-run data-eng effort, NOT a one-run validation. The probe surfaced + shipped a REAL fix (#232): the matcher's _yes_price now gates on market.active so an untradeable market's 0.500 placeholder can't feed a fabricated cross-venue disagreement (the #101/#102/#193 fake-price class). No edge validated; binding constraint (no robust alpha) STANDS."
    - "Factory run (2026-07-05): F10 category-threading COMPLETE (#231) — real per-market categories are now threaded end-to-end (3 resolved-history fetchers derive via market_category.derive_market_category → HistoricalMarket/BacktestTrade → validate_real_oos.category_by_market_id), so F10's analyze_regime_slices CATEGORY-concentration + leave-one-out checks fire on real OOS trades (they were always category_by_market_id=None before). category is _seed_hash-EXCLUDED metadata → the pinned real-data reproduction hash 8dc358439ffb5746 is unchanged (a dedicated invariance test pins it). Anti-overfitting integrity infra; not a validated edge (no DoD/floor box)."
    - "Bootstrap: prediction-markets engine runs in paper/dry-run; no validated out-of-sample edge yet."
    - "Kill switch exists in execution.py; LIVE_TRADING_ENABLED master gate added (default false)."
    - "A1 complete: stock/crypto engine + data/AI routes + ML stack + stock frontend retired; asset-agnostic infra kept; ~2GB+ leaner deploy (torch/xgboost/lightgbm dropped)."
    - "D3/D4 done: hard daily/total loss caps enforced at the execution gate + kill-switch auto-trip on breach (incl. the resolution loss path). Verified by harness + 2 fresh auditors."
    - "C2 cost-aware Kelly: sizing now uses cost-NET edge — prior gross-edge sizing systematically over-bet AND over-traded (took trades with negative net edge after fees+slippage). Honest costs LOWER turnover/sizing — correctly."
    - "C1/C3 walk-forward ENGINE built (prediction_markets/walk_forward.py): leakage-free by construction (decision sees no outcome; training only resolves pre-window), event-driven capital accounting (no over-deployment), cost_model costs, deterministic seed_hash. Proven on synthetic data to recover a known edge + report ~0 on no-edge. NOT a validated edge — no real resolved-market data yet, so no floor/DoD box ticked."
    - "B2 calibration eval built (calibration.py): Brier+reliability+ECE with a SIGNIFICANCE gate (paired bootstrap CI must exclude 0). A raw Brier point comparison passed ~21% of pure-noise strategies at N=30 (adversarial-audit finding); the bootstrap gate collapses that to <=1.2%. Honest: measures calibration-vs-crowd, not tradeable edge."
    - "A5 data-quality gates wired into the scan loop (data_quality.py): completeness/price-sanity catch None/NaN/inf/out-of-range/sum-violations; staleness fires via end_date expiry. Bad markets skipped before sizing; valid markets never skipped."
    - "C5 weekly-metrics aggregator (weekly_metrics.py): pure deterministic weekly PnL/Sharpe/hit-rate/max-drawdown from real realized trades. C2 unify done: execution.py sources its fill rates from cost_model (drift fails loud)."
    - "A2 resolved-history fetcher BUILT (polymarket_history_fetcher.py): leakage-safe ingest of real resolved markets + a PRE-resolution price snapshot into HistoricalMarket. The settled outcomePrice is NEVER used as the decision price; raises rather than fabricating; timeout/max-pages-bounded; discloses selection/survivorship bias + late-life pinning. 3 Opus auditors CANNOT-BREAK-LEAKAGE. This RESOLVES the named code blocker for OOS validation — but the autonomous env's EGRESS POLICY blocks Polymarket (403), so the real fetch is now a human-core step (OA-11)."
    - "C2/C3 market-impact model BUILT (cost_model.effective_buy_price_with_impact, applied in walk_forward): simplified conservative sqrt-impact, floored at the flat rate, capped at 1.0, deployed==budget to machine epsilon (no double-count); thin books strictly worsen PnL. seed_hash now covers liquidity+impact_coeff. Honestly a non-calibrated toy. 3 Opus auditors CANNOT-BREAK."
    - "G3 audit log DONE (audit_log.py): durable PredictionAuditLog table + best-effort observer in the scan loop records every decision + every would-be order (filled/rejected/gated). Side-effect-honest (event derived from the REAL OrderResult, never a fake fill); execution.py untouched; non-fatal. 3 Opus auditors CANNOT-BREAK."
    - "ENVIRONMENT REALITY: the binding constraint (validated OOS edge on REAL resolved-Polymarket data) is now blocked by the autonomous env's network EGRESS POLICY, not by missing code. The loop built everything buildable offline; the real-data run is OA-11 (owner runs the fetcher where Polymarket is reachable, or widens egress)."
    - "C5 metrics WIRED end-to-end (#56): metrics_aggregator + orchestrator.get_resolved_trades() + GET /prediction-markets/metrics/{weekly,floor-status,calibration} flow weekly PnL/Sharpe/hit-rate/drawdown + calibration from REAL resolved positions. Calibration reports honestly degenerate (never a fake pass) while model_prob==crowd. Backend done; dashboard UI remains."
    - "Live gate DEFENSE-IN-DEPTH (#57): LIVE_TRADING_ENABLED now also enforced fail-closed inside PolymarketExecutor.place_order() (both venue paths), plus side-effect-honest fill parsing (no FILLED without a real match). Opus auditor: SAFE — CANNOT-BREAK; paper provably unaffected."
    - "Real-data REPRODUCTION canary (#58): walk-forward + crowd Brier on the real 54-record fixture proven bit-for-bit reproducible (seed_hash 8dc358439ffb5746, crowd Brier 0.0933, 0 trades), pinned so drift fails loud. Proves determinism on REAL data; claims NO edge (model_prob==crowd)."
    - "B5 forensic audit harness (#59): existing cross-market alphas fire 0 signals on the real sample (no real question text / grouping). Adversarial auditor caught a boilerplate-text phantom-signal bug (98 false signals) — fixed + enforced by a regression test. Surfaced a real strategy weakness (keyword screen too weak), logged for future B-track."
    - "LLM spend cap + timeout ENFORCED (#60): LLM_SPEND_CAP_USD now fails loud before overspend (was config-only); every Gemini call now has a timeout (was none). LLM is not on the scan loop; hardens the /learn path per the standing hard rule."
    - "GATE STRENGTHENED: the blocking preflight now runs the new live-gate/metrics/canary/audit tests (99 -> 176 enforced tests), so these safety/honesty checks are required on every future change."
    - "B5 keyword screen HARDENED (#63): the weak '3+ shared words / 12-word skip set' cross-market relatedness screen (which paired on filler boilerplate AND same-template/different-subject text) is replaced by market_text.is_content_related — >=3 shared CONTENT tokens over a comprehensive stopword set. Rejects every adversarial-audit false positive (Biden/Macron, Bitcoin/Tesla, inflation/unemployment, Apple-Tesla-on-Nasdaq) while genuinely-related pairs still fire; strictly more conservative than before (190->0 phantom pairs). Honest SECONDARY-screen, not an exact classifier. Two fix cycles vs 5 reviewers/auditors."
    - "B2 multiple-comparison correction CODE-ENFORCED (#65): evaluate_calibration(strategies_screened=K) applies Bonferroni effective_alpha=alpha/K — the anti-p-hacking requirement is now a tested feature, not a doc note. Only ever TIGHTENS the gate (verified monotone, 0 False->True flips across thousands of datasets); strategies_screened=1 is bit-identical to prior behavior."
    - "B3/E6 learning-loop ENGINES built (#64): strategy_registry.py (alpha lifecycle state machine with a fail-loud integrity gate — promotion impossible without recorded backtest+OOS+calibration evidence) + per_strategy_metrics.py (pure per-strategy realized-PnL attribution, reconciles to total, no fabricated rows). Pure deterministic engines; NOT yet wired into the live loop (no DoD box). Opus auditors could not bypass the promotion gate or find fabricated attribution."
    - "A5 wall-clock staleness now FIRES (#66): Market carries a fetched_at ingest timestamp (stamped at parse), so the fetch-age staleness gate flags a stale in-memory snapshot in the live scan path (was a no-op). Never enters any backtest seed_hash."
    - "GATE STRENGTHENED again: the blocking preflight now also runs test_calibration/data_quality/market_text/strategy_registry/per_strategy_metrics (176 -> ~290 enforced tests)."
    - "B4a FIRST model_prob != crowd alpha BUILT (calibration_bucket_strategy.py): per-price-bucket empirical-calibration model + strategy; fits per-bucket YES-rates on a leakage-safe training set, ABSTAINS below min_bucket_n (default 30, never hardcodes), RAISES on empty fit; plugs into walk_forward (fresh model per call) + a live wrapper that abstains entirely without a fitted model (no fake control, left UNWIRED). 24 tests: recovers an injected OOS edge, 0/$0 on a well-calibrated crowd, cost band suppresses sub-threshold miscalibration, leakage-safe + reproduces. 3 fresh Opus auditors CANNOT-BREAK (no leakage, no fabricated edge, no overclaim). The MECHANISM, not a validated edge — needs the 7-day OOS corpus (OA-11) to prove a real edge; no DoD/floor box ticked."
    - "E5/E2 learning engines WIRED into the live loop (metrics_aggregator.compute_evaluation_windows + compute_calibration_drift; orchestrator.get_resolved_evaluation_trades + get_resolved_predictions; GET /metrics/evaluation-windows + /metrics/calibration-drift). Honest degenerate path: zero-trade windows never fabricated, Brier null without per-trade calibration, drift returns insufficient_data (never a false 'no drift = good'). 2 Sonnet + 1 Opus auditor CANNOT-BREAK."
    - "C5 dashboard UI BUILT (frontend/components/metrics/*): MetricsPanel + Weekly/Floor/Calibration/PerStrategy/EvaluationWindows cards render all /prediction-markets/metrics/* endpoints under a new Metrics tab; honest degenerate rendering (floor NOT MET with real avg, calibration note verbatim + Brier '—', drift 'not enough data', nulls as '—', a 0-trades banner). npm run build clean. F5 Playwright visual-verification of these states still pending."
    - "GATE STRENGTHENED again: test_calibration_bucket_strategy.py added to the blocking preflight list."
    - "Research Run 10 (2026-06-30): academic synthesis. Le 2026 (292M trades, Kalshi+Polymarket) confirms domain-specific calibration decomposition: political markets show PERSISTENT underconfidence (compression toward 50%) at ALL horizons — the dominant calibration component (bilateral partisan cancellation). EXP-003 proposed. Prediction Arena 2026: ALL 6 frontier LLMs lost money live-trading on Kalshi (-16% to -30.8%); Polymarket only -1.1% avg. PolyBench 2026: only 2/7 LLMs positive (MiMo-V2-Flash +17.6% CWR, Gemini-3-Flash +6.2%) — Gemini models show positive calibration, relevant for B4 design. MAJOR DATA FINDING: Polymarket-v1 HuggingFace dataset (arxiv 2606.04217, June 2026) — 1.3M markets, 1.2B trades, CC-BY-4.0, Parquet, includes market metadata + outcomes in daily_aligned layer — could bypass OA-11 entirely (proposed OA-16). Insider trading on Polymarket: ~25% of large longshot bets ($2500+, <35%) resolve YES vs 14% baseline; proposed as a DEFENSIVE adverse selection filter (avoid these markets), not an edge to copy. Cross-venue arb: confirmed bot-dominated (Kalshi now #1 by volume at $14.8B/mo April 2026). Binding constraint UNCHANGED: no validated OOS edge; OA-11/OA-15 (egress) OR new OA-16 (HuggingFace download) needed."
    - "Research Run 12 (2026-07-02): production-forensics on the now-live OA-17 forward-paper cycle
      (live-validation.yml, every 6h on GH Actions, Neon DATABASE_URL secret set). URGENT finding:
      the orchestrator's real order-persist path (_persist_order) has no default-portfolio guard and
      fails EVERY order with a Postgres ForeignKeyViolation, confirmed live today — despite two prior
      fixes (#139/#140) believed to cover this; the guarded path (persistence.save_order/save_position)
      is never called by the live loop. The forward-paper track record this mechanism was built to
      produce may not be durably accumulating. SECOND finding: the D2 per-category $200 cap has become
      a de facto GLOBAL cap because Market.category is empty on real Polymarket data (everything
      buckets as 'General') plus the in-memory category map resets every fresh process — confirmed
      live: 98/98 opportunities skipped in the most recent scheduled run. Both are loop-buildable code
      fixes, no data/egress/owner action needed. THIRD (insufficient data): logical_implication +
      adaptive_threshold fired real signals on live MECE question sets (LeBron team markets, FIFA WC
      winners) for the first time — not an edge claim, no resolutions yet. FOURTH: confirmed (not just
      theorized) that GitHub Actions runners have working Polymarket/Gemini egress, de-risking OA-13
      Option B. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "Research Run 11 (2026-07-01): SELF-VALIDATION — tested OA-16's premise directly from the autonomous env's own proxy: huggingface.co is 403-blocked (confirmed via the proxy's own diagnostic, not just an app error), and data-api.polymarket.com (the whale-feed's dependency) is ALSO 403-blocked. The egress block is broad-scope (Polymarket + HuggingFace + Data API), not a narrow allowlist gap — OA-16 step 1 can only be verified from the OWNER's own network, never from this env. A secondary comparative-calibration source (Calibration City 671K markets + brier.fyi 971 cross-linked markets) reports Polymarket calibration beating Kalshi's — the opposite direction a Kalshi-anchored effect (Le 2026) needs to transfer cleanly to Polymarket; added as a pre-mortem caution to EXP-002/EXP-003 (not a refutation — non-peer-reviewed, unreproduced by us). URGENT INTEGRITY FINDING (not an alpha claim): `WhaleCopyTradingStrategy` + `WeatherArbitrageStrategy` are wired UNCONDITIONALLY into `orchestrator._build_default_scanner()` (live in the paper scan loop today) despite NEVER being logged as proposed/tracked in ROADMAP or RESEARCH_MEMORY, and with zero tests. Worse: `whale_feed.py`'s hardcoded `KNOWN_WHALES` seed pairs the real trader name 'Theo4' with a WRONG on-chain address (verified against Theo4's actual public Polymarket profile address, which differs completely), and a third seed address is a self-evidently fake sequential-hex placeholder (`0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0`). Since the feed's dynamic `/holders` self-correction is also unreachable here (Data API 403), in this env the strategy runs on the fabricated seed alone, silently (logged warning, strategy continues), inflating the reported strategy count with a contributor producing no real signal. Full detail + recommended factory fix in RESEARCH_MEMORY 2026-07-01."
    - "Factory run (2026-07-03): B8 cross-venue coherence matcher + backtest BUILT (#179, prediction_markets/cross_venue_matcher.py) — the strongest reason to run two venues: trade the price gap when the SAME event is priced differently on Polymarket vs Kalshi (a logical-consistency edge that does NOT require out-calibrating the crowd, unlike B4a which lost -$639 OOS). Adversarially-hardened event-matcher (content + numeric-strike + timeframe gates; boolean match separated from a bounded coherence_score) + cost-net coherence primitive (no fabricated edge when venues agree) + resolved-pair backtest that honestly models the resolution-divergence downside. The adversarial gate broke it 4x/3 cycles (adjacent-strike tolerance, no-threshold cap, negation parsing x2) — the negation rabbit hole was ended by ELIMINATING the fragile inversion heuristic: a negated comparator now VOIDS the strike (tightening-only, can never fabricate a match). NO orchestrator/executor wiring (DECISION COROLLARY); a CANDIDATE edge, NOT validated (no DoD/floor box). F10 regime-slice report WIRED into validate_real_oos (#180) — anti-overfitting concentration check on every real OOS run; fixed a structurally-false category FRAGILE on an unlabeled corpus at the regime_slice root. Blocking-gate coverage: registered test_market_category (the #156 confirmed-outage fix, was NOT in the required gate), test_weekly_metrics, test_cross_venue_matcher (#182). Binding constraint UNCHANGED (validated OOS edge, owner/egress-blocked OA-11/15/16); B8 gives a second, possibly-more-robust alpha CANDIDATE once real dual-venue corpora exist. Dropped A3 Kalshi-category routing as padding (Kalshi not live-scanned; the loop already dropped this nit — the value reviewer caught it)."
    - "Factory run 3 (2026-07-02): ADDRESSED both of Research Run 12's URGENT loop-buildable flags. (1) LIVE-FREEZE FIXED (#156): the forward-paper cycle was skipping 154/154 opportunities on a de-facto-global category cap (real Polymarket markets ship empty `category` → everything bucketed 'General' → per-category $200 cap < $500 portfolio cap). New pure `market_category.py` derives a coarse real correlation bucket (tags → keyword scan) at parse time; `Position` carries category so rehydrated positions count in their real bucket across the fresh-process cycle. Opus safety auditor SAFE (the $500 global backstop still binds at both risk-manager + executor layers). (2) The FK-persist flag was VERIFIED-AND-DISPROVEN as a live bug (its 6/6-fail evidence predated the #140 seed; live runs now rehydrate $164 of positions — impossible if `_persist_order` still FK-failed) — so instead of re-fixing a non-bug, #157 hardened the live writer (in-transaction `_ensure_default_portfolio`) and closed the genuine gap: a missing FK-enforced (`PRAGMA foreign_keys=ON`) regression test on the live writer, since the SQLite gate was FK-blind by construction. No validated edge / no DoD box ticked — an operational unfreeze + coverage. Two more unguarded `portfolio_id=1` writers (`_take_snapshot`, `api/routes.py:445`) remain as a fast follow-up."
    - "Research Run 13 (2026-07-03): SELF-VALIDATED (direct job-log read, not self-report) that both Research Run 12 URGENT fixes hold live: the category-cap freeze stayed broken through the 2026-07-02 09:36 + 14:31 runs (98/98, 154/154 skipped) then fixed itself by 19:55 the same day (10/94 executed) and stayed fixed through 07-03 09:37 (6/108 executed, diverse categories: FIFA WC, Fed decision, MLB, esports, geopolitics, NVIDIA); zero ForeignKeyViolation/exception recurrence across 5 full job logs grepped. Zero resolutions yet (`resolutions: null` every run) — expected, not a bug: bankroll_remaining fell $500→$153.89 as positions opened but time hasn't passed for the short-dated ones (this week's Elon tweet-count window, a within-2-weeks Iran deadline) to resolve; the near-term binding constraint for real calibration/PnL evidence is now simply ELAPSED TIME, not a code defect. Minor non-blocking note: Gemini client fails to construct in every inspected smoke-test step (LLM not on the scan-decision critical path, degrades safely per G2, but no live Gemini connectivity currently for future B4 work). NEW DATA-SOURCE LEAD: Dune Analytics ships a free-tier unified Polymarket+Kalshi resolved-market dataset (simpler than HF parquet, uniquely spans BOTH venues — useful for EXP-004) but is CONFIRMED egress-blocked from the autonomous env (dune.com 403, same broad-allowlist signature as the other 3 blocked domains) and needs a free DUNE_API_KEY; not yet built as a fetcher, recommended to the factory. A secondary favorite-longshot-bias search surfaced two non-academic sources making OPPOSITE-direction claims about near-zero-price calibration — treated as noise per playbook discipline, not evidence either way. No new EXP proposed (proposing one against a zero-resolution track record would be premature). Full detail: RESEARCH_MEMORY 2026-07-03."
    - "Factory run 2 (2026-07-04): SAFETY — reject SELL-to-open-a-short (#215, D3/D4). A bare SELL on an un-held token fabricated a fictional `side=\"short\"` position via the paper `_simulate_fill` (fills unconditionally — a phantom fill the live venue would REJECT, since you can't sell CTF tokens you don't own), and a BUY 'to close' it scaled the position UP recording $0 realized PnL → the hard loss caps + kill switch (D3/D4) never saw the loss. REACHABLE in the live default scan: CrossMarketArbitrageStrategy emits an executable outcome_idx=0 SELL (strategies.py:627/686), routed at orchestrator.py:1033; skip-held guarantees any executed SELL is on an un-held token. Reproduced end-to-end (bare SELL→FILLED short 100@0.30; BUY-to-close→size 200, realized_pnl 0.0). Fix: `_check_risk` rejects a SELL whose size exceeds the covering long; SELL-to-reduce-a-held-long is preserved. 5 tests (3 fail-pre-fix); 2 Sonnet + a fresh Opus live-safety auditor SAFE (6 executed attack vectors). This OVERTURNED a twice-dropped 'SELL/short unreachable' prior with new specific evidence + a repro (the mirror of the anti-re-litigation rule). Also #216 gated test_simulation_engine (48 tests of the LIVE Monte-Carlo pricing feeding Kelly, previously ungated) + #217 removed the last stock-era render.yaml residue (FRED_API_KEY). No DoD/floor box ticked. Two non-blocking Opus-flagged follow-ups: the 1e-9 boundary tightening + legacy short-row remediation (guard the _update_position BUY-on-short branch)."
    - "Research Run 14 (2026-07-04): the research-agent's own environment has OPEN egress to
      gamma-api/clob/data-api.polymarket.com + huggingface.co (dune.com still 403) — the opposite of
      every prior research run's finding for the autonomous factory build-loop (untested this run;
      not assumed to be the same). Used it to run the first-ever REAL OOS test of EXP-002: N=510
      leakage-safe 7-day-lead records, walk-forward PnL -$2,938.70/46 trades + a static-split B2
      significance eval both NEGATIVE (not just insufficient data) — mechanism-tested-failed, with
      a diagnosed cause (a static all-time bucket average lags a possibly time-varying near-zero-price
      resolution rate: 1.0% train vs 7.59% test) and full adversarial pre-mortem on the result itself.
      Also found EXP-001's near-certainty-NO hypothesis independently corroborated on a second real
      OOS sample (N=79, not yet a validated result), confirmed EXP-003 is blocked by the same
      empty-category defect on resolved-market data that #156 fixed only for the live scan path, and
      found a factory-actionable pagination bug (Gamma silently caps pages at 100 rows regardless of
      requested --limit, so every documented --limit 250/500 OA-11/EXP command under-fetches). Full
      detail: RESEARCH_MEMORY 2026-07-04."
  next_actions:
    - "NEW (Research Run 23, 2026-07-15): EXP-006 is now a formally specified experiment in
      experiments[] (status=proposed) with a preliminary, real-data pilot signal (N=16 markets,
      mean hourly lag-1 price-change autocorrelation -0.102, 95% CI excludes 0) -- but it is NOT
      ready to build without first resolving two open design items, both genuinely new (no existing
      code to reuse): (1) a spike/move-DETECTION function with a PRE-REGISTERED Delta-threshold and
      window (not tuned after seeing data); (2) a per-CLUSTER (correlated event-group) notional
      exposure cap, since Research Run 22 already proved a per-TRADE cap is a structural no-op
      against cross-trade correlation -- the same risk applies here if reversal opportunities
      cluster around one news event. If a full-market-lifetime series is ever needed (not just the
      last-14-days window this pilot used), the fetch must be CHUNKED across multiple <=15-day CLOB
      calls -- a newly-discovered hard API constraint (see the GROWTH_STATUS EXP-006 pilot_probe
      field / RESEARCH_MEMORY 2026-07-15 for the live binary-search evidence). Recommend the next
      research run either (a) grow this pilot's N (more categories/time, still hourly/14-day-window,
      no code change needed, cheap) to sharpen the preliminary signal before recommending a factory
      build, or (b) if the factory independently prioritizes EXP-006, build the detector +
      per-cluster cap together from day one per this run's oos_plan. Do NOT build a spike detector
      with only a per-trade cap -- Run 22 already showed that specific mitigation fails. No new
      EXP-00N beyond EXP-006 proposed this run; binding constraint (no validated real-money OOS
      edge) STANDS. Full detail: RESEARCH_MEMORY 2026-07-15 (Research Run 23)."
    - "TESTS the Run 21 item below and finds its recommended mitigation does NOT work as hoped (Research
      Run 22, 2026-07-14): Run 21 recommended building a 'concentration-capped/recency-weighted
      CalibrationBucketStrategy redesign' as the lower-cost next step. This run tested the two concrete,
      cheaply-testable variants of that idea directly against the real EXP-003 Politics corpus (1,369
      leakage-safe records, byte-identical to Run 20's pull — a useful stability check), using only the
      EXISTING `make_calibration_bucket_strategy(edges=...)` parameter + a post-hoc trade-level analysis
      (no new strategy code): (a) FAVORITES-ONLY (price 0.5-1.0, matching EXP-002's original hypothesis
      band): 18 trades, net -$841.11 — kills the F10 fragility flags (correctly, since the aggregate is
      negative) but does NOT recover a positive result either; N=18 is below F11's own 30-trade
      significance floor, so this is honestly `insufficient_data`, not a refutation. (b) DROP-EXTREMES
      (exclude only price<0.10/>0.90, keep the broad middle): 135 trades, net +$13,584.50 (down from
      baseline's $28,815.49) but STILL F10 fragile (horizon + confidence concentration) and STILL F11
      `indistinguishable_from_zero` (hit rate 24.44%, CI spans 0) — excluding only the extreme deciles
      does not fix the failure mode, which persists broadly across the sub-0.5 price range. (c) A
      PER-TRADE notional concentration cap (10%/5%/2% of total deployed capital) is a structural NO-OP:
      0 of 472 baseline trades exceeded even the 2% cap ($3,736 vs. a $395.79 mean trade size) — the
      single-market-57%/category-134% concentration Run 20/21 flagged is caused by MANY separate,
      modestly-sized trades on the SAME underlying correlated event cluster (e.g. multiple candidate-
      outcome markets in one election), not one oversized bet. **This means Run 21's 'lower-cost' framing
      undersold the real cost: a working redesign needs a per-CLUSTER/entity exposure cap, not a per-trade
      size cap — a materially harder, unbuilt design problem, not a parameter tweak.** New VERIFIED
      academic corroboration this run (WebFetch of the primary abstract, not a search synthesis): Karl
      Whelan's 'Makers and Takers: The Economics of the Kalshi Prediction Market' (N>300,000 real Kalshi
      contracts, `ideas.repec.org/p/pra/mprapa/126350.html`) confirms classical favorite-longshot bias
      (`low-price contracts win far less often than required to break even, while high-price contracts
      win more often and yield small positive returns`) — Kalshi-only, NOT confirmed on Polymarket, but a
      plausible causal mechanism for why this project's OWN bucket-calibration family keeps finding
      apparent 'edge' concentrated in longshot buckets with a hit rate far below 50% (a static empirical-
      rate fit on a bucket the crowd already correctly under-prices is more likely picking up in-sample
      noise that reverts OOS than a real inefficiency). RECOMMEND-only, no ROADMAP steer (no high-
      confidence validated edge). Binding constraint unchanged: no validated real-money OOS edge on any
      tested mechanism to date. Full detail: RESEARCH_MEMORY 2026-07-14 (Research Run 22)."
    - "REFINES the Run 20 item below, does not supersede it (Research Run 21, 2026-07-13): Run 20 offered
      two next steps in no stated order (a concentration-capped/recency-weighted CalibrationBucketStrategy
      redesign, or scoping EXP-006). This run scoped EXP-006 further and found its stated blocker
      overstated: `PolymarketHistoryFetcher.fetch_price_history` already fetches the full raw CLOB tick
      series (not just one snapshot) and was LIVE-VERIFIED this run to support `fidelity=1` (real
      1-minute bars, 5,760 ticks at exact 60s spacing, fetched against the Trump-2024 election token
      across the July 13 2024 assassination-attempt window) — so EXP-006's remaining build is a
      detection+labeling pipeline on an already-fetchable series, not a wholly new fetcher. Despite that
      good news, priority still favors building the concentration-capped redesign FIRST: it needs zero
      new data-access work (testable directly on the EXP-002/003/005 corpora already fetched and
      characterized) vs. EXP-006 which still needs a new pipeline built + its own pre-registered OOS run.
      A live single-case illustration this run (N=1, explicitly not a test) is a concrete reason any
      EXP-006 build must ship the per-trade concentration cap from day one: the highest-salience 2024
      political spike (the assassination attempt) did NOT revert — it persisted (0.595->0.685 at
      +24h->0.705 at +48h) — the opposite of the aggregate weak-reversal finding EXP-006 is built on,
      consistent with large information-laden spikes behaving differently from the many small spikes
      likely dominating an aggregate daily-serial-correlation statistic. Also this run: a WebSearch
      synthesis invented a precisely-quantified \"Iran Ceasefire market\" spike/reversal example
      (\"$280M volume... 35% to 68% in eight minutes... settled at 58%\") that its own cited DL News
      source does not contain anywhere in its text (directly re-fetched and checked, not re-summarized) —
      caught before being logged as data; NOT used as evidence for or against EXP-006. Filed as a
      process-hardening note: a search tool's own synthesized answer can fabricate specific statistics
      not present in any of its listed sources, so every quantified claim destined for RESEARCH_MEMORY
      needs a direct fetch of its actual cited source, not just a plausible-sounding summary. No new
      EXP-00N proposed; binding constraint (no validated real-money OOS edge) STANDS. Full detail:
      RESEARCH_MEMORY 2026-07-13 (Research Run 21)."
    - "SUPERSEDES the Run 19 item below (DONE, not just recommended — Research Run 20, 2026-07-12):
      Run 19 recommended applying the `tag_id` lever to EXP-003/Politics. This run did that (`tag_id=2`
      via `GET /tags/slug/politics`, one pre-registered run, N=1,369) — EXP-003 is now TESTED, not
      proposed/corpus-blocked: fragile + statistically insignificant (hit_rate 25.64%, F10 134%
      category concentration + 57% single-market concentration), the SAME failure shape as EXP-005.
      NEW, higher-value recommendation for the next run (loop-buildable framing, not a data-fetch
      recipe): do NOT spend the next run's pre-registered test on a 4th category-only re-run of the
      SAME static CalibrationBucketStrategy mechanism (e.g. Economics/Crypto via their own `tag_id`) —
      3 independent real per-category corpora (EXP-002 all-categories, EXP-005 Sports, EXP-003
      Politics) now show the SAME failure shape (sub-50% hit rate, PnL concentrated in one
      category/confidence/horizon bucket and often one market), which is strong evidence the
      MECHANISM itself (cost-net Kelly sizing on a static per-bucket rate, which structurally
      concentrates on illiquid longshot convexity) is the problem, not any one category. Two
      concrete next steps, either is loop-buildable: (a) redesign CalibrationBucketStrategy with an
      explicit per-market/per-trade notional concentration cap (directly targets the 57-134%
      single-bucket/single-market failure mode common to both fragile results) and/or a
      recency-weighted (not static all-time) bucket fit; (b) scope the EXP-006 candidate this run
      surfaced (political price-reversal after hype-driven price spikes, Clinton & Huang 2025/2026) —
      requires a NEW intraday/sub-daily price-history fetcher (the existing HistoricalMarket fetchers
      capture one pre-decision snapshot per market, not a price series) plus a spike-detection +
      reversal-labeling pipeline; this is genuine factory-build scope, not a parameter tweak, and
      should be pre-registered (spike threshold Δ, window) BEFORE any real data is pulled to avoid the
      exact overfitting trap illustrated by the QuantPedia mean-reversion cautionary example logged
      this run (N=3 assets, 12-variant search, best result cost-fragile). Full detail: RESEARCH_MEMORY
      2026-07-12 (Research Run 20)."
    - "SUPERSEDED by the item above (kept for history — Research Run 19, 2026-07-11):
      Run 18 recommended merging the volumeNum + volume24hr axes to push EXP-005's Sports N toward
      300-400. This run found and used a stronger lever instead: resolved Gamma's real \"Sports\"
      tag id (`tag_id=1` via `GET /tags/slug/sports`) and ran the already-shipped
      `validate_real_oos.py --tag-id 1 --decision-lead-days 7 --seed 42 --max-pages 20` (one
      pre-registered run) — N=814, more than double the floor, no merge needed. EXP-005 is now
      TESTED (not insufficient-data): fragile + statistically insignificant (see GROWTH_STATUS
      EXP-005 for the full F10/F11 result) — a real negative result, not a further data-access gap.
      NEW, loop-buildable recommendation for the next run: apply the SAME `tag_id`-resolution lever
      to EXP-003 (Domain-Calibrated Political Strategy, still `proposed`/blocked on corpus size) —
      resolve the real Politics tag id via `GET gamma-api.polymarket.com/tags/slug/politics` (or
      `/elections`), spot-check a handful of live markets before committing, then run
      `validate_real_oos.py --tag-id <resolved id> --decision-lead-days 7 --seed 42 --max-pages 20`
      as ONE pre-registered run. This is the same mechanism EXP-005 just proved works at scale (N=814
      in ~9 minutes, zero code changes) — it should unblock EXP-003's corpus-size blocker the same
      way. Full detail: RESEARCH_MEMORY 2026-07-11 (Research Run 19)."
    - "RESOLVED + SELF-VALIDATED (Research Run 17, 2026-07-09): Research Run 16's URGENT
      resolution-telemetry flag (`check_resolutions()` never returning a value, so
      `\"resolutions\"` was a structural `null`) was fixed by the factory (#267, landed
      2026-07-08T17:00). This run independently confirmed the fix on 2 real post-fix
      `live-validation.yml` runs (2026-07-09T04:16 + 09:59) — both report a real
      `\"resolutions\": 0`, not `null`. The telemetry is now trustworthy; the value is genuinely
      zero. No further factory action needed on this item — just keep watching for the first
      non-zero reading now that it can actually show one. (basicConfig/INFO-logging visibility,
      the second half of Run 16's recommendation, was not independently re-checked this run.)
      Full detail: RESEARCH_MEMORY 2026-07-09 (Research Run 17)."
    - "SUPERSEDED by the item above (kept for history — Research Run 18, 2026-07-10): the merge
      recipe below was never executed — Research Run 19 found a stronger lever (`tag_id` resolved
      via `GET /tags/slug/<name>`) that reached the target N directly, without a merge.
      SUPERSEDES the Run 17 item below (LOOP-BUILDABLE, cheap — an operational recipe with
      EXISTING flags, no fetcher code change; Research Run 18, 2026-07-10): Run 17 diagnosed
      EXP-005's Sports corpus as stuck at N~135 and recommended a fetcher-DESIGN change (a new
      recency-ordered code path). This run found that fix already exists and works: passing
      `order=\"volume24hr\"` (a Gamma sort field `PolymarketHistoryFetcher.fetch_resolved_markets`
      already accepts, that no script in this repo had ever passed) grew leakage-safe Sports N
      135→253 (+87%) in one fetch, zero code changes. Recommended next step: run
      `scripts/fetch_polymarket_history.py` TWICE with `--merge` into the SAME `--out` file — once
      `--order volumeNum`, once `--order volume24hr` (dedupes by market_id automatically) — to
      combine both near-disjoint axes toward the ~300-400 Sports-only floor, then run
      `validate_real_oos.evaluate()` on the Sports-filtered merged corpus ONCE with the
      pre-registered params (seed=42, decision_lead_days=7), no retry after seeing the number.
      When interpreting the result, weigh the new Le-2026-Table-3 external caution (sports
      calibration slope is only 1.04 at the ~7-day/\"2d-1w\" horizon, vs. 1.74 beyond 1 month) —
      it tempers the a priori expected edge size even if N clears the floor. Full detail:
      RESEARCH_MEMORY 2026-07-10 (Research Run 18)."
    - "SUPERSEDED by the item above (kept for history — Research Run 17, 2026-07-09): EXP-005's
      Sports-category corpus was stuck at N~135 because `order=volumeNum` draws from an
      almost-static all-time top-volume ranking — re-fetching with a bigger `--max-pages`
      re-discovers nearly the SAME markets (confirmed empirically: 133→134→135 across 3
      independent pulls on 07-07/07-08/07-09). Run 17's own recommendation (a new fetcher-design
      code path) turned out to be unnecessary — see the Run 18 item above. Full detail:
      RESEARCH_MEMORY 2026-07-09 (Research Run 17)."
    - "NEW, loop-buildable, not yet built (Research Run 15, 2026-07-05): a 'mention/narrative
      market' classifier (keyword/tag heuristic in the style of market_category.py — question
      patterns like 'will X say/tweet/mention Y') would unlock testing the 'Yes Bias' candidate
      (unverified secondary source — QuantPedia review of Deleep et al. SSRN ~March 2026, primary
      paper unreachable): traders in low-liquidity, near-resolution mention markets allegedly
      overpay for YES via narrative conviction, a market-TYPE-based effect distinct from the
      refuted price-bucket family. Do NOT treat this as validated — no N/magnitude available; build
      the classifier + a pre-registered EXP-005 proposal only once real mention-market volume on
      Polymarket can be measured. Full detail: RESEARCH_MEMORY 2026-07-05."
    - "SHARPENED (Research Run 15, 2026-07-05): Kalshi's public /markets LIST endpoint reconfirmed,
      at n=1000 (5x the same-day factory B8 probe's n=200), to return ZERO markets with a populated
      yes_bid/yes_ask/last_price — a structural property of the bulk list endpoint, not a
      small-sample fluke. B8's next step should target a per-market quote/orderbook call or the
      already-fixed candlestick history path (OA-15/#170), not further iteration on the list
      endpoint. Full detail: RESEARCH_MEMORY 2026-07-05."
    - "STATUS UPDATE (Research Run 15, 2026-07-05): forward-paper track record (OA-17) still at zero
      resolutions as of 2026-07-05T09:24 UTC (6 runs checked since 2026-07-03, all null). NOT a new
      bug — bankroll ($102.87 remaining) is mostly deployed and the Sports category's $200 cap is
      genuinely saturated by real FIFA World Cup concentration (D2 working as designed); no fix
      needed. Keep watching for resolutions as shorter-dated 2026-07-02/03 positions mature — flag
      only if the Sports cap stays saturated for weeks with no rotation despite freed capital."
    - "HIGH-VALUE, loop-buildable (Research Run 14, 2026-07-04): re-probe gamma-api.polymarket.com,
      clob.polymarket.com, data-api.polymarket.com, huggingface.co, and dune.com from the AUTONOMOUS
      FACTORY BUILD LOOP itself (not just the research-agent session, which confirmed 4/5 open this
      run — dune.com still 403). If the factory's own loop also has open egress now, OA-11/OA-13/OA-16
      can close without owner action, and the factory can fetch+commit a real resolved-market corpus
      directly. Also fix the pagination bug this run found: `PolymarketHistoryFetcher.fetch_resolved_markets`
      (polymarket_history_fetcher.py:181-208) silently caps each Gamma page at 100 rows regardless of
      the requested `--limit`, so every documented `--limit 250`/`--limit 500` command in this file and
      PENDING_OPS under-fetches to a single ~100-row page; use `--limit 100` with `--max-pages` to get
      real depth. Full detail: RESEARCH_MEMORY 2026-07-04."
    - "EXP-002 TESTED AND FAILED on real data this run (Research Run 14, 2026-07-04): N=510 real
      7-day-lead resolved Polymarket records, two independent methods (walk-forward PnL: -$2,938.70
      over 46 trades; static-split B2 significance: improvement=-0.00266, 95% CI entirely negative,
      passes=False). Do not re-test the identical config — diagnosed cause + a candidate revised
      design (rolling-window recency-weighted bucket model, not yet built or tested) in RESEARCH_MEMORY
      2026-07-04. EXP-001's near-certainty-NO hypothesis independently strengthened by a second real
      OOS sample (N=79, 7.59% actual vs crowd's 1.85% average price, p~0.0035) but NOT validated —
      needs a fresh, pre-registered test on data not already used for EXP-002. EXP-003 confirmed
      blocked by the SAME empty-`category` defect on RESOLVED-market data (996/1000 empty) that #156
      already fixed for the live scan path but never ported to the history fetcher."
    - "URGENT, loop-buildable, no owner/data action needed (Research Run 12, 2026-07-02): the live
      OA-17 forward-paper cycle's real write path (orchestrator._persist_order, orchestrator.py:1034)
      has NO _ensure_default_portfolio guard and fails EVERY order persist with a Postgres
      ForeignKeyViolation — confirmed live in today's GitHub Actions logs (run 28563250362, 6/6
      executions failed to save), despite two prior fixes (#139, #140) that were believed to cover
      this. persistence.py's guarded save_order/save_position are never called by the live loop; the
      init_db() seed (#140) does not appear sufficient in production (root cause of WHY still needs
      RCA). Fix: route _persist_order through the guarded persistence.save_order/save_position (one
      write path, not three) AND add a PRAGMA-foreign_keys-ON SQLite (or Postgres-parity) regression
      test to the blocking gate — the current SQLite-only CI cannot catch this bug class by
      construction, which is why it has now recurred. Until fixed, do not read edge into any
      forward-paper numbers collected since OA-17 went live. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "URGENT, loop-buildable (Research Run 12, 2026-07-02): the D2 per-category exposure cap has
      become a de facto GLOBAL $200 cap, not a per-category one — Market.category is empty on real
      Polymarket data (polymarket_client.py:799 parses raw.get('category','')), so risk_manager.py:157
      buckets every real market as 'General', and the in-memory _market_categories map resets empty
      every fresh GH-Actions process, so rehydrated positions ALSO default to 'General'. Confirmed
      live: the 2026-07-02T09:36 scheduled run skipped 98/98 real opportunities on 'General exposure
      $164.18 > $200'. Since these positions won't resolve for weeks/months, this freezes the forward
      loop until fixed. Fix: derive category from a real Polymarket field (tags/event grouping) instead
      of the empty 'category' key, and/or read the category already stored on PredictionPosition rows
      back on rehydration instead of re-defaulting to General. Full detail: RESEARCH_MEMORY 2026-07-02."
    - "NOTABLE, insufficient data (Research Run 12, 2026-07-02): LogicalImplicationDetector
      ('logical_implication') and AdaptiveBuySignalThreshold ('adaptive_threshold') fired real signals
      live today for the first time (0 signals on the 2026-06-29 sterile fixture) on genuinely
      MECE real-world question sets (LeBron James team markets, FIFA World Cup winner candidates) —
      a plausible confirmation the B5-hardened relatedness screen generalizes to real text. NOT an
      edge claim: no resolutions yet, N<10, and per the finding above most fills likely never
      persisted. All fired trades bought near-zero-price longshots (0.25-1.65 cents) — the highest
      real-slippage-risk regime per EXP-002's pre-mortem. Revisit once persistence (above) is fixed
      and a real track record can accumulate."
    - "CONFIRMED (Research Run 12, 2026-07-02): GitHub Actions runners have working Polymarket +
      Gemini egress (proven repeatedly by live-validation.yml, not just theorized) — de-risks OA-13
      Option B (the staged-but-unapplied refresh-polymarket-data.yml). The only remaining step is the
      owner applying that staged workflow file."
    - "HIGHEST-EV owner action (two paths, either unblocks all calibration alphas at once): PATH A (new OA-16, PREFERRED) — verify HuggingFace egress is accessible, download Polymarket-v1 daily_aligned Parquet (1.3M markets, CC-BY-4.0, no Polymarket API key needed, broader corpus than OA-11); PATH B (existing OA-11) — re-run `python3 scripts/fetch_polymarket_history.py --decision-lead-days 7 --limit 500 --max-pages 3 --min-volume 1000 --merge --out data/polymarket_history_7d.json` from a network-permitted host. Either path produces the corpus needed for EXP-002 + EXP-003 (same CalibrationBucketStrategy mechanism, already built)."
    - "LOOP-BUILDABLE (no data needed): build polymarket_v1_hf_fetcher.py — reads the daily_aligned Parquet from HuggingFace (huggingface_hub Python library, dataset TimeSeventeen/Polymarket-v1) and assembles leakage-safe HistoricalMarket records with the same structural anti-leakage guarantee as polymarket_history_fetcher.py. Once built, OA-16 step 2 (owner runs it) can bypass OA-11 entirely."
    - "NEW (Research Run 13, 2026-07-03): Dune Analytics ships a unified, free-tier Polymarket+Kalshi resolved-market dataset (5 public tables, every resolved market carries its final outcome, hourly candlestick prices back to 2021-2022) — simpler to consume than the OA-16 HuggingFace parquet path AND uniquely spans BOTH venues in one schema (directly useful for EXP-004 cross-venue coherence, which no single existing source covers). CONFIRMED egress-blocked from the autonomous env (dune.com/api.dune.com/docs.dune.com all 403 at the proxy, same broad-allowlist signature as gamma-api/CLOB/HuggingFace/Data-API — the 4th domain in this class). Requires a free DUNE_API_KEY (not fully keyless like the Gamma/CLOB path) — a new, distinct owner-action class. NOT yet built as a fetcher (research-agent scope ends at surfacing the lead); recommend the factory build dune_fetcher.py (mirrors how polymarket_v1_hf_fetcher.py originated) and file the owner step once fixture-tested. GitHub Actions runner reachability to dune.com is untested (plausible but unconfirmed)."
    - "EXP-002 + EXP-003 share the same BUILT mechanism (calibration_bucket_strategy.py) and differ only in the corpus: EXP-002 uses all price ranges at 7-day lead; EXP-003 filters to politics/elections category. Once the corpus arrives, both can be tested in one run: fit on oldest 60%, OOS on newest 40%, B2 significance gate with Bonferroni correction across the two strategies."
    - "B4 LLM research design implication (Prediction Arena + PolyBench findings): if B4 is built, do NOT design an autonomous LLM trader (Prediction Arena proves 5/6 models lose money). Design LLM as a TARGETED RESEARCH TOOL for specific question categories (domain-specific calibration assistance). Use Gemini (already have GEMINI_API_KEY) — PolyBench shows Gemini-3-Flash achieves positive CWR. Gated on B2 producing a passing eval first."
    - "EXP-002 factory build DONE (calibration_bucket_strategy.py) — the CalibrationBucketStrategy is built, tested (24 deterministic tests, 3 Opus auditors CANNOT-BREAK), and plugs into walk_forward. ONLY remaining EXP-002 blocker is the real corpus (OA-11 or OA-16)."
    - "Once real data is available: produce a VALIDATED OOS weekly-PnL series + a passing B2 calibration eval on live strategy probabilities; calibrate the market-impact model against real OrderBook depth; wire the fitted-model fit path into a research/owner entry point + the B3 lifecycle."
    - "A4 event/market-universe + persistent resolution tracking (foundation for B2 on real data + the E learning loop); confirm the audit log's DATABASE_URL is durable (OA-10)."
    - "DONE (2026-07-01, #116) — the Research Run 11 whale/weather integrity finding: the fabricated `KNOWN_WHALES` seed in `whale_feed.py` is REMOVED (now `[]`; the feed uses only real `/leaderboard`+`/holders` discovery — real signal or none, never a fabrication), and `WhaleCopyTradingStrategy` + `WeatherArbitrageStrategy` are gated OUT of BOTH default scanners behind `ENABLE_UNVALIDATED_STRATEGIES` (default off). Tracked as ROADMAP B7. 2 Sonnet reviewers APPROVE + 1 Opus integrity auditor SOUND (verified no fabricated wallet enters any path even via the still-deployed `wallet_divergence` consumer). REMAINING to re-enable either strategy (B7): a B3 `PROPOSED` entry + a `strategy_audit.py` forensic pass + OOS validation (whale additionally needs `data-api.polymarket.com` reachable — egress-blocked in-env)."
  owner_blockers:
    - "Confirm venue ToS + jurisdiction eligibility before any live capability."
    - "OA-16: verify HuggingFace egress from owner's environment; download Polymarket-v1 daily_aligned Parquet (CC-BY-4.0, no API key). This is the preferred path over OA-11 (broader corpus, no Polymarket API egress needed). CONFIRMED (2026-07-01, research run): huggingface.co and data-api.polymarket.com are BOTH 403-blocked from the autonomous env's own proxy — this is a broad-scope block, not a narrow gap, so step 1 must be verified from the owner's own network/host; the loop cannot self-serve it. See PENDING_OPS OA-16. UPDATE (2026-07-04, Research Run 14): the research-agent's own session now reaches huggingface.co + data-api.polymarket.com directly (real content, not a block page) — this may mean OA-16/OA-13/OA-11 no longer need owner action, but that must be re-confirmed from the AUTONOMOUS FACTORY loop specifically (a different environment/session, not re-tested this run) before treating them as fully self-served. Owner action may shrink to 'nothing to do' once the factory confirms — not yet closed here."
```

## engine_pct rationale (pinned to real files)

`engine_pct: 73` (up from 72) is a **security + safety + side-effect-integrity hardening**
run (no new edge). (#96) closes the last unguarded state-mutating route — `/prediction-markets/scan`
now carries the shared-secret bearer like its sibling `/bot/scan-now` — bounds the user inputs
(`market_limit`/search `limit`/`query`/kill-switch `reason`), and **bounds-validates `risk/config`**
so a non-positive `daily_loss_limit_usd` (which would DISABLE the loss cap) is rejected 422
(pure `risk_config_validation.py` in the CI gate). (#95) removes a **phantom fill**: the orchestrator
built one empty-token order for multi-leg `outcome_idx == -1` arbitrage baskets that the paper
executor "filled," booking a position that never traversed a real per-leg path — now skipped honestly
until per-leg execution (B1) exists. (#94) makes the durable-state guard **actually fail closed**:
a rehydrate failure trips the kill switch instead of silently resuming a halted bot (an Opus auditor
proved the first cut was dead code because the store swallowed read errors; fixed so `load()` raises
on an unreadable store + a real-store fail-closed test, re-audit FIX-HOLDS) + a defense-in-depth
empty-token reject at the executor gate. The validated EDGE is still absent (binding constraint stays
the 7-day-lead OOS corpus, OA-11 / OA-15), so no DoD/floor box ticks.

### Prior

`engine_pct: 72` (up from 71) adds a **second venue DATA adapter** + a fresh deep-audit
hardening pass (no new edge). A3: `kalshi_client.py` + `kalshi_history_fetcher.py` ingest
public Kalshi market data + leakage-safe resolved history behind the SAME `Market`/`Outcome`
interface (offline-validated; the live status/price contract is documented-but-unverified,
disclosed honestly; an adversarial parsing auditor caught — and the maker fixed — a
BUILDS≠WORKS where the offline fixtures encoded request-filter words as live response values
that would have dropped every live market). Hardening (#91): a live-only boot-guard that
refuses to start with `LIVE_TRADING_ENABLED` on while `BACKEND_API_TOKEN` is empty (no
unauthenticated kill-switch/execute on a real-money deploy), a category-cap under-count fix
keyed to the executor's REAL per-trade cap, risk-score div-by-zero guards, MTM client reuse,
and API exception-detail leak sanitization (§12). The validated EDGE is still absent (the
binding constraint stays the 7-day-lead OOS corpus, OA-11 / now also Kalshi OA-15), so no
DoD/floor box ticks. Prior rationale (engine_pct 71, up from 70) is run-risk-readiness +
security + side-effect hardening of the
control path (no new edge): the kill-switch + realized-PnL loss counters now PERSIST and
rehydrate across a restart (`executor_state_store.py`) — and a BUILDS≠WORKS fix makes the
durable audit-log/registry/executor tables actually get created at startup (they silently
no-op'd before); state-mutating backend routes are now guarded by a degrade-safe shared-secret
token (`auth_core.py` + OA-14); and the REST order path validates the venue body so no fill is
reported without a real acknowledgement (D1). The validated EDGE is still absent (the binding
constraint stays the 7-day-lead OOS corpus, OA-11), so no DoD/floor box ticks. Prior rationale
(engine_pct 70, up from 68) adds the FIRST `model_prob != crowd` alpha mechanism
(`CalibrationBucketStrategy` — the per-bucket empirical-calibration model + strategy, the
EXP-002 build, leakage-safe + abstaining + 3-Opus-auditor-clean), WIRES the last two pure
learning engines into the running system (E5 evaluation-windows + E2 calibration-drift now
flow from the resolved stream through new read-only endpoints with an honest
degenerate/insufficient-data path), and makes paper metrics VISIBLE end-to-end (the
`frontend/components/metrics/` dashboard renders every `/metrics/*` endpoint with honest
empty/degenerate states). The validated EDGE itself is still absent — the calibration-bucket
strategy is the MECHANISM that *could* produce model_prob != crowd, but proving a real edge
needs the 7-day-lead OOS corpus (OA-11, owner/egress-scope), so no DoD/floor box ticks and
the bulk of the missing % remains. Prior rationale (engine_pct 68, up from 66) WIRES the
previously-pure learning-loop engines into the
running system and adds two more: per-strategy realized-PnL attribution (E6) flows from
resolved positions through a new `/metrics/per-strategy` endpoint; the alpha-lifecycle
registry (B3) is now persisted (a durable singleton table) + exposed read-only, seeded
honestly with deployed strategies as PROPOSED (truthfully: no alpha has passed the
integrity gate); market RESOLUTION losses now feed the per-strategy drawdown auto-disable
(D2 — the dominant binary-loss path was bypassing it); the only true logical-arbitrage
strategy now costs its basket through the canonical cost model + gates the multi-outcome
branch on `neg_risk` MECE (B5 honesty); and two new pure learning engines exist — an
evaluation-window engine with realized-vs-backtest overfit reconciliation (E5) and a
significance-gated calibration-drift detector (E2, FP-rate ~1–4% vs 47% for a naive
point comparison). The validated EDGE itself is still absent (no model_prob != crowd
alpha), and B3 evidence is still caller-asserted (authenticity-derivation is a named
follow-up), so the bulk of the missing % remains. Prior rationale (engine_pct 66, up from
64) adds this run's learning-loop engine pieces: the alpha
lifecycle registry with a fail-loud integrity gate (B3) + the per-strategy realized-PnL
attribution primitive (E6) — both pure/deterministic, the first concrete E-track
infrastructure — plus the hardened cross-market relatedness screen (B5), the
code-enforced Bonferroni multiple-comparison correction on the calibration gate (B2), and
the now-functional wall-clock staleness gate (A5). These are engine/quality/integrity
pieces; the lifecycle + attribution engines are not yet wired into the live loop, and the
validated edge ITSELF is still absent (the canary honestly shows 0 trades / no edge), so
the bulk of the missing % remains. Prior rationale (engine_pct 64, up from 61): this run's
end-to-end metrics wiring (C5 backend +
API), the venue-layer fail-closed live gate (D5 defense-in-depth), the real-data
reproduction canary (C3/F2), the forensic strategy-audit harness (B5 groundwork), and
enforced LLM timeout + spend cap (G2) — all engine/safety/measurement pieces. The
validated edge ITSELF is still absent (the canary honestly shows 0 trades / no edge), so
the bulk of the missing % remains. Prior rationale (engine_pct 61, up from 58: the
leakage-safe resolved-history fetcher
(A2 ingest — the named code blocker for OOS validation), the market-impact cost model
applied inside the walk-forward backtest (C2/C3 remainder), and the durable decision +
would-be-order audit log (G3) all landed this run. These are engine/safety pieces toward
a validated edge; the validated edge ITSELF is still absent — now gated on an
ENVIRONMENTAL egress block (Polymarket is unreachable from the autonomous env), not on
missing code — and remains the bulk of the missing %):

**Exists (counts toward %):**
- Polymarket ingestion + websocket feeds — `backend/app/prediction_markets/polymarket_client.py`, `websocket_feeds.py`
- Strategies + edge/EV + Kelly sizing — `strategies.py`, `advanced_strategies.py`, `quant_models.py`, `orchestrator.py`
- Paper/forward execution — the dry-run `execution.py` executor + the forward paper cycle `scripts/run_paper_cycle.py` (rehydrates OPEN positions across runs — ROADMAP D8, #143; the standalone `paper_simulator.py` was retired as dead code in #126)
- Risk manager + category caps — `risk_manager.py`
- Kill switch — `execution.py`
- Backtest/validation/metrics infra — `backend/app/backtest/*`

**Exists from prior runs (counts toward %):**
- Leakage-free, deterministic walk-forward backtest ENGINE (C1/C3 engine) — `prediction_markets/walk_forward.py` (+ `scripts/run_walk_forward.py`)
- Significance-gated calibration eval (B2) — `prediction_markets/calibration.py`
- Data-quality gates at the scan path (A5) — `prediction_markets/data_quality.py` (wired into `orchestrator`)
- Weekly-metrics aggregator (C5) — `prediction_markets/weekly_metrics.py`
- C2 unify: `execution.py` sources its fill rates from `cost_model` (drift fails loud)

**Added this run (counts toward %):**
- Leakage-safe resolved-history fetcher (A2 ingest — the named code blocker for OOS validation) — `prediction_markets/polymarket_history_fetcher.py`
- Market-impact / order-book-depth cost model, applied size-aware in the backtest (C2/C3 remainder) — `cost_model.effective_buy_price_with_impact` + `walk_forward._settle`
- Durable decision + would-be-order audit log (G3 DONE) — `prediction_markets/audit_log.py` (observer in `orchestrator`)

**Missing (keeps % < 100):**
- **Validated, reproducible, cost-realistic out-of-sample weekly-PnL series on REAL data (no proven edge)** — the engine + the ingest fetcher exist; running the fetcher on real history is EGRESS-BLOCKED in the autonomous env (OA-11: run where Polymarket is reachable)
- A *passing* calibration eval on real resolved markets + live strategy probabilities (B2 → unlocks B4)
- Market-impact model CALIBRATED against real OrderBook depth (the current model is a conservative non-calibrated toy)
- Full live path built + paper-validated (D6)
- A4 event/market-universe + persistent resolution tracking; metrics wired end-to-end into the live run/dashboard (C5 remainder)

`engine_built` flips to `true` (and `engine_pct` to `100`) **only** when the DoD in
ROADMAP is fully `[x]` with proof.
