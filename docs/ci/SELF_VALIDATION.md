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
  capabilities:
    - id: paper_pipeline
      desc: "scan -> Kelly-size -> paper execute -> PnL, deterministic"
      validates_via: "scripts/runtime_harness.py + backend/tests/test_prediction_markets.py"
      mode: in_process_deterministic
      requires_env: []
      active: true
      status: validated
    - id: risk_and_kill_switch
      desc: "loss caps + kill switch + position caps reject/halt orders"
      validates_via: "runtime_harness.py + test_loss_caps.py (real REJECT/halt asserted)"
      mode: in_process_deterministic
      requires_env: []
      active: true
      status: validated
    - id: live_trading_path
      desc: "real-order placement on Polymarket (the gated live path)"
      validates_via: "runtime_harness asserts the live gate + kill switch BLOCK real orders deterministically"
      mode: gated_off_proven        # built; LIVE_TRADING_ENABLED=false; validated AS gated-off
      requires_env: [POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER]
      active: false                 # not reachable until the owner activates (human-core)
      status: gated_off
    - id: llm_analysis
      desc: "Gemini-driven market/research analysis"
      validates_via: "config.has_llm_key gates use; without the key it falls back to templates (no fake output)"
      mode: degrades_without_key
      requires_env: [GEMINI_API_KEY]
      active: true
      status: degrades_safely       # absent key => templates, never a fabricated analysis
    - id: db_persistence
      desc: "audit log + state persisted to Neon (prod) / SQLite (dev)"
      validates_via: "tests use in-memory SQLite; SQLModel.create_all idempotent; durable hosting is OA-10"
      mode: in_process_deterministic
      requires_env: [DATABASE_URL]  # optional; falls back to local SQLite
      active: true
      status: validated
    - id: polymarket_market_data
      desc: "read public Gamma + CLOB market data (no auth)"
      validates_via: "fetcher + client tested offline with FakeSession; live reads are egress-gated (OA-13)"
      mode: mocked_offline
      requires_env: []
      active: true
      status: validated
    - id: residual_legacy_data
      desc: "retired stock/crypto data-provider config (ROADMAP A1) — no active trading path uses it"
      validates_via: "n/a — dead config kept only until the tidy-up; no active flow reads it for trading"
      mode: inactive
      requires_env: [FINNHUB_API_KEY, ALPACA_API_KEY, ALPACA_API_SECRET, BINANCE_API_KEY, BINANCE_API_SECRET, FRED_API_KEY]
      active: false
      status: inactive_residual
  # Every credential the CODE reads must appear here (checker enforces). new + undeclared => gate FAILS.
  credential_inventory:
    GEMINI_API_KEY:        {capability: llm_analysis, needed_to: enhance_analysis, owner_action: null}
    DATABASE_URL:          {capability: db_persistence, needed_to: durable_persist, owner_action: OA-10}
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
