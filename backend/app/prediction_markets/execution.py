"""
Order Execution Layer for Prediction Markets.

Supports:
- Polymarket: via py-clob-client (Polygon/CLOB, wallet-based auth)

All execution goes through a unified interface so strategies don't
need to know the exchange internals.

IMPORTANT: Start with dry_run=True to validate logic before real money.
"""

import hashlib
import hmac
import json
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle; the name is only used in an annotation
    from .risk_manager import RiskManager

import requests

from .cost_model import DEFAULT_FEE_RATE, DEFAULT_SLIPPAGE_RATE
from .polymarket_client import (
    CLOB_API,
    Market,
    OrderBook,
    Outcome,
    PolymarketClient,
)

logger = logging.getLogger(__name__)


# LIVE-SAFETY (FACTORY_STANDARD §6): every external/venue call needs a timeout SHORTER
# than the run budget — "a graceful try/catch is useless if the runtime kills (or, here,
# HANGS) the function first." The raw REST fallback already bounds its call (`timeout=15`),
# but the py-clob-client path (`create_and_sign_order` + `post_order`) exposes NO timeout
# and hangs indefinitely on a slow/stalled socket. Because `place_order` runs SYNCHRONOUSLY
# inside the orchestrator's async scan loop, an unbounded hang freezes the ENTIRE bot (no
# kill-switch check, no further orders). This constant bounds those calls; keep it shorter
# than a scan interval. Read at call time (module global) so tests can monkeypatch it.
_CLOB_ORDER_TIMEOUT_SEC = 20.0


class _CLOBOrderTimeout(Exception):
    """A py-clob-client call exceeded `_CLOB_ORDER_TIMEOUT_SEC`.

    Distinct from a normal venue error: on a timeout the order's venue state is UNKNOWN
    (the request may or may not have reached the book), so the caller must NOT fabricate a
    fill AND must surface it loudly for reconciliation — never silently retry into a
    possible double-placement.
    """


def _call_with_timeout(fn, timeout_sec: float, label: str):
    """Run a blocking `fn()` in a daemon thread, bounded by `timeout_sec`.

    Returns fn()'s value, or re-raises whatever fn() raised. Raises `_CLOBOrderTimeout` if
    fn does not finish in time. A daemon thread is used deliberately (not
    `ThreadPoolExecutor`, whose atexit join would re-introduce the very hang we are
    bounding): if the call is genuinely wedged the worker is abandoned and cannot block
    interpreter shutdown, while the event loop is freed after at most `timeout_sec`.
    """
    box: Dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — propagate the real error to the caller
            box["error"] = exc

    t = threading.Thread(target=_target, daemon=True, name=f"clob-{label}")
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        raise _CLOBOrderTimeout(f"{label} exceeded {timeout_sec:.0f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ============================================================
# Shared Types
# ============================================================

class Exchange(Enum):
    POLYMARKET = "polymarket"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    GTC = "GTC"  # Good til cancelled (Polymarket)
    FOK = "FOK"  # Fill or kill


class OrderStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class OrderRequest:
    """Request to place an order on a prediction market."""
    exchange: Exchange
    market_id: str           # Polymarket condition_id
    token_id: str            # Polymarket token_id
    side: OrderSide
    order_type: OrderType
    size: float              # Number of contracts
    # Limit price (0.01 - 0.99). Still Optional in the SCHEMA — but no longer accepted by the
    # executor for ANY order type: `_check_risk` rejects a missing/non-positive price before
    # anything is sized, submitted or filled. The `or 0.50` fallbacks further down are the
    # unreachable remains of the old behaviour, kept only as null-safety on the venue-response
    # reconstruction path. See the guard in `_check_risk` for the reasoning.
    price: Optional[float]
    strategy: str = ""       # Strategy that generated this order
    scan_result_id: str = "" # Link back to the scan result
    market_question: str = "" # Human-readable market title
    outcome_label: str = ""  # e.g., "Yes", "No", or specific outcome

    @property
    def notional(self) -> float:
        """Estimated cost in USD."""
        p = self.price if self.price else 0.50
        return self.size * p


@dataclass
class OrderResult:
    """Result of an order placement attempt."""
    order_id: str
    exchange: Exchange
    market_id: str
    token_id: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float]
    status: OrderStatus
    filled_size: float = 0.0
    filled_price: float = 0.0
    fees: float = 0.0
    error: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_success(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    @property
    def net_cost(self) -> float:
        """Total cost including fees."""
        return self.filled_size * self.filled_price + self.fees


@dataclass
class Position:
    """A live position on an exchange."""
    exchange: Exchange
    market_id: str
    token_id: str
    market_question: str
    outcome_label: str
    side: str              # "long" or "short"
    size: float            # Number of contracts held
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    strategy: str = ""
    # Correlation-risk bucket (see market_category.py). Carried on the in-memory Position
    # so a position REHYDRATED from the DB across the fresh-process paper cycle still
    # counts against its real category — otherwise the risk manager's per-market-category
    # map is empty on a fresh process and every rehydrated position defaults to "General".
    category: str = ""
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def market_value(self) -> float:
        return self.size * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.size * self.avg_entry_price

    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl


# ============================================================
# Polymarket Executor
# ============================================================

class PolymarketExecutor:
    """
    Order execution for Polymarket via the CLOB API.

    Authentication requires:
    - A Polygon wallet (private key)
    - API key + secret + passphrase from Polymarket

    For read-only operations, no auth is needed.
    For order placement, set credentials via environment variables:
        POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        private_key: str = "",
        funder: str = "",
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.private_key = private_key
        self.funder = funder
        self._client = None  # Lazy py-clob-client ClobClient
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "LLM-Quant/1.0",
            "Accept": "application/json",
        })

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key and self.api_secret and self.passphrase)

    def _get_clob_client(self):
        """Lazy-init py-clob-client if available."""
        if self._client is not None:
            return self._client

        if not self.is_authenticated:
            raise RuntimeError(
                "Polymarket auth not configured. Set POLYMARKET_API_KEY, "
                "POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE env vars."
            )

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.passphrase,
            )
            self._client = ClobClient(
                host=CLOB_API,
                chain_id=137,  # Polygon mainnet
                key=self.private_key if self.private_key else None,
                creds=creds,
                funder=self.funder if self.funder else None,
            )
            logger.info("Polymarket CLOB client initialized")
            return self._client
        except ImportError:
            raise RuntimeError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )

    def _build_auth_headers(self, method: str, path: str, body: str = "") -> dict:
        """Build L2 authentication headers for CLOB API."""
        timestamp = str(int(time.time()))
        message = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_PASSPHRASE": self.passphrase,
        }

    def place_order(self, req: OrderRequest) -> OrderResult:
        """
        Place an order on Polymarket.

        Uses py-clob-client if available, falls back to raw CLOB API.

        DEFENSE-IN-DEPTH (ROADMAP D5/D6): even though PredictionMarketExecutor.execute()
        already enforces the live gate, PolymarketExecutor is a public class and could be
        called directly, bypassing the outer gate.  We enforce the same gate here so no
        code path can reach a real venue call when LIVE_TRADING_ENABLED is false.
        """
        # --- Fail-closed live gate (defense-in-depth) ---
        # Check the master switch at the venue layer so a direct call to
        # polymarket.place_order() cannot bypass the outer gate in execute().
        try:
            from ..config import get_settings
            _live_ok = get_settings().live_trading_enabled
        except Exception:
            _live_ok = False  # safest default: treat as disabled

        if not _live_ok:
            logger.critical(
                "[LIVE GATE / venue layer] Real order BLOCKED: "
                "LIVE_TRADING_ENABLED is false (defense-in-depth at PolymarketExecutor)."
            )
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=(
                    "LIVE_TRADING_ENABLED is false — real order blocked at venue layer "
                    "(defense-in-depth)"
                ),
            )

        try:
            client = self._get_clob_client()
        except RuntimeError:
            client = None

        if client is not None:
            return self._place_via_clob_client(client, req)
        else:
            return self._place_via_rest(req)

    def _place_via_clob_client(self, client, req: OrderRequest) -> OrderResult:
        """Place order using py-clob-client library."""
        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            side_const = BUY if req.side == OrderSide.BUY else SELL

            order_args = {
                "token_id": req.token_id,
                "price": req.price if req.price else 0.50,
                "size": req.size,
                "side": side_const,
            }

            if req.order_type == OrderType.GTC:
                order_args["expiration"] = 0  # GTC = no expiration
            elif req.order_type == OrderType.FOK:
                order_args["order_type"] = "FOK"

            # LIVE-SAFETY (§6): bound both blocking venue calls so a stalled socket cannot
            # hang the synchronous scan loop indefinitely (the REST path is already bounded
            # by `timeout=15`; py-clob-client exposes no timeout, so we bound it externally).
            timeout_sec = _CLOB_ORDER_TIMEOUT_SEC
            signed_order = _call_with_timeout(
                lambda: client.create_and_sign_order(order_args),
                timeout_sec,
                "create_and_sign_order",
            )
            resp = _call_with_timeout(
                lambda: client.post_order(signed_order),
                timeout_sec,
                "post_order",
            )

            # SIDE-EFFECT INTEGRITY (ROADMAP G2/F4.1): a reported fill must reflect a
            # REAL matched execution — never an assumed fill from a non-error response.
            # Malformed/None/non-numeric responses must → REJECTED, not a fabricated fill.
            if resp is None:
                logger.error(
                    f"Polymarket CLOB returned None response for order; "
                    f"raw resp: {resp!r}"
                )
                return OrderResult(
                    order_id=str(uuid.uuid4()),
                    exchange=Exchange.POLYMARKET,
                    market_id=req.market_id,
                    token_id=req.token_id,
                    side=req.side,
                    order_type=req.order_type,
                    size=req.size,
                    price=req.price,
                    status=OrderStatus.REJECTED,
                    error="malformed venue response",
                )

            order_id = resp.get("orderID", resp.get("id", str(uuid.uuid4())))

            # Only report FILLED when the venue explicitly says "matched" AND a valid
            # matched size > 0 is parseable.  Any other combination → OPEN (resting) or
            # REJECTED on parse failure.
            venue_status = resp.get("status")
            filled_size = 0.0
            status = OrderStatus.OPEN

            if venue_status == "matched":
                raw_matched = resp.get("matchedAmount")
                try:
                    parsed = float(raw_matched)
                except (TypeError, ValueError):
                    logger.error(
                        f"Polymarket CLOB 'matched' but matchedAmount unparseable; "
                        f"raw resp: {resp!r}"
                    )
                    return OrderResult(
                        order_id=str(uuid.uuid4()),
                        exchange=Exchange.POLYMARKET,
                        market_id=req.market_id,
                        token_id=req.token_id,
                        side=req.side,
                        order_type=req.order_type,
                        size=req.size,
                        price=req.price,
                        status=OrderStatus.REJECTED,
                        error="malformed venue response",
                        raw_response=resp,
                    )
                if parsed > 0:
                    filled_size = parsed
                    status = OrderStatus.FILLED
                # parsed == 0: venue said "matched" but amount is zero → leave OPEN

            return OrderResult(
                order_id=order_id,
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=status,
                filled_size=filled_size,
                # The submitted limit is `req.price or 0.50` (line ~308), never None — mirror
                # it so a None req.price (schema-valid) can't set filled_price=None and crash
                # the downstream market_value / PnL math after a real order was placed.
                filled_price=(req.price or 0.50) if filled_size > 0 else 0.0,
                # Charge the venue fee on the ACTUAL matched size, from the cost_model single
                # source of truth (the SAME 2% notional `_simulate_fill` charges paper). The
                # live venue methods previously left fees=0.0, so a live EXIT fill's fee never
                # reached record_realized_pnl / the hard loss caps — only the reconstructed
                # ENTRY fee did (execution.py:~1187) — so the caps + kill switch undercounted
                # the real cash loss on the LIVE path by exactly the exit fee (paper was
                # already correct: _simulate_fill sets fees). Netting it is the CONSERVATIVE
                # direction (caps trip earlier, never later) and restores paper/live symmetry.
                # (If a future venue response carries a real fee field, prefer it over this
                # estimate.) filled_size==0 → 0.0, so a resting/OPEN order books no fee.
                fees=filled_size * ((req.price or 0.50) if filled_size > 0 else 0.0) * DEFAULT_FEE_RATE,
                raw_response=resp,
            )
        except _CLOBOrderTimeout as e:
            # SIDE-EFFECT INTEGRITY + LIVE-SAFETY (§6): the call timed out, so the order's
            # venue state is UNKNOWN — it may or may not have reached the book. We must NOT
            # fabricate a fill (return REJECTED, like every other unconfirmed path here), and
            # we log CRITICAL so the ambiguous state surfaces for reconciliation rather than
            # a silent retry. (Full auto-reconciliation of a possibly-placed order is ROADMAP
            # D6, which is why LIVE_TRADING_ENABLED stays gated off until that + the runbook.)
            logger.critical(
                "[LIVE ORDER TIMEOUT] Polymarket CLOB order timed out (%s) — venue state "
                "UNKNOWN; the order may or may not have been placed. Reported REJECTED (no "
                "fabricated fill); RECONCILE the venue before re-attempting this signal.",
                e,
            )
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                # Our own message (no venue internals) — safe to surface to the caller.
                error="order placement timed out — venue state unknown; reconcile before retry",
            )
        except Exception as e:
            logger.error(f"Polymarket order failed: {e}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                # Error-message hygiene (§12): a raw exception str leaks venue internals
                # (host:port, py-clob-client stack, proxy topology) and this field flows to
                # the /prediction-markets/execute HTTP response (routes.py:479). Surface only
                # the exception TYPE — the full detail is already in the logger.error above.
                # Mirrors routes.py::_safe_conn_error, the repo's established pattern.
                error=type(e).__name__,
            )

    def _rest_rejected(self, req: OrderRequest, error: str, raw=None) -> OrderResult:
        """Build a REJECTED OrderResult for a REST order the venue did not confirm."""
        return OrderResult(
            order_id=str(uuid.uuid4()),
            exchange=Exchange.POLYMARKET,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.REJECTED,
            error=error,
            raw_response=raw,
        )

    def _place_via_rest(self, req: OrderRequest) -> OrderResult:
        """Place order using raw CLOB REST API (fallback)."""
        if not self.is_authenticated:
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error="Polymarket credentials not configured",
            )

        path = "/order"
        body = json.dumps({
            "tokenID": req.token_id,
            "price": str(req.price or 0.50),
            "size": str(req.size),
            "side": req.side.value,
            "type": "GTC" if req.order_type == OrderType.GTC else "FOK",
        })

        headers = self._build_auth_headers("POST", path, body)
        headers["Content-Type"] = "application/json"

        try:
            resp = self.session.post(
                f"{CLOB_API}{path}",
                data=body,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # SIDE-EFFECT INTEGRITY (ROADMAP G2/F4.1): an HTTP 200 is NOT proof the order
            # was accepted. The CLOB REST API returns a JSON body that can carry
            # success=false / errorMsg even on a 200. Reporting OPEN off the status code
            # alone fabricates a resting order that never existed (and would later be
            # mark-to-market'd / settled as a real position). So we VALIDATE the body:
            #   * non-dict / None body                      -> REJECTED (malformed)
            #   * explicit success=false (or an errorMsg)   -> REJECTED (venue refused)
            #   * status "matched" with a parseable size>0  -> FILLED
            #   * otherwise, a real acknowledgement (an order id / success / live status)
            #                                                -> OPEN (resting)
            #   * an acknowledgement we cannot positively confirm
            #                                                -> REJECTED (never assume a fill)
            if not isinstance(data, dict):
                logger.error(f"Polymarket REST order: malformed (non-dict) response: {data!r}")
                return self._rest_rejected(req, "malformed venue response", data)

            success = data.get("success")
            err = data.get("errorMsg") or data.get("error")
            if success is False or err:
                logger.error(f"Polymarket REST order refused by venue: {data!r}")
                return self._rest_rejected(req, f"venue refused order: {err or 'success=false'}", data)

            order_id = data.get("orderID") or data.get("orderId") or data.get("id")
            venue_status = data.get("status")

            # A terminal NEGATIVE status is a refusal even if an order id echoes back —
            # never report such an order as resting OPEN (side-effect integrity: an order
            # id alone is not acknowledgement of a live order).
            if venue_status in ("rejected", "cancelled", "canceled", "expired"):
                logger.error(f"Polymarket REST order in terminal status {venue_status!r}: {data!r}")
                return self._rest_rejected(req, f"venue order {venue_status}", data)

            # Confirmed match -> FILLED only with a FINITE matched size > 0. A non-finite
            # (inf/nan) size is malformed, not a fill.
            if venue_status == "matched":
                raw_matched = data.get("matchedAmount", data.get("size_matched"))
                try:
                    parsed = float(raw_matched)
                except (TypeError, ValueError):
                    logger.error(f"Polymarket REST 'matched' but size unparseable: {data!r}")
                    return self._rest_rejected(req, "malformed venue response", data)
                if not math.isfinite(parsed):
                    logger.error(f"Polymarket REST 'matched' but size non-finite: {data!r}")
                    return self._rest_rejected(req, "malformed venue response", data)
                if parsed > 0:
                    return OrderResult(
                        order_id=order_id or str(uuid.uuid4()),
                        exchange=Exchange.POLYMARKET,
                        market_id=req.market_id,
                        token_id=req.token_id,
                        side=req.side,
                        order_type=req.order_type,
                        size=req.size,
                        price=req.price,
                        filled_size=parsed,
                        # A limit order fills at (or better than) the limit that was actually
                        # submitted — which is `req.price or 0.50` (the SAME expression the REST
                        # body used at line ~447 / the CLOB path at line ~308), so it is never
                        # None even when req.price is None (a schema-valid GTC/FOK input).
                        # Omitting this defaulted filled_price to 0.0, so a live REST fill built
                        # a Position with avg_entry_price=0.0 (execution.py:~1090), making
                        # realized PnL = settlement*size (all gain, no cost basis) and the entry
                        # fee 0 — the hard loss caps / kill switch would then gate on inflated
                        # net PnL. (Using req.price directly would set None → a downstream
                        # TypeError in market_value math AFTER a real order placed — the exact
                        # crash the None-safe expression avoids.)
                        filled_price=req.price or 0.50,
                        # Charge the venue fee on the ACTUAL matched size from the cost_model
                        # single source of truth (the SAME 2% notional paper charges). Live
                        # fills previously left fees=0.0, so a live exit fill's fee never
                        # reached the hard loss caps (only the reconstructed entry fee did) —
                        # the caps undercounted real cash loss on the live path by exactly the
                        # exit fee. Netting it is the CONSERVATIVE direction and restores
                        # paper/live symmetry. Mirrors the CLOB path above.
                        fees=parsed * (req.price or 0.50) * DEFAULT_FEE_RATE,
                        status=OrderStatus.FILLED,
                        raw_response=data,
                    )
                # parsed == 0: venue said "matched" but zero fill -> not a fill; fall through
                # to the acknowledgement check (an order id => resting OPEN, as the CLOB path).

            # A positive acknowledgement (an order id, or success truthy, or a live/open
            # resting status) -> OPEN. Anything we cannot positively confirm -> REJECTED;
            # we never assume an order rests on a venue we couldn't confirm accepted it.
            acknowledged = bool(order_id) or success is True or venue_status in ("live", "open")
            if not acknowledged:
                logger.error(f"Polymarket REST order: unconfirmed acknowledgement: {data!r}")
                return self._rest_rejected(req, "venue did not confirm the order", data)

            return OrderResult(
                order_id=order_id or str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.OPEN,
                raw_response=data,
            )
        except requests.RequestException as e:
            logger.error(f"Polymarket REST order failed: {e}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=Exchange.POLYMARKET,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                # Error-message hygiene (§12): surface only the exception TYPE, not the raw
                # str (which leaks host:port / requests internals) — this field reaches the
                # execute HTTP response (routes.py:479). Full detail stays in the log above.
                error=type(e).__name__,
            )

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order (time-bounded — §6 live-safety).

        `client.cancel` is a py-clob-client network call with no timeout of its own, and this
        method is reached from the `/prediction-markets/cancel/{order_id}` endpoint — an
        `async def` that calls it SYNCHRONOUSLY (routes.py) — so a stalled venue socket would
        hang the ENTIRE event loop (no scan, no kill-switch check, no other request served),
        exactly the failure the order path was bounded against (#330). Bound it with the same
        helper. A timeout means the cancel is UNCONFIRMED (venue state unknown — it may or may
        not have applied), so we return False and log LOUD for reconciliation rather than
        reporting a fabricated success.
        """
        try:
            client = self._get_clob_client()
            resp = _call_with_timeout(
                lambda: client.cancel(order_id), _CLOB_ORDER_TIMEOUT_SEC, "cancel"
            )
            return resp.get("canceled", False) or resp.get("success", False)
        except _CLOBOrderTimeout as e:
            logger.critical(
                f"Polymarket cancel TIMED OUT for order {order_id}: {e} — venue state UNKNOWN; "
                "reporting UNconfirmed (not a fabricated success) for reconciliation."
            )
            return False
        except Exception as e:
            logger.error(f"Polymarket cancel failed: {e}")
            return False

    def get_open_orders(self) -> List[dict]:
        """Get all open orders."""
        try:
            client = self._get_clob_client()
            return client.get_orders() or []
        except Exception as e:
            logger.error(f"Polymarket get_orders failed: {e}")
            return []

    def get_balances(self) -> Dict[str, float]:
        """Get USDC balance on Polygon."""
        try:
            client = self._get_clob_client()
            balance = client.get_balance_allowance()
            return {"USDC": float(balance.get("balance", 0)) / 1e6}
        except Exception as e:
            logger.error(f"Polymarket balance check failed: {e}")
            return {"USDC": 0.0}


# ============================================================
# Unified Executor (routes both exchanges through one interface)
# ============================================================

class PredictionMarketExecutor:
    """
    Unified order execution for Polymarket.

    Handles:
    - Order routing to Polymarket
    - Position tracking (in-memory + DB persistence)
    - Risk checks (max position size, max portfolio exposure)
    - Dry-run mode for paper trading
    """

    def __init__(
        self,
        polymarket: Optional[PolymarketExecutor] = None,
        dry_run: bool = True,
        max_position_usd: float = 50.0,
        max_portfolio_usd: float = 500.0,
        live_enabled: Optional[bool] = None,
        max_daily_loss_usd: Optional[float] = None,
        max_total_loss_usd: Optional[float] = None,
        max_per_trade_usd: Optional[float] = None,
    ):
        self.polymarket = polymarket or PolymarketExecutor()
        self.dry_run = dry_run
        self.max_position_usd = max_position_usd
        self.max_portfolio_usd = max_portfolio_usd
        # HARD PER-TRADE NOTIONAL CEILING (ROADMAP D3). The owner-facing MAX_PER_TRADE_USD
        # setting (config.py, default $5) is a distinct, TIGHTER bound than the per-POSITION
        # cap (max_position_usd) and the cumulative portfolio cap (max_portfolio_usd): it
        # limits how much a SINGLE order may deploy. It was defined in config but read
        # NOWHERE, so setting MAX_PER_TRADE_USD silently protected nothing. Enforced at the
        # execution gate (_check_risk) when set. None DISABLES the gate — the default for
        # standalone/test/harness constructions, so their behavior is bit-identical; the
        # production singleton (get_executor) passes the real setting so a live host actually
        # honors the owner's per-trade ceiling. Raising it is HUMAN-CORE (owner-only).
        self.max_per_trade_usd = max_per_trade_usd

        # OPTIONAL per-strategy drawdown circuit (ROADMAP D2). The orchestrator sets this to
        # its RiskManager so the SELL/partial-reduce path can feed realized PnL into the
        # strategy's drawdown auto-disable (not just the executor's global hard caps). Left
        # None when the executor runs standalone (e.g. the runtime harness) — then the
        # SELL/reduce path is a safe no-op for the drawdown circuit, exactly as before.
        self.risk_manager: Optional["RiskManager"] = None

        # HARD LOSS CAPS (ROADMAP D3/D4). Default from settings (MAX_DAILY_LOSS_USD /
        # MAX_TOTAL_LOSS_USD); overridable for tests. Enforced at the execution gate
        # (_check_risk) AND they AUTO-TRIP the kill switch on breach (D4) — not just a
        # config value. Cap is on REALIZED loss (money actually lost): the safest hard
        # stop. Raising a cap is HUMAN-CORE (owner-only) — the loop never raises it.
        if max_daily_loss_usd is None or max_total_loss_usd is None:
            _cfg_daily = _cfg_total = None
            try:
                from ..config import get_settings
                _s = get_settings()
                _cfg_daily = _s.max_daily_loss_usd
                _cfg_total = _s.max_total_loss_usd
            except Exception as e:
                logger.warning(
                    "[EXECUTOR] could not read loss-cap settings; using conservative "
                    "fallbacks ($25 daily / $100 total): %s", e
                )
            # Coerce each cap independently and FAIL LOUD (not silently) on a malformed
            # env value — a misconfigured MAX_*_LOSS_USD must surface in the logs, never
            # be swallowed. The fallback is the SAFE direction (tighter caps), so a bad
            # value never loosens protection; but the owner needs to SEE that their value
            # was ignored.
            if max_daily_loss_usd is None:
                try:
                    max_daily_loss_usd = float(_cfg_daily)
                except (TypeError, ValueError):
                    if _cfg_daily is not None:
                        logger.warning(
                            "[EXECUTOR] MAX_DAILY_LOSS_USD=%r is unparseable; using "
                            "conservative fallback $25", _cfg_daily
                        )
                    max_daily_loss_usd = 25.0
            if max_total_loss_usd is None:
                try:
                    max_total_loss_usd = float(_cfg_total)
                except (TypeError, ValueError):
                    if _cfg_total is not None:
                        logger.warning(
                            "[EXECUTOR] MAX_TOTAL_LOSS_USD=%r is unparseable; using "
                            "conservative fallback $100", _cfg_total
                        )
                    max_total_loss_usd = 100.0
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_total_loss_usd = max_total_loss_usd

        # Cumulative REALIZED PnL (negative = loss). Tracked at the executor level so it
        # SURVIVES position close — total_pnl summed over open positions alone would drop
        # a closed position's realized PnL. record_realized_pnl() feeds these counters.
        self._realized_pnl_total: float = 0.0
        self._realized_pnl_daily: float = 0.0
        self._loss_cap_day = datetime.now(timezone.utc).date()

        # REAL-MONEY MASTER GATE (HUMAN-CORE). Default resolves from settings
        # (LIVE_TRADING_ENABLED, default False). When False, no real order can be
        # placed even if dry_run is False — the live branch is hard-blocked. The
        # autonomous loop never sets this True; only the owner does, per LIVE_RUNBOOK.
        if live_enabled is None:
            try:
                from ..config import get_settings
                live_enabled = bool(get_settings().live_trading_enabled)
            except Exception:
                live_enabled = False
        self.live_enabled = live_enabled

        # In-memory state
        self.positions: Dict[str, Position] = {}  # token_id -> Position
        self.order_history: List[OrderResult] = []
        self.total_fees: float = 0.0

        # Kill switch: when True, ALL order placement is blocked immediately.
        # This is the hard emergency stop — override everything, cancel all pending.
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._kill_switch_time: Optional[datetime] = None
        # Set True whenever a safety-state persist FAILS (best-effort store momentarily
        # unwritable); retried on subsequent activity so a transient outage cannot
        # permanently lose a durable kill-switch/loss record. See
        # _retry_pending_safety_persist().
        self._safety_persist_pending: bool = False

        # Durable SAFETY-state persistence (ROADMAP D3/D4 / run-risk-readiness).
        # OPT-IN: None here means no persistence and fresh in-memory state — so a bare
        # executor (tests / runtime harness) is fully isolated and deterministic. The
        # production singleton wires a real store via attach_state_store() in
        # get_executor(), which then REHYDRATES a tripped kill switch / accumulated loss
        # across restarts (a restart must not silently un-halt trading or reset the loss
        # budget). SAVE is best-effort EXCEPT on a realized LOSS: if a loss cannot be durably
        # persisted, record_realized_pnl FAILS CLOSED (halts) so a restart cannot rehydrate a
        # pre-loss row and reset the loss cap. REHYDRATE also FAILS CLOSED — if the store is
        # attached but unreadable, the executor halts rather than resume un-halted (see
        # attach_state_store).
        self._state_store = None

    @property
    def total_exposure(self) -> float:
        """Total USD exposed across all positions."""
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_pnl(self) -> float:
        """Total P&L across all positions."""
        return sum(p.total_pnl for p in self.positions.values())

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str = "manual"):
        """
        Emergency kill switch — blocks ALL new orders immediately.

        Call this on: VPIN spike, connection loss, unexpected error,
        or manual intervention. Unlike the circuit breaker in risk_manager
        (which has a cooldown), the kill switch stays active until
        explicitly deactivated.
        """
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self._kill_switch_time = datetime.now(timezone.utc)
        logger.critical(
            f"[KILL SWITCH] ACTIVATED — reason: {reason} | "
            f"Positions: {len(self.positions)} | Exposure: ${self.total_exposure:.2f}"
        )
        self._persist_state()

    def deactivate_kill_switch(self):
        """Re-enable trading after kill switch was activated."""
        was_active = self._kill_switch_active
        if was_active:
            logger.info(
                f"[KILL SWITCH] Deactivated (was active since "
                f"{self._kill_switch_time.isoformat() if self._kill_switch_time else 'unknown'})"
            )
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._kill_switch_time = None
        # Only persist on a REAL transition. A no-op deactivate (switch already off) must
        # not write — otherwise a stale process calling deactivate could overwrite another
        # process's persisted TRIP with an inactive row (reviewer A race note).
        if was_active:
            self._persist_state()

    # ------------------------------------------------------------------
    # Durable safety-state persistence (best-effort; see executor_state_store.py)
    # ------------------------------------------------------------------
    def attach_state_store(self, store) -> None:
        """Wire a durable safety-state store and REHYDRATE from it (production singleton).

        Called once on the long-lived production executor (in ``get_executor``). Loads any
        persisted kill-switch / realized-PnL state so a restart cannot silently un-trip a
        halted kill switch or reset the accumulated loss budget. FAILS CLOSED: if the store
        is attached but UNREADABLE (``_rehydrate_state`` raises — e.g. the DB is unreachable
        at startup), the executor trips its OWN kill switch (reason ``state_rehydrate_failed``)
        rather than resume with fresh, un-halted state, because it cannot confirm there was
        no persisted halt. (An ABSENT row is not a failure — the store returns ``None`` and
        the executor legitimately starts fresh.)
        """
        self._state_store = store
        try:
            self._rehydrate_state()
        except Exception as e:
            # FAIL SAFE (run-risk-readiness): a durable store is attached PRECISELY so a
            # restart cannot silently un-trip a halted kill switch or reset the loss
            # budget. If rehydration FAILS (e.g. the DB is unreachable at startup), we
            # CANNOT confirm there was no persisted halt — so we must assume the worst and
            # BLOCK trading rather than resume with fresh (un-halted) in-memory state.
            # Leaving the fresh state would let a DB hiccup at boot silently resurrect a
            # killed bot. The owner deactivates once the store is healthy again (which
            # itself requires the persisted state to be readable). We do NOT _persist_state
            # here: the store is the thing that just failed, and a halt born of an
            # unreadable store must not overwrite whatever (possibly tripped) row it holds.
            self._kill_switch_active = True
            self._kill_switch_reason = f"state_rehydrate_failed: {e}"
            self._kill_switch_time = datetime.now(timezone.utc)
            logger.critical(
                "[EXECUTOR STATE] rehydrate FAILED and is REQUIRED for safety; cannot "
                "confirm a prior kill-switch / loss state. FAILING CLOSED (kill switch "
                "ACTIVE) until the durable store is readable and the owner deactivates: %s",
                e,
            )

    def _state_snapshot(self) -> dict:
        # Both temporal fields are serialized to ISO strings (or None) so the snapshot is
        # uniformly JSON-safe; the store coerces back to a datetime column on save.
        return {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "kill_switch_time": self._kill_switch_time.isoformat() if self._kill_switch_time else None,
            "realized_pnl_total": self._realized_pnl_total,
            "realized_pnl_daily": self._realized_pnl_daily,
            "loss_cap_day": self._loss_cap_day.isoformat(),
        }

    def _rehydrate_state(self) -> None:
        """Restore persisted safety state, if any. Only ever RESTORES (never clears) a halt."""
        if self._state_store is None:
            return
        state = self._state_store.load()
        if not state:
            return
        self._kill_switch_active = bool(state.get("kill_switch_active", False))
        self._kill_switch_reason = state.get("kill_switch_reason", "") or ""
        self._kill_switch_time = state.get("kill_switch_time")
        self._realized_pnl_total = float(state.get("realized_pnl_total", 0.0))
        self._realized_pnl_daily = float(state.get("realized_pnl_daily", 0.0))
        day = state.get("loss_cap_day") or ""
        try:
            if day:
                self._loss_cap_day = date.fromisoformat(day)
        except (ValueError, TypeError):  # pragma: no cover - defensive
            pass
        # A restored daily tally is only valid for the UTC day it was recorded; if the day
        # has since rolled over, reset it (the safe direction — never carry a stale daily
        # loss into a new day, and never resurrect one for a past day).
        self._roll_daily_loss_window()
        if self._kill_switch_active:
            logger.critical(
                "[KILL SWITCH] REHYDRATED as ACTIVE from durable store — reason: %s. "
                "Trading stays halted across the restart until explicitly deactivated.",
                self._kill_switch_reason,
            )

    def _persist_state(self) -> bool:
        """Persist safety state (best-effort, never raises).

        Returns True when the state is durable — either it was SAVED, or there is no store
        attached so there is nothing to persist (the paper default). Returns False ONLY when
        an attached store's ``save`` FAILED. The boolean lets a safety-critical caller (a
        realized-LOSS update) fail CLOSED when it cannot durably record the loss; every other
        caller ignores it, so behavior there is bit-identical.
        """
        if self._state_store is None:
            return True
        try:
            self._state_store.save(self._state_snapshot())
            self._safety_persist_pending = False
            return True
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[EXECUTOR STATE] persist failed: %s", e)
            # Mark for retry: a FAILED safety-state write (e.g. a kill-switch auto-trip
            # while the store is momentarily unwritable) must be re-attempted on
            # subsequent activity, else a store recovery + restart silently loses it.
            self._safety_persist_pending = True
            return False

    def _retry_pending_safety_persist(self) -> None:
        """Re-attempt a previously-FAILED safety-state persist (durability, D3/D4).

        ``activate_kill_switch`` (and every other safety-state write) persists
        best-effort. When that write FAILS — e.g. a realized loss BREACHES a cap and
        AUTO-TRIPS the kill switch while the durable store is momentarily unwritable —
        the trip + loss counters live only in memory. If the store then RECOVERS and the
        process later restarts, ``_rehydrate_state`` loads the last GOOD (pre-trip) row
        and silently un-trips the halt / resets the loss budget: the readable-but-stale
        restart the boot-time fail-closed guard does NOT catch (the store IS readable, so
        ``_rehydrate_state`` doesn't raise). Retrying the pending write on the next order
        attempt durably records the halt the moment the store is writable again, so a
        later restart re-loads it. (A subsequent realization already self-heals via
        ``record_realized_pnl``'s own persist of the updated counters; the order-gate
        retry closes the case where a halted bot only ever REJECTS orders — the scan loop
        keeps calling ``execute`` — and never realizes again before a restart.) Idempotent
        + monotone: it only ever
        re-writes the CURRENT snapshot and never clears a halt; ``_persist_state`` clears
        the pending flag on the first success. No-op (bit-identical) when no store is
        attached or nothing is pending — the paper default never touches this path.
        """
        if self._safety_persist_pending and self._state_store is not None:
            self._persist_state()

    def _roll_daily_loss_window(self):
        """Reset the daily realized-loss tally when the UTC day rolls over."""
        today = datetime.now(timezone.utc).date()
        if today != self._loss_cap_day:
            self._loss_cap_day = today
            self._realized_pnl_daily = 0.0

    def record_realized_pnl(self, pnl: float, fees: float = 0.0):
        """Record realized PnL from a closed/reduced position and AUTO-TRIP the kill
        switch if a hard loss cap is breached (ROADMAP D3/D4).

        Call this whenever PnL is realized (a position is reduced/closed, or a market
        resolves). It accumulates the daily + total realized PnL the loss caps gate on,
        then enforces them immediately so the kill switch trips on the very trade that
        breaches the cap — not only on the next order attempt.

        ``fees`` (>= 0) is the realized TRANSACTION COST tied to this realization — the
        venue fee(s) actually paid on the round trip (the entry fill's fee, plus the exit
        fill's fee on a reduce; resolution has no exit fill so only the entry fee). It is
        SUBTRACTED so the counters — and therefore the hard loss caps + kill switch —
        gate on the TRUE net cash PnL, not the gross price move. Fees are a definite cash
        cost that ``_simulate_fill`` charges (2% of notional) and were previously tracked
        only in the reporting-only ``total_fees`` field, NEVER against the loss cap — so
        the cap undercounted the real cash loss by exactly the fees. Netting them here is
        the CONSERVATIVE direction: it can only make the cap trip EARLIER (at a slightly
        smaller gross loss), never later. ``abs()`` guards against a caller passing a
        signed fee — a fee always reduces PnL. Default 0.0 keeps every existing caller
        (and the direct-record tests) bit-identical.
        """
        net_pnl = pnl - abs(fees)
        self._roll_daily_loss_window()
        self._realized_pnl_total += net_pnl
        self._realized_pnl_daily += net_pnl
        was_tripped = self._kill_switch_active
        self._enforce_loss_caps()
        # Durably persist the updated loss counters so a restart cannot reset the
        # accumulated loss budget. If _enforce_loss_caps just AUTO-TRIPPED the kill switch,
        # activate_kill_switch() already persisted the full snapshot (counters included) —
        # skip the redundant write; otherwise persist the counter update here.
        if not (self._kill_switch_active and not was_tripped):
            persisted = self._persist_state()
            # FAIL-CLOSED (ROADMAP D3/D4 durability): a realized LOSS that could NOT be
            # durably persisted is a safety-integrity failure — on a restart, _rehydrate_state
            # would load the last GOOD row (pre-loss) and RESET the accumulated loss budget,
            # silently handing back loss headroom the cap already spent. Left running, each
            # further un-persisted loss compounds the bypass. So halt NOW via the in-memory
            # kill switch (activate_kill_switch sets _kill_switch_active before it persists, so
            # the halt holds even if that write also fails): no new order is placed this
            # session, bounding the un-persisted loss to this single realization. A profit /
            # break-even update (net_pnl >= 0) never trips — it cannot spend loss headroom.
            if net_pnl < 0 and not persisted and not self._kill_switch_active:
                self.activate_kill_switch(
                    "loss-persist failure: a realized loss could not be durably recorded — "
                    "halting so a restart cannot reset the loss cap (fail-closed)"
                )

    def _loss_cap_breach(self) -> Optional[str]:
        """Return a reason string if a daily/total realized-loss cap is breached, else
        None. Caps are on realized LOSS, so we compare the negative of realized PnL."""
        self._roll_daily_loss_window()
        if -self._realized_pnl_daily >= self.max_daily_loss_usd:
            return (
                f"DAILY loss cap: realized ${self._realized_pnl_daily:.2f} breaches "
                f"-${self.max_daily_loss_usd:.2f}"
            )
        if -self._realized_pnl_total >= self.max_total_loss_usd:
            return (
                f"TOTAL loss cap: realized ${self._realized_pnl_total:.2f} breaches "
                f"-${self.max_total_loss_usd:.2f}"
            )
        return None

    def _enforce_loss_caps(self):
        """Auto-trip the kill switch (D4) if a loss cap is breached (D3)."""
        breach = self._loss_cap_breach()
        if breach and not self._kill_switch_active:
            self.activate_kill_switch(f"loss_cap: {breach}")

    def _check_risk(self, req: OrderRequest) -> Optional[str]:
        """Pre-trade risk checks. Returns error message or None if OK."""
        # Durability self-heal (D3/D4): if a prior safety-state write (e.g. a kill-switch
        # auto-trip) could not be persisted, re-attempt it now — BEFORE admitting any new
        # order — so a recovered store durably records the halt and a later restart
        # re-loads it (never resumes trading having lost a trip). No-op on the happy path.
        self._retry_pending_safety_persist()
        # Kill switch overrides everything
        if self._kill_switch_active:
            return f"KILL SWITCH ACTIVE: {self._kill_switch_reason}"

        # SIDE-EFFECT INTEGRITY (defense-in-depth): never fill an order that has no
        # tradeable token. A multi-leg / basket opportunity (outcome_idx == -1) is skipped
        # upstream in the orchestrator, but guard HERE too so NO path can phantom-fill an
        # empty-token order through _simulate_fill (which fills unconditionally) and book a
        # meaningless empty-key position.
        if not req.token_id:
            return "empty token_id — no tradeable token (multi-leg basket not executable here)"

        # SIDE-EFFECT INTEGRITY (run-risk-readiness top_gaps): seven separate sites below —
        # `OrderRequest.notional`, `_place_via_clob_client`, `_place_via_rest`, their two fill/
        # fee reconstructions each, and `_simulate_fill` — independently substituted the SAME
        # fabricated $0.50 (`req.price or 0.50`) whenever price was falsy. Because they all
        # invented the identical number, the risk-gate notional, the submitted venue limit and
        # the paper fill stayed consistent with EACH OTHER — and all of them consistent with a
        # made-up price rather than a real one. A FILLED result and a real position came out
        # the far end.
        #
        # The guard is keyed on the MISSING PRICE, not on the order type. A first cut checked
        # `order_type == MARKET` only, on the reasoning that LIMIT/GTC/FOK "always carry an
        # explicit price". A reviewer disproved that: `PlaceOrderRequest` (api/routes.py) has
        # `order_type` defaulting to "LIMIT" and `price` defaulting to None, so the DEFAULT body
        # POSTed to /prediction-markets/execute reproduced the identical fabricated $0.50 fill —
        # the narrow guard closed the variant the orchestrator never emits and left open the one
        # its own HTTP surface emits by default. A limit order without a limit price is exactly
        # as meaningless as a market order without a book price, so both are rejected.
        #
        # Rejecting here means before `req.notional` is ever computed and before any position /
        # exposure / fee state is touched, on the paper and the (gated-off) live path alike —
        # `execute()` calls `_check_risk` ahead of the dry_run/live_enabled branch.
        #
        # A non-positive price is rejected on the same grounds: 0.0 is not a tradeable
        # prediction-market price, and every one of the seven fallback sites already treated it
        # identically to None (they test falsiness, not `is None`), so this is the existing
        # semantics made explicit rather than a new rule.
        # NaN and out-of-range are checked EXPLICITLY, not left to the falsy/<=0 test above.
        # An adversarial auditor found the reason: `not float("nan")` is False and
        # `nan <= 0.0` is False, so a NaN price slips this guard — and then EVERY downstream
        # cap comparison (`nan > 50.0`) is also False, so it slips the notional cap, the
        # per-trade cap and the max-position cap too, and books a position with `exposure=nan`
        # and `fees=nan`. That is worse than a fabricated price: it manufactures unbounded
        # risk headroom out of a single bad float. The same auditor showed a base-code
        # `price=-inf` booking NEGATIVE exposure and NEGATIVE fees, which the `<= 0.0` test
        # already closes. This hole is PRE-EXISTING and unreachable from the HTTP surface
        # (`PlaceOrderRequest` pins `ge=0.0, le=1.0, allow_inf_nan=False`), so it is latent —
        # but a guard whose whole job is "no order transacts against a price we cannot trust"
        # should not have a value it silently trusts, and the fix is one line.
        if req.price is None or not math.isfinite(req.price) or not (0.0 < req.price <= 1.0):
            return (
                f"{req.order_type.value} order rejected: no usable price "
                f"(price={req.price!r}) — refusing to fabricate, or transact against, a price "
                "that is missing, non-finite, or outside the (0, 1] range a prediction-market "
                "contract can trade in (a real price is required for every order)"
            )

        # SIDE-EFFECT INTEGRITY: on a prediction market you CANNOT open a short by
        # selling tokens you do not hold — a CTF/YES token can only be sold if it is
        # already owned. A SELL may therefore only ever REDUCE an existing long
        # position. Reject a SELL with no covering long (or one that exceeds it):
        # otherwise the paper `_simulate_fill` (which fills unconditionally) fabricates
        # a fictional ``side="short"`` position the real venue would REJECT — a phantom
        # fill (same class as the empty-token / multi-leg guards) whose broken accounting
        # then NEVER feeds the realized-PnL loss caps (a BUY "to close" the fictional
        # short scales it UP and records $0 PnL), silently bypassing the D3/D4 kill
        # switch. The scan loop reaches this whenever a default strategy emits an
        # executable SELL (e.g. CrossMarketArbitrage's exclusion/cross-market branch)
        # on an un-held token — the orchestrator's skip-held dedup guarantees any SELL
        # that reaches execution is on an un-held token. Reducing a genuinely-held long
        # (BUY then SELL) is preserved and still records PnL via the reduce branch.
        if req.side == OrderSide.SELL:
            pos = self.positions.get(req.token_id)
            covering_long = pos.size if (pos is not None and pos.side == "long") else 0.0
            if req.size > covering_long + 1e-9:
                return (
                    "SELL rejected: no covering long position for this token — cannot "
                    "open/increase a short by selling unowned tokens on a prediction "
                    "market (a SELL may only reduce a held long)"
                )

        # SIDE-EFFECT INTEGRITY (D4 named follow-up): a BUY on a token that already holds a
        # ``side="short"`` position must be REJECTED. New shorts cannot be opened (the SELL
        # guard above blocks that since #215), so a short can only ever be a LEGACY DB row
        # rehydrated from before that fix — an anomaly. `_update_position`'s BUY branch keys
        # off `req.side` assuming LONG semantics, so a BUY here would SCALE the short UP and
        # record $0 realized PnL (never feeding the D3/D4 loss caps), and a later SELL to
        # reduce it is then rejected by the guard above ("no covering long") — trapping the
        # position in a corrupted, un-closeable state. Refuse the BUY and QUARANTINE the
        # anomalous position for manual cleanup (surfaced loudly on rehydrate) rather than
        # letting the bot compound it. Paper-safe (no short is ever created in-process).
        if req.side == OrderSide.BUY:
            pos = self.positions.get(req.token_id)
            if pos is not None and getattr(pos, "side", "long") == "short":
                logger.critical(
                    "[EXEC] BUY rejected on a token holding a legacy short position "
                    "(token_id=%s, size=%s) — anomalous side='short' row; quarantined for "
                    "manual cleanup, not scaled by automated trading",
                    req.token_id, pos.size,
                )
                return (
                    "BUY rejected: token holds a legacy short position (side='short') — "
                    "quarantined anomaly (shorts cannot be opened since #215); resolve the "
                    "stale DB row manually rather than scaling it via automated trading"
                )

        # HARD LOSS CAPS (D3) enforced AT THE GATE — defense-in-depth alongside the
        # auto-trip on PnL realization. If realized losses already breach a cap, trip
        # the kill switch (D4) and reject. Caps are config-derived but ENFORCED here,
        # not merely declared.
        loss_breach = self._loss_cap_breach()
        if loss_breach:
            if not self._kill_switch_active:
                self.activate_kill_switch(f"loss_cap: {loss_breach}")
            return f"LOSS CAP: {loss_breach}"

        notional = req.notional

        # PER-TRADE ceiling (D3) — a SINGLE order can never deploy more than the owner's
        # MAX_PER_TRADE_USD. Checked before the per-position cap so the tighter bound wins
        # and the rejection message names the right ceiling. None => gate disabled.
        # The 1e-9 is float-noise tolerance on a MONEY comparison: a legitimately resized
        # order can reconstruct notional a sub-nanocent above a NON-round cap purely from
        # IEEE-754 rounding (e.g. 1.8 contracts * 0.65 == 1.17 mathematically but
        # 1.1700000000000002 in float). A real breach is >= 1 cent, so this never admits an
        # actually-oversized order — it only stops float noise from rejecting a good one.
        if self.max_per_trade_usd is not None and notional > self.max_per_trade_usd + 1e-9:
            return (
                f"Order notional ${notional:.2f} exceeds max per-trade "
                f"${self.max_per_trade_usd:.2f}"
            )

        if notional > self.max_position_usd:
            return f"Order notional ${notional:.2f} exceeds max position ${self.max_position_usd:.2f}"

        if self.total_exposure + notional > self.max_portfolio_usd:
            return (
                f"Portfolio exposure would be ${self.total_exposure + notional:.2f}, "
                f"exceeds max ${self.max_portfolio_usd:.2f}"
            )

        return None

    def execute(self, req: OrderRequest) -> OrderResult:
        """
        Execute an order with risk checks.

        In dry_run mode, simulates the fill without touching any exchange.
        """
        # Risk check
        risk_error = self._check_risk(req)
        if risk_error:
            logger.warning(f"Risk check failed: {risk_error}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=f"Risk check: {risk_error}",
            )

        if self.dry_run:
            result = self._simulate_fill(req)
        elif not self.live_enabled:
            # REAL-MONEY MASTER GATE: dry_run is off but the owner has not enabled
            # live trading. Hard-block any real order. This is the load-bearing
            # safety gate — paper is the default and the loop cannot bypass it.
            logger.critical(
                "[LIVE GATE] Real order BLOCKED: LIVE_TRADING_ENABLED is false. "
                "Set it true (owner-only, see LIVE_RUNBOOK) to place real orders."
            )
            result = OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error="LIVE_TRADING_ENABLED is false — real orders are gated off (owner-only).",
            )
        elif req.exchange == Exchange.POLYMARKET:
            result = self.polymarket.place_order(req)
        else:
            result = OrderResult(
                order_id=str(uuid.uuid4()),
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                side=req.side,
                order_type=req.order_type,
                size=req.size,
                price=req.price,
                status=OrderStatus.REJECTED,
                error=f"Unknown exchange: {req.exchange}",
            )

        # Track result
        self.order_history.append(result)
        # SIDE-EFFECT INTEGRITY (D1 class): only a REAL fill produces a position. A
        # resting/acknowledged order comes back status=OPEN with filled_size=0 (the live
        # CLOB path at ~L349 and the REST path at ~L559 both return OPEN on a non-match),
        # and `is_success` is True for OPEN — so the un-guarded `is_success` created a
        # phantom Position with size=0 / avg_entry_price=0 that (a) never traversed a real
        # fill and (b) POISONS the orchestrator's `token_id in executor.positions` dedup,
        # silently skipping every later genuine opportunity on that token (and persisting
        # the phantom across restarts via the durable store). Mutate position/fee state
        # ONLY on an actual fill; the order is still recorded in order_history above.
        # (Paper is unaffected: _simulate_fill always returns FILLED with filled_size>0.)
        if result.is_success and result.filled_size > 0:
            self._update_position(req, result)
            self.total_fees += result.fees

        return result

    def _simulate_fill(self, req: OrderRequest) -> OrderResult:
        """Simulate a fill for dry-run / paper trading mode."""
        fill_price = req.price or 0.50

        # Simulate realistic slippage for market orders. The rate is sourced from the
        # cost_model single source of truth (DEFAULT_SLIPPAGE_RATE) so the paper fill,
        # the backtest EV, and the Kelly sizer all subtract the SAME slippage — a
        # divergence here would otherwise read as false overfit. Guarded by
        # test_cost_model.test_effective_price_matches_executor_rates.
        if req.order_type == OrderType.MARKET:
            slippage = DEFAULT_SLIPPAGE_RATE
            if req.side == OrderSide.BUY:
                fill_price = min(fill_price * (1 + slippage), 0.99)
            else:
                fill_price = max(fill_price * (1 - slippage), 0.01)

        # Simulate venue fees from the cost_model single source of truth (Polymarket ~2%).
        fees = req.size * fill_price * DEFAULT_FEE_RATE

        return OrderResult(
            order_id=f"sim_{uuid.uuid4().hex[:12]}",
            exchange=req.exchange,
            market_id=req.market_id,
            token_id=req.token_id,
            side=req.side,
            order_type=req.order_type,
            size=req.size,
            price=req.price,
            status=OrderStatus.FILLED,
            filled_size=req.size,
            filled_price=fill_price,
            fees=fees,
            raw_response={"simulated": True, "dry_run": True},
        )

    def _update_position(self, req: OrderRequest, result: OrderResult):
        """Update in-memory position after a fill."""
        key = result.token_id

        if key in self.positions:
            pos = self.positions[key]
            if req.side == OrderSide.BUY:
                # Add to position
                total_cost = pos.avg_entry_price * pos.size + result.filled_price * result.filled_size
                pos.size += result.filled_size
                pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else 0
            else:
                # Reduce position
                pnl = (result.filled_price - pos.avg_entry_price) * result.filled_size
                pos.realized_pnl += pnl
                # Feed the executor-level realized-PnL counters + auto-trip the kill
                # switch if this realized loss breaches a hard cap (D3/D4). NET the
                # round-trip transaction cost so the caps gate on TRUE cash PnL: the exit
                # fill fee (result.fees, just charged on this SELL) PLUS the entry fee
                # attributable to the reduced size. The entry fee is exact — the venue fee
                # is a flat rate on notional and avg_entry_price is the recorded fill
                # price, so DEFAULT_FEE_RATE * avg_entry_price * filled_size reconstructs
                # the fee actually paid to open this many contracts. Netting fees only ever
                # trips the cap EARLIER (the conservative, safe direction).
                entry_fee = DEFAULT_FEE_RATE * pos.avg_entry_price * result.filled_size
                self.record_realized_pnl(pnl, fees=result.fees + entry_fee)
                # Feed the per-strategy DRAWDOWN circuit too (ROADMAP D2, the correctness
                # A->A+ gap the scorecard named). The RESOLUTION path (MTM engine) already
                # feeds risk_manager.record_pnl; this SELL/partial-reduce path realized PnL
                # but previously fed ONLY the executor's global hard caps, so a strategy
                # bleeding on REDUCES tripped the global kill switch but never its own
                # drawdown auto-disable. Attribute the realized PnL to the position's owning
                # strategy (pos.strategy — the alpha that opened it). No double-count: a
                # resolved position settles via the MTM engine, NOT through _update_position,
                # so each portion's PnL reaches record_pnl exactly once (reduced part here,
                # held-to-resolution remainder there). Best-effort + None-safe: a risk-manager
                # hiccup (or a standalone executor with no risk_manager) never breaks a fill.
                if self.risk_manager is not None:
                    strategy = (getattr(pos, "strategy", "") or "").strip()
                    if strategy:
                        try:
                            # Net the round-trip fee (exit fill fee + pro-rata entry fee,
                            # the same value fed to the executor caps at :1376) so the
                            # per-strategy drawdown circuit gates on TRUE net cash PnL.
                            self.risk_manager.record_pnl(
                                strategy, pnl, fees=result.fees + entry_fee
                            )
                        except Exception as e:  # pragma: no cover - defensive
                            logger.warning(
                                "[EXEC] risk_manager.record_pnl failed for %s: %s", key, e
                            )
                pos.size -= result.filled_size
                if pos.size <= 0.001:
                    # Position closed
                    del self.positions[key]
                    return
            pos.current_price = result.filled_price
            pos.unrealized_pnl = (pos.current_price - pos.avg_entry_price) * pos.size
            pos.updated_at = datetime.now(timezone.utc)
        else:
            # New position
            self.positions[key] = Position(
                exchange=req.exchange,
                market_id=req.market_id,
                token_id=req.token_id,
                market_question=req.market_question,
                outcome_label=req.outcome_label,
                side="long" if req.side == OrderSide.BUY else "short",
                size=result.filled_size,
                avg_entry_price=result.filled_price,
                current_price=result.filled_price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                strategy=req.strategy,
            )

    def cancel_order(self, order_id: str, exchange: Exchange) -> bool:
        """Cancel an order on the specified exchange."""
        if self.dry_run:
            return True
        if exchange == Exchange.POLYMARKET:
            return self.polymarket.cancel_order(order_id)
        return False

    def get_portfolio_summary(self) -> dict:
        """Get a summary of all positions and P&L."""
        positions_list = []
        for pos in self.positions.values():
            positions_list.append({
                "exchange": pos.exchange.value,
                "market_id": pos.market_id,
                "token_id": pos.token_id,
                "market_question": pos.market_question,
                "outcome_label": pos.outcome_label,
                "side": pos.side,
                "size": pos.size,
                "avg_entry_price": pos.avg_entry_price,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "total_pnl": pos.total_pnl,
                "strategy": pos.strategy,
                "opened_at": pos.opened_at.isoformat(),
            })

        return {
            "total_positions": len(self.positions),
            "total_exposure": self.total_exposure,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "total_orders": len(self.order_history),
            "dry_run": self.dry_run,
            "positions": positions_list,
        }

    def get_order_history(self, limit: int = 50) -> List[dict]:
        """Get recent order history."""
        return [
            {
                "order_id": o.order_id,
                "exchange": o.exchange.value,
                "market_id": o.market_id,
                "token_id": o.token_id,
                "side": o.side.value,
                "order_type": o.order_type.value,
                "size": o.size,
                "price": o.price,
                "status": o.status.value,
                "filled_size": o.filled_size,
                "filled_price": o.filled_price,
                "fees": o.fees,
                "error": o.error,
                "timestamp": o.timestamp.isoformat(),
            }
            for o in reversed(self.order_history[-limit:])
        ]


# ============================================================
# Singleton accessor
# ============================================================

_executor: Optional[PredictionMarketExecutor] = None


def get_executor(
    dry_run: bool = True,
    max_position_usd: float = 50.0,
    max_portfolio_usd: float = 500.0,
    max_per_trade_usd: Optional[float] = None,
) -> PredictionMarketExecutor:
    """Get or create the global prediction market executor."""
    global _executor
    if _executor is None:
        import os

        # Per-trade notional ceiling: read the owner's MAX_PER_TRADE_USD (config default
        # $5) so the setting is ENFORCED on the production path, not left inert. Fail LOUD
        # on a malformed value in the SAFE direction (conservative $5 fallback, never
        # looser). None here means "resolve from settings" — an explicit caller value wins.
        if max_per_trade_usd is None:
            try:
                from ..config import get_settings
                _cfg_per_trade = get_settings().max_per_trade_usd
                try:
                    max_per_trade_usd = float(_cfg_per_trade)
                except (TypeError, ValueError):
                    if _cfg_per_trade is not None:
                        logger.warning(
                            "[EXECUTOR] MAX_PER_TRADE_USD=%r is unparseable; using "
                            "conservative fallback $5", _cfg_per_trade
                        )
                    max_per_trade_usd = 5.0
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(
                    "[EXECUTOR] could not read MAX_PER_TRADE_USD setting; using "
                    "conservative fallback $5: %s", e
                )
                max_per_trade_usd = 5.0

        poly = PolymarketExecutor(
            api_key=os.environ.get("POLYMARKET_API_KEY", ""),
            api_secret=os.environ.get("POLYMARKET_API_SECRET", ""),
            passphrase=os.environ.get("POLYMARKET_PASSPHRASE", ""),
            private_key=os.environ.get("POLYMARKET_PRIVATE_KEY", ""),
            funder=os.environ.get("POLYMARKET_FUNDER", ""),
        )
        _executor = PredictionMarketExecutor(
            polymarket=poly,
            dry_run=dry_run,
            max_position_usd=max_position_usd,
            max_portfolio_usd=max_portfolio_usd,
            max_per_trade_usd=max_per_trade_usd,
        )
        # Wire durable safety-state persistence onto the production singleton and
        # rehydrate (run-risk-readiness). Best-effort + lazy import (same dual-import
        # discipline as the audit log / registry store): a persistence problem can never
        # break executor construction. In CI the DB is an empty ephemeral SQLite, so this
        # loads nothing and the executor is fresh + deterministic.
        try:
            from .executor_state_store import ExecutorStateStore, _NoOpExecutorStateStore
            try:
                _executor.attach_state_store(ExecutorStateStore())
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("[EXECUTOR STATE] store init failed, using no-op: %s", e)
                _executor.attach_state_store(_NoOpExecutorStateStore())
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[EXECUTOR STATE] persistence unavailable: %s", e)

        # Rehydrate OPEN positions from the durable store (ROADMAP D8). The
        # scheduled paper cycle runs as a FRESH PROCESS each run; without this,
        # `executor.positions` starts empty every run, so positions opened in a
        # prior run are ORPHANED in the DB and `check_resolutions` (which reads
        # in-memory `executor.positions`) never settles them → realized PnL never
        # books and the forward record can't progress. Runs AFTER the state-store
        # attach so a rehydrated position sees the restored kill-switch/loss
        # counters. Best-effort + lazy import (persistence imports execution, so a
        # module-level import would be circular): a persistence problem can never
        # break executor construction. In CI the DB is an empty ephemeral SQLite,
        # so this loads nothing and the executor stays fresh + deterministic.
        try:
            from . import persistence
            persistence.load_positions_into_executor(_executor)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[EXECUTOR STATE] position rehydrate skipped: %s", e)
    return _executor
