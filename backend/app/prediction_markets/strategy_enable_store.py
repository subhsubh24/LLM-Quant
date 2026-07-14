"""
Durable persistence for the per-strategy enable/disable control (ROADMAP B6).

The panel's old strategy toggle was a FAKE control (it flipped local UI state only; the
orchestrator ran every strategy regardless), so it was removed per the DECISION COROLLARY
(don't gate UI on an unbuilt loop). This module is the REAL backend half: it persists the
set of DISABLED strategy names so an operator's choice SURVIVES restarts and is applied to
every scanner the app builds (``orchestrator._build_default_scanner`` — the trading path —
and the routes preview scanner).

Design (mirrors ``strategy_registry_store.py`` / ``audit_log.py`` exactly — the proven,
dual-import-safe recipe):
* A single ``table=True`` row type with ``extend_existing`` so the dual ``app.*`` /
  ``backend.app.*`` import paths can't double-register and crash import.
* Best-effort + non-fatal: every read/write is wrapped so a persistence hiccup can NEVER
  break the scan/trade path. A disabled-strategy preference is OPERATIONAL, not a safety
  control (the loss caps / kill switch / live gate are the hard gates), so a load failure
  fails OPEN (all strategies enabled) — the safe default for a paper bot.
* We persist the DISABLED set (usually empty/small) as one deterministic JSON list in a
  singleton row. Enabled is the default, so an absent row means "nothing disabled".

HONESTY
  This stores exactly the names the operator toggled. It cannot enable a strategy that isn't
  registered, and the scanner's ``set_strategy_enabled`` rejects unknown names — a typo can't
  shadow a future strategy.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Set

from sqlmodel import SQLModel, Field, Session

logger = logging.getLogger(__name__)


# ============================================================
# Table
# ============================================================

class PredictionStrategyEnableRow(SQLModel, table=True):
    """One row holding the set of DISABLED strategy names as deterministic JSON.

    A singleton table (``key`` is always ``"singleton"``). Enabled is the default, so the
    absence of a name (or of the whole row) means the strategy runs.
    """
    __tablename__ = "prediction_strategy_enable"
    # See audit_log.PredictionAuditLog for why extend_existing is required here: the package
    # is importable under two module paths in some test sessions, and a table=True class
    # registers with the shared SQLModel.metadata at import time.
    __table_args__ = {"extend_existing": True}

    key: str = Field(default="singleton", primary_key=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    disabled_json: str = Field(default="[]")


# ============================================================
# Helpers
# ============================================================

def init_db(engine) -> None:
    """Create the enable-store table on the given engine (used by tests on an in-memory DB)."""
    SQLModel.metadata.create_all(engine, tables=[PredictionStrategyEnableRow.__table__])


def _default_session_factory():
    """Return the app's ``get_session()`` contextmanager (imported lazily)."""
    from ..db.database import get_session
    return get_session


# ============================================================
# Store
# ============================================================

class StrategyEnableStore:
    """Best-effort durable load/save for the per-strategy disabled set.

    Parameters mirror :class:`strategy_registry_store.StrategyRegistryStore`: pass an
    ``engine`` (tests, an in-memory SQLite engine) or rely on the app's ``get_session``
    factory (production).
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
                logger.warning("StrategyEnableStore: no default session factory: %s", e)
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
                raise RuntimeError("StrategyEnableStore has no session_factory or engine")
            with self._session_factory() as session:
                yield session

    def load_disabled(self) -> Set[str]:
        """Return the persisted set of disabled strategy names (empty if absent/unreadable).

        Fails OPEN: any error returns an empty set (all strategies enabled), the safe default.
        """
        try:
            with self._session() as session:
                row = session.get(PredictionStrategyEnableRow, self.SINGLETON_KEY)
                if row is None or not row.disabled_json:
                    return set()
                data = json.loads(row.disabled_json)
                if not isinstance(data, list):
                    logger.warning("StrategyEnableStore: malformed disabled_json (not a list)")
                    return set()
                return {str(n) for n in data}
        except Exception as e:
            logger.warning("StrategyEnableStore: load failed (failing open): %s", e)
            return set()

    def save_disabled(self, names: Iterable[str]) -> bool:
        """Persist the disabled set (deterministic sorted JSON). Best-effort; never raises."""
        try:
            snapshot = json.dumps(sorted({str(n) for n in names}))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("StrategyEnableStore: could not serialize disabled set: %s", e)
            return False
        try:
            with self._session() as session:
                row = session.get(PredictionStrategyEnableRow, self.SINGLETON_KEY)
                if row is None:
                    row = PredictionStrategyEnableRow(key=self.SINGLETON_KEY)
                row.disabled_json = snapshot
                row.updated_at = datetime.now(timezone.utc)
                session.add(row)
            return True
        except Exception as e:
            logger.warning("StrategyEnableStore: save failed: %s", e)
            return False
