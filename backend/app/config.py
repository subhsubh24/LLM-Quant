"""
Configuration management for QuantLab.
Uses pydantic-settings for type-safe configuration.
"""

import os
from functools import lru_cache
from typing import Literal
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

    # Market Data API Keys (optional but recommended for live data)
    finnhub_api_key: str = ""  # Free tier: 60 calls/min

    # Data Provider
    data_provider: Literal["stooq", "yfinance"] = "yfinance"
    data_cache_days: int = 1

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
    # DEGRADES SAFELY: empty (the default) => auth DISABLED, every request passes, so
    # paper/dev behaviour is unchanged. When the owner sets BACKEND_API_TOKEN on a public
    # deploy, those routes require a matching `Authorization: Bearer <token>` (401 else),
    # so the backend control surface is credential-protected server-side, not merely
    # network-isolated. Server-side only; the autonomous loop never sets it. See
    # backend/app/api/auth.py + PENDING_OPS OA-14.
    backend_api_token: str = ""  # env: BACKEND_API_TOKEN — owner-set; default off (open)

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

    # ============ Live Broker Settings ============
    # Alpaca (US Stocks/ETFs) - Paper Trading
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper_mode: bool = True  # True = paper trading, False = live

    # Binance (Crypto)
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet_mode: bool = True  # True = testnet, False = live
    binance_us_mode: bool = True  # True = Binance.US, False = Binance Global (non-US)
    # NOTE: equity/crypto live-broker auto-connect was removed (ROADMAP A1 — retire
    # stock/crypto trading). The alpaca/binance settings above remain only for the
    # not-yet-retired read-only stock data provider (data/alpaca_data.py); they drive
    # no order placement. Prediction-markets is the only venue path.

    # ============ Alternative Data Settings ============
    # FRED API key (free from https://fred.stlouisfed.org/docs/api/api_key.html)
    fred_api_key: str = ""

    # Enable/disable alternative data sources
    alt_data_enabled: bool = True          # Master switch for all alt data
    alt_data_fred_enabled: bool = True     # Macroeconomic data from FRED
    alt_data_cross_asset_enabled: bool = True  # Cross-asset signals (bonds, commodities, FX)
    alt_data_sentiment_enabled: bool = True    # Sentiment indicators (VIX, breadth)

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
        config, portfolio reset) degrade-safely to OPEN when BACKEND_API_TOKEN is unset —
        correct for paper/dev, but a deploy that flips LIVE_TRADING_ENABLED while leaving
        the token empty would expose an unauthenticated kill-switch/execute surface on a
        real-money bot (a deep-audit footgun). So when live trading is on, an empty token
        HARD-REFUSES to boot. This can NEVER affect paper/dev/CI (live defaults false and
        the autonomous loop never flips it) — it only binds the owner's real-money host,
        mirroring `_forbid_test_bypass_in_live`. See PENDING_OPS OA-14 / LIVE_RUNBOOK §5.
        """
        if self.live_trading_enabled and not (self.backend_api_token or "").strip():
            raise ValueError(
                "LIVE_TRADING_ENABLED is true but BACKEND_API_TOKEN is empty — the "
                "state-mutating control routes (kill-switch, execute, bot start/stop) would "
                "be UNAUTHENTICATED on a real-money deploy. Refusing to boot. Set "
                "BACKEND_API_TOKEN to a strong random secret on the live host (see "
                "LIVE_RUNBOOK §5 / PENDING_OPS OA-14)."
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

    @property
    def has_alpaca_keys(self) -> bool:
        """Check if Alpaca API keys are configured."""
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    @property
    def has_binance_keys(self) -> bool:
        """Check if Binance API keys are configured."""
        return bool(self.binance_api_key and self.binance_api_secret)

    @property
    def has_fred_key(self) -> bool:
        """Check if FRED API key is configured."""
        return bool(self.fred_api_key and len(self.fred_api_key) > 5)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
