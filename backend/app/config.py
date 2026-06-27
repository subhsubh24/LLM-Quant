"""
Configuration management for QuantLab.
Uses pydantic-settings for type-safe configuration.
"""

import os
from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field


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

    # Auto-connect to brokers on startup
    auto_connect_brokers: bool = True

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
