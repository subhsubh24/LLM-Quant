"""FACTORY_STANDARD §32 — a single un-rehydratable position row must NOT abort the
WHOLE rehydration.

``persistence.load_positions_into_executor`` runs once at ``get_executor()`` construction
(ROADMAP D8) to resume OPEN positions across the fresh-process-per-run paper cycle. Each row
is a per-row side-effect. Before the guard, an uncaught ``Exchange(db_pos.exchange)``
ValueError on ONE malformed/legacy row (an ``exchange`` string that is no longer a valid
``Exchange`` enum member — a schema/enum change, a manual edit, or a venue added to the DB
before its enum) crashed the loop inside the session, so EVERY open position stayed orphaned
→ ``check_resolutions`` (which reads in-memory ``executor.positions``) never settled them →
realized losses never booked → the loss caps / kill switch never saw them. The core action
(rehydrating the good positions) must survive a bad row.

These tests are PROVEN to fail on the pre-guard code (the whole call raises).
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, create_engine

from app.prediction_markets import models as m
from app.prediction_markets import persistence
from app.prediction_markets.execution import PredictionMarketExecutor


@pytest.fixture
def db(monkeypatch):
    """In-memory SQLite wired as the engine ``get_session`` uses (SingletonThreadPool → one
    shared connection so writes persist across the multiple ``get_session()`` calls)."""
    from app.db import database
    from app.prediction_markets.executor_state_store import PredictionExecutorStateRow

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    for tbl in (m.PredictionPortfolio, m.PredictionPosition, m.PredictionOrder, PredictionExecutorStateRow):
        tbl.__table__.create(eng, checkfirst=True)
    with Session(eng) as s:
        s.add(m.PredictionPortfolio(id=persistence.DEFAULT_PORTFOLIO_ID, name="default", exchange="all"))
        s.commit()
    monkeypatch.setattr(database, "engine", eng)
    return eng


def _insert(eng, token_id, exchange, *, market_id="mkt", is_resolved=False):
    with Session(eng) as s:
        s.add(
            m.PredictionPosition(
                portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
                exchange=exchange,
                market_id=market_id,
                token_id=token_id,
                side="long",
                size=10.0,
                avg_entry_price=0.4,
                current_price=0.4,
                market_value=4.0,
                is_resolved=is_resolved,
                strategy="test_strat",
            )
        )
        s.commit()


def test_one_bad_exchange_row_does_not_abort_rehydration(db):
    # A valid open row + a legacy row whose exchange is no longer a valid Exchange enum
    # member. The bad row must be skipped; the good row must still rehydrate. (Pre-guard,
    # Exchange("kalshi") raises and the whole call crashes → the good row is lost too.)
    _insert(db, "GOOD_TOK", "polymarket")
    _insert(db, "BAD_TOK", "kalshi")  # not a valid Exchange member (enum has only 'polymarket')

    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)  # must NOT raise

    assert "GOOD_TOK" in ex.positions          # the core action survived the bad row
    assert "BAD_TOK" not in ex.positions        # the un-rehydratable row was skipped, not fatal


def test_all_good_rows_still_rehydrate_normally(db):
    # Control: with no malformed rows every open position rehydrates (the guard is inert on
    # clean data — no false skips).
    _insert(db, "T1", "polymarket", market_id="m1")
    _insert(db, "T2", "polymarket", market_id="m2")
    _insert(db, "CLOSED", "polymarket", market_id="m3", is_resolved=True)

    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)

    assert set(ex.positions) == {"T1", "T2"}    # both OPEN rows; the resolved one excluded


def test_bad_row_does_not_block_a_later_good_row(db):
    # Ordering independence: even when the bad row is processed FIRST (updated_at desc puts
    # the most-recent first), the subsequently-processed good row still loads.
    import time

    _insert(db, "BAD_TOK", "kraken")   # invalid enum, inserted first
    time.sleep(0.01)
    _insert(db, "GOOD_TOK", "polymarket")  # newer updated_at → processed first anyway

    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    assert "GOOD_TOK" in ex.positions
    assert "BAD_TOK" not in ex.positions
