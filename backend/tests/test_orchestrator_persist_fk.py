"""FK integrity on the LIVE order-persist path (orchestrator._persist_order).

WHY THIS EXISTS: the durable forward record persists orders/positions with a hardcoded
``portfolio_id=1``. SQLite does NOT enforce foreign keys by default, but production Neon
Postgres DOES — so a missing default-portfolio parent raised ForeignKeyViolation and every
order failed to persist (confirmed live pre-seed, 2026-07-02). A boot-time seed
(``init_db``) fixes the normal case, but the LIVE writer is ``orchestrator._persist_order``
(``persistence.save_order``/``save_position`` are dead code — never called by the running
loop), and NO test exercised THAT path with FK enforcement. The whole SQLite-based gate was
FK-BLIND by construction, so this bug class could recur invisibly.

These tests close that gap. They enable ``PRAGMA foreign_keys=ON`` so in-memory SQLite
enforces the FK exactly like Postgres, then:
  (1) prove the enforcement is real (a raw order insert with no portfolio parent RAISES);
  (2) prove ``init_db()``'s seed satisfies the FK (the production boot path);
  (3) prove ``orchestrator._persist_order`` is SELF-SUFFICIENT — it persists the order AND
      the position even with NO pre-seeded portfolio, because it now ensures the parent in
      its own transaction. If someone removes that guard AND the seed ever fails, (3) fails
      loud instead of silently losing every order in production.

Import via ``app.*`` (conftest puts backend/ on sys.path) — the suite-wide convention.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.prediction_markets import models as m
from app.prediction_markets import persistence
from app.prediction_markets.execution import (
    Exchange,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PredictionMarketExecutor,
)
from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
from app.prediction_markets.polymarket_client import Market, Outcome, ScanResult


def _fk_engine():
    """In-memory SQLite that enforces foreign keys like Postgres does."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_con, _rec):  # pragma: no cover - trivial pragma
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    for tbl in (m.PredictionPortfolio, m.PredictionPosition, m.PredictionOrder):
        tbl.__table__.create(eng, checkfirst=True)
    return eng


def _make_result():
    return OrderResult(
        order_id="sim_fk_test",
        exchange=Exchange.POLYMARKET,
        market_id="mkt1",
        token_id="tokYes",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=10.0,
        price=0.4,
        status=OrderStatus.FILLED,
        filled_size=10.0,
        filled_price=0.4,
        fees=0.08,
        raw_response={"simulated": True},
    )


def _make_opp():
    market = Market(
        id="mkt1",
        condition_id="0xcond",
        question="Will X happen?",
        slug="will-x",
        description="",
        category="Sports",
        end_date=None,
        outcomes=[
            Outcome(token_id="tokYes", label="Yes", price=0.4, midpoint=0.4, volume=1000.0),
            Outcome(token_id="tokNo", label="No", price=0.6, midpoint=0.6, volume=1000.0),
        ],
        total_volume=2000.0,
        liquidity=5000.0,
        active=True,
        closed=False,
        resolved=False,
    )
    return ScanResult(
        market=market,
        strategy="near_certainty",
        outcome_idx=0,
        side="BUY",
        entry_price=0.4,
        expected_value=0.5,
        edge=0.1,
        confidence=0.9,
        reason="test",
    )


def _held_executor(result):
    """A dry-run executor already holding the filled position (so _persist_order also
    exercises the POSITION insert, which carries the same portfolio FK as the order)."""
    ex = PredictionMarketExecutor(dry_run=True)
    ex.positions[result.token_id] = Position(
        exchange=result.exchange,
        market_id=result.market_id,
        token_id=result.token_id,
        market_question="Will X happen?",
        outcome_label="Yes",
        side="long",
        size=result.filled_size,
        avg_entry_price=result.filled_price,
        current_price=result.filled_price,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        strategy="near_certainty",
    )
    return ex


def test_fk_is_actually_enforced_in_this_test(monkeypatch):
    """Guards against a vacuous suite: a raw order insert with NO portfolio parent MUST
    raise under PRAGMA foreign_keys=ON. If this ever stops raising, FK enforcement is off
    and the other assertions prove nothing."""
    from sqlalchemy.exc import IntegrityError

    eng = _fk_engine()
    # order_id is set (NOT NULL) so the ONLY possible failure is the portfolio FK — this
    # keeps the "FK is enforced" assertion honest, not a NOT-NULL false positive.
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        with Session(eng) as s:
            s.add(m.PredictionOrder(portfolio_id=1, order_id="o1", exchange="polymarket",
                                    market_id="m", token_id="t", side="BUY",
                                    order_type="MARKET", size=1.0, status="FILLED"))
            s.commit()


def test_init_db_seed_satisfies_fk(monkeypatch):
    """The production boot path: init_db() seeds the default portfolio, so a subsequent
    order insert satisfies the FK."""
    from app.db import database

    eng = _fk_engine()
    monkeypatch.setattr(database, "engine", eng)
    database.init_db()  # creates tables (idempotent) + seeds portfolio id=1

    with Session(eng) as s:
        s.add(m.PredictionOrder(portfolio_id=1, order_id="o1", exchange="polymarket",
                                market_id="m", token_id="t", side="BUY",
                                order_type="MARKET", size=1.0, status="FILLED"))
        s.commit()  # must NOT raise — parent row exists
    with Session(eng) as s:
        assert s.get(m.PredictionPortfolio, 1) is not None
        assert len(list(s.exec(select(m.PredictionOrder)).all())) == 1


def test_persist_order_self_sufficient_without_preseeded_portfolio(monkeypatch):
    """THE regression: orchestrator._persist_order (the LIVE writer) must persist the order
    AND the position under FK enforcement even with NO pre-seeded portfolio row, because it
    ensures the parent in its own transaction. Reverting that guard makes this fail loud."""
    from app.db import database

    eng = _fk_engine()
    monkeypatch.setattr(database, "engine", eng)
    # Deliberately do NOT call init_db()'s seed — prove the write path stands on its own.

    result = _make_result()
    orch = PredictionMarketOrchestrator(executor=_held_executor(result))
    orch._persist_order(result, _make_opp())  # must not raise, must not swallow a real error

    with Session(eng) as s:
        orders = list(s.exec(select(m.PredictionOrder)).all())
        positions = list(s.exec(select(m.PredictionPosition)).all())
        assert len(orders) == 1, "the live order write must have persisted"
        assert orders[0].portfolio_id == 1
        assert len(positions) == 1, "the live position write must have persisted"
        assert positions[0].category == "Sports"  # the derived category flows to the row
        assert s.get(m.PredictionPortfolio, 1) is not None  # parent created in-transaction
