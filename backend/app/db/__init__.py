"""Database module for QuantLab.

The legacy equity/paper-trading SQLModel tables (StockPrice, Universe, Feature,
ModelRun, BacktestRun, PaperPortfolio/Position/Trade, ResearchMemo, BotActivityLog,
ExperimentConfig) were removed 2026-07-01 as stock-era dead residue (ROADMAP A1) —
they were registered only by `create_all` and read by nothing in the prediction-markets
app. The prediction-markets tables live under `prediction_markets/` (models.py, audit_log,
strategy_registry_store, executor_state_store).
"""

from .database import get_session, init_db, engine

__all__ = [
    "get_session",
    "init_db",
    "engine",
]
