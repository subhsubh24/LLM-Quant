"""
Database connection and session management.
"""

from sqlmodel import SQLModel, Session, create_engine
from contextlib import contextmanager
from typing import Generator

from ..config import get_settings

settings = get_settings()

# Create engine with SQLite optimizations
engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False}  # Required for SQLite with FastAPI
)


def init_db():
    """Initialize database and create all tables."""
    # Import all model modules so SQLModel registers their tables
    from ..db import models as _db_models  # noqa: F401 — equity/paper trading models
    from ..prediction_markets import models as _pm_models  # noqa: F401 — prediction market models
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
