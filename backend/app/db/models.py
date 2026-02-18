"""
SQLModel database models for QuantLab.
All models use SQLite for local-first storage.
"""

from datetime import datetime, date as dt_date
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import json
import logging
from hashlib import sha256

logger = logging.getLogger(__name__)


class StockPrice(SQLModel, table=True):
    """Daily OHLCV price data."""
    __tablename__ = "stock_prices"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: dt_date = Field(index=True)
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjusted_close: Optional[float] = None

    # Data quality flags
    is_valid: bool = True
    data_source: str = "stooq"

    created_at: datetime = Field(default_factory=datetime.utcnow)


class Universe(SQLModel, table=True):
    """Stock universe definition."""
    __tablename__ = "universes"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    is_default: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    tickers: List["UniverseTicker"] = Relationship(back_populates="universe")


class UniverseTicker(SQLModel, table=True):
    """Tickers in a universe."""
    __tablename__ = "universe_tickers"

    id: Optional[int] = Field(default=None, primary_key=True)
    universe_id: int = Field(foreign_key="universes.id", index=True)
    ticker: str = Field(index=True)
    sector: Optional[str] = None
    industry: Optional[str] = None

    universe: Optional[Universe] = Relationship(back_populates="tickers")


class Feature(SQLModel, table=True):
    """Computed features for ML models."""
    __tablename__ = "features"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    date: dt_date = Field(index=True)
    feature_set_id: str = Field(index=True)  # Hash of feature config

    # Store features as JSON for flexibility
    features_json: str  # JSON dict of feature_name -> value

    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_features(self) -> dict:
        """Parse features from JSON."""
        # CRITICAL FIX: Handle corrupted JSON gracefully
        try:
            return json.loads(self.features_json) if self.features_json else {}
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse features JSON: {e}")
            return {}

    def set_features(self, features: dict):
        """Serialize features to JSON."""
        self.features_json = json.dumps(features)


class ExperimentConfig(SQLModel, table=True):
    """Experiment configuration for reproducibility."""
    __tablename__ = "experiment_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    config_hash: str = Field(unique=True, index=True)
    config_json: str  # Full configuration as JSON
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def compute_hash(cls, config: dict) -> str:
        """Compute deterministic hash of configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return sha256(config_str.encode()).hexdigest()[:16]


class ModelRun(SQLModel, table=True):
    """ML model training run."""
    __tablename__ = "model_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    config_hash: str = Field(index=True)
    model_type: str  # ridge, elasticnet, rf, gbm

    # Training details
    train_start: dt_date
    train_end: dt_date
    validation_start: dt_date
    validation_end: dt_date
    embargo_days: int = 5

    # Metrics
    train_score: Optional[float] = None
    validation_score: Optional[float] = None
    feature_importance_json: Optional[str] = None

    # Model artifact (serialized)
    model_artifact: Optional[bytes] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class BacktestRun(SQLModel, table=True):
    """Backtest execution record."""
    __tablename__ = "backtest_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    config_hash: str = Field(index=True)
    model_run_id: Optional[int] = Field(foreign_key="model_runs.id")

    # Period
    start_date: dt_date
    end_date: dt_date
    rebalance_frequency: str = "weekly"  # daily, weekly, monthly

    # Costs
    transaction_cost_bps: float
    slippage_bps: float

    # Results (stored as JSON for flexibility)
    metrics_json: str  # CAGR, Sharpe, Sortino, MaxDD, etc.
    equity_curve_json: str  # Date -> portfolio value
    holdings_history_json: str  # Date -> {ticker: weight}
    trades_json: str  # List of trades

    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_metrics(self) -> dict:
        # CRITICAL FIX: Handle corrupted JSON gracefully
        try:
            return json.loads(self.metrics_json) if self.metrics_json else {}
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse metrics JSON: {e}")
            return {}

    def get_equity_curve(self) -> dict:
        # CRITICAL FIX: Handle corrupted JSON gracefully
        try:
            return json.loads(self.equity_curve_json) if self.equity_curve_json else {}
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse equity curve JSON: {e}")
            return {}


class PaperPortfolio(SQLModel, table=True):
    """Paper trading portfolio."""
    __tablename__ = "paper_portfolios"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    initial_cash: float
    current_cash: float

    # Performance tracking
    total_value: float
    total_pnl: float
    total_pnl_pct: float
    realized_pnl: float
    unrealized_pnl: float

    # Config
    config_hash: Optional[str] = None
    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    positions: List["PaperPosition"] = Relationship(back_populates="portfolio")
    trades: List["PaperTrade"] = Relationship(back_populates="portfolio")


class PaperPosition(SQLModel, table=True):
    """Current position in paper portfolio."""
    __tablename__ = "paper_positions"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="paper_portfolios.id", index=True)
    ticker: str = Field(index=True)

    shares: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    weight: float  # As fraction of total portfolio

    updated_at: datetime = Field(default_factory=datetime.utcnow)

    portfolio: Optional[PaperPortfolio] = Relationship(back_populates="positions")


class PaperTrade(SQLModel, table=True):
    """Paper trade execution record."""
    __tablename__ = "paper_trades"

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(foreign_key="paper_portfolios.id", index=True)

    ticker: str
    side: str  # buy, sell
    shares: float
    price: float
    notional: float

    # Costs
    transaction_cost: float
    slippage: float
    total_cost: float

    # Attribution
    signal_score: Optional[float] = None
    signal_rank: Optional[int] = None

    executed_at: datetime = Field(default_factory=datetime.utcnow)

    portfolio: Optional[PaperPortfolio] = Relationship(back_populates="trades")


class ResearchMemo(SQLModel, table=True):
    """Generated research memos."""
    __tablename__ = "research_memos"

    id: Optional[int] = Field(default=None, primary_key=True)
    backtest_run_id: int = Field(foreign_key="backtest_runs.id", index=True)

    title: str
    hypothesis: str
    methodology: str
    results: str
    limitations: str
    next_steps: str
    full_memo: str  # Complete formatted memo

    generated_by: str = "template"  # template or llm
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BotActivityLog(SQLModel, table=True):
    """
    Comprehensive bot activity logging for monitoring and debugging.

    Logs all significant bot events including:
    - Bot lifecycle (start, stop, restart)
    - Broker connections/disconnections
    - Market scanning events
    - Trade executions
    - ML model events
    - Errors and warnings
    - Position updates
    - Configuration changes
    """
    __tablename__ = "bot_activity_logs"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Event classification
    event_type: str = Field(index=True)  # lifecycle, broker, trade, scan, ml, error, position, config
    event_subtype: str = Field(index=True)  # start, stop, connect, disconnect, execute, scan_complete, etc.
    severity: str = Field(default="info")  # debug, info, warning, error, critical

    # Event details
    symbol: Optional[str] = Field(default=None, index=True)  # Related symbol if applicable
    asset_class: Optional[str] = Field(default=None)  # stock_options, crypto_perpetual, etc.
    broker: Optional[str] = Field(default=None)  # alpaca, binance, paper

    # Message and context
    message: str  # Human-readable event description
    details_json: Optional[str] = None  # Additional structured data as JSON

    # Performance/metrics if applicable
    value: Optional[float] = None  # Numeric value (price, PnL, score, etc.)
    duration_ms: Optional[int] = None  # Duration of operation in milliseconds

    # Request tracing
    session_id: Optional[str] = Field(default=None, index=True)  # Bot session ID
    correlation_id: Optional[str] = None  # For linking related events

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    def get_details(self) -> dict:
        """Parse details from JSON."""
        # CRITICAL FIX: Handle corrupted JSON gracefully
        if self.details_json:
            try:
                return json.loads(self.details_json)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse details JSON: {e}")
                return {}
        return {}

    def set_details(self, details: dict):
        """Serialize details to JSON."""
        self.details_json = json.dumps(details)
