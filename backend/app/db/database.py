"""
Database connection and session management.

Supports SQLite (default, local dev) and Postgres (Supabase / any Postgres) via the
DATABASE_URL setting. The engine is dialect-aware so SQLite-only options
(check_same_thread) are never sent to Postgres, and Postgres gets pooling that
survives Supabase's connection poolers (Supavisor) dropping idle connections.

To use Supabase, set DATABASE_URL to your Supabase connection string (see
backend/.env.example). For a persistent backend prefer the DIRECT connection
(IPv6) or the SESSION POOLER (IPv4, port 5432). Avoid the transaction pooler
(port 6543) for a long-running server.
"""

import logging

from sqlmodel import SQLModel, Session, create_engine
from contextlib import contextmanager
from typing import Generator

from ..config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def _normalize_url(url: str) -> str:
    """Normalize a Postgres URL for SQLAlchemy 2.x + psycopg2.

    Supabase (and Heroku) hand out `postgres://...`, which SQLAlchemy 2.x rejects.
    Pin the psycopg2 driver explicitly so the dialect is unambiguous.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def _make_engine(url: str):
    """Create a dialect-aware engine."""
    url = _normalize_url(url)

    if url.startswith("postgresql"):
        connect_args: dict = {}
        # Supabase requires SSL. Only set it if the URL doesn't already specify it.
        if "sslmode=" not in url:
            connect_args["sslmode"] = "require"
        engine = create_engine(
            url,
            echo=False,
            pool_pre_ping=True,   # revalidate connections (poolers drop idle ones)
            pool_recycle=1800,    # recycle every 30 min to stay under pooler timeouts
            pool_size=5,
            max_overflow=5,
            connect_args=connect_args,
        )
        logger.info("Database engine: Postgres (pool_pre_ping=on, ssl=%s)",
                    connect_args.get("sslmode", "from-url"))
        return engine

    # SQLite (local-dev default)
    engine = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},  # required for SQLite + FastAPI
    )
    logger.info("Database engine: SQLite (%s)", url)
    return engine


engine = _make_engine(settings.database_url)


def init_db():
    """Initialize database and create all tables.

    Works on both SQLite and Postgres — SQLModel.metadata.create_all is a no-op
    for tables that already exist.
    """
    # Import all model modules so SQLModel registers their tables BEFORE create_all.
    # The durable singleton tables below live in their own modules and were previously
    # imported only LAZILY (inside orchestrator/executor construction, which runs AFTER
    # this create_all at app startup) — so their tables were never created in prod and the
    # "durable" audit-log / strategy-registry / executor-safety-state persistence silently
    # no-op'd (BUILDS≠WORKS, caught by an adversarial auditor). Importing them here
    # registers their `table=True` classes so create_all actually builds them. All three
    # use extend_existing=True, so this eager import is dual-import-safe.
    from ..db import models as _db_models  # noqa: F401 — equity/paper trading models
    from ..prediction_markets import models as _pm_models  # noqa: F401 — prediction market models
    from ..prediction_markets import audit_log as _pm_audit  # noqa: F401 — durable audit log (G3)
    from ..prediction_markets import strategy_registry_store as _pm_reg  # noqa: F401 — alpha lifecycle (B3)
    from ..prediction_markets import executor_state_store as _pm_state  # noqa: F401 — kill-switch/PnL durability
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get database session as context manager."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_dependency() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    with get_session() as session:
        yield session
