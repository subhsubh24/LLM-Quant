"""
Durable persistence for the alpha-lifecycle registry (ROADMAP B3 wiring).

``strategy_registry.py`` is a PURE, deterministic state machine (propose → backtest
→ paper → promote → retire, with a fail-loud integrity gate). It had no home in the
running system — lifecycle state lived only in prose. This module is the thin,
best-effort persistence layer that lets the orchestrator RECORD real alpha state
transitions and have them SURVIVE restarts, closing B3's named "remaining" work
("wire it into the live loop so real alpha state transitions are recorded +
persisted").

Design (mirrors ``audit_log.py`` exactly — the proven, dual-import-safe recipe):
* A single ``table=True`` row type with ``extend_existing`` so the dual ``app.*`` /
  ``backend.app.*`` import paths can't double-register and crash import.
* Best-effort + non-fatal: every read/write is wrapped so a persistence hiccup can
  NEVER break the trade path (a registry transition is governance, not the money path).
* The registry is serialized via ``StrategyRegistry.to_dict()`` — a deterministic,
  byte-stable snapshot — into one JSON row (``singleton`` key). We persist the WHOLE
  registry as one snapshot rather than per-alpha rows: the registry is small, the
  engine already guarantees a byte-stable round trip, and a single-row snapshot makes
  load/save atomic and trivially correct (no partial-write races).

HONESTY
  This stores exactly what the engine produced — it cannot manufacture evidence or
  bypass the promotion gate (that lives in the engine and runs BEFORE we ever persist).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlmodel import SQLModel, Field, Session, select

from .strategy_registry import StrategyRegistry

logger = logging.getLogger(__name__)


# ============================================================
# Table
# ============================================================

class PredictionStrategyRegistryRow(SQLModel, table=True):
    """One row holding the full registry snapshot as deterministic JSON.

    A singleton table (``key`` is always ``"singleton"``). We keep the entire
    registry in one row because ``StrategyRegistry.to_dict()`` is already a stable,
    self-contained snapshot and a single row makes persistence atomic.
    """
    __tablename__ = "prediction_strategy_registry"
    # See audit_log.PredictionAuditLog for why extend_existing is required here:
    # the package is importable under two module paths in some test sessions, and a
    # table=True class registers with the shared SQLModel.metadata at import time.
    __table_args__ = {"extend_existing": True}

    key: str = Field(default="singleton", primary_key=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    snapshot_json: str = Field(default="{}")


# ============================================================
# Helpers
# ============================================================

def init_db(engine) -> None:
    """Create the registry table on the given engine (used by tests on an in-memory DB)."""
    SQLModel.metadata.create_all(engine, tables=[PredictionStrategyRegistryRow.__table__])


def _default_session_factory():
    """Return the app's ``get_session()`` contextmanager (imported lazily)."""
    from ..db.database import get_session
    return get_session


# ============================================================
# Store
# ============================================================

class StrategyRegistryStore:
    """Best-effort durable load/save for a :class:`StrategyRegistry`.

    Parameters mirror :class:`audit_log.AuditLogger`: pass an ``engine`` (tests, an
    in-memory SQLite engine) or rely on the app's ``get_session`` factory (production).
    """

    SINGLETON_KEY = "singleton"

    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        engine: Any = None,
    ):
        self._engine = engine
        if session_factory is None and engine is None:
            try:
                session_factory = _default_session_factory()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("StrategyRegistryStore: no default session factory: %s", e)
                session_factory = None
        self._session_factory = session_factory

    @contextmanager
    def _session(self):
        if self._engine is not None:
            session = Session(self._engine, expire_on_commit=False)
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        else:
            if self._session_factory is None:
                raise RuntimeError("StrategyRegistryStore has no session_factory or engine")
            with self._session_factory() as session:
                yield session

    def load(self) -> Optional[StrategyRegistry]:
        """Return the persisted registry, or ``None`` if absent/unreadable.

        ``None`` (not an empty registry) signals "nothing persisted yet" so the caller
        can decide whether to seed defaults — distinguishing "never initialised" from
        "initialised but empty".
        """
        try:
            with self._session() as session:
                row = session.get(PredictionStrategyRegistryRow, self.SINGLETON_KEY)
                if row is None or not row.snapshot_json:
                    return None
                data = json.loads(row.snapshot_json)
                return StrategyRegistry.from_dict(data)
        except Exception as e:
            logger.warning("StrategyRegistryStore: load failed: %s", e)
            return None

    def save(self, registry: StrategyRegistry) -> bool:
        """Persist the registry snapshot. Returns True on success (best-effort, never raises)."""
        try:
            snapshot = json.dumps(registry.to_dict(), default=str, sort_keys=True)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("StrategyRegistryStore: could not serialize registry: %s", e)
            return False
        try:
            with self._session() as session:
                row = session.get(PredictionStrategyRegistryRow, self.SINGLETON_KEY)
                if row is None:
                    row = PredictionStrategyRegistryRow(key=self.SINGLETON_KEY)
                row.snapshot_json = snapshot
                row.updated_at = datetime.now(timezone.utc)
                session.add(row)
            return True
        except Exception as e:
            logger.warning("StrategyRegistryStore: save failed: %s", e)
            return False


class _NoOpStrategyRegistryStore:
    """Fallback used if store construction fails — never raises, never persists."""

    def load(self) -> Optional[StrategyRegistry]:
        return None

    def save(self, registry: StrategyRegistry) -> bool:
        return False
