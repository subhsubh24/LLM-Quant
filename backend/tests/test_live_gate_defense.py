"""
Tests for defense-in-depth live gate + side-effect integrity hardening.

ROADMAP D5/D6/G2/F4.1

Coverage:
  - D5/D6: PolymarketExecutor.place_order() enforces LIVE_TRADING_ENABLED=false at the
    VENUE layer (both CLOB-client path and REST-fallback path), so a direct call that
    bypasses PredictionMarketExecutor.execute() is still fail-closed.
  - G2/F4.1: _place_via_clob_client rejects malformed/None/non-numeric venue responses
    instead of fabricating a fill.
  - REGRESSION: the outer gate in PredictionMarketExecutor.execute() still blocks real
    orders when live_enabled=False, and paper/dry-run still fills normally.

All tests are deterministic and make no network calls.
"""

import sys
import os
import types
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend root is on sys.path (mirrors conftest.py)
backend_root = os.path.join(os.path.dirname(__file__), "..")
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.prediction_markets.execution import (
    Exchange,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PolymarketExecutor,
    PredictionMarketExecutor,
)
from app.prediction_markets.cost_model import DEFAULT_FEE_RATE


# ---------------------------------------------------------------------------
# py_clob_client stub
# ---------------------------------------------------------------------------
# py_clob_client is not installed in this environment. Tests that exercise
# _place_via_clob_client() directly call it with a mock client object, but the
# function's first line attempts `from py_clob_client.order_builder.constants import
# BUY, SELL`. We register lightweight stubs in sys.modules so that import succeeds
# and the rest of the function body (the logic under test) can run.

def _install_clob_stubs():
    """Register minimal py_clob_client stubs so the in-function import doesn't fail."""
    if "py_clob_client" not in sys.modules:
        pkg = types.ModuleType("py_clob_client")
        ob = types.ModuleType("py_clob_client.order_builder")
        constants = types.ModuleType("py_clob_client.order_builder.constants")
        constants.BUY = "BUY"
        constants.SELL = "SELL"
        pkg.order_builder = ob
        ob.constants = constants
        sys.modules["py_clob_client"] = pkg
        sys.modules["py_clob_client.order_builder"] = ob
        sys.modules["py_clob_client.order_builder.constants"] = constants

_install_clob_stubs()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(
    size: float = 10.0,
    price: float = 0.50,
    side: OrderSide = OrderSide.BUY,
) -> OrderRequest:
    return OrderRequest(
        exchange=Exchange.POLYMARKET,
        market_id="market-test",
        token_id="token-test",
        side=side,
        order_type=OrderType.LIMIT,
        size=size,
        price=price,
        strategy="test",
        market_question="Test market?",
        outcome_label="Yes",
    )


def _poly_executor() -> PolymarketExecutor:
    """Return a PolymarketExecutor with dummy credentials so is_authenticated=True."""
    return PolymarketExecutor(
        api_key="key",
        api_secret="secret",
        passphrase="pass",
        private_key="0x" + "a" * 64,
    )


# ---------------------------------------------------------------------------
# D5/D6  Venue-layer live gate
# ---------------------------------------------------------------------------

class TestVenueLiveGate:
    """PolymarketExecutor.place_order() must reject when LIVE_TRADING_ENABLED is false,
    regardless of whether the CLOB client path or the REST-fallback path would be used."""

    def test_place_order_rejected_clob_path_when_live_disabled(self):
        """
        CLOB-client path: even when _get_clob_client() would succeed, place_order()
        must return REJECTED before reaching _place_via_clob_client().
        """
        poly = _poly_executor()

        # Patch get_settings so live_trading_enabled is False
        fake_settings = MagicMock()
        fake_settings.live_trading_enabled = False

        with patch(
            "app.prediction_markets.execution.PolymarketExecutor.place_order",
            wraps=poly.place_order,
        ):
            with patch(
                "app.config.get_settings",
                return_value=fake_settings,
            ):
                result = poly.place_order(_req())

        assert result.status == OrderStatus.REJECTED, (
            f"Expected REJECTED, got {result.status}; error={result.error!r}"
        )
        assert result.error is not None
        assert "LIVE_TRADING_ENABLED" in result.error
        assert "defense-in-depth" in result.error

    def test_place_order_rejected_rest_path_when_live_disabled(self):
        """
        REST-fallback path: force _get_clob_client() to raise (simulating missing lib),
        so _place_via_rest() would be called — but the live gate must fire first.
        """
        poly = _poly_executor()

        fake_settings = MagicMock()
        fake_settings.live_trading_enabled = False

        with patch.object(
            poly,
            "_get_clob_client",
            side_effect=RuntimeError("py-clob-client not available"),
        ):
            with patch(
                "app.config.get_settings",
                return_value=fake_settings,
            ):
                result = poly.place_order(_req())

        assert result.status == OrderStatus.REJECTED
        assert result.error is not None
        assert "LIVE_TRADING_ENABLED" in result.error
        assert "defense-in-depth" in result.error

    def test_place_order_rejected_when_get_settings_raises(self):
        """
        If get_settings() itself raises (misconfiguration), we must default to False
        (fail-closed) and reject — never proceed to a real order.
        """
        poly = _poly_executor()

        with patch(
            "app.config.get_settings",
            side_effect=RuntimeError("settings unavailable"),
        ):
            result = poly.place_order(_req())

        assert result.status == OrderStatus.REJECTED
        assert result.error is not None
        assert "LIVE_TRADING_ENABLED" in result.error

    def test_place_order_proceeds_when_live_enabled(self):
        """
        When live_trading_enabled=True, place_order() must NOT be blocked by the
        venue gate itself — it should proceed to the client/rest paths.
        We verify the gate doesn't fire by confirming _place_via_clob_client is called.
        """
        poly = _poly_executor()

        fake_settings = MagicMock()
        fake_settings.live_trading_enabled = True

        # Patch _place_via_clob_client to return a known result without network
        dummy_result = OrderResult(
            order_id="live-order-001",
            exchange=Exchange.POLYMARKET,
            market_id="market-test",
            token_id="token-test",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=10.0,
            price=0.50,
            status=OrderStatus.OPEN,
        )

        with patch(
            "app.config.get_settings",
            return_value=fake_settings,
        ):
            with patch.object(
                poly,
                "_place_via_clob_client",
                return_value=dummy_result,
            ) as mock_clob:
                # Force CLOB client to be non-None
                poly._client = MagicMock()
                result = poly.place_order(_req())

        mock_clob.assert_called_once()
        assert result.status == OrderStatus.OPEN


# ---------------------------------------------------------------------------
# G2/F4.1  Side-effect integrity — malformed venue response handling
# ---------------------------------------------------------------------------

class TestMalformedVenueResponse:
    """_place_via_clob_client must reject rather than fabricate fills when the venue
    response is malformed, None, or contains a non-numeric matchedAmount."""

    def _call_clob(self, resp_dict) -> OrderResult:
        """Helper: call _place_via_clob_client with a mocked client that returns resp_dict."""
        poly = _poly_executor()
        mock_client = MagicMock()
        mock_client.create_and_sign_order.return_value = MagicMock()
        mock_client.post_order.return_value = resp_dict
        return poly._place_via_clob_client(mock_client, _req())

    def test_none_response_is_rejected(self):
        """A None response from the CLOB must produce REJECTED, not a crash or fake fill."""
        result = self._call_clob(None)
        assert result.status == OrderStatus.REJECTED
        assert "malformed venue response" in (result.error or "")
        assert result.filled_size == 0.0

    def test_string_matched_amount_is_rejected(self):
        """matchedAmount='bad' (non-numeric string) with status='matched' → REJECTED."""
        result = self._call_clob({"status": "matched", "matchedAmount": "bad"})
        assert result.status == OrderStatus.REJECTED
        assert "malformed venue response" in (result.error or "")
        assert result.filled_size == 0.0

    def test_none_matched_amount_with_matched_status_is_rejected(self):
        """matchedAmount=None with status='matched' → REJECTED (not filled_size=0 OPEN)."""
        result = self._call_clob({"status": "matched", "matchedAmount": None})
        assert result.status == OrderStatus.REJECTED
        assert "malformed venue response" in (result.error or "")
        assert result.filled_size == 0.0

    def test_valid_matched_response_produces_fill(self):
        """A well-formed 'matched' response with numeric matchedAmount → FILLED."""
        result = self._call_clob(
            {"status": "matched", "matchedAmount": 10.0, "orderID": "order-abc"}
        )
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == pytest.approx(10.0)
        assert result.filled_price == pytest.approx(0.50)  # req.price
        assert result.order_id == "order-abc"

    def test_non_matched_status_does_not_fabricate_fill(self):
        """A response with status != 'matched' (e.g. 'live') → OPEN with filled_size=0."""
        result = self._call_clob(
            {"status": "live", "matchedAmount": "5.0", "orderID": "order-xyz"}
        )
        # Should not be FILLED and filled_size must be 0 — no real match occurred
        assert result.status == OrderStatus.OPEN
        assert result.filled_size == 0.0

    def test_zero_matched_amount_does_not_report_fill(self):
        """matchedAmount=0 with status='matched' → OPEN, not FILLED (no actual fill)."""
        result = self._call_clob(
            {"status": "matched", "matchedAmount": 0, "orderID": "order-zero"}
        )
        assert result.status == OrderStatus.OPEN
        assert result.filled_size == 0.0


# ---------------------------------------------------------------------------
# Regression: outer gate + paper/dry-run untouched
# ---------------------------------------------------------------------------

class TestRegressionOuterGateAndPaper:
    """Prove the existing PredictionMarketExecutor.execute() gate still works AND
    paper/dry-run is completely unaffected by the new venue-layer gate."""

    def test_outer_execute_gate_still_blocks_real_order(self):
        """
        PredictionMarketExecutor.execute() with dry_run=False, live_enabled=False
        must still REJECT — the outer gate must not have been removed.
        """
        ex = PredictionMarketExecutor(
            dry_run=False,
            live_enabled=False,
            max_position_usd=50.0,
            max_portfolio_usd=500.0,
        )
        result = ex.execute(_req())
        assert result.status == OrderStatus.REJECTED
        assert result.error is not None
        assert "LIVE_TRADING_ENABLED" in result.error

    def test_paper_dry_run_fills_normally(self):
        """
        Paper/dry-run: execute() with dry_run=True must FILL normally.
        The dry_run path goes through _simulate_fill(), never calls
        PolymarketExecutor.place_order(), so the venue-layer gate is never reached.
        """
        ex = PredictionMarketExecutor(
            dry_run=True,
            max_position_usd=50.0,
            max_portfolio_usd=500.0,
        )
        result = ex.execute(_req(size=10.0, price=0.50))
        assert result.status == OrderStatus.FILLED, (
            f"Paper order should fill; got {result.status}, error={result.error!r}"
        )
        assert result.filled_size == pytest.approx(10.0)
        assert result.filled_price > 0.0
        # Position must be tracked
        assert len(ex.positions) == 1


class TestOpenOrderCreatesNoPhantomPosition:
    """SIDE-EFFECT INTEGRITY (D1 class): a resting/acknowledged live order returns
    status=OPEN with filled_size=0. `is_success` is True for OPEN, so the executor used
    to fabricate a phantom size=0/avg_entry_price=0 Position that poisons the orchestrator
    `token_id in executor.positions` dedup — silently skipping every later real
    opportunity on that token. execute() must record the order in history but create NO
    position until a real (partial or full) fill occurs.
    """

    def _live_executor(self, venue_result):
        """A live-enabled executor whose venue place_order returns `venue_result`."""
        fake_poly = MagicMock()
        fake_poly.place_order.return_value = venue_result
        return PredictionMarketExecutor(
            polymarket=fake_poly,
            dry_run=False,
            live_enabled=True,
            max_position_usd=50.0,
            max_portfolio_usd=500.0,
        )

    def _open_result(self, req):
        return OrderResult(
            order_id="resting-001",
            exchange=Exchange.POLYMARKET,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.OPEN,   # accepted, not yet matched
            filled_size=0.0,
            filled_price=0.0,
        )

    def test_open_order_creates_no_phantom_position(self):
        req = _req(size=10.0, price=0.50)
        ex = self._live_executor(self._open_result(req))

        result = ex.execute(req)

        # The venue accepted the order (OPEN) and it is recorded in history...
        assert result.status == OrderStatus.OPEN
        assert result in ex.order_history
        # ...but a 0-fill OPEN order is NOT a position — no phantom, no poisoned dedup.
        assert ex.positions == {}, (
            f"Phantom position fabricated from a 0-fill OPEN order: {ex.positions!r}"
        )
        assert req.token_id not in ex.positions
        assert ex.total_fees == 0.0

    def test_dedup_not_poisoned_second_real_opportunity_can_execute(self):
        """The concrete downstream harm: after a 0-fill OPEN order, a later REAL fill on
        the SAME token must still create the position (the dedup was not poisoned)."""
        req = _req(size=10.0, price=0.50)
        ex = self._live_executor(self._open_result(req))
        ex.execute(req)
        assert req.token_id not in ex.positions

        # A subsequent genuine fill on the same token now arrives.
        filled = OrderResult(
            order_id="fill-002",
            exchange=Exchange.POLYMARKET,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.FILLED,
            filled_size=10.0,
            filled_price=0.50,
        )
        ex.polymarket.place_order.return_value = filled
        ex.execute(req)

        assert req.token_id in ex.positions
        assert ex.positions[req.token_id].size == pytest.approx(10.0)
        assert ex.positions[req.token_id].avg_entry_price == pytest.approx(0.50)

    def test_real_fill_still_creates_position(self):
        """Control: the guard must NOT block a genuine fill (filled_size>0)."""
        req = _req(size=10.0, price=0.50)
        filled = OrderResult(
            order_id="fill-001",
            exchange=Exchange.POLYMARKET,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.FILLED,
            filled_size=10.0,
            filled_price=0.50,
        )
        ex = self._live_executor(filled)
        ex.execute(req)
        assert req.token_id in ex.positions
        assert ex.positions[req.token_id].size == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# D3/D4  Live fills charge the venue fee (so the hard loss caps net it)
# ---------------------------------------------------------------------------

class TestLiveFillChargesVenueFee:
    """The live venue methods (_place_via_clob_client / _place_via_rest) must populate
    OrderResult.fees on a real fill — the SAME cost-model fee paper's _simulate_fill
    charges. Before this fix they left fees=0.0, so a live EXIT fill's fee never reached
    record_realized_pnl (execution.py:~1188 nets result.fees + reconstructed entry_fee) —
    only the entry fee was netted, and the hard loss caps + kill switch undercounted the
    real cash loss on the LIVE path by exactly the exit fee.

    The three `*_charges_*_fee` tests FAIL on pre-fix code (a live matched fill would carry
    fees=0.0); `test_clob_open_order_books_no_fee` is a control (0 fee was always correct
    for a non-fill). The end-to-end loss-counter netting is covered separately via the
    public execute() path in test_loss_cap_fees.py::test_reduce_loss_nets_entry_and_exit_fees."""

    def _call_clob(self, resp_dict, req=None) -> OrderResult:
        poly = _poly_executor()
        mock_client = MagicMock()
        mock_client.create_and_sign_order.return_value = MagicMock()
        mock_client.post_order.return_value = resp_dict
        return poly._place_via_clob_client(mock_client, req or _req())

    def _call_rest(self, data_dict, req=None) -> OrderResult:
        poly = _poly_executor()
        poly.session = MagicMock()
        http_resp = MagicMock()
        http_resp.raise_for_status.return_value = None
        http_resp.json.return_value = data_dict
        poly.session.post.return_value = http_resp
        return poly._place_via_rest(req or _req())

    def test_clob_matched_fill_charges_cost_model_fee(self):
        """A CLOB 'matched' fill of 10 @ $0.50 charges 10*0.50*DEFAULT_FEE_RATE, not 0."""
        result = self._call_clob(
            {"status": "matched", "matchedAmount": 10.0, "orderID": "order-fee"}
        )
        assert result.status == OrderStatus.FILLED
        expected = 10.0 * 0.50 * DEFAULT_FEE_RATE
        assert result.fees == pytest.approx(expected)
        assert result.fees > 0.0  # the pre-fix bug: fees defaulted to 0.0

    def test_clob_open_order_books_no_fee(self):
        """A resting/OPEN order (no match) must NOT book a fee — filled_size==0 → fees==0."""
        result = self._call_clob(
            {"status": "matched", "matchedAmount": 0, "orderID": "order-open"}
        )
        assert result.status == OrderStatus.OPEN
        assert result.filled_size == 0.0
        assert result.fees == pytest.approx(0.0)

    def test_clob_fee_scales_with_matched_size_and_price(self):
        """Fee is on the ACTUAL matched size at the fill price (partial fill / other price)."""
        result = self._call_clob(
            {"status": "matched", "matchedAmount": 7.0, "orderID": "order-part"},
            req=_req(size=10.0, price=0.30),
        )
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == pytest.approx(7.0)
        assert result.fees == pytest.approx(7.0 * 0.30 * DEFAULT_FEE_RATE)

    def test_rest_matched_fill_charges_cost_model_fee(self):
        """The REST fallback path must also charge the venue fee on a real match."""
        result = self._call_rest(
            {"status": "matched", "matchedAmount": 10.0, "orderID": "rest-fee"}
        )
        assert result.status == OrderStatus.FILLED
        assert result.fees == pytest.approx(10.0 * 0.50 * DEFAULT_FEE_RATE)
        assert result.fees > 0.0
