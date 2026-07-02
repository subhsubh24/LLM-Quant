"""Regression: order/position persistence must satisfy the portfolio FK.

SQLite doesn't enforce foreign keys by default, so a missing parent portfolio row was
silently tolerated in dev — but Neon Postgres enforces them, so inserts raised
ForeignKeyViolation and the durable forward paper record never persisted (caught by the
live-validation run on real Neon). This reproduces FK enforcement locally (SQLite +
PRAGMA foreign_keys=ON) and proves _ensure_default_portfolio fixes it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

# Import via `app.*` (conftest puts backend/ on sys.path) — the convention the rest of the
# prediction-market gate tests use. Importing the table models via a SECOND path
# (backend.app.*) double-registers them on the shared SQLModel.metadata -> "Table already
# defined" in the full suite. Match the convention to stay collision-free.
from app.prediction_markets import models as m
from app.prediction_markets.persistence import _ensure_default_portfolio, DEFAULT_PORTFOLIO_ID


def _fk_engine():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_con, _rec):  # make SQLite enforce FKs like Postgres
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    return eng


def _minimal_order():
    return m.PredictionOrder(
        portfolio_id=DEFAULT_PORTFOLIO_ID, order_id="o1", exchange="polymarket",
        market_id="mkt1", token_id="tok1", side="BUY", order_type="MARKET", size=1.0,
    )


def test_order_insert_violates_fk_without_portfolio():
    """Baseline: with FKs enforced and no portfolio row, the order insert MUST fail
    (this is what silently broke on Neon)."""
    from sqlalchemy.exc import IntegrityError
    with Session(_fk_engine()) as s:
        s.add(_minimal_order())
        with pytest.raises(IntegrityError):
            s.flush()


def test_ensure_default_portfolio_lets_order_persist():
    """With the fix, the parent portfolio exists and the order persists."""
    with Session(_fk_engine()) as s:
        _ensure_default_portfolio(s)
        s.add(_minimal_order())
        s.flush()  # must NOT raise
        assert s.get(m.PredictionPortfolio, DEFAULT_PORTFOLIO_ID) is not None


def test_ensure_default_portfolio_is_idempotent():
    with Session(_fk_engine()) as s:
        _ensure_default_portfolio(s)
        _ensure_default_portfolio(s)  # second call must not duplicate / raise
        from sqlmodel import select
        n = len(list(s.exec(select(m.PredictionPortfolio)).all()))
        assert n == 1
