"""
SQLModel database models for Prediction Market trading.

Persists positions, orders, P&L snapshots, and whale activity
alongside the existing QuantLab models.
"""

from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import json
import logging

logger = logging.getLogger(__name__)


# ============================================================
# Portfolio & Positions
# ============================================================

class PredictionPortfolio(SQLModel, table=True):
    """
    A prediction market trading portfolio.

    Each portfolio tracks capital allocated to prediction markets,
    separate from the equity paper trading portfolios.
    """
    __tablename__ = "prediction_portfolios"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    exchange: str = Field(index=True)  # "polymarket", "kalshi", "all"

    # Capital
    initial_capital_usd: float = 100.0
    current_cash_usd: float = 100.0
    total_deposited_usd: float = 100.0

    # Aggregate P&L
    total_value_usd: float = 100.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_fees: float = 0.0

    # Config
    dry_run: bool = True
    max_position_usd: float = 50.0
    max_portfolio_usd: float = 500.0
    is_active: bool = True

    # Stats
    total_orders: int = 0
    total_fills: int = 0
    win_count: int = 0
    loss_count: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    positions: List["PredictionPosition"] = Relationship(back_populates="portfolio")
    orders: List["PredictionOrder"] = Relationship(back_populates="portfolio")
    snapshots: List["PredictionPnLSnapshot"] = Relationship(back_populates="portfolio")

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def return_pct(self) -> float:
        if self.initial_capital_usd > 0:
            return self.total_pnl / self.initial_capital_usd
        return 0.0

    @property
    def win_rate(self) -> float:
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0


class PredictionPosition(SQLModel, table=True):
    """
    A position in a prediction market outcome token.

    Each position tracks a single token (e.g., YES on "Will BTC > $100k?").
    """
    __tablename__ = "prediction_positions"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="prediction_portfolios.id", index=True)

    # Market identity
    exchange: str = Field(index=True)   # "polymarket" or "kalshi"
    market_id: str = Field(index=True)  # Polymarket condition_id or Kalshi ticker
    token_id: str = Field(index=True)   # Polymarket token_id or Kalshi ticker
    market_question: str = ""
    outcome_label: str = ""             # "Yes", "No", "42-45°F", etc.
    category: str = ""

    # Position details
    side: str = "long"                  # "long" or "short"
    size: float = 0.0                   # Number of contracts
    avg_entry_price: float = 0.0        # Average price paid (0.00-1.00)
    current_price: float = 0.0
    market_value: float = 0.0           # size * current_price

    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0

    # Strategy attribution
    strategy: str = ""                  # Which strategy opened this position
    confidence: float = 0.0             # Strategy confidence at entry
    edge_at_entry: float = 0.0          # Expected edge at entry

    # Resolution
    is_resolved: bool = False
    resolution_value: Optional[float] = None  # 0.0 or 1.0 if resolved

    is_active: bool = True
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None

    portfolio: Optional[PredictionPortfolio] = Relationship(back_populates="positions")

    @property
    def cost_basis(self) -> float:
        return self.size * self.avg_entry_price

    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl


# ============================================================
# Orders
# ============================================================

class PredictionOrder(SQLModel, table=True):
    """
    Order execution record for prediction markets.

    Every order attempt (success or failure) is logged for audit.
    """
    __tablename__ = "prediction_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="prediction_portfolios.id", index=True)

    # Order identity
    order_id: str = Field(index=True)   # Exchange-assigned order ID
    exchange: str = Field(index=True)
    market_id: str = Field(index=True)
    token_id: str

    # Order params
    side: str                           # "BUY" or "SELL"
    order_type: str                     # "MARKET", "LIMIT", "GTC", "FOK"
    size: float
    limit_price: Optional[float] = None

    # Fill info
    status: str = "pending"             # pending, open, filled, cancelled, rejected
    filled_size: float = 0.0
    filled_price: float = 0.0
    fees: float = 0.0

    # Context
    strategy: str = ""
    error: Optional[str] = None
    is_dry_run: bool = True
    raw_response_json: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    portfolio: Optional[PredictionPortfolio] = Relationship(back_populates="orders")

    def get_raw_response(self) -> dict:
        if self.raw_response_json:
            try:
                return json.loads(self.raw_response_json)
            except (json.JSONDecodeError, ValueError, TypeError):
                return {}
        return {}


# ============================================================
# P&L Snapshots (time-series for equity curve)
# ============================================================

class PredictionPnLSnapshot(SQLModel, table=True):
    """
    Periodic P&L snapshot for building equity curves.

    Taken every N minutes or on every trade event.
    """
    __tablename__ = "prediction_pnl_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="prediction_portfolios.id", index=True)

    # Portfolio state at snapshot time
    total_value_usd: float
    cash_usd: float
    positions_value_usd: float
    realized_pnl: float
    unrealized_pnl: float
    total_fees: float
    num_positions: int

    # Breakdown by exchange
    polymarket_value: float = 0.0
    kalshi_value: float = 0.0

    # Breakdown by strategy (JSON: {strategy_name: value})
    strategy_breakdown_json: Optional[str] = None

    snapshot_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    portfolio: Optional[PredictionPortfolio] = Relationship(back_populates="snapshots")

    def get_strategy_breakdown(self) -> dict:
        if self.strategy_breakdown_json:
            try:
                return json.loads(self.strategy_breakdown_json)
            except (json.JSONDecodeError, ValueError, TypeError):
                return {}
        return {}


# ============================================================
# Whale Activity (on-chain tracking)
# ============================================================

class WhaleActivity(SQLModel, table=True):
    """
    On-chain whale activity detected on Polygon.

    Tracks large trades on Polymarket's CLOB contract.
    """
    __tablename__ = "whale_activity"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Transaction details
    tx_hash: str = Field(index=True)
    block_number: int = Field(index=True)
    wallet_address: str = Field(index=True)
    wallet_label: Optional[str] = None  # "Theo4", "Fredi9999", etc.

    # Trade details
    market_id: str = Field(index=True)
    token_id: str
    side: str           # "BUY" or "SELL"
    size: float         # Number of contracts
    price: float        # Execution price
    value_usd: float    # Total USD value

    # Market context
    market_question: Optional[str] = None
    outcome_label: Optional[str] = None

    # Metadata
    is_significant: bool = False  # True if > threshold (e.g., $1000)
    gas_price_gwei: Optional[float] = None

    detected_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# ============================================================
# Market Price History (from WebSocket feeds)
# ============================================================

class PredictionPriceHistory(SQLModel, table=True):
    """
    Price history for prediction market outcomes.

    Sampled from WebSocket feeds at regular intervals (e.g., every 60s).
    Used for charting, strategy backtesting, and anomaly detection.
    """
    __tablename__ = "prediction_price_history"

    id: Optional[int] = Field(default=None, primary_key=True)

    exchange: str = Field(index=True)
    market_id: str = Field(index=True)
    token_id: str = Field(index=True)
    outcome_label: str = ""

    # Price data
    price: float
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    volume_24h: float = 0.0

    sampled_at: datetime = Field(default_factory=datetime.utcnow, index=True)
