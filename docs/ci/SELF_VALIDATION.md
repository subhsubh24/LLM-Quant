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
  as_of: 2026-07-08
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
      validates_via: "test_backend_auth.py (pure token decision: exact-Bearer + constant-time when set) + test_risk_config_validation.py (pure bounds: reject non-positive/NaN/inf/absurd risk limits) in the CI gate; test_backend_auth_fastapi.py exercises the FastAPI adapter POLICY (default-closed 401 when no token + no opt-out; open on BACKEND_AUTH_DISABLED; enforced when a token is set; /scan guard + bounds return 401/422) where fastapi is installed (importorskip — CI-skipped, run locally)"
      mode: fail_closed
      requires_env: [BACKEND_API_TOKEN]  # unset => DENY (default-closed); BACKEND_AUTH_DISABLED=1 is the dev opt-out (never honoured with live money — config refuses to boot)
      active: true
      ci_validatable: true             # the default-closed DENY, the dev-opt-out OPEN, AND the enforced-token decision are all tested without any secret; the token only sets the credential
      status: degrades_safely            # absent token => CLOSED (deny), the SAFE degradation; set => enforced; BACKEND_AUTH_DISABLED => open (dev only). Owner activates (OA-14).
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
      validates_via: "test_kalshi_client.py + test_kalshi_history_fetcher.py — parsing + anti-leakage core exercised offline with FakeSession fixtures; live reads are egress-gated (same as Polymarket)"
      mode: mocked_offline
      requires_env: []              # NO credentials required; Kalshi market data is public
      active: true
      ci_validatable: true          # no secret needed; the logic-critical parts (parsing + anti-leakage) are tested on realistic fixtures
      real_flow_note: "the critical logic is PARSING + anti-leakage (exercised on real-shaped fixtures, fully offline); live HTTP read is a thin GET with no business logic and no side-effect; owner runs fetch_kalshi_history.py on a network-permitted host. HONESTY CAVEAT: the Kalshi status-string + price-field CONTRACT (response status='active'/'settled'/'determined'; cent prices; the 'settled' discovery filter) is encoded per Kalshi's DOCUMENTED API but is NOT yet confirmed against a live response (egress-blocked offline) — an unrecognized status is logged LOUDLY (never silently dropped), and the OWNER must confirm the contract on the first real fetch."
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
  # The dashboard validation feed (mirror of LOOP_HEALTH.validation; computed by
  # `check_self_validation.py --readiness`). unmet MUST be empty here AND in LOOP_HEALTH.
  readiness:
    enforced_in_ci: true
    capabilities_total: 11
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
