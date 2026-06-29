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
  as_of: 2026-06-29
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
      desc: "shared-secret bearer token on state-mutating routes (kill-switch/config/execute/bot)"
      validates_via: "test_backend_auth.py — open when BACKEND_API_TOKEN unset (degrades safely), exact-Bearer required + all mismatches denied (constant-time) when set"
      mode: degrades_without_key
      requires_env: [BACKEND_API_TOKEN]  # unset => auth disabled (open), unchanged paper/dev behaviour
      active: true
      ci_validatable: true             # the no-token (open) AND the enforced decision are both tested without any secret; the token only ACTIVATES protection
      status: degrades_safely            # absent token => open (as today); set => enforced. Owner activates (OA-14).
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
      validates_via: "config.has_llm_key gates use; without the key it falls back to templates (no fake output)"
      mode: degrades_without_key
      requires_env: [GEMINI_API_KEY]
      active: true
      ci_validatable: true          # the degraded (no-key) path is the one that runs in CI and is validated
      real_flow_note: "analysis is advisory, never an order side-effect; the no-key template path is exercised, and a real key only enriches text (enhancement, not a critical path)."
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
      desc: "read public Gamma + CLOB market data (no auth)"
      validates_via: "fetcher + client tested offline with FakeSession; live reads are egress-gated (OA-13)"
      mode: mocked_offline
      requires_env: []
      active: true
      ci_validatable: true          # no secret needed; the logic-critical part is parsing/anti-leakage, tested on realistic fixtures
      real_flow_note: "the critical logic is PARSING + anti-leakage (exercised on real-shaped fixtures, incl. the real fetch run in OA-11); the live HTTP read is a thin GET with no business logic and no side-effect."
      status: validated
    - id: residual_legacy_data
      desc: "retired stock/crypto data-provider config (ROADMAP A1) — no active trading path uses it"
      validates_via: "n/a — dead config kept only until the tidy-up; no active flow reads it for trading"
      mode: inactive
      requires_env: [FINNHUB_API_KEY, ALPACA_API_KEY, ALPACA_API_SECRET, BINANCE_API_KEY, BINANCE_API_SECRET, FRED_API_KEY]
      active: false
      ci_validatable: false         # cannot validate a retired path — but active:false, so NOT unmet (inactive is exempt)
      status: inactive_residual
  # The dashboard validation feed (mirror of LOOP_HEALTH.validation; computed by
  # `check_self_validation.py --readiness`). unmet MUST be empty here AND in LOOP_HEALTH.
  readiness:
    enforced_in_ci: true
    capabilities_total: 9
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
    FINNHUB_API_KEY:       {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
    ALPACA_API_KEY:        {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
    ALPACA_API_SECRET:     {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
    BINANCE_API_KEY:       {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
    BINANCE_API_SECRET:    {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
    FRED_API_KEY:          {capability: residual_legacy_data, needed_to: none_retired, owner_action: null}
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
