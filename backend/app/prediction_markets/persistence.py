"""
Database persistence layer for prediction market trading.

Bridges the in-memory executor state to SQLModel tables so that
positions, orders, and P&L survive server restarts.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, select

from ..db.database import get_session
from .models import (
    PredictionOrder,
    PredictionPosition,
    PredictionPortfolioSnapshot,
    PredictionStrategyPerformance,
)
from .execution import (
    Exchange,
    OrderResult,
    OrderRequest,
    OrderSide,
    OrderStatus,
    PredictionMarketExecutor,
    Position,
)

logger = logging.getLogger(__name__)

DEFAULT_PORTFOLIO_ID = 1


def _ensure_default_portfolio(session) -> None:
    """Ensure the default portfolio (id=1) row exists so order/position FKs resolve.

    Orders and positions reference ``portfolio_id=1``. SQLite does NOT enforce foreign
    keys by default, so a missing parent row was silently tolerated in dev; Neon Postgres
    DOES enforce them, so inserts raised ForeignKeyViolation and the durable forward record
    never persisted. Create the parent row (idempotent) in the SAME transaction as the insert.
    """
    from .models import PredictionPortfolio
    if session.get(PredictionPortfolio, DEFAULT_PORTFOLIO_ID) is None:
        session.add(PredictionPortfolio(id=DEFAULT_PORTFOLIO_ID, name="default", exchange="all"))
        session.flush()


# ============================================================
# Order persistence
# ============================================================

def save_order(
    result: OrderResult,
    strategy: str = "",
    market_question: str = "",
    outcome_label: str = "",
    is_dry_run: bool = True,
) -> Optional[int]:
    """Persist an order result to the database. Returns the row ID."""
    with get_session() as session:
        _ensure_default_portfolio(session)
        order = PredictionOrder(
            portfolio_id=DEFAULT_PORTFOLIO_ID,
            exchange=result.exchange.value,
            market_id=result.market_id,
            token_id=result.token_id,
            side=result.side.value,
            order_type=result.order_type.value,
            size=result.size,
            limit_price=result.price,
            order_id=result.order_id,
            status=result.status.value,
            filled_size=result.filled_size,
            filled_price=result.filled_price,
            fees=result.fees,
            strategy=strategy,
            error=result.error,
            is_dry_run=is_dry_run,
            raw_response_json=json.dumps(result.raw_response) if result.raw_response else None,
        )
        session.add(order)
        session.flush()
        return order.id


def get_orders(
    strategy: Optional[str] = None,
    exchange: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[PredictionOrder]:
    """Query order history with optional filters."""
    with get_session() as session:
        stmt = select(PredictionOrder).order_by(PredictionOrder.created_at.desc())
        if strategy:
            stmt = stmt.where(PredictionOrder.strategy == strategy)
        if exchange:
            stmt = stmt.where(PredictionOrder.exchange == exchange)
        if status:
            stmt = stmt.where(PredictionOrder.status == status)
        stmt = stmt.limit(limit)
        return list(session.exec(stmt).all())


# ============================================================
# Position persistence
# ============================================================

def save_position(pos: Position, market_question: str = "", outcome_label: str = "", category: str = ""):
    """Upsert a position (insert or update by token_id)."""
    with get_session() as session:
        _ensure_default_portfolio(session)
        # Check if position already exists
        stmt = select(PredictionPosition).where(PredictionPosition.token_id == pos.token_id)
        existing = session.exec(stmt).first()

        if existing:
            existing.size = pos.size
            existing.avg_entry_price = pos.avg_entry_price
            existing.current_price = pos.current_price
            existing.market_value = pos.market_value
            existing.unrealized_pnl = pos.unrealized_pnl
            existing.realized_pnl = pos.realized_pnl
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            db_pos = PredictionPosition(
                portfolio_id=DEFAULT_PORTFOLIO_ID,
                exchange=pos.exchange.value,
                market_id=pos.market_id,
                token_id=pos.token_id,
                market_question=market_question or pos.market_question,
                outcome_label=outcome_label or pos.outcome_label,
                category=category,
                side=pos.side,
                size=pos.size,
                avg_entry_price=pos.avg_entry_price,
                current_price=pos.current_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                strategy=pos.strategy,
                opened_at=pos.opened_at,
            )
            session.add(db_pos)


def delete_position(token_id: str):
    """Remove a closed position from the database."""
    with get_session() as session:
        stmt = select(PredictionPosition).where(PredictionPosition.token_id == token_id)
        existing = session.exec(stmt).first()
        if existing:
            session.delete(existing)


def get_positions(
    exchange: Optional[str] = None,
    strategy: Optional[str] = None,
    open_only: bool = True,
) -> List[PredictionPosition]:
    """Get positions with optional filters.

    ``open_only`` (default True) excludes rows already settled
    (``is_resolved == True``) — the correct behaviour for rehydrating live
    state (ROADMAP D8): a resolved position has already booked its realized PnL
    and been removed from the executor, so reloading it would resurrect a dead
    position that ``check_resolutions`` would try to re-settle. The docstring
    of this function always claimed "open positions" but it returned ALL rows;
    this makes code match contract. Pass ``open_only=False`` to include closed
    rows (e.g. for a full history view).
    """
    with get_session() as session:
        stmt = select(PredictionPosition).order_by(PredictionPosition.updated_at.desc())
        if open_only:
            stmt = stmt.where(PredictionPosition.is_resolved == False)  # noqa: E712
        if exchange:
            stmt = stmt.where(PredictionPosition.exchange == exchange)
        if strategy:
            stmt = stmt.where(PredictionPosition.strategy == strategy)
        return list(session.exec(stmt).all())


def load_positions_into_executor(executor: PredictionMarketExecutor):
    """
    Restore persisted positions into the executor's in-memory state.

    Call this on startup to resume from where we left off.

    Loads OPEN positions only (``is_resolved == False``) — a resolved position
    has already booked its PnL and must not be resurrected. Idempotent: a token
    already present in memory (a fresher in-process position) is not clobbered,
    so a redundant call is a safe no-op.

    The rows are read and the ``Position`` objects are built INSIDE the open
    session. ``get_session()`` uses the default ``expire_on_commit=True``, so a
    returned-and-detached ORM row would raise ``DetachedInstanceError`` on the
    first attribute access after the session closes — the exact latent bug that
    hid here because this helper had ZERO call sites until ROADMAP D8 wired it.
    """
    loaded = 0
    skipped = 0
    total_open = 0
    with get_session() as session:
        stmt = (
            select(PredictionPosition)
            .where(PredictionPosition.is_resolved == False)  # noqa: E712
            .order_by(PredictionPosition.updated_at.desc())
        )
        db_positions = list(session.exec(stmt).all())
        total_open = len(db_positions)
        for db_pos in db_positions:
            if db_pos.token_id in executor.positions:
                continue
            # SIDE-EFFECT INTEGRITY / FACTORY_STANDARD §32: rehydrating ONE row is a
            # per-row side-effect; a single malformed/legacy row (e.g. an ``exchange`` value
            # that is no longer a valid ``Exchange`` enum member — a schema/enum change, a
            # manual edit, or a venue string added before its enum) must NEVER abort the
            # WHOLE rehydration. Before this guard, an uncaught ``Exchange(...)`` ValueError
            # crashed the loop inside the session → EVERY open position stayed orphaned →
            # ``check_resolutions`` (which reads in-memory ``executor.positions``) never
            # settled them → realized losses never booked → the loss caps / kill switch never
            # saw them. Build the Position first; a failure logs LOUD (swallow the BLOCK, not
            # the SIGNAL — §28) and skips only that row so the rest still rehydrate.
            try:
                pos = Position(
                    exchange=Exchange(db_pos.exchange),
                    market_id=db_pos.market_id,
                    token_id=db_pos.token_id,
                    market_question=db_pos.market_question,
                    outcome_label=db_pos.outcome_label,
                    side=db_pos.side,
                    size=db_pos.size,
                    avg_entry_price=db_pos.avg_entry_price,
                    current_price=db_pos.current_price,
                    unrealized_pnl=db_pos.unrealized_pnl,
                    realized_pnl=db_pos.realized_pnl,
                    strategy=db_pos.strategy,
                    # Carry the persisted correlation bucket so the risk manager counts this
                    # rehydrated position against its REAL category, not "General" (the
                    # per-category cap otherwise silently degrades to a global cap across the
                    # fresh-process paper cycle — a confirmed live freeze, 2026-07-02).
                    category=db_pos.category or "",
                    opened_at=db_pos.opened_at,
                    updated_at=db_pos.updated_at,
                )
                # Surface a LEGACY short (side="short") anomaly loudly. Shorts cannot be
                # opened since #215 (the executor's SELL guard rejects opening one), so a
                # rehydrated short is a stale pre-#215 DB row. The executor now QUARANTINES
                # it (a BUY on it is rejected, not scaled — D4 follow-up), but it should be
                # cleaned up manually; a WARNING makes it visible rather than silent.
                if str(getattr(pos, "side", "long")) == "short":
                    logger.warning(
                        "rehydrated a LEGACY short position (token_id=%r, size=%s) — shorts "
                        "cannot be opened since #215; this stale row is quarantined (BUYs "
                        "rejected), resolve it manually",
                        db_pos.token_id, db_pos.size,
                    )
            except Exception as e:
                skipped += 1
                logger.error(
                    "skipping un-rehydratable open position row (token_id=%r, "
                    "exchange=%r): %s — the other open positions still rehydrate",
                    db_pos.token_id, db_pos.exchange, e,
                )
                continue
            executor.positions[db_pos.token_id] = pos
            loaded += 1
    logger.info(
        f"Rehydrated {loaded} open prediction-market position(s) from DB "
        f"({total_open} open row(s) found, {skipped} skipped)"
    )


# ============================================================
# Portfolio snapshots (equity curve)
# ============================================================

def save_portfolio_snapshot(executor: PredictionMarketExecutor):
    """Take a snapshot of current portfolio state for the equity curve."""
    poly_exposure = sum(
        p.market_value for p in executor.positions.values()
        if p.exchange == Exchange.POLYMARKET
    )
    total_unrealized = sum(p.unrealized_pnl for p in executor.positions.values())
    total_realized = sum(p.realized_pnl for p in executor.positions.values())

    # Count wins/losses from order history
    wins = sum(1 for o in executor.order_history if o.is_success and o.filled_price > 0)
    losses = sum(1 for o in executor.order_history if o.status == OrderStatus.REJECTED)

    with get_session() as session:
        snapshot = PredictionPortfolioSnapshot(
            total_positions=len(executor.positions),
            total_exposure=executor.total_exposure,
            cash_balance=executor.max_portfolio_usd - executor.total_exposure,
            total_value=executor.max_portfolio_usd + executor.total_pnl,
            unrealized_pnl=total_unrealized,
            realized_pnl=total_realized,
            total_pnl=executor.total_pnl,
            total_fees=executor.total_fees,
            total_orders=len(executor.order_history),
            total_fills=sum(1 for o in executor.order_history if o.status == OrderStatus.FILLED),
            win_count=wins,
            loss_count=losses,
            polymarket_exposure=poly_exposure,
            is_dry_run=executor.dry_run,
        )
        session.add(snapshot)


def get_portfolio_snapshots(limit: int = 500) -> List[PredictionPortfolioSnapshot]:
    """Get portfolio snapshots for equity curve rendering."""
    with get_session() as session:
        stmt = (
            select(PredictionPortfolioSnapshot)
            .order_by(PredictionPortfolioSnapshot.created_at.desc())
            .limit(limit)
        )
        return list(session.exec(stmt).all())


# ============================================================
# Strategy performance tracking
# ============================================================

def update_strategy_performance(
    strategy: str,
    pnl: float,
    fees: float,
    edge: float,
    confidence: float,
    notional: float,
    is_win: bool,
):
    """Update cumulative performance for a strategy after a trade resolves."""
    with get_session() as session:
        stmt = select(PredictionStrategyPerformance).where(
            PredictionStrategyPerformance.strategy == strategy
        )
        perf = session.exec(stmt).first()

        if not perf:
            perf = PredictionStrategyPerformance(strategy=strategy, first_trade_at=datetime.utcnow())

        perf.total_trades += 1
        if is_win:
            perf.winning_trades += 1
        else:
            perf.losing_trades += 1
        perf.win_rate = perf.winning_trades / perf.total_trades if perf.total_trades > 0 else 0.0

        perf.total_pnl += pnl
        perf.avg_pnl_per_trade = perf.total_pnl / perf.total_trades if perf.total_trades > 0 else 0.0
        perf.max_win = max(perf.max_win, pnl) if is_win else perf.max_win
        perf.max_loss = min(perf.max_loss, pnl) if not is_win else perf.max_loss
        perf.total_fees += fees

        # Running averages
        n = perf.total_trades
        perf.avg_edge = perf.avg_edge * (n - 1) / n + edge / n
        perf.avg_confidence = perf.avg_confidence * (n - 1) / n + confidence / n

        perf.total_notional += notional
        perf.last_trade_at = datetime.utcnow()
        perf.updated_at = datetime.utcnow()

        session.add(perf)


def get_strategy_performance() -> List[PredictionStrategyPerformance]:
    """Get performance for all strategies."""
    with get_session() as session:
        stmt = select(PredictionStrategyPerformance).order_by(
            PredictionStrategyPerformance.total_pnl.desc()
        )
        return list(session.exec(stmt).all())
