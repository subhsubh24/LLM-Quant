"""
Database connection and session management.

Supports SQLite (default, local dev) and Postgres (production: Neon, or any Postgres)
via the DATABASE_URL setting. The engine is dialect-aware so SQLite-only options
(check_same_thread) are never sent to Postgres, and Postgres gets pooling
(pool_pre_ping + pool_recycle) that survives a managed pooler dropping idle connections.

For production, set DATABASE_URL to the Neon POOLED connection string from the Neon
Console (it includes ?sslmode=require); see backend/.env.example. Any other managed
Postgres works too — prefer a session/pooled endpoint suited to a long-running server
over a short-lived transaction pooler.
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

    Some hosts (Heroku, and older Postgres URLs) hand out `postgres://...`, which
    SQLAlchemy 2.x rejects. Pin the psycopg2 driver explicitly so the dialect is
    unambiguous.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


_DEFAULT_SQLITE_URL = "sqlite:///./quantlab.db"


def _make_engine(url: str):
    """Create a dialect-aware engine."""
    # An empty / whitespace DATABASE_URL (e.g. an unset CI secret interpolates to "") must
    # NOT crash boot with a SQLAlchemy parse error — fall back to the local SQLite default.
    if not (url or "").strip():
        logger.info("DATABASE_URL empty/unset — falling back to local SQLite default")
        url = _DEFAULT_SQLITE_URL
    url = _normalize_url(url)

    if url.startswith("postgresql"):
        connect_args: dict = {}
        # Managed Postgres (Neon) requires SSL. Only set it if the URL doesn't specify it.
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
    # (The legacy equity/paper-trading `db.models` stack was removed 2026-07-01 as
    # stock-era dead residue — ROADMAP A1; nothing in the prediction-markets app read it.)
    from ..prediction_markets import models as _pm_models  # noqa: F401 — prediction market models
    from ..prediction_markets import audit_log as _pm_audit  # noqa: F401 — durable audit log (G3)
    from ..prediction_markets import strategy_registry_store as _pm_reg  # noqa: F401 — alpha lifecycle (B3)
    from ..prediction_markets import executor_state_store as _pm_state  # noqa: F401 — kill-switch/PnL durability
    from ..prediction_markets import strategy_enable_store as _pm_enable  # noqa: F401 — per-strategy enable/disable (B6)
    SQLModel.metadata.create_all(engine)

    # Seed the default portfolio (id=1) so order/position inserts satisfy their portfolio FK.
    # MULTIPLE writers reference portfolio_id=1 (persistence.save_order/save_position AND
    # orchestrator._persist_order) — SQLite doesn't enforce FKs but Postgres (Neon) does, so
    # without this parent row the durable writes raise ForeignKeyViolation. Idempotent +
    # best-effort (never breaks boot). One place covers every writer.
    try:
        with Session(engine) as _s:
            if _s.get(_pm_models.PredictionPortfolio, 1) is None:
                _s.add(_pm_models.PredictionPortfolio(id=1, name="default", exchange="all"))
                _s.commit()
    except Exception as e:  # pragma: no cover - defensive; boot must not depend on the seed
        logger.warning("init_db: default-portfolio seed skipped (%s)", e)


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
