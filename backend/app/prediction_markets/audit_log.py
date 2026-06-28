"""
Persistent audit log for prediction-market trading decisions and orders.

ROADMAP G3 / PENDING_OPS OA-10.

The orchestrator keeps an in-memory ``activity_log`` (max 200 entries) for the
frontend, but that history is lost on every restart. This module adds a DURABLE,
DB-backed audit trail of:

  * every trading DECISION the scan loop makes (why an opportunity was rejected,
    skipped, or sized to zero), and
  * every would-be ORDER that traverses the executor (filled, rejected, or gated
    off by the real-money master gate).

Design principles
-----------------
* Best-effort and non-fatal: EVERY write is wrapped so an audit failure can NEVER
  break the scan/trade path. This mirrors the error-swallowing idiom used by
  ``orchestrator._persist_order``.
* Side-effect integrity: a logged order ALWAYS reflects the actual ``OrderResult``
  that traversed the executor path. A gated or rejected order is recorded AS such,
  with its real error — never fabricated as a success.

This module imports only SQLModel/SQLAlchemy + stdlib + the app's database layer,
so it stays inside the CI import gate.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from sqlmodel import SQLModel, Field, Session, select

logger = logging.getLogger(__name__)


# ============================================================
# Table
# ============================================================

class PredictionAuditLog(SQLModel, table=True):
    """
    Durable audit record of a single trading decision or would-be order.

    Unlike the in-memory ``activity_log``, these rows survive restarts so the
    full decision/order history can be reconstructed and reviewed.
    """
    __tablename__ = "prediction_audit_log"
    # Defensive: this package is importable under two module paths in some test
    # sessions (``app.*`` via conftest's sys.path and ``backend.app.*`` in
    # production). A ``table=True`` class registers its Table with the shared
    # ``SQLModel.metadata`` at import time, so a dual-path import would otherwise
    # raise "Table is already defined". ``extend_existing`` makes the second
    # registration a no-op redefinition instead of a hard crash — the table can
    # never take down app/test import just by being seen twice.
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)

    # When the event happened (UTC). Indexed for newest-first queries.
    ts: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )

    # One of: dq_reject, risk_reject, kelly_skip, order_filled,
    # order_rejected, order_gated.
    event_type: str = Field(index=True)

    # Context (all optional — decisions and orders populate different subsets).
    strategy: Optional[str] = Field(default=None, index=True)
    market_id: Optional[str] = Field(default=None, index=True)
    market_question: Optional[str] = None
    side: Optional[str] = None
    size: Optional[float] = None
    price: Optional[float] = None
    edge: Optional[float] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None

    # Order-specific (populated by record_would_be_order).
    order_id: Optional[str] = None
    is_dry_run: Optional[bool] = None
    live_enabled: Optional[bool] = None

    # Free-form JSON blob for anything not captured by a column.
    payload_json: Optional[str] = None

    def get_payload(self) -> dict:
        if self.payload_json:
            try:
                return json.loads(self.payload_json)
            except (json.JSONDecodeError, ValueError, TypeError):
                return {}
        return {}


# ============================================================
# Helpers
# ============================================================

def init_db(engine) -> None:
    """Create the audit-log table on the given engine if it does not exist.

    Production relies on the app's existing table creation (the table is
    registered with ``SQLModel.metadata`` simply by importing this module).
    Tests use this to materialize the table on an in-memory engine.
    """
    SQLModel.metadata.create_all(engine, tables=[PredictionAuditLog.__table__])


def _default_session_factory():
    """Return the app's ``get_session()`` contextmanager.

    Imported lazily so that constructing an :class:`AuditLogger` with an explicit
    ``session_factory`` or ``engine`` never requires the app's settings/database
    module to import cleanly (handy in isolated tests).
    """
    from ..db.database import get_session
    return get_session


def _enum_value(v: Any) -> Optional[str]:
    """Best-effort extraction of a string value from an Enum or plain value."""
    if v is None:
        return None
    return getattr(v, "value", v)


# ============================================================
# Logger
# ============================================================

class AuditLogger:
    """Best-effort writer for :class:`PredictionAuditLog` rows.

    Parameters
    ----------
    session_factory:
        A zero-arg callable returning a context manager yielding a SQLModel
        ``Session`` (defaults to the app's ``get_session``). Used when no
        ``engine`` is supplied.
    engine:
        If provided (e.g. an in-memory SQLite engine in tests), a fresh
        ``Session(engine)`` is opened per write and this takes precedence over
        ``session_factory``.
    """

    def __init__(
        self,
        session_factory: Optional[Callable[[], Any]] = None,
        engine: Any = None,
    ):
        self._engine = engine
        # Resolve the default factory lazily so construction is cheap and robust.
        if session_factory is None and engine is None:
            try:
                session_factory = _default_session_factory()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("AuditLogger: could not resolve default session factory: %s", e)
                session_factory = None
        self._session_factory = session_factory

    # -- session plumbing ---------------------------------------------------

    @contextmanager
    def _session(self):
        """Yield a committed/rolled-back session from engine or factory."""
        if self._engine is not None:
            # expire_on_commit=False keeps attributes loaded after commit so
            # recent() can return detached rows that are still readable.
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
                raise RuntimeError("AuditLogger has no session_factory or engine")
            with self._session_factory() as session:
                yield session

    def _write(self, row: PredictionAuditLog) -> None:
        """Persist one row, swallowing any error (best-effort, never raises)."""
        try:
            with self._session() as session:
                session.add(row)
        except Exception as e:
            logger.warning("AuditLogger: failed to persist %s event: %s", row.event_type, e)

    # -- public API ---------------------------------------------------------

    def record_decision(
        self,
        event_type: str,
        *,
        strategy: Optional[str] = None,
        market_id: Optional[str] = None,
        market_question: Optional[str] = None,
        side: Optional[str] = None,
        size: Optional[float] = None,
        price: Optional[float] = None,
        edge: Optional[float] = None,
        confidence: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Record a non-order trading decision (dq_reject/risk_reject/kelly_skip)."""
        try:
            row = PredictionAuditLog(
                event_type=event_type,
                strategy=strategy,
                market_id=market_id,
                market_question=market_question,
                side=side,
                size=size,
                price=price,
                edge=edge,
                confidence=confidence,
                reason=reason,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("AuditLogger: failed to build %s row: %s", event_type, e)
            return
        self._write(row)

    def record_would_be_order(
        self,
        result: Any,
        *,
        strategy: Optional[str] = None,
        market_question: Optional[str] = None,
        edge: Optional[float] = None,
        confidence: Optional[float] = None,
        is_dry_run: Optional[bool] = None,
        live_enabled: Optional[bool] = None,
    ) -> None:
        """Record the REAL ``OrderResult`` that traversed the executor path.

        The event_type is derived from the actual result — a gated or rejected
        order is logged as such with its real error, never as a fake success.
        ``is_dry_run`` / ``live_enabled`` (the executor's mode at decision time) are
        stored so a later query can tell paper, gated-live, and live orders apart.
        """
        try:
            error = getattr(result, "error", None)
            is_success = bool(getattr(result, "is_success", False))

            if is_success:
                event_type = "order_filled"
            elif error and "LIVE_TRADING_ENABLED" in str(error):
                event_type = "order_gated"
            else:
                event_type = "order_rejected"

            status = _enum_value(getattr(result, "status", None))
            payload = {
                "status": status,
                "filled_size": getattr(result, "filled_size", None),
                "filled_price": getattr(result, "filled_price", None),
                "fees": getattr(result, "fees", None),
                "error": error,
            }

            # None-safe fill price: OrderResult.filled_price defaults to 0.0 (not None),
            # so a truthiness fallback would silently log the LIMIT price for a real fill
            # at 0.0. Fall back to the limit price ONLY when filled_price is genuinely None.
            filled_price = getattr(result, "filled_price", None)
            price = filled_price if filled_price is not None else getattr(result, "price", None)

            row = PredictionAuditLog(
                event_type=event_type,
                strategy=strategy,
                market_id=getattr(result, "market_id", None),
                market_question=market_question,
                side=_enum_value(getattr(result, "side", None)),
                size=getattr(result, "size", None),
                price=price,
                edge=edge,
                confidence=confidence,
                reason=error,
                order_id=getattr(result, "order_id", None),
                is_dry_run=is_dry_run,
                live_enabled=live_enabled,
                payload_json=json.dumps(payload, default=str),
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("AuditLogger: failed to build would-be order row: %s", e)
            return
        self._write(row)

    def recent(self, limit: int = 100) -> List[PredictionAuditLog]:
        """Return the most recent audit rows, newest first (best-effort).

        Rows are detached from the session (expunged) so callers can read their
        attributes after the session closes.
        """
        try:
            with self._session() as session:
                stmt = (
                    select(PredictionAuditLog)
                    .order_by(PredictionAuditLog.id.desc())
                    .limit(limit)
                )
                rows = list(session.exec(stmt).all())
                # Eager-load every attribute, then detach so post-close access
                # does not trigger a DetachedInstanceError on commit-expire.
                for row in rows:
                    _ = row.id, row.event_type, row.ts
                session.expunge_all()
                return rows
        except Exception as e:
            logger.warning("AuditLogger: failed to query recent audit rows: %s", e)
            return []


class _NoOpAuditLogger:
    """Fallback used if AuditLogger construction fails — never raises, never persists."""

    def record_decision(self, *args, **kwargs) -> None:  # noqa: D401
        return None

    def record_would_be_order(self, *args, **kwargs) -> None:
        return None

    def recent(self, limit: int = 100) -> List[PredictionAuditLog]:
        return []
