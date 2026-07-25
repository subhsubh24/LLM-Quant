# SELF-VALIDATION MANIFEST — can the loop really validate every capability?

> **Purpose.** The blocking gate validates the core paper pipeline deterministically. This
> manifest extends that guarantee to **every** capability the app has: each one must carry an
> honest validation story, and the loop must never silently ship a capability it cannot really
> validate. Enforced by `scripts/check_self_validation.py` as a **blocking** preflight step.

## The policy (enforced mechanically)

1. **Coverage.** Every capability that is **active** (reachable in a real flow) must be
   `validated` (really exercised in the gate — in-process/deterministic or via a CI secret),
   `gated_off` (built but unreachable, and the gate proves it's off), or `degrades_safely`
   (works without its credential, producing no fake output). An active capability that is
   `unvalidated` or `needs_credential` **fails the gate → blocks every merge.**
2. **Credential declaration (the "new service surfaces + blocks" rule).** Every external
   credential the **code reads** — a credential-shaped field in `config.Settings` or an
   `os.environ.get("X")` of the same shape under `backend/app` — must be declared in
   `credential_inventory`. A **new, undeclared** credential **fails the gate.** So when the loop
   builds a capability needing a new key, it cannot ship until it declares how that capability is
   validated and, if a key is genuinely required, records the owner action — at which point the
   missing key is **surfaced** (here + in PENDING_OPS) and **subsequent PRs are blocked** until
   the owner provides it or the capability is gated off.

**Resolution when a credential the CI gate lacks is required:** either the owner sets it (env /
GitHub Actions secret) so real validation runs, **or** the loop gates the capability OFF so no
active flow depends on an unvalidated path. Live real-money keys are HUMAN-CORE and only ever
*activate* a capability — they are never needed to *validate it as gated-off*.

```yaml
SELF_VALIDATION:
  as_of: 2026-07-12
  # ci_validatable: can the gate REALLY validate this with NO owner-only secret? An ACTIVE
  # capability with ci_validatable:false is UNMET -> it surfaces (urgent OWNER_ACTION +
  # LOOP_HEALTH validation.unmet) and blocks merges. real_flow_note (pitfall #5): for a
  # mock/degrade/gated capability, where the genuinely-critical path is really exercised.
  capabilities:
    - id: paper_pipeline
      desc: "scan -> Kelly-size -> paper execute -> PnL, deterministic"
      validates_via: "scripts/runtime_harness.py + backend/tests/test_prediction_markets.py"
      mode: in_process_deterministic
      requires_env: []
      active: true
      ci_validatable: true
      status: validated
    - id: risk_and_kill_switch
      desc: "loss caps + kill switch + position caps reject/halt orders"
      validates_via: "runtime_harness.py + test_loss_caps.py (real REJECT/halt asserted)"
      mode: in_process_deterministic
      requires_env: []
      active: true
      ci_validatable: true
      status: validated
    - id: executor_state_persistence
      desc: "kill switch + realized-PnL loss counters persist across restart (run-risk-readiness)"
      validates_via: "test_executor_state_persistence.py — tripped kill switch + accumulated loss rehydrate on a fresh executor (in-memory SQLite); bare executor stays isolated; best-effort never raises"
      mode: in_process_deterministic   # in-memory SQLite; durable Neon is OA-10
      requires_env: [DATABASE_URL]      # optional; falls back to local SQLite, degrades to in-memory-only
      active: true
      ci_validatable: true             # exercised against in-memory SQLite; no secret needed to validate
      status: validated
    - id: backend_route_auth
      desc: "shared-secret bearer token on state-mutating routes (kill-switch/config/execute/bot/scan), DEFAULT-CLOSED: no token => DENY (401) unless BACKEND_AUTH_DISABLED=1 dev opt-out; risk-config bounds-validated (a non-positive loss cap can't disable the control)"
      validates_via: "test_backend_auth.py (pure token decision: exact-Bearer + constant-time when set) + test_risk_config_validation.py (pure bounds: reject non-positive/NaN/inf/absurd risk limits) in the CI gate; test_backend_auth_fastapi.py exercises the FastAPI adapter POLICY (default-closed 401 when no token + no opt-out; open on BACKEND_AUTH_DISABLED; enforced when a token is set; /scan guard + bounds return 401/422) and is REGISTERED in the CI gate since fastapi+httpx landed in requirements-ci.txt (#283) — app.api.routes/auth/main import cleanly under the light dep set, so the adapter half now validates IN the required gate (importorskip retained as defence-in-depth for a fastapi-absent standalone run)"
      mode: fail_closed
      requires_env: [BACKEND_API_TOKEN]  # unset => DENY (default-closed); BACKEND_AUTH_DISABLED=1 is the dev opt-out (never honoured with live money — config refuses to boot)
      active: true
      ci_validatable: true             # the default-closed DENY, the dev-opt-out OPEN, AND the enforced-token decision are all tested without any secret; the token only sets the credential
      status: degrades_safely            # absent token => CLOSED (deny), the SAFE degradation; set => enforced; BACKEND_AUTH_DISABLED => open (dev only). Owner activates (OA-14).
    - id: strategy_enable_disable
      desc: "per-strategy enable/disable control (ROADMAP B6): auth-gated POST /prediction-markets/strategies/{name}/{enable,disable} toggles which strategies the scan loop runs, PERSISTED (StrategyEnableStore) + respected across restarts; reaches both top-level strategies and adaptive-wrapper inner strategies (not a fake control). No new credential; a persistence hiccup fails OPEN (all enabled) — operational preference, not a safety gate"
      validates_via: "test_strategy_enable_disable.py — drives a real offline scanner.scan() and asserts a disabled strategy's results DISAPPEAR (top-level AND wrapped-inner), that an unknown name is a rejected no-op, that the disabled set persists+rehydrates on a fresh StrategyEnableStore (in-memory SQLite), and that apply_persisted_strategy_states re-applies it at scanner build; PLUS route-level tests in test_backend_auth_fastapi.py exercise the two HTTP endpoints directly — 401 tokenless-when-token-set (guard before handler), 422 name-path max_length bound, and 404 on an unknown strategy name (rejected before any persist)"
      mode: in_process_deterministic   # in-memory SQLite; verifies the EFFECT (which strategies run), not the message
      requires_env: []                  # optional DATABASE_URL for durable persist; falls back to local/in-memory
      active: true
      ci_validatable: true             # exercised end-to-end against a fake client + in-memory SQLite; no secret needed
      status: validated
    - id: live_trading_path
      desc: "real-order placement on Polymarket (the gated live path)"
      validates_via: "runtime_harness asserts the live gate + kill switch BLOCK real orders deterministically"
      mode: gated_off_proven        # built; LIVE_TRADING_ENABLED=false; validated AS gated-off
      requires_env: [POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER]
      active: false                 # not reachable until the owner activates (human-core)
      ci_validatable: true          # the gated-off PROOF needs no key; live activation is human-core, never a CI target
      real_flow_note: "the money-critical side-effect (order placement) is REALLY exercised: the harness drives a real order through execution.py and asserts the gate REJECTS it — not a stub."
      status: gated_off
    - id: llm_analysis
      desc: "Gemini-driven market/research analysis"
      validates_via: "MOCK/degraded (required gate): config.has_llm_key gates use; without the key it falls back to templates (no fake output). REAL (non-blocking): scripts/live_integration_smoke.py makes a real Gemini call when GEMINI_API_KEY is set (scheduled job) — dual-validated."
      mode: degrades_without_key
      requires_env: [GEMINI_API_KEY]
      active: true
      ci_validatable: true          # the degraded (no-key) path is validated in the required gate; the REAL path is exercised by the non-blocking live smoke (not the deterministic gate)
      real_flow_note: "analysis is advisory, never an order side-effect; the no-key template path is exercised in-gate, the real Gemini path in the live smoke; a real key only enriches text (enhancement, not a critical path)."
      status: degrades_safely       # absent key => templates, never a fabricated analysis
    - id: db_persistence
      desc: "audit log + state persisted to Neon (prod) / SQLite (dev)"
      validates_via: "tests use in-memory SQLite; SQLModel.create_all idempotent; durable hosting is OA-10"
      mode: in_process_deterministic
      requires_env: [DATABASE_URL]  # optional; falls back to local SQLite
      active: true
      ci_validatable: true          # same ORM path exercised against SQLite; Postgres is the same SQLAlchemy dialect surface
      status: validated
    - id: polymarket_market_data
      desc: "read public Polymarket market data + assemble leakage-safe resolved history — Gamma/CLOB live reads AND the HuggingFace Polymarket-v1 archive (daily_aligned), no auth"
      validates_via: "MOCK (required gate): the Gamma/CLOB fetcher + client tested offline with FakeSession (test_history_fetcher.py, test_polymarket_parse.py); the HuggingFace Polymarket-v1 fetcher's pure leakage-safe assembly tested offline on realistic daily_aligned rows with NO heavy deps (test_polymarket_v1_hf_fetcher.py). REAL (non-blocking): scripts/live_integration_smoke.py reads real public markets on a network-permitted runner. The HF archive is WIRED into scripts/validate_real_oos.py as the OPT-IN venue `polymarket_v1_hf` (NOT in the default cron venue set polymarket,kalshi) — run on a permitted host with `datasets` installed (`validate_real_oos.py --venues polymarket_v1_hf`); a missing `datasets` dep reports N/A, never a false red. Live reads in the cloud loop are egress-gated (OA-13/OA-16)."
      mode: mocked_offline
      requires_env: []              # NO credentials — Gamma/CLOB are public, the HF dataset is CC-BY-4.0 public
      active: true
      ci_validatable: true          # no secret needed; the logic-critical part is parsing/anti-leakage, tested on realistic fixtures; the REAL reads are exercised by the live smoke / permitted lane
      real_flow_note: "the critical logic is PARSING + anti-leakage (exercised on real-shaped fixtures + the live smoke's real read + the OA-11 real fetch); the HF fetcher LAZY-imports datasets only on a real download (never in CI) and its leakage-safe assembly is pure + offline-tested; the exact daily_aligned schema is VERIFIED on the first real download (logs the columns, RAISES with the actual keys on a required-field mismatch — no silent mis-parse)."
      status: validated
    - id: paper_trading_forward
      desc: "FORWARD paper-trading on REAL live markets — scan real open markets, decide, record AS-IF filled (cost-aware, NO venue call), book realized PnL on resolution. 'Live trading validation with paper money.'"
      validates_via: "MOCK/deterministic (required gate): scripts/runtime_harness.py proves a paper order really fills + the live gate blocks real orders, reproducibly. REAL/forward (non-blocking scheduled): scripts/run_paper_cycle.py drives orchestrator.scan_and_execute() + check_resolutions() against live markets on a network-permitted host. Safety belt: test_live_validation_tiers.py asserts it REFUSES to run when LIVE_TRADING_ENABLED is true."
      mode: gated_off_proven          # runs ONLY in dry_run/paper mode; real order placement is human-core, never automated
      requires_env: []                # public data, NO credentials; durable forward record wants DATABASE_URL (Neon) on the runner
      active: true
      ci_validatable: true            # the deterministic paper fill + gate-block is validated in-gate with no secret; the forward run is the non-blocking scheduled tier
      real_flow_note: "NEVER places a real order: uses the dry_run executor + the LIVE_TRADING_ENABLED gate (doubly enforced) + a runner-level refusal if live is on. Fills are cost-aware (C2/C3), not fantasy mid. PnL is only booked when a market actually resolves — an honest forward test, not a fabricated number."
      status: validated
    - id: kalshi_market_data
      desc: "read public Kalshi market data + assemble leakage-safe resolved history (no auth)"
      validates_via: "test_kalshi_client.py + test_kalshi_history_fetcher.py — parsing + anti-leakage core (incl. the LIVE + HISTORICAL /historical/* tier + the dollar candlestick schema) exercised offline with FakeSession fixtures; live reads are egress-gated (run on a network-permitted host, e.g. this run's build env which happened to have egress)"
      mode: mocked_offline
      requires_env: []              # NO credentials required; Kalshi market data is public
      active: true
      ci_validatable: true          # no secret needed; the logic-critical parts (parsing + anti-leakage) are tested on realistic fixtures
      real_flow_note: "the critical logic is PARSING + anti-leakage (exercised on real-shaped fixtures, fully offline); live HTTP read is a thin GET with no business logic and no side-effect; owner (or a network-permitted runner) runs fetch_kalshi_history.py. CONTRACT NOW LIVE-CONFIRMED (2026-07-23, HTTP 200 probes): the resolved-market status/result contract AND the candlestick PRICE UNIT are verified against real responses — Kalshi serves candle prices in DOLLARS ([0,1]), under explicit *_dollars keys on the LIVE /series/.../candlesticks feed and under bare decimal-STRING keys on the /historical/markets/{t}/candlesticks feed (the `*_dollars` migration #397 first saw on the list feed). _candle_price reads both dollar schemas as-is (never /100 — that would fabricate 0.0067 from a real $0.67) while still supporting the legacy numeric-cents fixtures; the deep /historical/* tier (reached via fetch_resolved_markets(historical=True)) is what makes multi-year Kalshi resolved history (EXP-009 employment calibration, B8 co-listed crypto) fetchable past the live ~3-month cutoff. An unrecognized settlement result is still logged LOUDLY."
      status: validated
    - id: manifold_market_data
      desc: "read public Manifold Markets data + assemble leakage-safe resolved history (no auth) — RESEARCH ONLY (PLAY MONEY)"
      validates_via: "test_manifold_history_fetcher.py (now REGISTERED in the blocking preflight gate, #258) — parse + anti-leakage core exercised offline with injected bet histories (decision price is a pre-decision probAfter; settled outcome never the decision price; RAISES rather than fabricating). STRUCTURAL research-only guardrail (#259): records carry research_only=True and the real-money floor lane (validate_real_oos.evaluate) REFUSES them — test_validate_real_oos.test_floor_lane_refuses_research_only_play_money_records"
      mode: mocked_offline
      requires_env: []              # NO credentials required; Manifold market data is public
      active: true
      ci_validatable: true          # no secret needed; parsing + anti-leakage tested on injected fixtures; live probe is a thin read
      real_flow_note: "RESEARCH ONLY — Manifold is PLAY MONEY. A Manifold finding validates the METHOD (can a model beat a softer crowd?) and NEVER counts toward the profit floor, go-live-eligibility, or any real-money decision. NO orders, NO money, NO credentials. The critical logic is PARSING + anti-leakage (offline fixtures); the live read (scripts/manifold_research_probe.py) is a thin GET with no side-effect. Live probe RAN 2026-07-07: 2147 leakage-safe records, crowd Brier 0.144, ECE 0.027, only 18.5% pinned (7-day lead). HONEST framing (per an adversarial auditor): the 0.144 Brier is NOT apples-to-apples with the real-money crowds' ~0.09 — it is driven by far LESS pinning (18.5% vs ~70%) + a longer lead (7d vs 2d), not worse calibration; ECE 0.027 is LOW, so the play crowd is actually well-calibrated on this sample. So this is a less-pinned/longer-horizon research corpus, NOT proven a 'softer, beatable' crowd — a method must still be run and beat it OOS. (2026-07-08: the 'materially softer crowd' overclaim was corrected across ROADMAP/loop-memory/LOOP_HEALTH to match THIS framing; and the research-only property is now STRUCTURALLY enforced, not convention-only — #259.)"
      status: validated
    - id: cost_telemetry
      desc: "emit LLM cost-per-outcome economics to the external Margin ingest service (unit-economics observability, §24/§25) — advisory telemetry, NEVER on the trading/order path"
      validates_via: "test_llm_safety.py::test_margin_meter_emits_blocking_in_the_call_flow (a fake margin_meter proves the emit is a BLOCKING call in the request's OWN thread — the #312 fix; a fire-and-forget daemon thread the serverless freeze drops would run it in a different thread and FAIL the test) + test_margin_meter_absent_degrades_safely (margin_meter absent => returns model text, no error, no emit)"
      mode: degrades_without_dep       # the margin-meter PyPI dep is deliberately NOT in requirements-ci.txt; absent => a safe no-op
      requires_env: [MARGIN_INGEST_URL, MARGIN_INGEST_KEY]  # owner-optional; both unset => telemetry disabled (no network I/O), never blocks
      active: true
      ci_validatable: true             # the BLOCKING-emit contract AND the safe-degrade are both validated in-gate with a fake meter; no secret needed
      real_flow_note: "PURELY ADVISORY telemetry — every emit is wrapped in try/except and bounded by the meter's 2.0s timeout, so it can NEVER affect the trading/order path or its result (`return response.text` is unchanged whether the emit succeeds, fails, or is skipped). The MARGIN_INGEST_URL/KEY credentials are read INSIDE the margin_meter PyPI package (not repo code), so the self-validation credential scanner does not force them — declared here for capability-honesty (#310/#312 added the active capability without declaring it). Absent dep OR unset URL/KEY => a safe no-op, never a fabricated emit."
      status: degrades_safely          # absent margin_meter dep or unset MARGIN_INGEST_* => no emit, never fake output
    - id: oos_reproducibility
      desc: "reproduce a REAL (not just synthetic) out-of-sample result OFFLINE from a committed FROZEN corpus — the leakage-safe Polymarket resolved-market corpus (data/real_oos_corpus_polymarket.json, N=187) replays the crowd-baseline + B4a-alpha walk-forward + F10/F11 gates deterministically, with NO egress (ROADMAP F2 / backtest integrity A→A+)"
      validates_via: "test_frozen_corpus_replay.py (REGISTERED in the blocking gate): loads the committed corpus, asserts it is structurally leakage-safe + real-money-only, that offline replay is bit-for-bit DETERMINISTIC (same seed → same seed_hash + PnL), that serialization round-trips losslessly (byte-stable artifact), that the frozen result NEVER claims a validated edge (F10 fragility / F11 significance must reject it), and that the #259 play-money guardrail still fires on the frozen path. The corpus is produced by `validate_real_oos.py --freeze-corpus` on a Polymarket-permitted host and replayed anywhere via `--from-corpus`."
      mode: committed_artifact         # pure offline replay of committed bytes — no network, no credentials
      requires_env: []                 # NONE — replay reads a committed file; the FREEZE step uses PUBLIC Gamma/CLOB (no auth)
      active: true
      ci_validatable: true             # fully validated in-gate with no secret — committed data replayed deterministically
      real_flow_note: "The frozen corpus is REAL leakage-safe resolved-market data (the fetcher RAISES rather than fabricating a decision price; the settled outcome is NEVER the decision price). It carries NO edge claim — the committed corpus's B4a alpha is F11 significant_NEGATIVE (net -$3,228 OOS, 95% CI excludes 0 on the negative side), an honest REFUTATION made reproducible, not an edge. `liquidity` is stored as null: Gamma's `liquidity` is a USD metric, NOT order-book contract-depth, so it is deliberately NOT mapped onto HistoricalMarket.liquidity — mapping it would be a units fabrication that would activate the uncalibrated market-impact path with wrong-units depth."
      status: validated
    - id: exp006_robustness_surface
      desc: "EXP-006 pre-registered (threshold × window × horizon) config robustness surface over the committed spike corpus — answers whether the default's EDGE-NOT-PROVEN is config-fragile or config-family-wide, WITHOUT ever claiming an edge (in-sample; report-all-cells, select-none)"
      validates_via: "test_spike_robustness_surface.py (REGISTERED in the blocking gate): asserts the 5×4×3=60-cell pre-registered grid, deterministic re-run, that the default cell TABULATES the standalone fade engine verbatim (never re-derives the gate), that a momentum corpus yields FAMILY-NULL-STRONG, and that the surface NEVER exposes a revenue / validated-edge field at the family level (selection is refused)."
      mode: committed_artifact         # pure offline sweep of the committed corpus via the already-validated fade engine — no network, no credentials
      requires_env: []                 # NONE — reuses data/spike_corpus_politics.json.gz + the deterministic engine
      active: true
      ci_validatable: true             # fully validated in-gate with no secret — committed corpus + seeded engine reproduce identically
      real_flow_note: "This capability carries NO edge claim and reaches NO revenue field. It reuses the SINGLE committed corpus, so it is a WITHIN-SAMPLE config-sensitivity map by construction — no cell can be a validated edge, however green, and selecting the greenest cell is refused as p-hacking. Its only outputs are a family verdict (FAMILY-NULL-* / HYPOTHESES-FLAGGED-NOT-AN-EDGE) and, at most, hypotheses for a FRESH pre-registered OOS on NEW data. The critical honesty path (that a green cell is never promoted to an edge) is exercised directly by the test."
      status: validated
    - id: exp010_cost_realism_rescore
      desc: "EXP-010 cost-model-realism re-score — re-price the committed leakage-safe OOS corpus (data/real_oos_corpus_polymarket.json) under Polymarket's REAL documented price-dependent, per-category taker-fee formula (feeRate·p·(1-p)) instead of the flat 2%, and check whether any already-refuted verdict is a cost-model artifact. Predicted + observed NULL (the refutation is cost-model-robust; the longshot-heavy corpus is scored MORE punitively under the real formula)."
      validates_via: "test_exp010_cost_realism.py (REGISTERED in the blocking gate): pins the DEFAULT (flat) path bit-identical (category inert without a fee_schedule — the pinned walk-forward reproduction hash in test_walk_forward_pm.py is unaffected), pins PolymarketFeeSchedule's per-category rates + the vanish-at-extremes + symmetric-in-p formula + the conservative fallback for unmapped categories, asserts the crossover direction (real cheaper only above p>1-0.02/feeRate), and asserts the re-score on the committed corpus is DETERMINISTIC and flips NEITHER model to a validated edge (flip_to_validated_edge=False)."
      mode: committed_artifact         # pure offline re-score of the committed corpus via the walk-forward engine — no network, no credentials
      requires_env: []                 # NONE — reuses data/real_oos_corpus_polymarket.json + the deterministic engine
      active: true
      ci_validatable: true             # fully validated in-gate with no secret — committed corpus + seeded engine reproduce identically
      real_flow_note: "This capability carries NO edge claim and reaches NO revenue field — it changes a COST INPUT (fee realism, which VISION requires) and re-tests an already-committed refutation, it does NOT re-parameterize a strategy. A flip_to_validated_edge would NOT be an edge: it is surfaced as a CANDIDATE requiring >=3 FRESH adversarial Opus auditors before any claim; the observed result is flip=False (the honest, predicted NULL — real net -$3,502 vs flat -$3,228, both F11 significant_NEGATIVE). The honesty path (a flip is never auto-promoted; the fallback fee-rate for unmapped categories is the conservative highest documented rate) is exercised directly by the test."
      status: validated
    - id: simulation_pricer_probability_override
      desc: "Monte-Carlo simulation pricer that can REPLACE a strategy's own win_probability on the live/paper sizing path and re-size the bet (orchestrator.size_from_scan_result). DEACTIVATED 2026-07-25: it ran on a hardcoded vol=0.3 / T=30/365 — market-agnostic FABRICATED constants, with the market's real end_date available and ignored — and inflated real bet sizes (measured +37.5% at price 0.62) on a path NO test covered (all 9 test call sites set use_monte_carlo=False while the production default was True, so backtest sizing != live sizing). It was also constructed UNSEEDED, making the production-default paper path non-deterministic."
      validates_via: "test_simulation_pricer_sizing.py (REGISTERED in the blocking gate), 13 tests: asserts the capability is OFF by default (KellyConfig().use_simulation_pricer is False); that the DEFAULT config sizes IDENTICALLY to explicitly-disabled (the property the 9 pre-existing test call sites assumed but never verified); that use_monte_carlo=True alone — still the production default for the SEPARATE, evidence-backed mc_kelly path — no longer drags this override along with it; that when explicitly enabled it SKIPS rather than fabricating whenever the horizon cannot be derived from the market's real end_date or vol is not supplied; that T comes from the real end_date (never the old 30/365) and the pricer is constructed SEEDED; and that repeated sizing of identical inputs is bit-identical."
      mode: gated_off_proven           # default-OFF; the gate itself is what the tests exercise, not a mock standing in for a live flow
      requires_env: []                 # NONE — no credential; pure in-process sizing computation
      active: false                    # DEFAULT-OFF. Enabling is a deliberate, reviewable config act.
      ci_validatable: true             # fully validated in-gate with no secret
      real_flow_note: "The gated-off state is the HONEST one, not a convenience: the pricer remains UNCALIBRATED and has never been shown to round-trip against the market price. Because it is systematically biased away from the market price, its >0.02 disagreement override fired on essentially every market. Gating it off is what makes backtest sizing == live sizing again. This is NOT a stub hiding an un-exercised critical path — the sizing path it sits on IS exercised, by 13 tests here plus the 9 pre-existing sizing tests, and the runtime harness continues to produce real paper fills through it. Re-activation requires (a) a round-trip test against the market price with a market-derived vol and (b) a per-market volatility measured from real data (ROADMAP E9); it is NOT re-enabled by this or any loop run."
      status: gated_off
  # The dashboard validation feed (mirror of LOOP_HEALTH.validation; computed by
  # `check_self_validation.py --readiness`). unmet MUST be empty here AND in LOOP_HEALTH.
  readiness:
    enforced_in_ci: true
    capabilities_total: 17
    unmet: []                       # active + ci_validatable:false. NON-EMPTY => urgent OWNER_ACTION + blocks.
  # Every credential the CODE reads must appear here (checker enforces). new + undeclared => gate FAILS.
  credential_inventory:
    GEMINI_API_KEY:        {capability: llm_analysis, needed_to: enhance_analysis, owner_action: null}
    DATABASE_URL:          {capability: db_persistence, needed_to: durable_persist, owner_action: OA-10}
    BACKEND_API_TOKEN:     {capability: backend_route_auth, needed_to: protect_state_mutating_routes, owner_action: OA-14}
    POLYMARKET_API_KEY:    {capability: live_trading_path, needed_to: activate_live, owner_action: OA-5}
    POLYMARKET_API_SECRET: {capability: live_trading_path, needed_to: activate_live, owner_action: OA-5}
    POLYMARKET_PASSPHRASE: {capability: live_trading_path, needed_to: activate_live, owner_action: OA-5}
    POLYMARKET_PRIVATE_KEY: {capability: live_trading_path, needed_to: activate_live, owner_action: OA-5}
    POLYMARKET_FUNDER:     {capability: live_trading_path, needed_to: activate_live, owner_action: OA-5}
    MARGIN_INGEST_URL:     {capability: cost_telemetry, needed_to: emit_cost_telemetry, owner_action: null}
    MARGIN_INGEST_KEY:     {capability: cost_telemetry, needed_to: emit_cost_telemetry, owner_action: null}
  unvalidated_blocking: []   # active + unvalidated capabilities. NON-EMPTY => gate fails. Empty = green.
```

## How the loop uses this (factory routine discipline)

When a change adds or activates a capability: add/refresh its entry here in the **same** PR.
If it reads a new credential, add it to `credential_inventory`. If that credential is required
for the capability to actually work (not just enhance it) and the CI gate can't supply it, you
have two honest moves — **gate the capability off** (`status: gated_off`) so nothing active
depends on it, or **record the owner action** (PENDING_OPS) and mark it `needs_credential` /
list it in `unvalidated_blocking`, which **blocks every subsequent PR** until the owner provides
the key. Never fake a validation to get green (side-effect integrity), and never ship an active
capability with no validation story.

## Readiness + surfacing (cross-factory addendum)

`scripts/check_self_validation.py --readiness` is the **readiness** mode wired into the gate
(preflight step 9d). It runs coverage + credential checks AND surfaces **unmet** capabilities.

- **`ci_validatable`** per capability: can the gate REALLY validate it with **no owner-only
  secret**? An **active** capability with `ci_validatable: false` is **UNMET**.
- **An unmet capability must be visible in BOTH dashboard channels or it's a bug:** an urgent
  PENDING_OPS `OWNER_ACTION` id `validation-capability-<service>` **and**
  `LOOP_HEALTH.validation.unmet`. The checker fails if an unmet capability is missing from either.
- **`readiness` block** here mirrors `LOOP_HEALTH.validation` (`enforced_in_ci`,
  `capabilities_total`, `unmet`); the loop refreshes both every run.

Pitfalls deliberately handled: scan covers **only `backend/app` runtime code** (not tests/
scripts/CI — no false drift from CI-only env vars); the YAML parser (`pyyaml`) is a **declared**
CI dependency and the gate **fails, never skips**, if it's absent; **two modes** — the default
coverage check and `--readiness` (wired into the ship gate, any unmet fails). LLM-Quant runs the
full readiness check on **every** PR (stronger than per-PR scoping), so no base-diff/`fetch-depth`
machinery is needed. **Honesty (pitfall #5):** a capability marked `validated` via a
mock/degrade/gated path carries a `real_flow_note` showing the genuinely-critical path is really
exercised — and the adversarial auditors reconcile that a "validated" capability isn't a stubbed
critical flow (the email-verification trap in a new form).
