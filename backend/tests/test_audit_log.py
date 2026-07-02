"""
Tests for the durable prediction-market audit log (ROADMAP G3 / OA-10).

Deterministic, in-memory SQLite, no network. Verifies that decisions and
would-be orders are persisted, that an order row reflects the REAL OrderResult
(filled vs rejected vs gated — never a fabricated success), and that all writes
are best-effort (a DB failure never raises into the caller).
"""

import pytest
from sqlmodel import create_engine

from app.prediction_markets.audit_log import (
    AuditLogger,
    PredictionAuditLog,
    init_db,
)
from app.prediction_markets.execution import (
    Exchange,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
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
