"""
Tests for the durable prediction-market audit log (ROADMAP G3 / OA-10).

Deterministic, in-memory SQLite, no network. Verifies that decisions and
would-be orders are persisted, that an order row reflects the REAL OrderResult
(filled vs rejected vs gated — never a fabricated success), and that all writes
are best-effort (a DB failure never raises into the caller).

Also covers FORWARD DEPTH CAPTURE AT DECISION TIME (ROADMAP E11): the orchestrator
records the real order book alongside each would-be order, because depth at a PAST
decision instant is unobtainable from Polymarket and capture-going-forward is the only
route to a MEASURED capacity curve. Those tests pin the four properties that make the
capture trustworthy — it round-trips, it is bounded, it never fabricates a quote, and
it can never change a trading decision.
"""

import asyncio
import time
import types
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import create_engine

from app.prediction_markets import orchestrator as orch_mod
from app.prediction_markets.audit_log import (
    AuditLogger,
    BOOK_LADDER_LEVELS,
    PredictionAuditLog,
    init_db,
    snapshot_order_book,
)
from app.prediction_markets.execution import (
    Exchange,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from app.prediction_markets.orchestrator import PredictionMarketOrchestrator
from app.prediction_markets.polymarket_client import (
    Market,
    OrderBook,
    Outcome,
    ScanResult,
)


@pytest.fixture
def engine():
    """Fresh in-memory SQLite engine with the audit table created."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    init_db(eng)
    return eng


@pytest.fixture
def auditor(engine):
    return AuditLogger(engine=engine)


def _make_result(status, *, error=None, filled_size=0.0, filled_price=0.0,
                 order_id="oid-1", price=0.42):
    return OrderResult(
        order_id=order_id,
        exchange=Exchange.POLYMARKET,
        market_id="mkt-123",
        token_id="tok-456",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=10.0,
        price=price,
        status=status,
        filled_size=filled_size,
        filled_price=filled_price,
        error=error,
    )


# ============================================================
# record_decision
# ============================================================

def test_record_decision_persists_row(auditor):
    auditor.record_decision(
        "risk_reject",
        strategy="momentum",
        market_id="mkt-9",
        market_question="Will it rain?",
        side="BUY",
        edge=0.05,
        confidence=0.7,
        reason="exposure limit",
    )

    rows = auditor.recent()
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PredictionAuditLog)
    assert row.event_type == "risk_reject"
    assert row.strategy == "momentum"
    assert row.market_id == "mkt-9"
    assert row.market_question == "Will it rain?"
    assert row.side == "BUY"
    assert row.edge == 0.05
    assert row.confidence == 0.7
    assert row.reason == "exposure limit"
    assert row.ts is not None


def test_recent_newest_first(auditor):
    auditor.record_decision("dq_reject", reason="first")
    auditor.record_decision("kelly_skip", reason="second")
    rows = auditor.recent()
    assert [r.reason for r in rows] == ["second", "first"]


# ============================================================
# record_would_be_order
# ============================================================

def test_would_be_order_filled(auditor):
    result = _make_result(
        OrderStatus.FILLED,
        filled_size=10.0,
        filled_price=0.43,
        order_id="filled-1",
    )
    auditor.record_would_be_order(
        result, strategy="arb", market_question="Q?", edge=0.1, confidence=0.9
    )

    row = auditor.recent()[0]
    assert row.event_type == "order_filled"
    assert row.order_id == "filled-1"
    assert row.price == 0.43  # real fill price
    assert row.side == "BUY"
    assert row.market_id == "mkt-123"
    assert row.strategy == "arb"


def test_would_be_order_fill_price_zero_not_confused_with_limit(auditor):
    """A genuine fill AT 0.0 must log price 0.0 — not silently fall back to the limit
    price. (OrderResult.filled_price defaults to 0.0, so a truthiness fallback would be a
    bug.) Also confirms is_dry_run/live_enabled are persisted for mode context."""
    result = _make_result(
        OrderStatus.FILLED, filled_size=10.0, filled_price=0.0, order_id="zero-1", price=0.42
    )
    auditor.record_would_be_order(result, is_dry_run=True, live_enabled=False)
    row = auditor.recent()[0]
    assert row.event_type == "order_filled"
    assert row.price == 0.0            # the REAL fill price, not the 0.42 limit
    assert row.is_dry_run is True
    assert row.live_enabled is False


def test_would_be_order_gated_reflects_real_error(auditor):
    """A gated order must be logged AS gated with its real error, not a fake success."""
    err = "LIVE_TRADING_ENABLED is false — real orders are gated off (owner-only)."
    result = _make_result(OrderStatus.REJECTED, error=err, order_id="gated-1")
    auditor.record_would_be_order(result, strategy="s")

    row = auditor.recent()[0]
    assert row.event_type == "order_gated"
    assert row.reason == err
    assert "LIVE_TRADING_ENABLED" in row.get_payload()["error"]
    assert row.get_payload()["status"] == "rejected"
    # Proves integrity: the gated order was NOT recorded as filled.
    assert row.event_type != "order_filled"


def test_would_be_order_rejected(auditor):
    result = _make_result(
        OrderStatus.REJECTED,
        error="risk: max exposure exceeded",
        order_id="rej-1",
    )
    auditor.record_would_be_order(result)

    row = auditor.recent()[0]
    assert row.event_type == "order_rejected"
    assert row.reason == "risk: max exposure exceeded"


# ============================================================
# Best-effort: writes never raise
# ============================================================

def test_record_decision_best_effort(monkeypatch, auditor):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    # Force every write to blow up.
    monkeypatch.setattr(auditor, "_session", boom)

    # Must return normally (no exception propagates to the caller).
    auditor.record_decision("dq_reject", reason="x")


def test_record_would_be_order_best_effort(monkeypatch, auditor):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(auditor, "_session", boom)

    result = _make_result(OrderStatus.FILLED, filled_size=1.0, filled_price=0.5)
    # The guarantee under test IS the absence of a raised exception — if the call below
    # returns, the best-effort contract held. (No row assertion: the write was forced to
    # fail; we are asserting the failure was swallowed, not persisted.)
    auditor.record_would_be_order(result)
    assert auditor.recent() == []  # nothing persisted, and crucially nothing raised


# ============================================================================
# ROADMAP E11 — forward depth capture at decision time
#
# Retrospective depth is UNOBTAINABLE from Polymarket: Gamma serves `liquidity: null`
# on resolved markets and CLOB /book 404s on a settled token (both verified live
# 2026-07-26). So no past corpus can ever be capacity-tested, and recording the book
# alongside each decision going forward is the ONLY route to a MEASURED capacity curve
# — and the only route to a corpus whose entry price is OBSERVED rather than estimated
# at the midpoint (today's records never pay a spread).
#
# The capture is OBSERVATION ONLY. Everything below exists to keep it that way.
# ============================================================================

def _book(
    *,
    token_id="tok-e11",
    best_bid=0.41,
    best_ask=0.43,
    n_levels=5,
    level_size=100.0,
    tick=0.01,
):
    """A realistic two-sided OrderBook, best-first on both sides (as the client returns).

    Built from the REAL ``OrderBook`` dataclass rather than a stub so the snapshot code is
    exercised against the exact shape ``PolymarketClient.get_order_book`` produces.
    """
    asks = [
        {"price": round(best_ask + i * tick, 6), "size": level_size}
        for i in range(n_levels)
    ]
    bids = [
        {"price": round(best_bid - i * tick, 6), "size": level_size}
        for i in range(n_levels)
    ]
    return OrderBook(
        token_id=token_id,
        bids=bids,
        asks=asks,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=best_ask - best_bid,
        tick_size=0.01,
        min_order_size=5.0,
    )


# ---------------------------------------------------------------------------
# Store side: the snapshot round-trips, stays bounded, and never invents a quote
# ---------------------------------------------------------------------------

def test_book_snapshot_round_trips_through_the_store(auditor):
    """A captured book must survive the write/read cycle with its REAL touch intact.

    FAILS ON PRE-CHANGE CODE: there is no ``book_json`` column and no ``get_book()``.
    """
    snap = snapshot_order_book(_book(best_bid=0.41, best_ask=0.43, n_levels=4))
    result = _make_result(OrderStatus.FILLED, filled_size=10.0, filled_price=0.43)
    auditor.record_would_be_order(result, strategy="e11", book=snap)

    row = auditor.recent()[0]
    stored = row.get_book()
    assert stored is not None, "the captured book did not round-trip"
    # The REAL touch — the numbers that make a spread cost measurable instead of assumed.
    assert stored["best_bid"] == 0.41
    assert stored["best_ask"] == 0.43
    assert stored["spread"] == pytest.approx(0.02)
    assert stored["token_id"] == "tok-e11"
    # The ladder itself, best-first, with real sizes.
    assert stored["ask_ladder"][0] == {"price": 0.43, "size": 100.0}
    assert [lvl["price"] for lvl in stored["ask_ladder"]] == sorted(
        lvl["price"] for lvl in stored["ask_ladder"]
    )
    # Executable-depth scalars, mirroring capacity_probe's row shape so a forward row and
    # a probe row can be read by the same capacity code.
    assert stored["depth_at_touch_contracts"] == 100.0
    assert stored["depth_within_2c_contracts"] == 300.0   # 0.43 + 0.44 + 0.45
    assert stored["total_ask_contracts"] == 400.0
    # The order row is still a faithful order row — capture did not displace anything.
    assert row.event_type == "order_filled"
    assert row.price == 0.43


def test_decision_row_round_trips_a_book(auditor):
    """The same capture works on a plain decision row, not just an order row."""
    snap = snapshot_order_book(_book(best_bid=0.30, best_ask=0.34))
    auditor.record_decision("risk_reject", market_id="m-1", reason="exposure", book=snap)
    stored = auditor.recent()[0].get_book()
    assert stored["best_bid"] == 0.30 and stored["best_ask"] == 0.34
    assert stored["spread"] == pytest.approx(0.04)


def test_ask_ladder_is_bounded(auditor):
    """The stored ladder must be BOUNDED, and the bound must match capacity_probe's.

    An unbounded book would bloat every audit row with penny-priced tail levels that no
    capacity analysis is allowed to count as depth; a ladder truncated at a DIFFERENT
    depth than the probe artifact's would make the two samples silently non-comparable.
    """
    # 40 is `scripts/capacity_probe.py`'s LADDER_LEVELS. Pinned literally (the probe is
    # not importable from the backend app) so a drift on either side fails loudly here.
    assert BOOK_LADDER_LEVELS == 40

    deep = _book(best_ask=0.10, n_levels=500, level_size=7.0, tick=0.001)
    snap = snapshot_order_book(deep)
    assert len(snap["ask_ladder"]) == BOOK_LADDER_LEVELS
    assert snap["ladder_levels_bound"] == BOOK_LADDER_LEVELS
    # The FULL ladder length is still reported, so a reader can tell this is a truncation
    # rather than the whole book...
    assert snap["n_ask_levels"] == 500
    # ...and the depth scalars are computed over the FULL ladder, so they do not quietly
    # depend on the truncation bound.
    assert snap["total_ask_contracts"] == pytest.approx(500 * 7.0)

    auditor.record_would_be_order(
        _make_result(OrderStatus.FILLED, filled_size=1.0, filled_price=0.1), book=snap
    )
    assert len(auditor.recent()[0].get_book()["ask_ladder"]) == BOOK_LADDER_LEVELS


@pytest.mark.parametrize(
    "bad_book, why",
    [
        (None, "no book at all (client returned None / venue 404)"),
        (_book(n_levels=0), "empty ask side"),
        (
            OrderBook(
                token_id="t", bids=[{"price": 0.4, "size": 1.0}], asks=[],
                best_bid=0.4, best_ask=0.5, spread=0.1, tick_size=0.01, min_order_size=5,
            ),
            "one-sided book (the shape get_order_book refuses to quote)",
        ),
        (
            OrderBook(
                token_id="t", bids=[{"price": 0.4, "size": 1.0}],
                asks=[{"price": "not-a-price", "size": None}],
                best_bid=0.4, best_ask=0.5, spread=0.1, tick_size=0.01, min_order_size=5,
            ),
            "malformed levels",
        ),
        (
            OrderBook(
                token_id="t", bids=[], asks=[{"price": 0.5, "size": 1.0}],
                best_bid=float("nan"), best_ask=0.5, spread=0.1,
                tick_size=0.01, min_order_size=5,
            ),
            "non-finite touch",
        ),
    ],
)
def test_no_fabricated_quote_is_ever_stored(auditor, bad_book, why):
    """Anything that is not a real two-sided book is recorded as NULL, never repaired.

    ``get_order_book`` already refuses a one-sided book rather than inventing
    ``best_bid=0.0``/``best_ask=1.0`` (a strategy reads that as a real 100%-wide market —
    the data analog of a fake fill). That refusal must survive all the way to the stored
    row: a fabricated quote here would poison the very capacity curve E11 exists to build,
    and a 0-depth row would understate the depth distribution while LOOKING conservative.
    """
    snap = snapshot_order_book(bad_book)
    assert snap is None, f"a book that is {why} must not produce a snapshot"

    auditor.record_would_be_order(
        _make_result(OrderStatus.FILLED, filled_size=1.0, filled_price=0.5), book=snap
    )
    row = auditor.recent()[0]
    assert row.book_json is None
    # None, not {} — "no book was obtainable" must never read back as "a book with no
    # depth". The honest NULL is itself the finding.
    assert row.get_book() is None


# ---------------------------------------------------------------------------
# Orchestrator side: the capture site
# ---------------------------------------------------------------------------

class _Strategy:
    def __init__(self, name):
        self.name = name
        self.trades_executed = 0


class _Client:
    """Stand-in for PolymarketClient exposing only what the capture uses."""

    def __init__(self, book=None, raises=None, delay=0.0):
        self._book = book
        self._raises = raises
        self._delay = delay
        self.calls = []

    def get_order_book(self, token_id):
        self.calls.append(token_id)
        if self._delay:
            time.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        return self._book


class _Scanner:
    def __init__(self, opportunities, client):
        self.strategies = [_Strategy("e11_probe")]
        self.client = client
        self._opps = opportunities

    def scan(self, market_limit=200):
        return list(self._opps)


class _Executor:
    """Paper executor stand-in that RECORDS every OrderRequest it is handed.

    The recorded requests are the evidence for the decision-neutrality test: if capture
    could influence sizing or pricing, these objects would differ.
    """

    def __init__(self):
        self.max_portfolio_usd = 1000.0
        self.total_exposure = 0.0
        self.max_per_trade_usd = 5.0
        self.positions = {}
        self.dry_run = True
        self.live_enabled = False   # real money stays gated OFF
        self.orders = []

    def execute(self, order):
        self.orders.append(order)
        return OrderResult(
            order_id=f"paper-{len(self.orders)}",
            exchange=order.exchange,
            market_id=order.market_id,
            token_id=order.token_id,
            side=order.side,
            order_type=order.order_type,
            size=order.size,
            price=order.price,
            status=OrderStatus.FILLED,
            filled_size=order.size,
            filled_price=order.price,
        )


def _opportunity(*, market_id="mkt-e11", token_id="tok-e11", edge=0.10,
                 entry_price=0.43, confidence=0.60):
    market = Market(
        id=market_id,
        condition_id=f"cond-{market_id}",
        question="Will the E11 capture stay observation-only?",
        slug="e11",
        description="",
        category="test",
        end_date=datetime.now(timezone.utc) + timedelta(days=30),
        outcomes=[Outcome(token_id=token_id, label="Yes", price=entry_price,
                          midpoint=entry_price, volume=10_000.0)],
        total_volume=10_000.0,
        liquidity=5_000.0,
        active=True,
        closed=False,
        resolved=False,
    )
    return ScanResult(
        market=market,
        strategy="e11_probe",
        outcome_idx=0,
        side="BUY",
        entry_price=entry_price,
        expected_value=1.0,
        edge=edge,
        confidence=confidence,
        reason="synthetic opportunity for the E11 capture tests",
    )


def _orchestrator(engine, client, *, capture, opportunities=None):
    opportunities = opportunities if opportunities is not None else [_opportunity()]
    executor = _Executor()
    orch = PredictionMarketOrchestrator(
        scanner=_Scanner(opportunities, client),
        executor=executor,
        # Approve-all risk + data-quality stand-ins: these gates have their own suites, and
        # holding them constant is what isolates the variable under test (capture on/off).
        risk_manager=types.SimpleNamespace(
            check_opportunity=lambda opp, ex, sc: types.SimpleNamespace(
                approved=True, reason="ok"
            ),
            record_execution=lambda result: None,
        ),
        capture_book_at_decision=capture,
    )
    orch._dq_validator = types.SimpleNamespace(
        check_market=lambda market: types.SimpleNamespace(ok=True, reason="ok")
    )
    orch._audit = AuditLogger(engine=engine)
    # Keep the test off the app's real database. Persistence is not part of the decision
    # and has its own suite (test_orchestrator_persist_fk.py).
    orch._persist_order = lambda *a, **k: None
    return orch, executor


def _run(orch):
    """Run one scan cycle on a PRIVATE event loop.

    Deliberately not ``asyncio.run``: that clears the thread's current event loop on the
    way out, and sibling suites (``test_prediction_markets.TestOrchestrator``) still call
    ``asyncio.get_event_loop().run_until_complete(...)``, which then raises "no current
    event loop" purely because of test ordering. A private loop that is never installed as
    the current one leaves that global state exactly as it found it.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(orch.scan_and_execute())
    finally:
        loop.close()


def test_capture_records_the_real_book_with_the_decision(engine):
    """The book fetched AT THE DECISION INSTANT lands on the decision's audit row.

    THIS IS THE TEST THAT FAILS ON PRE-CHANGE CODE: before E11 the orchestrator never
    fetched a book (``client.calls`` stays empty), the audit row has no ``book_json``, and
    ``PredictionAuditLog.get_book`` does not exist.
    """
    client = _Client(book=_book(best_bid=0.41, best_ask=0.43))
    orch, executor = _orchestrator(engine, client, capture=True)

    summary = _run(orch)
    assert summary["executed"] == 1

    # The capture fetched the book for the token actually being decided.
    assert client.calls == ["tok-e11"]

    row = orch._audit.recent()[0]
    stored = row.get_book()
    assert stored is not None
    assert stored["best_bid"] == 0.41 and stored["best_ask"] == 0.43
    assert stored["spread"] == pytest.approx(0.02)
    assert stored["ask_ladder"], "the ladder must be recorded, not just the touch"
    assert stored["captured_utc"], "the capture instant must be stamped"
    # And it is attached to the REAL would-be order, not a synthetic row.
    assert row.event_type == "order_filled"
    assert row.size == executor.orders[0].size


def test_capture_switchable_off(engine):
    """The switch must actually reach the venue call — off means no fetch at all."""
    client = _Client(book=_book())
    orch, _ = _orchestrator(engine, client, capture=False)

    summary = _run(orch)
    assert summary["executed"] == 1
    assert client.calls == [], "capture is off but the book was still fetched"
    assert orch._audit.recent()[0].book_json is None


def test_capture_defaults_on_and_the_env_switch_turns_it_off(monkeypatch):
    """Default ON (E11 only produces data if it runs), with an explicit off switch.

    Defaulting ON is the opposite of this repo's stance for flags that CHANGE trades
    (``enable_unvalidated_strategies``, ``use_simulation_pricer``). It is justified here
    only because capture changes no trade at all — the test above proves that — while a
    default-OFF capture would collect nothing and leave the measured capacity curve
    permanently unbuildable, since past depth cannot be recovered.
    """
    monkeypatch.delenv(orch_mod.BOOK_CAPTURE_ENV_VAR, raising=False)
    assert orch_mod._book_capture_default() is True
    for off in ("0", "false", "FALSE", "no", "off", ""):
        monkeypatch.setenv(orch_mod.BOOK_CAPTURE_ENV_VAR, off)
        assert orch_mod._book_capture_default() is False, off
    monkeypatch.setenv(orch_mod.BOOK_CAPTURE_ENV_VAR, "1")
    assert orch_mod._book_capture_default() is True
    # The bound the capture runs under is well under the scan budget, so a stalled fetch
    # can never eat a scan cycle.
    assert 0 < orch_mod.BOOK_CAPTURE_TIMEOUT_SEC <= 15.0
    assert orch_mod.BOOK_CAPTURE_TIMEOUT_SEC < PredictionMarketOrchestrator(
        scanner=None
    ).scan_interval_sec


@pytest.mark.parametrize(
    "client_kwargs, patch_timeout, why",
    [
        ({"raises": RuntimeError("clob exploded")}, None, "the fetch raises"),
        ({"raises": TimeoutError("read timeout")}, None, "the fetch times out inside the client"),
        ({"book": None}, None, "the venue served no real two-sided book (404 / one-sided)"),
        ({"book": _book(), "delay": 1.0}, 0.05, "the fetch hangs past our own wall-clock bound"),
    ],
)
def test_book_failure_records_none_and_the_scan_continues(
    engine, monkeypatch, client_kwargs, patch_timeout, why
):
    """Every failure mode records None and the scan loop keeps running.

    ``orchestrator.py`` has a known bug class where one swallowed exception blacks out
    every FUTURE scan cycle. So this asserts more than "no exception escaped": it runs a
    SECOND cycle afterwards and requires it to execute normally, which is what proves the
    loop was not killed. It also requires that nothing was fabricated in place of the
    missing book.
    """
    if patch_timeout is not None:
        # Our OWN wall-clock bound, shortened so the hang case runs fast. This is the
        # bound that protects the scan from a client that never returns.
        monkeypatch.setattr(orch_mod, "BOOK_CAPTURE_TIMEOUT_SEC", patch_timeout)

    client = _Client(**client_kwargs)
    orch, executor = _orchestrator(engine, client, capture=True)

    first = _run(orch)
    assert first["executed"] == 1, f"the decision was lost when {why}"

    # The loop is ALIVE: a second cycle still scans, sizes, and executes.
    orch.executor.positions.clear()   # undo the D8 already-held dedup for a clean re-run
    second = _run(orch)
    assert second["executed"] == 1, f"the scan loop was killed when {why}"
    assert orch.total_scans == 2

    rows = orch._audit.recent()
    assert len(rows) == 2
    for row in rows:
        assert row.event_type == "order_filled"
        # Honest NULL — no fabricated 0/1 quote, no zero-depth stand-in.
        assert row.book_json is None
        assert row.get_book() is None
    # The orders themselves were untouched by the failure.
    assert len(executor.orders) == 2
    assert executor.orders[0].size == executor.orders[1].size


def test_capture_does_not_alter_the_decision_size_or_order(engine):
    """CAPTURE IS OBSERVATION ONLY: identical decisions with capture on and off.

    Two full scan cycles over the SAME opportunity set — one with capture off, one with a
    live book being captured — must produce byte-identical decisions: the same executions
    (side, size, price, edge, Kelly bet), the same skip reasons, the same bankroll, and
    field-identical ``OrderRequest`` objects reaching the executor. If the snapshot could
    leak into sizing, pricing, or gating, one of these would move.
    """
    # Two opportunities: one that executes, one the Kelly gate sizes to zero — so the
    # comparison covers the executed AND the skipped branch.
    opps = [
        _opportunity(market_id="mkt-exec", token_id="tok-exec", edge=0.10),
        _opportunity(market_id="mkt-skip", token_id="tok-skip", edge=0.0,
                     confidence=0.60),
    ]

    off_client = _Client(book=_book())
    orch_off, exec_off = _orchestrator(
        engine, off_client, capture=False, opportunities=opps
    )
    summary_off = _run(orch_off)

    on_client = _Client(book=_book())
    orch_on, exec_on = _orchestrator(
        engine, on_client, capture=True, opportunities=opps
    )
    summary_on = _run(orch_on)

    # Guard against a tautology: the capture really did run in the second cycle.
    assert on_client.calls == ["tok-exec"]
    assert off_client.calls == []
    order_rows = [r for r in orch_on._audit.recent() if r.event_type == "order_filled"]
    assert order_rows and order_rows[0].get_book() is not None

    # The decision surface is identical.
    assert summary_on["executed"] == summary_off["executed"]
    assert summary_on["skipped"] == summary_off["skipped"]
    assert summary_on["executions"] == summary_off["executions"]
    assert summary_on["skip_reasons"] == summary_off["skip_reasons"]
    assert summary_on["bankroll_remaining"] == summary_off["bankroll_remaining"]
    assert summary_on["executions"], "the comparison would be vacuous with no executions"

    # The ORDERS are identical, field by field.
    def _fields(order):
        return (
            order.exchange, order.market_id, order.token_id, order.side,
            order.order_type, order.size, order.price, order.strategy,
            order.outcome_label,
        )

    assert [_fields(o) for o in exec_on.orders] == [_fields(o) for o in exec_off.orders]
