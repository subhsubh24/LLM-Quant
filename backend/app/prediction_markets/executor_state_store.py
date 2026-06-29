"""
Durable persistence for the executor's SAFETY state (ROADMAP D3/D4 / run-risk-readiness).

The kill switch and the realized-PnL loss-cap counters live in memory on
``PredictionMarketExecutor``. That is correct for a single long-lived process, but a
backend restart silently RESET them — a tripped kill switch would un-trip and the
accumulated daily/total realized loss would reset to zero, re-opening the loss-cap
budget. For a real-money safety control that is the wrong default: a restart must NOT
forget that trading was halted or how much has already been lost.

This module is the thin, best-effort persistence layer that lets the executor's safety
state SURVIVE restarts. It mirrors ``strategy_registry_store.py`` / ``audit_log.py``
exactly — the proven, dual-import-safe recipe:

* A single ``table=True`` row type with ``extend_existing`` so the dual ``app.*`` /
  ``backend.app.*`` import paths can't double-register and crash import.
* Best-effort + non-fatal: every read/write is wrapped so a persistence hiccup can NEVER
  break the trade path. Durability is a hardening, not a new failure mode — if the DB is
  unreachable the executor still runs (just without cross-restart memory, exactly as
  before this module existed).

HONESTY / SAFE-BY-DEFAULT
  * This stores exactly what the executor produced; it cannot fabricate a fill, an
    order, or a PnL number.
  * Persistence is OPT-IN via :meth:`PredictionMarketExecutor.attach_state_store` (wired
    on the production singleton in ``get_executor``). A bare ``PredictionMarketExecutor``
    constructed for a test/harness has NO store and therefore fresh, isolated state — so
    this change does not couple the existing deterministic tests/harness to a DB.
  * Rehydration only ever RESTORES a tripped kill switch / accumulated loss; it can never
    CLEAR one (a persisted tripped switch loads as tripped). The safe direction.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlmodel import SQLModel, Field, Session

logger = logging.getLogger(__name__)


# ============================================================
# Table
# ============================================================

class PredictionExecutorStateRow(SQLModel, table=True):
    """One row holding the executor's safety state (singleton, ``key="singleton"``).

    Only SAFETY state is persisted — the kill switch and the realized-PnL loss-cap
    counters. Open positions are NOT persisted here (they are reconstructed from the
    market/position store); this row exists solely so a restart cannot forget a halt or
    an accumulated loss.
    """
    __tablename__ = "prediction_executor_state"
    # See audit_log.PredictionAuditLog for why extend_existing is required: the package
    # is importable under two module paths in some test sessions, and a table=True class
    # registers with the shared SQLModel.metadata at import time.
    __table_args__ = {"extend_existing": True}

    key: str = Field(default="singleton", primary_key=True)
    kill_switch_active: bool = Field(default=False)
    kill_switch_reason: str = Field(default="")
    kill_switch_time: Optional[datetime] = Field(default=None)
    realized_pnl_total: float = Field(default=0.0)
    realized_pnl_daily: float = Field(default=0.0)
    loss_cap_day: str = Field(default="")  # ISO date (UTC) the daily tally belongs to
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# Helpers
# ============================================================

def init_db(engine) -> None:
    """Create the executor-state table on the given engine (used by tests on in-memory DB)."""
    SQLModel.metadata.create_all(engine, tables=[PredictionExecutorStateRow.__table__])


def _default_session_factory():
    """Return the app's ``get_session()`` contextmanager (imported lazily)."""
    from ..db.database import get_session
    return get_session


def _parse_dt(value: Any) -> Optional[datetime]:
    """Best-effort ISO/`datetime` -> aware datetime. Returns None on anything unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


# ============================================================
# Store
# ============================================================

class ExecutorStateStore:
    """Best-effort durable load/save for executor SAFETY state.

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
                logger.warning("ExecutorStateStore: no default session factory: %s", e)
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
                raise RuntimeError("ExecutorStateStore has no session_factory or engine")
            with self._session_factory() as session:
                yield session

    def load(self) -> Optional[dict]:
        """Return the persisted state as a plain dict, or ``None`` if absent/unreadable.

        ``None`` signals "nothing persisted yet" so the caller keeps its fresh in-memory
        state (distinguishing "never persisted" from "persisted but zeroed").
        """
        try:
            with self._session() as session:
                row = session.get(PredictionExecutorStateRow, self.SINGLETON_KEY)
                if row is None:
                    return None
                return {
                    "kill_switch_active": bool(row.kill_switch_active),
                    "kill_switch_reason": row.kill_switch_reason or "",
                    "kill_switch_time": _parse_dt(row.kill_switch_time),
                    "realized_pnl_total": float(row.realized_pnl_total),
                    "realized_pnl_daily": float(row.realized_pnl_daily),
                    "loss_cap_day": row.loss_cap_day or "",
                }
        except Exception as e:
            logger.warning("ExecutorStateStore: load failed: %s", e)
            return None

    def save(self, state: dict) -> bool:
        """Persist the executor safety state. Returns True on success (best-effort, never raises)."""
        try:
            with self._session() as session:
                row = session.get(PredictionExecutorStateRow, self.SINGLETON_KEY)
                if row is None:
                    row = PredictionExecutorStateRow(key=self.SINGLETON_KEY)
                row.kill_switch_active = bool(state.get("kill_switch_active", False))
                row.kill_switch_reason = str(state.get("kill_switch_reason", "") or "")
                kst = state.get("kill_switch_time")
                row.kill_switch_time = kst if isinstance(kst, datetime) else _parse_dt(kst)
                row.realized_pnl_total = float(state.get("realized_pnl_total", 0.0))
                row.realized_pnl_daily = float(state.get("realized_pnl_daily", 0.0))
                row.loss_cap_day = str(state.get("loss_cap_day", "") or "")
                row.updated_at = datetime.now(timezone.utc)
                session.add(row)
            return True
        except Exception as e:
            logger.warning("ExecutorStateStore: save failed: %s", e)
            return False


class _NoOpExecutorStateStore:
    """Fallback used if store construction fails — never raises, never persists."""

    def load(self) -> Optional[dict]:
        return None

    def save(self, state: dict) -> bool:
        return False
