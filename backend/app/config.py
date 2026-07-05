"""
Configuration management for QuantLab.
Uses pydantic-settings for type-safe configuration.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field, model_validator


def find_env_file():
    """Find .env file in multiple locations."""
    # Get the directory where this config.py file is located
    config_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(config_dir)  # backend/app -> backend

    possible_paths = [
        os.path.join(backend_dir, ".env"),   # backend/.env (most likely)
        ".env",                               # Current working directory
        "../.env",                            # Parent directory
        "backend/.env",                       # If running from root
        os.path.expanduser("~/.env"),         # Home directory
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return ".env"  # Default


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "sqlite:///./quantlab.db"

    # LLM Integration - Google Gemini (primary)
    gemini_api_key: str = ""  # env: GEMINI_API_KEY
    gemini_model: str = "gemini-2.5-flash"  # env: GEMINI_MODEL — override to a newer model without code changes

    # Paper Trading
    initial_cash: float = 100_000.0
    # Realistic transaction costs (previously 10+5=15 bps, too optimistic):
    # - Commission: ~2-5 bps (commission-free brokers still have payment-for-order-flow)
    # - Bid-ask spread: ~3-8 bps for mid/large-cap
    # - Market impact: ~2-5 bps per side
    # Total: 10-20 bps per side, 20-30 bps round-trip
    default_transaction_cost_bps: float = 15.0  # Per-side commission + spread
    default_slippage_bps: float = 8.0  # Per-side market impact + execution delay
    # Market impact model: cost increases with sqrt(participation rate)
    # impact_bps = base_impact * sqrt(order_size / daily_volume)
    market_impact_base_bps: float = 10.0  # Base impact for sqrt model

    # Risk Settings
    max_position_weight: float = 0.10
    target_volatility: float = 0.15
    max_drawdown_limit: float = 0.15  # Tightened from 0.20 — 15% max DD is institutional standard

    # Demo Mode - ENABLED BY DEFAULT for easy setup
    # Uses fallback data when external APIs unavailable
    demo_mode: bool = True
    demo_seed: int = 42

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # Extra CORS origins for deployed frontends (comma-separated exact origins, e.g.
    # "https://llm-quant.vercel.app"). Localhost dev origins are always allowed.
    cors_allow_origins: str = ""  # env: CORS_ALLOW_ORIGINS

    # ============ REAL-MONEY MASTER GATE (HUMAN-CORE) ============
    # The autonomous loop NEVER sets these. Default is SAFE (paper-only).
    # With live_trading_enabled False, no real order can be placed regardless of
    # any other setting. The owner flips this only after the LIVE_RUNBOOK steps.
    live_trading_enabled: bool = False  # env: LIVE_TRADING_ENABLED — owner-only master switch

    # Shared-secret bearer token guarding the backend's STATE-MUTATING routes
    # (kill-switch, risk config, execute, portfolio reset, bot start/stop/scan, …).
    # DEFAULT-CLOSED (since #129): when this is empty AND `backend_auth_disabled` is False
    # (the default), the mutating routes DENY with 401 — a public paper deploy that forgets
    # to set the token is NOT silently unauthenticated. To run those routes, EITHER set
    # BACKEND_API_TOKEN (they then require a matching `Authorization: Bearer <token>`, 401
    # else) OR set BACKEND_AUTH_DISABLED=1 for a trusted local/dev host (see below).
    # Server-side only; the autonomous loop never sets it. See backend/app/api/auth.py +
    # PENDING_OPS OA-14.
    backend_api_token: str = ""  # env: BACKEND_API_TOKEN — owner-set; protects control routes (default CLOSED)

    # Dev/paper opt-out for the default-CLOSED control auth. By DEFAULT (this flag False) the
    # state-mutating routes REQUIRE a token — so a public paper deploy that forgets to set
    # BACKEND_API_TOKEN is NOT silently unauthenticated: it denies mutating requests with 401
    # rather than exposing the kill-switch/execute/bot-control surface. Set
    # BACKEND_AUTH_DISABLED=1 to deliberately run OPEN on a trusted single-user dev/paper host.
    # It can NEVER be active with real money — `_require_control_auth_in_live` refuses to boot
    # if it is set while LIVE_TRADING_ENABLED is on. The autonomous loop never sets either.
    backend_auth_disabled: bool = False  # env: BACKEND_AUTH_DISABLED — dev opt-out (run open)

    # TEST-ONLY bypass. The CI functional gate may set E2E_DISABLE_RATE_LIMIT=1 so a single
    # CI-runner IP cannot trip rate limits while exercising endpoints. PRODUCTION MUST NEVER
    # SET IT: if it is ever truthy while live_trading_enabled is on, the app HARD-REFUSES to
    # boot (see _forbid_test_bypass_in_live). NOTE: there is no inbound rate limiter wired
    # today (the gate runs in-process), so this flag's ONLY current effect is that boot-refusal
    # tripwire — when a real limiter is added, wire this to disable it on the gate job only.
    e2e_disable_rate_limit: bool = False  # env: E2E_DISABLE_RATE_LIMIT — CI gate ONLY, never prod

    # Hard loss / spend ceilings (USD). Conservative defaults; owner sets real values.
    # These are enforced in code; a breach auto-trips the kill switch.
    max_per_trade_usd: float = 5.0       # env: MAX_PER_TRADE_USD
    max_daily_loss_usd: float = 25.0     # env: MAX_DAILY_LOSS_USD
    max_total_loss_usd: float = 100.0    # env: MAX_TOTAL_LOSS_USD
    llm_spend_cap_usd: float = 20.0      # env: LLM_SPEND_CAP_USD

    # ============ UNVALIDATED-STRATEGY GATE ============
    # Some strategies are NOT tracked in ROADMAP/RESEARCH_MEMORY, have no B3 registry
    # evidence, no backtest, and no forensic-audit proof they fire on real-shaped data —
    # and the whale infrastructure historically shipped a FABRICATED hardcoded seed of
    # "known whale" wallet addresses (removed 2026-07-01). Per FACTORY_STANDARD
    # "no alpha ships while integrity is weak" + evidence-based-done, such strategies must
    # NOT run in the default paper scan until validated. This flag (default OFF) keeps them
    # out of the auto-configured scanner; flip it only to deliberately exercise them.
    # The autonomous loop never sets this. See the whale/weather ROADMAP items + the
    # 2026-07-01 Research Run 11 integrity finding in docs/growth/RESEARCH_MEMORY.md.
    enable_unvalidated_strategies: bool = False  # env: ENABLE_UNVALIDATED_STRATEGIES — default off

    model_config = ConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _forbid_test_bypass_in_live(self) -> "Settings":
        """A test-only bypass must NEVER be active with real money on the line.

        If E2E_DISABLE_RATE_LIMIT is set while LIVE_TRADING_ENABLED is true, refuse to boot.
        This guarantees a CI convenience can never weaken the live platform — even before any
        real inbound rate limiter exists, the tripwire is in place.
        """
        if self.e2e_disable_rate_limit and self.live_trading_enabled:
            raise ValueError(
                "E2E_DISABLE_RATE_LIMIT is a TEST-ONLY flag and must never be set when "
                "LIVE_TRADING_ENABLED is true — refusing to boot. Unset it on the live host."
            )
        return self

    @model_validator(mode="after")
    def _require_control_auth_in_live(self) -> "Settings":
        """Real money on the line ⇒ the control surface MUST be authenticated.

        The backend's state-mutating routes (kill-switch, execute, bot start/stop, risk
        config, portfolio reset) are default-CLOSED: they require BACKEND_API_TOKEN unless
        BACKEND_AUTH_DISABLED=1 is explicitly set (a trusted-host dev/paper opt-out). Either
        an empty token OR the dev opt-out while LIVE_TRADING_ENABLED is on would expose an
        unauthenticated kill-switch/execute surface on a real-money bot (a deep-audit
        footgun), so both HARD-REFUSE to boot when live trading is on. This can NEVER affect
        paper/dev/CI (live defaults false and the autonomous loop never flips it) — it only
        binds the owner's real-money host, mirroring `_forbid_test_bypass_in_live`. See
        PENDING_OPS OA-14 (the control-token owner action); the live master gate is
        LIVE_RUNBOOK §6.
        """
        if self.live_trading_enabled and self.backend_auth_disabled:
            raise ValueError(
                "LIVE_TRADING_ENABLED is true but BACKEND_AUTH_DISABLED is set — the dev "
                "opt-out would leave the state-mutating control routes (kill-switch, execute, "
                "bot start/stop) UNAUTHENTICATED on a real-money deploy. Refusing to boot. "
                "Unset BACKEND_AUTH_DISABLED and set BACKEND_API_TOKEN to a strong random "
                "secret on the live host (see PENDING_OPS OA-14 / LIVE_RUNBOOK §6)."
            )
        if self.live_trading_enabled and not (self.backend_api_token or "").strip():
            raise ValueError(
                "LIVE_TRADING_ENABLED is true but BACKEND_API_TOKEN is empty — the "
                "state-mutating control routes (kill-switch, execute, bot start/stop) would "
                "be UNAUTHENTICATED on a real-money deploy. Refusing to boot. Set "
                "BACKEND_API_TOKEN to a strong random secret on the live host (see "
                "PENDING_OPS OA-14 / LIVE_RUNBOOK §6)."
            )
        return self

    @model_validator(mode="after")
    def _require_venue_credentials_in_live(self) -> "Settings":
        """Real money on the line ⇒ the venue order credentials MUST be present at BOOT.

        The Polymarket order path needs POLYMARKET_API_KEY / _API_SECRET / _PASSPHRASE /
        _PRIVATE_KEY (read from the environment in `execution.get_executor()`). Without
        them the executor's `is_authenticated` is False, so `_get_clob_client()` raises at
        RUNTIME on the FIRST order attempt — i.e. a live-enabled bot boots "fine" but is
        silently unable to place a single order (a live-but-broken state that surfaces only
        as a per-order failure once the scan loop is already running). FAIL LOUD at boot
        instead (FACTORY_STANDARD §28: an env credential a critical path requires must fail
        loud, not late), naming the exact missing var — mirroring the control-auth boot
        gate above. This can NEVER affect paper/dev/CI (live defaults false and the
        autonomous loop never flips it) — it only binds the owner's real-money host.
        Setting these keys is HUMAN-CORE (PENDING_OPS OA-5, LIVE_RUNBOOK §5 — the venue
        LIVE-API-key step; §6/OA-6 is the separate master-gate flip).
        """
        if self.live_trading_enabled:
            required = (
                "POLYMARKET_API_KEY",
                "POLYMARKET_API_SECRET",
                "POLYMARKET_PASSPHRASE",
                "POLYMARKET_PRIVATE_KEY",
            )
            missing = [name for name in required if not (os.environ.get(name) or "").strip()]
            if missing:
                raise ValueError(
                    "LIVE_TRADING_ENABLED is true but the Polymarket order credentials "
                    f"{missing} are unset — the bot would boot but fail EVERY real order at "
                    "runtime (the executor is not authenticated). Refusing to boot. Set all "
                    "of POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, "
                    "POLYMARKET_PRIVATE_KEY on the live host (see PENDING_OPS OA-5 / "
                    "LIVE_RUNBOOK §5)."
                )
        return self

    @property
    def has_llm_key(self) -> bool:
        """Check if LLM API key is configured."""
        return bool(self.gemini_api_key and len(self.gemini_api_key) > 10)

    @property
    def transaction_cost_decimal(self) -> float:
        """Transaction cost as decimal (not basis points)."""
        return self.default_transaction_cost_bps / 10000.0

    @property
    def slippage_decimal(self) -> float:
        """Slippage as decimal (not basis points)."""
        return self.default_slippage_bps / 10000.0


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
