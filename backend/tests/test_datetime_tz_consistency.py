"""Timezone-awareness consistency across the persistence / rehydration path.

The whole prediction-markets trading path standardized on tz-AWARE
``datetime.now(timezone.utc)`` (52 sites) — EXCEPT the SQLModel table defaults in
``models.py`` and the write-side calls in ``persistence.py`` / ``orchestrator.py``,
which used naive ``datetime.utcnow`` (15 sites). SQLModel maps a plain ``datetime``
column to a timezone-NAIVE SQL column, so a value read back from the DB is naive
regardless of how it was written. Rehydrating such a naive timestamp into a live
``Position`` (``load_positions_into_executor``, ROADMAP D8) left the executor holding a
MIX of naive + aware datetimes — a latent
``TypeError: can't compare offset-naive and offset-aware datetimes`` waiting for the
first age/staleness subtraction to touch a *rehydrated* (not fresh) position, a
heisenbug that fires only after a restart.

These tests lock the fix at the root:
  1. Fresh model defaults are tz-aware.
  2. ``_as_utc`` normalizes a naive value to UTC and passes an aware value through.
  3. FUNCTIONAL: a rehydrated Position carries tz-aware ``opened_at``/``updated_at``
     even when the DB row's timestamps are naive (the money-adjacent footgun).
  4. GUARD: naive ``datetime.utcnow`` is not reintroduced into the persistence path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, create_engine

from app.prediction_markets import models as m
from app.prediction_markets import persistence
from app.prediction_markets.persistence import _as_utc
from app.prediction_markets.execution import PredictionMarketExecutor


def test_model_default_timestamps_are_tz_aware():
    """Fresh rows default to tz-aware UTC (not naive utcnow)."""
    pos = m.PredictionPosition(
        portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
        exchange="polymarket",
        market_id="mkt",
        token_id="TOK",
    )
    assert pos.opened_at.tzinfo is not None, "opened_at must be tz-aware"
    assert pos.updated_at.tzinfo is not None, "updated_at must be tz-aware"
    assert pos.opened_at.utcoffset() == timezone.utc.utcoffset(None)

    port = m.PredictionPortfolio(name="x", exchange="all")
    assert port.created_at.tzinfo is not None
    assert port.updated_at.tzinfo is not None

    order = m.PredictionOrder(
        portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
        order_id="o1", exchange="polymarket", market_id="mkt", token_id="TOK",
        side="BUY", order_type="MARKET", size=1.0,
    )
    assert order.created_at.tzinfo is not None
    assert order.updated_at.tzinfo is not None


def test_as_utc_normalizes_naive_and_passes_aware_through():
    naive = datetime(2026, 7, 17, 12, 0, 0)
    out = _as_utc(naive)
    assert out is not None and out.tzinfo is not None
    assert out.replace(tzinfo=None) == naive  # same wall-clock instant, now stamped UTC

    aware = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
    assert _as_utc(aware) is aware  # already aware -> unchanged (identity)

    assert _as_utc(None) is None  # an unset column stays None


@pytest.fixture
def db(monkeypatch):
    """In-memory SQLite wired as the engine ``get_session`` uses (one shared connection)."""
    from app.db import database

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    for tbl in (m.PredictionPortfolio, m.PredictionPosition):
        tbl.__table__.create(eng, checkfirst=True)
    with Session(eng) as s:
        s.add(m.PredictionPortfolio(id=persistence.DEFAULT_PORTFOLIO_ID, name="default", exchange="all"))
        s.commit()
    monkeypatch.setattr(database, "engine", eng)
    return eng


def test_rehydrated_position_timestamps_are_tz_aware(db):
    """A DB row with NAIVE timestamps must rehydrate into a tz-aware Position.

    Simulates the exact production read-back: SQLModel returns naive datetimes even
    for aware writes, so we insert naive timestamps explicitly. Pre-fix, the executor
    Position carried these naive values while fresh positions were aware — the mixed-tz
    footgun. Post-fix, ``load_positions_into_executor`` normalizes them via ``_as_utc``.
    """
    naive_open = datetime(2026, 7, 10, 8, 0, 0)  # tzinfo is None
    naive_upd = datetime(2026, 7, 16, 9, 30, 0)
    with Session(db) as s:
        s.add(
            m.PredictionPosition(
                portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
                exchange="polymarket",
                market_id="mkt",
                token_id="REHYDRATE_TOK",
                side="long",
                size=10.0,
                avg_entry_price=0.4,
                current_price=0.4,
                market_value=4.0,
                is_resolved=False,
                strategy="test_strat",
                opened_at=naive_open,
                updated_at=naive_upd,
            )
        )
        s.commit()

    executor = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(executor)

    assert "REHYDRATE_TOK" in executor.positions
    pos = executor.positions["REHYDRATE_TOK"]
    assert pos.opened_at.tzinfo is not None, "rehydrated opened_at must be tz-aware"
    assert pos.updated_at.tzinfo is not None, "rehydrated updated_at must be tz-aware"
    # And it must be a NO-OP on the wall-clock instant (UTC by construction).
    assert pos.opened_at.replace(tzinfo=None) == naive_open
    assert pos.updated_at.replace(tzinfo=None) == naive_upd

    # The footgun itself: subtracting a rehydrated timestamp from a fresh aware "now"
    # must NOT raise (pre-fix this threw TypeError for rehydrated-only positions).
    delta = datetime.now(timezone.utc) - pos.opened_at
    assert delta.total_seconds() > 0


def test_no_naive_utcnow_in_persistence_path():
    """Guard: the naive ``datetime.utcnow`` must not creep back into the persistence path."""
    import inspect
    from app.prediction_markets import persistence as pmod
    from app.prediction_markets import models as mmod

    for mod in (pmod, mmod):
        src = inspect.getsource(mod)
        assert "datetime.utcnow" not in src, (
            f"{mod.__name__} reintroduced naive datetime.utcnow — use "
            f"datetime.now(timezone.utc) for tz-awareness consistency"
        )
