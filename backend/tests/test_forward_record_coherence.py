"""ROADMAP D8 — forward-record coherence across the fresh-process-per-run paper cycle.

The scheduled paper cycle (OA-17 live-validation) runs as a FRESH PROCESS each run. Before
D8, ``executor.positions`` started empty every run and ``persistence.load_positions_into_executor``
was NEVER called (zero call sites), so:
  - positions opened in a prior run were ORPHANED in the DB and ``check_resolutions`` (which
    reads in-memory ``executor.positions`` and returns early on an empty dict) never settled
    them → realized PnL never booked → the forward record could not progress; and
  - the scan→execute loop had no "skip a market already held" dedup, so each run re-opened /
    scaled the same market → double-counting.

These tests prove the coupled fix end-to-end:
  (a) get_positions(open_only=True) / load_positions_into_executor rehydrate OPEN positions
      only (a resolved row must not be resurrected);
  (b) check_resolutions settles a REHYDRATED position and books its realized PnL + marks the
      DB row resolved;
  (c) get_executor() wires the rehydration on construction (the real production seam);
  (d) the scan loop SKIPS an opportunity whose outcome token is already held (no scale-in /
      double-count), and does so AFTER the data-quality/risk/Kelly gates (proving it reached
      the dedup, not an upstream reject).

Import via ``app.*`` (conftest puts backend/ on sys.path) — importing the table models via a
SECOND, non-canonical path (``backend.app.*``) would double-register them on the shared
SQLModel.metadata; that is now avoided suite-wide since every test standardized on ``app.*``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, create_engine, select

from app.prediction_markets import models as m
from app.prediction_markets import persistence
from app.prediction_markets.execution import PredictionMarketExecutor
from app.prediction_markets.polymarket_client import Market, Outcome, ScanResult
from app.prediction_markets.orchestrator import (
    KellyConfig,
    MarkToMarketEngine,
    PredictionMarketOrchestrator,
)
from app.prediction_markets.risk_manager import RiskManager, RiskConfig


@pytest.fixture
def db(monkeypatch):
    """An in-memory SQLite DB wired as the engine `get_session` uses.

    A default `sqlite://` engine uses SingletonThreadPool → one shared connection per thread,
    so data persists across the multiple `get_session()` calls these tests make (same pattern
    as test_executor_state_persistence).

    We create ONLY the specific tables these tests touch, via ``__table__.create(checkfirst=
    True)`` — deliberately NOT a blanket ``SQLModel.metadata.create_all``. Historically the
    FULL suite imported the models via TWO paths (``app.*`` and ``backend.app.*``), so the
    shared metadata carried dual-registered tables and a blanket create_all emitted a
    duplicate ``CREATE INDEX`` and errored. Creating each table object individually sidesteps
    that; the dual-import root cause is now resolved by standardizing every test on ``app.*``.
    """
    from app.db import database
    from app.prediction_markets.executor_state_store import PredictionExecutorStateRow

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    for tbl in (
        m.PredictionPortfolio,
        m.PredictionPosition,
        m.PredictionOrder,
        PredictionExecutorStateRow,
    ):
        tbl.__table__.create(eng, checkfirst=True)
    with Session(eng) as s:
        s.add(m.PredictionPortfolio(id=persistence.DEFAULT_PORTFOLIO_ID, name="default", exchange="all"))
        s.commit()
    monkeypatch.setattr(database, "engine", eng)
    return eng


def _insert_position(eng, token_id, market_id, is_resolved, avg=0.4, size=10.0):
    with Session(eng) as s:
        s.add(
            m.PredictionPosition(
                portfolio_id=persistence.DEFAULT_PORTFOLIO_ID,
                exchange="polymarket",
                market_id=market_id,
                token_id=token_id,
                side="long",
                size=size,
                avg_entry_price=avg,
                current_price=avg,
                market_value=size * avg,
                is_resolved=is_resolved,
                strategy="test_strat",
            )
        )
        s.commit()


# ---------------------------------------------------------------------------
# (a) rehydrate OPEN positions only
# ---------------------------------------------------------------------------

def test_get_positions_open_only_excludes_resolved(db):
    _insert_position(db, "OPEN_TOK", "mktA", is_resolved=False)
    _insert_position(db, "CLOSED_TOK", "mktB", is_resolved=True)

    # get_session() detaches rows on commit, so assert on COUNTS (touching no lazy attr).
    # The exact-token correctness of the open filter is proven via the rehydrate path in
    # test_rehydrate_loads_open_not_closed.
    assert len(persistence.get_positions(open_only=True)) == 1
    # open_only=False still returns everything (history view / backwards-compat).
    assert len(persistence.get_positions(open_only=False)) == 2


def test_rehydrate_loads_open_not_closed(db):
    _insert_position(db, "OPEN_TOK", "mktA", is_resolved=False)
    _insert_position(db, "CLOSED_TOK", "mktB", is_resolved=True)

    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)

    assert "OPEN_TOK" in ex.positions
    assert "CLOSED_TOK" not in ex.positions
    assert len(ex.positions) == 1


def test_rehydrate_is_idempotent_and_does_not_clobber(db):
    _insert_position(db, "OPEN_TOK", "mktA", is_resolved=False, size=10.0)
    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    # Simulate a fresher in-process position for the same token.
    ex.positions["OPEN_TOK"].size = 999.0
    persistence.load_positions_into_executor(ex)  # must NOT clobber the in-memory one
    assert ex.positions["OPEN_TOK"].size == 999.0
    assert len(ex.positions) == 1


# ---------------------------------------------------------------------------
# (b) check_resolutions settles a REHYDRATED position
# ---------------------------------------------------------------------------

def test_check_resolutions_settles_rehydrated_position(db, monkeypatch):
    # A prior run opened this (won) position; a fresh run must rehydrate + settle it.
    _insert_position(db, "TOKW", "42", is_resolved=False, avg=0.4, size=10.0)

    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    assert "TOKW" in ex.positions, "precondition: the open position rehydrated"

    from app.prediction_markets import polymarket_client as pmc

    won = Market(
        id="42", condition_id="c", question="Q?", slug="will-x", description="",
        category="", end_date=None,
        outcomes=[Outcome(token_id="TOKW", label="Yes", price=1.0, midpoint=1.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_market_by_id(self, market_id):
            assert market_id == "42"
            return won

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _FakeClient
    try:
        MarkToMarketEngine(ex).check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # Settled + removed from memory; gross realized PnL = (1.0 - 0.4) * 10 = +6.0, NET of
    # the entry fee the loss-cap counters now subtract (2% of the $4.00 cost basis =
    # $0.08): +5.92. (The counter tracks true net cash PnL; a win is reduced by its fee.)
    assert "TOKW" not in ex.positions
    assert ex._realized_pnl_total == pytest.approx(5.92)

    # DB row marked resolved so a subsequent run does NOT re-rehydrate/re-settle it.
    with Session(db) as s:
        row = s.exec(
            select(m.PredictionPosition).where(m.PredictionPosition.token_id == "TOKW")
        ).first()
        assert row.is_resolved is True
        assert row.resolution_value == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# (c) get_executor() wires rehydration end-to-end (the production seam)
# ---------------------------------------------------------------------------

def test_get_executor_rehydrates_open_positions(db, monkeypatch):
    _insert_position(db, "GTOK", "mktG", is_resolved=False)

    import app.prediction_markets.execution as ex_mod

    monkeypatch.setattr(ex_mod, "_executor", None)  # reset the global singleton
    try:
        ex = ex_mod.get_executor(dry_run=True)
        assert "GTOK" in ex.positions, "get_executor must rehydrate open positions (D8)"
    finally:
        monkeypatch.setattr(ex_mod, "_executor", None)


# ---------------------------------------------------------------------------
# (d) scan loop skips an already-held outcome token (no scale-in / double-count)
# ---------------------------------------------------------------------------

def _make_market(mid: str) -> Market:
    return Market(
        id=mid, condition_id=mid, question="Will BTC exceed $100k?", slug=mid,
        description="", category="Crypto",
        end_date=datetime.now(timezone.utc) + timedelta(hours=48),
        outcomes=[
            Outcome(token_id=f"{mid}_yes", label="Yes", price=0.60, midpoint=0.60, volume=100_000),
            Outcome(token_id=f"{mid}_no", label="No", price=0.40, midpoint=0.40, volume=100_000),
        ],
        total_volume=100_000, liquidity=50_000, active=True, closed=False, resolved=False,
        resolution_source="polymarket", tags=[], neg_risk=False,
    )


def _permissive_risk():
    return RiskManager(RiskConfig(
        daily_loss_limit_usd=100_000.0,
        max_portfolio_exposure_usd=100_000.0,
        max_single_position_usd=100_000.0,
        max_category_exposure_usd=100_000.0,
        max_strategy_exposure_usd=100_000.0,
        max_total_positions=1000,
    ))


def test_scan_skips_already_held_outcome(db):
    market = _make_market("held1")
    held_token = "held1_yes"
    opp = ScanResult(
        market=market, strategy="TestStrat", outcome_idx=0, side="BUY",
        entry_price=0.60, expected_value=0.72, edge=0.12, confidence=0.9,
        reason="signal",
    )

    class _FakeScanner:
        strategies: list = []

        def scan(self, market_limit=200):
            return [opp]

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=10_000.0)
    # Pre-seed the held outcome (as if rehydrated from a prior run).
    persistence.load_positions_into_executor(ex)  # no-op (empty), proves the seam is benign
    from app.prediction_markets.execution import Position, Exchange
    ex.positions[held_token] = Position(
        exchange=Exchange.POLYMARKET, market_id="held1", token_id=held_token,
        market_question="Q", outcome_label="Yes", side="long", size=5.0,
        avg_entry_price=0.55, current_price=0.60, unrealized_pnl=0.0, realized_pnl=0.0,
    )

    orch = PredictionMarketOrchestrator(
        scanner=_FakeScanner(), executor=ex, risk_manager=_permissive_risk(),
        kelly_config=KellyConfig(max_bet_usd=20.0),
    )
    summary = asyncio.get_event_loop().run_until_complete(orch.scan_and_execute())

    # No new execution: the held outcome is skipped by the dedup (one position per outcome).
    assert summary["executed"] == 0
    assert orch.total_executions == 0
    assert any("already holding" in s["reason"] for s in summary["skip_reasons"]), summary["skip_reasons"]
    # No scale-in: the position size is unchanged and no second position was booked.
    assert ex.positions[held_token].size == 5.0
    assert len(ex.positions) == 1


def test_scan_executes_when_not_held(db):
    """Control: the SAME opp DOES execute when the outcome is not already held — proving the
    skip in the prior test is the dedup, not a blanket upstream reject."""
    market = _make_market("fresh1")
    opp = ScanResult(
        market=market, strategy="TestStrat", outcome_idx=0, side="BUY",
        entry_price=0.60, expected_value=0.72, edge=0.12, confidence=0.9,
        reason="signal",
    )

    class _FakeScanner:
        strategies: list = []

        def scan(self, market_limit=200):
            return [opp]

    ex = PredictionMarketExecutor(dry_run=True, max_position_usd=50.0, max_portfolio_usd=10_000.0)
    orch = PredictionMarketOrchestrator(
        scanner=_FakeScanner(), executor=ex, risk_manager=_permissive_risk(),
        kelly_config=KellyConfig(max_bet_usd=20.0),
    )
    summary = asyncio.get_event_loop().run_until_complete(orch.scan_and_execute())

    assert summary["executed"] == 1
    assert "fresh1_yes" in ex.positions


# ---------------------------------------------------------------------------
# Settlement is counted into the loss caps AT MOST ONCE across a restart, even if
# the DB persist FAILS. Before this fix, check_resolutions counted the PnL + removed
# the position BEFORE persisting; a swallowed persist failure then left the row
# is_resolved=False, so D8's rehydration re-settled it on the next process and
# DOUBLE-COUNTED the realized PnL into the durable loss-cap/kill-switch counters.
# ---------------------------------------------------------------------------

def _resolved_loser_market(market_id: str, token_id: str) -> Market:
    """A resolved market where the held ``token_id`` LOST (settles at 0.0)."""
    return Market(
        id=market_id, condition_id="c", question="Q?", slug="will-x", description="",
        category="", end_date=None,
        outcomes=[Outcome(token_id=token_id, label="Yes", price=0.0, midpoint=0.0, volume=0.0)],
        total_volume=0.0, liquidity=0.0, active=False, closed=True, resolved=True,
    )


def _fake_client_returning(market: Market):
    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_market_by_id(self, market_id):
            return market if market_id == market.id else None

    return _FakeClient


def test_persist_failure_does_not_count_or_remove(db, monkeypatch):
    """A FAILED resolution persist must NOT count PnL or drop the position (proven-fail
    on pre-fix code, which counted+removed regardless of persist success)."""
    _insert_position(db, "TOKL", "77", is_resolved=False, avg=0.9, size=10.0)  # a loser
    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    assert "TOKL" in ex.positions

    from app.prediction_markets import polymarket_client as pmc
    engine = MarkToMarketEngine(ex)
    # Force the persist to fail (simulate a DB write error).
    monkeypatch.setattr(engine, "_persist_resolution", lambda *a, **k: False)

    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _fake_client_returning(_resolved_loser_market("77", "TOKL"))
    try:
        engine.check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # No PnL counted, position still OPEN (left to retry) — so a restart cannot double-count.
    assert ex._realized_pnl_total == 0.0
    assert "TOKL" in ex.positions
    with Session(db) as s:
        row = s.exec(select(m.PredictionPosition).where(m.PredictionPosition.token_id == "TOKL")).first()
        assert row.is_resolved is False


def test_settlement_counted_exactly_once_across_restart(db, monkeypatch):
    """Persist fails on run 1 (nothing counted) → the position rehydrates on run 2 and
    settles once. The loss hits the durable counters EXACTLY ONCE, never twice."""
    _insert_position(db, "TOKL", "88", is_resolved=False, avg=0.9, size=10.0)
    from app.prediction_markets import polymarket_client as pmc
    orig = pmc.PolymarketClient
    pmc.PolymarketClient = _fake_client_returning(_resolved_loser_market("88", "TOKL"))
    try:
        # --- run 1: persist FAILS -> nothing counted, row stays open ---
        ex1 = PredictionMarketExecutor(dry_run=True)
        persistence.load_positions_into_executor(ex1)
        eng1 = MarkToMarketEngine(ex1)
        monkeypatch.setattr(eng1, "_persist_resolution", lambda *a, **k: False)
        eng1.check_resolutions()
        assert ex1._realized_pnl_total == 0.0

        # --- run 2 (fresh process): rehydrate the still-open row, persist SUCCEEDS ---
        ex2 = PredictionMarketExecutor(dry_run=True)
        persistence.load_positions_into_executor(ex2)
        assert "TOKL" in ex2.positions, "the un-persisted position rehydrated for retry"
        MarkToMarketEngine(ex2).check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    # Counted ONCE: gross loss (0.0-0.9)*10 = -9.0, net of the 2%-notional entry fee on the
    # $9.00 cost basis (-0.18) => -9.18. Not -18.36 (which a double-count would produce).
    assert ex2._realized_pnl_total == pytest.approx(-9.18)
    assert "TOKL" not in ex2.positions
    with Session(db) as s:
        row = s.exec(select(m.PredictionPosition).where(m.PredictionPosition.token_id == "TOKL")).first()
        assert row.is_resolved is True


def test_persist_resolution_returns_false_on_db_error(db, monkeypatch):
    """_persist_resolution reports failure (False) when the DB write raises, and success
    (True) on a clean write — the contract the caller relies on to avoid double-counting."""
    _insert_position(db, "TOKX", "99", is_resolved=False, avg=0.4, size=10.0)
    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    engine = MarkToMarketEngine(ex)
    pos = ex.positions["TOKX"]

    # Clean write -> True + the row is marked resolved.
    assert engine._persist_resolution(pos, realized_pnl=-1.0, settlement_price=0.0) is True
    with Session(db) as s:
        row = s.exec(select(m.PredictionPosition).where(m.PredictionPosition.token_id == "TOKX")).first()
        assert row.is_resolved is True and row.realized_pnl == pytest.approx(-1.0)

    # DB error -> False (never raises).
    from app.db import database

    def _boom():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(database, "get_session", _boom)
    assert engine._persist_resolution(pos, realized_pnl=-1.0, settlement_price=0.0) is False


def test_has_table_probe_failure_defers_not_counts(db, monkeypatch):
    """A DB outage during the has_table PROBE (the first DB touch) must DEFER (return
    False), not be mistaken for 'no table → safe to count'. A rehydratable row EXISTS but
    is unreachable; counting now would double-count on the next process. FAILS on the
    swallow-to-False variant (which returned True)."""
    _insert_position(db, "TOKP", "66", is_resolved=False, avg=0.9, size=10.0)
    ex = PredictionMarketExecutor(dry_run=True)
    persistence.load_positions_into_executor(ex)
    engine = MarkToMarketEngine(ex)
    pos = ex.positions["TOKP"]

    import sqlalchemy

    def _boom_inspect(*a, **k):
        raise RuntimeError("db unreachable during inspect")

    monkeypatch.setattr(sqlalchemy, "inspect", _boom_inspect)
    assert engine._persist_resolution(pos, realized_pnl=-9.18, settlement_price=0.0) is False


def test_outage_during_probe_does_not_double_count_across_restart(db, monkeypatch):
    """End-to-end (the adversarial live-safety auditor's exact reproduction): a DB outage
    during the has_table probe on run 1 must count NOTHING (the row stays open); run 2
    (healthy) settles it ONCE. The durable loss counter is -9.18, not -18.36."""
    _insert_position(db, "TOKO", "67", is_resolved=False, avg=0.9, size=10.0)
    from app.prediction_markets import polymarket_client as pmc
    import sqlalchemy

    orig = pmc.PolymarketClient
    real_inspect = sqlalchemy.inspect
    pmc.PolymarketClient = _fake_client_returning(_resolved_loser_market("67", "TOKO"))
    try:
        # run 1: outage during the has_table probe → _persist_resolution returns False →
        # nothing counted, position left OPEN.
        ex1 = PredictionMarketExecutor(dry_run=True)
        persistence.load_positions_into_executor(ex1)
        monkeypatch.setattr(
            sqlalchemy, "inspect",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db unreachable during inspect")),
        )
        MarkToMarketEngine(ex1).check_resolutions()
        assert ex1._realized_pnl_total == 0.0
        monkeypatch.setattr(sqlalchemy, "inspect", real_inspect)  # DB heals

        # run 2 (fresh process): the still-open row rehydrates + settles ONCE.
        ex2 = PredictionMarketExecutor(dry_run=True)
        persistence.load_positions_into_executor(ex2)
        assert "TOKO" in ex2.positions
        MarkToMarketEngine(ex2).check_resolutions()
    finally:
        pmc.PolymarketClient = orig

    assert ex2._realized_pnl_total == pytest.approx(-9.18)  # counted ONCE, not -18.36
    assert "TOKO" not in ex2.positions
