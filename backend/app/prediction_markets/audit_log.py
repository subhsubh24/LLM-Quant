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

FORWARD DEPTH CAPTURE (ROADMAP E11)
-----------------------------------
A decision row can additionally carry the ORDER BOOK AS IT STOOD AT THE DECISION
INSTANT (``book_json``). This exists because retrospective depth is UNOBTAINABLE from
Polymarket: Gamma serves ``liquidity: null`` on resolved markets and CLOB ``/book``
returns 404 for a settled token (both verified live 2026-07-26). That is a venue
data-availability FACT, not a fetcher bug — which means NO past corpus can ever be
capacity-tested, and every committed OOS record's ``liquidity: null`` is honest.

Depth IS observable going forward. Recording the book alongside each decision is the
ONLY route to a MEASURED historical capacity curve (``scripts/capacity_probe.py`` is
the read side; this is the capture side), and the only route to a corpus where the
entry price is OBSERVED rather than estimated — today the corpora price at the CLOB
midpoint and therefore never pay a spread, so their fills are optimistic by
construction. A row carrying a real ``best_bid``/``best_ask`` is a row whose spread
cost can be measured instead of assumed.

The snapshot is OBSERVATION ONLY. Nothing in the trading path ever reads it back: it
does not size, price, gate, or order anything. An absent or malformed book is recorded
as ``None`` — never as a fabricated quote (see :func:`snapshot_order_book`).

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
import math
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from sqlmodel import SQLModel, Field, Session, select

logger = logging.getLogger(__name__)


# ============================================================
# Book-snapshot bounds (ROADMAP E11)
# ============================================================

# How many ask levels (best-first) a decision-time snapshot keeps.
#
# This MUST stay equal to ``scripts/capacity_probe.py``'s ``LADDER_LEVELS`` (40): the
# probe artifact and these forward rows are meant to be read by the SAME capacity code,
# and a ladder truncated at a different depth would make the two samples silently
# non-comparable (a 40-level probe ladder vs an 80-level captured ladder produce
# different book-walk costs for the same market). It is duplicated rather than imported
# because ``scripts/`` is not an importable package from the backend app — the constant
# is the contract, so it is stated here with the reason it cannot drift.
#
# The bound itself is deliberate, not incidental: the far tail of a prediction-market
# book is penny-priced resting size (a 3.96M-contract order at $0.001 was observed live)
# which is real but untradeable, so storing the WHOLE book would bloat every audit row
# with levels no capacity analysis is allowed to count as depth.
BOOK_LADDER_LEVELS = 40

# Slippage bands the executable-depth scalars use, in dollars. Pre-registered to match
# ``capacity_probe.BAND_CENTS`` so a forward row and a probe row mean the same thing.
BOOK_BAND_CENTS = (0.02, 0.05)


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

    # ORDER BOOK AT THE DECISION INSTANT (ROADMAP E11), or NULL when no real
    # two-sided book was obtainable. Shape: see :func:`snapshot_order_book`.
    #
    # WHY A DEDICATED COLUMN rather than another key inside ``payload_json``:
    #   * "was depth captured for this decision?" is the primary query of the whole
    #     feature (``WHERE book_json IS NOT NULL``), and it must be answerable in SQL
    #     without deserializing every row's free-form blob and hoping a key is present.
    #   * ``payload_json`` is written ONLY by ``record_would_be_order`` and holds the
    #     executor's result envelope. Depth is a property of the MARKET at the decision
    #     instant, not of the order result; merging the two would make a NULL ambiguous
    #     between "no book" and "not an order row".
    #   * NULL is a first-class, meaningful value here — it is the honest record of "the
    #     venue did not serve a real two-sided quote", which is precisely the fact E11
    #     exists to stop guessing about. A missing dict key cannot say that.
    #
    # WHY JSON-IN-ONE-COLUMN rather than four scalar columns + a ladder table: the ladder
    # is inherently a nested list, so it needs JSON regardless; splitting the touch
    # scalars out would multiply the schema delta (below) for query power nothing needs.
    #
    # SCHEMA-PATH CAVEAT (read before deploying): this repo has NO migration tool. The one
    # and only schema path is ``db.database.init_db`` → ``SQLModel.metadata.create_all``,
    # which CREATES missing tables but never ALTERs an existing one. A fresh database gets
    # this column automatically; a database that already contains ``prediction_audit_log``
    # does NOT, and every insert would then fail on the unknown column. ``_write`` detects
    # exactly that failure and logs the one-line fix LOUDLY rather than letting the
    # best-effort swallow turn it into a silent audit blackout.
    book_json: Optional[str] = None

    def get_payload(self) -> dict:
        if self.payload_json:
            try:
                return json.loads(self.payload_json)
            except (json.JSONDecodeError, ValueError, TypeError):
                return {}
        return {}

    def get_book(self) -> Optional[dict]:
        """The decision-time book snapshot, or None if none was captured.

        Returns None (not ``{}``) for an absent snapshot so a caller can never mistake
        "no book was obtainable" for "a book with no depth" — the same distinction
        ``get_order_book`` protects by refusing to fabricate a 0/1 quote.
        """
        if not self.book_json:
            return None
        try:
            parsed = json.loads(self.book_json)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None


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


def _book_json(book: Optional[dict]) -> Optional[str]:
    """Serialize a book snapshot for storage, or None.

    A serialization failure yields ``None`` rather than a partial string: half a book is
    not a book, and a truncated JSON blob would read back as a corrupt "captured" row.
    """
    if not book:
        return None
    try:
        return json.dumps(book, default=str)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("AuditLogger: could not serialize book snapshot (%s) — storing None", e)
        return None


def snapshot_order_book(
    book: Any, *, captured_utc: Optional[datetime] = None
) -> Optional[dict]:
    """Summarize a live ``OrderBook`` into the bounded dict stored in ``book_json``.

    Returns ``None`` — never a partial or invented quote — for anything that is not a
    real two-sided book. This function deliberately does NOT re-derive or repair a
    quote: ``PolymarketClient.get_order_book`` already drops non-finite/out-of-range
    levels, sorts both sides best-first, and REFUSES a one-sided book rather than
    fabricating ``best_bid=0.0`` / ``best_ask=1.0`` (which a strategy would read as a
    real 100%-wide market — the data analog of a fake fill). Reusing that honesty is the
    whole point; re-implementing it here would create a second, weaker definition of
    "a real quote" that could disagree with the one the trading path uses.

    The emitted keys MIRROR ``capacity_probe.probe_market``'s row shape on purpose, so a
    forward-captured row and a probe-artifact row can be fed to the same capacity code:

      ``best_bid`` / ``best_ask`` / ``spread``  the real touch — the numbers that make a
          decision's spread cost MEASURED instead of assumed (today's corpora price at
          the midpoint and so never pay a spread at all).
      ``n_ask_levels``          full ask-ladder length BEFORE truncation, so a reader can
          see when the stored ladder is a truncation rather than the whole book.
      ``depth_at_touch_contracts``          size resting AT the best ask.
      ``depth_within_2c/5c_contracts``      cumulative ask size within the slippage bands
          — computed over the FULL ladder, not the truncated one, so the number does not
          quietly depend on ``BOOK_LADDER_LEVELS``.
      ``total_ask_contracts``   whole visible ask side. Context ONLY — it is NOT
          tradeable capacity (the tail is penny-priced resting size).
      ``ask_ladder``            the bounded, best-first ladder itself. This is what makes
          impact CALIBRATABLE with no free parameter: walking a real ladder gives the
          true cost of filling N contracts.

    LIMITATION, stated rather than hidden: only the ASK ladder is stored (plus the bid
    TOUCH), matching the probe artifact — the ask side is what a taker BUY lifts, and the
    deployed strategies open with BUYs. A SELL-side capacity question needs the bid
    ladder and this snapshot cannot answer it.
    """
    if book is None:
        return None
    try:
        best_bid = getattr(book, "best_bid", None)
        best_ask = getattr(book, "best_ask", None)
        raw_asks = getattr(book, "asks", None) or []
        if best_bid is None or best_ask is None or not raw_asks:
            return None
        best_bid = float(best_bid)
        best_ask = float(best_ask)
        if not (math.isfinite(best_bid) and math.isfinite(best_ask)):
            return None

        levels: List[dict] = []
        for lvl in raw_asks:
            try:
                p = float(lvl["price"])
                s = float(lvl["size"])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if not (math.isfinite(p) and math.isfinite(s)):
                continue
            levels.append({"price": p, "size": s})
        if not levels:
            # Every level was unusable. That is "no book", not "zero depth" — recording
            # a 0-depth snapshot here would understate the capacity distribution while
            # LOOKING like conservatism, which is a data error dressed as caution.
            return None
        # Best (lowest) ask first. The client already sorts, so this is normally a no-op;
        # it is here so the ``[:BOOK_LADDER_LEVELS]`` bound below always means "the levels
        # nearest the touch" even for a book that reached us from some other producer.
        levels.sort(key=lambda lvl: lvl["price"])

        snap = {
            "captured_utc": (captured_utc or datetime.now(timezone.utc)).isoformat(),
            "token_id": getattr(book, "token_id", None),
            "best_bid": best_bid,
            "best_ask": best_ask,
            # Recomputed from the two touches rather than trusting ``book.spread``, so the
            # stored spread can never disagree with the stored bid/ask.
            "spread": round(best_ask - best_bid, 6),
            "n_ask_levels": len(levels),
            "depth_at_touch_contracts": round(
                sum(lvl["size"] for lvl in levels if lvl["price"] == best_ask), 4
            ),
            "total_ask_contracts": round(sum(lvl["size"] for lvl in levels), 4),
            "ask_ladder": [
                {"price": lvl["price"], "size": round(lvl["size"], 4)}
                for lvl in levels[:BOOK_LADDER_LEVELS]
            ],
            "ladder_levels_bound": BOOK_LADDER_LEVELS,
        }
        for band in BOOK_BAND_CENTS:
            snap[f"depth_within_{int(band * 100)}c_contracts"] = round(
                sum(lvl["size"] for lvl in levels if lvl["price"] <= best_ask + band), 4
            )
        return snap
    except Exception as e:  # pragma: no cover - defensive
        # A malformed book must never propagate. Recording nothing is correct; recording
        # a guess would poison the very measurement this feature exists to produce.
        logger.warning("snapshot_order_book: unusable book (%s: %s) — recording None",
                       type(e).__name__, e)
        return None


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
            # FAIL LOUD on the one failure mode that would silently kill the ENTIRE audit
            # trail rather than one row: this repo has no migration tool, so a database
            # that already contains ``prediction_audit_log`` never gains the E11
            # ``book_json`` column from ``create_all``, and then EVERY insert fails on the
            # unknown column while the best-effort swallow hides it. Name the exact
            # one-line fix at ERROR level so the operator sees a cause, not a mystery.
            if "book_json" in str(e):
                logger.error(
                    "AuditLogger: the audit INSERT references `book_json` but this "
                    "database's prediction_audit_log table does not have that column, so "
                    "EVERY audit write is failing (not just this one). This repo has no "
                    "migration tool — create_all() never ALTERs an existing table. Run "
                    "once against the database: "
                    "ALTER TABLE prediction_audit_log ADD COLUMN book_json TEXT; "
                    "(underlying error: %s)", e,
                )
            else:
                logger.warning(
                    "AuditLogger: failed to persist %s event: %s", row.event_type, e
                )

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
        book: Optional[dict] = None,
    ) -> None:
        """Record a non-order trading decision (dq_reject/risk_reject/kelly_skip).

        ``book`` is an optional decision-time snapshot from :func:`snapshot_order_book`
        (ROADMAP E11). Passing ``None`` is a first-class outcome, not an error: it is the
        honest record of "no real two-sided book was obtainable at that instant".
        """
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
                book_json=_book_json(book),
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
        book: Optional[dict] = None,
    ) -> None:
        """Record the REAL ``OrderResult`` that traversed the executor path.

        The event_type is derived from the actual result — a gated or rejected
        order is logged as such with its real error, never as a fake success.
        ``is_dry_run`` / ``live_enabled`` (the executor's mode at decision time) are
        stored so a later query can tell paper, gated-live, and live orders apart.

        ``book`` is the optional decision-time depth snapshot (ROADMAP E11). This is the
        row that matters most for capacity: it is the one where a size was actually
        committed, so pairing it with the real ladder is what turns "what could this bot
        have traded at scale?" from an assumption into a measurement.
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
                book_json=_book_json(book),
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
