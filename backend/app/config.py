"""
Configuration management for QuantLab.
Uses pydantic-settings for type-safe configuration.
"""

from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "sqlite:///./quantlab.db"

    # LLM Integration - Anthropic Claude (primary)
    anthropic_api_key: str = ""

    # Market Data API Keys (optional but recommended for live data)
    finnhub_api_key: str = ""  # Free tier: 60 calls/min

    # Data Provider
    data_provider: Literal["stooq", "yfinance"] = "yfinance"
    data_cache_days: int = 1

    # Paper Trading
    initial_cash: float = 100_000.0
    default_transaction_cost_bps: float = 10.0
    default_slippage_bps: float = 5.0

    # Risk Settings
    max_position_weight: float = 0.10
    target_volatility: float = 0.15
    max_drawdown_limit: float = 0.20

    # Demo Mode (set to False for live data)
    demo_mode: bool = False
    demo_seed: int = 42

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def has_llm_key(self) -> bool:
        """Check if LLM API key is configured."""
        return bool(self.anthropic_api_key and len(self.anthropic_api_key) > 10)

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
